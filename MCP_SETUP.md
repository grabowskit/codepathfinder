# MCP Server Setup Guide

This document explains how Notion and Linear MCP servers are configured for LibreChat with user-provided authentication.

## Overview

You now have **self-hosted MCP servers** that allow LibreChat users to connect directly to their Notion and Linear accounts using their own API credentials. This eliminates the need for Anthropic's hosted MCP servers and gives users full control over their data.

## Architecture

### Before (Anthropic-Hosted)
```
LibreChat → Anthropic's MCP Server → Notion/Linear API
           (requires Anthropic account)
```

### After (Self-Hosted)
```
LibreChat → Your MCP Server Container → Notion/Linear API
           (user provides their own tokens)
```

## What Changed

### 1. Added MCP Server Containers

**docker-compose.yml** now includes:
- `notion-mcp` (port 3001) - Notion MCP server
- `linear-mcp` (port 3002) - Linear MCP server

### 2. Updated LibreChat Configuration

**chat-config/librechat.yaml** now configures:
- **Notion MCP**: Connects to `http://notion-mcp:3000/mcp` with user-provided `NOTION_TOKEN`
- **Linear MCP**: Connects to `http://linear-mcp:3000/mcp` with user-provided `LINEAR_API_TOKEN`
- **Custom User Variables**: Each user provides their own API credentials through LibreChat UI

### 3. User Authentication Flow

1. User selects a Claude model in LibreChat
2. User sees "Notion" and "Linear" in the MCP servers list
3. User clicks the settings icon next to each server
4. User pastes their API token (created separately in Notion/Linear)
5. LibreChat encrypts and stores the token per-user
6. When the user chats, LibreChat sends their token to the MCP server
7. MCP server uses the token to access Notion/Linear API

## Getting Started

### 1. Build and Start the Services

```bash
cd /Users/grabowskit/dev/pathfinder

# Build the new MCP server containers
docker compose build notion-mcp linear-mcp

# Start all services
docker compose up -d

# Verify MCP servers are running
./mcp-servers/test-mcp.sh
```

### 2. Test MCP Connectivity

```bash
# Check Notion MCP
curl http://localhost:3001/health

# Check Linear MCP
curl http://localhost:3002/health
```

Expected response: `{"status":"ok",...}`

### 3. User Setup Instructions

Share these instructions with your LibreChat users:

#### For Notion:
1. Visit https://www.notion.so/profile/integrations
2. Create a new integration
3. Copy the "Internal Integration Secret" (starts with `ntn_`)
4. In Notion, connect pages to your integration via page settings
5. In LibreChat, configure the Notion MCP server with your token

#### For Linear:
1. Visit Linear → Settings → API → Personal API Keys
2. Create a new API key
3. Copy the key (starts with `lin_api_`)
4. In LibreChat, configure the Linear MCP server with your key

### 4. Using MCP Servers in LibreChat

1. Log into LibreChat at https://localhost:3443
2. Select a Claude model (Sonnet, Opus, or Haiku)
3. Look for "Notion" and "Linear" in the MCP dropdown
4. Click the gear/settings icon next to each
5. Enter your API credentials
6. Start chatting! Ask Claude to:
   - "Read my Notion page about project X"
   - "Create a Linear issue for this bug"
   - "Search my Notion workspace for meeting notes"
   - "Show me all Linear issues assigned to me"

## Files Created

```
mcp-servers/
├── README.md                    # User-facing documentation
├── test-mcp.sh                  # Test script for connectivity
├── notion/
│   └── Dockerfile               # Notion MCP server container
├── linear/
│   ├── Dockerfile               # Linear MCP server (direct)
│   └── Dockerfile.wrapped       # Linear MCP server (with HTTP wrapper)
└── http-wrapper/                # Generic HTTP wrapper for stdio MCP servers
    ├── package.json
    └── server.js
```

## Configuration Files Updated

