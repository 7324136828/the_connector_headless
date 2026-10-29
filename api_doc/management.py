"""Enrich management routes in the generated OpenAPI 3.1 document.

This module uses only the standard library and never imports the backend. The
schema details reflect the validators and services in backend/app, including
normalization that FastAPI's dict[str, Any] schemas cannot describe automatically.
"""

from copy import deepcopy


MAX_PLUGIN_BYTES = 10 * 1024 * 1024
CONFIG_EXAMPLE = {
    "sequences": [{"provider": "mock", "model": "mock-assistant", "retries": 0}],
    "system_prompt": "You are a helpful, precise, and thoughtful AI assistant.",
    "past_memory": True,
    "context_window": 10,
    "memory_window": 20,
    "agent_final_retries": 5,
    "memory_scope": "all_sessions",
    "memory_sources": {
        "completion_events": True,
        "system_sessions": True,
        "user_sessions": True,
    },
}


def _ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def _json_response(description, schema, example=None, headers=None):
    media = {"schema": schema}
    if example is not None:
        media["example"] = example
    result = {"description": description, "content": {"application/json": media}}
    if headers:
        result["headers"] = deepcopy(headers)
    return result


def _error(description, example):
    return _json_response(description, _ref("MgmtError"), {"detail": example})


def _validation(operation, description):
    """Both Pydantic validation errors and explicit HTTP 422 strings are possible."""
    old = operation.get("responses", {}).get("422", {})
    schemas = [_ref("MgmtError")]
    existing = old.get("content", {}).get("application/json", {}).get("schema")
    if existing:
        schemas.append(deepcopy(existing))
    operation.setdefault("responses", {})["422"] = _json_response(
        description, {"anyOf": schemas},
    )


def _describe_parameters(operation, **descriptions):
    for parameter in operation.get("parameters", []):
        name = parameter.get("name")
        if name in descriptions:
            parameter["description"] = descriptions[name]


