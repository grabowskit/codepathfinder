# OSS vs Private Configuration Management

This document explains how to maintain separate configurations for the OSS CodePathfinder repository versus your private deployment with additional MCP servers.

## Problem

Your private deployment includes Notion and Linear MCP servers that you don't want to expose in the public OSS repository. Users should only see the CodePathfinder MCP configuration.

## Solution

We maintain **base configurations** (OSS) and **extended configurations** (private) with `.gitignore` rules to prevent private configs from being committed.

## File Structure

### Local Development

```
chat-config/
├── librechat.base.yaml          ✅ Committed (OSS - CodePathfinder MCP only)
├── librechat.yaml               ❌ NOT committed (Private - includes Notion/Linear)
├── librechat.local.yaml         ❌ NOT committed (Backup/alternative)
├── .env                         ❌ NOT committed (secrets)
└── README.md                    ✅ Committed (documentation)
```

### Production (Kubernetes)

```
kubernetes/librechat/
├── librechat-configmap.base.yaml      ✅ Committed (OSS - CodePathfinder only)
├── librechat-configmap.yaml           ✅ Committed (Symlink/copy of base)
├── librechat-configmap.private.yaml   ❌ NOT committed (Private - with Notion/Linear)
└── librechat-secrets.yaml             ❌ NOT committed (secrets)
```

### MCP Servers

```
mcp-servers/                     ❌ NOT committed (private infrastructure)
├── notion/
│   └── Dockerfile
├── linear/
│   └── Dockerfile
└── http-wrapper/
    ├── package.json
    └── server.js

kubernetes/mcp-servers.yaml      ❌ NOT committed (private infrastructure)
```

## Workflow

### Working in Private Repo (pathfinder-prototype)

This is your current repo where you can work freely with all MCP servers.

1. **Local Development**:
   - Use `chat-config/librechat.yaml` (includes all MCP servers)
   - Start all services including Notion/Linear MCP: `docker compose up -d`

2. **Production Deployment**:
   - Use `kubernetes/librechat/librechat-configmap.private.yaml`
   - Deploy MCP servers: `kubectl apply -f kubernetes/mcp-servers.yaml`
   - Deploy config: `kubectl apply -f kubernetes/librechat/librechat-configmap.private.yaml`

### Preparing for OSS Release (codepathfinder)

When you want to push to the public OSS repo:

1. **Verify .gitignore is working**:
   ```bash
   git status
   # Should NOT show:
   # - chat-config/librechat.yaml
   # - chat-config/librechat.local.yaml
   # - kubernetes/librechat/librechat-configmap.private.yaml
   # - kubernetes/mcp-servers.yaml
   # - mcp-servers/
   ```

2. **Check base configs are included**:
   ```bash
   git status
   # Should show (if modified):
   # - chat-config/librechat.base.yaml
   # - kubernetes/librechat/librechat-configmap.yaml (or .base.yaml)
   ```

3. **Commit and push safely**:
   ```bash
   git add .
   git commit -m "Update configurations"
   git push origin main
   ```

## .gitignore Rules

The following rules prevent private configurations from being committed:

```gitignore
# Private LibreChat configs (with Notion/Linear MCP - not for OSS)
chat-config/librechat.yaml
chat-config/librechat.local.yaml
kubernetes/librechat/librechat-configmap.private.yaml
kubernetes/mcp-servers.yaml

# Private MCP servers (not for OSS)
mcp-servers/

# Chat config secrets
chat-config/.env
```

## Configuration Comparison

### Base Configuration (OSS)

**chat-config/librechat.base.yaml**:
```yaml
mcpServers:
  codepathfinder:
    type: streamable-http
    url: "http://web:8000/mcp/"
    title: "CodePathfinder"
    # ... CodePathfinder MCP only

modelSpecs:
  list:
    - name: "bedrock-claude-sonnet-4-6"
      mcpServers:
        - "codepathfinder"  # Only CodePathfinder
```

### Extended Configuration (Private)

**chat-config/librechat.yaml**:
```yaml
mcpServers:
  codepathfinder:
    # ... CodePathfinder MCP
  notion:
    # ... Notion MCP with customUserVars
  linear:
    # ... Linear MCP with customUserVars

modelSpecs:
  list:
    - name: "bedrock-claude-sonnet-4-6"
      mcpServers:
        - "codepathfinder"
        - "notion"
        - "linear"
```

## Docker Compose Setup

**Current behavior**:
- `docker-compose.yml` references `chat-config/librechat.yaml`
- This file is `.gitignore`d, so it won't be in the OSS repo
- OSS users need to create it from `librechat.base.yaml`

**For OSS users** (when they clone the repo):
```bash
# They'll need to do this once:
cp chat-config/librechat.base.yaml chat-config/librechat.yaml
docker compose up -d
```

