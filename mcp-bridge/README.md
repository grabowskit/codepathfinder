# CodePathfinder MCP Bridge

MCP (Model Context Protocol) bridge for CodePathfinder. This bridge allows Claude Desktop to interact with CodePathfinder projects using project-scoped API keys.

## Features

- **6 Powerful Code Search Tools**:
  - `semantic_code_search` - Search code by semantic meaning
  - `map_symbols_by_query` - Find symbols grouped by file
  - `size` - Get index statistics
  - `symbol_analysis` - Analyze symbol definitions and references
  - `read_file_from_chunks` - Reconstruct files from indexed chunks
  - `document_symbols` - List symbols needing documentation

- **Project-Scoped Authentication** - Each API key is tied to a specific project
- **Secure** - API keys are transmitted via Bearer token authentication
- **Simple Setup** - Works with Claude Desktop out of the box

## Requirements

- Node.js >= 18.0.0
- A CodePathfinder account with at least one indexed project
- A project API key (generated from the CodePathfinder web UI)

## Installation

> **Note**: The package is not yet published to npm. For local development, use Option 3 below.

### Option 1: NPX (Recommended)

Use `npx` to run the bridge without installing it globally:

```json
{
  "mcpServers": {
    "codepathfinder": {
      "command": "npx",
      "args": ["-y", "@grabowskit/mcp-bridge"],
      "env": {
        "CODEPATHFINDER_API_KEY": "your-api-key-here",
        "CODEPATHFINDER_API_ENDPOINT": "https://codepathfinder.com/api/v1/mcp/tools/call/"
      }
    }
  }
}
```

### Option 2: Global Installation

Install the package globally:

```bash
npm install -g @grabowskit/mcp-bridge
```

Then use it in your Claude Desktop config:

```json
{
  "mcpServers": {
    "codepathfinder": {
      "command": "codepathfinder-mcp",
      "env": {
        "CODEPATHFINDER_API_KEY": "your-api-key-here",
        "CODEPATHFINDER_API_ENDPOINT": "https://codepathfinder.com/api/v1/mcp/tools/call/"
      }
    }
  }
}
```

### Option 3: Local Development

Clone and build from source:

```bash
cd mcp-bridge
npm install
npm run build
```

Use in Claude Desktop config:

```json
{
  "mcpServers": {
    "codepathfinder": {
      "command": "node",
      "args": ["/absolute/path/to/mcp-bridge/build/index.js"],
      "env": {
        "CODEPATHFINDER_API_KEY": "your-api-key-here",
        "CODEPATHFINDER_API_ENDPOINT": "http://localhost:8443/api/v1/mcp/tools/call/"
      }
    }
  }
}
```

## Setup Guide

### Step 1: Get Your API Key

1. Log in to CodePathfinder
2. Navigate to your project
3. Click the "API Keys" button (key icon) in the project list
4. Generate a new API key with a descriptive label (e.g., "Claude Desktop")
5. **Copy the key immediately** - you won't see it again!

### Step 2: Configure Claude Desktop

1. Locate your Claude Desktop config file:
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows**: `%APPDATA%/Claude/claude_desktop_config.json`

2. Edit the file and add the MCP server configuration:

```json
{
  "mcpServers": {
    "codepathfinder": {
      "command": "npx",
      "args": ["-y", "@grabowskit/mcp-bridge"],
      "env": {
        "CODEPATHFINDER_API_KEY": "cpf_abc123_xyz789...",
        "CODEPATHFINDER_API_ENDPOINT": "https://codepathfinder.com/api/v1/mcp/tools/call/"
      }
    }
  }
}
```

3. Replace `cpf_abc123_xyz789...` with your actual API key
4. Optionally customize the server name (`codepathfinder-myproject`)

### Step 3: Restart Claude Desktop

Close and reopen Claude Desktop. The MCP server will be available as a tool provider.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CODEPATHFINDER_API_KEY` | ✅ Yes | - | Your project API key from CodePathfinder |
| `CODEPATHFINDER_API_ENDPOINT` | No | `https://codepathfinder.com/api/v1/mcp/tools/call/` | API endpoint URL |
| `CODEPATHFINDER_DISABLE_SSL_VERIFY` | No | `false` | Disable SSL verification (local dev only!) |

