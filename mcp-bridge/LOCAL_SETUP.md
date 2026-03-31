# Local Development Setup for MCP Bridge

## Problem Identified

The error "Could not attach to MCP server codepathfinder-tester" was caused by:

1. **Package not published to npm** - The `@grabowskit/mcp-bridge` package hasn't been published yet, so `npx` can't find it
2. **SSL certificate validation** - Local development uses self-signed certificates that Node.js rejects by default

## Solution

Use the **local path** to the built bridge instead of npx, and disable SSL verification for local development.

## Step-by-Step Setup

### 1. Get Your API Key

From the CodePathfinder web UI at https://localhost:8443:
1. Log in to your account
2. Navigate to your project
3. Click the "API Keys" button (key icon)
4. Generate a new key with label "Claude Desktop - Local Dev"
5. **Copy the full key** (starts with `cpf_`)

### 2. Configure Claude Desktop

Edit your Claude Desktop config file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

Replace the entire `codepathfinder-tester` section with:

```json
{
  "mcpServers": {
    "codepathfinder-tester": {
      "command": "node",
      "args": ["/path/to/codepathfinder/mcp-bridge/build/index.js"],
      "env": {
        "CODEPATHFINDER_API_KEY": "cpf_YOUR_ACTUAL_KEY_HERE",
        "CODEPATHFINDER_API_ENDPOINT": "https://localhost:8443/api/v1/mcp/tools/call/",
        "CODEPATHFINDER_DISABLE_SSL_VERIFY": "true"
      }
    }
  }
}
```

**Important changes:**
- ✅ Use `"command": "node"` instead of `"npx"`
- ✅ Use absolute path to `build/index.js`
- ✅ Set `CODEPATHFINDER_DISABLE_SSL_VERIFY` to `"true"` for local dev
- ✅ Use `https://localhost:8443` as the endpoint

### 3. Restart Claude Desktop

Completely quit and restart Claude Desktop for the config to take effect.

### 4. Verify Connection

In Claude Desktop, you should see:
- No error messages
- The MCP server status should show as connected
- 6 tools should be available

Check the logs if needed:
```bash
tail -f ~/Library/Logs/Claude/mcp-server-codepathfinder-tester.log
```

You should see:
```
Starting CodePathfinder MCP Bridge...
API Endpoint: https://localhost:8443/api/v1/mcp/tools/call/
API Key: cpf_xTT9rLYJ...
WARNING: SSL certificate verification is DISABLED. Only use this for local development!
CodePathfinder MCP Bridge is running
```

## Available Tools

Once connected, you can use these 6 tools:

1. **semantic_code_search** - Search code by meaning
2. **map_symbols_by_query** - Find symbols by name
3. **size** - Get index statistics
4. **symbol_analysis** - Analyze symbol usage
5. **read_file_from_chunks** - Read full files
6. **document_symbols** - List symbols needing docs

## Troubleshooting

### Error: "CODEPATHFINDER_API_KEY environment variable is required"
- Check that you've set the API key in the config
- Ensure the key starts with `cpf_`
- Restart Claude Desktop

### Error: "API error: Invalid API key"
- Generate a new API key from the web UI
- Make sure you copied the full key
- Check that the key hasn't been revoked

### Error: "fetch failed" or connection errors
- Verify the Django server is running: `docker-compose ps`
- Check you can access https://localhost:8443 in your browser
- Ensure `CODEPATHFINDER_DISABLE_SSL_VERIFY` is set to `"true"`

### Tools not appearing
- Check the log file for errors
- Verify the bridge process started successfully
- Ensure the config JSON is valid

### SSL/TLS errors
- The `CODEPATHFINDER_DISABLE_SSL_VERIFY: "true"` setting should fix this
- This is safe for local development only
- Never use this in production

## Testing the Bridge Manually

You can test the bridge outside of Claude Desktop:

```bash
cd /path/to/codepathfinder/mcp-bridge

# Set environment variables
export CODEPATHFINDER_API_KEY="cpf_YOUR_KEY"
export CODEPATHFINDER_API_ENDPOINT="https://localhost:8443/api/v1/mcp/tools/call/"
export CODEPATHFINDER_DISABLE_SSL_VERIFY="true"

# Run the bridge
node build/index.js
```

The bridge will start and wait for MCP protocol messages on stdin. You should see:
```
Starting CodePathfinder MCP Bridge...
API Endpoint: https://localhost:8443/api/v1/mcp/tools/call/
API Key: cpf_xTT9rLYJ...
WARNING: SSL certificate verification is DISABLED...
CodePathfinder MCP Bridge is running
```

Press Ctrl+C to exit.

## Production Deployment

When you're ready to publish to production:

1. **Remove SSL disable flag** from the config
2. **Use production endpoint**: `https://<YOUR_DOMAIN>/api/v1/mcp/tools/call/`
3. **Publish to npm**: `npm publish --access public`
4. **Update config to use npx**: `"command": "npx", "args": ["-y", "@your-org/mcp-bridge"]`

## What Changed

I made these updates to fix the connection issue:

1. **Added SSL verification bypass** for local development in [src/index.ts:23-35](src/index.ts)
2. **Updated example config** to use local path in [claude_desktop_config.example.json](claude_desktop_config.example.json)
3. **Rebuilt the bridge** with `npm run build`

The bridge now supports the `CODEPATHFINDER_DISABLE_SSL_VERIFY` environment variable for local development with self-signed certificates.
