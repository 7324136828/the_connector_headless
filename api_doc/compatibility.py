"""Describe compatibility routes missing response models in FastAPI's schema.

This module has no backend imports. ``enrich`` accepts the generated OpenAPI
document and updates it in place, using the contracts in compatibility.py and
completion_service.py. All added schema names use the Compat prefix.
"""

from __future__ import annotations

from copy import deepcopy
import json
import re


TAG = "Agent compatibility"
MODEL_PATHS = ("/v1/models", "/api/v1/models", "/api/models", "/models")
COMPLETION_PATHS = (
    "/v1/chat/completions", "/api/v1/chat/completions",
    "/api/chat/completions", "/chat/completions",
)
TAGS_PATHS = ("/api/tags", "/api/api/tags")
SHOW_PATHS = ("/api/show", "/api/api/show")
PROPS_PATHS = ("/props", "/v1/props", "/api/props", "/api/v1/props")
VERSION_PATHS = ("/api/version", "/version")


def _ref(name: str) -> dict:
    return {"$ref": "#/components/schemas/" + name}


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def _object(properties: dict, required: tuple[str, ...] | list[str] = (), **extra) -> dict:
    result = {"type": "object", "properties": properties, **extra}
    if required:
        result["required"] = list(required)
    return result


def _json_response(name: str, description: str, example: dict | None = None) -> dict:
    media = {"schema": _ref(name)}
    if example is not None:
        media["example"] = deepcopy(example)
    return {"description": description, "content": {"application/json": media}}


def _error(status: int, description: str, code: str, message: str, param=None) -> dict:
    return _json_response("CompatErrorResponse", description, {"error": {
        "message": message,
        "type": "server_error" if status >= 500 else "invalid_request_error",
        "param": param, "code": code,
    }})


MODEL_EXAMPLE = {
    "id": "research-router", "object": "model", "created": 1767225600,
    "owned_by": "the_connector", "name": "Research routing",
    "description": "Example active mock configuration",
    "configuration_id": "9c3da661-ab76-4b6d-b72b-b409b9558528",
    "context_length": 32000,
}
USAGE_EXAMPLE = {"prompt_tokens": 8, "completion_tokens": 5, "total_tokens": 13}
COMPLETION_EXAMPLE = {
    "id": "chatcmpl-00000000000000000000000000000001", "object": "chat.completion",
    "created": 1767225600, "model": "research-router",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Mock completion: Hello"},
                 "finish_reason": "stop"}],
    "usage": USAGE_EXAMPLE,
}
TOOL_EXAMPLE = {"type": "function", "function": {
    "name": "lookup", "description": "Look up an item",
    "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                   "required": ["query"], "additionalProperties": False},
}}
OLLAMA_DETAILS_EXAMPLE = {
    "format": "configuration", "family": "connector", "families": ["connector"],
    "parameter_size": "", "quantization_level": "",
}


