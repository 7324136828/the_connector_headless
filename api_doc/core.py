"""Source-reviewed contracts for the application's core FastAPI endpoints."""

def ref(name):
    return {"$ref": f"#/components/schemas/{name}"}


def obj(properties, required=None, **extra):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required, **extra}


def enrich(spec):
    schemas = spec["components"]["schemas"]
    paths = spec["paths"]
    schemas["ConnectorHTTPError"] = obj({"detail": {"type": "string"}})
    # Runtime semantic checks and FastAPI request validation share HTTP 422.
    schemas["ConnectorValidationError"] = {
        "anyOf": [ref("ConnectorHTTPError"), ref("HTTPValidationError")]
    }
    schemas["ConnectorSpeechHealth"] = obj({
        "status": {"type": "string", "const": "ok"},
        "service": {"type": "string", "const": "python-kokoro"},
    }, additionalProperties=True,
        description="Verified Kokoro health payload. Additional runtime/model/device fields are forwarded from Kokoro.")
    schemas["ConnectorSpeechUnavailable"] = obj({
        "status": {"type": "string", "const": "unavailable"},
        "required": {"type": "boolean", "const": False},
        "detail": {"type": "string"},
    })
    schemas["ConnectorHealth"] = obj({
        "status": {"type": "string", "const": "ok"},
        "version": {"type": "string"},
        "providers_status": obj({
            name: {"type": "string" if name == "ollama_host" else "boolean"}
            for name in ("openai", "claude", "gemini", "openrouter", "ollama_host", "mock")
        }, description="Provider booleans indicate configured API keys, not verified upstream connectivity."),
        "speech": {"anyOf": [
            {"allOf": [ref("ConnectorSpeechHealth"), obj({"required": {"type": "boolean", "const": False}})]},
            ref("ConnectorSpeechUnavailable"),
        ]},
    })
    schemas["ConnectorVoices"] = obj({
        "default": {"type": "string", "description": "Connector's configured default voice."},
        "voices": {"type": "array", "items": {"type": "string"}},
    }, additionalProperties=True)
    schemas["ConnectorToolRegistration"] = obj({
        "status": {"type": "string", "const": "registered"}, "tool": {"type": "string"}
    })
    schemas["ConnectorSkillExport"] = obj({
        "version": {"type": "integer", "const": 1},
        "skills": {"type": "array", "items": ref("SkillCreate")},
    }, description="Portable skill definitions; database IDs and timestamps are omitted.")
    schemas["ConnectorModelCapabilitiesRequest"] = {
        "type": "object", "additionalProperties": {"type": "string"},
        "properties": {
            "provider": {"type": "string", "description": "Provider name; absent defaults to an empty string."},
            "model": {"type": "string", "description": "Provider model name; absent defaults to an empty string."},
        },
    }
    schemas["ConnectorModelCapabilities"] = obj({
        "effort_levels": {"type": "array", "items": {"type": "string"}},
        "default_effort": {"type": ["string", "null"]},
    })

    def op(path, method):
        return paths[path][method]

    def describe(path, method, text):
        op(path, method)["description"] = text

    def response(path, method, name, status="200", description="Successful response", **extra):
        op(path, method)["responses"][status] = {
            "description": description,
            "content": {"application/json": {"schema": ref(name)}}, **extra,
        }

    def errors(path, method, codes):
        operation = op(path, method)
        for code, detail in codes.items():
            operation["responses"][str(code)] = {
                "description": detail,
                "content": {"application/json": {"schema": ref(
                    "ConnectorValidationError" if code == 422 else "ConnectorHTTPError"
                )}},
            }

    for path, item in paths.items():
        for method, operation in item.items():
            if method not in {"get", "post", "patch", "delete", "put", "options", "head"}:
                continue
            if path.startswith("/api/") and "422" in operation["responses"]:
                operation["responses"]["422"]["content"]["application/json"]["schema"] = ref("ConnectorValidationError")

    response("/api/health", "get", "ConnectorHealth")
    describe("/api/health", "get", "Return API readiness and configured-provider indicators. Kokoro speech is optional in headless mode; unavailable speech is reported in the payload while this endpoint still returns HTTP 200. Provider indicators do not contact the providers.")
    response("/api/speech/health", "get", "ConnectorSpeechHealth")
    response("/api/speech/voices", "get", "ConnectorVoices")
    for path in ("/api/speech", "/api/speech/health", "/api/speech/voices"):
        method = "post" if path == "/api/speech" else "get"
        errors(path, method, {502: "Kokoro rejected the request or returned invalid data.",
                              503: "The configured Kokoro service is unreachable."})
    errors("/api/speech", "post", {422: "Invalid request, unknown voice, or response content without speakable text."})
    op("/api/speech", "post")["responses"]["200"] = {
        "description": "WAV audio synthesized by the external Kokoro service.",
        "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}},
        "headers": {name: {"description": text + " Forwarded only when supplied by Kokoro.",
                           "schema": {"type": "string"}}
                    for name, text in {
                        "X-Audio-Duration": "Generated audio duration in seconds.",
                        "X-Render-Seconds": "Rendering time in seconds.",
                        "X-Real-Time-Factor": "Rendering time divided by audio duration.",
                    }.items()},
    }
    describe("/api/speech", "post", "Synthesize plain text or a serialized JSON object with a nonempty `text` string. Valid JSON arrays/scalars, missing `text`, and empty text are rejected. Voice precedence: request `actor`, then JSON content `actor`, then the configured default. JSON `actor`, when non-null, must be a nonempty string. Returns WAV audio; speech requires an available external Kokoro service.")
    schemas["SpeechRequest"]["examples"] = [
        {"content": "Hello from the Connector.", "actor": "af_heart"},
        {"content": '{"text":"Hello from the Connector.","actor":"am_michael"}'},
    ]

    for name in ("NewSessionRequest", "UpdateSessionRequest", "SessionDetail"):
        prop = schemas[name]["properties"]["config"]
        schemas[name]["properties"]["config"] = (
            {"anyOf": [ref("ConnectorConfiguration"), {"type": "null"}], "default": None}
            if name != "UpdateSessionRequest" else ref("ConnectorConfiguration")
        )
        if "description" in prop:
            schemas[name]["properties"]["config"]["description"] = prop["description"]
    schemas["NewSessionRequest"]["oneOf"] = [
        {"required": [selected], "properties": {
            field: ({"type": "object"} if field == "config" else {"type": "string"})
            if field == selected else {"type": "null"}
            for field in ("config", "config_id", "history_id")
        }} for selected in ("config", "config_id", "history_id")
    ]
    sample_config = {"sequences": [{"provider": "mock", "model": "mock-assistant", "retries": 1}]}
    schemas["NewSessionRequest"]["examples"] = [
        {"title": "Demo chat", "config": sample_config, "user_session": True},
        {"config_id": "saved-configuration-id", "user_session": True},
        {"history_id": "configuration-history-id"},
    ]
    schemas["UpdateSessionRequest"]["examples"] = [{"config": sample_config}]
    schemas["ChatRequest"]["examples"] = [{"session_id": "session-id", "message": "Hello"}]
    schemas["AgentRunRequest"]["examples"] = [{"session_id": "session-id", "prompt": "Explain this calculation", "max_steps": 5}]
    schemas["AgentStepRequest"]["examples"] = [{"tool": "run_python_script", "arguments": {"code": "print(1 + 1)"}}]
    schemas["ClearHistoryRequest"]["examples"] = [{"confirmation": "DELETE"}]
    for path in ("/api/sessions", "/api/new"):
        describe(path, "post", "Create a session from exactly one non-null `config`, `config_id`, or `history_id`. A saved configuration must be active. The session owns its own configuration snapshot. `user_session` defaults to false; those system sessions return the mock reply `message received` on chat and agent runs. Set `user_session: true` to execute configured model routes.")
        errors(path, "post", {404: "Saved configuration or configuration-history entry not found.",
                              409: "The saved configuration is inactive."})
    describe("/api/sessions", "get", "List at most 50 active sessions, ordered by latest update first. Closed sessions are omitted; no pagination or limit query parameter is exposed.")
    errors("/api/sessions/{session_id}", "get", {404: "Session not found."})
    errors("/api/sessions/{session_id}", "patch", {404: "Session not found.", 409: "Session is closed."})
    for path in ("/api/close", "/api/sessions/{session_id}"):
        describe(path, "delete", "Deactivate a saved session and purge its temporary files. This preserves the transcript and configuration; closing an already closed existing session succeeds again. For `/api/close`, provide `session_id` in the JSON body or query string; a nonempty body value takes precedence.")
        errors(path, "delete", {404: "Session not found."})
    errors("/api/close", "delete", {400: "Missing session_id in both body and query string."})
    common_session_errors = {400: "Input exceeds a configured context/token limit.",
                             404: "Session not found.", 409: "Session is closed."}
    errors("/api/chat", "post", {**common_session_errors, 500: "Routing failed."})
    describe("/api/chat", "post", "Send a message through the session's saved routing configuration, then atomically persist the user/assistant exchange. Configuration controls routing and memory; request-level routing overrides are not accepted. System sessions (`user_session: false`) persist a mock `message received` reply without contacting a provider.")
    errors("/api/agent/run", "post", {**common_session_errors, 502: "Agent routing or execution failed."})
    describe("/api/agent/run", "post", "Execute a ReAct reasoning/tool loop using the session's configuration, memory policy, and optional list of tools to advertise to the model. Omitted, null, or empty `tools` advertises all registered tools; unknown names in a supplied list are ignored. This list does not enforce execution permissions. The final exchange and tool trace are persisted. System sessions return the mock `message received` reply without model routing.")
    describe("/api/agent/step", "post", "Execute one registered tool or webhook. Unknown tools and exceptions raised by a tool/webhook return HTTP 200 with `success: false` and an `error` string. Some handlers return execution errors in `result` even when `success` is true. `result` depends on the tool. `fetch_memory` requires a session ID in the request or tool arguments; a request-level session ID takes precedence.")
    response("/api/agent/register-tool", "post", "ConnectorToolRegistration", "201")
    describe("/api/agent/register-tool", "post", "Register or replace an in-memory tool by name. An optional endpoint is invoked via HTTP POST with JSON tool arguments. The registration is not a persisted skill or installed plugin and is lost on process restart.")

    errors("/api/python-environments", "post", {409: "An environment already uses this name (case insensitive).",
                                              422: "Invalid environment name or request.",
                                              502: "Environment provisioning failed."})
    errors("/api/python-environments/{environment_id}/select", "post", {404: "Environment not found.",
                                                                      502: "Environment provisioning or repair failed."})
    schemas["PythonEnvironmentCreate"]["properties"]["name"]["description"] = "Trimmed before validation; must match ^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$. Names are unique case insensitively."
    describe("/api/python-environments", "post", "Synchronously provision a managed Python virtual environment. `select` defaults to true and selects it for agent Python execution and package installation.")
    for name in ("SkillCreate", "SkillRecord", "SkillUpdate"):
        schemas[name]["properties"]["name"]["description"] = "Trimmed; name must match ^[a-z][a-z0-9_]{1,63}$ and must not collide with a reserved built-in tool name. Uppercase names are rejected."
        schemas[name]["properties"]["parameters"]["description"] = "Tool argument JSON Schema. The schema must declare type: object."
        schemas[name]["properties"]["python_code"]["description"] = "Code for the selected skill type (field name is shared by Python, CMD, and C++). Also limited to 100000 UTF-8 bytes. Python must define top-level run(args); C++ must define main()."
        schemas[name]["properties"]["source_conversation"]["description"] = "Optional source conversation; also limited to 1000000 UTF-8 bytes."
    update = schemas["SkillUpdate"]
    update["minProperties"] = 1
    for prop in update["properties"].values():
        if "anyOf" in prop:
            variants = [v for v in prop.pop("anyOf") if v != {"type": "null"}]
            prop.update(variants[0] if len(variants) == 1 else {"anyOf": variants})
        prop.pop("default", None)
    update["description"] = "At least one field must be supplied. Explicit null values are rejected."
    skill_errors = {409: "Duplicate skill name.", 422: "Invalid skill definition, reserved built-in name, or request."}
    errors("/api/skills", "post", skill_errors)
    errors("/api/skills/{skill_id}", "patch", {**skill_errors, 404: "Skill not found."})
    errors("/api/skills/{skill_id}", "delete", {404: "Skill not found."})
    errors("/api/skills/from-conversation", "post", {**skill_errors, 409: "Duplicate skill name or session is closed or lacks a configuration.", 404: "Session not found.",
                                                     502: "Model-based skill generation failed."})
    errors("/api/skills/import", "post", skill_errors)
    describe("/api/skills/import", "post", "Validate and import all skill definitions atomically. `conflict` controls collisions with saved names: error, skip, or replace. Duplicate canonical names within the upload always fail with HTTP 409. Response `skills` contains created/replaced records and excludes skipped records."
             )
    response("/api/skills/export", "get", "ConnectorSkillExport", headers={
        "Content-Disposition": {"schema": {"type": "string"}, "example": 'attachment; filename="skills.json"'}
    })
    schemas["SkillCreate"]["examples"] = [{
        "name": "add_numbers", "description": "Add two numbers.", "type": "python",
        "parameters": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]},
        "python_code": 'def run(args):\n    return args["a"] + args["b"]\n',
    }]

    response("/api/config/example", "get", "ConnectorConfiguration", headers={
        "Content-Disposition": {"schema": {"type": "string"}, "example": 'attachment; filename="config.json"'}
    })
    response("/api/config/validate", "post", "ConnectorConfiguration")
    op("/api/config/validate", "post")["requestBody"]["content"]["application/json"]["schema"] = ref("ConnectorConfiguration")
    errors("/api/config/validate", "post", {422: "Invalid configuration or request; normalization failed."})
    describe("/api/config/validate", "post", "Validate and normalize an uploaded configuration without saving it. Apply defaults, canonicalize provider/token aliases, remove direct-step type markers, and normalize memory_scope to all_sessions. Per-provider/model effort support and positive weighted-route totals are checked at runtime."
             )
    response("/api/models/capabilities", "post", "ConnectorModelCapabilities")
    op("/api/models/capabilities", "post")["requestBody"]["content"]["application/json"]["schema"] = ref("ConnectorModelCapabilitiesRequest")
    describe("/api/models/capabilities", "post", "Return the backend's effort-level registry for a provider/model pair. Missing names and unrecognized pairs can return an empty list and null default. This is a local registry query and does not contact an upstream provider.")
    describe("/api/providers/models", "get", "Return the backend's provider-model catalog and effort settings, including dynamically discovered local Ollama models. If Ollama discovery returns no models, include the fallback llama3.2 entry. This catalog differs from the active configuration model IDs exposed by /v1/models.")
    for path in ("/api/sessions/{session_id}/export-zip", "/api/history/export-zip"):
        op(path, "get")["responses"]["200"] = {
            "description": "ZIP archive containing metadata.json, transcript.json, and transcript.md. All-history exports add manifest.json and one directory per saved session (including closed sessions).",
            "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
            "headers": {"Content-Disposition": {"schema": {"type": "string"}, "description": "Attachment filename."}},
        }
        errors(path, "get", {500: "Could not create the export archive."})
    errors("/api/sessions/{session_id}/export-zip", "get", {404: "Session not found."})
    describe("/api/history", "delete", "Permanently delete every saved session and transcript, including closed sessions, and purge session/history export files. The required JSON body must contain `confirmation: DELETE`. Configuration-library/history records and skills are separate stores.")
