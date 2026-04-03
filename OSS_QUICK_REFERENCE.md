# OSS Configuration - Quick Reference

## ✅ What's Now Safe for OSS

Your repository is now configured to **separate base (OSS) configs from private (Notion/Linear) configs**.

## File Status

### ✅ Committed to OSS (Safe)
```
chat-config/
├── librechat.base.yaml          # Base config (CodePathfinder MCP only)
└── README.md                    # Setup instructions

kubernetes/librechat/
├── librechat-configmap.base.yaml  # Production base config
└── librechat-configmap.yaml       # Production base config (copy)

OSS_CONFIGURATION.md             # Configuration strategy docs
OSS_QUICK_REFERENCE.md           # This file
scripts/check-oss-safety.sh      # Safety check script
```

### ❌ NOT Committed (Private)
```
chat-config/
├── librechat.yaml               # Your working config (Notion/Linear)
└── librechat.local.yaml         # Alternative working config

kubernetes/librechat/
└── librechat-configmap.private.yaml  # Production with Notion/Linear

kubernetes/mcp-servers.yaml      # MCP server deployments

mcp-servers/                     # MCP server Docker images
├── notion/
├── linear/
└── http-wrapper/
```

## Quick Commands

### Before Pushing to OSS
```bash
# Run safety check
./scripts/check-oss-safety.sh

# If passed, safe to push
git push origin main
```

### Local Development
```bash
# Currently uses: chat-config/librechat.yaml (private, with Notion/Linear)
docker compose up -d

# To test OSS-only setup:
cp chat-config/librechat.base.yaml chat-config/librechat.yaml
docker compose restart librechat
```

### Production Deployment

**Current (Private with Notion/Linear):**
```bash
kubectl apply -f kubernetes/mcp-servers.yaml
kubectl apply -f kubernetes/librechat/librechat-configmap.private.yaml
kubectl rollout restart deployment librechat -n codepathfinder
```

**OSS-only (CodePathfinder MCP only):**
```bash
kubectl apply -f kubernetes/librechat/librechat-configmap.yaml
kubectl rollout restart deployment librechat -n codepathfinder
```

## What OSS Users See

When someone clones the public repo, they get:

1. **Base LibreChat config** (`librechat.base.yaml`)
   - Only CodePathfinder MCP server
   - Example LLM provider configuration (AWS Bedrock with Claude)
   - Clean, production-ready setup

2. **Setup instructions** (`chat-config/README.md`)
   - How to create `librechat.yaml` from base
   - How to configure any LLM provider (OpenAI, Anthropic, Google, AWS Bedrock, Azure, etc.)
   - Optional: how to add their own MCP servers

3. **No private infrastructure**
   - No Notion MCP references
   - No Linear MCP references
   - No MCP server Docker images

## Configuration Comparison

### OSS Version (Public)
```yaml
mcpServers:
  codepathfinder:
    url: "http://web:8000/mcp/"
    # Only CodePathfinder

modelSpecs:
  list:
    - mcpServers: ["codepathfinder"]
```

### Your Private Version
```yaml
mcpServers:
  codepathfinder:
    url: "http://web:8000/mcp/"
  notion:
    url: "http://notion-mcp:3000/mcp"
    customUserVars: { NOTION_TOKEN: ... }
  linear:
    url: "http://linear-mcp:3000/mcp"
    customUserVars: { LINEAR_API_TOKEN: ... }

modelSpecs:
  list:
    - mcpServers: ["codepathfinder", "notion", "linear"]
```

## Troubleshooting

### "librechat.yaml not found" (OSS users)
Expected! They need to:
```bash
cp chat-config/librechat.base.yaml chat-config/librechat.yaml
```

### Safety check fails
Don't push! Fix issues first:
```bash
./scripts/check-oss-safety.sh
# Read the output and fix errors
```

### Private config accidentally staged
```bash
git reset HEAD chat-config/librechat.yaml
git reset HEAD kubernetes/librechat/librechat-configmap.private.yaml
git reset HEAD kubernetes/mcp-servers.yaml
```

## Summary

✅ **You're safe to push!**

Your private Notion/Linear MCP configurations are now properly gitignored and won't leak into the OSS repository. OSS users will only see the base CodePathfinder MCP setup.

---

Run `./scripts/check-oss-safety.sh` before every push to verify safety.
