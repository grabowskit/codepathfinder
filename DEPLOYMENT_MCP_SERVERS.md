# MCP Servers Production Deployment - 2026-04-03

## Deployment Summary

Successfully deployed Notion and Linear MCP servers to production GKE cluster.

### Deployed Components

#### 1. Notion MCP Server
- **Image**: `<YOUR_REGISTRY>/codepathfinder/notion-mcp:v1.0.0`
- **Replicas**: 2
- **Service**: `notion-mcp.codepathfinder.svc.cluster.local:3000`
- **Health Status**: ✅ Healthy
- **Package**: `@notionhq/notion-mcp-server` (official)

#### 2. Linear MCP Server
- **Image**: `<YOUR_REGISTRY>/codepathfinder/linear-mcp:v1.0.0`
- **Replicas**: 2
- **Service**: `linear-mcp.codepathfinder.svc.cluster.local:3000`
- **Health Status**: ✅ Healthy
- **Package**: `@tacticlaunch/mcp-linear`

#### 3. LibreChat Configuration
- **ConfigMap**: Updated with Notion and Linear MCP servers
- **Status**: ✅ Restarted and running
- **MCP Servers Available**: CodePathfinder, Notion, Linear

## Deployment Commands Used

```bash
# 1. Built Docker images with amd64 platform
docker build --platform linux/amd64 \
  -t <YOUR_REGISTRY>/codepathfinder/notion-mcp:v1.0.0 \
  -f mcp-servers/notion/Dockerfile mcp-servers/

docker build --platform linux/amd64 \
  -t <YOUR_REGISTRY>/codepathfinder/linear-mcp:v1.0.0 \
  -f mcp-servers/linear/Dockerfile mcp-servers/

# 2. Pushed images to Artifact Registry
docker push <YOUR_REGISTRY>/codepathfinder/notion-mcp:v1.0.0
docker push <YOUR_REGISTRY>/codepathfinder/linear-mcp:v1.0.0

# 3. Deployed to GKE
kubectl apply -f kubernetes/mcp-servers.yaml
kubectl apply -f kubernetes/librechat/librechat-configmap.yaml
kubectl rollout restart deployment librechat -n codepathfinder
```

## Resource Configuration

### Per MCP Server
- **CPU Request**: 100m
- **CPU Limit**: 500m
- **Memory Request**: 256Mi
- **Memory Limit**: 512Mi
- **Replicas**: 2 (for high availability)
- **Health Checks**: HTTP GET `/health` every 30s

## User Access Instructions

Users can now access Notion and Linear MCP tools through LibreChat at:
**https://<YOUR_DOMAIN>/chat** (via <YOUR_CHAT_DOMAIN>)

### Setting Up Notion

1. Create integration at https://www.notion.so/profile/integrations
2. Copy the Integration Token (starts with `ntn_`)
3. Connect pages to the integration via page settings
4. In LibreChat:
   - Select a Claude model
   - Find "Notion" in MCP servers list
   - Click settings icon
   - Paste token
   - Save

### Setting Up Linear

1. Go to Linear → Settings → API → Personal API Keys
2. Create new API key with appropriate scopes
3. Copy the key (starts with `lin_api_`)
4. In LibreChat:
   - Select a Claude model
   - Find "Linear" in MCP servers list
   - Click settings icon
   - Paste API key
   - Save

## Architecture

```
┌─────────────────────────────────────────┐
│         LibreChat (chat.codepathfinder)  │
│         (with user's API tokens)         │
└──────────┬──────────────┬───────────────┘
           │              │
     Token │        Token │
           ▼              ▼
    ┌──────────┐   ┌──────────┐
    │ notion-  │   │ linear-  │
    │ mcp      │   │ mcp      │
    │ (2 pods) │   │ (2 pods) │
    └────┬─────┘   └────┬─────┘
         │              │
   Token │        Token │
         ▼              ▼
  ┌──────────┐   ┌──────────┐
  │ Notion   │   │ Linear   │
  │ API      │   │ API      │
  └──────────┘   └──────────┘
```

## Security Model

### Per-User Isolation
- ✅ Each user provides their own API credentials
- ✅ Tokens encrypted in LibreChat's MongoDB
- ✅ No token sharing between users
- ✅ MCP servers are stateless (no token storage)

### Network Security
- ✅ MCP servers use ClusterIP (not exposed externally)
- ✅ Only accessible from within the cluster
- ✅ Traffic between LibreChat and MCP servers stays internal

## Monitoring & Troubleshooting

