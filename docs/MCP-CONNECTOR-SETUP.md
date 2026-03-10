# CodePathfinder MCP Connector Setup

Connect Claude Desktop to CodePathfinder using OAuth for secure, seamless access to your indexed code.

## Quick Setup (Recommended: OAuth)

### Step 1: Add Custom Connector in Claude Desktop

1. Open **Claude Desktop**
2. Go to **Settings** (gear icon) → **Connectors**
3. Click **Add Connector** → **Custom**
4. Enter:
   - **Name:** `CodePathfinder`
   - **URL:** `https://codepathfinder.com/mcp`
5. Click **Add**

### Step 2: Authorize Access

1. Claude Desktop will open your browser
2. Log in to CodePathfinder (via Google if prompted)
3. Click **Authorize** on the consent screen
4. You'll be redirected back to Claude Desktop

### Step 3: Verify Connection

In a new Claude conversation, ask:
```
What CodePathfinder tools do you have available?
```

You should see 6 tools listed:
- `semantic_code_search` - Search code by meaning
- `map_symbols_by_query` - Find functions/classes
- `size` - Get repository statistics
- `symbol_analysis` - Analyze symbol usage
- `read_file_from_chunks` - Read file contents
- `document_symbols` - List undocumented symbols

## Alternative: API Key Authentication

For programmatic access or when OAuth isn't available, you can use API keys.

### Generate an API Key

1. Log in to [codepathfinder.com](https://codepathfinder.com)
2. Navigate to your project list
3. Click the **API Keys** button next to your project
4. Click **Generate New API Key**
5. Copy the generated key (starts with `cpf_`)

### Configure Claude Desktop with API Key

Add this to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "codepathfinder": {
      "command": "npx",
      "args": ["-y", "@grabowskit/mcp-bridge"],
      "env": {
        "CODEPATHFINDER_API_KEY": "cpf_your_api_key_here",
        "CODEPATHFINDER_API_ENDPOINT": "https://codepathfinder.com/api/v1/mcp/tools/call/"
      }
    }
  }
}
```

## OAuth vs API Key

| Feature | OAuth (Recommended) | API Key |
|---------|---------------------|---------|
| Setup complexity | Simple (UI-based) | Requires config file editing |
| Authentication | Browser-based login | Static key |
| Project access | All your projects | Project-scoped |
| Token refresh | Automatic | N/A |
| Revocation | Via CodePathfinder settings | Via API Keys page |

## Available Tools

All tools support the `projects` parameter for project-scoped searches:

| Tool | Description |
|------|-------------|
| `semantic_code_search` | Search code using natural language queries |
| `map_symbols_by_query` | Find functions, classes, methods matching a query |
| `symbol_analysis` | Analyze a symbol's definitions and references |
| `read_file_from_chunks` | Read a complete file from indexed chunks |
| `document_symbols` | List symbols that need documentation |
| `size` | Get statistics about the code index |

## Troubleshooting

### OAuth: "Failed to add connector"

1. Ensure you're using the correct URL: `https://codepathfinder.com/mcp`
2. Check that CodePathfinder is accessible in your browser
3. Try removing and re-adding the connector

### OAuth: Stuck on authorization page

1. Make sure you click the **Authorize** button
2. If the page is blank, try refreshing
3. Check you're logged into CodePathfinder

### API Key: "Could not connect to MCP server"

1. Check Node.js is installed: `node --version`
2. Verify the API key is correct (including `cpf_` prefix)
3. Check Claude Desktop logs for errors

### No tools appearing

1. Restart Claude Desktop completely (Cmd+Q on macOS)
2. Verify connection in Settings → Connectors
3. Try asking Claude to list available tools

## Support

- **Documentation**: [codepathfinder.com/docs](https://codepathfinder.com/docs)
- **Testing Guide**: [CLAUDE-DESKTOP-TESTING-GUIDE.md](CLAUDE-DESKTOP-TESTING-GUIDE.md)

---

**Last Updated**: 2025-12-19
