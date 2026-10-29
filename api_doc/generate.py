"""Export source-derived OpenAPI documents without touching live application data.

Run from the project root: .venv/Scripts/python.exe api_doc/generate.py
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import warnings

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(__file__).resolve().parent
METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


def operations(spec):
    return {(path, method) for path, item in spec["paths"].items()
            for method in item if method in METHODS}


def validate_structure(spec, expected):
    actual = operations(spec)
    if expected != actual:
        raise ValueError(f"Route coverage mismatch: missing={expected - actual}, extra={actual - expected}")
    ids = []
    for path, method in sorted(actual):
        operation = spec["paths"][path][method]
        ids.append(operation["operationId"])
        if not operation.get("responses") or not operation.get("description"):
            raise ValueError(f"Missing response or description: {method.upper()} {path}")
        for status, response in operation["responses"].items():
            if "content" in response:
                for media, contract in response["content"].items():
                    if "schema" not in contract:
                        raise ValueError(f"Missing media schema: {method} {path} {status} {media}")
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate operation IDs")

    def walk(value):
        if isinstance(value, dict):
            if "$ref" in value:
                pointer = value["$ref"]
                if not pointer.startswith("#/"):
                    raise ValueError(f"External reference requires review: {pointer}")
                target = spec
                for segment in pointer[2:].split("/"):
                    target = target[segment.replace("~1", "/").replace("~0", "~")]
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(spec)


def build_spec(work: Path):
    # All import-time database/settings/plugin initialization is confined here.
    # No lifespan startup or API handlers are invoked.
    defaults = json.loads((ROOT / "port_mapping.json").read_text(encoding="utf-8-sig"))
    (work / "settings.json").write_text(json.dumps(defaults), encoding="utf-8")
    env = {
        "CONNECTOR_RUNTIME_ROOT": str(ROOT),
        "CONNECTOR_SETTINGS_PATH": str(work / "settings.json"),
        "SETTINGS_PATH": str(work / "settings.json"),
        "DATA_DIR": str(work / "data"), "DB_PATH": str(work / "database.sqlite"),
        "PLUGIN_DIR": str(work / "plugins"), "JOBS_DIR": str(work / "jobs"),
        "AGENT_PYTHON_ENV_DIR": str(work / "python"),
        "AGENT_PYTHON_ENVS_DIR": str(work / "python_envs"),
        "RESPONSE_LOG_DIR": str(work / "logs"),
        "RESPONSE_LOGGING_ENABLED": "false", "INTERNAL_AUDIT_ENABLED": "false",
    }
    os.environ.update(env)
    sys.path.insert(0, str(ROOT))
    from fastapi.routing import APIRoute
    from backend.app.main import app
    from core import enrich as enrich_core
    from management import enrich as enrich_management
    from compatibility import enrich as enrich_compatibility

    expected = set()
    for route in app.routes:
        if isinstance(route, APIRoute):
            expected.update((route.path_format, method.lower()) for method in route.methods)
        elif hasattr(route, "effective_route_contexts"):
            # Recent FastAPI versions retain included routers instead of
            # copying their APIRoutes into app.routes. Effective contexts also
            # include any prefix supplied at router inclusion time.
            for context in route.effective_route_contexts():
                if isinstance(context.original_route, APIRoute):
                    expected.update((context.path_format, method.lower()) for method in context.methods)
    # FastAPI derives operation IDs before source-reviewed overrides; the
    # multi-method plugin routes are assigned explicit unique IDs below.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Duplicate Operation ID")
        spec = app.openapi()
    spec["info"]["title"] = "The Connector Headless API"
    spec["info"]["description"] = (
        "Comprehensive specification of the backend application routes in this repository. "
        "Includes session/chat/agent workflows, configuration libraries and history, typed skills, "
        "Python environments, plugins, storage settings, optional Kokoro speech, OpenAI-compatible "
        "completions, and discovery aliases. The backend does not enforce API authentication; "
        "an SDK's Authorization header is not validated by these routes. Configuration model IDs "
        "are distinct from upstream provider model names. Runtime-generated tool arguments and "
        "plugin proxy payloads intentionally have extensible schemas."
    )
    spec["servers"] = [{"url": f"http://127.0.0.1:{defaults['connector_port']}",
                        "description": "Local backend (project default port)."}]
    spec["security"] = []
    spec["jsonSchemaDialect"] = "https://spec.openapis.org/oas/3.1/dialect/base"
    enrich_core(spec)
    enrich_management(spec)
    enrich_compatibility(spec)

    tag_descriptions = {
        "Health": "Backend readiness and optional speech-service status.",
        "Speech": "External Kokoro voices and WAV synthesis.",
        "Sessions": "Session configuration snapshots and persisted transcripts.",
        "Chat": "Session-based routed completions.",
        "Agents": "Tool registry, direct execution, and ReAct runs.",
        "Python environments": "Managed execution environments.",
        "Skills": "Typed callable skills, import, and export.",
        "Configuration utilities": "Validation examples and provider capabilities.",
        "History exports": "ZIP exports and permanent chat-history deletion.",
    }
    for path, method in sorted(operations(spec)):
        operation = spec["paths"][path][method]
        if not operation.get("tags"):
            if path == "/api/health": tag = "Health"
            elif path.startswith("/api/speech"): tag = "Speech"
            elif path.startswith("/api/agent"): tag = "Agents"
            elif path.startswith("/api/python-environments"): tag = "Python environments"
            elif path.startswith("/api/skills"): tag = "Skills"
            elif "export-zip" in path or path == "/api/history": tag = "History exports"
            elif path.startswith(("/api/sessions", "/api/new", "/api/close")): tag = "Sessions"
            elif path == "/api/chat": tag = "Chat"
            else: tag = "Configuration utilities"
            operation["tags"] = [tag]
        operation.setdefault("description", operation.get("summary", ""))
        # Preserve the readable generated IDs, resolving shared-method routes.
        operation["operationId"] = operation["operationId"].rsplit("_", 1)[0] + "_" + method
    used_tags = sorted({tag for path, method in operations(spec)
                       for tag in spec["paths"][path][method]["tags"]})
    existing_tags = {tag["name"]: tag for tag in spec.get("tags", [])}
    spec["tags"] = [existing_tags.get(name, {"name": name, "description": tag_descriptions.get(name, name + " endpoints.")})
                    for name in used_tags]
    validate_structure(spec, expected)
    return spec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if committed documents differ from current source-derived output")
    args = parser.parse_args()
    import yaml
    with tempfile.TemporaryDirectory(prefix="connector-openapi-") as directory:
        spec = build_spec(Path(directory))
    documents = {
        "openapi.json": json.dumps(spec, indent=2, ensure_ascii=False) + "\n",
        "openapi.yaml": yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=100),
    }
    if json.loads(documents["openapi.json"]) != yaml.safe_load(documents["openapi.yaml"]):
        raise ValueError("JSON/YAML documents differ")
    for filename, contents in documents.items():
        path = OUTPUT / filename
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != contents:
                raise SystemExit(f"Outdated specification: {path}. Run api_doc/generate.py.")
        else:
            path.write_text(contents, encoding="utf-8", newline="\n")
    print(f"{'Checked' if args.check else 'Generated'} OpenAPI {spec['openapi']}: "
          f"{len(operations(spec))} operations, {len(spec['paths'])} paths, "
          f"{len(spec['components']['schemas'])} schemas; full application-route coverage.")


if __name__ == "__main__":
    main()
