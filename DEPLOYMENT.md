# CodePathfinder Production Deployment Guide

**Target Audience**: AI agents and developers deploying to production GKE cluster

> **📌 Important**: Elasticsearch trial licenses expire every 30 days. When indexing stops working, see [docs/ELASTICSEARCH_LICENSE_RESET.md](docs/ELASTICSEARCH_LICENSE_RESET.md) for the reset procedure.

## Production Environment Overview

- **GCP Project**: `wired-sound-479919-k8`
- **GKE Cluster**: `codepathfinder-cluster` (zone: `us-central1-a`)
- **Namespace**: `codepathfinder`
- **Domain**: `codepathfinder.com` (main), `chat.codepathfinder.com` (LibreChat)
- **Registry**: `us-central1-docker.pkg.dev/wired-sound-479919-k8/codepathfinder/`
- **Database**: Cloud SQL (via cloud-sql-proxy sidecar)

## Pre-Deployment Checklist

### 1. Code Validation
Before building any images, verify:

```bash
# Test Python syntax
python -m py_compile web/**/*.py

# Check for import errors (run from project root)
cd web && python -c "import django; django.setup()" 2>&1 | grep -i error

# Verify no references to deleted models/views
grep -r "ChatConversation\|ChatMessage" web/chat/*.py --exclude-dir=migrations
```

### 2. Local Testing
```bash
# Rebuild local containers after code changes
docker compose up -d --build web

# CRITICAL: After rebuilding web locally, always reload nginx
docker compose exec nginx nginx -s reload

# Test health endpoint
curl http://localhost/health/
```

⚠️ **Common Mistake**: `docker compose restart` does NOT reload code. Always use `--build`.

### 3. Database Migrations
```bash
# Check for pending migrations
docker compose exec web python manage.py makemigrations --check --dry-run

# If migrations exist, plan to run them post-deploy
docker compose exec web python manage.py showmigrations
```

## Building and Pushing Images

### Web Container

```bash
# 1. Build with correct platform (GKE nodes are amd64)
docker build \
  --platform linux/amd64 \
  -f Dockerfile.prod \
  -t us-central1-docker.pkg.dev/wired-sound-479919-k8/codepathfinder/web:v<VERSION> \
  .

# 2. Push to registry
docker push us-central1-docker.pkg.dev/wired-sound-479919-k8/codepathfinder/web:v<VERSION>
```

**Version Naming Convention**:
- Semantic: `v1.6.0`, `v1.6.1` (preferred for releases)
- Descriptive: `v1.6.0-chat-fix` (for hotfixes)
- Never use: `latest` in production (ambiguous)

### Indexer Container

```bash
# CRITICAL: Always build with --platform linux/amd64
docker build \
  --platform linux/amd64 \
  -f indexer/Dockerfile \
  -t us-central1-docker.pkg.dev/wired-sound-479919-k8/codepathfinder/indexer:v<VERSION> \
  indexer/

docker push us-central1-docker.pkg.dev/wired-sound-479919-k8/codepathfinder/indexer:v<VERSION>
```

## Deployment Methods

### Method 1: Simple Image Update (Recommended for Code-Only Changes)

Use this when you're only updating the application code, not environment variables or resource limits.

```bash
# Deploy new image
kubectl set image deployment/codepathfinder \
  -n codepathfinder \
  web=us-central1-docker.pkg.dev/wired-sound-479919-k8/codepathfinder/web:v<VERSION>

# Watch rollout
kubectl rollout status deployment/codepathfinder -n codepathfinder --timeout=5m
```

### Method 2: Full Manifest Apply (For Config/Env Changes)

⚠️ **CRITICAL GOTCHA**: `kubectl apply -f deployment.yaml` will revert the image to whatever tag is hardcoded in the file!

```bash
# 1. FIRST update the image tag in deployment.yaml
sed -i '' 's|web:v.*|web:v<NEW_VERSION>|g' kubernetes/deployment.yaml

# 2. Review the diff
kubectl diff -f kubernetes/deployment.yaml

# 3. Apply changes
kubectl apply -f kubernetes/deployment.yaml

# 4. Watch rollout
kubectl rollout status deployment/codepathfinder -n codepathfinder --timeout=5m
```

**When to use Method 2**:
- Adding/removing environment variables
- Changing resource requests/limits
- Updating probe configurations
- Modifying volume mounts

### Using deploy.sh Script

The `scripts/deploy.sh` script automates building and image updates, but **does NOT apply env var changes**.

```bash
# Deploy specific version
./scripts/deploy.sh v1.6.1

# What it does:
# - Builds and pushes image
# - Updates deployment image
# - Checks rollout status
# - Reminds about migrations
```

## Post-Deployment Steps

### 1. Verify Pods are Healthy