def _configuration_schemas(schemas):
    token_limit = {
        "type": ["integer", "null"], "minimum": 1, "maximum": 1_000_000_000,
        "description": "Positive finite token cap. Omitted or null means unspecified and is removed during normalization.",
    }
    route = {
        "type": "object", "additionalProperties": False,
        "required": ["provider", "model"],
        "properties": {
            "provider": {
                "type": "string",
                "description": (
                    "Provider, compared after stripping whitespace and lowercasing. Canonical values: "
                    "openai, claude, gemini, openrouter, ollama, mock. Legacy aliases anthropic, google, "
                    "and demo normalize to claude, gemini, and mock respectively. Unknown providers are rejected."
                ),
                "x-normalized-enum": ["openai", "claude", "gemini", "openrouter", "ollama", "mock"],
                "examples": ["openai", "mock", "anthropic"],
            },
            "model": {
                "type": "string", "minLength": 1,
                "description": "Nonblank provider model ID. Leading/trailing whitespace is removed.",
                "examples": ["mock-assistant", "gpt-5-nano"],
            },
            "effort": {
                "type": ["string", "null"],
                "enum": ["none", "minimal", "low", "medium", "high", "xhigh", "max", None],
                "description": (
                    "Provider/model-dependent reasoning effort. OpenAI and OpenRouter accept all seven "
                    "strings shown; missing/null OpenAI effort becomes minimal, and missing/null OpenRouter "
                    "effort remains unspecified. Claude opus-4-5 and sonnet-4-6 accept low/medium/high; "
                    "opus-4-6 additionally accepts max. Gemini 2.5 flash/flash-lite accept none/low/medium/high; "
                    "2.5 pro accepts low/medium/high. Ollama gpt-oss accepts low/medium/high. For those "
                    "model-specific controls, missing/null selects the first supported level. Other models "
                    "must omit effort or set null, and normalization removes it. Dated Claude/OpenAI-style "
                    "model suffixes are stripped by the effort registry. Upstream providers may impose "
                    "additional model-specific restrictions."
                ),
            },
            "retries": {"type": "integer", "minimum": 0, "maximum": 5},
            "max_input_tokens": deepcopy(token_limit),
            "max_output_tokens": deepcopy(token_limit),
            "max_input_token": {
                **deepcopy(token_limit),
                "description": "Legacy alias for max_input_tokens; removed during normalization. If both non-null forms occur, their values must match.",
            },
            "max_output_token": {
                **deepcopy(token_limit),
                "description": "Legacy alias for max_output_tokens; removed during normalization. If both non-null forms occur, their values must match.",
            },
        },
    }
    direct = deepcopy(route)
    direct["title"] = "Direct routing step"
    direct["description"] = "Attempt this route in sequence. The optional type discriminator is removed from normalized direct steps."
    direct["properties"]["type"] = {"type": ["string", "null"], "enum": ["direct", None]}
    direct["properties"]["retries"].update(default=1, description="Retry count after the initial route attempt.")
    schemas["MgmtDirectRoute"] = direct

    choice = deepcopy(route)
    choice["title"] = "Weighted routing choice"
    choice["description"] = "A candidate in a probability routing step. A choice has no type field."
    choice["properties"]["retries"]["description"] = "Retry count; defaults to the enclosing probability step's retries."
    choice["properties"]["probability"] = {
        "type": "number", "minimum": 0, "maximum": 1_000_000, "default": 1,
        "description": "Finite nonnegative relative weight; weights need not sum to one. Zero excludes the choice.",
    }
    schemas["MgmtProbabilityChoice"] = choice
    schemas["MgmtProbabilityStep"] = {
        "type": "object", "additionalProperties": False,
        "required": ["type", "choices"],
        "description": "Choose a route by relative weight. At least one choice must have positive weight (an omitted probability defaults to 1).",
        "properties": {
            "type": {"type": "string", "const": "probability"},
            "choices": {
                "type": "array", "minItems": 1, "maxItems": 30,
                "items": _ref("MgmtProbabilityChoice"),
                "contains": {
                    "anyOf": [
                        {"required": ["probability"], "properties": {"probability": {"type": "number", "exclusiveMinimum": 0}}},
                        {"not": {"required": ["probability"]}},
                    ],
                },
                "minContains": 1,
            },
            "retries": {
                "type": "integer", "minimum": 0, "maximum": 5, "default": 1,
                "description": "Default retry count for choices that omit their own retries.",
            },
        },
    }
    schemas["MgmtMemorySources"] = {
        "type": "object", "additionalProperties": False,
        "description": "Every omitted source flag is filled with true during normalization.",
        "properties": {
            "user_sessions": {"type": "boolean", "default": True, "description": "Include messages from user sessions."},
            "system_sessions": {"type": "boolean", "default": True, "description": "Include messages from system/API sessions."},
            "completion_events": {"type": "boolean", "default": True, "description": "Include compatibility completion events."},
        },
    }
    schemas["ConnectorConfiguration"] = {
        "title": "Connector config.json",
        "type": "object", "additionalProperties": False, "required": ["sequences"],
        "description": (
            "Complete routing snapshot accepted by the configuration normalizer. Defaults are materialized "
            "when saved or loaded; the caller must supply sequences. Unknown fields are rejected at every "
            "configuration/route level. Direct step type markers and singular route token-cap aliases are "
            "removed, provider/model values are normalized, and absent/null token caps are removed. "
            "A configuration update replaces this entire snapshot rather than merging individual fields. "
            "Provider/model effort compatibility and equality of duplicate token-cap aliases are additional "
            "semantic checks described on the route fields. JSON Schema defaults document server behavior; "
            "client-side validators need not materialize them."
        ),
        "properties": {
            "sequences": {
                "type": "array", "minItems": 1, "maxItems": 30,
                "description": "Ordered routing steps, each a direct route or a weighted probability step.",
                "items": {"oneOf": [_ref("MgmtDirectRoute"), _ref("MgmtProbabilityStep")]},
            },
            "system_prompt": {
                "type": "string", "maxLength": 100_000,
                "default": "You are a helpful, precise, and thoughtful AI assistant.",
            },
            "past_memory": {"type": "boolean", "default": True},
            "context_window": {
                "type": "integer", "minimum": 1, "maximum": 200, "default": 10,
                "description": "Conversation context window setting (independent of provider token caps).",
            },
            "memory_window": {"type": "integer", "minimum": 0, "maximum": 200, "default": 20},
            "agent_final_retries": {
                "type": "integer", "minimum": 0, "maximum": 15, "default": 5,
                "description": "Maximum final-response retries for an agent run.",
            },
            "memory_scope": {
                "type": "string", "enum": ["all_sessions", "session"], "default": "all_sessions",
                "description": "Legacy session is accepted for compatibility; every saved/loaded value normalizes to all_sessions because memory is shared across conversations.",
            },
            "memory_sources": {**_ref("MgmtMemorySources"), "default": {}},
            "gross_max_input_token": {
                **deepcopy(token_limit), "description": "Total input-token cap across the routing operation. Omitted/null is unspecified.",
            },
            "gross_max_output_token": {
                **deepcopy(token_limit), "description": "Total output-token cap across the routing operation. Omitted/null is unspecified.",
            },
        },
        "examples": [deepcopy(CONFIG_EXAMPLE), {
            "sequences": [{"type": "probability", "retries": 1, "choices": [
                {"provider": "openai", "model": "gpt-5-nano", "effort": "minimal", "probability": 3},
                {"provider": "mock", "model": "mock-assistant", "probability": 1},
            ]}],
        }],
    }


