# CodePathfinder - GCP Deployment Guide

This guide details the step-by-step process to deploy CodePathfinder to Google Cloud Platform (GCP) using Google Kubernetes Engine (GKE) and Cloud SQL.

## 1. Prerequisites

### Tools Required
Ensure you have the following CLI tools installed and authenticated:
*   **Google Cloud CLI (`gcloud`)**: For managing GCP resources.
*   **Kubernetes CLI (`kubectl`)**: For cluster management.
*   **Docker**: For building and pushing images.

### GCP Project Setup
1.  **Create a Project**: Create a new project in GCP Console (e.g., `codepathfinder-prod`).
2.  **Enable Billing**: Link a billing account.
3.  **Enable APIs**:
    ```bash
    gcloud services enable \
      container.googleapis.com \
      sqladmin.googleapis.com \
      compute.googleapis.com \
      artifactregistry.googleapis.com \
      iam.googleapis.com
    ```

## 2. Infrastructure Setup

### Network & Static IP
Reserve a static external IP for the Ingress controller to ensure the domain always points to the correct address.
```bash
gcloud compute addresses create codepathfinder-ip --global
```

### Cloud SQL (PostgreSQL)
Create a managed PostgreSQL instance.
1.  Create instance:
    ```bash
    gcloud sql instances create codepathfinder-db \
      --database-version=POSTGRES_15 \
      --tier=db-f1-micro \
      --region=us-central1
    ```
2.  Create database and user:
    ```bash
    gcloud sql databases create codepathfinder --instance=codepathfinder-db
    gcloud sql users create codepathfinder --instance=codepathfinder-db --password=YOUR_PASSWORD
    ```

### GKE Cluster
Create a cost-effective cluster. **Crucial:** Enable `cloud-platform` scope for Workload Identity and Cloud SQL access.
```bash
gcloud container clusters create codepathfinder-cluster \
  --region us-central1 \
  --num-nodes 1 \
  --machine-type e2-small \
  --scopes "https://www.googleapis.com/auth/cloud-platform" \
  --workload-pool=PROJECT_ID.svc.id.goog
```

## 3. Configuration & Secrets

### Namespaces
Create dedicated namespaces for the application.
```bash
kubectl create namespace codepathfinder
kubectl create namespace code-pathfinder
```

### Secrets
Store sensitive data (DB credentials, Django secret).
1.  **Application Secrets**:
    ```bash
    kubectl create secret generic codepathfinder-secrets \
      --from-literal=DATABASE_URL="postgres://codepathfinder:PASSWORD@localhost:5432/codepathfinder" \
      --from-literal=DJANGO_SECRET_KEY="your-secret-key" \
      -n codepathfinder
    ```
2.  **GCR Image Pull Secrets** (Required for both namespaces):
    ```bash
    # For web app namespace
    kubectl create secret docker-registry gcr-json-key \
      --docker-server=gcr.io \
      --docker-username=oauth2accesstoken \
      --docker-password="$(gcloud auth print-access-token)" \
      --docker-email=your-email@example.com \
      -n codepathfinder
    
    # For indexer jobs namespace
    kubectl create secret docker-registry gcr-json-key \
      --docker-server=gcr.io \
      --docker-username=oauth2accesstoken \
      --docker-password="$(gcloud auth print-access-token)" \
      --docker-email=your-email@example.com \
      -n code-pathfinder
    ```
    
    > **Note**: These secrets expire after ~1 hour. You'll need to refresh them periodically:
    ```bash
    kubectl delete secret gcr-json-key -n code-pathfinder
    kubectl create secret docker-registry gcr-json-key --docker-server=gcr.io --docker-username=oauth2accesstoken --docker-password="$(gcloud auth print-access-token)" --docker-email=your-email@example.com -n code-pathfinder
    ```

### Service Accounts & RBAC
The application needs permissions to create Kubernetes Jobs for indexing.
1.  **Apply RBAC Configuration**:
    ```bash
    kubectl apply -f kubernetes/rbac.yaml
    ```
    This creates:
    - `codepathfinder-ksa` ServiceAccount in `codepathfinder` namespace
    - `indexer-sa` ServiceAccount in `code-pathfinder` namespace
    - Role granting job management permissions
    - RoleBinding allowing cross-namespace access

