# Contributing to CodePathfinder

Thank you for your interest in contributing! This guide covers how to set up your development environment, submit changes, and work with the codebase.

## License

By contributing to CodePathfinder, you agree that your contributions will be licensed under the [Elastic License 2.0](LICENSE). Please read the license before contributing.

## Getting Started

### 1. Fork and clone the repository

```bash
git clone --recurse-submodules https://github.com/<your-org>/codepathfinder.git
cd codepathfinder
```

### 2. Set up local development

Follow [docs/LOCAL_DEV.md](docs/LOCAL_DEV.md) for a complete local setup with Docker Compose.

Quick start:
```bash
cp .env.example .env
# Edit .env with your Elasticsearch credentials
docker-compose up
```

### 3. Run existing tests

```bash
# Django tests
docker-compose exec web python manage.py test

# Smoke tests (requires running services)
python scripts/smoke_test.py
```

## How to Contribute

### Bug Reports

Open an issue with:
- A clear title and description
- Steps to reproduce
- Expected vs actual behavior
- Version/environment details

### Feature Requests

Open an issue tagged `enhancement` before starting work. Discuss the approach to avoid duplicate effort.

### Pull Requests

1. Create a branch from `main`: `git checkout -b feature/your-feature-name`
2. Make your changes with focused, atomic commits
3. Run tests: `docker-compose exec web python manage.py test`
4. Open a PR against `main` with a clear description of what changed and why

### Code Style

- **Python**: Follow PEP 8. Keep functions small and focused.
- **Django**: Use class-based views, prefer Django ORM over raw SQL.
- **Templates**: Keep logic in views, not templates.
- **Tests**: Add tests for new behavior. We use Django's built-in `TestCase`.

## Architecture Overview

- `web/` — Django application
  - `core/` — User auth, admin, system settings
  - `projects/` — Project management and indexing orchestration
  - `mcp_server/` — MCP protocol implementation (Claude Desktop integration)
  - `api/` — REST API endpoints
  - `chat/` — LibreChat integration (OIDC redirect)
  - `skills/` — AI agent skills system
  - `otel_ingest/` — OpenTelemetry ingest proxy
- `indexer/` — Elastic semantic code search indexer (submodule)
- `chat/` — LibreChat (submodule)
- `kubernetes/` — K8s deployment manifests (GCP reference)
- `docs/` — Documentation

## Commercial Use

CodePathfinder is licensed under the [Elastic License 2.0](LICENSE). If you want to offer CodePathfinder as a hosted or managed service, or include it in a commercial product, you'll need a commercial license. Reach out at [hello@codepathfinder.com](mailto:hello@codepathfinder.com).
