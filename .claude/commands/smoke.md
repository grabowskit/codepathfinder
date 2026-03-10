---
description: Run CodePathfinder smoke tests to verify all services are up
allowed-tools: Bash, Read
---

# Smoke Test Runner

Run the CodePathfinder end-to-end smoke test suite to verify that all services are running correctly.

## Arguments

The user may optionally specify a test category:
- `health` - Service health checks (PostgreSQL, Elasticsearch, Kibana, MongoDB, MeiliSearch)
- `auth` - Authentication tests (login, API keys, internal secret)
- `projects` - Project management tests
- `mcp` - MCP protocol tests (initialize, tools/list, tool calls)
- `librechat` - LibreChat integration tests
- `oauth` - OAuth2 endpoint tests
- `all` - Run all tests (default)

## Instructions

1. Parse the user's input to determine which category to run. If no category specified, use "all".

2. Run the smoke test script with the appropriate category:

```bash
cd /Users/grabowskit/dev/pathfinder && python scripts/smoke_test.py --category <CATEGORY> -v --timing
```

3. Report the results clearly:
   - Show which tests passed/failed
   - For failures, show the error message
   - Provide a summary at the end

4. If tests fail, offer to help diagnose the issue by:
   - Checking if Docker services are running: `docker-compose ps`
   - Checking service logs: `docker-compose logs <service>`
   - Verifying environment variables

## Example Usage

User: `/smoke`
-> Runs all smoke tests

User: `/smoke health`
-> Runs only health check tests

User: `/smoke mcp`
-> Runs only MCP protocol tests
