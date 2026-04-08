# CodePathfinder Changelog

All notable changes to this project will be documented in this file.

## [v1.8.0] - 2026-04-07

### Added
- **Telemetry Endpoint**: Public endpoint `/telemetry/event` for OSS usage analytics
  - Supports install, startup, and feature_counts event types
  - Anonymous data collection (installation_id only, no PII)
  - Rate limiting: 100 events per installation per hour
  - Stores data in Elasticsearch `oss-telemetry-{YYYY.MM}` indices
  - Opt-out via `TELEMETRY_ENABLED=false`

- **Bidirectional Personal Skills Sync**: Users can now push local skills to GitHub
  - "Sync My Skills" button now performs bidirectional sync (pull AND push)
  - Automatically pushes database skills to user's GitHub repo
  - Smart timestamp comparison prevents overwriting newer versions
  - Updates `github_path` and `last_synced` fields after successful push

### Fixed
- **MCP `skills_import` Scope Assignment**: Fixed bug where imported skills defaulted to `global` scope for all users
  - Superusers → `global` scope (visible to all)
  - Regular users → `personal` scope (visible only to creator)
  - Prevents cross-contamination of personal and global skills

- **GitHub Token Form Field**: Fixed token updates not saving in database
  - Changed from `PasswordInput` to `TextInput` with `type='password'`
  - Shows masked placeholder instead of pre-filling existing token
  - Resolves browser compatibility issues with password field submission

### Changed
- **Skills Service**: Enhanced `sync_user_skills()` to support push operations
  - Returns dict with `{'pulled': [...], 'pushed': [...], 'errors': [...]}`
  - Phase 1: Pull skills from GitHub to database
  - Phase 2: Push database skills to GitHub

- **UI Improvements**: Updated "Sync My Skills" button tooltip to clarify bidirectional sync


## [v1.7.3] - 2026-04-07

### Fixed
- GitHub token form field not saving updates due to PasswordInput browser issues
- Changed to TextInput with type='password' attribute
- Shows masked placeholder instead of pre-filling value

## [v1.7.2] - 2026-04-07

### Added
- Bidirectional personal skills sync (initial implementation)
- Users can now push locally-created skills to their GitHub repository

## [v1.7.1] - 2026-04-07

### Fixed
- Cloud SQL proxy configuration using actual instance name

## [v1.7.0] - 2026-04-07

### Added
- Usage tracking and UI enhancements
- Skills management improvements

## [v1.6.1-skills-fix] - 2026-04-07

### Fixed
- `skills_import` circular reference bug ("cannot access local variable 'created'")
- Used existing variable instead of created flag in defaults dict

## [v1.6.0-chat-fix] - 2026-04-02

### Fixed
- Removed PostgreSQL chat models to resolve ImportError crashes
- Fixed chat history storage issues

## [v1.5.4] - 2026-03-30

### Added
- Embedded chat side panel in base template
- AWS Bedrock credentials support

## [v1.5.3] - 2026-03-30

### Added
- LibreChat config volume mount
- Shared LLM configuration via librechat.yaml

---

## Version Naming Convention

- **Semantic versions** (v1.x.x): Major feature releases
- **Descriptive versions** (v1.x.x-feature-name): Hotfixes and targeted updates
- **Never use `latest`** in production deployments

## Contributing

See the README for setup and deployment procedures.
