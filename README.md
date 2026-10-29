# The Connector (Headless API Server)

A high-performance, headless FastAPI gateway connecting OpenAI, Anthropic Claude, Google Gemini, OpenRouter, Ollama, and local mock providers into a unified API.

This is a **backend-only, headless distribution** of The Connector:
- **No UI / Frontend dependencies**: No Node.js, npm, or React build tooling required.
- **Kokoro Speech Engine is optional**: The server boots and reports healthy (`status: "ok"`) without requiring Kokoro running, while all speech endpoints (`/api/speech`, `/api/speech/health`, `/api/speech/voices`) remain fully functional if an external Kokoro service is connected.
- **Full Backend API Surface**: 100% of the core backend endpoints are provided, including multi-provider chat routing, session transcripts, OpenAI-compatible `/v1/chat/completions`, Ollama tags/show discovery, agent tool execution, custom skills, sandboxed plugins, and audit logging.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Running the Server](#running-the-server)
  - [Command-Line Flags](#command-line-flags)
  - [PowerShell Launcher](#powershell-launcher)
  - [Stateless High-Throughput Mode](#stateless-high-throughput-mode)
- [Environment Configuration](#environment-configuration)
- [Settings & Storage Layout](#settings--storage-layout)
- [Complete API Reference](#complete-api-reference)
  - [1. System & Health](#1-system--health)
  - [2. OpenAI & Agent Compatibility](#2-openai--agent-compatibility)
  - [3. Chat Sessions & Lifecycle](#3-chat-sessions--lifecycle)
  - [4. Multi-Provider Chat Routing](#4-multi-provider-chat-routing)
  - [5. Saved Configurations & Models](#5-saved-configurations--models)
  - [6. Agent Tools & Autonomous ReAct Loop](#6-agent-tools--autonomous-react-loop)
  - [7. Reusable Skills](#7-reusable-skills)
  - [8. Plugins & Python Environments](#8-plugins--python-environments)
  - [9. Speech Endpoints](#9-speech-endpoints)
  - [10. Storage Settings](#10-storage-settings)
- [Building Standalone Portable Executables](#building-standalone-portable-executables)
- [Running Tests](#running-tests)

---

## Quick Start

### Prerequisites
- Python 3.10+ (Python 3.11 or newer recommended)
- Windows, Linux, or macOS

### 1. Installation

**Windows**:
```cmd
setup.bat
```

**Linux / macOS**:
```bash
./setup.sh
```

The setup script checks for an active virtual environment (or Conda). If none is active, it creates a local `.venv` environment and installs all dependencies from `backend/requirements.txt`. It also automatically seeds `.env` from `.env.example` if not already present.

### 2. Configure API Keys

Edit `.env` to supply API keys for the providers you wish to use:

```env
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=AIzaSy...
OPENROUTER_API_KEY=sk-or-...
OLLAMA_HOST=http://localhost:11434
```

*(Unconfigured providers are automatically flagged as inactive; the offline `mock` provider is always available for zero-credential testing.)*

### 3. Launch the Server

**Windows**:
```cmd
run.bat
```

**Linux / macOS**:
```bash
./run.sh
```

**Direct Python**:
```bash
python run.py --port 8301
```

When started, the server binds to `0.0.0.0:8301` (or `127.0.0.1:8301` with `--local`) and prints:
```text
================================================================
The Connector Headless API Server
Backend:  http://127.0.0.1:8301 (API docs: http://127.0.0.1:8301/docs)
LAN API:  http://192.168.1.50:8301/docs
OpenAI Base URL: http://127.0.0.1:8301/v1
Press Ctrl+C to stop. No UI started.
================================================================
```

The complete OpenAPI 3.1 specification is in [api_doc/openapi.yaml](api_doc/openapi.yaml)
and [api_doc/openapi.json](api_doc/openapi.json). See [api_doc/README.md](api_doc/README.md)
for coverage, regeneration, and validation commands.

---

## Running the Server

### Command-Line Flags

Both `run.py` and `run_backend.py` accept the following arguments:

| Flag | Description | Default |
| --- | --- | --- |
| `--host HOST` | Network interface to bind to (`0.0.0.0` for LAN access) | `0.0.0.0` |
| `--local` | Shortcut for `--host 127.0.0.1` | Loopback only |
| `--port PORT`, `--backend PORT` | Port for the backend API | Saved port or `8301` |
| `--strict-port` | Fail immediately if the port is in use, rather than finding the next available port | Disabled |
| `--reload` | Enable Uvicorn auto-reload on code modifications | Disabled |
| `--completion-no-database-access` | Serve completions in memory without SQLite database operations | Disabled |

### PowerShell Launcher

On Windows, use `run.ps1` for native PowerShell execution:

```powershell
# Run locally on custom port
.\run.ps1 -Local -BackendPort 9000

# Run with development auto-reload
.\run.ps1 -Local -Reload

# Run in database-free high-throughput completion mode
.\run.ps1 -Local -CompletionNoDatabaseAccess
```

### Stateless High-Throughput Mode

For high-throughput agent benchmarks or stateless client loops where you do not need database persistence:
```bash
python run.py --completion-no-database-access
```
Or set `COMPLETION_NO_DATABASE_ACCESS=true` in `.env`.
In this mode:
- Chat completions use routing configurations cached in memory at startup.
- Database reads/writes, saved memory summaries, and completion audit logs are bypassed.
- Streaming SSE and full tool-calling capabilities remain fully functional.

---

## Environment Configuration

Configure your environment via `.env` in the repository root:

```env
# Network Binding
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8301

# Provider API Credentials
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
GOOGLE_API_KEY=
OPENROUTER_API_KEY=
OLLAMA_HOST=http://localhost:11434

# Data & Logging Paths (Defaults to %TEMP%/the_connector on Windows)
DATA_DIR=
DB_PATH=
PLUGIN_DIR=
RESPONSE_LOG_DIR=
RESPONSE_LOGGING_ENABLED=true

# Kokoro Speech (Optional)
KOKORO_BASE_URL=http://localhost:8131
```

---

## Settings & Storage Layout

Default user preferences are stored in:
- **Windows**: `%APPDATA%\the_connector\settings.json`
- **Linux / macOS**: `~/.config/the_connector/settings.json`

Missing port mappings are initialized from [port_mapping.json](port_mapping.json) (`{"connector_port": 8301}`).

### Data Directory Contents

The configured `data_dir` (default: temporary directory) holds:
| Path | Description |
| --- | --- |
| `connector.db` | SQLite database storing sessions, transcripts, skills, configurations, and plugins |
| `plugins/` | Installed plugin packages and dedicated virtual environments |
| `logs/` | JSONL request/response audit logs |
| `python/` | Managed Python virtual environments for agent tool execution |

---

## Complete API Reference

Interactive Swagger UI documentation is available at **`/docs`** (ReDoc at **`/redoc`**).

### 1. System & Health

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/` | Root gateway status with service name, version, and links |
| `GET` | `/api/health` | Readiness probe returning provider status and speech status (`required: false`) |
| `GET` | `/api/version` | Returns service name and API version |
| `GET` | `/docs` | OpenAPI Swagger documentation |

#### Example: `GET /api/health`
```json
{
  "status": "ok",
  "version": "1.0.0",
  "providers_status": {
    "openai": true,
    "claude": true,
    "gemini": true,
    "openrouter": false,
    "ollama_host": "http://localhost:11434",
    "mock": true
  },
  "speech": {
    "required": false,
    "status": "unavailable"
  }
}
```

---

### 2. OpenAI & Agent Compatibility

Expose your saved multi-provider routing configurations directly to external agent frameworks (Hermes, Cursor, AutoGen, OpenDevin, LangChain) using standard OpenAI protocols:

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/v1/chat/completions` | Standard OpenAI chat completion endpoint (supports `stream: true`, tool calling, usage) |
| `GET` | `/v1/models` | List active configuration models |
| `GET` | `/v1/models/{model_id}` | Retrieve details for a specific model |
| `GET` | `/api/tags` | Ollama model tags list |
| `POST` | `/api/show` | Ollama model inspection |
| `GET` | `/v1/props` | Server properties and context capacity |

#### Example: Python `openai` Client
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8301/v1",
    api_key="not-needed",  # Upstream keys are managed by The Connector
)

response = client.chat.completions.create(
    model="fast-hybrid",  # Any active configuration model ID
    messages=[{"role": "user", "content": "Hello!"}],
    stream=True,
)

for chunk in response:
    print(chunk.choices[0].delta.content or "", end="")
```

---

### 3. Chat Sessions & Lifecycle

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/api/sessions` | Create a new session with title, configuration snapshot, and memory settings |
| `GET` | `/api/sessions` | List active chat sessions |
| `GET` | `/api/sessions/{session_id}` | Retrieve full message transcript for a session |
| `PATCH` | `/api/sessions/{session_id}` | Update session configuration snapshot |
| `DELETE` | `/api/sessions/{session_id}` | Close session and purge temporary workspace files |
| `GET` | `/api/sessions/{session_id}/export-zip` | Export session history as a ZIP archive |
| `GET` | `/api/history/export-zip` | Export all session histories across the system as a ZIP |
| `DELETE` | `/api/history` | Permanently wipe all session histories |

---

### 4. Multi-Provider Chat Routing

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/api/chat` | Send a user message to a session; routes via waterfall sequence with automatic fallbacks |

#### Example: `POST /api/chat`
```json
{
  "session_id": "01944e43-a621-72f5-9610-85f269a8b11c",
  "message": "Write a Python function to parse JSON lines."
}
```

---

### 5. Saved Configurations & Models

Configurations define routing sequences, fallback rules, reasoning effort, system prompts, and memory settings:

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/configs` | List all saved configurations (`?active_only=true` supported) |
| `POST` | `/api/configs` | Save a new routing configuration |
| `GET` | `/api/configs/{id}` | Retrieve a specific configuration record |
| `PATCH` | `/api/configs/{id}` | Update a configuration record (activate/deactivate, rename) |
| `DELETE` | `/api/configs/{id}` | Delete a configuration record |
| `GET` | `/api/configs/{id}/download` | Download configuration JSON |
| `GET` | `/api/configuration/detail/{name}` | Fetch configuration by exact display name |
| `GET` | `/api/config-history` | View audit trail of configuration changes |
| `GET` | `/api/config/example` | Download schema-validated template `config.json` |
| `POST` | `/api/config/validate` | Validate a configuration JSON payload without saving |
| `GET` | `/api/providers/models` | List all upstream models supported across all providers |
| `POST` | `/api/models/capabilities` | Inspect reasoning effort options for a specific provider/model |

---

### 6. Agent Tools & Autonomous ReAct Loop

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/agent/tools` | List registered tools and JSON schemas |
| `POST` | `/api/agent/register-tool` | Register a dynamic webhook tool |
| `POST` | `/api/agent/run` | Execute an autonomous multi-step reasoning & tool execution loop |
| `POST` | `/api/agent/step` | Directly execute a single tool call |

---

### 7. Reusable Skills

Store, update, and reuse typed Python skills:

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/skills` | List all persisted coding skills |
| `POST` | `/api/skills` | Create and register a skill |
| `POST` | `/api/skills/from-conversation` | Synthesize a new skill from conversational context |
| `GET` | `/api/skills/export` | Export skills library as JSON file |
| `POST` | `/api/skills/import` | Import skills from JSON with conflict resolution |
| `PATCH` | `/api/skills/{id}` | Edit an existing skill |
| `DELETE` | `/api/skills/{id}` | Delete a skill |

---

### 8. Plugins & Python Environments

Install and manage self-contained Python plugins:

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/plugins` | List installed plugins and runtime states |
| `POST` | `/api/plugins/install` | Upload and unpack a `plugin.zip` (`Content-Type: application/zip`) |
| `POST` | `/api/plugins/{id}/enable` | Start plugin backend and register its agent tools |
| `POST` | `/api/plugins/{id}/disable` | Stop plugin backend |
| `DELETE` | `/api/plugins/{id}` | Uninstall plugin and wipe isolated virtualenv |
| `GET`/`POST` | `/api/plugins/{id}/proxy/...` | Reverse-proxy requests to the plugin backend |
| `GET` | `/api/python-environments` | List managed Python execution environments |
| `POST` | `/api/python-environments` | Provision a new virtual environment |
| `POST` | `/api/python-environments/{id}/select` | Set the active execution environment |

---

### 9. Speech Endpoints

Optional speech synthesis integration (Kokoro-compatible):

| Method | Endpoint | Description |
| --- | --- | --- |
| `POST` | `/api/speech` | Synthesize plain text into a WAV audio response |
| `GET` | `/api/speech/health` | Check health of the speech subsystem |
| `GET` | `/api/speech/voices` | List available voice actors |

---

### 10. Storage Settings

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/settings` | Get current data folder, defaults, and configuration path |
| `PATCH` | `/api/settings` | Update storage directory (`{"data_dir": "D:/ConnectorData"}`) |

---

## Building Standalone Portable Executables

You can package The Connector into self-contained Windows distributions using PyInstaller:

```cmd
build.bat
```
Or directly:
```bash
python build.py
```

This generates two isolated packages in `dist/`:
- **`dist\Debug`**: Preconfigured for local loopback access (`127.0.0.1:8301`).
- **`dist\Release`**: Preconfigured for local network access (`0.0.0.0:8301`).

Each folder contains:
- `server.exe` (standalone binary)
- `run.bat` (automated launcher)
- `port_mapping.json` (port preferences)
- `runtime.json` (host profile)
- `config.json` (initial routing config)

---

## Running Tests

Run the full pytest suite (660+ tests):

```powershell
$env:PYTHONPATH="." ; .\.venv\Scripts\pytest.exe backend/tests/
```
Or on Linux/macOS:
```bash
PYTHONPATH="." pytest backend/tests/
```
