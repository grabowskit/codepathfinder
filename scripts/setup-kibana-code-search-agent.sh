#!/bin/bash
# Script to create Kibana Agent Builder tools and agent for code search
# This sets up semantic code search capabilities for Kibana Agent Builder

set -e

KIBANA_HOST="${KIBANA_HOST:-http://localhost:5601}"
ELASTIC_USER="${ELASTICSEARCH_USER:-elastic}"
ELASTIC_PASSWORD="${ELASTICSEARCH_PASSWORD:-changeme}"
INDEX_NAME="${ELASTICSEARCH_INDEX:-code-chunks}"

echo "Setting up Kibana Agent Builder for code search..."
echo "Kibana: ${KIBANA_HOST}"
echo "Index: ${INDEX_NAME}"

# Wait for Kibana to be ready
echo "Waiting for Kibana to be ready..."
max_attempts=30
attempt=0
while [ $attempt -lt $max_attempts ]; do
    if curl -s -f -u "${ELASTIC_USER}:${ELASTIC_PASSWORD}" "${KIBANA_HOST}/api/status" > /dev/null 2>&1; then
        echo "Kibana is ready!"
        break
    fi
    attempt=$((attempt + 1))
    echo "Waiting for Kibana... (attempt $attempt/$max_attempts)"
    sleep 2
done

if [ $attempt -eq $max_attempts ]; then
    echo "ERROR: Kibana did not become ready in time"
    exit 1
fi

# Create semantic code search tool using index_search
# Note: This uses basic index search. For true semantic search, you may need to
# create an external API connector that calls your Django backend's semantic search endpoint.
echo ""
echo "Creating code search tool..."
SEARCH_TOOL_ID="code-semantic-search"
SEARCH_TOOL_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
    -u "${ELASTIC_USER}:${ELASTIC_PASSWORD}" \
    -H "Content-Type: application/json" \
    -H "kbn-xsrf: true" \
    "${KIBANA_HOST}/api/agent_builder/tools" \
    -d "{
        \"id\": \"${SEARCH_TOOL_ID}\",
        \"description\": \"Search the ${INDEX_NAME} index for code chunks. Use natural language queries to find relevant code, functions, classes, and documentation.\",
        \"type\": \"index_search\",
        \"tags\": [\"code\", \"search\", \"${INDEX_NAME}\"],
        \"configuration\": {
            \"pattern\": \"${INDEX_NAME}\"
        }
    }" 2>&1)

SEARCH_TOOL_HTTP_CODE=$(echo "$SEARCH_TOOL_RESPONSE" | tail -n1)
SEARCH_TOOL_BODY=$(echo "$SEARCH_TOOL_RESPONSE" | sed '$d')

if [ "$SEARCH_TOOL_HTTP_CODE" -eq 200 ] || [ "$SEARCH_TOOL_HTTP_CODE" -eq 201 ]; then
    echo "✓ Semantic search tool created successfully!"
elif [ "$SEARCH_TOOL_HTTP_CODE" -eq 409 ]; then
    echo "⚠ Semantic search tool already exists, skipping..."
else
    echo "⚠ Failed to create semantic search tool (HTTP $SEARCH_TOOL_HTTP_CODE)"
    echo "Response: $SEARCH_TOOL_BODY"
    echo ""
    echo "Note: ES|QL semantic queries might not be supported. Trying alternative approach..."
    
    # Alternative: Use index_search tool
    echo "Creating index_search tool as fallback..."
    INDEX_SEARCH_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
        -u "${ELASTIC_USER}:${ELASTIC_PASSWORD}" \
        -H "Content-Type: application/json" \
        -H "kbn-xsrf: true" \
        "${KIBANA_HOST}/api/agent_builder/tools" \
        -d "{
            \"id\": \"${SEARCH_TOOL_ID}\",
            \"description\": \"Search the ${INDEX_NAME} index for code chunks\",
            \"type\": \"index_search\",
            \"tags\": [\"code\", \"search\"],
            \"configuration\": {
                \"pattern\": \"${INDEX_NAME}\"
            }
        }" 2>&1)
    
    INDEX_SEARCH_HTTP_CODE=$(echo "$INDEX_SEARCH_RESPONSE" | tail -n1)
    if [ "$INDEX_SEARCH_HTTP_CODE" -eq 200 ] || [ "$INDEX_SEARCH_HTTP_CODE" -eq 201 ] || [ "$INDEX_SEARCH_HTTP_CODE" -eq 409 ]; then
        echo "✓ Index search tool created/updated"
    fi
