# The Connector Headless API specification

The complete OpenAPI 3.1.0 specification is available in two equivalent formats:

- [openapi.yaml](openapi.yaml) — readable YAML for Swagger Editor, API documentation tools, and client generators.
- [openapi.json](openapi.json) — JSON for programmatic integrations and tooling.

The specification covers **81 operations, 68 paths, and 84 component schemas** from this repository's backend. The default server is `http://127.0.0.1:8301`; change the server URL in your tooling if you use a different host or saved port.

## Coverage

| API area | Contracts included |
| --- | --- |
| Health and speech | Readiness, Kokoro health and voices, WAV synthesis and audio headers |
| Sessions and chat | Creation, configuration snapshots, listing, transcripts, closure, routed chat |
| Agents | Tool discovery/registration, direct tool steps, ReAct runs |
| Skills and Python environments | Typed skill CRUD, generation, imports/exports, environment creation and selection |
| Configurations | Saved-model library, name lookup, downloads, history, normalization, capability queries |
| Plugins and settings | Raw ZIP installation, lifecycle, assets, frames, proxy methods, storage preferences |
| Compatibility | OpenAI-style models and completions, JSON/SSE responses, Ollama and llama.cpp discovery probes, all aliases |
| Exports and discovery | Session/history ZIPs, confirmed history deletion, root and favicon routes |

Requests, responses, parameters, status codes, media types, headers, examples, and runtime validation rules are documented. Schema extensions identify semantics that JSON Schema cannot completely express, such as provider-dependent effort support. Tool results, plugin proxy bodies, provider replay metadata, and external Kokoro health fields remain extensible where the backend accepts or forwards dynamic data.

The backend does not enforce API authentication. There is no mandatory bearer-token security scheme in these files. Compatibility model IDs come from active saved configurations, while `/api/providers/models` lists upstream provider models. New sessions default to `user_session: false`, which returns the saved mock reply `message received`; set it to true to execute the configured model routes. Compatibility streaming is buffered and emitted as SSE after generation completes. The backend can use saved memory and archive compatibility completions; `store: false` does not disable those local features.

Framework documentation endpoints (`/docs`, `/redoc`, `/openapi.json`, and the Swagger OAuth redirect) are excluded from the application-operation count. The live `/openapi.json` is FastAPI's generated schema; the files here additionally describe behavior reviewed from source, including responses without declared Pydantic models.

## Regenerate and validate

From the project root, using the backend's Python environment:

```powershell
.\.venv\Scripts\python.exe api_doc\generate.py
.\.venv\Scripts\python.exe api_doc\generate.py --check
```

Generation imports the backend with isolated temporary settings, database, logs, jobs, plugins, and Python-environment paths. It does not start the server, run lifespan hooks, restore plugins, call upstream providers, or use the running backend's database. It checks complete route coverage, unique operation IDs, resolved component references, and JSON/YAML equivalence. `--check` also detects stale exported documents. On Windows, a restricted execution sandbox may require running these commands in a normal terminal because of Python's temporary-directory permissions.

Optional independent standards and example validation:

```powershell
.\.venv\Scripts\python.exe -m pip install openapi-spec-validator PyYAML
.\.venv\Scripts\python.exe api_doc\validate.py
```

`generate.py` preserves FastAPI's typed schemas and applies the source-reviewed contracts in `core.py`, `management.py`, and `compatibility.py`. Update those enrichment modules when an untyped response or a runtime semantic rule changes, then regenerate both documents. The backend implementation is the authority for runtime behavior.