## 4. Application Deployment

### Build & Push Images
1.  **Web App**:
    ```bash
    docker build --platform linux/amd64 -f Dockerfile.prod -t gcr.io/PROJECT_ID/codepathfinder:v1.0.0 .
    docker push gcr.io/PROJECT_ID/codepathfinder:v1.0.0
    ```
2.  **Indexer**:
    ```bash
    # From indexer directory
    cd indexer
    docker build --platform linux/amd64 -t gcr.io/PROJECT_ID/indexer:v1.0.0 .
    docker push gcr.io/PROJECT_ID/indexer:v1.0.0
    ```

### Deploy to Kubernetes
Apply the manifest files in order:
```bash
kubectl apply -f kubernetes/pvc.yaml        # Storage for indexer
kubectl apply -f kubernetes/rbac.yaml       # Permissions
kubectl apply -f kubernetes/deployment.yaml # Web app & Sidecar
kubectl apply -f kubernetes/service.yaml    # Internal networking
kubectl apply -f kubernetes/ingress.yaml    # External access & SSL
```

### DNS Configuration
Get the static IP address and point your domain's A record to it.
```bash
kubectl get ingress -n codepathfinder
```

## 5. Troubleshooting Guide

### Common Issues & Fixes

#### 1. 502 Server Error (Bad Gateway)
*   **Cause**: Health checks failing. GKE Ingress expects a 200 OK response.
*   **Check**:
    ```bash
    kubectl describe pod -n codepathfinder
    ```
*   **Fix**: Ensure `readinessProbe` and `livenessProbe` point to `/health/` endpoint.

#### 2. ImagePullBackOff / 401/403 Forbidden
*   **Cause**: GKE node cannot pull the image from GCR due to expired credentials.
*   **Check**:
    ```bash
    kubectl describe pod POD_NAME -n codepathfinder
    kubectl describe pod POD_NAME -n code-pathfinder
    ```
*   **Fix**: Refresh the `gcr-json-key` secrets in both namespaces (see section 3).

#### 3. Job Creation Failed (403 Forbidden)
*   **Cause**: Web app ServiceAccount doesn't have RBAC permissions to create Jobs.
*   **Check**: App logs (`kubectl logs -n codepathfinder -l app=codepathfinder`). Look for "User ... cannot create resource jobs".
*   **Fix**: Ensure `kubernetes/rbac.yaml` is applied correctly.

#### 4. Pod Pending (Insufficient Resources)
*   **Cause**: Pod requests more CPU/Memory than the node has available.
*   **Check**:
    ```bash
    kubectl describe pod POD_NAME -n code-pathfinder
    kubectl top nodes
    ```
*   **Fix**: Reduce `resources.requests` in `apps/web/projects/utils.py` (for Indexer jobs). For `e2-small` nodes (2 vCPU, 2GB RAM), keep requests at **200m CPU / 256Mi Memory** or lower.

#### 5. Console Not Showing Logs
*   **Cause**: Job stuck in `Pending` or `ImagePullBackOff` state.
*   **Check**:
    ```bash
    kubectl get jobs -n code-pathfinder
    kubectl get pods -n code-pathfinder
    ```