## Available Tools

### 1. semantic_code_search

Search code by semantic meaning using natural language queries.

**Parameters:**
- `query` (string, required) - Natural language search query
- `index` (string, optional) - Index name override
- `size` (number, optional) - Max results (default: 10, max: 50)

**Example:**
```
Search for "function that handles user authentication"
```

### 2. map_symbols_by_query

Find symbols (functions, classes, methods) matching a query, grouped by file path.

**Parameters:**
- `query` (string, required) - Symbol name search query
- `index` (string, optional) - Index name override
- `size` (number, optional) - Max files (default: 20)

**Example:**
```
Find all symbols matching "authenticate"
```

### 3. size

Get statistics about the code index.

**Parameters:**
- `index` (string, optional) - Index name override

**Example:**
```
Get index statistics
```

### 4. symbol_analysis

Analyze a symbol to find its definitions, call sites, and references.

**Parameters:**
- `symbol_name` (string, required) - Name of the symbol to analyze
- `index` (string, optional) - Index name override

**Example:**
```
Analyze the symbol "authenticateUser"
```

### 5. read_file_from_chunks

Reconstruct a complete file from indexed code chunks.

**Parameters:**
- `file_path` (string, required) - Path to the file to reconstruct
- `index` (string, optional) - Index name override

**Example:**
```
Read the file "src/auth/login.ts"
```

### 6. document_symbols

List all symbols in a file that would benefit from documentation.

**Parameters:**
- `file_path` (string, required) - Path to the file to analyze
- `index` (string, optional) - Index name override

**Example:**
```
List symbols in "src/models/user.ts"
```

## Troubleshooting

### Local Development Setup

For detailed local development setup instructions (including SSL certificate handling), see [LOCAL_SETUP.md](LOCAL_SETUP.md).

### "Could not attach to MCP server"

This usually means:
- The package hasn't been published to npm yet - use the local path instead of `npx`
- Check the Claude Desktop logs: `~/Library/Logs/Claude/mcp-server-*.log`
- For local development, see [LOCAL_SETUP.md](LOCAL_SETUP.md)

### "CODEPATHFINDER_API_KEY environment variable is required"

Make sure you've set the `CODEPATHFINDER_API_KEY` in your Claude Desktop config's `env` section.

### "API error: Invalid API key"

Your API key may be incorrect or has been revoked. Generate a new key from the CodePathfinder web UI.

### "API error: Valid API key required"

The API key format is invalid. Ensure it starts with `cpf_` and includes the full key.

### "Failed to call CodePathfinder API: fetch failed"

- Check that the `CODEPATHFINDER_API_ENDPOINT` is correct
- Verify your network connection
- If using a local instance, ensure the server is running

### Tools not appearing in Claude Desktop

1. Verify the config file syntax is valid JSON
2. Check that Claude Desktop has been restarted
3. Look at Claude Desktop's logs for errors

## Development

### Build

```bash
npm run build
```

### Watch Mode

```bash
npm run watch
```

### Test Locally

```bash
# Build first
npm run build

# Set environment variables
export CODEPATHFINDER_API_KEY="your-api-key"
export CODEPATHFINDER_API_ENDPOINT="http://localhost:8443/api/v1/mcp/tools/call/"

# Run the bridge
npm start
```

## Architecture

```
Claude Desktop
      ↓ (stdio)
CodePathfinder MCP Bridge (Node.js)
      ↓ (HTTPS + Bearer Token)
CodePathfinder REST API (Django)
      ↓ (Internal)
Elasticsearch Serverless
```

The bridge acts as a lightweight proxy that:
1. Receives MCP tool calls from Claude Desktop via stdio
2. Forwards them to the CodePathfinder REST API with authentication
3. Returns results in MCP format

## Security

- **API keys are never logged or exposed** - They're only used for authentication
- **Bearer token authentication** - Industry standard secure method
- **Project-scoped access** - Each key only accesses one project
- **HTTPS required** - All API communication is encrypted

## License

MIT

## Support

For issues or questions:
- GitHub Issues: [https://github.com/yourusername/pathfinder/issues](https://github.com/yourusername/pathfinder/issues)
- Documentation: [https://codepathfinder.com/docs](https://codepathfinder.com/docs)
