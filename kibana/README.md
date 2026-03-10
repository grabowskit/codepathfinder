# Kibana Configuration

This directory contains configuration files for the local Kibana instance.

## Files

- `config/kibana.yml` - Main Kibana configuration file

## Enabling Agent Builder

Agent Builder in Kibana 9.2 is in technical preview and must be enabled via the Advanced Settings API or UI. 

### Option 1: Automatic (Recommended)

After starting Kibana with `docker-compose up`, run:

```bash
./scripts/enable-agent-builder.sh
```

This script will:
1. Wait for Kibana to be ready
2. Enable Agent Builder via the settings API
3. Provide instructions for configuring LLM connectors

### Option 2: Manual via Kibana UI

1. Open Kibana at http://localhost:5601
2. Log in with your Elasticsearch credentials (default: `elastic` / `changeme`)
3. Use the **Global Search** (top search bar)
4. Search for "Agent Builder"
5. Toggle the "Elastic Agent Builder" switch to **ON**
6. Save changes

### Option 3: Manual via API

```bash
curl -X POST "http://localhost:5601/internal/kibana/settings" \
  -u elastic:changeme \
  -H "Content-Type: application/json" \
  -H "kbn-xsrf: true" \
  -d '{
    "changes": {
      "agentBuilder:enabled": true
    }
  }'
```

## Configuring LLM Connectors

After enabling Agent Builder, you need to configure an LLM connector:

1. In Kibana, go to **Global Search** → "GenAI Settings"
2. Or navigate to: **Management** → **Kibana** → **AI Assistant Management**
3. Set up a **Default AI Connector**:
   - Choose from available connectors (OpenAI, Anthropic, etc.)
   - Or create a new connector with your API credentials
4. Save the settings

## Troubleshooting

If you see errors about connectors not being available:

1. **Check Agent Builder is enabled**: Verify the feature is toggled ON in Advanced Settings
2. **Check license**: Agent Builder requires an Enterprise license (trial license works for development)
3. **Check permissions**: Ensure your user has the `kibana_admin` role or appropriate permissions
4. **Check Elasticsearch connection**: Verify Kibana can connect to Elasticsearch

## References

- [Elastic Agent Builder Documentation](https://www.elastic.co/docs/solutions/search/agent-builder)
- [Kibana Advanced Settings](https://www.elastic.co/guide/en/kibana/current/advanced-options.html)