fi

# Create code search agent
echo ""
echo "Creating code search agent..."
AGENT_ID="code-search-agent"
AGENT_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
    -u "${ELASTIC_USER}:${ELASTIC_PASSWORD}" \
    -H "Content-Type: application/json" \
    -H "kbn-xsrf: true" \
    "${KIBANA_HOST}/api/agent_builder/agents" \
    -d "{
        \"id\": \"${AGENT_ID}\",
        \"name\": \"Code Search Assistant\",
        \"description\": \"AI assistant that can search and understand code using semantic search\",
        \"configuration\": {
            \"instructions\": \"You are a helpful AI coding assistant. When users ask about code, projects, or need to find specific functionality, use the semantic code search tool to find relevant code chunks. Always cite the file paths and line numbers in your responses. Format code examples with proper syntax highlighting.\",
            \"tools\": [
                {
                    \"tool_ids\": [\"${SEARCH_TOOL_ID}\"]
                }
            ]
        }
    }" 2>&1)

AGENT_HTTP_CODE=$(echo "$AGENT_RESPONSE" | tail -n1)
AGENT_BODY=$(echo "$AGENT_RESPONSE" | sed '$d')

if [ "$AGENT_HTTP_CODE" -eq 200 ] || [ "$AGENT_HTTP_CODE" -eq 201 ]; then
    echo "✓ Code search agent created successfully!"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Agent ID: ${AGENT_ID}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "Update your Kibana provider configuration to use agent ID: ${AGENT_ID}"
elif [ "$AGENT_HTTP_CODE" -eq 409 ]; then
    echo "⚠ Agent already exists. Updating it..."
    # Try to update the agent
    UPDATE_RESPONSE=$(curl -s -w "\n%{http_code}" -X PUT \
        -u "${ELASTIC_USER}:${ELASTIC_PASSWORD}" \
        -H "Content-Type: application/json" \
        -H "kbn-xsrf: true" \
        "${KIBANA_HOST}/api/agent_builder/agents/${AGENT_ID}" \
        -d "{
            \"name\": \"Code Search Assistant\",
            \"description\": \"AI assistant that can search and understand code using semantic search\",
            \"configuration\": {
                \"instructions\": \"You are a helpful AI coding assistant. When users ask about code, projects, or need to find specific functionality, use the semantic code search tool to find relevant code chunks. Always cite the file paths and line numbers in your responses. Format code examples with proper syntax highlighting.\",
                \"tools\": [
                    {
                        \"tool_ids\": [\"${SEARCH_TOOL_ID}\"]
                    }
                ]
            }
        }" 2>&1)
    
    UPDATE_HTTP_CODE=$(echo "$UPDATE_RESPONSE" | tail -n1)
    if [ "$UPDATE_HTTP_CODE" -eq 200 ]; then
        echo "✓ Agent updated successfully!"
    else
        echo "⚠ Failed to update agent (HTTP $UPDATE_HTTP_CODE)"
    fi
else
    echo "⚠ Failed to create agent (HTTP $AGENT_HTTP_CODE)"
    echo "Response: $AGENT_BODY"
fi

echo ""
echo "Setup complete!"
echo ""
echo "To use this agent, update your Kibana provider configuration:"
echo "  Agent ID: ${AGENT_ID}"
echo ""