def _record_schemas(schemas):
    for name in ("ConfigurationCreate", "ConfigurationRecord", "ConfigurationHistoryCreate", "ConfigurationHistoryRecord"):
        schemas[name]["properties"]["config"] = _ref("ConnectorConfiguration")
    update = schemas["ConfigurationUpdate"]
    update["description"] = (
        "Partial saved-record update. Omit any field to preserve its value. Only context_length accepts "
        "explicit null (to clear the value); name, description, active and config reject null. model_id is "
        "immutable and cannot be sent. A supplied config replaces the complete routing snapshot."
    )
    for name in ("name", "description", "active"):
        field = update["properties"][name]
        variants = field.pop("anyOf", [])
        nonnull = next((v for v in variants if v.get("type") != "null"), None)
        if nonnull:
            field.update(nonnull)
        field.pop("default", None)
    update["properties"]["config"] = _ref("ConnectorConfiguration")
    for name in ("ConfigurationCreate", "ConfigurationUpdate"):
        schemas[name]["properties"]["name"]["description"] = "Display name; trimmed on save and rejected if blank. Display names need not be unique."
        schemas[name]["properties"]["context_length"]["description"] = "Positive context-length metadata exposed by the compatibility models endpoint; null means unspecified."
    schemas["ConfigurationCreate"]["properties"]["model_id"]["description"] = "Unique, immutable model ID exposed by compatibility endpoints; 1-100 characters matching the declared pattern."
    for name in ("ConfigurationRecord", "ConfigurationHistoryRecord"):
        for field in ("id",):
            schemas[name]["properties"][field]["description"] = "Server-assigned UUID string."
        dates = ("created_at", "updated_at") if name == "ConfigurationRecord" else ("first_loaded_at", "last_loaded_at")
        for field in dates:
            schemas[name]["properties"][field].update(format="date-time", description="ISO 8601 UTC timestamp.")
    schemas["ConfigurationHistoryRecord"]["properties"]["load_count"].update(minimum=1, description="Number of successful loads of the normalized content, accumulated across sources.")
    schemas["ConfigurationHistoryCreate"]["properties"]["name"]["description"] = "Snapshot name; trimmed and rejected if blank. If identical normalized content already exists, its original name/source are retained."


