#!/bin/bash
# =============================================================================
# Setup Kibana Agent Builder with CodePathfinder Tools
# =============================================================================
#
# This script registers CodePathfinder's semantic code search tools with
# Kibana Agent Builder using external API connectors. This allows the Kibana
# agent to call CodePathfinder's MCP Tool Proxy API to execute tools.
#
# Prerequisites:
#   - Kibana Agent Builder enabled (Elastic 8.15+)
#   - CodePathfinder instance running with accessible API endpoint
#   - Project API Key with 'all' or 'mcp' scope from CodePathfinder
#
# Usage:
#   ./setup-kibana-codepathfinder-tools.sh
#
# Environment Variables (required):
#   KIBANA_HOST          - Kibana endpoint URL (e.g., https://kibana:5601)
#   KIBANA_API_KEY       - Kibana API key (or elastic:password for basic auth)
#   CODEPATHFINDER_URL   - CodePathfinder API URL (e.g., https://localhost:8443)
#   CODEPATHFINDER_API_KEY - CodePathfinder Project API Key (cpf_xxx)
#
# Environment Variables (optional):
#   AGENT_ID             - Custom agent ID (default: codepathfinder-agent)
#   AGENT_NAME           - Custom agent name (default: CodePathfinder Assistant)
#
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
KIBANA_HOST="${KIBANA_HOST:-http://localhost:5601}"
KIBANA_API_KEY="${KIBANA_API_KEY:-}"
CODEPATHFINDER_URL="${CODEPATHFINDER_URL:-https://localhost:8443}"
CODEPATHFINDER_API_KEY="${CODEPATHFINDER_API_KEY:-}"
AGENT_ID="${AGENT_ID:-codepathfinder-agent}"
AGENT_NAME="${AGENT_NAME:-CodePathfinder Assistant}"

# Remove trailing slashes
KIBANA_HOST="${KIBANA_HOST%/}"
CODEPATHFINDER_URL="${CODEPATHFINDER_URL%/}"