def _sse_example() -> str:
    base = {key: COMPLETION_EXAMPLE[key] for key in ("id", "created", "model")}
    base["object"] = "chat.completion.chunk"
    chunks = [
        {**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}], "usage": None},
        {**base, "choices": [{"index": 0, "delta": {"content": "Mock completion: Hello"}, "finish_reason": None}], "usage": None},
        {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": None},
        {**base, "choices": [], "usage": USAGE_EXAMPLE},
    ]
    return "".join("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"


def _schemas() -> dict:
    """Build explicit request, discovery, JSON response, and SSE event schemas."""
    text_parts = {"type": "array", "items": {"type": "object", "additionalProperties": True}}
    content = {"anyOf": [{"type": "string"}, text_parts, {"type": "null"}]}
    schemas = {
        "CompatErrorResponse": _object({"error": _object({
            "message": {"type": "string"},
            "type": {"type": "string", "enum": ["invalid_request_error", "server_error"]},
            "param": {"type": ["string", "null"]},
            "code": {"type": "string", "enum": [
                "invalid_request_error", "model_not_found", "unsupported_option",
                "context_length_exceeded", "upstream_error", "empty_completion",
            ]},
        }, ("message", "type", "param", "code"), additionalProperties=False)},
            ("error",), additionalProperties=False),
        "CompatModel": _object({
            "id": {"type": "string", "description": "The active configuration's model_id, used in completion requests."},
            "object": {"type": "string", "const": "model"},
            "created": {"type": "integer", "description": "Configuration creation time as Unix seconds."},
            "owned_by": {"type": "string", "const": "the_connector"},
            "name": {"type": "string"}, "description": {"type": "string"},
            "configuration_id": {"type": "string"},
            "context_length": {"type": "integer", "minimum": 1,
                               "description": "Declared context capacity, or the minimum known capacity across all configured routes. Omitted when any route has unknown capacity."},
        }, ("id", "object", "created", "owned_by", "name", "description", "configuration_id"), additionalProperties=False),
        "CompatModelList": _object({
            "object": {"type": "string", "const": "list"},
            "data": {"type": "array", "items": _ref("CompatModel")},
        }, ("object", "data"), additionalProperties=False),
        "CompatToolCall": _object({
            "id": {"type": "string", "minLength": 1},
            "type": {"type": "string", "const": "function"},
            "function": _object({
                "name": {"type": "string"},
                "arguments": {"type": "string", "description": "Serialized JSON arguments. Native Claude, Gemini, and Ollama routes require this string to decode to a JSON object."},
            }, ("name", "arguments"), additionalProperties=True),
            "extra_content": {"type": "object", "additionalProperties": True,
                              "description": "Provider metadata, including Gemini function IDs and thought signatures. Preserve when replaying a response."},
        }, ("id", "type", "function"), additionalProperties=True),
        "CompatFunctionTool": _object({
            "type": {"type": "string", "const": "function"},
            "function": _object({
                "name": {"type": "string", "minLength": 1},
                "parameters": {"type": "object", "additionalProperties": True,
                               "description": "A JSON Schema object describing the function arguments."},
            }, ("name",), additionalProperties=True,
                description="Function names must be unique within tools. Additional provider options such as description and strict are retained; strict function schemas are unsupported by native Gemini and Ollama routes."),
        }, ("type", "function"), additionalProperties=True),
        "CompatNamedToolChoice": _object({
            "type": {"type": "string", "const": "function"},
            "function": _object({"name": {"type": "string", "minLength": 1}},
                                ("name",), additionalProperties=True),
        }, ("type", "function"), additionalProperties=True,
            description="The name must match one of the supplied function tools."),
        "CompatResponseFormat": _object({
            "type": {"type": "string", "enum": ["text", "json_object", "json_schema"]},
            "json_schema": _object({"schema": {"type": "object", "additionalProperties": True}},
                                   ("schema",), additionalProperties=True),
        }, ("type",), additionalProperties=True, allOf=[{
            "if": {"properties": {"type": {"const": "json_schema"}}, "required": ["type"]},
            "then": {"required": ["json_schema"]},
        }], description="Native Claude routes reject response_format. Other providers support these forms subject to provider capabilities."),
        "CompatStreamOptions": _object({"include_usage": {"type": "boolean", "default": False}},
                                      additionalProperties=False),
        "CompatCompletionMessage": _object({
            "role": {"type": "string", "enum": ["system", "developer", "user", "assistant", "tool"]},
            "content": {**deepcopy(content), "description": "Non-assistant messages require non-null content. Native Claude, Gemini, Ollama, and mock routes accept strings or an array consisting only of {type: text, text: string} parts. OpenAI/OpenRouter routes receive content parts unchanged."},
            "tool_calls": _nullable({"type": "array", "items": _ref("CompatToolCall")}),
            "tool_call_id": {"type": ["string", "null"], "description": "Required and nonempty for tool messages, and must reference a call in an earlier assistant message."},
            "name": {"type": ["string", "null"]},
        }, ("role",), additionalProperties=True, allOf=[
            {"if": {"properties": {"role": {"const": "tool"}}, "required": ["role"]},
             "then": {"required": ["tool_call_id"], "properties": {"tool_call_id": {"type": "string", "minLength": 1}}}},
            {"if": {"properties": {"role": {"not": {"const": "assistant"}}}, "required": ["role"]},
             "then": {"required": ["content"], "properties": {
                 "content": {"anyOf": [{"type": "string"}, deepcopy(text_parts)]},
                 "tool_calls": _nullable({"type": "array", "maxItems": 0}),
             }}},
            {"if": {"properties": {"role": {"const": "assistant"}}, "required": ["role"]},
             "then": {"anyOf": [
                 {"required": ["content"], "properties": {"content": {"anyOf": [{"type": "string"}, deepcopy(text_parts)]}}},
                 {"required": ["tool_calls"], "properties": {"tool_calls": {"type": "array", "minItems": 1}}},
             ]}},
        ], description="Additional fields preserve provider reasoning and replay metadata. Only assistant messages may contain nonempty tool_calls. Assistant messages require non-null content or nonempty tool_calls; a refusal-only response cannot be replayed without satisfying that request constraint."),
        "CompatAssistantMessage": _object({
            "role": {"type": "string", "const": "assistant"}, "content": deepcopy(content),
            "tool_calls": _nullable({"type": "array", "items": _ref("CompatToolCall")}),
            "reasoning_content": {"type": ["string", "null"]},
            "refusal": {"type": ["string", "null"]},
            "extra_content": {"type": "object", "additionalProperties": True},
        }, ("role", "content"), additionalProperties=True,
            description="The assistant message, including provider-specific fields unchanged. Null content is valid for tool calls, refusals, and content_filter results; empty text is also valid. Preserve provider metadata when continuing a tool loop."),
        "CompatCompletionUsage": _object({
            "prompt_tokens": {"type": "integer", "minimum": 0},
            "completion_tokens": {"type": "integer", "minimum": 0},
            "total_tokens": {"type": "integer"},
            "prompt_tokens_details": {"description": "Optional provider-specific token details, retained unchanged."},
            "completion_tokens_details": {"description": "Optional provider-specific token details, retained unchanged."},
        }, ("prompt_tokens", "completion_tokens", "total_tokens"), additionalProperties=False,
            description="Provider counts when available; otherwise prompt and completion counts are estimated from serialized input and assistant output. A provider-supplied integer total_tokens is preserved."),
        "CompatCompletionResponse": _object({
            "id": {"type": "string", "pattern": "^chatcmpl-[0-9a-f]{32}$"},
            "object": {"type": "string", "const": "chat.completion"},
            "created": {"type": "integer", "description": "Response creation time as Unix seconds."},
            "model": {"type": "string", "description": "The requested configuration model_id, rather than the underlying provider's returned model."},
            "choices": {"type": "array", "minItems": 1, "maxItems": 1, "items": _object({
                "index": {"type": "integer", "const": 0},
                "message": _ref("CompatAssistantMessage"),
                "finish_reason": {"type": "string", "description": "Typically stop, length, tool_calls, or content_filter; upstream OpenAI/OpenRouter reasons are preserved."},
            }, ("index", "message", "finish_reason"), additionalProperties=False)},
            "usage": _ref("CompatCompletionUsage"),
        }, ("id", "object", "created", "model", "choices", "usage"), additionalProperties=False),
        "CompatCompletionDelta": _object({
            "role": {"type": "string", "const": "assistant"},
            "content": {"type": "string"}, "reasoning_content": {"type": "string"},
            "tool_calls": {"type": "array", "items": {
                "allOf": [_ref("CompatToolCall"), _object({"index": {"type": "integer", "minimum": 0}}, ("index",))],
            }},
        }, additionalProperties=True,
            description="Role, text, reasoning, tool calls, or provider metadata. An empty delta marks the terminal choice event. Tool-call payloads are emitted together rather than streamed argument fragments."),
        "CompatCompletionChunk": _object({
            "id": {"type": "string", "pattern": "^chatcmpl-[0-9a-f]{32}$"},
            "object": {"type": "string", "const": "chat.completion.chunk"},
            "created": {"type": "integer"}, "model": {"type": "string"},
            "choices": {"type": "array", "minItems": 0, "maxItems": 1, "items": _object({
                "index": {"type": "integer", "const": 0},
                "delta": _ref("CompatCompletionDelta"),
                "finish_reason": {"type": ["string", "null"]},
            }, ("index", "delta", "finish_reason"), additionalProperties=False)},
            "usage": _nullable(_ref("CompatCompletionUsage")),
        }, ("id", "object", "created", "model", "choices"), additionalProperties=False,
            description="The JSON payload after data: in an SSE event. With include_usage=true, choice chunks have usage=null, followed by a final usage chunk with choices=[]. Without include_usage, usage is absent. The final data: [DONE] marker is not JSON."),
        "CompatOllamaDetails": _object({
            "format": {"type": "string", "const": "configuration"},
            "family": {"type": "string", "const": "connector"},
            "families": {"type": "array", "items": {"type": "string"}, "const": ["connector"]},
            "parameter_size": {"type": "string", "const": ""},
            "quantization_level": {"type": "string", "const": ""},
        }, ("format", "family", "families", "parameter_size", "quantization_level"), additionalProperties=False),
        "CompatOllamaModel": _object({
            "name": {"type": "string"}, "model": {"type": "string"},
            "modified_at": {"type": "string", "format": "date-time"},
            "size": {"type": "integer", "minimum": 0, "description": "Byte length of sorted-key JSON serialization of the routing configuration; this is not a model-weight file size."},
            "digest": {"type": "string", "pattern": "^[0-9a-f]{64}$", "description": "SHA-256 of the serialized routing configuration."},
            "details": _ref("CompatOllamaDetails"),
        }, ("name", "model", "modified_at", "size", "digest", "details"), additionalProperties=False),
        "CompatOllamaModelList": _object({
            "models": {"type": "array", "items": _ref("CompatOllamaModel")},
        }, ("models",), additionalProperties=False),
        "CompatOllamaShowRequest": {
            "type": "object", "additionalProperties": True,
            "properties": {"model": {}, "name": {}},
            "description": "The server selects body.model when truthy, otherwise body.name; the selected value must be a nonempty string identifying an active configuration. model takes precedence over name. Extra fields such as verbose are accepted and ignored.",
            "examples": [{"model": "research-router"}, {"name": "research-router"}],
        },
        "CompatOllamaShowResponse": _object({
            "name": {"type": "string"}, "model": {"type": "string"},
            "details": _ref("CompatOllamaDetails"),
            "model_info": _object({
                "general.architecture": {"type": "string", "const": "connector"},
                "general.name": {"type": "string"},
                "connector.context_length": {"type": "integer", "minimum": 1},
            }, ("general.architecture", "general.name"), additionalProperties=False),
            "parameters": {"type": "string", "description": "num_ctx <context_length> when known, otherwise an empty string."},
            "capabilities": {"type": "array", "items": {"type": "string"}, "const": ["completion", "tools"]},
            "modified_at": {"type": "string", "format": "date-time"},
            "template": {"type": "string", "const": ""},
            "configuration_id": {"type": "string"},
        }, ("name", "model", "details", "model_info", "parameters", "capabilities", "modified_at", "template", "configuration_id"), additionalProperties=False),
        "CompatPropsResponse": _object({
            "service": {"type": "string"}, "version": {"type": "string"},
            "models": {"type": "array", "items": _ref("CompatModel")},
            "default_generation_settings": _object({
                "model": {"type": ["string", "null"], "description": "The sole selected model ID, or null when zero or multiple models are selected."},
                "n_ctx": {"type": "integer", "minimum": 1},
                "params": _object({"n_ctx": {"type": "integer", "minimum": 1}}, ("n_ctx",), additionalProperties=False),
            }, ("model",), additionalProperties=False,
                description="n_ctx and params appear only if every selected configuration has a known context capacity; the minimum capacity is reported."),
            "model_path": {"type": ["string", "null"]},
            "total_slots": {"type": "integer", "const": 1},
            "chat_template": {"type": "string", "const": ""},
            "streaming": {"type": "string", "const": "buffered"},
            "tool_calling": {"type": "boolean", "const": True},
        }, ("service", "version", "models", "default_generation_settings", "model_path", "total_slots", "chat_template", "streaming", "tool_calling"), additionalProperties=False),
        "CompatVersionResponse": _object({
            "version": {"type": "string"}, "service": {"type": "string"},
            "api": {"type": "string", "const": "openai-compatible"},
        }, ("version", "service", "api"), additionalProperties=False),
        "CompatRootResponse": _object({
            "service": {"type": "string"}, "version": {"type": "string"},
            "status": {"type": "string", "const": "ok"},
            "docs": {"type": "string", "const": "/docs"},
            "configurations": {"type": "string", "const": "/api/configs"},
            "models": {"type": "string", "const": "/v1/models"},
            "chat_completions": {"type": "string", "const": "/v1/chat/completions"},
            "active_configurations": {"type": "integer", "minimum": 0},
        }, ("service", "version", "status", "docs", "configurations", "models", "chat_completions", "active_configurations"), additionalProperties=False),
    }
    schemas["CompatCompletionRequest"] = _object({
        "model": {"type": "string", "minLength": 1, "description": "An active configuration model_id returned by GET /v1/models; an underlying provider model name is accepted only when saved as that configuration model_id."},
        "messages": {"type": "array", "minItems": 1, "items": _ref("CompatCompletionMessage")},
        "stream": {"type": "boolean", "default": False, "description": "When true, return buffered SSE after the entire upstream completion has finished."},
        "stream_options": _nullable(_ref("CompatStreamOptions")),
        "tools": {**_nullable({"type": "array", "items": _ref("CompatFunctionTool")}), "description": "Function definitions only. Names must be unique; the gateway returns calls to the caller and never executes them locally."},
        "tool_choice": {"anyOf": [{"type": "string", "enum": ["auto", "none", "required"]}, _ref("CompatNamedToolChoice"), {"type": "null"}],
                        "description": "Defaults to auto when tools are present and none otherwise. required needs at least one tool; a named choice must reference a supplied tool."},
        "parallel_tool_calls": {"type": ["boolean", "null"], "description": "Native Gemini and Ollama cannot guarantee false with enabled tools; such routes are skipped as unsupported."},
        "temperature": {"type": ["number", "null"], "minimum": 0, "maximum": 2},
        "top_p": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
        "max_tokens": {"type": ["integer", "null"], "minimum": 1},
        "max_completion_tokens": {"type": ["integer", "null"], "minimum": 1},
        "stop": {"anyOf": [{"type": "string", "minLength": 1}, {"type": "array", "minItems": 1, "maxItems": 4, "items": {"type": "string", "minLength": 1}}, {"type": "null"}]},
        "response_format": _nullable(_ref("CompatResponseFormat")),
        "seed": {"type": ["integer", "null"]},
        "reasoning_effort": {"type": ["string", "null"], "description": "Accepted for client compatibility. The configured route's reasoning effort is authoritative and takes precedence over this value."},
        "frequency_penalty": {"type": ["number", "null"], "minimum": -2, "maximum": 2},
        "presence_penalty": {"type": ["number", "null"], "minimum": -2, "maximum": 2},
        "n": {"type": "integer", "const": 1, "default": 1},
        "user": {"type": ["string", "null"], "description": "Accepted but not forwarded to completion providers."},
        "metadata": {**_nullable({"type": "object", "additionalProperties": {"type": "string"}}), "description": "Accepted but not forwarded to completion providers."},
        "store": {"type": "boolean", "const": False, "default": False,
                  "description": "Only false is accepted. This field is not forwarded and does not disable the server's own completion-response archive."},
    }, ("model", "messages"), additionalProperties=False, allOf=[{
        "not": {"required": ["max_tokens", "max_completion_tokens"], "properties": {
            "max_tokens": {"type": "integer"}, "max_completion_tokens": {"type": "integer"},
        }},
    }], description="Only declared top-level fields are accepted. Choose at most one non-null token-limit field. Tools must have unique names and tool results must reference an earlier assistant call. Provider-specific constraints may cause explicit configured fallbacks or an unsupported_option error. Numeric options must be finite.")
    return schemas


def _operation(spec: dict, path: str, method: str, summary: str, description: str, aliases=()) -> dict:
    op = spec.setdefault("paths", {}).setdefault(path, {}).setdefault(method, {})
    suffix = re.sub(r"[^a-zA-Z0-9]+", "_", path).strip("_") or "root"
    op["operationId"] = "compat_" + suffix + "_" + method
    op["tags"] = [TAG]
    op["summary"] = summary
    op["description"] = description
    if aliases:
        op["x-canonical-path"] = aliases[0]
        op["x-aliases"] = [alias for alias in aliases if alias != path]
        if path != aliases[0]:
            op["description"] += "\n\nAlias of " + method.upper() + " " + aliases[0] + "."
    return op


def enrich(spec: dict) -> None:
    """Enrich all compatibility operations, including hidden favicon routes."""
    schemas = spec.setdefault("components", {}).setdefault("schemas", {})
    schemas.update(_schemas())
    for path in MODEL_PATHS:
        op = _operation(spec, path, "get", "List active configuration models",
            "Return an OpenAI-style model list containing only saved, active configurations. "
            "Inactive configurations and unsaved provider models are excluded. No active configurations yields data=[]. "
            "Use configuration model_id values in completion requests; this is distinct from the provider catalog at /api/providers/models.", MODEL_PATHS)
        op.setdefault("responses", {})["200"] = _json_response("CompatModelList", "Active configuration models.", {"object": "list", "data": [MODEL_EXAMPLE]})
        detail_path = path + "/{model_id}"
        detail_aliases = tuple(p + "/{model_id}" for p in MODEL_PATHS)
        op = _operation(spec, detail_path, "get", "Retrieve an active configuration model",
            "Look up an active saved configuration by its model_id. Missing, inactive, or deleted configurations return an OpenAI error envelope.", detail_aliases)
        op.setdefault("parameters", [{"name": "model_id", "in": "path", "required": True, "schema": {"type": "string"}}])
        for parameter in op["parameters"]:
            if parameter.get("name") == "model_id":
                parameter["description"] = "An active configuration model_id from the model list."
                parameter["example"] = "research-router"
        op.setdefault("responses", {})["200"] = _json_response("CompatModel", "The requested active configuration model.", MODEL_EXAMPLE)
        op["responses"]["404"] = _error(404, "No active configuration has the requested model_id.", "model_not_found", "Active configuration model 'missing' not found. Save and activate a configuration in /api/configs, then use its model_id.", "model")

    completion_description = (
        "Run one structured assistant turn using an active saved routing configuration. The caller supplies its conversation "
        "and owns any tool-execution loop; this endpoint never executes tools or creates a chat session. The configured system "
        "prompt is prepended, and only explicitly configured routes are attempted, including configured retries and fallbacks. "
        "The response model is the requested configuration model_id.\n\n"
        "With stream=false (default), return application/json. With stream=true, obtain the full upstream result first, then "
        "emit text/event-stream: assistant role; reasoning_content, then content in chunks of at most 256 characters; complete "
        "indexed tool calls; additional provider metadata; an empty delta with finish_reason; an optional usage event; and "
        "data: [DONE]. This is buffered streaming, so provider failures arrive as JSON errors before the stream starts. "
        "include_usage=true adds usage=null to choice events and a final usage event with choices=[].\n\n"
        "Unless server setting completion_no_database_access is enabled, successful JSON responses are archived (including "
        "requests served as SSE), and saved memory may be added to the configured system prompt according to past_memory and "
        "memory-window settings. user and metadata are accepted but discarded; store=false does not control this archive.\n\n"
        "Only function tools are supported. Native Claude rejects seed, frequency_penalty, presence_penalty, and response_format. "
        "Native Gemini rejects frequency_penalty and presence_penalty, cannot guarantee parallel_tool_calls=false with enabled "
        "tools, and rejects strict tool schemas. Native Ollama cannot force required or named tool calls, guarantee "
        "parallel_tool_calls=false with enabled tools, or represent strict tool schemas. Native transports require text-only "
        "content parts and tool argument strings decoding to JSON objects. OpenAI/OpenRouter reasoning routes with an active "
        "non-none effort require temperature=1 or omission. The configured route effort takes precedence over reasoning_effort. "
        "Unsupported routes may fall back to other explicitly configured routes; no implicit mock fallback is added."
    )
    for path in COMPLETION_PATHS:
        op = _operation(spec, path, "post", "Create a structured chat completion", completion_description, COMPLETION_PATHS)
        op["requestBody"] = {"required": True, "content": {"application/json": {
            "schema": _ref("CompatCompletionRequest"), "examples": {
                "text": {"summary": "Plain completion", "value": {"model": "research-router", "messages": [{"role": "user", "content": "Hello"}]}},
                "bufferedStream": {"summary": "Buffered SSE with usage", "value": {"model": "research-router", "messages": [{"role": "user", "content": "Hello"}], "stream": True, "stream_options": {"include_usage": True}}},
                "functionTool": {"summary": "Return a function call for the caller to execute", "value": {"model": "research-router", "messages": [{"role": "user", "content": "Look it up"}], "tools": [TOOL_EXAMPLE], "tool_choice": "required"}},
                "toolResult": {"summary": "Continue after executing a returned tool call", "value": {"model": "research-router", "messages": [
                    {"role": "user", "content": "Look it up"},
                    {"role": "assistant", "content": None, "tool_calls": [{"id": "call_lookup", "type": "function", "function": {"name": "lookup", "arguments": '{"query":"example"}'}}]},
                    {"role": "tool", "tool_call_id": "call_lookup", "content": '{"result":"example item"}'},
                ], "tools": [TOOL_EXAMPLE]}},
            },
        }}}
        op["responses"] = {
            "200": {
                "description": "A single structured completion, or buffered SSE when stream=true.",
                "headers": {
                    "Cache-Control": {"description": "For SSE responses: no-cache.", "schema": {"type": "string", "const": "no-cache"}},
                    "X-Accel-Buffering": {"description": "For SSE responses: no (disable proxy buffering).", "schema": {"type": "string", "const": "no"}},
                },
                "content": {
                    "application/json": {"schema": _ref("CompatCompletionResponse"), "example": deepcopy(COMPLETION_EXAMPLE)},
                    "text/event-stream": {
                        "schema": {"type": "string", "description": "SSE framing: data: <CompatCompletionChunk JSON> followed by two newlines, ending with data: [DONE] followed by two newlines."},
                        "example": _sse_example(),
                        "x-event-schema": _ref("CompatCompletionChunk"),
                    },
                },
            },
            "400": _error(400,
                "Invalid JSON/request validation, malformed messages/tools/options, unsupported options on all available routes, or input context limit exceeded. Pydantic validation is mapped to this OpenAI envelope rather than HTTP 422. Codes: invalid_request_error, unsupported_option, context_length_exceeded (param=messages).",
                "unsupported_option", "Specify either max_tokens or max_completion_tokens, not both."),
            "404": _error(404, "Requested model_id is not an active saved configuration.", "model_not_found", "Active configuration model 'missing' not found. Save and activate a configuration in /api/configs, then use its model_id.", "model"),
            "502": _error(502, "All configured completion routes failed, or a result contained neither text, tool calls, nor a refusal/content-filter outcome. Codes: upstream_error, empty_completion.", "upstream_error", "All configured completion routes failed."),
        }

    for path in TAGS_PATHS:
        op = _operation(spec, path, "get", "List models in Ollama discovery format",
            "Return active configuration models in an Ollama-style discovery envelope. Digest and size describe the serialized routing configuration, not downloaded model weights. This probe does not expose a native Ollama generation endpoint.", TAGS_PATHS)
        op.setdefault("responses", {})["200"] = _json_response("CompatOllamaModelList", "Active configurations in Ollama discovery format.", {"models": [{
            "name": "research-router", "model": "research-router", "modified_at": "2026-01-01T00:00:00+00:00",
            "size": 180, "digest": "0" * 64, "details": OLLAMA_DETAILS_EXAMPLE,
        }]})
    for path in SHOW_PATHS:
        op = _operation(spec, path, "post", "Inspect a model in Ollama discovery format",
            "Select an active configuration by model or name and return Ollama-style discovery metadata. The truthy model field takes precedence over name. Context metadata is omitted when capacity is unknown; advertised capabilities describe gateway completion/tool support and do not guarantee every configured provider supports every option.", SHOW_PATHS)
        op["requestBody"] = {"required": True, "content": {"application/json": {"schema": _ref("CompatOllamaShowRequest"), "examples": {
            "model": {"value": {"model": "research-router"}}, "nameAlias": {"value": {"name": "research-router"}},
        }}}}
        op.setdefault("responses", {})["200"] = _json_response("CompatOllamaShowResponse", "Ollama-style metadata for an active configuration.", {
            "name": "research-router", "model": "research-router", "details": OLLAMA_DETAILS_EXAMPLE,
            "model_info": {"general.architecture": "connector", "general.name": "Research routing", "connector.context_length": 32000},
            "parameters": "num_ctx 32000", "capabilities": ["completion", "tools"],
            "modified_at": "2026-01-01T00:00:00+00:00", "template": "",
            "configuration_id": MODEL_EXAMPLE["configuration_id"],
        })
        op["responses"]["400"] = _error(400, "The selected model/name is absent, empty, or not a string.", "invalid_request_error", "Provide a model (or name) from the active configuration list.", "model")
        op["responses"]["404"] = _error(404, "The selected model/name does not identify an active configuration.", "model_not_found", "Active configuration model 'missing' not found. Save and activate a configuration in /api/configs, then use its model_id.", "model")

    for path in PROPS_PATHS:
        op = _operation(spec, path, "get", "Read llama.cpp-style discovery properties",
            "Return gateway and active-model discovery properties. With a truthy model query, select one active configuration or return 404; with the parameter omitted or empty, select all active configurations. Context capacity is the minimum known capacity across the selected models and is omitted if any selected model has unknown capacity. total_slots is discovery metadata, not a configured concurrency guarantee.", PROPS_PATHS)
        op.setdefault("parameters", [{"name": "model", "in": "query", "required": False, "schema": {"type": ["string", "null"]}}])
        for parameter in op["parameters"]:
            if parameter.get("name") == "model":
                parameter["description"] = "Optional active configuration model_id. An empty value selects all active configurations."
                parameter["example"] = "research-router"
        op.setdefault("responses", {})["200"] = _json_response("CompatPropsResponse", "Discovery properties for the selected active configurations.", {
            "service": "The Connector API", "version": "1.0.0", "models": [MODEL_EXAMPLE],
            "default_generation_settings": {"model": "research-router", "n_ctx": 32000, "params": {"n_ctx": 32000}},
            "model_path": "research-router", "total_slots": 1, "chat_template": "", "streaming": "buffered", "tool_calling": True,
        })
        op["responses"]["404"] = _error(404, "A nonempty model query does not identify an active configuration.", "model_not_found", "Active configuration model 'missing' not found. Save and activate a configuration in /api/configs, then use its model_id.", "model")

    for path in VERSION_PATHS:
        op = _operation(spec, path, "get", "Read compatibility service version",
            "Return the configured gateway application version and service name.", VERSION_PATHS)
        op.setdefault("responses", {})["200"] = _json_response("CompatVersionResponse", "Compatibility service identity.", {"version": "1.0.0", "service": "The Connector API", "api": "openai-compatible"})
    op = _operation(spec, "/", "get", "Read gateway discovery links",
        "Return service identity, API/documentation links, and the number of currently active saved configurations. status=ok is a discovery response; provider and speech readiness are reported by /api/health.")
    op.setdefault("responses", {})["200"] = _json_response("CompatRootResponse", "Gateway discovery document.", {
        "service": "The Connector API", "version": "1.0.0", "status": "ok", "docs": "/docs",
        "configurations": "/api/configs", "models": "/v1/models", "chat_completions": "/v1/chat/completions", "active_configurations": 1,
    })
    for path in ("/favicon.svg", "/favicon.ico"):
        op = _operation(spec, path, "get", "Read gateway favicon",
            "Return the packaged SVG favicon, or a built-in SVG fallback. Both .svg and .ico aliases return image/svg+xml; this operation is intentionally excluded from the backend's default generated schema and added to this comprehensive specification.",
            ("/favicon.svg", "/favicon.ico"))
        op["x-included-by-documentation"] = True
        op["responses"] = {"200": {
            "description": "An SVG favicon, cached publicly for one day.",
            "headers": {"Cache-Control": {"schema": {"type": "string", "const": "public, max-age=86400"}}},
            "content": {"image/svg+xml": {"schema": {"type": "string"}, "example": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7" fill="#10b981"/></svg>'}},
        }}