## Kubernetes Setup

### Base Deployment (OSS)

```bash
# OSS users deploy only CodePathfinder MCP
kubectl apply -f kubernetes/librechat/librechat-configmap.yaml
kubectl apply -f kubernetes/deployment.yaml
```

### Extended Deployment (Private)

```bash
# You deploy with Notion/Linear MCP
kubectl apply -f kubernetes/mcp-servers.yaml
kubectl apply -f kubernetes/librechat/librechat-configmap.private.yaml
kubectl rollout restart deployment librechat -n codepathfinder
```

## Switching Between Configurations

### Local Dev: Switch to Base (OSS-only)

```bash
# Use base config temporarily
docker compose down
cp chat-config/librechat.base.yaml chat-config/librechat.yaml
docker compose up -d

# Verify only CodePathfinder MCP is available
docker compose exec librechat cat /app/librechat.yaml | grep -A2 "mcpServers:"
```

### Local Dev: Switch to Extended (Private)

```bash
# Restore full config with Notion/Linear
docker compose down
cp chat-config/librechat.local.yaml chat-config/librechat.yaml
docker compose up -d notion-mcp linear-mcp
docker compose up -d
```

### Production: Switch to Base (OSS-only)

```bash
kubectl apply -f kubernetes/librechat/librechat-configmap.yaml
kubectl rollout restart deployment librechat -n codepathfinder
```

### Production: Switch to Extended (Private)

```bash
kubectl apply -f kubernetes/mcp-servers.yaml
kubectl apply -f kubernetes/librechat/librechat-configmap.private.yaml
kubectl rollout restart deployment librechat -n codepathfinder
```

## Maintaining Two Repos

If you maintain both `pathfinder-prototype` (private) and `codepathfinder` (public):

### pathfinder-prototype (Private)
- Contains ALL files including private MCP configs
- No restrictions on what you commit
- Full Notion/Linear MCP setup

### codepathfinder (Public/OSS)
- Only push files that pass .gitignore
- Contains only base configurations
- Only CodePathfinder MCP

### Sync Process

```bash
# In pathfinder-prototype (private)
git add .
git commit -m "Add feature X"
git push origin main

# Check what would go to OSS
git status --ignored | grep "chat-config\|kubernetes/librechat\|mcp-servers"

# Copy to OSS repo (manual or script)
cd ../codepathfinder
cp -r ../pathfinder-prototype/web ./
cp -r ../pathfinder-prototype/indexer ./
# etc... (but NOT private configs - .gitignore will prevent them)

# Verify private files are NOT staged
git status
# Should NOT show Notion/Linear configs

# Commit to OSS
git add .
git commit -m "Add feature X"
git push origin main
```

## Safety Checks

Before pushing to OSS repo, run these checks:

```bash
# Check for private MCP references
grep -r "notion-mcp\|linear-mcp" --exclude-dir=.git --exclude="*.md"
# Should only appear in .gitignore'd files

# Check for sensitive tokens/keys
grep -r "ntn_\|lin_api_" --exclude-dir=.git
# Should be empty

# Verify .gitignore is working
git ls-files | grep -E "librechat\.yaml$|librechat\.local|configmap\.private|mcp-servers\.yaml"
# Should be empty

# Check what would be committed
git status --ignored
```

## Documentation for OSS Users

OSS users will see:
- `chat-config/librechat.base.yaml` - Base config to copy
- `chat-config/README.md` - Setup instructions
- Instructions to create their own `librechat.yaml` from base

They can optionally add their own MCP servers by:
1. Copying `librechat.base.yaml` to `librechat.yaml`
2. Adding their own MCP server configurations
3. Deploying their own MCP containers

## Summary

| File | Private Repo | OSS Repo | Purpose |
|------|-------------|----------|---------|
| `chat-config/librechat.base.yaml` | ✅ | ✅ | Template (CodePathfinder only) |
| `chat-config/librechat.yaml` | ✅ | ❌ | Working config (with Notion/Linear) |
| `chat-config/librechat.local.yaml` | ✅ | ❌ | Backup/alternative |
| `kubernetes/librechat/librechat-configmap.base.yaml` | ✅ | ✅ | Production template |
| `kubernetes/librechat/librechat-configmap.yaml` | ✅ | ✅ | Production base (symlink/copy) |
| `kubernetes/librechat/librechat-configmap.private.yaml` | ✅ | ❌ | Production with Notion/Linear |
| `kubernetes/mcp-servers.yaml` | ✅ | ❌ | MCP server deployments |
| `mcp-servers/` | ✅ | ❌ | MCP server Docker images |

---

**Result**: You can work freely in your private repo with all MCP servers, and when pushing to OSS, only the base configurations are included. OSS users get a clean CodePathfinder MCP setup without seeing your private Notion/Linear integrations.