### Check Deployment Status
```bash
kubectl get deployments -n codepathfinder | grep mcp
kubectl get pods -n codepathfinder | grep mcp
kubectl get services -n codepathfinder | grep mcp
```

### Check Logs
```bash
# Notion MCP logs
kubectl logs -n codepathfinder deployment/notion-mcp --tail=50

# Linear MCP logs
kubectl logs -n codepathfinder deployment/linear-mcp --tail=50

# LibreChat logs (check for MCP connection issues)
kubectl logs -n codepathfinder deployment/librechat --tail=100 | grep -i mcp
```

### Health Checks
```bash
# Test from within cluster
kubectl run test-curl --rm -i --restart=Never \
  --image=curlimages/curl:latest -n codepathfinder \
  -- curl -s http://notion-mcp:3000/health

kubectl run test-curl --rm -i --restart=Never \
  --image=curlimages/curl:latest -n codepathfinder \
  -- curl -s http://linear-mcp:3000/health
```

Expected response: `{"status":"ok","mcp_command":"npx"}`

### Common Issues

#### MCP Server Pod Crashes
```bash
# Check pod events
kubectl describe pod -n codepathfinder -l app=notion-mcp

# Check resource usage
kubectl top pods -n codepathfinder | grep mcp
```

**Solution**: If CPU/memory limits are too low, increase in `kubernetes/mcp-servers.yaml`

#### User Authentication Failures
**Symptoms**: User gets "Authentication failed" in LibreChat

**Common Causes**:
- Notion: Token valid but pages not connected to integration
- Linear: Token doesn't have required scopes
- Token copied incorrectly (extra spaces)

**Solution**: Have user re-create token and ensure proper setup

#### Connection Timeout
**Symptoms**: LibreChat shows "Server not responding"

```bash
# Check if services are healthy
kubectl get endpoints -n codepathfinder | grep mcp

# Verify pods are ready
kubectl get pods -n codepathfinder | grep mcp
```

**Solution**: Restart MCP deployments if needed:
```bash
kubectl rollout restart deployment notion-mcp -n codepathfinder
kubectl rollout restart deployment linear-mcp -n codepathfinder
```

## Future Updates

### To Deploy New Version

1. **Build new image**:
   ```bash
   docker build --platform linux/amd64 \
     -t <YOUR_REGISTRY>/codepathfinder/notion-mcp:v1.0.1 \
     -f mcp-servers/notion/Dockerfile mcp-servers/
   docker push <YOUR_REGISTRY>/codepathfinder/notion-mcp:v1.0.1
   ```

2. **Update deployment**:
   ```bash
   kubectl set image deployment/notion-mcp \
     notion-mcp=<YOUR_REGISTRY>/codepathfinder/notion-mcp:v1.0.1 \
     -n codepathfinder
   ```

3. **Monitor rollout**:
   ```bash
   kubectl rollout status deployment/notion-mcp -n codepathfinder
   ```

### To Add New MCP Server

1. Create Dockerfile in `mcp-servers/<server-name>/Dockerfile`
2. Build and push image
3. Add deployment and service to `kubernetes/mcp-servers.yaml`
4. Add server config to `kubernetes/librechat/librechat-configmap.yaml`
5. Apply manifests and restart LibreChat

## Files Modified

- ✅ `kubernetes/mcp-servers.yaml` (new)
- ✅ `kubernetes/librechat/librechat-configmap.yaml` (updated)
- ✅ `mcp-servers/notion/Dockerfile`
- ✅ `mcp-servers/linear/Dockerfile`
- ✅ `mcp-servers/http-wrapper/server.js`
- ✅ `mcp-servers/http-wrapper/package.json`

## Verification

All services verified healthy on 2026-04-03:

```
NAME             READY   UP-TO-DATE   AVAILABLE
codepathfinder   2/2     2            2
librechat        1/1     1            1
linear-mcp       2/2     2            2
notion-mcp       2/2     2            2
```

Health checks passing:
- ✅ Notion MCP: `{"status":"ok","mcp_command":"npx"}`
- ✅ Linear MCP: `{"status":"ok","mcp_command":"npx"}`

## Next Steps

1. **Test with real tokens**: Create test Notion integration and Linear API key
2. **Verify user flow**: Complete end-to-end test as a user
3. **Monitor usage**: Watch logs for any authentication or connection issues
4. **Update documentation**: Share setup instructions with users
5. **Consider alerts**: Set up monitoring alerts for MCP server health

---

**Deployment completed successfully at 2026-04-03**
