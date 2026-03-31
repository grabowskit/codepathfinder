# CodePathfinder Smoke Tests

This document describes the end-to-end smoke test suite for validating that all CodePathfinder services are running correctly.

## Overview

The smoke test suite validates:
- **Service Health** - All Docker services are up and responding
- **Authentication** - Login, API keys, and internal service secrets work
- **Projects** - Project listing and management via MCP
- **MCP Protocol** - JSON-RPC endpoints, tool discovery, and tool execution
- **LibreChat Integration** - LibreChat can connect to CodePathfinder MCP
- **OAuth2** - OAuth metadata and authorization endpoints

## Quick Start

### Run All Tests

```bash
# Set your Elasticsearch password
export ELASTICSEARCH_PASSWORD=your_es_password

# Run all smoke tests
python scripts/smoke_test.py
```

### Run Specific Category

```bash
python scripts/smoke_test.py --category health    # Service health only
python scripts/smoke_test.py --category auth      # Authentication only
python scripts/smoke_test.py --category mcp       # MCP protocol only
python scripts/smoke_test.py --category projects  # Project management only
python scripts/smoke_test.py --category librechat # LibreChat integration only
python scripts/smoke_test.py --category oauth     # OAuth2 endpoints only
```

### Verbose Output with Timing

```bash
python scripts/smoke_test.py -v --timing
```

### JSON Output (for CI/CD)

```bash
python scripts/smoke_test.py --output json
# Results saved to smoke_results.json
```

## Using the Slash Command

If using Claude Code, you can run smoke tests with:

```
/smoke           # Run all tests
/smoke health    # Health checks only
/smoke mcp       # MCP tests only
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SMOKE_TEST_BASE_URL` | `https://localhost:8443` | Base URL for web service |
| `SMOKE_TEST_ES_URL` | `http://localhost:9200` | Elasticsearch URL |
| `ELASTICSEARCH_PASSWORD` | `changeme` | Elasticsearch password |
| `CPF_INTERNAL_SERVICE_SECRET` | `default_internal_secret_change_me` | Internal service auth |
| `SMOKE_TEST_LIBRECHAT_URL` | `http://localhost:3080` | LibreChat URL |
| `SMOKE_TEST_KIBANA_URL` | `http://localhost:5601` | Kibana URL |
| `SMOKE_TEST_MEILISEARCH_URL` | `http://localhost:7700` | MeiliSearch URL |

## Test Categories

### Health Tests (`test_health.py`)

| Test | Description |
|------|-------------|
| `test_web_health` | Django `/health/` endpoint responds |
| `test_elasticsearch_health` | ES cluster status is green/yellow |
| `test_kibana_health` | Kibana is accessible |
| `test_db_health` | PostgreSQL accepts connections on 5432 |
| `test_mongodb_health` | MongoDB accepts connections on 27017 |
| `test_meilisearch_health` | MeiliSearch `/health` responds |

### Authentication Tests (`test_auth.py`)

| Test | Description |
|------|-------------|
| `test_login_page_loads` | Login page is accessible |
| `test_login_redirect_unauthenticated` | Protected pages redirect to login |
| `test_api_key_authentication_mcp` | Internal secret authenticates MCP |
| `test_invalid_api_key_rejected` | Invalid keys return 401 |
| `test_missing_auth_rejected` | Missing auth returns 401 |
| `test_malformed_bearer_token_rejected` | Malformed tokens rejected |
| `test_wrong_auth_scheme_rejected` | Non-Bearer schemes rejected |

### MCP Protocol Tests (`test_mcp.py`)

| Test | Description |
|------|-------------|
| `test_mcp_initialize` | Returns protocol version 2025-06-18 |
| `test_mcp_tools_list` | Returns 10+ available tools |
| `test_mcp_ping` | Ping returns empty result |
| `test_mcp_resources_list` | Resources endpoint works |
| `test_mcp_tool_call_job_status` | Can execute job_status tool |
| `test_mcp_invalid_method` | Unknown methods return error |
| `test_mcp_invalid_tool` | Unknown tools return error |
| `test_mcp_cors_options` | CORS headers on OPTIONS |
| `test_mcp_jsonrpc_format` | Responses follow JSON-RPC 2.0 |

### Project Tests (`test_projects.py`)

| Test | Description |
|------|-------------|
| `test_projects_page_requires_auth` | Projects page requires login |
| `test_job_list_via_mcp` | Can list jobs via MCP tool |
| `test_job_status_action` | job_status tool works |
| `test_size_tool_returns_stats` | size tool returns index stats |
| `test_api_projects_endpoint` | REST API endpoint exists |
| `test_project_creation_requires_auth` | Creating projects requires auth |

