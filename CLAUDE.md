# CodePathfinder

## Purpose
Semantic code search platform that indexes repositories, combines skills/tools/documentation,
and enables AI-powered discovery of best practices for building applications.
Stack: Django + Elasticsearch + Tree-sitter + LibreChat + OpenTelemetry, deployed on GKE.

## Project Tree
```
web/                  # Django backend — API, MCP server, OTel ingest, auth, models
  core/               # Auth, middleware, signals, OAuth, user management
  api/                # REST endpoints, job queue integration
  projects/           # Repo management, GitHub integration, indexing
  mcp_server/         # MCP tools (semantic search, skills, OTel queries)
  otel_ingest/        # OpenTelemetry data pipeline
  skills/             # Skills CRUD and management
  chat/               # Chat UI, artifacts, Kibana integration
  documents/          # Document management
indexer/              # Node.js semantic code indexer (tree-sitter + ES)
mcp-bridge/           # TypeScript MCP bridge (streamable HTTP)
chat/                 # LibreChat submodule (React + Express)
skills/               # Shared skills repository (git submodule, 26 skills)
kubernetes/           # GKE manifests (web, otel-collector, librechat/, ingress, rbac)
otel-collector/       # OTel collector config (traces/metrics/logs → ES)
chat-config/          # librechat.yaml (LLM providers), .env
scripts/              # deploy.sh, smoke_test.py, setup-kibana scripts
docs/                 # 44 guides: deployment, features, integrations, ops
nginx/                # Local HTTPS proxy config
docker-compose.yml    # Local dev: 9 services
Dockerfile.prod       # Multi-stage production build
setup.sh              # One-command interactive setup (1135 lines)
```

## Rules of Engagement
1. **Read before writing.** Always read a file before editing it. Understand existing patterns first.
2. **Prefer editing over creating.** Modify existing files rather than adding new ones.
3. **No secrets in code.** Never commit API keys, passwords, or credentials. They live in K8s secrets.
4. **Test after changes.** Run `python -m pytest` (Django) or `npm test` (indexer) after modifications.
5. **Migrations matter.** After model changes: `python manage.py makemigrations && python manage.py migrate`.
6. **Deploy carefully.** `scripts/deploy.sh` only sets the image — env var changes need `kubectl apply`.
7. **Keep it simple.** No over-engineering, no speculative abstractions, no premature optimization.
8. **Match conventions.** Follow existing code style in each component (Python/Django, TypeScript/Node).
9. **MCP tools go in** `web/mcp_server/tools.py`. Skills go in `skills/skills/`. Docs go in `docs/`.
10. **OTel kill switch.** Set `OTEL_ENABLED=false` to disable all instrumentation if needed.

## Local Dev Quick Start
```bash
./setup.sh                          # Full interactive setup
docker compose up -d                # Start services
# Web: http://localhost:8000  Chat: http://localhost:3080  Kibana: http://localhost:5601
```

## Key Endpoints
- `/api/` — REST API
- `/mcp/` — MCP server (LibreChat connects here)
- `/health/` — Health probe
- `/admin/` — Django admin

## Deployment

### Production (GCP/GKE)
```bash
scripts/deploy.sh v1.5.0              # Build, push, rollout web image
kubectl exec $POD -n codepathfinder -c web -- python manage.py migrate  # Post-deploy
```
- `deploy.sh` only does `kubectl set image` — env/config changes need `kubectl apply -f kubernetes/deployment.yaml`
- Full GCP setup guide: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

### OSS Release (public GitHub)
```bash
git log --oneline oss-release..main   # See unported commits
git checkout oss-release && git cherry-pick <hash>  # Port commit
git diff HEAD~1 | grep -E "wired-sound|codepathfinder\.com|grabowskit"  # Scan for prod refs
# Sanitize → <YOUR_*> placeholders, then sync to public repo
git archive oss-release | tar -xf - -C /tmp/codepathfinder-public
```
- `main` = dev/staging (has prod values), `oss-release` = sanitized public
- Cherry-pick, never merge. Sanitize each commit individually.
- Full checklist: [docs/OSS-RELEASE-WORKFLOW.md](docs/OSS-RELEASE-WORKFLOW.md)

## Notes Protocol
When working on this project, follow these rules for taking notes:

**When to write notes:**
- After discovering a non-obvious gotcha or workaround
- After making an architectural decision or trade-off
- After a debugging session reveals root cause of a recurring issue
- When a deployment or migration has side effects worth remembering

**Where to write them:**
- Update `~/.claude/projects/-Users-grabowskit-dev-pathfinder/memory/MEMORY.md` for high-level facts
- Create topic files in that same directory (e.g., `debugging.md`, `migrations.md`) for detailed notes
- Link new topic files from MEMORY.md

**How to format:**
- Use `## Section` headers grouped by domain (infra, app, indexer, otel, skills)
- Keep entries to 1-3 lines with specific file paths, commands, or error messages
- Include the date when the note was written
- Delete or update notes that become stale

**When to create a new context file:**
- When a topic has 5+ related notes that clutter MEMORY.md
- When a debugging session produces detailed steps worth preserving
- When a new subsystem (e.g., a new integration) needs its own reference doc
