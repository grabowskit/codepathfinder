# Memory Management Guide

This guide explains how to maintain and update the CodePathfinder development memory system.

## Overview

The memory system lives in `~/.claude/projects/-Users-grabowskit-dev-pathfinder/memory/` and helps AI agents understand project context, deployment gotchas, and institutional knowledge.

## Memory Types

| Type | Purpose | Example |
|------|---------|---------|
| **user** | User preferences, role, knowledge | "User is a backend engineer, prefers Python over TypeScript" |
| **feedback** | How to approach work (dos/don'ts) | "Always verify imports before deploying (Why: ImportError crashed prod)" |
| **project** | Ongoing work, goals, initiatives | "Migrating chat to LibreChat (Why: reduce maintenance burden)" |
| **reference** | Pointers to external systems | "Production logs are in GCP project my-gcp-project" |

## Updating Memory After Chat Sessions

Use the `update-memory.sh` script to capture learnings from chat sessions:

```bash
# Interactive mode (recommended)
./scripts/update-memory.sh

# Quick mode (for simple notes)
./scripts/update-memory.sh --quick "Added CPF_INTERNAL_PROJECT_ID secret for OTel"
```

### Interactive Mode Walkthrough

The script will guide you through 8 steps:

1. **Chat Session Summary** - What did you work on?
   - Example: "Fixed Elasticsearch indexer BATCH_SIZE for Elastic Cloud limits"

2. **Key Learnings** - What's important to remember?
   - Example: "BATCH_SIZE of 1 caused 14× throughput regression. Optimal is 10 for Elastic Cloud Serverless (6000 docs/min limit)"

3. **Memory Type** - Choose user/feedback/project/reference

4. **File Selection** - Update existing or create new memory file

5. **Metadata** (if new file) - Name and description

6. **Additional Context** - Why important? How to apply? (for feedback/project types)

7. **Preview & Confirm** - Review the update before writing

8. **Optional** - Update `docs/cpf-dev-memory.md` timestamp

### Example Session

```bash
$ ./scripts/update-memory.sh

╔════════════════════════════════════════════════╗
║   CodePathfinder Memory Update Tool           ║
╚════════════════════════════════════════════════╝

Step 1: Chat Session Summary
What did you work on in this session?
> Fixed indexer job labels bug - jobs weren't being found by label selector

Step 2: Key Learnings
What should be remembered for future sessions?
> Labels must be set on BOTH Job object metadata AND pod template.
  list_namespaced_job(label_selector="project-id=N") matches Job labels, not pod labels.

Memory types:
1. user
2. feedback
3. project
4. reference

Select memory type [1-4]: 2

Existing memory files:
1. deployment_gotchas (deployment_gotchas.md)
   Critical deployment failures and lessons learned

Select file to update: 1

Additional Context
Why is this important?: Job status tracking was broken for 20 days because jobs weren't found
How should this be applied?: When creating K8s Jobs, always set labels in V1ObjectMeta AND pod template

Preview:
────────────────────────────────────────────
Updating existing file: /Users/grabowskit/.claude/projects/.../memory/deployment_gotchas.md

## Fixed indexer job labels bug (added 2026-04-04)

Labels must be set on BOTH Job object metadata AND pod template...

**Why:** Job status tracking was broken for 20 days because jobs weren't found

**How to apply:** When creating K8s Jobs, always set labels in V1ObjectMeta AND pod template
────────────────────────────────────────────

Proceed with update? [y/N] y

✓ Backed up to .backups/deployment_gotchas.md.20260404_153022.bak
✓ Memory updated!
  File: /Users/grabowskit/.claude/projects/.../memory/deployment_gotchas.md

Update docs/cpf-dev-memory.md as well? [y/N] y
✓ Updated Last Updated date in cpf-dev-memory.md
Note: You may want to manually add details to the relevant section

Done!
```

## Memory Structure

### Memory Index (MEMORY.md)

The main index file that lists all memory files. Format:

```markdown
## Section Name

- [Memory Title](filename.md) — One-line description
```

### Individual Memory Files

Each memory file has frontmatter and content:

```markdown
---
name: short_name
description: One-line description for relevance matching
type: user|feedback|project|reference
---

## Topic Name (added YYYY-MM-DD)

Content here...

**Why:** (for feedback/project types)

**How to apply:** (for feedback/project types)
```

## Best Practices

### When to Create Memory

✅ **Do create memory for:**
- Deployment failures and fixes
- Non-obvious architecture decisions
- Recurring gotchas or pitfalls
- External system locations/credentials
- User workflow preferences

❌ **Don't create memory for:**
- Code patterns (derivable from codebase)
- Git history (use `git log`)
- Information in CLAUDE.md files
- Ephemeral task details
- Current conversation context

### Memory Hygiene

1. **Update stale memories** - If reality has changed, update or remove the memory
2. **Verify before acting** - Memories are point-in-time snapshots; verify against current state
3. **Keep descriptions specific** - "Elasticsearch indexer BATCH_SIZE gotcha" not "indexer issue"
4. **Include dates** - Always add `(added YYYY-MM-DD)` to section headers
5. **Structure feedback/project** - Always include **Why:** and **How to apply:** sections

### Checking Memory Age

The system adds age warnings to memory files:

```
<system-reminder>This memory is 4 days old...</system-reminder>
```

If a memory is more than a few days old and you're making decisions based on it, verify the facts haven't changed.

## Backup and Recovery

The `update-memory.sh` script automatically backs up files before modifying them:

```bash
# Backups are stored in
~/.claude/projects/-Users-grabowskit-dev-pathfinder/memory/.backups/

# Format: filename.YYYYMMDD_HHMMSS.bak

# To restore a backup:
cp ~/.claude/projects/.../memory/.backups/deployment_gotchas.md.20260404_153022.bak \
   ~/.claude/projects/.../memory/deployment_gotchas.md
```

## Integration with cpf-dev-memory.md

The `docs/cpf-dev-memory.md` file is the high-level AI agent onboarding doc. It links to memory files but doesn't duplicate their content.

After updating memory:
1. Run `./scripts/update-memory.sh` and let it update the "Last Updated" timestamp
2. Manually update relevant sections in `cpf-dev-memory.md` if needed
3. The memory files are the source of truth; `cpf-dev-memory.md` is the index

## Tips for AI Agents Reading Memory

When Claude or another AI agent reads memory:

1. **Check the date** - Memory files show when they were last updated
2. **Verify current state** - Don't assume a file mentioned in memory still exists; check with `Read` tool
3. **Trust but verify** - If memory says "X exists", grep/glob for it before recommending
4. **Prefer recent** - For architecture snapshots, prefer `git log` over old memory
5. **Memory ≠ current** - "The memory says X exists" is not the same as "X exists now"

## Manual Memory Management

You can also manually edit memory files:

```bash
# Edit a memory file
vim ~/.claude/projects/-Users-grabowskit-dev-pathfinder/memory/deployment_gotchas.md

# Add to index
vim ~/.claude/projects/-Users-grabowskit-dev-pathfinder/memory/MEMORY.md

# Format:
# - [Memory Name](filename.md) — One-line description
```

## Quick Reference

```bash
# Interactive memory update
./scripts/update-memory.sh

# Quick note to MEMORY.md
./scripts/update-memory.sh --quick "Note text here"

# View all memory files
ls ~/.claude/projects/-Users-grabowskit-dev-pathfinder/memory/

# View main index
cat ~/.claude/projects/-Users-grabowskit-dev-pathfinder/memory/MEMORY.md

# Search memory content
grep -r "keyword" ~/.claude/projects/-Users-grabowskit-dev-pathfinder/memory/

# View recent backups
ls -lt ~/.claude/projects/-Users-grabowskit-dev-pathfinder/memory/.backups/ | head
```

---

**Related Documentation:**
- [docs/cpf-dev-memory.md](cpf-dev-memory.md) - Main AI agent onboarding doc
- [~/.claude/projects/.../memory/MEMORY.md](~/.claude/projects/-Users-grabowskit-dev-pathfinder/memory/MEMORY.md) - Memory index