### chat-config/librechat.yaml
- Added `notion` MCP server with `customUserVars` for `NOTION_TOKEN`
- Added `linear` MCP server with `customUserVars` for `LINEAR_API_TOKEN`
- Both servers use `type: streamable-http` (not SSE)
- Both servers connect to local containers (not Anthropic's hosted servers)

### docker-compose.yml
- Added `notion-mcp` service
- Added `linear-mcp` service

## Troubleshooting

### MCP Server Won't Start

**Check logs:**
```bash
docker compose logs notion-mcp
docker compose logs linear-mcp
```

**Common issues:**
- Port conflicts: Change ports 3001/3002 if already in use
- Build errors: Ensure Docker has internet access to pull Node.js image

### Linear MCP: "HTTP transport not supported"

If the Linear MCP server doesn't support `--transport http` flag, switch to the wrapped version:

1. Update [docker-compose.yml](docker-compose.yml):
   ```yaml
   linear-mcp:
     restart: always
     build:
       context: ./mcp-servers/linear
       dockerfile: Dockerfile.wrapped  # <-- Change this
     ports:
       - "3002:3000"
   ```

2. Rebuild:
   ```bash
   docker compose build linear-mcp
   docker compose up -d linear-mcp
   ```

### User: "Authentication failed"

Common causes:
- **Notion**: Token is correct, but pages aren't connected to integration
  - Fix: In Notion, go to page → ... → Connections → Add your integration
- **Linear**: Token doesn't have required scopes
  - Fix: Regenerate token with `read:*` and `write:*` scopes
- **Typo**: User copied token incorrectly
  - Fix: Re-copy token, ensure no extra spaces

### User: "Server not responding"

1. Verify services are up: `docker compose ps`
2. Check network: `docker compose exec librechat ping notion-mcp`
3. Restart services: `docker compose restart notion-mcp linear-mcp librechat`
4. Check LibreChat logs: `docker compose logs librechat | grep -i mcp`

## Security Considerations

### ✅ Good
- Each user provides their own API credentials
- Tokens are encrypted in LibreChat's database
- No shared secrets between users
- MCP servers don't store tokens (stateless)
- Tokens are validated by Notion/Linear APIs directly

### ⚠️ Important
- Users must trust your LibreChat instance with their API tokens
- API tokens are sent over HTTP within your Docker network (not encrypted in transit between containers)
- For production: Add TLS between LibreChat and MCP containers, or keep them on a private network
- Users should create tokens with minimal required scopes

### 🔒 Best Practices
- Regularly rotate API tokens
- Use separate tokens for dev/staging/prod
- Monitor token usage in Notion/Linear audit logs
- Revoke tokens when users leave your organization

## Production Deployment

For production (GKE), you'll need to:

1. **Deploy MCP servers as K8s services**:
   ```yaml
   apiVersion: apps/v1
   kind: Deployment
   metadata:
     name: notion-mcp
   spec:
     replicas: 2  # For high availability
     ...
   ```

2. **Update librechat-configmap.yaml**:
   ```yaml
   mcpServers:
     notion:
       url: "http://notion-mcp.codepathfinder.svc.cluster.local:3000/mcp"
   ```

3. **Consider**:
   - Horizontal Pod Autoscaling (HPA) for MCP servers
   - Resource limits (CPU/memory)
   - Network policies (restrict MCP servers to only accept from LibreChat)
   - TLS between LibreChat and MCP servers

## Testing

### Manual Test: Notion
```bash
# Get a test token from Notion
NOTION_TOKEN="ntn_your_token_here"

# Test the MCP server
curl -X POST http://localhost:3001/mcp \
  -H "Authorization: Bearer $NOTION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }'
```

Expected: JSON response with available Notion tools

### Manual Test: Linear
```bash
# Get a test token from Linear
LINEAR_TOKEN="lin_api_your_token_here"

# Test the MCP server
curl -X POST http://localhost:3002/mcp \
  -H "Authorization: Bearer $LINEAR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
  }'
```

Expected: JSON response with available Linear tools

## Next Steps

1. **Start the services**: `docker compose up -d`
2. **Test connectivity**: `./mcp-servers/test-mcp.sh`
3. **Create test tokens**: Set up one Notion and one Linear integration
4. **Test in LibreChat**: Configure your tokens and try a few queries
5. **Share with users**: Point them to [mcp-servers/README.md](mcp-servers/README.md)
6. **Monitor**: Watch logs for errors or authentication issues

## Support

- **MCP Documentation**: https://modelcontextprotocol.io/
- **LibreChat MCP Docs**: https://www.librechat.ai/docs/features/mcp
- **Notion API**: https://developers.notion.com/
- **Linear API**: https://developers.linear.app/

---

**Summary**: You now have a complete self-hosted MCP setup where users can directly connect their Notion and Linear accounts to LibreChat without going through Anthropic's hosted servers. Each user maintains control of their own credentials and can revoke access at any time.
