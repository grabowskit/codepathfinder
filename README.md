# CodePathfinder

[![License: Elastic License 2.0](https://img.shields.io/badge/License-Elastic%20License%202.0-blue.svg)](LICENSE)

A semantic code indexing, search, and AI-powered chat platform. Index GitHub repositories, search code by intent using semantic embeddings, and interact with your codebase through an AI assistant powered by LibreChat and the Model Context Protocol (MCP).

## Architecture

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   Browser    │────▶│   Nginx (local)  │────▶│  Django Web App  │
│              │     │   Load Balancer  │     │  (gunicorn)      │
└──────────────┘     │   (production)   │     └────────┬─────────┘
                     └──────────────────┘              │
                                                       │ MCP (Streamable HTTP)
                     ┌──────────────────┐              │
                     │    LibreChat     │◀─────────────┘
                     │  (AI Chat UI)    │     ┌────────┴─────────┐
                     └──────────────────┘     │   Elasticsearch  │
                                              │   (ELSER model)  │
┌──────────────┐     ┌──────────────────┐     └──────────────────┘
│    GitHub    │◀────│  Node.js Indexer  │
│ Repositories │     │  (Tree-sitter)   │
└──────────────┘     └──────────────────┘
```

**Key components:**

- **Django Web App** — Project management, user auth, API keys, MCP server, job orchestration
- **LibreChat** — AI chat interface with multi-model support (Claude, GPT, Gemini, etc.)
- **MCP Server** — 21 tools exposed via Model Context Protocol (code search, GitHub ops, skills, jobs)
- **Node.js Indexer** — Clones repos, parses code with Tree-sitter, indexes into Elasticsearch
- **Elasticsearch** — Semantic search with ELSER (Elastic Learned Sparse Encoder)

## Quick Start

### Prerequisites

- **Required:** Docker & Docker Compose v2, Git, openssl
- **Optional:** [mkcert](https://github.com/FiloSottile/mkcert) — enables local HTTPS (recommended)
  ```bash
  # macOS
  brew install mkcert && mkcert -install
  ```

### One-Command Setup

```bash
git clone https://github.com/grabowskit/codepathfinder.git
cd codepathfinder
./setup.sh
```

The interactive setup script guides you through the full stack in one command:

1. Checks prerequisites (Docker, openssl, mkcert)
2. Prompts for Elasticsearch mode, LLM providers, OAuth, and GitHub token
3. Auto-generates all secrets (no Python required on host)
4. Writes `.env`, `chat-config/.env`, and `indexer/.env`
5. Creates Docker volumes/network and generates mkcert SSL certs
6. Builds and starts all services
7. Runs database migrations and creates your admin account
8. Configures LibreChat OIDC SSO automatically
9. Shows a health check table and service URLs

**Common flags:**

| Flag | Description |
|------|-------------|
| `--skip-build` | Skip `docker compose build` (use cached images) |
| `--skip-start` | Generate config files only — don't start services |
| `--non-interactive` | Read all answers from `SETUP_*` env vars or `answers.conf` |

> Re-running `./setup.sh` is safe — existing secrets are preserved and current `.env` values are shown as defaults.

### Service URLs (after setup)

With HTTPS (mkcert available):

| Service         | URL                         | Description                    |
|-----------------|-----------------------------|--------------------------------|
| CodePathfinder  | https://localhost:8443      | Main UI (projects, admin, docs)|
| LibreChat       | https://localhost:3443      | AI chat with MCP tools         |
| Kibana          | http://localhost:5601       | Elasticsearch dashboard        |

Without HTTPS:

| Service         | URL                         | Description                    |
|-----------------|-----------------------------|--------------------------------|
| CodePathfinder  | http://localhost:8000       | Main UI (projects, admin, docs)|
| LibreChat       | http://localhost:3080       | AI chat with MCP tools         |
| Kibana          | http://localhost:5601       | Elasticsearch dashboard        |

> **Note**: New accounts are inactive by default. Log in as the superuser to activate them, or check `docker compose logs web` for the approval link.

### LLM Providers

`setup.sh` prompts for LLM API keys but they are **optional** — LibreChat starts without them. You can add keys later:

1. Edit `chat-config/.env` with your API key(s)
2. `docker compose restart librechat`

Supported providers: OpenAI, Anthropic, Azure OpenAI, Google Gemini, AWS Bedrock.

See [docs/LOCAL_DEV.md](docs/LOCAL_DEV.md) for full setup details including manual configuration and troubleshooting.

## Features

### Semantic Code Search
- Index GitHub repositories (public and private) with Tree-sitter parsing
- Search code by intent using Elasticsearch ELSER semantic embeddings
- Supports TypeScript, JavaScript, Python, Java, C++, Go, Rust, Ruby, PHP, C#, Swift, and more

### AI Chat (via LibreChat)
- Chat with your codebase through LibreChat at `/chat/`
- Multi-model support: Claude, GPT, Gemini, and more via LibreChat's model config
- All models have access to CodePathfinder MCP tools by default

### MCP Server (21 Tools)
The MCP server at `/mcp/` implements the MCP 2025-06-18 Streamable HTTP specification:

| Category         | Tools |
|------------------|-------|
| **Code Search**  | `semantic_code_search`, `map_symbols_by_query`, `size`, `symbol_analysis`, `read_file_from_chunks`, `document_symbols` |
| **GitHub**       | `github_create_issue`, `github_get_labels`, `github_add_comment`, `github_create_pull_request`, `github_create_branch`, `github_list_branches`, `github_get_repo_info` |
| **Skills**       | `skills_list`, `skills_get`, `skills_search`, `skills_sync`, `skills_import`, `skills_activate` |
| **Jobs**         | `job_manage`, `job_status` |
| **OTel**         | `otel_configure_collection`, `otel_get_onboarding_config`, `otel_query_traces`, `otel_query_metrics`, `otel_query_logs` |

**Authentication** (in priority order):
1. Internal service secret (`CPF_INTERNAL_SERVICE_SECRET` header) — used by LibreChat
2. Project API keys (`cpf_`-prefixed Bearer tokens) — for external integrations
3. OAuth2 access tokens — for programmatic access

A legacy SSE transport is also available at `/mcp/sse/` (MCP 2024-11-05 spec).

### Connecting Claude Desktop

CodePathfinder integrates directly with Claude Desktop via the Model Context Protocol (MCP).

**Option 1: OAuth (Recommended)**

1. Open Claude Desktop → **Settings → Connectors**
2. Click **Add Connector** → **Custom**
3. Enter the URL: `https://your-domain.com/mcp`
4. Click **Add** — Claude will redirect you to authorize
5. Log in and click **Authorize**

**Option 2: API Key**

Generate a project-scoped API key from the **API Keys** page. See [docs/CLAUDE-DESKTOP-SETUP.md](docs/CLAUDE-DESKTOP-SETUP.md) for details.

#### Project-Scoped Search

All search tools support **project scoping** for multi-project workflows:

- **Default:** Searches all projects you have access to
- **Specific:** Use the `projects` parameter: `semantic_code_search(query="auth logic", projects=["backend"])`

### Skills System

Skills are reusable instructions that configure the AI agent's behavior for specific tasks. They can be:
- **Global** — shared across all users (admin-managed)
- **Personal** — user-owned, optionally forked from global skills, synced from a personal GitHub repo

### Project Management
- Create, edit, clone, and share indexing projects
- Start/stop indexing jobs
- Real-time status tracking with auto-refresh
- Per-project API key generation for MCP access

### User Management
- Google OAuth and email/password registration
- Admin approval workflow (new users start inactive)
- Superuser admin panel for user management

## Project Structure

```
codepathfinder/
├── setup.sh                      # Interactive setup script (start here!)
├── web/                          # Django web application
│   ├── CodePathfinder/           # Django settings and root URLs
│   ├── core/                     # User auth, admin, system settings
│   ├── projects/                 # Project management, job orchestration
│   ├── chat/                     # LibreChat OIDC redirect
│   ├── mcp_server/               # MCP server (streamable HTTP + SSE)
│   │   ├── streamable.py         # Primary MCP endpoint (/mcp/)
│   │   ├── views.py              # Legacy SSE + OAuth dashboard
│   │   └── tools.py              # Tool definitions and handlers
│   ├── api/                      # REST API endpoints
│   ├── skills/                   # AI agent skills system
│   ├── otel_ingest/              # OpenTelemetry ingest proxy
│   ├── templates/                # Django templates
│   └── static/                   # CSS, JS assets
├── indexer/                      # Node.js semantic code indexer (submodule)
├── chat/                         # LibreChat (submodule)
├── chat-config/
│   └── librechat.yaml            # LibreChat config (models, MCP, presets)
├── kubernetes/                   # K8s deployment manifests (GCP reference)
│   ├── deployment.yaml           # Web app deployment
│   ├── cronjob-status-checker.yaml
│   └── librechat/                # LibreChat K8s manifests
├── scripts/
│   ├── deploy.sh                 # GCP production deployment
│   ├── setup.sh                  # Forwarder → ./setup.sh
│   └── smoke_test.py             # Smoke test suite
├── tests/                        # Test suite
├── nginx/                        # Nginx config (local dev HTTPS)
├── docker-compose.yml            # Local development stack
├── Dockerfile.prod               # Production web image
└── docs/                         # Documentation
```

## Documentation

| Document | Description |
|----------|-------------|
| [docs/LOCAL_DEV.md](docs/LOCAL_DEV.md) | Local development setup |
| [docs/PROJECT_DOCUMENTATION.md](docs/PROJECT_DOCUMENTATION.md) | Full architecture, API reference, database schema |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | GCP/GKE production deployment guide |
| [docs/CLAUDE-DESKTOP-SETUP.md](docs/CLAUDE-DESKTOP-SETUP.md) | Claude Desktop MCP setup |
| [docs/SMOKE_TESTS.md](docs/SMOKE_TESTS.md) | Smoke test documentation |
| [docs/MCP-CONNECTOR-SETUP.md](docs/MCP-CONNECTOR-SETUP.md) | MCP connector configuration |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common issues and solutions |

## Tech Stack

| Layer          | Technology                                    |
|----------------|-----------------------------------------------|
| Backend        | Django 4.2, Python 3.9, gunicorn              |
| Chat           | LibreChat (Claude, GPT, Gemini, and more)     |
| Indexer        | Node.js 20, TypeScript, Tree-sitter           |
| Database       | PostgreSQL 15                                 |
| Search         | Elasticsearch 9.x with ELSER                  |
| Infrastructure | Docker, Kubernetes, Nginx                     |
| Supporting     | MongoDB (LibreChat), Meilisearch (LibreChat)  |

## Development

```bash
# View logs
docker-compose logs -f web

# Run migrations
docker-compose exec web python manage.py migrate

# Run tests
docker-compose exec web python manage.py test

# Run smoke tests
python scripts/smoke_test.py
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to contribute.

## License

CodePathfinder is licensed under the [Elastic License 2.0](LICENSE).

**In summary:**
- Free to use, modify, and self-host
- You may NOT offer CodePathfinder as a hosted/managed service to third parties without a commercial license

For commercial licensing inquiries, contact [hello@codepathfinder.com](mailto:hello@codepathfinder.com).
