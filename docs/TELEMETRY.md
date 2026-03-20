# CodePathfinder Anonymous Telemetry

CodePathfinder collects anonymous usage data to understand how many people install and use the software. This helps prioritize features and ensure the project stays healthy.

**Telemetry is enabled by default.** You can opt out at any time by setting `TELEMETRY_ENABLED=false` in your `.env` file.

---

## What we collect

| Field | Description |
|-------|-------------|
| `installation_id` | Random UUID generated at install time. Not linked to any account or identity. |
| `version` | CodePathfinder version string. |
| `os_type` | Operating system (`linux`, `darwin`, `windows`). |
| `es_mode` | Elasticsearch mode (`local`, `cloud`, or `skip`). |
| `llm_providers_count` | Number of LLM providers configured (integer only — not which providers). |
| `uptime_count` | How many times the service has started (approximate restart counter). |
| `search_count` | Daily count of semantic code searches run. |
| `index_count` | Daily count of indexing jobs started. |
| `mcp_call_counts` | Map of MCP tool name → daily call count (e.g., `{"semantic_code_search": 12}`). |
| `memory_access_count` | Daily count of memory search operations. |

## What we do NOT collect

- IP addresses (used only for rate limiting, never stored)
- Repository names, file paths, or file contents
- Code snippets or search query text
- Usernames, email addresses, or any account information
- Any data from your indexed repositories
- Which LLM providers you use (only a count)

---

## How to opt out

1. Open your `.env` file in the project root
2. Set or add: `TELEMETRY_ENABLED=false`
3. Restart the web service: `docker compose restart web`

Telemetry events are never queued or retried. Opting out takes effect immediately on restart.

## How to re-enable

Set `TELEMETRY_ENABLED=true` in `.env` and restart: `docker compose restart web`

---

## How data is sent

- Events are sent as HTTPS POST requests to `https://codepathfinder.com/telemetry/event`
- Requests are fire-and-forget with a 5-second timeout — no retries
- Failures are silent and never affect application behavior
- Feature usage events are aggregated daily (run `python manage.py send_telemetry_heartbeat`)
- Install events are sent once at the end of `./setup.sh`
- Startup events are sent each time the Django service starts

## Where data is stored

Telemetry data is stored in Elasticsearch on the CodePathfinder production system, in an index named `oss-telemetry-YYYY.MM`. It is not shared with third parties.
