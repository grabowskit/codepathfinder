# Local Elasticsearch Setup Guide

This guide describes how to configure your local development environment to use a local Elasticsearch and Kibana instance instead of the shared development server. This allows for isolated testing without affecting shared indexes.

## 1. Environment Configuration

You must update your environment variables in the primary `.env` file located at:
`.env` (in the project root)

### Elasticsearch Settings
Update the following keys to point to your local Elasticsearch instance:
- `ELASTICSEARCH_ENDPOINT`: Set this to your local URL (e.g., `http://localhost:9200`).
- `ELASTICSEARCH_API_KEY`: Update if your local setup uses API keys, or leave blank if using basic auth.
- `ELASTICSEARCH_USER`: (Optional) Local username.
- `ELASTICSEARCH_PASSWORD`: (Optional) Local password.

### Kibana Settings
The Kibana host is configured in the Django settings but can be overridden by environment variables if you add it to your `.env`:
- `KIBANA_HOST`: Set this to your local Kibana URL (e.g., `http://localhost:5601`).

---

## 2. Source Code Hardcoded Fallbacks

The application currently contains hardcoded fallback credentials in the indexing utility. For full isolation, these should be updated to match your local setup:

### Utility File: `web/projects/utils.py`
Update the credentials in the following two functions:

1.  **`trigger_local_indexer_job`**: Update the `environment` dictionary (around line 108).
2.  **`trigger_indexer_job`**: Update the `env` list (around line 194).

---

## 3. Applying Changes

After updating your configuration, restart the development services to apply the new settings:

```bash
# Restart Docker services
docker-compose down
docker-compose up -d

# Restart Django development server
# (Ensure your virtual environment is active)
python web/manage.py runserver 8000
```

> [!IMPORTANT]
> Ensure that your local Elasticsearch instance has the necessary inference models (e.g., ELSER) installed if you plan to use semantic search features locally.
