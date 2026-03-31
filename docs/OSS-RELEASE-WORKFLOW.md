# OSS Release Workflow

This document explains how to move new commits from the `main` (staging) branch
into the `oss-release` branch and sync them to the public GitHub repo at
`https://github.com/grabowskit/codepathfinder`.

---

## Branch Model

| Branch | Purpose |
|--------|---------|
| `main` | Active development + GCP staging. Contains production-specific values. |
| `oss-release` | Public OSS release. All production refs replaced with placeholders. |

The `oss-release` branch was forked from `main` at `a540d2c`, so all commits
up to and including that point (e.g. the OTel pipeline in `d870111` and
`a540d2c`) are shared history. The cleanup commits on `oss-release` then
sanitized production-specific values.

New work on `main` after the fork point must be **cherry-picked** onto
`oss-release`, not merged, so we can sanitize each commit individually.

The public repo at `/tmp/codepathfinder-public` is updated by re-archiving the
`oss-release` branch and pushing. It has **no git history** from `main`.

---

## General Process

```bash
# 1. Identify the commit(s) to port
git log --oneline main

# 2. Switch to oss-release
git checkout oss-release

# 3. Cherry-pick the commit
git cherry-pick <hash>

# 4. Scan the cherry-picked diff for production-specific values (see checklist)
git diff HEAD~1

# 5. Fix anything that needs sanitizing, then amend or add a fixup commit

# 6. Sync to the public repo (see bottom of this doc)
```

---

## Sanitization Checklist

After cherry-picking, grep for the following patterns and replace with the
`<YOUR_*>` placeholder equivalents:

| Pattern | Replace with |
|---------|-------------|
| `wired-sound-479919-k8` | `<YOUR_GCP_PROJECT>` |
| `us-central1-docker.pkg.dev/wired-sound-479919-k8/` | `<YOUR_REGISTRY>/` |
| `us-central1` (as a region) | `<YOUR_REGION>` |
| `codepathfinder-db` | `<YOUR_CLOUD_SQL_INSTANCE>` |
| `34.54.144.82` | `<YOUR_STATIC_IP>` |
| `codepathfinder.com` (domain refs in K8s/config) | `<YOUR_DOMAIN>` |
| `grabowskit.tplinkdns.com` | remove or replace |
| `grabowski.org` / `tom@…` email addresses | remove or replace |
| Any real API keys, tokens, or passwords | remove |
| `/Users/grabowskit/…` local paths | replace with generic paths |

**Files most likely to need sanitization:**

- `kubernetes/deployment.yaml` — image tag and Cloud SQL instance name
- `kubernetes/cronjob-status-checker.yaml` — image tag and Cloud SQL instance
- `web/CodePathfinder/settings.py` — `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`,
  `SESSION_COOKIE_DOMAIN`, `DEFAULT_FROM_EMAIL`

### OSS Telemetry split (two-commit rule)

The OSS telemetry feature is split across two commits on `main`:

1. **Production receiver** (`web/oss_telemetry/` + settings/urls) — stays on `main` only. **Do not cherry-pick this commit to `oss-release`.**
2. **OSS client** (`web/telemetry/`, `setup.sh` changes, feature counters, `docs/TELEMETRY.md`) — cherry-pick this commit to `oss-release`.

After cherry-picking commit 2:
- `web/CodePathfinder/settings.py`: the `'oss_telemetry'` entry in `INSTALLED_APPS` comes from commit 1 (not present on `oss-release`). Verify only `'telemetry'` is listed.
- `web/CodePathfinder/urls.py`: remove the `path('telemetry/', ...)` line (production receiver route, not needed on OSS side).
- The `TELEMETRY_ENDPOINT` in `web/telemetry/client.py` points to `https://codepathfinder.com/telemetry/event` — this is intentional and should NOT be replaced with a placeholder.

---

## Example: Porting a Feature Commit

Suppose a new commit `abc1234` on `main` adds a feature that touches K8s
manifests and Django settings. Here's the full walkthrough.

### Step 1 — Cherry-pick

```bash
git checkout oss-release
git cherry-pick abc1234
```

Expect conflicts if `oss-release` has diverged in the same files (e.g.
`deployment.yaml` where placeholders replaced production values).

### Step 2 — Review the diff for production refs

```bash
# Scan the cherry-picked diff
git diff HEAD~1 | grep -E "wired-sound|us-central1-docker|codepathfinder\.com|grabowskit"
```

Common things to fix:

**`kubernetes/deployment.yaml`** — image tag and Cloud SQL instance:
```yaml
# BEFORE (from main)
image: us-central1-docker.pkg.dev/wired-sound-479919-k8/codepathfinder/web:v1.3.1
# AFTER (oss-release)
image: <YOUR_REGISTRY>/codepathfinder/web:latest
```

**`kubernetes/cronjob-status-checker.yaml`** — same patterns:
```yaml
# BEFORE
image: us-central1-docker.pkg.dev/wired-sound-479919-k8/codepathfinder/web:latest
- "wired-sound-479919-k8:us-central1:codepathfinder-db"
# AFTER
image: <YOUR_REGISTRY>/codepathfinder/web:latest
- "<YOUR_GCP_PROJECT>:<YOUR_REGION>:<YOUR_CLOUD_SQL_INSTANCE>"
```

**`web/CodePathfinder/settings.py`** — check `ALLOWED_HOSTS`,
`CSRF_TRUSTED_ORIGINS`, `SESSION_COOKIE_DOMAIN`, `DEFAULT_FROM_EMAIL` for
`grabowskit.tplinkdns.com` and `codepathfinder.com` hardcoded values.

### Step 3 — Fix and commit

```bash
# Edit the files that need sanitizing, then:
git add <fixed-files>
git commit -m "Sanitize production refs for OSS release"
```

Or amend the cherry-pick directly:
```bash
git add <fixed-files>
git commit --amend --no-edit
```

### Step 4 — Sync to the public repo

```bash
# Re-archive oss-release into the public repo directory
git archive oss-release | tar -xf - -C /tmp/codepathfinder-public

# Manually git rm any files that were deleted (tar doesn't handle deletions)

cd /tmp/codepathfinder-public
git add -A
git commit -m "Port <feature> from main (sanitized)"
git push origin main
```

---

## Already Ported Features

The `oss-release` branch was forked from `main` at `a540d2c`, so the following
features are already included and sanitized:

| Commit | Feature |
|--------|---------|
| `d870111` | OTel data plane, internal instrumentation, request/auth logging |
| `a540d2c` | Elastic Cloud Serverless support for OTel index templates |
| `71e5322` | Personal skills with forking, user repositories, OTel project settings |

---

## Keeping Track of What's Been Ported

To see commits on `main` not yet in `oss-release`:

```bash
git log --oneline oss-release..main
```

After each cherry-pick + sanitize cycle the list will shrink. Aim to port
commits in small batches so the sanitization review stays manageable.