### LibreChat Tests (`test_librechat.py`)

| Test | Description |
|------|-------------|
| `test_librechat_health` | LibreChat responds on port 3080 |
| `test_librechat_api_health` | `/api/health` endpoint works |
| `test_librechat_can_reach_mcp` | MCP reachable with internal secret |
| `test_librechat_mcp_tools_available` | Tools discoverable via MCP |

### OAuth2 Tests (`test_oauth.py`)

| Test | Description |
|------|-------------|
| `test_oauth_protected_resource_metadata` | RFC 9728 metadata endpoint |
| `test_oauth_authorization_server_metadata` | RFC 8414 metadata endpoint |
| `test_oauth_authorize_endpoint` | `/o/authorize/` exists |
| `test_oauth_token_endpoint` | `/o/token/` accepts requests |
| `test_oauth_dcr_endpoint` | Dynamic Client Registration works |

## Running in Docker

To run smoke tests from inside the Docker container:

```bash
docker-compose exec web python scripts/smoke_test.py -v
```

Note: When running inside Docker, services are accessible via internal Docker DNS names, so you may need to adjust URLs:

```bash
docker-compose exec web python scripts/smoke_test.py \
  --base-url http://web:8000
```

## Interpreting Results

### All Passing

```
======================== 38 passed, 1 skipped in 1.44s =========================
STATUS: ALL SMOKE TESTS PASSING
```

### Some Failures

```
FAILED tests/smoke/test_health.py::TestServiceHealth::test_elasticsearch_health
=================== 2 failed, 36 passed, 1 skipped in 1.48s ====================
STATUS: SOME TESTS FAILED (exit code: 1)
```

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| ES health fails with 401 | Wrong password | Set `ELASTICSEARCH_PASSWORD` |
| MCP tests timeout | Services not running | Run `docker-compose up -d` |
| Connection refused | Wrong URL | Check `SMOKE_TEST_BASE_URL` |
| LibreChat tests skip | LibreChat not running | Start LibreChat service |

## Debugging Failed Tests

1. **Check service status:**
   ```bash
   docker-compose ps
   ```

2. **Check service logs:**
   ```bash
   docker-compose logs web
   docker-compose logs elasticsearch
   ```

3. **Run specific failing test with verbose output:**
   ```bash
   pytest tests/smoke/test_mcp.py::TestMCPProtocol::test_mcp_initialize -v
   ```

4. **Test MCP endpoint directly:**
   ```bash
   curl -k -X POST "https://localhost:8443/mcp/" \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer $CPF_INTERNAL_SERVICE_SECRET" \
     -d '{"jsonrpc":"2.0","id":1,"method":"ping","params":{}}'
   ```

## File Structure

```
pathfinder/
├── tests/
│   └── smoke/
│       ├── __init__.py
│       ├── conftest.py          # Pytest fixtures
│       ├── test_health.py       # Service health tests
│       ├── test_auth.py         # Authentication tests
│       ├── test_projects.py     # Project management tests
│       ├── test_mcp.py          # MCP protocol tests
│       ├── test_librechat.py    # LibreChat integration tests
│       └── test_oauth.py        # OAuth2 endpoint tests
├── scripts/
│   └── smoke_test.py            # CLI runner
├── .claude/
│   └── commands/
│       └── smoke.md             # Slash command definition
└── pytest.ini                   # Pytest configuration
```

## Adding New Tests

1. Add tests to the appropriate file in `tests/smoke/`
2. Mark tests with `@pytest.mark.smoke` and category marker (e.g., `@pytest.mark.health`)
3. Use fixtures from `conftest.py` for URLs and authentication

Example:

```python
import pytest

@pytest.mark.smoke
@pytest.mark.health
class TestNewService:
    def test_new_service_health(self, base_url, http_client):
        """New service responds."""
        response = http_client.get(f"{base_url}/new-service/health")
        assert response.status_code == 200
```

## CI/CD Integration

For automated testing in CI/CD pipelines:

```yaml
# Example GitHub Actions step
- name: Run Smoke Tests
  run: |
    python scripts/smoke_test.py --output junit
  env:
    ELASTICSEARCH_PASSWORD: ${{ secrets.ES_PASSWORD }}
    CPF_INTERNAL_SERVICE_SECRET: ${{ secrets.INTERNAL_SECRET }}

- name: Upload Test Results
  uses: actions/upload-artifact@v3
  with:
    name: smoke-test-results
    path: smoke_results.xml
```
