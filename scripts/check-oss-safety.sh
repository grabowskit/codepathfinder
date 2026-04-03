#!/bin/bash

# Script to verify that private MCP configurations won't leak into OSS repo

set -e

echo "🔍 Checking OSS Safety - Verifying private configs are gitignored..."
echo

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

errors=0

# Check 1: Verify .gitignore rules are present
echo "✓ Checking .gitignore rules..."
if grep -q "chat-config/librechat.yaml" .gitignore && \
   grep -q "kubernetes/librechat/librechat-configmap.private.yaml" .gitignore && \
   grep -q "kubernetes/mcp-servers.yaml" .gitignore && \
   grep -q "mcp-servers/" .gitignore; then
    echo -e "${GREEN}  ✓ All required .gitignore rules are present${NC}"
else
    echo -e "${RED}  ✗ Missing .gitignore rules!${NC}"
    errors=$((errors + 1))
fi
echo

# Check 2: Verify private files are not tracked
echo "✓ Checking if private files are tracked by git..."
private_files=$(git ls-files | grep -E "librechat\.yaml$|librechat\.local|configmap\.private|mcp-servers\.yaml|^mcp-servers/" || true)
if [ -z "$private_files" ]; then
    echo -e "${GREEN}  ✓ No private files are tracked${NC}"
else
    echo -e "${RED}  ✗ Found tracked private files:${NC}"
    echo "$private_files"
    errors=$((errors + 1))
fi
echo

# Check 3: Check for Notion/Linear references in tracked files
echo "✓ Checking for Notion/Linear MCP references in tracked files..."
notion_linear_refs=$(git ls-files | grep -v "\.md$" | xargs grep -l "notion-mcp\|linear-mcp" 2>/dev/null || true)
if [ -z "$notion_linear_refs" ]; then
    echo -e "${GREEN}  ✓ No Notion/Linear MCP references in tracked files${NC}"
else
    echo -e "${YELLOW}  ⚠ Found Notion/Linear references in tracked files:${NC}"
    echo "$notion_linear_refs"
    echo -e "${YELLOW}  (This is OK if they're in documentation or examples)${NC}"
fi
echo

# Check 4: Check for sensitive tokens
echo "✓ Checking for sensitive tokens in tracked files..."
tokens=$(git ls-files | grep -v "\.md$" | grep -v "\.sh$" | xargs grep -E "ntn_[a-zA-Z0-9]{40}|lin_api_[a-zA-Z0-9]{40}" 2>/dev/null || true)
if [ -z "$tokens" ]; then
    echo -e "${GREEN}  ✓ No sensitive tokens found${NC}"
else
    echo -e "${RED}  ✗ Found potential sensitive tokens:${NC}"
    echo "$tokens"
    errors=$((errors + 1))
fi
echo

# Check 5: Verify base configs exist and are tracked
echo "✓ Checking if base configs are tracked..."
if git ls-files | grep -q "chat-config/librechat.base.yaml" && \
   git ls-files | grep -q "kubernetes/librechat/librechat-configmap.base.yaml"; then
    echo -e "${GREEN}  ✓ Base configurations are tracked${NC}"
else
    echo -e "${RED}  ✗ Missing base configuration files!${NC}"
    errors=$((errors + 1))
fi
echo

# Check 6: List what would be committed
echo "✓ Files that would be committed (staged changes)..."
staged=$(git diff --name-only --cached || true)
if [ -z "$staged" ]; then
    echo -e "${GREEN}  (No staged changes)${NC}"
else
    echo "$staged"
    # Check if any staged files are private
    private_staged=$(echo "$staged" | grep -E "librechat\.yaml$|librechat\.local|configmap\.private|mcp-servers\.yaml|^mcp-servers/" || true)
    if [ -n "$private_staged" ]; then
        echo -e "${RED}  ✗ DANGER: Private files are staged!${NC}"
        echo "$private_staged"
        errors=$((errors + 1))
    fi
fi
echo

# Check 7: Show ignored files that exist
echo "✓ Private files that exist but are ignored..."
ignored_files=""
[ -f "chat-config/librechat.yaml" ] && ignored_files="${ignored_files}\n  chat-config/librechat.yaml"
[ -f "chat-config/librechat.local.yaml" ] && ignored_files="${ignored_files}\n  chat-config/librechat.local.yaml"
[ -f "kubernetes/librechat/librechat-configmap.private.yaml" ] && ignored_files="${ignored_files}\n  kubernetes/librechat/librechat-configmap.private.yaml"
[ -f "kubernetes/mcp-servers.yaml" ] && ignored_files="${ignored_files}\n  kubernetes/mcp-servers.yaml"
[ -d "mcp-servers" ] && ignored_files="${ignored_files}\n  mcp-servers/"

if [ -n "$ignored_files" ]; then
    echo -e "${GREEN}  ✓ These private files exist and are properly ignored:${NC}"
    echo -e "$ignored_files"
else
    echo -e "${YELLOW}  ⚠ No private files found (you may be using base configs only)${NC}"
fi
echo

# Final result
echo "================================================"
if [ $errors -eq 0 ]; then
    echo -e "${GREEN}✅ OSS Safety Check PASSED${NC}"
    echo "Safe to push to OSS repository!"
else
    echo -e "${RED}❌ OSS Safety Check FAILED with $errors error(s)${NC}"
    echo "DO NOT push to OSS repository until issues are resolved!"
    exit 1
fi
echo "================================================"