def _configuration_routes(spec):
    paths = spec["paths"]
    operation = paths["/api/configs"]["get"]
    operation.update(summary="List saved configurations", description="Return saved records ordered by creation timestamp and ID. Set active_only=true to include only active compatibility models.")
    _describe_parameters(operation, active_only="Filter inactive saved configurations when true; false returns the entire library.")

    operation = paths["/api/configs"]["post"]
    operation.update(summary="Create a saved configuration", description="Validate and normalize a complete routing snapshot, assign a UUID, persist the named compatibility model and remember the configuration in history. model_id must be unique; display names may repeat.")
    operation["requestBody"]["content"]["application/json"]["example"] = {
        "name": "Local demo", "model_id": "local-demo", "description": "Deterministic local example.",
        "active": True, "context_length": None, "config": deepcopy(CONFIG_EXAMPLE),
    }
    operation["responses"]["409"] = _error("The model_id is already assigned to another saved configuration.", "Model ID 'local-demo' already exists.")
    _validation(operation, "Invalid request fields or configuration semantics; detail is a validation-error array or a string.")

    operation = paths["/api/configs/{config_id}"]["get"]
    operation.update(summary="Get a saved configuration", description="Return the complete saved record, including its normalized routing snapshot, for an opaque configuration ID.")
    operation["responses"]["404"] = _error("No saved record has this ID.", "Configuration not found.")

    operation = paths["/api/configs/{config_id}"]["patch"]
    operation.update(summary="Update a saved configuration", description="Update only the supplied library fields. model_id is immutable. Explicit null is allowed only for context_length. A supplied config replaces the complete snapshot, updates configuration history, and changes future routing through this model.")
    operation["requestBody"]["content"]["application/json"]["example"] = {"active": False, "description": "Temporarily disabled."}
    operation["responses"]["404"] = _error("No saved record has this ID.", "Configuration not found.")
    _validation(operation, "Invalid update fields or complete configuration snapshot; detail is a validation-error array or a string.")

    operation = paths["/api/configs/{config_id}"]["delete"]
    operation.update(summary="Delete a saved configuration", description="Remove a saved library record and its compatibility model. Previously remembered history snapshots are retained.")
    operation["responses"]["204"] = {"description": "Configuration deleted; no response body."}
    operation["responses"]["404"] = _error("No saved record has this ID.", "Configuration not found.")

    operation = paths["/api/configuration/detail/{configuration_name}"]["get"]
    operation.update(summary="Get config.json by exact display name", description="Return only the routing snapshot for an exact, case-sensitive saved display name, including inactive records. The path parameter can include slashes. Duplicate display names make the lookup ambiguous and produce HTTP 409.")
    operation["responses"]["200"] = _json_response("Saved routing snapshot, without library metadata.", _ref("ConnectorConfiguration"), CONFIG_EXAMPLE)
    operation["responses"]["404"] = _error("No saved record has this exact display name.", "Configuration not found.")
    operation["responses"]["409"] = _error("More than one saved record has this display name.", "Multiple saved configurations are named 'Local demo'.")
    _describe_parameters(operation, configuration_name="Exact display name. URL-encode reserved characters; this is a greedy path parameter and may include slashes.")

    attachment = {"Content-Disposition": {"description": "Suggests config.json as the download filename.", "schema": {"type": "string", "const": 'attachment; filename="config.json"'}}}
    for path, field, not_found in (
        ("/api/configs/{config_id}/download", "config_id", "Configuration not found."),
        ("/api/config-history/{history_id}/download", "history_id", "Configuration history entry not found."),
    ):
        operation = paths[path]["get"]
        operation.update(summary="Download config.json" if field == "config_id" else "Download historical config.json", description="Download the stored routing snapshot as indented UTF-8 JSON with a trailing newline and an attachment filename of config.json. Library/history metadata is excluded.")
        operation["responses"]["200"] = _json_response("config.json attachment.", _ref("ConnectorConfiguration"), CONFIG_EXAMPLE, attachment)
        operation["responses"]["404"] = _error("The requested record does not exist.", not_found)

    operation = paths["/api/config-history"]["get"]
    operation.update(summary="List configuration history", description="Return immutable normalized configuration snapshots ordered by last_loaded_at descending, with most recently inserted rows first for timestamp ties. Identical normalized content is deduplicated across sessions, uploads, editor actions and library records.")
    operation = paths["/api/config-history"]["post"]
    operation.update(summary="Remember a configuration snapshot", description="Normalize and remember a successfully loaded config. New normalized content creates a UUID record; existing content increments load_count and updates timestamps while preserving the original name/source. Both cases return HTTP 201.")
    operation["requestBody"]["content"]["application/json"]["example"] = {"config": deepcopy(CONFIG_EXAMPLE), "name": "config.json", "source": "editor"}
    operation = paths["/api/config-history/{history_id}"]["get"]
    operation.update(summary="Get configuration history entry", description="Return one immutable routing snapshot and its accumulated successful-load metadata.")
    operation["responses"]["404"] = _error("No configuration history entry has this ID.", "Configuration history entry not found.")
    for path, path_item in paths.items():
        if path.startswith(("/api/configs", "/api/config-history")):
            for method in ("get", "post", "patch", "delete"):
                if method in path_item:
                    _describe_parameters(path_item[method], config_id="Opaque UUID string assigned when the saved configuration is created.", history_id="Opaque UUID string assigned to deduplicated normalized configuration content.")