# Build MCP Tool Proxy URL
MCP_TOOL_PROXY_URL="${CODEPATHFINDER_URL}/api/v1/mcp/tools/call/"

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  CodePathfinder Tools Setup for Kibana Agent Builder${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Validate required environment variables
if [ -z "$KIBANA_API_KEY" ]; then
    echo -e "${RED}ERROR: KIBANA_API_KEY is required${NC}"
    echo "Set it via: export KIBANA_API_KEY='your-api-key'"
    echo "Or for basic auth: export KIBANA_API_KEY='elastic:password'"
    exit 1
fi

if [ -z "$CODEPATHFINDER_API_KEY" ]; then
    echo -e "${RED}ERROR: CODEPATHFINDER_API_KEY is required${NC}"
    echo "Get a Project API Key from CodePathfinder Settings > API Keys"
    echo "Set it via: export CODEPATHFINDER_API_KEY='cpf_xxx'"
    exit 1
fi

echo -e "Configuration:"
echo -e "  Kibana Host:        ${YELLOW}${KIBANA_HOST}${NC}"
echo -e "  CodePathfinder URL: ${YELLOW}${CODEPATHFINDER_URL}${NC}"
echo -e "  MCP Tool Proxy:     ${YELLOW}${MCP_TOOL_PROXY_URL}${NC}"
echo -e "  Agent ID:           ${YELLOW}${AGENT_ID}${NC}"
echo ""

# Build auth header
if [[ "$KIBANA_API_KEY" == *":"* ]]; then
    # Basic auth format (username:password)
    AUTH_HEADER="Basic $(echo -n "$KIBANA_API_KEY" | base64)"
    echo -e "  Auth Mode:          ${YELLOW}Basic Auth${NC}"
else
    # API Key format
    AUTH_HEADER="ApiKey ${KIBANA_API_KEY}"
    echo -e "  Auth Mode:          ${YELLOW}API Key${NC}"
fi
echo ""

# Function to make Kibana API requests
kibana_request() {
    local method="$1"
    local path="$2"
    local data="$3"

    local curl_args=(
        -s
        -w "\n%{http_code}"
        -X "$method"
        -H "Authorization: ${AUTH_HEADER}"
        -H "Content-Type: application/json"
        -H "kbn-xsrf: true"
        -k  # Allow self-signed certs
    )

    if [ -n "$data" ]; then
        curl_args+=(-d "$data")
    fi

    curl "${curl_args[@]}" "${KIBANA_HOST}${path}" 2>&1
}

# Function to create or update a tool
create_tool() {
    local tool_id="$1"
    local tool_name="$2"
    local description="$3"
    local body_template="$4"

    echo -ne "  Creating tool: ${YELLOW}${tool_name}${NC}... "

    local payload=$(cat <<EOF
{
    "id": "${tool_id}",
    "description": "${description}",
    "type": "external_api",
    "tags": ["codepathfinder", "code-search"],
    "configuration": {
        "method": "POST",
        "url_template": "${MCP_TOOL_PROXY_URL}",
        "headers": {
            "Authorization": "Bearer ${CODEPATHFINDER_API_KEY}",
            "Content-Type": "application/json"
        },
        "body_template": ${body_template}
    }
}
EOF
)

    local response
    response=$(kibana_request "POST" "/api/agent_builder/tools" "$payload")
    local http_code=$(echo "$response" | tail -n1)
    local body=$(echo "$response" | sed '$d')

    if [ "$http_code" -eq 200 ] || [ "$http_code" -eq 201 ]; then
        echo -e "${GREEN}✓ Created${NC}"
        return 0
    elif [ "$http_code" -eq 409 ]; then
        echo -e "${YELLOW}⚠ Already exists, updating...${NC}"
        # Try to update
        response=$(kibana_request "PUT" "/api/agent_builder/tools/${tool_id}" "$payload")
        http_code=$(echo "$response" | tail -n1)
        if [ "$http_code" -eq 200 ]; then
            echo -e "    ${GREEN}✓ Updated${NC}"
            return 0
        else
            echo -e "    ${RED}✗ Update failed (HTTP ${http_code})${NC}"
            return 1
        fi
    else
        echo -e "${RED}✗ Failed (HTTP ${http_code})${NC}"
        echo -e "    ${RED}Response: ${body}${NC}"
        return 1
    fi
}

# Wait for Kibana to be ready
echo -e "${BLUE}Step 1: Checking Kibana connectivity...${NC}"
max_attempts=10
attempt=0
while [ $attempt -lt $max_attempts ]; do
    response=$(kibana_request "GET" "/api/status" "")
    http_code=$(echo "$response" | tail -n1)

    if [ "$http_code" -eq 200 ]; then
        echo -e "  ${GREEN}✓ Kibana is ready${NC}"
        break
    fi

    attempt=$((attempt + 1))
    echo -e "  Waiting for Kibana... (attempt $attempt/$max_attempts)"
    sleep 2
done

if [ $attempt -eq $max_attempts ]; then
    echo -e "${RED}ERROR: Could not connect to Kibana at ${KIBANA_HOST}${NC}"
    exit 1
fi
echo ""

# Create tools
echo -e "${BLUE}Step 2: Creating CodePathfinder tools...${NC}"
echo ""

TOOLS_CREATED=0
TOOLS_FAILED=0

# Tool 1: semantic_code_search
create_tool "cpf-semantic-code-search" "semantic_code_search" \
    "Search code by semantic meaning. Use natural language to find relevant code, functions, classes, and implementations." \
    '{"name": "semantic_code_search", "arguments": {"query": "{{query}}", "size": {{size:10}}}}' && ((TOOLS_CREATED++)) || ((TOOLS_FAILED++))

# Tool 2: map_symbols_by_query
create_tool "cpf-map-symbols" "map_symbols_by_query" \
    "Find symbols (functions, classes, methods) matching a query, grouped by file path." \
    '{"name": "map_symbols_by_query", "arguments": {"query": "{{query}}", "size": {{size:20}}}}' && ((TOOLS_CREATED++)) || ((TOOLS_FAILED++))

# Tool 3: symbol_analysis
create_tool "cpf-symbol-analysis" "symbol_analysis" \
    "Analyze a symbol to find its definitions and references across the codebase." \
    '{"name": "symbol_analysis", "arguments": {"symbol_name": "{{symbol_name}}"}}' && ((TOOLS_CREATED++)) || ((TOOLS_FAILED++))

# Tool 4: read_file_from_chunks
create_tool "cpf-read-file" "read_file_from_chunks" \
    "Reconstruct and read a file'"'"'s content from indexed code chunks." \
    '{"name": "read_file_from_chunks", "arguments": {"file_path": "{{file_path}}"}}' && ((TOOLS_CREATED++)) || ((TOOLS_FAILED++))

# Tool 5: document_symbols
create_tool "cpf-document-symbols" "document_symbols" \
    "List all symbols in a file (functions, classes, methods) for documentation or analysis." \
    '{"name": "document_symbols", "arguments": {"file_path": "{{file_path}}"}}' && ((TOOLS_CREATED++)) || ((TOOLS_FAILED++))

# Tool 6: size (index stats)
create_tool "cpf-index-size" "size" \
    "Get statistics about indexed projects including document count and storage size." \
    '{"name": "size", "arguments": {}}' && ((TOOLS_CREATED++)) || ((TOOLS_FAILED++))

echo ""
echo -e "  Tools created: ${GREEN}${TOOLS_CREATED}${NC}, Failed: ${RED}${TOOLS_FAILED}${NC}"
echo ""

# Create the agent
echo -e "${BLUE}Step 3: Creating CodePathfinder agent...${NC}"
echo ""

AGENT_INSTRUCTIONS=$(cat <<'INSTRUCTIONS'
You are a helpful AI coding assistant with access to CodePathfinder's semantic code search tools.

## Available Tools

1. **semantic_code_search** - Find code by meaning
   - Use natural language queries like "authentication logic" or "error handling for API calls"
   - Best for discovering relevant code when you don't know exact names

2. **map_symbols_by_query** - Find symbols by name pattern
   - Search for functions, classes, methods by name
   - Returns results grouped by file path

3. **symbol_analysis** - Analyze a specific symbol
   - Find where a symbol is defined and referenced
   - Understand how code is connected

4. **read_file_from_chunks** - Read file contents
   - Reconstruct full file content from indexed chunks
   - Use after finding relevant files via search

5. **document_symbols** - List symbols in a file
   - Get all functions, classes, methods in a file
   - Useful for understanding file structure

6. **size** - Get index statistics
   - Check how many files/chunks are indexed
   - Verify project indexing status

## Guidelines

- Always cite code with file paths when sharing results
- Use semantic_code_search first to find relevant code
- Follow up with read_file_from_chunks to see full context
- Format code in markdown code blocks with language hints
- Be concise but thorough in explanations
INSTRUCTIONS
)

# Escape the instructions for JSON
AGENT_INSTRUCTIONS_ESCAPED=$(echo "$AGENT_INSTRUCTIONS" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')

AGENT_PAYLOAD=$(cat <<EOF
{
    "id": "${AGENT_ID}",
    "name": "${AGENT_NAME}",
    "description": "AI assistant with semantic code search capabilities powered by CodePathfinder",
    "configuration": {
        "instructions": ${AGENT_INSTRUCTIONS_ESCAPED},
        "tools": [
            {
                "tool_ids": [
                    "cpf-semantic-code-search",
                    "cpf-map-symbols",
                    "cpf-symbol-analysis",
                    "cpf-read-file",
                    "cpf-document-symbols",
                    "cpf-index-size"
                ]
            }
        ]
    }
}
EOF
)

echo -ne "  Creating agent: ${YELLOW}${AGENT_NAME}${NC}... "

response=$(kibana_request "POST" "/api/agent_builder/agents" "$AGENT_PAYLOAD")
http_code=$(echo "$response" | tail -n1)
body=$(echo "$response" | sed '$d')

if [ "$http_code" -eq 200 ] || [ "$http_code" -eq 201 ]; then
    echo -e "${GREEN}✓ Created${NC}"
elif [ "$http_code" -eq 409 ]; then
    echo -e "${YELLOW}⚠ Already exists, updating...${NC}"
    response=$(kibana_request "PUT" "/api/agent_builder/agents/${AGENT_ID}" "$AGENT_PAYLOAD")
    http_code=$(echo "$response" | tail -n1)
    if [ "$http_code" -eq 200 ]; then
        echo -e "    ${GREEN}✓ Updated${NC}"
    else
        echo -e "    ${RED}✗ Update failed (HTTP ${http_code})${NC}"
    fi
else
    echo -e "${RED}✗ Failed (HTTP ${http_code})${NC}"
    echo -e "  Response: ${body}"
fi

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Setup Complete!${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  Agent ID:   ${GREEN}${AGENT_ID}${NC}"
echo -e "  Agent Name: ${GREEN}${AGENT_NAME}${NC}"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo ""
echo "  1. Update your CodePathfinder LLM Provider settings:"
echo "     - Go to Settings > LLM Config"
echo "     - Edit your Kibana provider"
echo "     - Set Agent ID to: ${AGENT_ID}"
echo ""
echo "  2. Test in Kibana:"
echo "     - Open Kibana > Agent Builder > Agents"
echo "     - Find '${AGENT_NAME}'"
echo "     - Click 'Chat' to test"
echo ""
echo "  3. Test in CodePathfinder:"
echo "     - Go to Chat"
echo "     - Select the Kibana Agent model"
echo "     - Ask: 'What files are in the project?' or 'Search for authentication code'"
echo ""