```bash
# Check pod status
kubectl get pods -n codepathfinder -l app=codepathfinder

# Expected output:
# NAME                              READY   STATUS    RESTARTS   AGE
# codepathfinder-xxxxx-yyyyy        2/2     Running   0          2m
# codepathfinder-xxxxx-zzzzz        2/2     Running   0          2m

# Check logs for errors
kubectl logs -n codepathfinder -l app=codepathfinder -c web --tail=50 | grep -i error

# Test health endpoint
curl -s https://codepathfinder.com/health/
```

### 2. Run Database Migrations

⚠️ **CRITICAL**: Always run migrations manually after deployment.

```bash
# Get a web pod name
POD=$(kubectl get pods -n codepathfinder -l app=codepathfinder -o jsonpath='{.items[0].metadata.name}')

# Run migrations
kubectl exec $POD -n codepathfinder -c web -- python manage.py migrate

# Verify migration status
kubectl exec $POD -n codepathfinder -c web -- python manage.py showmigrations
```

### 3. Check Load Balancer Health

```bash
# Verify pods are registered with load balancer
kubectl get pods -n codepathfinder -l app=codepathfinder -o wide | grep "1/1"

# READINESS GATES should show 1/1 (not 0/1)
```

### 4. Monitor for Issues

```bash
# Watch events for warnings
kubectl get events -n codepathfinder --sort-by='.lastTimestamp' --field-selector type=Warning | tail -20

# Check recent logs
kubectl logs -n codepathfinder -l app=codepathfinder -c web --tail=100 --since=5m
```

## Rollback Procedures

### Quick Rollback

```bash
# Rollback to previous revision
kubectl rollout undo deployment/codepathfinder -n codepathfinder

# Watch rollback
kubectl rollout status deployment/codepathfinder -n codepathfinder
```

### Rollback to Specific Version

```bash
# 1. View deployment history
kubectl rollout history deployment/codepathfinder -n codepathfinder

# 2. Check specific revision
kubectl rollout history deployment/codepathfinder -n codepathfinder --revision=224

# 3. Rollback to that revision
kubectl rollout undo deployment/codepathfinder -n codepathfinder --to-revision=224
```

### Manual Image Revert

```bash
# Set to known good image
kubectl set image deployment/codepathfinder \
  -n codepathfinder \
  web=us-central1-docker.pkg.dev/wired-sound-479919-k8/codepathfinder/web:v1.5.4
```

## Common Issues and Solutions

### Issue: Pods CrashLooping with ImportError

**Symptoms**:
```
ImportError: cannot import name 'SomeModel' from 'app.models'
```

**Cause**: Code imports models/modules that don't exist (common after refactoring)

**Solution**:
1. Check the error in pod logs: `kubectl logs <pod> -n codepathfinder -c web --tail=200`
2. Verify imports in the problematic file
3. Build and deploy a fixed image
4. If urgent, rollback: `kubectl rollout undo deployment/codepathfinder -n codepathfinder`

### Issue: Pods Showing 1/2 Ready

**Symptoms**:
```
NAME                              READY   STATUS
codepathfinder-xxxxx-yyyyy        1/2     Running
```

**Cause**: Cloud SQL proxy sidecar or web container failing health checks

**Diagnosis**:
```bash
# Check which container is not ready
kubectl describe pod <pod-name> -n codepathfinder

# Check web container logs
kubectl logs <pod-name> -n codepathfinder -c web --tail=100

# Check cloud-sql-proxy logs
kubectl logs <pod-name> -n codepathfinder -c cloud-sql-proxy --tail=100
```

### Issue: 502 Bad Gateway from Load Balancer

**Possible Causes**:
1. All pods failing health checks
2. Pods not registered with NEG (Network Endpoint Group)
3. Deployment still rolling out

**Solutions**:
```bash
# Check pod readiness gates
kubectl get pods -n codepathfinder -l app=codepathfinder -o wide

# Check for unhealthy probes
kubectl get events -n codepathfinder --field-selector type=Warning | grep Unhealthy

# Wait for NEG registration (can take 1-2 minutes)
kubectl get pods -n codepathfinder -l app=codepathfinder -o jsonpath='{.items[*].status.conditions[?(@.type=="cloud.google.com/load-balancer-neg-ready")].status}'
```

### Issue: Insufficient CPU/Memory

**Symptoms**:
```
Events:
  Warning  FailedScheduling  pod/codepathfinder-xxxxx  0/3 nodes available: 3 Insufficient cpu
```

**Solution**:
```bash
# Check resource requests in deployment
kubectl get deployment codepathfinder -n codepathfinder -o jsonpath='{.spec.template.spec.containers[0].resources}'

# Either:
# 1. Reduce CPU requests in deployment.yaml (e.g., 250m -> 100m)
# 2. Wait for cluster autoscaler to add nodes
```

