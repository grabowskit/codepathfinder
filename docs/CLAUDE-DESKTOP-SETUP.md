# Using CodePathfinder with Claude Desktop

## Overview

CodePathfinder provides an MCP (Model Context Protocol) server that allows Claude Desktop to search and analyze your indexed code repositories. This guide explains how to connect Claude Desktop to your CodePathfinder projects.

## Prerequisites

- Claude Desktop installed (version 1.0.1768 or later)
- A CodePathfinder account at [codepathfinder.com](https://codepathfinder.com)
- At least one indexed project in CodePathfinder

## Quick Setup with OAuth (Recommended)

The easiest way to connect Claude Desktop to CodePathfinder is using OAuth authentication.

### Step 1: Add Custom Connector

1. Open **Claude Desktop**
2. Go to **Settings** (gear icon) → **Connectors**
3. Click **Add Connector** → **Custom**
4. Enter:
   - **Name:** `CodePathfinder`
   - **URL:** `https://codepathfinder.com/mcp`
5. Click **Add**

### Step 2: Authorize Access

1. Claude Desktop will open your browser automatically
2. Log in to CodePathfinder (via Google if prompted)
3. Review the permissions and click **Authorize**
4. You'll be redirected back to Claude Desktop
5. The connector should now show as **Connected**

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

## Alternative: API Key Setup

For programmatic access or environments where OAuth isn't available, you can use API keys with the MCP Bridge.

### Step 1: Generate an API Key

1. Log in to [codepathfinder.com](https://codepathfinder.com)
2. Navigate to your project list
3. Click the **API Keys** button (key icon) next to the project you want to use
4. Click **"Generate New API Key"**
5. Enter a descriptive label: `Claude Desktop`
6. Click **Generate** and copy the key

### Step 2: Configure Claude Desktop

1. Open Claude Desktop
2. Go to **Settings** → **Developer**
3. Find the **MCP Servers** section
4. Click **"Edit Config"** or manually open:
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

5. Add the configuration:

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

6. Save the file

### Step 3: Restart Claude Desktop

**Important**: Completely quit Claude Desktop (not just close the window) and reopen it.

On macOS: `Cmd+Q` to quit, then relaunch
On Windows: Right-click taskbar icon → Exit, then relaunch

## Usage Examples

Once connected, you can ask Claude questions about your code:

### Search for Functionality
```
Using codepathfinder, find code related to user authentication
```

### Browse Code Structure
```
Using codepathfinder, show me all the API endpoints in this project
```

### Get Repository Stats
```
Using codepathfinder, how big is my codebase and what languages does it use?
```

### Analyze Specific Symbols
```
Using codepathfinder, show me everywhere the function "processPayment" is called
```

## OAuth vs API Key Comparison

| Feature | OAuth (Recommended) | API Key |
|---------|---------------------|---------|
| Setup | Simple UI-based | Config file editing |
| Authentication | Browser login | Static key |
| Project access | All your projects | Single project |
| Token refresh | Automatic | N/A |
| Security | Session-based | Key-based |

## How It Works

### OAuth Flow
```
┌─────────────────┐
│  Claude Desktop │
└────────┬────────┘
         │
         │ (MCP over HTTPS)
         ↓
┌─────────────────┐
│  CodePathfinder │ ← OAuth authentication
│   MCP Server    │   at codepathfinder.com
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│  Elasticsearch  │ ← Your indexed code
└─────────────────┘
```

### API Key Flow
```
┌─────────────────┐
│  Claude Desktop │
└────────┬────────┘
         │
         │ (stdio)
         ↓
┌─────────────────┐
│   MCP Bridge    │ ← Runs locally via npx
│   (Node.js)     │
└────────┬────────┘
         │
         │ (HTTPS + API Key)
         ↓
┌─────────────────┐
│  CodePathfinder │
│   API Server    │
└────────┬────────┘
         │
         ↓
┌─────────────────┐
│  Elasticsearch  │
└─────────────────┘
```

## Multiple Projects

With OAuth, you automatically have access to all projects you own or have been shared with.

With API keys, add separate entries for each project:

```json
{
  "mcpServers": {
    "codepathfinder-project1": {
      "command": "npx",
      "args": ["-y", "@grabowskit/mcp-bridge"],
      "env": {
        "CODEPATHFINDER_API_KEY": "cpf_project1_key...",
        "CODEPATHFINDER_API_ENDPOINT": "https://codepathfinder.com/api/v1/mcp/tools/call/"
      }
    },
    "codepathfinder-project2": {
      "command": "npx",
      "args": ["-y", "@grabowskit/mcp-bridge"],
      "env": {
        "CODEPATHFINDER_API_KEY": "cpf_project2_key...",
        "CODEPATHFINDER_API_ENDPOINT": "https://codepathfinder.com/api/v1/mcp/tools/call/"
      }
    }
  }
}
```

## Troubleshooting

### OAuth: "Failed to add connector"

**Solutions**:
1. Verify the URL is exactly: `https://codepathfinder.com/mcp`
2. Check CodePathfinder is accessible in your browser
3. Remove the connector and try adding it again

### OAuth: Authorization page is blank

**Cause**: Template rendering issue (rare)

**Solutions**:
1. Refresh the page
2. Clear browser cookies for codepathfinder.com
3. Try in an incognito window

### OAuth: Stuck after clicking Authorize

**Solutions**:
1. Check if you were redirected back to Claude Desktop
2. Look for the connector in Settings → Connectors
3. Try removing and re-adding the connector

### API Key: "Could not connect to MCP server"

**Solutions**:
1. Check that you have Node.js 18+ installed: `node --version`
2. Try running the bridge manually:
   ```bash
   npx -y @grabowskit/mcp-bridge
   ```
3. Check Claude Desktop logs:
   - **macOS**: `~/Library/Logs/Claude/mcp-server-codepathfinder.log`
   - **Windows**: `%LOCALAPPDATA%\Claude\logs\mcp-server-codepathfinder.log`

### "Invalid API key" error

**Solutions**:
1. Verify the API key is correctly copied (including `cpf_` prefix)
2. Check the API key hasn't been revoked in CodePathfinder
3. Generate a new API key and update the config

### Tools not appearing

**Solutions**:
1. Validate JSON syntax using [jsonlint.com](https://jsonlint.com)
2. Ensure the config file is saved
3. **Completely quit** and restart Claude Desktop (Cmd+Q on macOS)
4. Check for error messages in Claude Desktop's developer console

### "No code found" responses

**Solutions**:
1. Verify your project is indexed at [codepathfinder.com](https://codepathfinder.com)
2. Check the project status shows "Completed"
3. Run the indexer if needed

## Security & Privacy

- **OAuth tokens expire**: Automatic refresh keeps you connected
- **API keys are project-scoped**: Each key only accesses one specific project
- **HTTPS encryption**: All communication uses HTTPS
- **No code storage**: Claude doesn't store your code; it queries CodePathfinder in real-time

## Project Status & Visibility

To manage which code is accessible to Claude:

- **Running / Watching:** Project is active and searchable
- **Enabled:** Project is active and searchable
- **Disabled:** Project is hidden from Claude/MCP - search tools won't find it

Use the "Enable/Disable" toggle in the web dashboard to control access.

## Revoking Access

### OAuth
1. Go to Settings → Connectors in Claude Desktop
2. Click **Remove** next to CodePathfinder

### API Keys
1. Go to your project's API Keys page on CodePathfinder
2. Click **Revoke** next to the key
3. The key becomes invalid immediately

## Getting Help

- **Documentation**: [codepathfinder.com/docs](https://codepathfinder.com/docs)
- **Support**: [support@codepathfinder.com](mailto:support@codepathfinder.com)

## FAQ

**Q: Which authentication method should I use?**
A: Use OAuth for the simplest setup. Use API keys only if you need programmatic access or OAuth isn't available.

**Q: Does OAuth work with other AI assistants?**
A: OAuth is specifically for Claude Desktop. Other MCP clients may support different authentication methods.

**Q: Can I use this with private/self-hosted CodePathfinder?**
A: Yes, change the URL to your instance's URL (e.g., `https://your-instance.com/mcp`).

**Q: What's the rate limit?**
A: API keys have a rate limit of 100 requests/minute per project. OAuth connections share your account's rate limit.

---

**Last Updated**: 2025-12-19