def _plugin_schemas(schemas):
    schemas["MgmtPluginManifest"] = {
        "type": "object", "additionalProperties": True,
        "required": ["id", "version", "backend", "ui", "webhook"],
        "description": "The installed plugin.json manifest. Additional manifest metadata is preserved and returned. Tool parameter schemas are supplied by each plugin.",
        "properties": {
            "id": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,63}$"},
            "version": {"type": "string", "minLength": 1, "maxLength": 64},
            "backend": {
                "type": "object", "additionalProperties": True, "required": ["language", "path", "entry"],
                "properties": {
                    "language": {"type": "string", "const": "python"},
                    "path": {"type": "string", "const": "backend"},
                    "entry": {"type": "string", "description": "Python module:function invoked to start the supervised backend.", "examples": ["count_message.server:main"]},
                },
            },
            "ui": {
                "type": "object", "additionalProperties": True, "required": ["entry"],
                "properties": {"entry": {"type": "string", "description": "Existing browser-ready .js module under ui/.", "examples": ["ui/src/index.js"]}},
            },
            "webhook": {
                "type": "object", "additionalProperties": True, "required": ["method", "path"],
                "properties": {
                    "method": {"type": "string", "const": "POST"},
                    "path": {"type": "string", "pattern": "^/[A-Za-z0-9_/-]+$", "examples": ["/api/count_message"]},
                },
            },
            "permissions": {
                "type": "array", "maxItems": 1,
                "items": {"type": "string", "const": "connector-database:read"},
                "default": [], "description": "Optional read-only connector database permission.",
            },
            "tool": {
                "type": "object", "additionalProperties": True,
                "properties": {
                    "description": {"description": "Plugin-supplied description used to register its agent tool."},
                    "parameters": {"type": "object", "additionalProperties": True, "description": "Plugin-defined JSON Schema for tool arguments; defaults to an unconstrained object."},
                },
            },
        },
    }
    schemas["MgmtPluginRecord"] = {
        "type": "object", "additionalProperties": False,
        "required": ["id", "version", "enabled", "status", "error", "manifest"],
        "properties": {
            "id": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,63}$"},
            "version": {"type": "string"},
            "enabled": {"type": "boolean", "description": "Persisted enablement intent; may remain true when the supervised backend has failed."},
            "status": {"type": "string", "enum": ["running", "error", "disabled"]},
            "error": {"type": ["string", "null"], "description": "Most recent startup/runtime diagnostic, or null."},
            "manifest": _ref("MgmtPluginManifest"),
        },
    }
    schemas["MgmtPluginUninstalled"] = {
        "type": "object", "additionalProperties": False, "required": ["status", "id"],
        "properties": {"status": {"type": "string", "const": "uninstalled"}, "id": {"type": "string"}},
    }


