"""Run the portable headless backend executable."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import socket
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

if __package__ in (None, "") and not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.user_settings import (
    UserSettingsError,
    initialize_port_settings,
    load_port_mapping,
    settings_file_path,
)
from backend.network import lan_urls


class RunError(RuntimeError):
    """Raised when the portable application cannot start or keep running."""


def runtime_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1] / "dist"


def load_environment(root: Path) -> None:
    os.environ["CONNECTOR_RUNTIME_ROOT"] = str(root.resolve())
    load_dotenv(root / ".env", override=False, encoding="utf-8-sig")
    for name in (
        "DATA_DIR", "DB_PATH", "CONFIG_PATH", "PLUGIN_DIR", "RESPONSE_LOG_DIR",
        "AGENT_PYTHON_ENV_DIR", "AGENT_PYTHON_ENVS_DIR", "JOBS_DIR",
        "CONNECTOR_SETTINGS_PATH", "SETTINGS_PATH", "CONNECTOR_PYTHON_EXECUTABLE",
    ):
        configured = os.environ.get(name)
        if configured is None:
            continue
        if not configured.strip():
            os.environ.pop(name)
            continue
        path = Path(os.path.expandvars(configured.strip())).expanduser()
        if not path.is_absolute():
            path = root / path
        os.environ[name] = str(path.resolve())


def runtime_host(root: Path) -> str:
    profile_path = root / "runtime.json"
    if not profile_path.exists():
        return "0.0.0.0"
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RunError(f"Cannot read runtime profile at {profile_path}: {error}") from error
    if not isinstance(profile, dict) or profile.get("host") not in ("127.0.0.1", "0.0.0.0"):
        raise RunError(
            f"Invalid runtime profile at {profile_path}: host must be 127.0.0.1 or 0.0.0.0"
        )
    return profile["host"]


def port_number(value: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def parse_args(
    argv: list[str] | None = None, *, default_host: str = "0.0.0.0",
    defaults_path: Path | None = None,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend", "--backend-port", "--port", dest="backend_port", type=port_number,
        help="backend port (default: settings.json connector_port or port_mapping.json)",
    )
    parser.add_argument(
        "--host", default=default_host,
        help=f"bind address (default: {default_host})",
    )
    parser.add_argument(
        "--completion-no-database-access", action="store_true",
        help="Serve completions without database access, saved memory, or response persistence",
    )
    parser.add_argument(
        "--initialize-settings", action="store_true",
        help="Create user preferences if missing, populate missing ports, and exit",
    )
    return parser.parse_args(argv)


def bind_listener(host: str, port: int, label: str) -> socket.socket:
    last_error: OSError | None = None
    for family, kind, protocol, _, address in socket.getaddrinfo(
        host, port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE,
    ):
        listener = socket.socket(family, kind, protocol)
        try:
            if os.name == "nt":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(address)
            listener.listen(socket.SOMAXCONN)
            listener.setblocking(False)
            return listener
        except OSError as error:
            listener.close()
            last_error = error
    raise RunError(
        f"Cannot bind {label} to {host}:{port}; choose another port or close "
        f"the service using it. {last_error}"
    ) from last_error


def listener_url(listener: socket.socket) -> str:
    host, port = listener.getsockname()[:2]
    if host == "0.0.0.0":
        host = "127.0.0.1"
    elif host == "::":
        host = "::1"
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{port}"


def main(argv: list[str] | None = None) -> int:
    root = runtime_directory()
    load_environment(root)
    defaults_path = root / "port_mapping.json"
    host = runtime_host(root)
    args = parse_args(argv, default_host=host, defaults_path=defaults_path)

    if args.initialize_settings:
        initialize_port_settings(defaults_path=defaults_path)
        return 0

    if args.completion_no_database_access:
        os.environ["COMPLETION_NO_DATABASE_ACCESS"] = "true"

    preferences = initialize_port_settings(defaults_path=defaults_path)
    backend_port = args.backend_port or preferences.get("connector_port") or preferences.get("backend_port", 8301)

    from backend.app.main import app as backend_app

    backend_listener = bind_listener(args.host, backend_port, "backend")
    backend_url = listener_url(backend_listener)
    lan_urls_list = lan_urls(backend_listener)

    print("=" * 64)
    print("The Connector Headless API Server")
    print(f"Backend:  {backend_url} (API docs: {backend_url}/docs)")
    for lan_url in lan_urls_list:
        print(f"LAN API:  {lan_url}/docs")
    print("Press Ctrl+C to stop. No UI started.")
    print("=" * 64, flush=True)

    config = uvicorn.Config(backend_app, log_level="info", access_log=False)
    server = uvicorn.Server(config)
    try:
        asyncio.run(server.serve(sockets=[backend_listener]))
    finally:
        backend_listener.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RunError, UserSettingsError) as error:
        print(f"[run] ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
