#!/bin/bash
set -e

echo "=== Pathfinder Setup ==="
echo ""

# Initialize and update submodules
echo "1. Initializing git submodules..."
git submodule update --init --recursive
echo "   Done."
echo ""

# Create chat-config/.env from template if it doesn't exist
if [ ! -f "chat-config/.env" ]; then
    echo "2. Creating chat-config/.env from template..."
    cp chat-config/.env.template chat-config/.env
    echo "   Created chat-config/.env"
    echo ""
    echo "   IMPORTANT: Edit chat-config/.env and add:"
    echo "   - OPENAI_API_KEY or ANTHROPIC_API_KEY (for LLM access)"
    echo "   - CPF_API_KEY (create in Django admin after first boot)"
    echo "   - CREDS_KEY, JWT_SECRET, etc. (generate secure values)"
    echo ""
else
    echo "2. chat-config/.env already exists, skipping..."
    echo ""
fi

# Create shared Docker network if it doesn't exist
if ! docker network inspect cpf-librechat >/dev/null 2>&1; then
    echo "3. Creating shared Docker network (cpf-librechat)..."
    docker network create cpf-librechat
    echo "   Done."
else
    echo "3. Docker network cpf-librechat already exists, skipping..."
fi
echo ""

# Check for required external volumes
echo "4. Checking Docker volumes..."
MISSING_VOLUMES=""
if ! docker volume inspect pathfinder-prototype_postgres_data >/dev/null 2>&1; then
    MISSING_VOLUMES="$MISSING_VOLUMES pathfinder-prototype_postgres_data"
fi
if ! docker volume inspect pathfinder-prototype_elasticsearch_data >/dev/null 2>&1; then
    MISSING_VOLUMES="$MISSING_VOLUMES pathfinder-prototype_elasticsearch_data"
fi

if [ -n "$MISSING_VOLUMES" ]; then
    echo "   WARNING: Missing external volumes:$MISSING_VOLUMES"
    echo "   Create them with: docker volume create <volume_name>"
else
    echo "   All required volumes exist."
fi
echo ""

echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit chat-config/.env with your API keys"
echo "  2. Run: docker compose build"
echo "  3. Run: docker compose up -d"
echo "  4. Access:"
echo "     - CodePathfinder: https://localhost:8443"
echo "     - LibreChat: http://localhost:3080"
echo "     - Kibana: http://localhost:5601"
echo ""
echo "  5. Create a CPF_API_KEY in Django admin:"
echo "     - https://localhost:8443/admin/"
echo "     - Projects > Project API Keys > Add"
echo "     - Copy the key to chat-config/.env"
echo "     - Restart: docker compose restart librechat"