*   **Fix**: 
    - For `ImagePullBackOff`: Refresh GCR secrets (see issue #2)
    - For `Pending`: Check resource usage and reduce requests (see issue #4)
    - Clean up stuck jobs: `kubectl delete job --all -n code-pathfinder`

### Useful Debug Commands

**View App Logs:**
```bash
kubectl logs -n codepathfinder -l app=codepathfinder --tail=100 -f
```

**View Indexer Job Logs:**
```bash
kubectl get pods -n code-pathfinder
kubectl logs -n code-pathfinder POD_NAME --tail=100 -f
```

**Check Pod/Job Status:**
```bash
kubectl get pods -n codepathfinder
kubectl get pods -n code-pathfinder
kubectl get jobs -n code-pathfinder
```

**Check Resource Usage:**
```bash
kubectl top nodes
kubectl top pods -n codepathfinder
```

**Delete Stuck Jobs:**
```bash
kubectl delete job --all -n code-pathfinder
```

**Access Database Shell:**
```bash
POD=$(kubectl get pod -n codepathfinder -l app=codepathfinder -o jsonpath="{.items[0].metadata.name}")
kubectl exec -it $POD -n codepathfinder -c web -- ./manage.py dbshell
```

## 6. Maintenance

### Updating the Application
1.  Build new image with updated tag:
    ```bash
    docker build --platform linux/amd64 -f Dockerfile.prod -t gcr.io/PROJECT_ID/codepathfinder:v1.1.0 .
    docker push gcr.io/PROJECT_ID/codepathfinder:v1.1.0
    ```
2.  Update `kubernetes/deployment.yaml` image tag
3.  Apply changes:
    ```bash
    kubectl apply -f kubernetes/deployment.yaml
    kubectl rollout restart deployment/codepathfinder -n codepathfinder
    ```

### Refreshing GCR Credentials
GCR image pull secrets expire after ~1 hour. Refresh them periodically:
```bash
kubectl delete secret gcr-json-key -n code-pathfinder
kubectl create secret docker-registry gcr-json-key --docker-server=gcr.io --docker-username=oauth2accesstoken --docker-password="$(gcloud auth print-access-token)" --docker-email=your-email@example.com -n code-pathfinder
```

## 7. MCP Tools & Claude Desktop

### Architecture
CodePathfinder exposes Model Context Protocol (MCP) tools via two endpoints:
1. **Streamable HTTP** (`/mcp/`): Handled by `web/mcp_server/streamable.py`. This is the primary endpoint used by **Claude Desktop** and **LibreChat**.
2. **Legacy SSE** (`/mcp/sse/` + `/mcp/messages/`): Handled by `web/mcp_server/views.py`.

### Tool Definitions
All 21 tools (Code Search, GitHub, Skills, Jobs) are defined in a centralized location:
- `web/mcp_server/tools.py` in the `TOOL_DEFINITIONS` list.

**Important**: Both endpoints import `TOOL_DEFINITIONS` from this file. If you add or modify a tool, you **must** update this list.

### Authentication
Three authentication methods (checked in priority order):
1. **Internal service secret** (`CPF_INTERNAL_SERVICE_SECRET` header) → superuser context (used by LibreChat)
2. **Project API keys** (`cpf_`-prefixed Bearer tokens) → project owner context
3. **OAuth2 access tokens** → token user context

### LibreChat Integration
In production, LibreChat connects to the MCP server via Kubernetes cluster DNS:
```
http://codepathfinder-service.codepathfinder.svc.cluster.local/mcp/
```
Auth is via Bearer token using the shared `CPF_INTERNAL_SERVICE_SECRET` secret.

The LibreChat config is managed via a ConfigMap (sourced from `chat-config/librechat.yaml`).

### Updating MCP Tools
When adding or modifying tools:
1. Update `TOOL_DEFINITIONS` in `web/mcp_server/tools.py`.
2. Implement the tool logic in `tools.py` (and register it in `TOOLS` dict).
3. **Rebuild and Deploy**:
   MCP clients fetch tool definitions from the server. You must deploy the changes for them to appear.
   ```bash
   # Build & Push
   docker build --platform linux/amd64 -f Dockerfile.prod -t us-central1-docker.pkg.dev/PROJECT_ID/codepathfinder/web:vX.Y.Z .
   docker push us-central1-docker.pkg.dev/PROJECT_ID/codepathfinder/web:vX.Y.Z

   # Update Deployment
   kubectl set image deployment/codepathfinder web=us-central1-docker.pkg.dev/PROJECT_ID/codepathfinder/web:vX.Y.Z -n codepathfinder
   ```
4. **Client Refresh**:
   Users may need to restart Claude Desktop or re-connect the MCP server to fetch the new tool list. LibreChat picks up changes on its next MCP connection (typically on startup).
