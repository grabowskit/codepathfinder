# Publishing the MCP Bridge to npm

## Overview

To enable users to run `npx @codepathfinder/mcp-bridge`, the package needs to be published to npm. This document outlines the steps.

## Prerequisites

- npm account (create at [npmjs.com](https://npmjs.com))
- npm organization `@codepathfinder` (or use a different scope)
- Access to publish packages under the org

## One-Time Setup

### 1. Create npm Account & Organization

**Create account:**
```bash
npm adduser
```

**Create organization:**
Organizations must be created via the npm website, not the CLI.

1. Go to [npmjs.com/org/create](https://www.npmjs.com/org/create)
2. Sign in with your npm account
3. Click "Create an Organization"
4. Enter organization name: `codepathfinder`
5. Choose plan: **Free** (for open source packages)
6. Complete creation

Alternatively, you can publish without an organization using your personal scope:
- Package name: `@grabowskit/mcp-bridge` (using your username)
- Or use unscoped: `codepathfinder-mcp-bridge`

### 2. Update package.json

The package is already configured correctly:
- Name: `@codepathfinder/mcp-bridge`
- Version: `1.0.0`
- Main: `build/index.js`
- Bin: `codepathfinder-mcp` → `build/index.js`

### 3. Verify Package Contents

```bash
cd mcp-bridge
npm run build
npm pack --dry-run
```

This shows what will be included in the package.

## Publishing Process

### Step 1: Build

```bash
cd mcp-bridge
npm install
npm run build
```

### Step 2: Test Locally

```bash
# Test the built package
node build/index.js

# Should show: Error: CODEPATHFINDER_API_KEY environment variable is required
```

### Step 3: Publish

```bash
# Login to npm
npm login

# Publish (first time)
npm publish --access public

# For updates
npm version patch  # or minor, or major
npm publish
```

### Step 4: Verify

```bash
# Test installation via npx
npx -y @codepathfinder/mcp-bridge

# Should error with: CODEPATHFINDER_API_KEY environment variable is required
```

## Publishing Updates

When you make changes:

```bash
# 1. Make your code changes
# 2. Build
npm run build

# 3. Test locally
node build/index.js

# 4. Bump version
npm version patch   # 1.0.0 → 1.0.1
# or
npm version minor   # 1.0.0 → 1.1.0
# or
npm version major   # 1.0.0 → 2.0.0

# 5. Publish
npm publish

# 6. Update documentation with new version
```

## Alternative: GitHub Package Registry

If you prefer GitHub over npm:

### 1. Update package.json

```json
{
  "name": "@yourorg/mcp-bridge",
  "repository": {
    "type": "git",
    "url": "https://github.com/yourorg/pathfinder"
  },
  "publishConfig": {
    "registry": "https://npm.pkg.github.com"
  }
}
```

### 2. Create GitHub Token

1. Go to GitHub Settings → Developer Settings → Personal Access Tokens
2. Create token with `write:packages` scope
3. Login: `npm login --registry=https://npm.pkg.github.com`

### 3. Publish

```bash
npm publish
```

### 4. Update User Instructions

Users need to configure npm to use GitHub registry:

```bash
echo "@yourorg:registry=https://npm.pkg.github.com" >> ~/.npmrc
```

## Package Maintenance

### Versioning Strategy

- **Patch** (1.0.x): Bug fixes, documentation
- **Minor** (1.x.0): New features, backward compatible
- **Major** (x.0.0): Breaking changes

### Changelog

Maintain `CHANGELOG.md`:

```markdown
# Changelog

## [1.0.1] - 2025-01-15
### Fixed
- Fixed error handling for network timeouts

## [1.0.0] - 2025-01-01
### Added
- Initial release with 6 MCP tools
```

### npm Scripts

Useful scripts to add to `package.json`:

```json
{
  "scripts": {
    "prepublishOnly": "npm run build && npm test",
    "postpublish": "git push && git push --tags"
  }
}
```

## Without Publishing: Local Distribution

If you don't want to publish to npm yet, users can still use it locally:

### Option 1: Git Install

```json
{
  "mcpServers": {
    "codepathfinder": {
      "command": "npx",
      "args": ["-y", "github:yourorg/pathfinder#main:mcp-bridge"],
      "env": {
        "CODEPATHFINDER_API_KEY": "...",
        "CODEPATHFINDER_API_ENDPOINT": "https://codepathfinder.com/api/v1/mcp/tools/call/"
      }
    }
  }
}
```

### Option 2: Local Path

```json
{
  "mcpServers": {
    "codepathfinder": {
      "command": "node",
      "args": ["/absolute/path/to/pathfinder/mcp-bridge/build/index.js"],
      "env": {
        "CODEPATHFINDER_API_KEY": "...",
        "CODEPATHFINDER_API_ENDPOINT": "https://codepathfinder.com/api/v1/mcp/tools/call/"
      }
    }
  }
}
```

## Recommended Approach

**For production use**: Publish to npm  
**For testing**: Use local paths or GitHub URLs

## Security Considerations

- **Never commit API keys** to the repository
- **Use .npmignore** to exclude sensitive files
- **Review published contents** with `npm pack --dry-run` before publishing
- **Enable 2FA** on npm account

## Support After Publishing

Users will find your package at:
- **npm**: [npmjs.com/package/@codepathfinder/mcp-bridge](https://npmjs.com/package/@codepathfinder/mcp-bridge)
- **Documentation**: `README.md` included in package
- **Issues**: GitHub repository issues

## Current Status

**Not yet published** - The package exists locally but hasn't been published to npm.

To use it now, users must:
1. Clone the repository
2. Build locally: `cd mcp-bridge && npm install && npm run build`
3. Point Claude Desktop to local build path

Once published to npm, users can simply use:
```bash
npx -y @codepathfinder/mcp-bridge
```