### Issue: Image Pull Errors

**Symptoms**:
```
Failed to pull image: UNAUTHENTICATED: failed to resolve token
```

**Cause**: Artifact Registry pull secret expired (OAuth token has 1-hour TTL)

**Solution**:
```bash
# Refresh the pull secret
kubectl create secret docker-registry artifact-registry-key \
  --docker-server=us-central1-docker.pkg.dev \
  --docker-username=oauth2accesstoken \
  --docker-password="$(gcloud auth print-access-token)" \
  -n codepathfinder \
  --dry-run=client -o yaml | kubectl apply -f -
```

## Critical Deployment Gotchas

### 1. Environment Variable Changes Don't Auto-Deploy

`kubectl set image` only updates the image, NOT env vars. You must use `kubectl apply -f deployment.yaml` for env changes.

### 2. Deployment.yaml Image Tag Must Match

When using `kubectl apply`, the image tag in `deployment.yaml` must be correct, or you'll accidentally rollback to an old version.

### 3. Code Mounted vs Baked In

- **Local dev**: Code is NOT volume-mounted; it's baked into the image
- **Production**: Code is always baked into the image
- **Impact**: Always rebuild after code changes: `docker compose up -d --build web`

### 4. Nginx IP Caching

After restarting any service that nginx proxies to (web, librechat), nginx caches the old container IP:

```bash
docker compose exec nginx nginx -s reload
```

### 5. Cloud SQL Proxy and Workload Identity

The `iam.gke.io/gcp-service-account` annotation MUST stay on `codepathfinder-ksa` ServiceAccount. Moving it breaks Cloud SQL access.

### 6. Indexer Job Permissions

Indexer jobs run under `indexer-sa` ServiceAccount (defined in `kubernetes/rbac.yaml`), but Cloud SQL access uses `codepathfinder-ksa` via Workload Identity.

## Monitoring Production

### Key Metrics to Watch

```bash
# Pod health
kubectl get pods -n codepathfinder -l app=codepathfinder

# Deployment status
kubectl get deployment codepathfinder -n codepathfinder

# Recent errors in logs
kubectl logs -n codepathfinder -l app=codepathfinder -c web --tail=500 --since=10m | grep ERROR

# Elasticsearch health (from a web pod)
kubectl exec <pod> -n codepathfinder -c web -- curl -s "$ELASTICSEARCH_ENDPOINT/_cluster/health"
```

### Health Endpoints

- Main app: https://codepathfinder.com/health/
- LibreChat: https://chat.codepathfinder.com/ (no /health endpoint)

## Emergency Contacts / Resources

- **GKE Console**: https://console.cloud.google.com/kubernetes/workload?project=wired-sound-479919-k8
- **Artifact Registry**: https://console.cloud.google.com/artifacts/docker/wired-sound-479919-k8/us-central1/codepathfinder
- **Cloud SQL**: https://console.cloud.google.com/sql/instances?project=wired-sound-479919-k8
- **Elasticsearch**: Elastic Cloud at platform-e9bd11.es.us-east-1.aws.elastic.cloud

## Version History

Update this section after each deployment:

| Date | Version | Changes | Deployed By |
|------|---------|---------|-------------|
| 2026-04-02 | v1.6.0-chat-fix | Removed PostgreSQL chat models, fixed ImportError | Claude |
| 2026-03-30 | v1.5.4 | Added embedded chat panel, Bedrock creds | - |
| 2026-03-30 | v1.5.3 | LibreChat config volume mount | - |

---

## Quick Reference Commands

```bash
# Get cluster credentials
gcloud container clusters get-credentials codepathfinder-cluster \
  --zone us-central1-a \
  --project wired-sound-479919-k8

# Build and deploy (full flow)
docker build --platform linux/amd64 -f Dockerfile.prod -t us-central1-docker.pkg.dev/wired-sound-479919-k8/codepathfinder/web:v1.x.x .
docker push us-central1-docker.pkg.dev/wired-sound-479919-k8/codepathfinder/web:v1.x.x
kubectl set image deployment/codepathfinder -n codepathfinder web=us-central1-docker.pkg.dev/wired-sound-479919-k8/codepathfinder/web:v1.x.x
kubectl rollout status deployment/codepathfinder -n codepathfinder

# Run migrations
POD=$(kubectl get pods -n codepathfinder -l app=codepathfinder -o jsonpath='{.items[0].metadata.name}')
kubectl exec $POD -n codepathfinder -c web -- python manage.py migrate

# Emergency rollback
kubectl rollout undo deployment/codepathfinder -n codepathfinder

# View logs
kubectl logs -n codepathfinder -l app=codepathfinder -c web --tail=100 -f
```