def _plugin_routes(spec):
    paths = spec["paths"]
    cors_headers = {"Access-Control-Allow-Origin": {"description": "Normally *; null when the sandbox-origin middleware handles Origin: null.", "schema": {"type": "string"}, "example": "*"}}
    resource_headers = {**cors_headers, "Cache-Control": {"schema": {"type": "string", "const": "no-store"}, "description": "Plugin asset/proxy responses are not cached."}}
    binary = {"type": "string", "format": "binary"}
    dynamic_content = {"application/json": {"schema": {}}, "*/*": {"schema": binary}}

    operation = paths["/api/plugins"]["get"]
    operation.update(summary="List installed plugins", description="Return plugin records ordered by ID. status reflects the supervised process; enabled records whose process has stopped can report error.")
    operation["responses"]["200"] = _json_response("Installed plugin records.", {"type": "array", "items": _ref("MgmtPluginRecord")})

    operation = paths["/api/plugins/install"]["post"]
    operation.update(summary="Install a plugin ZIP", description=(
        "Send the ZIP as the raw HTTP request body. The server streams at most 10 MiB and validates "
        "up to 1000 entries and 50 MiB extracted data. The archive root must contain instruction.md, "
        "plugin.json, ui/package.json, backend/pyproject.toml, run.bat and run.sh. Unsafe paths, hidden "
        "files, duplicate entries, symlinks, encrypted/corrupt files, unsupported permissions and invalid "
        "manifests are rejected. Installation persists the plugin in disabled state; enable it separately. "
        "No Content-Type check is performed; application/zip is recommended."
    ))
    operation["requestBody"] = {
        "required": True, "description": "Raw ZIP bytes, maximum 10 MiB. Empty input is rejected as an invalid archive. This endpoint does not accept a multipart file field.",
        "content": {"application/zip": {"schema": {**binary, "x-max-size-bytes": MAX_PLUGIN_BYTES}}, "application/octet-stream": {"schema": deepcopy(binary)}},
    }
    operation["responses"]["201"] = _json_response("Plugin installed, initially disabled.", _ref("MgmtPluginRecord"))
    operation["responses"]["400"] = _error("Invalid ZIP, archive layout, extraction limits, or manifest.", "Invalid plugin ZIP or manifest")
    operation["responses"]["409"] = _error("This ID is already installed or its managed folder already exists.", "Plugin is already installed; uninstall it before installing another version")
    operation["responses"]["413"] = _error("The raw ZIP exceeds 10 MiB.", "Plugin ZIP exceeds 10 MiB")

    for method, suffix, summary, description in (
        ("post", "/enable", "Enable a plugin", "Prepare the plugin's isolated Python runtime, start its declared backend, wait up to 15 seconds for /health and register its agent tool. Enabling an already running plugin returns its existing record. Startup preparation may install plugin dependencies and can take longer than the health timeout."),
        ("post", "/disable", "Disable a plugin", "Stop the supervised backend, unregister its agent tool, clear diagnostics and persist disabled state. Disabling an already disabled installed plugin succeeds."),
        ("delete", "", "Uninstall a plugin", "Disable the plugin, remove its managed installed files and delete its registry record."),
    ):
        operation = paths["/api/plugins/{plugin_id}" + suffix][method]
        operation.update(summary=summary, description=description)
        operation["responses"]["200"] = _json_response("Plugin uninstalled." if method == "delete" else "Updated plugin record.", _ref("MgmtPluginUninstalled" if method == "delete" else "MgmtPluginRecord"))
        operation["responses"]["400"] = _error("Plugin operation failed validation or runtime preparation/startup.", "Could not start plugin")
        operation["responses"]["404"] = _error("The plugin is not installed.", "Plugin not found")
        operation["responses"]["409"] = _error("The plugin operation conflicts with current lifecycle or agent-tool state.", "An agent tool with this name is already registered")

    operation = paths["/api/plugins/{plugin_id}/assets/{asset_path}"]["get"]
    operation.update(summary="Get a running plugin's UI asset", description="Serve an existing safe file under the installed plugin's ui/ directory. asset_path is a greedy path and must start with ui/. Only running plugins can serve assets. JavaScript uses text/javascript; other media types are inferred from the filename, with arbitrary binary content possible. FileResponse supports byte Range and If-Range requests and emits ETag and Last-Modified metadata; it does not perform If-None-Match/If-Modified-Since conditional GET handling.")
    operation["responses"]["200"] = {"description": "Plugin UI asset. Actual Content-Type depends on the file; */* represents other inferred media types.", "content": {"text/javascript": {"schema": {"type": "string"}}, "text/html": {"schema": {"type": "string"}}, "*/*": {"schema": binary}}, "headers": deepcopy(resource_headers)}
    operation["responses"]["206"] = {"description": "Partial asset content for a satisfiable byte Range request; multipart ranges may use multipart/byteranges.", "content": {"*/*": {"schema": deepcopy(binary)}}, "headers": {**deepcopy(resource_headers), "Content-Range": {"schema": {"type": "string"}, "description": "Byte interval and complete size for a single range."}}}
    operation["responses"]["416"] = {"description": "Asset byte range cannot be satisfied; the response body is empty.", "headers": {"Content-Range": {"schema": {"type": "string"}, "example": "bytes */1024"}}}
    operation["responses"]["400"] = _error("Unsafe asset path, or malformed byte Range request (the latter is text/plain).", "Unsafe ZIP path")
    operation["responses"]["400"]["content"]["text/plain"] = {"schema": {"type": "string"}}
    operation["responses"]["404"] = _error("Plugin or UI asset not found; non-UI files cannot be served.", "UI asset not found")
    operation["responses"]["409"] = _error("The plugin is not running.", "Enable the plugin before opening its UI")
    _describe_parameters(operation, asset_path="Greedy safe relative asset path, including ui/ prefix; for example ui/src/index.js.")
    operation.setdefault("parameters", []).extend([
        {"name": "Range", "in": "header", "required": False, "description": "Optional byte range(s) for a partial asset response.", "schema": {"type": "string"}, "example": "bytes=0-1023"},
        {"name": "If-Range", "in": "header", "required": False, "description": "ETag or Last-Modified value; a mismatch sends the complete asset.", "schema": {"type": "string"}},
    ])

    operation = paths["/api/plugins/{plugin_id}/frame"]["get"]
    operation.update(summary="Get a plugin's sandbox frame HTML", description="Return an HTML module bootstrap for a running plugin. It imports the manifest's UI entry, calls mount(element, {apiBaseUrl, sessionId}), and unmounts on pagehide. session_id is passed to the UI as sessionId; this route does not validate session existence.")
    operation["responses"]["200"] = {"description": "HTML plugin mount frame.", "content": {"text/html": {"schema": {"type": "string"}}}, "headers": deepcopy(cors_headers)}
    operation["responses"]["404"] = _error("The plugin is not installed.", "Plugin not found")
    operation["responses"]["409"] = _error("The plugin is not running.", "Enable the plugin before using it")
    _describe_parameters(operation, session_id="Optional session ID passed through to the mounted UI without a session lookup.")

    operation = paths["/api/plugins/{plugin_id}/proxy/{path}"]["options"]
    operation.update(summary="Preflight a plugin proxy request", description="Return permissive plugin-proxy CORS headers. Ordinary OPTIONS calls do not verify the plugin or requested path. For Origin: null, plugin resource middleware handles CORS preflight with GET/POST and Content-Type allowed.")
    operation["responses"]["200"] = {"description": "Empty ordinary OPTIONS response, or text/plain OK when CORS middleware handles preflight.", "content": {"text/plain": {"schema": {"type": "string"}, "example": "OK"}}, "headers": {**deepcopy(cors_headers), "Access-Control-Allow-Methods": {"schema": {"type": "string"}, "example": "GET, POST, OPTIONS"}, "Access-Control-Allow-Headers": {"schema": {"type": "string"}, "example": "Content-Type"}}}
    operation["responses"]["400"] = {"description": "CORS middleware rejected a requested preflight method, header or origin.", "content": {"text/plain": {"schema": {"type": "string"}}}}

    for method in ("get", "post"):
        operation = paths["/api/plugins/{plugin_id}/proxy/{path}"][method]
        operation.update(summary=f"Proxy a plugin {method.upper()} request", description=(
            "Forward the HTTP method, repeated query parameters and raw body to a running plugin's "
            "declared webhook path or /health. All other target paths are rejected. Only Content-Type "
            "is forwarded as a request header; it defaults to application/json when absent. Request "
            "bodies are limited to 10 MiB. The upstream timeout is 10 seconds; redirects are returned "
            "without following them. The response body, status and upstream Content-Type are passed "
            "through (default application/json); other upstream headers are not preserved. Each plugin "
            "defines its own request/response formats. A body and Content-Type header are optional at "
            "the gateway; the plugin may require them. Arbitrary upstream statuses and media types are "
            "covered by the default response."
        ))
        if method == "post":
            operation["requestBody"] = {
                "required": False,
                "description": "Optional raw plugin request payload, at most 10 MiB. application/json is the default forwarded Content-Type when the client omits it; */* covers plugin-specific payload media types.",
                "content": {"application/json": {"schema": {}, "example": {"session_id": "example-session-id"}}, "*/*": {"schema": {**binary, "x-max-size-bytes": MAX_PLUGIN_BYTES}}},
            }
        operation["responses"]["200"] = {"description": "Upstream plugin response; JSON shape and media type are plugin-defined.", "content": deepcopy(dynamic_content), "headers": deepcopy(resource_headers)}
        for code, description, example in (
            ("400", "Gateway plugin validation error, or a plugin-defined upstream HTTP 400 response.", "Unsafe ZIP path"),
            ("404", "Plugin or target path not found, or a plugin-defined upstream HTTP 404 response.", "Undeclared plugin endpoint"),
            ("409", "The plugin is not running, or a plugin-defined upstream HTTP 409 response.", "Enable the plugin before using it"),
            ("413", "Gateway request exceeds 10 MiB, or an upstream HTTP 413 response.", "Plugin request exceeds 10 MiB"),
            ("502", "Connection/timeout/upstream HTTP transport failed, or an upstream HTTP 502 response.", "Plugin backend is unavailable"),
        ):
            response = _error(description, example)
            # Upstream bodies of these status codes are equally unconstrained.
            response["content"]["application/json"]["schema"] = {}
            response["content"]["*/*"] = {"schema": deepcopy(binary)}
            operation["responses"][code] = response
        operation["responses"]["default"] = {"description": "Any other upstream HTTP status, including redirects and plugin-defined errors. Content and status are passed through; upstream headers other than Content-Type are discarded.", "content": deepcopy(dynamic_content), "headers": deepcopy(resource_headers)}
        operation["x-forwarded-query-parameters"] = "All query names and repeated values are passed through unchanged. Their meaning is plugin-defined."
        _describe_parameters(operation, path="Greedy path without its leading slash; must equal the manifest webhook path after adding /, or health. Example: api/count_message.")
    for path, path_item in paths.items():
        if path.startswith("/api/plugins/"):
            for method in ("get", "post", "delete", "options"):
                if method in path_item:
                    _describe_parameters(path_item[method], plugin_id="Installed lowercase snake_case plugin ID. Unknown IDs return 404, except ordinary OPTIONS which does not perform a lookup.")


