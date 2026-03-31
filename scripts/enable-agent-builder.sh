#!/bin/bash
# Script to enable Agent Builder in Kibana via the settings API
# This should be run after Kibana has started

set -e

KIBANA_HOST="${KIBANA_HOST:-http://localhost:5601}"
ELASTIC_USER="${ELASTICSEARCH_USER:-elastic}"
ELASTIC_PASSWORD="${ELASTICSEARCH_PASSWORD:-changeme}"

echo "Enabling Agent Builder in Kibana at ${KIBANA_HOST}..."

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

# Enable Agent Builder via Advanced Settings
# Note: The internal/kibana/settings endpoint may not be available in all Kibana versions
# We'll try the API first, then provide manual instructions

echo "Attempting to enable Agent Builder via API..."
response=$(curl -s -w "\n%{http_code}" -X POST \
    -u "${ELASTIC_USER}:${ELASTIC_PASSWORD}" \
    -H "Content-Type: application/json" \
    -H "kbn-xsrf: true" \
    "${KIBANA_HOST}/internal/kibana/settings" \
    -d '{
        "changes": {
            "agentBuilder:enabled": true
        }
    }' 2>&1)

http_code=$(echo "$response" | tail -n1)
body=$(echo "$response" | sed '$d')

if [ "$http_code" -eq 200 ] || [ "$http_code" -eq 204 ]; then
    echo "✓ Agent Builder enabled successfully via API!"
    echo "Response: $body"
else
    echo "⚠ API endpoint not available (HTTP $http_code)"
    echo "Response: $body"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Agent Builder must be enabled manually via the Kibana UI"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "Steps to enable Agent Builder:"
    echo ""
    echo "1. Open Kibana in your browser:"
    echo "   ${KIBANA_HOST}"
    echo ""
    echo "2. Log in with credentials:"
    echo "   Username: ${ELASTIC_USER}"
    echo "   Password: ${ELASTIC_PASSWORD}"
    echo ""
    echo "3. Navigate to Advanced Settings:"
    echo "   - Click the menu (☰) in the top left"
    echo "   - Go to: Stack Management → Advanced Settings"
    echo "   - OR use Global Search (top search bar) and search for 'Advanced Settings'"
    echo ""
    echo "4. Search for 'agentBuilder' in the settings search box"
    echo ""
    echo "5. Find 'agentBuilder:enabled' and toggle it to 'true'"
    echo ""
    echo "6. Click 'Save changes' at the bottom"
    echo ""
    echo "After enabling, you can configure LLM connectors at:"
    echo "  ${KIBANA_HOST}/app/management/kibana/aiAssistantManagement"
    echo ""
    echo "Or via Global Search → 'GenAI Settings' → 'Default AI Connector'"
    echo ""
    exit 0  # Don't fail, just provide instructions
fi

echo ""
echo "Agent Builder is now enabled. You can configure LLM connectors in:"
echo "  ${KIBANA_HOST}/app/management/kibana/aiAssistantManagement"
echo ""
echo "Or via Global Search → 'GenAI Settings' → 'Default AI Connector'"
