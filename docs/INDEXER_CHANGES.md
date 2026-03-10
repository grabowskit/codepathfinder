# Indexer App Modifications

This document details all modifications made to the indexer application from the original open source repository at [elastic/semantic-code-search-indexer](https://github.com/elastic/semantic-code-search-indexer).

**Last Updated:** December 2, 2025  
**Base Repository:** https://github.com/elastic/semantic-code-search-indexer

---

## Table of Contents

1. [Overview](#overview)
2. [Critical Changes](#critical-changes)
3. [File-Specific Modifications](#file-specific-modifications)
4. [Environment Configuration](#environment-configuration)
5. [Deployment Changes](#deployment-changes)
6. [Upgrade Path](#upgrade-path)

---

## Overview

The CodePathfinder indexer is based on Elastic's semantic-code-search-indexer but has been customized for production deployment on Kubernetes with specific configuration optimizations for Elastic Cloud.

### Key Modifications

- **Production Runtime**: Changed from development (`ts-node`) to production (`node dist/index.js`)
- **Index Name Normalization**: Added automatic lowercase conversion for Elasticsearch index names
- **Resource Optimization**: Tuned for GKE e2-small nodes (200m CPU / 256Mi Memory)
- **Batch Size Configuration**: Reduced to 14 for Elastic Inference Service (EIS) compatibility
- **Environment Configuration**: Customized environment variables for Kubernetes deployment

---

## Critical Changes

### 1. Index Name Case Normalization

**File:** `src/utils/elasticsearch.ts`  
**Lines Modified:** 78, 145, 165, 181, 252, 310, 373, 435, 446

**Change:**
```typescript
// BEFORE (Original)
const indexName = index || defaultIndexName;

// AFTER (Modified)
const indexName = (index || defaultIndexName).toLowerCase();
```

**Reason:**  
Elasticsearch **rejects index names containing uppercase letters**. The original code allowed users to create indexes with names like "ClickHouse" which would fail. This modification ensures all index names are automatically converted to lowercase (e.g., "clickhouse") to comply with Elasticsearch requirements.

**Functions Affected:**
- `createIndex()`
- `createSettingsIndex()`
- `getLastIndexedCommit()`
- `updateLastIndexedCommit()`
- `indexCodeChunks()`
- `searchCodeChunks()`
- `aggregateBySymbols()`
- `deleteIndex()`
- `deleteDocumentsByFilePath()`

**Impact:** This is a **non-breaking change** that improves user experience by preventing index creation failures.

---

### 2. Production Container Runtime

**File:** `apps/web/projects/utils.py` (Django job configuration)  
**Line:** 70

**Change:**
```python
# BEFORE (Development)
command=["npx", "ts-node", "src/index.ts", "index"]

# AFTER (Production)
command=["node", "dist/index.js", "index"]
```

**Reason:**  
The production Docker image (`apps/indexer/Dockerfile`) builds TypeScript into JavaScript at build time. Using `ts-node` in production would require installing development dependencies (TypeScript, ts-node) in the production image, increasing image size and attack surface. The compiled JavaScript approach:
- **Reduces image size** by excluding dev dependencies
- **Improves startup time** (no TypeScript compilation needed)
- **Follows Docker best practices** for production deployments

**Related Files:**
- `apps/indexer/Dockerfile` - Multi-stage build compiling TS to JS
- `apps/indexer/package.json` - Build scripts

---

## File-Specific Modifications

### `src/utils/elasticsearch.ts`

**Purpose:** Elasticsearch client and index management

**Changes:**

1. **Function: `createIndex()`**
   - Line 78: `const indexName = (index || defaultIndexName).toLowerCase();`
   - **Why:** Ensure index names comply with Elasticsearch naming rules

2. **Function: `createSettingsIndex()`**
   - Line 145: `const settingsIndexName = \`\${(index || defaultIndexName).toLowerCase()}_settings\`;`
   - **Why:** Settings index must also use lowercase naming

3. **Function: `getLastIndexedCommit()`**
   - Line 165: `const settingsIndexName = \`\${(index || defaultIndexName).toLowerCase()}_settings\`;`
   - **Why:** Query correct settings index name

4. **Function: `updateLastIndexedCommit()`**
   - Line 181: `const settingsIndexName = \`\${(index || defaultIndexName).toLowerCase()}_settings\`;`
   - **Why:** Update correct settings index name

5. **Function: `indexCodeChunks()`**
   - Line 252: `const indexName = (index || defaultIndexName).toLowerCase();`
   - **Why:** Bulk indexing operations must target correctly named index

6. **Function: `searchCodeChunks()`**
   - Line 310: `const indexName = (index || defaultIndexName).toLowerCase();`
   - **Why:** Search queries must target correctly named index

7. **Function: `aggregateBySymbols()`**
   - Line 373: `const indexName = (index || defaultIndexName).toLowerCase();`
   - **Why:** Aggregation queries must target correctly named index

8. **Function: `deleteIndex()`**
   - Line 435: `const indexName = (index || defaultIndexName).toLowerCase();`
   - **Why:** Deletion operations must target correctly named index

9. **Function: `deleteDocumentsByFilePath()`**
   - Line 446: `const indexName = (index || defaultIndexName).toLowerCase();`
   - **Why:** Document deletion must target correctly named index

**No other logic changes** were made to this file.

---

### `apps/indexer/Dockerfile`

**Purpose:** Production container image definition

**Status:** Likely **unchanged** from upstream, but critical to deployment

**Key Features:**
- Multi-stage build (builder stage + production stage)
- Compiles TypeScript to JavaScript
- Excludes development dependencies from production image
- Uses Node.js 20 Alpine for minimal image size

**Build Command:**
```bash
docker build --platform linux/amd64 -f apps/indexer/Dockerfile -t gcr.io/PROJECT_ID/indexer:v1.0.0 .
```

---

### Environment Configuration Files

**No modifications** to core source files beyond `elasticsearch.ts` and container runtime.

---

## Environment Configuration

### Production Environment Variables

**Set in:** `apps/web/projects/utils.py` (Kubernetes Job spec)

```python
env=[
    client.V1EnvVar(name="ELASTICSEARCH_ENDPOINT", value="https://<YOUR_ES_ENDPOINT>"),
    client.V1EnvVar(name="ELASTICSEARCH_API_KEY", value="<your-api-key>"),
    client.V1EnvVar(name="ELASTICSEARCH_INFERENCE_ID", value=".elser-2-elasticsearch"),
    client.V1EnvVar(name="ELASTICSEARCH_INDEX", value="code-chunks"),
    client.V1EnvVar(name="SEMANTIC_CODE_INDEXER_LANGUAGES", value="typescript,javascript,markdown,yaml,java,go,python"),
    client.V1EnvVar(name="BATCH_SIZE", value="14"),  # Critical for EIS
    client.V1EnvVar(name="OTEL_LOGGING_ENABLED", value="false"),
    client.V1EnvVar(name="OTEL_SERVICE_NAME", value="semantic-code-search-indexer"),
    client.V1EnvVar(name="NODE_ENV", value="production"),
]
```

**Critical Variables:**

1. **`BATCH_SIZE=14`**
   - **Original:** 500 (default in upstream)
   - **Modified:** 14
   - **Reason:** Elastic Inference Service (EIS) rate limits. The default batch size of 500 overwhelmed EIS, causing "Error processing batch" loops. A batch size of 14 is recommended by Elastic for EIS deployments.

2. **`ELASTICSEARCH_INFERENCE_ID=.elser-2-elasticsearch`**
   - **Purpose:** Specifies the ELSER model for semantic embeddings
   - **Required:** For Elastic Cloud deployments using ELSER v2

3. **`OTEL_LOGGING_ENABLED=false`**
   - **Purpose:** Disables OpenTelemetry logging in production
   - **Reason:** Reduces log verbosity and resource usage

---

## Deployment Changes

### Kubernetes Job Configuration

**File:** `apps/web/projects/utils.py`

**Resource Limits:**
```python
resources=client.V1ResourceRequirements(
    limits={"cpu": "1", "memory": "1Gi"},
    requests={"cpu": "200m", "memory": "256Mi"}  # Tuned for e2-small nodes
)
```

**Changes from Upstream:**
- **Original:** Not Kubernetes-native (designed for local execution)
- **Modified:** Full Kubernetes Job integration with:
  - Job TTL (1 hour after completion)
  - Backoff limits (4 retries)
  - Active deadline (4 hours max runtime)
  - Persistent volume mounts for repository data
  - Label-based tracking per project

### Image Configuration

**File:** `apps/web/projects/utils.py`

```python
image_name = "<YOUR_REGISTRY>/indexer:v1.0.0"
image_pull_policy = "Always"
```

**Changes:**
- **Original:** Docker Compose with `indexer:local` tag
- **Modified:** GCR-hosted production image with always-pull policy

---

## Upgrade Path

### When Updating from Upstream

If you need to pull updates from the upstream repository, follow these steps:

1. **Preserve Critical Changes**
   
   Before merging upstream changes, create a backup of:
   ```bash
   cp apps/indexer/src/utils/elasticsearch.ts apps/indexer/src/utils/elasticsearch.ts.backup
   ```

2. **Merge Upstream Changes**
   
   ```bash
   cd apps/indexer
   git remote add upstream https://github.com/elastic/semantic-code-search-indexer.git
   git fetch upstream
   git merge upstream/main
   ```

3. **Re-apply Lowercase Modifications**
   
   After merging, search for all occurrences in `elasticsearch.ts`:
   ```bash
   grep -n "index || defaultIndexName" apps/indexer/src/utils/elasticsearch.ts
   ```
   
   For each occurrence, wrap with `.toLowerCase()`:
   ```typescript
   (index || defaultIndexName).toLowerCase()
   ```

4. **Verify Environment Variables**
   
   Ensure `apps/web/projects/utils.py` still has:
   - Correct `command` (using `node dist/index.js`)
   - `BATCH_SIZE=14`
   - All required Elasticsearch environment variables

5. **Test Locally**
   
   ```bash
   # Rebuild indexer image
   cd apps/indexer
   docker build -t indexer:local .
   
   # Test with Docker Compose
   cd ../..
   docker-compose up
   
   # Create a test project and verify indexing works
   ```

6. **Deploy to Production**
   
   ```bash
   # Build production image
   docker build --platform linux/amd64 -f apps/indexer/Dockerfile -t gcr.io/PROJECT_ID/indexer:v1.0.1 apps/indexer
   docker push gcr.io/PROJECT_ID/indexer:v1.0.1
   
   # Update image reference in projects/utils.py
   image_name = "gcr.io/PROJECT_ID/indexer:v1.0.1"
   ```

---

## Testing Modified Functionality

### Test 1: Index Name Normalization

```bash
# Create a project with mixed-case name via UI
Name: "MyAwesomeProject"
Repository URL: "https://github.com/test/repo"

# Verify index created with lowercase name
curl -X GET "http://elasticsearch:9200/myawesomeproject"
# Should return index info, not 404
```

### Test 2: Production Runtime

```bash
# Check running job uses compiled JS
kubectl logs -n code-pathfinder -l app=indexer-cli --tail=10

# Should show "node dist/index.js" in process, NOT "ts-node"
```

### Test 3: Batch Size Configuration

```bash
# Monitor logs during indexing
kubectl logs -f -n code-pathfinder POD_NAME

# Should show "Enqueued batch of 14 documents" (not 500)
# Should NOT show "Error processing batch" loops
```

---

## Summary

### Modified Files

1. **`src/utils/elasticsearch.ts`** - Added `.toLowerCase()` to 9 functions
2. **`apps/web/projects/utils.py`** (Django app) - Production runtime, environment vars, resources

### Unmodified Files

All other indexer source files remain **unchanged** from the upstream repository.

### Deployment-Specific

- Kubernetes Job configuration (`projects/utils.py`)
- Docker build process (`Dockerfile`)
- Environment variables for Elastic Cloud

---

## Questions or Issues?

If you encounter issues after updating from upstream:

1. **Index creation fails:** Verify `.toLowerCase()` is present in all index name operations
2. **Container fails to start:** Check that `command` uses `node dist/index.js`, not `ts-node`
3. **Rate limiting errors:** Confirm `BATCH_SIZE=14` is set in job environment

For further assistance, refer to:
- [DEPLOYMENT.md](DEPLOYMENT.md) - Production deployment guide
- [PROJECT_DOCUMENTATION.md](PROJECT_DOCUMENTATION.md) - Full system documentation