def _settings_routes(spec, schemas):
    schemas["MgmtStorageSettings"] = {
        "type": "object", "additionalProperties": False,
        "required": ["data_dir", "configured_data_dir", "default_data_dir", "settings_path", "restart_required"],
        "properties": {
            "data_dir": {"type": "string", "description": "Absolute data directory currently used by the running backend."},
            "configured_data_dir": {"type": "string", "description": "Saved user preference. Empty means use the default temporary directory."},
            "default_data_dir": {"type": "string", "description": "Host temporary directory plus the_connector."},
            "settings_path": {"type": "string", "description": "Absolute host path of the persisted settings JSON."},
            "restart_required": {"type": "boolean", "description": "True when the requested resolved directory differs from the running service's directory, or the saved preference is invalid."},
            "configuration_error": {"type": "string", "description": "Present only when a saved data-directory preference cannot be resolved; the preference is returned for repair."},
        },
    }
    schemas["StorageSettingsUpdate"]["properties"]["data_dir"]["description"] = (
        "Host-side absolute folder path. Whitespace is trimmed; empty restores the temporary default. "
        "Environment-variable expansion and ~ are supported. Undefined variables, control characters, "
        "relative paths, or paths to existing non-directories are rejected. The folder need not exist yet."
    )
    for method in ("get", "patch"):
        operation = spec["paths"]["/api/settings"][method]
        operation["responses"]["200"] = _json_response("Running storage paths and saved directory preference.", _ref("MgmtStorageSettings"))
        operation["responses"]["500"] = _error("The settings file cannot be read or written, or saved JSON is invalid.", "Could not save settings: permission denied")
        if method == "get":
            operation.update(summary="Get storage settings", description="Read the saved storage preference and compare it with the running backend's directory. Invalid saved directory preferences are reported with configuration_error when the backend remains running under an override.")
        else:
            operation.update(summary="Save storage directory preference", description="Validate and atomically save data_dir while preserving other settings. The storage services adopt the directory only after restart; the returned data_dir remains the currently running directory and restart_required indicates whether the preference differs. This endpoint does not change the service port.")
            operation["requestBody"]["content"]["application/json"]["example"] = {"data_dir": ""}
            _validation(operation, "Invalid request body or host-side directory preference; detail is a validation-error array or a string.")


def enrich(spec: dict) -> None:
    """Add precise management route schemas and documentation in place."""
    schemas = spec.setdefault("components", {}).setdefault("schemas", {})
    schemas["MgmtError"] = {
        "type": "object", "required": ["detail"],
        "properties": {"detail": {"type": "string"}},
        "description": "FastAPI HTTPException JSON error emitted by management handlers. Validation errors instead use HTTPValidationError.",
    }
    _configuration_schemas(schemas)
    _record_schemas(schemas)
    _configuration_routes(spec)
    _plugin_schemas(schemas)
    _plugin_routes(spec)
    _settings_routes(spec, schemas)
