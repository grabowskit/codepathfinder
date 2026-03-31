# Local Development Guide

This guide explains how to run CodePathfinder locally using Docker Compose.

## Prerequisites
- Docker & Docker Compose
- Git
- gcloud CLI + kubectl (for deployment only)

## Running Locally

1. **Create the shared Docker network** (one-time):
   ```bash
   docker network create cpf-librechat
   ```
   This network allows the Django web app and LibreChat to communicate internally.

2. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your Elasticsearch credentials and API keys
   ```

3. **Start the Stack**
   ```bash
   docker-compose up --build
   ```
   This starts:
   - **Web App** (Django): http://localhost:8000
   - **PostgreSQL**: Port 5432
   - **Elasticsearch**: http://localhost:9200
   - **Kibana**: http://localhost:5601
   - **LibreChat**: http://localhost:3080 (also available via http://localhost:8000/chat/)
   - **MongoDB**: Port 27017 (for LibreChat)
   - **Meilisearch**: Port 7700 (for LibreChat)
   - **Nginx**: Ports 8000 (HTTP), 8443 (HTTPS), 3443 (LibreChat HTTPS)
   - **Indexer**: Background worker

4. **Database Setup (First Run)**
   ```bash
   docker-compose exec web python manage.py migrate
   docker-compose exec web python manage.py createsuperuser
   ```

5. **Access the App**
   - Main UI: http://localhost:8000
   - AI Chat: http://localhost:8000/chat/
   - MCP endpoint: http://localhost:8000/mcp/

## Elasticsearch Setup

The indexer service requires Elasticsearch with the ELSER (Elastic Learned Sparse EncodeR) model for semantic code search. **Without Elasticsearch configured, the indexer will fail to start.**

### Option 1: Local Elasticsearch (Default in docker-compose)

The `docker-compose.yml` includes an Elasticsearch 9.x service with security enabled. It starts automatically with the stack.

### Option 2: Elastic Cloud (Recommended for reliable ELSER)

1. Sign up for a free trial at [Elastic Cloud](https://cloud.elastic.co)
2. Create a deployment with **Machine Learning** capabilities enabled
3. Deploy the ELSER model (see [Elasticsearch ML documentation](https://www.elastic.co/guide/en/machine-learning/current/ml-nlp-elser.html))
4. Get your **Cloud ID** and **API key** from the deployment dashboard
5. Add to your `.env` file:
   ```bash
   ELASTICSEARCH_CLOUD_ID=your-cloud-id-from-elastic
   ELASTICSEARCH_API_KEY=your-api-key-from-elastic
   ```

### Option 3: Skip Indexer for Development

If you only want to test the web UI and chat without indexing functionality:

```bash
docker-compose up web db nginx librechat mongodb meilisearch
```

Projects can be created but won't be indexed.

### Checking Indexer Status

```bash
# View indexer logs
docker-compose logs -f indexer

# Should NOT show "Elasticsearch connection not configured" error
```

## LibreChat Setup

LibreChat is the AI chat interface. It connects to CodePathfinder's MCP server for tool access.

### How It Works

- LibreChat is built from `chat/Dockerfile` and configured via `chat-config/librechat.yaml`
- It connects to the Django MCP server at `http://web:8000/mcp/` over the shared `cpf-librechat` network
- Auth uses the `CPF_INTERNAL_SERVICE_SECRET` environment variable (shared between both services)
- LLM providers (OpenAI, Anthropic) are configured in `chat-config/librechat.yaml`

### Configuration

Edit `chat-config/librechat.yaml` to:
- Add/remove LLM models
- Configure model presets
- Adjust MCP server settings

### Required API Keys

For LibreChat to work, you need at least one LLM API key in your `.env`:
```bash
OPENAI_API_KEY=sk-...
# and/or
ANTHROPIC_API_KEY=sk-ant-...
```

### Troubleshooting LibreChat

```bash
# View LibreChat logs
docker-compose logs -f librechat

# Check MCP connection
docker-compose logs librechat | grep -i mcp

# Verify the shared network exists
docker network ls | grep cpf-librechat
```

If LibreChat can't connect to MCP tools:
1. Ensure `cpf-librechat` network exists
2. Check that both `web` and `librechat` services are running
3. Verify `CPF_INTERNAL_SERVICE_SECRET` matches in both services

## Authentication & Email

- New users (Email or Google) are created as **Inactive** by default.
- You MUST have an admin user (superuser) to approve them.
- Verification emails are sent to the console logs. Run `docker-compose logs -f web` to see them.

### Google OAuth Setup

To enable "Sign in with Google", add these to your `.env` file (get credentials from [Google Cloud Console](https://console.cloud.google.com/)):
```bash
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
```

## Running Tests

### Smoke Tests

The smoke test suite validates that all services are running correctly:

```bash
python scripts/smoke_test.py
```

This checks health endpoints, auth, MCP connectivity, projects, and LibreChat. See [SMOKE_TESTS.md](SMOKE_TESTS.md) for details.

### Django Tests

```bash
docker-compose exec web python manage.py test
```

## Useful Commands

```bash
# View all logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f web
docker-compose logs -f librechat
docker-compose logs -f indexer

# Restart a service
docker-compose restart web

# Django shell
docker-compose exec web python manage.py shell

# Database shell
docker-compose exec web python manage.py dbshell

# Run migrations
docker-compose exec web python manage.py migrate

# List Elasticsearch indices
docker-compose exec web python manage.py list_indices

# Check job statuses
docker-compose exec web python manage.py check_job_status --verbose
```

## Deployment

To deploy changes to GCP production:

```bash
./scripts/deploy.sh [version_tag]
```

If no version tag is provided, a timestamp-based tag will be generated automatically.

Example:
```bash
./scripts/deploy.sh v1.3.0
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for full production deployment guide.

## Troubleshooting

- **Database Connection Issues**: Ensure the `db` service is healthy with `docker-compose ps`.
- **Static Files**: In local mode (`DEBUG=1`), Django serves static files. In production, WhiteNoise handles them.
- **Port Conflicts**: If port 8000 is in use, check for other Docker containers or local processes.
- **LibreChat Not Loading**: Verify the `cpf-librechat` network exists and both services are on it.
- **MCP Tools Not Available**: Check LibreChat logs for MCP connection errors. Ensure `CPF_INTERNAL_SERVICE_SECRET` is set.
