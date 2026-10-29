#!/usr/bin/env python3
"""Run The Connector Headless API Server (backend only, no UI)."""

from __future__ import annotations

import argparse
import errno
import os
from pathlib import Path
import socket
import subprocess
import sys

from backend.network import lan_urls_for_host
from backend.app.user_settings import UserSettingsError, initialize_port_settings

ROOT = Path(__file__).resolve().parent
LOCAL_PYTHON = ROOT / ".venv" / (
    "Scripts/python.exe" if os.name == "nt" else "bin/python"
)


class RunError(RuntimeError):
    """Raised when the application cannot be started."""


def in_active_environment() -> bool:
    return (
        sys.prefix != getattr(sys, "base_prefix", sys.prefix)
        or bool(os.environ.get("VIRTUAL_ENV"))
        or bool(os.environ.get("CONDA_PREFIX"))
    )


def load_env_file(root: Path | None = None) -> None:
    root = root or ROOT
    env_file = root / ".env"
    if not env_file.is_file():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file, override=False)
    except ImportError:
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def select_runtime() -> Path:
    if in_active_environment():
        return Path(sys.executable)
    if LOCAL_PYTHON.is_file():
        return LOCAL_PYTHON
    setup_script = ROOT / "setup.py"
    if setup_script.is_file():
        print("[run] No active environment or local .venv; running setup...")
        if subprocess.call([sys.executable, str(setup_script)], cwd=ROOT):
            raise RunError("Setup failed")
    if not LOCAL_PYTHON.is_file():
        raise RunError(f"Python environment not found at {LOCAL_PYTHON}")
    return LOCAL_PYTHON


def parse_port(value: str | int, label: str = "port") -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as error:
        raise RunError(f"{label} must be an integer") from error
    if not 1 <= port <= 65535:
        raise RunError(f"{label} must be between 1 and 65535")
    return port


def resolve_host(host: str) -> tuple[int, str]:
    try:
        addresses = socket.getaddrinfo(host, 0, type=socket.SOCK_STREAM)
    except OSError as error:
        raise RunError(f"Cannot resolve bind address {host!r}: {error}") from error
    family, _, _, _, address = addresses[0]
    return family, address[0]


def available_port(
    start: int, reserved: set[int] | None = None, *,
    host: str = "127.0.0.1", family: int = socket.AF_INET,
) -> int:
    reserved = reserved or set()
    for port in range(start, 65536):
        if port in reserved:
            continue
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            try:
                if os.name == "nt":
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                probe.bind((host, port))
            except OSError as error:
                if error.errno in (errno.EADDRINUSE, errno.EACCES):
                    continue
                raise RunError(f"Cannot bind to {host}:{port}: {error}") from error
        return port
    raise RunError(f"No available TCP port was found at or above {start}")


def service_url(host: str, port: int) -> str:
    host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
    if ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{port}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    hosts = parser.add_mutually_exclusive_group()
    hosts.add_argument("--host", help="Bind address (default: BACKEND_HOST, HOST, or 0.0.0.0)")
    hosts.add_argument("--local", action="store_true", help="Bind only to 127.0.0.1")
    parser.add_argument("--port", type=int, help="First listen port to try (default: settings.json connector_port, initialized from port_mapping.json)")
    parser.add_argument("--backend-port", type=int, dest="port", help=argparse.SUPPRESS)
    parser.add_argument("--strict-port", action="store_true", help="Fail if the requested port is unavailable")
    parser.add_argument("--reload", action="store_true", help="Reload on backend code changes during development")
    parser.add_argument("--no-reload", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--completion-no-database-access", action="store_true",
                        help="Serve completions without database access, saved memory, or response persistence")
    args = parser.parse_args()

    runtime = select_runtime()
    if Path(sys.executable).resolve() != runtime.resolve():
        sys.exit(subprocess.call([str(runtime), str(Path(__file__).resolve()), *sys.argv[1:]]))

    try:
        from dotenv import load_dotenv
        import uvicorn
    except ImportError as exc:
        parser.exit(1, "Backend dependencies are missing. Install them with:\n"
                    "  python -m pip install -r backend/requirements.txt\n" + str(exc) + "\n")
    os.chdir(ROOT)
    load_dotenv(ROOT / ".env", override=False)
    try:
        preferences = initialize_port_settings()
        default_port = preferences.get("connector_port") or preferences.get("backend_port", 8301)
        requested_port = parse_port(args.port if args.port is not None else default_port, "backend port")
        family, host = resolve_host("127.0.0.1" if args.local else args.host or os.environ.get("BACKEND_HOST") or os.environ.get("HOST", "0.0.0.0"))
        port = available_port(requested_port, host=host, family=family)
        if args.strict_port and port != requested_port:
            raise RunError(f"Backend port {requested_port} is unavailable")
    except (RunError, UserSettingsError, OSError) as exc:
        parser.error(str(exc))
    if args.completion_no_database_access:
        os.environ["COMPLETION_NO_DATABASE_ACCESS"] = "true"
    if port != requested_port:
        print(f"[run] Backend port {requested_port} is busy; using {port}.", flush=True)
    url = service_url(host, port)
    print("=" * 64)
    print("The Connector Headless API Server")
    print(f"Python:   {sys.executable}")
    print(f"Backend:  {url} (API docs: {url}/docs)")
    for lan_url in lan_urls_for_host(host, port):
        print(f"LAN API:  {lan_url}/docs")
    print("Press Ctrl+C to stop. No UI started.")
    print("=" * 64, flush=True)
    reload_flag = args.reload and not args.no_reload
    uvicorn.run("backend.app.main:app", host=host, port=port,
                reload=reload_flag, reload_dirs=[str(ROOT / "backend")] if reload_flag else None)


if __name__ == "__main__":
    main()

