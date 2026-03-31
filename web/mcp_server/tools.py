"""
MCP Tools for CodePathfinder

This module implements tools for code search, GitHub operations, skills, and job management:

Code Search Tools (from Elastic semantic-code-search-mcp-server):
1. semantic_code_search - Search code by semantic meaning
2. map_symbols_by_query - Find symbols grouped by file path
3. size - Get index statistics
4. symbol_analysis - Analyze symbol definitions and references
5. read_file_from_chunks - Reconstruct file from indexed chunks
6. document_symbols - List symbols in a file for documentation

GitHub Tools:
7. github_create_issue - Create a new GitHub issue (with templates and draft mode)
8. github_get_labels - Get available labels for a repository
9. github_add_comment - Add a comment to an issue/PR
10. github_create_pull_request - Create a new pull request
11. github_create_branch - Create a new branch
12. github_list_branches - List repository branches
13. github_get_repo_info - Get repository information

Skills Tools:
14. skills_list - List all available skills
15. skills_get - Get a skill by name
16. skills_search - Search for skills
17. skills_sync - Sync skills from GitHub repository (admin only)
18. skills_import - Import a skill from SKILL.md content
19. skills_activate - Activate a skill for the conversation (use this to "become" a skill)
20. skills_discover - Discover and import skills from an external GitHub repository

Memories Tools:
21. memories_list - List memories (personal and/or organization)
22. memories_get - Get a memory by ID
23. memories_search - Semantic search across memories
24. memories_create - Create a new memory
25. memories_update - Update an existing memory
26. memories_delete - Soft-delete a memory
27. memories_import - Import a markdown document as a RAG memory

Job Management Tools:
28. job_manage - Manage indexing jobs (start, stop, reset, create, update, delete, bulk ops)
29. job_status - Get job status and information (status, list, details, logs, history)

All tools support project-scoped access control.
"""

import os
import logging
from typing import Dict, List, Optional, Any
from elasticsearch import Elasticsearch
from django.conf import settings
from django.db.models import Q
from projects.models import PathfinderProject
from projects.github_service import GitHubService, GitHubPermissionError
from skills.services import SkillService, SkillSyncError
from skills.models import Skill, SkillUsage
from projects.utils import get_es_client

logger = logging.getLogger(__name__)


class ToolError(Exception):
    """Exception raised when a tool execution fails"""
    pass



# Tool definitions used by MCP protocol
TOOL_DEFINITIONS = [
    # Code Search Tools
    {
        "name": "semantic_code_search",
        "description": "Search the codebase using semantic meaning. Searches all accessible projects by default, or specific projects if provided.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query"
                },
                "projects": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of project names to search. If not provided, searches all accessible projects."
                },
                "size": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 10, max: 50)",
                    "default": 10
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "map_symbols_by_query",
        "description": "Find symbols (functions, classes, methods) matching a query, grouped by file",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for symbol names"
                },
                "projects": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of project names to search"
                },
                "size": {
                    "type": "integer",
                    "description": "Maximum number of files to return (default: 20)",
                    "default": 20
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "size",
        "description": "Get statistics about indexed projects (document count, storage size)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projects": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of project names to get stats for"
                }
            }
        }
    },
    {
        "name": "symbol_analysis",
        "description": "Analyze a symbol to find its definitions and references across the codebase",
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol_name": {
                    "type": "string",
                    "description": "Name of the symbol to analyze"
                },
                "projects": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of project names to search"
                }
            },
            "required": ["symbol_name"]
        }
    },
    {
        "name": "read_file_from_chunks",
        "description": "Reconstruct a file's content from indexed code chunks",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to reconstruct"
                },
                "projects": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of project names to search"
                }
            },
            "required": ["file_path"]
        }
    },
    {
        "name": "document_symbols",
        "description": "List all symbols in a file that would benefit from documentation",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to analyze"
                },
                "projects": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of project names to search"
                }
            },
            "required": ["file_path"]
        }
    },
    # GitHub Tools
    {
        "name": "github_manage_issues",
        "description": "Manage GitHub issues and PR comments. Actions: create_issue, add_comment, get_labels.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create_issue", "add_comment", "get_labels"],
                    "description": "The action to perform"
                },
                "project_name": {
                    "type": "string",
                    "description": "Name of the project"
                },
                "title": {"type": "string", "description": "Issue title (for create_issue)"},
                "body": {"type": "string", "description": "Issue/Comment body (for create_issue, add_comment)"},
                "issue_number": {"type": "integer", "description": "Issue/PR number (for add_comment)"},
                "labels": {
                    "type": "array", 
                    "items": {"type": "string"}, 
                    "description": "Optional list of label names (for create_issue)"
                },
                "issue_type": {
                    "type": "string", 
                    "enum": ["bug", "feature", "general"], 
                    "description": "Issue type for template formatting (for create_issue, default: general)"
                },
                "draft": {"type": "boolean", "description": "Return a preview without creating (for create_issue)"},
                "code_references": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string"},
                            "line_start": {"type": "integer"},
                            "line_end": {"type": "integer"},
                            "snippet": {"type": "string"},
                            "description": {"type": "string"}
                        },
                        "required": ["file_path"]
                    },
                    "description": "Code references to include (for create_issue)"
                },
                "steps_to_reproduce": {"type": "string", "description": "For bug reports: steps to reproduce"},
                "expected_behavior": {"type": "string", "description": "For bug reports: expected behavior"},
                "actual_behavior": {"type": "string", "description": "For bug reports: actual/observed behavior"},
                "environment": {"type": "string", "description": "For bug reports: environment details"},
                "use_case": {"type": "string", "description": "For feature requests: the use case"},
                "proposed_solution": {"type": "string", "description": "For feature requests: proposed solution"},
                "alternatives_considered": {"type": "string", "description": "For feature requests: alternatives considered"}
            },
            "required": ["action", "project_name"]
        }
    },
    {
        "name": "github_manage_code",
        "description": "Manage GitHub repository, branches, and code changes. Actions: get_info, latest_changes, list_branches, create_branch, create_pr.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get_info", "latest_changes", "list_branches", "create_branch", "create_pr"],
                    "description": "The action to perform"
                },
                "project_name": {
                    "type": "string",
                    "description": "Name of the project"
                },
                "branch": {"type": "string", "description": "Optional branch name (for latest_changes)"},
                "limit": {"type": "integer", "description": "Max commits to return (for latest_changes, default: 10)"},
                "branch_name": {"type": "string", "description": "Name for the new branch (for create_branch)"},
                "from_ref": {"type": "string", "description": "Source branch/ref (for create_branch, default: main)"},
                "title": {"type": "string", "description": "PR title (for create_pr)"},
                "body": {"type": "string", "description": "PR body/description (for create_pr)"},
                "head": {"type": "string", "description": "Head branch name (for create_pr)"},
                "base": {"type": "string", "description": "Base branch name (for create_pr, default: main)"}
            },
            "required": ["action", "project_name"]
        }
    },
    # Skills Tools
    {
        "name": "skills_list",
        "description": "List all available skills with optional filtering by tags or curated status",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of tags to filter by"
                },
                "curated_only": {
                    "type": "boolean",
                    "description": "If true, only return curated skills",
                    "default": False
                }
            }
        }
    },
    {
        "name": "skills_get",
        "description": "Get a skill by its exact name with full details and instructions",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Exact name of the skill"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "skills_search",
        "description": "Search for skills by name, description, or tags",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default: 5)",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "skills_sync",
        "description": "Sync skills from the configured GitHub repository. Admin-only operation.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "skills_import",
        "description": "Import a skill from SKILL.md formatted content with YAML frontmatter",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "SKILL.md formatted content string with YAML frontmatter and markdown instructions"
                }
            },
            "required": ["content"]
        }
    },
    {
        "name": "skills_activate",
        "description": "Activate a skill for the current conversation. Returns full instructions to follow as a persona.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Exact name of the skill to activate (e.g., 'code-review-coach')"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "skills_discover",
        "description": "Discover and import skills from an external GitHub repository. Call without import_skills to list available skills, then call again with import_skills to import selected ones.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_url": {
                    "type": "string",
                    "description": "GitHub repository URL containing skills (e.g., 'https://github.com/org/community-skills')"
                },
                "branch": {
                    "type": "string",
                    "description": "Branch to scan (default: 'main')",
                    "default": "main"
                },
                "import_skills": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of skill names to import. If omitted, just lists available skills without importing."
                },
                "scope": {
                    "type": "string",
                    "enum": ["personal", "global"],
                    "description": "Import scope: 'personal' (default, your own skills) or 'global' (admin only, visible to all users)",
                    "default": "personal"
                }
            },
            "required": ["repo_url"]
        }
    },
    # Memories Tools
    {
        "name": "memories_list",
        "description": "List memories (personal and/or organization) with optional tag, scope, or type filter",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by tags (AND match)"
                },
                "scope": {
                    "type": "string",
                    "enum": ["user", "organization"],
                    "description": "Filter by scope: 'user' (personal) or 'organization' (shared)"
                },
                "memory_type": {
                    "type": "string",
                    "enum": ["text", "document"],
                    "description": "Filter by memory type"
                }
            }
        }
    },
    {
        "name": "memories_get",
        "description": "Get a memory by ID with full content",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "integer",
                    "description": "Memory ID"
                }
            },
            "required": ["memory_id"]
        }
    },
    {
        "name": "memories_search",
        "description": "Semantic search across memories (org + personal) using ELSER",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default: 5)",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "memories_create",
        "description": "Create a new memory. User scope is open to all users; organization scope requires admin.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Memory title"},
                "content": {"type": "string", "description": "Memory content (markdown or plain text)"},
                "memory_type": {
                    "type": "string",
                    "enum": ["text", "document"],
                    "description": "Type: 'text' for short facts, 'document' for longer docs",
                    "default": "text"
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for categorization and auto-injection matching"
                },
                "scope": {
                    "type": "string",
                    "enum": ["user", "organization"],
                    "description": "Scope: 'user' (personal, default) or 'organization' (admin only)",
                    "default": "user"
                }
            },
            "required": ["title", "content"]
        }
    },
    {
        "name": "memories_update",
        "description": "Update an existing memory. Owner can update personal memories; admins can update org memories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "integer", "description": "Memory ID"},
                "title": {"type": "string"},
                "content": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "scope": {"type": "string", "enum": ["user", "organization"]}
            },
            "required": ["memory_id"]
        }
    },
    {
        "name": "memories_delete",
        "description": "Soft-delete a memory. Owner can delete personal memories; admins can delete org memories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "integer", "description": "Memory ID to delete"}
            },
            "required": ["memory_id"]
        }
    },
    {
        "name": "memories_import",
        "description": "Import a markdown document as a chunked RAG memory. Personal scope is open to all users; organization scope requires admin.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Document title"},
                "content": {"type": "string", "description": "Full markdown document content"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for categorization"
                },
                "scope": {
                    "type": "string",
                    "enum": ["user", "organization"],
                    "description": "Scope: 'user' (personal, default) or 'organization' (admin only)",
                    "default": "user"
                }
            },
            "required": ["title", "content"]
        }
    },
    # Job Management Tools
    {
        "name": "job_manage",
        "description": """Manage CodePathFinder indexing jobs for a project.

Actions:
- start: Start indexing a project's codebase
- stop: Stop a running indexing job
- reset: Reset a failed/stuck project to pending
- create: Create a new project for indexing
- update: Update project settings (name, branch, concurrency)
- delete: Delete a project and its index
- bulk_start: Start multiple projects at once
- bulk_stop: Stop multiple running jobs

Examples:
- Start indexing: job_manage(action="start", project="my-repo")
- Start with clean: job_manage(action="start", project="my-repo", clean_index=true)
- Stop job: job_manage(action="stop", project="my-repo")
- Create project: job_manage(action="create", repository_url="https://github.com/org/repo", name="my-repo")
- Create and start: job_manage(action="create", repository_url="https://github.com/org/repo", name="my-repo", auto_start=true)
- Update settings: job_manage(action="update", project="my-repo", branch="develop", concurrency=8)
- Bulk start: job_manage(action="bulk_start", project_ids=[1, 2, 3])
- Bulk stop: job_manage(action="bulk_stop", project_ids=[1, 2, 3])""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "reset", "create", "update", "delete", "bulk_start", "bulk_stop"],
                    "description": "The action to perform"
                },
                "project": {
                    "type": "string",
                    "description": "Project name (for single-project actions)"
                },
                "project_id": {
                    "type": "integer",
                    "description": "Project ID (alternative to project name)"
                },
                "project_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of project IDs (for bulk_start, bulk_stop actions)"
                },
                "repository_url": {
                    "type": "string",
                    "description": "GitHub repository URL (required for create action)"
                },
                "name": {
                    "type": "string",
                    "description": "Project name (for create/update actions)"
                },
                "branch": {
                    "type": "string",
                    "description": "Git branch to index (default: main)"
                },
                "clean_index": {
                    "type": "boolean",
                    "description": "Delete existing index before starting (default: false)"
                },
                "concurrency": {
                    "type": "integer",
                    "description": "Number of parallel indexing workers (1-16, default: 4)"
                },
                "auto_start": {
                    "type": "boolean",
                    "description": "Start indexing immediately after create (default: false)"
                },
                "github_token": {
                    "type": "string",
                    "description": "GitHub token for private repositories (for create action)"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "job_status",
        "description": """Get status and information about CodePathFinder indexing jobs.

Actions:
- status: Get current status of a specific project (progress, document count, etc.)
- list: List all accessible projects with their status summary
- details: Get full project details including configuration
- logs: Get recent logs from a job (optionally specify tail count)
- history: Get history of past job runs for a project

Examples:
- Check status: job_status(action="status", project="my-repo")
- List all: job_status(action="list")
- List running: job_status(action="list", status_filter="running")
- List completed: job_status(action="list", status_filter="completed")
- Get details: job_status(action="details", project="my-repo")
- Get logs: job_status(action="logs", project="my-repo", tail=100)
- View history: job_status(action="history", project="my-repo")""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "list", "details", "logs", "history"],
                    "description": "The type of information to retrieve"
                },
                "project": {
                    "type": "string",
                    "description": "Project name (required for status, details, logs, history)"
                },
                "project_id": {
                    "type": "integer",
                    "description": "Project ID (alternative to project name)"
                },
                "status_filter": {
                    "type": "string",
                    "enum": ["pending", "running", "completed", "failed", "watching", "stopped"],
                    "description": "Filter projects by status (for list action)"
                },
                "tail": {
                    "type": "integer",
                    "description": "Number of log lines to return (default: 100, max: 500)"
                },
                "page": {
                    "type": "integer",
                    "description": "Page number for paginated results (default: 1)"
                },
                "page_size": {
                    "type": "integer",
                    "description": "Items per page (default: 20, max: 100)"
                }
            },
            "required": ["action"]
        }
    },
    # OTel Collection Tools
    {
        "name": "otel_configure_collection",
        "description": """Configure OpenTelemetry collection for a project.

Actions:
- enable: Enable OTel collection (creates settings if needed)
- disable: Disable OTel collection
- update: Update settings (service_name, signal toggles)
- generate_key: Generate an API key with 'otel' scope for OTLP ingest
- status: Get current OTel collection status and config

Examples:
- Enable: otel_configure_collection(action="enable", project="my-app")
- Traces only: otel_configure_collection(action="enable", project="my-app", collect_metrics=false, collect_logs=false)
- Gen key: otel_configure_collection(action="generate_key", project="my-app", label="Prod Collector")
- Status: otel_configure_collection(action="status", project="my-app")""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["enable", "disable", "update", "generate_key", "status"],
                    "description": "The action to perform"
                },
                "project": {"type": "string", "description": "Project name"},
                "project_id": {"type": "integer", "description": "Project ID (alternative to name)"},
                "service_name": {"type": "string", "description": "Custom service.name for telemetry"},
                "collect_traces": {"type": "boolean", "description": "Enable/disable trace collection"},
                "collect_metrics": {"type": "boolean", "description": "Enable/disable metrics collection"},
                "collect_logs": {"type": "boolean", "description": "Enable/disable log collection"},
                "label": {"type": "string", "description": "Label for generated API key"},
                "index_prefix": {"type": "string", "description": "Custom Elasticsearch index prefix (e.g. 'myapp-prod' → traces-customer.myapp-prod). Defaults to project-{id}."}
            },
            "required": ["action"]
        }
    },
    {
        "name": "otel_get_onboarding_config",
        "description": """Get onboarding configuration snippets for sending OTLP telemetry to a project.

Returns ready-to-use configuration pre-filled with the project's collector endpoint, auth details, and index routing.

Formats: env, python, node, otel_collector, dotnet, java

Examples:
- Env vars: otel_get_onboarding_config(project="my-app", format="env")
- Python SDK: otel_get_onboarding_config(project="my-app", format="python")
- Collector YAML: otel_get_onboarding_config(project="my-app", format="otel_collector")""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project name"},
                "project_id": {"type": "integer", "description": "Project ID"},
                "format": {
                    "type": "string",
                    "enum": ["otel_collector", "python", "node", "env", "dotnet", "java"],
                    "default": "env",
                    "description": "Configuration format to generate"
                }
            },
            "required": ["project"]
        }
    },
    {
        "name": "otel_query_traces",
        "description": """Query OpenTelemetry traces stored in Elasticsearch for a project.

Two modes:
- mode="raw" (default): Returns individual spans sorted by time.
- mode="aggregate": Returns bucketed/summarized data as JSON for reports and charts.

Time filtering (both modes):
- start_time/end_time accept ISO 8601 ("2026-03-09T00:00:00Z") or ES relative ("now-1h", "now-24h", "now-7d")

Key trace fields: name (operation), status.code (Ok/Error/Unset), duration (long, nanoseconds), resource.attributes.service.name, kind

Aggregation examples:
- Error rate over time:    mode="aggregate", start_time="now-24h", aggregation={"type": "date_histogram", "interval": "1h", "group_by": "status.code"}
- Avg duration per hour:   mode="aggregate", start_time="now-24h", aggregation={"type": "date_histogram", "interval": "1h", "metric": "avg", "metric_field": "duration"}
- P95 latency per service: mode="aggregate", aggregation={"type": "terms", "field": "resource.attributes.service.name", "metric": "percentiles", "metric_field": "duration", "percents": [50, 95, 99]}
- Top operations by count: mode="aggregate", aggregation={"type": "terms", "field": "name", "size": 10}
- Overall avg duration:    mode="aggregate", aggregation={"type": "avg", "field": "duration"}

Raw examples:
- Recent traces: otel_query_traces(project="my-app")
- Errors in last hour: otel_query_traces(project="my-app", status_code="ERROR", start_time="now-1h")""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project name"},
                "project_id": {"type": "integer", "description": "Project ID (alternative to name)"},
                "trace_id": {"type": "string", "description": "Filter by trace ID (raw mode)"},
                "service_name": {"type": "string", "description": "Filter by service.name"},
                "status_code": {
                    "type": "string",
                    "enum": ["OK", "ERROR", "UNSET"],
                    "description": "Filter by span status code"
                },
                "start_time": {
                    "type": "string",
                    "description": "Start of time range. ISO 8601 or ES relative (e.g. 'now-1h', 'now-24h', 'now-7d')"
                },
                "end_time": {
                    "type": "string",
                    "description": "End of time range. Defaults to 'now' when start_time is set"
                },
                "mode": {
                    "type": "string",
                    "enum": ["raw", "aggregate"],
                    "default": "raw",
                    "description": "raw: return individual spans. aggregate: return bucketed/summarized data as JSON"
                },
                "aggregation": {
                    "type": "object",
                    "description": "Aggregation spec (required when mode='aggregate')",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["date_histogram", "terms", "avg", "sum", "min", "max", "percentiles"],
                            "description": "Aggregation type"
                        },
                        "interval": {
                            "type": "string",
                            "description": "For date_histogram: '1h', '30m', '1d', or calendar: 'hour', 'day', 'week', 'month'"
                        },
                        "field": {
                            "type": "string",
                            "description": "For terms/numeric aggs: field to aggregate on (e.g. 'name', 'duration', 'resource.attributes.service.name')"
                        },
                        "metric": {
                            "type": "string",
                            "enum": ["avg", "sum", "min", "max", "percentiles"],
                            "description": "Sub-metric within each bucket"
                        },
                        "metric_field": {
                            "type": "string",
                            "description": "Field for sub-metric (e.g. 'duration' for latency stats)"
                        },
                        "group_by": {
                            "type": "string",
                            "description": "For date_histogram: break down each bucket by this field (e.g. 'status.code', 'name')"
                        },
                        "group_by_size": {"type": "integer", "default": 10, "description": "Max groups per bucket"},
                        "size": {"type": "integer", "default": 10, "description": "For terms: max buckets"},
                        "percents": {
                            "type": "array", "items": {"type": "number"},
                            "description": "Percentile thresholds (default [50, 95, 99])"
                        }
                    },
                    "required": ["type"]
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Max spans in raw mode (default 20, max 100). Ignored in aggregate mode."
                }
            },
            "required": ["project"]
        }
    },
    {
        "name": "otel_query_metrics",
        "description": """Query OpenTelemetry metrics stored in Elasticsearch for a project.

Two modes:
- mode="raw" (default): Returns individual metric data points.
- mode="aggregate": Returns bucketed/summarized data as JSON for reports and charts.

Metric values are stored under metrics.<name> (e.g. metrics.http.server.duration). Use metric_name to filter, and metrics.<name> as metric_field in aggregations.

Aggregation examples:
- Metric value over time: mode="aggregate", metric_name="http.server.duration", start_time="now-24h", aggregation={"type": "date_histogram", "interval": "1h", "metric": "avg", "metric_field": "metrics.http.server.duration"}
- Avg metric by service:  mode="aggregate", aggregation={"type": "terms", "field": "resource.attributes.service.name", "metric": "avg", "metric_field": "metrics.http.server.duration"}
- Overall sum:            mode="aggregate", aggregation={"type": "sum", "field": "metrics.http.server.request_count"}

Raw examples:
- All metrics: otel_query_metrics(project="my-app")
- By name: otel_query_metrics(project="my-app", metric_name="http.server.duration")""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project name"},
                "project_id": {"type": "integer", "description": "Project ID (alternative to name)"},
                "metric_name": {"type": "string", "description": "Filter by metric name (supports wildcard *)"},
                "service_name": {"type": "string", "description": "Filter by service.name"},
                "start_time": {
                    "type": "string",
                    "description": "Start of time range. ISO 8601 or ES relative (e.g. 'now-1h', 'now-24h', 'now-7d')"
                },
                "end_time": {
                    "type": "string",
                    "description": "End of time range. Defaults to 'now' when start_time is set"
                },
                "mode": {
                    "type": "string",
                    "enum": ["raw", "aggregate"],
                    "default": "raw",
                    "description": "raw: return data points. aggregate: return bucketed/summarized data as JSON"
                },
                "aggregation": {
                    "type": "object",
                    "description": "Aggregation spec (required when mode='aggregate'). Use metrics.<name> for metric_field.",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["date_histogram", "terms", "avg", "sum", "min", "max", "percentiles"],
                            "description": "Aggregation type"
                        },
                        "interval": {
                            "type": "string",
                            "description": "For date_histogram: '1h', '30m', '1d', or calendar: 'hour', 'day', 'week', 'month'"
                        },
                        "field": {
                            "type": "string",
                            "description": "For terms/numeric aggs: field to aggregate on (e.g. 'metrics.http.server.duration')"
                        },
                        "metric": {
                            "type": "string",
                            "enum": ["avg", "sum", "min", "max", "percentiles"],
                            "description": "Sub-metric within each bucket"
                        },
                        "metric_field": {
                            "type": "string",
                            "description": "Field for sub-metric (e.g. 'metrics.http.server.duration')"
                        },
                        "group_by": {
                            "type": "string",
                            "description": "For date_histogram: break down each bucket by this field"
                        },
                        "group_by_size": {"type": "integer", "default": 10, "description": "Max groups per bucket"},
                        "size": {"type": "integer", "default": 10, "description": "For terms: max buckets"},
                        "percents": {
                            "type": "array", "items": {"type": "number"},
                            "description": "Percentile thresholds (default [50, 95, 99])"
                        }
                    },
                    "required": ["type"]
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Max data points in raw mode (default 20, max 100). Ignored in aggregate mode."
                }
            },
            "required": ["project"]
        }
    },
    {
        "name": "otel_query_logs",
        "description": """Query OpenTelemetry logs stored in Elasticsearch for a project.

Two modes:
- mode="raw" (default): Returns individual log records.
- mode="aggregate": Returns bucketed/summarized data as JSON for reports and charts.

Key log fields for aggregation: severity_text (keyword: ERROR/WARN/INFO/DEBUG), severity_number (integer), resource.attributes.service.name. Do NOT use body.text as an aggregation field (it is analyzed text).

Aggregation examples:
- Log volume over time:        mode="aggregate", start_time="now-24h", aggregation={"type": "date_histogram", "interval": "1h"}
- Errors per hour:             mode="aggregate", severity="ERROR", start_time="now-24h", aggregation={"type": "date_histogram", "interval": "1h"}
- Log count by severity:       mode="aggregate", aggregation={"type": "terms", "field": "severity_text"}
- Severity breakdown over time: mode="aggregate", start_time="now-24h", aggregation={"type": "date_histogram", "interval": "1h", "group_by": "severity_text"}
- Logs per service:            mode="aggregate", aggregation={"type": "terms", "field": "resource.attributes.service.name"}

Raw examples:
- Recent logs: otel_query_logs(project="my-app")
- Errors in last hour: otel_query_logs(project="my-app", severity="ERROR", start_time="now-1h")
- Search body: otel_query_logs(project="my-app", search="connection refused")""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Project name"},
                "project_id": {"type": "integer", "description": "Project ID (alternative to name)"},
                "severity": {
                    "type": "string",
                    "description": "Filter by severity_text (e.g. ERROR, WARN, INFO, DEBUG)"
                },
                "service_name": {"type": "string", "description": "Filter by service.name"},
                "search": {"type": "string", "description": "Full-text search in log body"},
                "trace_id": {"type": "string", "description": "Filter by trace ID to correlate with spans"},
                "start_time": {
                    "type": "string",
                    "description": "Start of time range. ISO 8601 or ES relative (e.g. 'now-1h', 'now-24h', 'now-7d')"
                },
                "end_time": {
                    "type": "string",
                    "description": "End of time range. Defaults to 'now' when start_time is set"
                },
                "mode": {
                    "type": "string",
                    "enum": ["raw", "aggregate"],
                    "default": "raw",
                    "description": "raw: return log records. aggregate: return bucketed/summarized data as JSON"
                },
                "aggregation": {
                    "type": "object",
                    "description": "Aggregation spec (required when mode='aggregate'). Do not use body.text as a field.",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["date_histogram", "terms", "avg", "sum", "min", "max", "percentiles"],
                            "description": "Aggregation type"
                        },
                        "interval": {
                            "type": "string",
                            "description": "For date_histogram: '1h', '30m', '1d', or calendar: 'hour', 'day', 'week', 'month'"
                        },
                        "field": {
                            "type": "string",
                            "description": "For terms/numeric aggs: field to aggregate on (e.g. 'severity_text', 'severity_number')"
                        },
                        "metric": {
                            "type": "string",
                            "enum": ["avg", "sum", "min", "max", "percentiles"],
                            "description": "Sub-metric within each bucket"
                        },
                        "metric_field": {
                            "type": "string",
                            "description": "Field for sub-metric"
                        },
                        "group_by": {
                            "type": "string",
                            "description": "For date_histogram: break down each bucket by this field (e.g. 'severity_text')"
                        },
                        "group_by_size": {"type": "integer", "default": 10, "description": "Max groups per bucket"},
                        "size": {"type": "integer", "default": 10, "description": "For terms: max buckets"},
                        "percents": {
                            "type": "array", "items": {"type": "number"},
                            "description": "Percentile thresholds (default [50, 95, 99])"
                        }
                    },
                    "required": ["type"]
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Max log records in raw mode (default 20, max 100). Ignored in aggregate mode."
                }
            },
            "required": ["project"]
        }
    },
]





def _get_index_name(index: Optional[str] = None) -> str:
    """
    Get the index name to use for queries.

    Args:
        index: Optional index override

    Returns:
        Index name to use
    """
    return index or os.environ.get('ELASTICSEARCH_INDEX', 'code-chunks')


def resolve_project_indices(user, projects: Optional[List[str]] = None, index: Optional[str] = None) -> str:
    """
    Resolve project names to Elasticsearch index names with user authorization.

    Resolution order:
    1. If explicit index override is provided, use it (superuser debug case)
    2. If projects are specified, look them up and validate user access
    3. Default: Search all user-accessible projects

    Args:
        user: Django User object (or None for unauthenticated)
        projects: Optional list of project names to search
        index: Optional explicit index override

    Returns:
        Comma-separated string of index names for Elasticsearch

    Raises:
        ToolError: If user lacks access or projects don't exist
    """
    # 1. Explicit index override - but first check if it's a project name
    if index:
        # Check if this index is actually a project name that needs resolving
        if user and user.is_authenticated:
            project_by_name = PathfinderProject.objects.filter(
                Q(user=user) | Q(shared_with=user),
                name__iexact=index,
                is_enabled=True
            ).exclude(status='disabled').first()
            
            if project_by_name and project_by_name.custom_index_name:
                logger.info(f"Resolved project name '{index}' to index: {project_by_name.custom_index_name}")
                return project_by_name.custom_index_name
        
        # If not a project name, ONLY allow raw index override for superusers
        # This prevents regular users (or LLM hallucinations) from accessing arbitrary indices
        # or getting "no results" when the LLM guesses a wrong index name like "semantic-code-search"
        if user and user.is_superuser:
            logger.info(f"Using explicit index override (superuser): {index}")
            return index
        
        logger.warning(f"Ignoring raw index override '{index}' for non-superuser {user}")
        # Fall through to default behavior (search all projects)

    # 2. If projects specified, resolve them
    if projects:
        if not user or not user.is_authenticated:
            raise ToolError("Authentication required to search specific projects")

        # Create case-insensitive query for all requested projects
        name_query = Q()
        for p_name in projects:
            name_query |= Q(name__iexact=p_name)

        # Find projects user has access to (only enabled projects)
        filters = Q(name_query) & Q(is_enabled=True)
        if not user.is_superuser:
            filters &= (Q(user=user) | Q(shared_with=user))

        user_projects = PathfinderProject.objects.filter(
            filters
        ).exclude(status='disabled').values_list('custom_index_name', 'name')

        found_indices = []
        found_names = []
        
        # Build map of found names (case-insensitive keys) to handle "missing" check
        # We need to map the user's requested (potentially wrong case) name to the actual DB name
        # OR just check which of the requested names matched ANY db project
        
        # Simplest approach: normalize both sets for comparison
        # Store found projects
        for idx, name in user_projects:
            if idx:
                found_indices.append(idx)
                found_names.append(name)

        # Validate all requested projects were found (case-insensitive check)
        # Create a set of found names lowercased
        found_set_lower = {n.lower() for n in found_names}
        
        # Check which requested projects are missing
        missing = []
        for p in projects:
            if p.lower() not in found_set_lower:
                missing.append(p)

        if missing:
            raise ToolError(
                f"Projects not found, disabled, or access denied: {', '.join(sorted(missing))}"
            )

        if not found_indices:
            raise ToolError("No accessible projects found")

        indices_str = ','.join(found_indices)
        logger.info(f"Resolved projects {projects} to indices: {indices_str}")
        return indices_str

    # 3. Default: Search all user-accessible projects
    if user and user.is_authenticated:
        filters = Q(is_enabled=True)
        if not user.is_superuser:
            filters &= (Q(user=user) | Q(shared_with=user))

        all_user_projects = PathfinderProject.objects.filter(
            filters
        ).exclude(status='disabled').values_list('custom_index_name', flat=True)

        accessible_indices = [idx for idx in all_user_projects if idx]

        if accessible_indices:
            indices_str = ','.join(accessible_indices)
            logger.info(f"Default search: User {user.username} has {len(accessible_indices)} accessible project(s)")
            return indices_str
        else:
            logger.warning(f"User {user.username} has no accessible projects")
            raise ToolError("No projects available. Please create or get access to a project first.")

    # Fallback: No user, no projects - use default index
    default = os.environ.get('ELASTICSEARCH_INDEX', 'code-chunks')
    logger.info(f"No user context, using default index: {default}")
    return default


# =============================================================================
# Tool 1: semantic_code_search
# =============================================================================

def semantic_code_search(
    query: str,
    user=None,
    projects: Optional[List[str]] = None,
    index: Optional[str] = None,
    size: int = 10
) -> str:
    """
    Perform semantic search on code chunks using natural language queries.

    This tool uses Elasticsearch's semantic_text field with ELSER embeddings
    to find code that matches the semantic meaning of the query.

    Args:
        query: Natural language search query
        user: Django User object for project access control
        projects: Optional list of project names to search
        index: Optional index name override
        size: Maximum number of results to return (default: 10)

    Returns:
        Formatted string with search results

    Raises:
        ToolError: If search fails
    """
    es = get_es_client()
    if not es:
        raise ToolError("Search unavailable: Elasticsearch configuration missing")

    index_name = resolve_project_indices(user, projects, index)

    # Get inference_id from config
    from projects.utils import get_elasticsearch_config
    es_config = get_elasticsearch_config()
    inference_id = es_config.get('inference_id', '.elser-2-elasticsearch')

    try:
        # Check index mapping to determine which semantic field to use.
        # Indices indexed with semantic_text use that field; older indices may use content_embedding.
        # We inspect the mapping rather than relying on exception-based fallback because
        # sparse_vector queries on a missing/empty field return 200 with 0 hits (not an error).
        response = None
        try:
            mapping = es.indices.get_mapping(index=index_name)
            # Handle comma-separated multi-index names
            first_index = index_name.split(',')[0].strip()
            props = mapping.get(first_index, {}).get('mappings', {}).get('properties', {})
            has_semantic_text = 'semantic_text' in props
            has_content_embedding = 'content_embedding' in props
        except Exception:
            # If mapping check fails, default to trying semantic_text first
            has_semantic_text = True
            has_content_embedding = False

        # Attempt 1: semantic_text field (preferred — standard ELSER field for newer indices)
        if has_semantic_text:
            try:
                body = {
                    "query": {
                        "sparse_vector": {
                            "field": "semantic_text",
                            "inference_id": inference_id,
                            "query": query
                        }
                    },
                    "size": min(size, 50),
                    "_source": ["filePath", "content", "startLine", "endLine", "kind", "symbols"]
                }
                response = es.search(index=index_name, body=body, request_timeout=30)
            except Exception as e1:
                logger.debug(f"Sparse vector query on semantic_text failed: {e1}")

        # Attempt 2: content_embedding field (older index format)
        if (response is None or not response['hits']['hits']) and has_content_embedding:
            try:
                body = {
                    "query": {
                        "sparse_vector": {
                            "field": "content_embedding",
                            "inference_id": inference_id,
                            "query": query
                        }
                    },
                    "size": min(size, 50),
                    "_source": ["filePath", "content", "startLine", "endLine", "kind", "symbols"]
                }
                response = es.search(index=index_name, body=body, request_timeout=30)
            except Exception as e2:
                logger.debug(f"Sparse vector query on content_embedding failed: {e2}")

        # Fallback: plain text match query
        if response is None or not response['hits']['hits']:
            logger.warning(f"Semantic search returned no results for index '{index_name}', falling back to text match query.")
            body = {
                "query": {
                    "match": {
                        "content": {
                            "query": query,
                            "operator": "or"
                        }
                    }
                },
                "size": min(size, 50),
                "_source": ["filePath", "content", "startLine", "endLine", "kind", "symbols"]
            }
            response = es.search(index=index_name, body=body, request_timeout=30)

        hits = response['hits']['hits']
        try:
            from telemetry.counters import increment
            increment('search_count')
        except Exception:
            pass
        if not hits:
            return "No results found."

        results = []
        for hit in hits:
            source = hit['_source']
            file_path = source.get('filePath', 'unknown')
            content = source.get('content', '')
            start_line = source.get('startLine', '?')
            end_line = source.get('endLine', '?')
            score = hit['_score']
            kind = source.get('kind', 'unknown')

            # Defensive truncation: don't let a single chunk be massive
            if len(content) > 15000:
                content = content[:15000] + "... [Chunk truncated from " + str(len(content)) + " characters]"

            results.append(
                f"File: {file_path}:{start_line}-{end_line}\n"
                f"Kind: {kind}\n"
                f"Score: {score:.2f}\n"
                f"Content:\n{content}\n"
                f"---"
            )

        return "\n\n".join(results)

    except Exception as e:
        logger.error(f"Elasticsearch semantic search error: {e}")
        raise ToolError(f"Search failed: {str(e)}")


# =============================================================================
# Tool 2: map_symbols_by_query
# =============================================================================

def map_symbols_by_query(
    query: str,
    user=None,
    projects: Optional[List[str]] = None,
    index: Optional[str] = None,
    size: int = 20
) -> str:
    """
    Find symbols matching a query, grouped by file path.

    This tool searches for symbols (functions, classes, methods) that match
    the query and groups them by the files they appear in.

    Args:
        query: Search query for symbol names
        user: Django User object for project access control
        projects: Optional list of project names to search
        index: Optional index name override
        size: Maximum number of files to return (default: 20)

    Returns:
        Formatted string with symbols grouped by file

    Raises:
        ToolError: If search fails
    """
    es = get_es_client()
    if not es:
        raise ToolError("Search unavailable: Elasticsearch configuration missing")

    index_name = resolve_project_indices(user, projects, index)

    try:
        # Search for chunks containing symbols matching the query
        body = {
            "query": {
                "nested": {
                    "path": "symbols",
                    "query": {
                        "wildcard": {
                            "symbols.name": f"*{query}*"
                        }
                    }
                }
            },
            "size": size * 5,  # Get more hits to ensure we have enough files
            "_source": ["filePath", "symbols"],
            "collapse": {
                "field": "filePath"
            }
        }

        response = es.search(index=index_name, body=body, request_timeout=30)

        hits = response['hits']['hits']
        if not hits:
            return f"No symbols found matching '{query}'."

        # Group symbols by file
        files_map: Dict[str, List[Dict[str, Any]]] = {}
        for hit in hits:
            source = hit['_source']
            file_path = source.get('filePath', 'unknown')
            symbols = source.get('symbols', [])

            # Filter symbols that match the query
            matching_symbols = [
                s for s in symbols
                if query.lower() in s.get('name', '').lower()
            ]

            if matching_symbols:
                if file_path not in files_map:
                    files_map[file_path] = []
                files_map[file_path].extend(matching_symbols)

        if not files_map:
            return f"No symbols found matching '{query}'."

        # Format output
        results = []
        for file_path in sorted(files_map.keys())[:size]:
            symbols_list = files_map[file_path]
            # Deduplicate symbols by name
            unique_symbols = {s['name']: s for s in symbols_list}.values()

            symbol_lines = []
            for symbol in sorted(unique_symbols, key=lambda s: s.get('line', 0)):
                symbol_lines.append(
                    f"  - {symbol.get('name')} ({symbol.get('kind', 'unknown')}) at line {symbol.get('line', '?')}"
                )

            results.append(
                f"{file_path}:\n" + "\n".join(symbol_lines)
            )

        return "\n\n".join(results)

    except Exception as e:
        logger.error(f"Elasticsearch symbol query error: {e}")
        raise ToolError(f"Symbol query failed: {str(e)}")


# =============================================================================
# Tool 3: size
# =============================================================================

def size(
    user=None,
    projects: Optional[List[str]] = None,
    index: Optional[str] = None
) -> str:
    """
    Get statistics about the Elasticsearch index.

    Returns information about document count, storage size, and index health.

    Args:
        user: Django User object for project access control
        projects: Optional list of project names to search
        index: Optional index name override

    Returns:
        Formatted string with index statistics

    Raises:
        ToolError: If stats retrieval fails
    """
    es = get_es_client()
    if not es:
        raise ToolError("Search unavailable: Elasticsearch configuration missing")

    index_name = resolve_project_indices(user, projects, index)

    # Resolve friendly project names for display
    friendly_name = index_name
    if user:
        try:
            indices = index_name.split(',')
            found_projects = PathfinderProject.objects.filter(custom_index_name__in=indices)
            if found_projects.exists():
                friendly_name = ", ".join([p.name for p in found_projects])
        except Exception as e:
            logger.warning(f"Failed to resolve project names: {e}")

    try:
        # Get count
        count_response = es.count(index=index_name)
        doc_count = count_response['count']

        try:
            # Try getting detailed stats (might fail on serverless)
            stats = es.indices.stats(index=index_name)
            
            # Sum stats across all indices if multiple
            store_size_bytes = 0
            segments_count = 0
            
            for idx in stats['indices']:
                idx_stats = stats['indices'][idx]
                total = idx_stats.get('total', {})
                store_size_bytes += total.get('store', {}).get('size_in_bytes', 0)
                segments_count += total.get('segments', {}).get('count', 0)

            store_size_mb = store_size_bytes / (1024 * 1024)

            result = f"""Project: {friendly_name}
Document Count: {doc_count:,}
Storage Size: {store_size_mb:.2f} MB ({store_size_bytes:,} bytes)
Segments: {segments_count}
"""
        except Exception as e:
            # Fallback for serverless or if stats API fails
            logger.warning(f"Failed to get detailed stats for {index_name} (likely serverless): {e}")
            result = f"""Project: {friendly_name}
Document Count: {doc_count:,}
(Detailed storage stats unavailable in current environment)
"""

        return result

    except Exception as e:
        logger.error(f"Elasticsearch stats error: {e}")
        raise ToolError(f"Failed to get index stats: {str(e)}")


# =============================================================================
# Tool 4: symbol_analysis
# =============================================================================

def symbol_analysis(
    symbol_name: str,
    user=None,
    projects: Optional[List[str]] = None,
    index: Optional[str] = None
) -> str:
    """
    Analyze a symbol to find its definitions, call sites, and references.

    This tool provides a comprehensive report on where a symbol is defined,
    where it's called, and where it's referenced in the codebase.

    Args:
        symbol_name: Name of the symbol to analyze
        user: Django User object for project access control
        projects: Optional list of project names to search
        index: Optional index name override

    Returns:
        Formatted string with symbol analysis report

    Raises:
        ToolError: If analysis fails
    """
    es = get_es_client()
    if not es:
        raise ToolError("Search unavailable: Elasticsearch configuration missing")

    index_name = resolve_project_indices(user, projects, index)

    try:
        # Search for definitions (in symbols field)
        definitions_query = {
            "query": {
                "nested": {
                    "path": "symbols",
                    "query": {
                        "term": {
                            "symbols.name": symbol_name
                        }
                    }
                }
            },
            "size": 50,
            "_source": ["filePath", "symbols", "kind", "startLine", "endLine"]
        }

        definitions_response = es.search(index=index_name, body=definitions_query)

        # Search for references (in content)
        references_query = {
            "query": {
                "match": {
                    "content": symbol_name
                }
            },
            "size": 50,
            "_source": ["filePath", "content", "startLine", "endLine", "kind"]
        }

        references_response = es.search(index=index_name, body=references_query)

        # Process definitions
        definitions = []
        for hit in definitions_response['hits']['hits']:
            source = hit['_source']
            symbols = source.get('symbols', [])
            for symbol in symbols:
                if symbol.get('name') == symbol_name:
                    definitions.append({
                        'file': source.get('filePath', 'unknown'),
                        'kind': symbol.get('kind', 'unknown'),
                        'line': symbol.get('line', '?')
                    })

        # Process references
        references = []
        for hit in references_response['hits']['hits']:
            source = hit['_source']
            file_path = source.get('filePath', 'unknown')
            start_line = source.get('startLine', '?')
            end_line = source.get('endLine', '?')

            references.append({
                'file': file_path,
                'lines': f"{start_line}-{end_line}"
            })

        # Format output
        result_parts = [f"Symbol Analysis: {symbol_name}", "=" * 50]

        if definitions:
            result_parts.append(f"\nDefinitions ({len(definitions)}):")
            for defn in definitions[:10]:  # Limit to 10
                result_parts.append(f"  - {defn['file']}:{defn['line']} ({defn['kind']})")
        else:
            result_parts.append("\nDefinitions: None found")

        if references:
            result_parts.append(f"\nReferences ({len(references)}):")
            for ref in references[:20]:  # Limit to 20
                result_parts.append(f"  - {ref['file']}:{ref['lines']}")
        else:
            result_parts.append("\nReferences: None found")

        return "\n".join(result_parts)

    except Exception as e:
        logger.error(f"Elasticsearch symbol analysis error: {e}")
        raise ToolError(f"Symbol analysis failed: {str(e)}")


# =============================================================================
# Tool 5: read_file_from_chunks
# =============================================================================

def read_file_from_chunks(
    file_path: str,
    user=None,
    projects: Optional[List[str]] = None,
    index: Optional[str] = None
) -> str:
    """
    Reconstruct a file's content from indexed code chunks.

    This tool retrieves all chunks for a given file path and reconstructs
    the file content by sorting chunks by line number.

    Args:
        file_path: Path to the file to reconstruct
        user: Django User object for project access control
        projects: Optional list of project names to search
        index: Optional index name override

    Returns:
        Reconstructed file content

    Raises:
        ToolError: If reconstruction fails
    """
    es = get_es_client()
    if not es:
        raise ToolError("Search unavailable: Elasticsearch configuration missing")

    index_name = resolve_project_indices(user, projects, index)

    try:
        # Query for all chunks of this file
        body = {
            "query": {
                "term": {
                    "filePath": file_path
                }
            },
            "size": 1000,  # Assume most files have < 1000 chunks
            "_source": ["content", "startLine", "endLine", "kind"],
            "sort": [
                {"startLine": "asc"}
            ]
        }

        response = es.search(index=index_name, body=body, request_timeout=30)

        hits = response['hits']['hits']
        if not hits:
            return f"File not found: {file_path}"

        # Sort chunks by start line and reconstruct
        chunks = []
        for hit in hits:
            source = hit['_source']
            chunks.append({
                'content': source.get('content', ''),
                'start_line': source.get('startLine', 0),
                'end_line': source.get('endLine', 0)
            })

        # Sort by start line
        chunks.sort(key=lambda c: c['start_line'])

        # Reconstruct file
        result_parts = [f"File: {file_path}", "=" * 50, ""]

        total_len = 0
        max_file_content = 100000 # 100k chars max for a file reconstruction
        
        for chunk in chunks:
            chunk_content = chunk['content']
            if total_len + len(chunk_content) > max_file_content:
                remaining = max_file_content - total_len
                result_parts.append(f"# Lines {chunk['start_line']}-? (TRUNCATED - file too large)")
                result_parts.append(chunk_content[:remaining] + "\n... [Rest of file truncated] ...")
                break
                
            result_parts.append(f"# Lines {chunk['start_line']}-{chunk['end_line']}")
            result_parts.append(chunk_content)
            result_parts.append("")
            total_len += len(chunk_content)

        return "\n".join(result_parts)

    except Exception as e:
        logger.error(f"Elasticsearch file reconstruction error: {e}")
        raise ToolError(f"File reconstruction failed: {str(e)}")


# =============================================================================
# Tool 6: document_symbols
# =============================================================================

def document_symbols(
    file_path: str,
    user=None,
    projects: Optional[List[str]] = None,
    index: Optional[str] = None
) -> str:
    """
    List all symbols in a file that would benefit from documentation.

    This tool identifies key symbols (functions, classes, methods) in a file
    that are candidates for documentation to improve code quality.

    Args:
        file_path: Path to the file to analyze
        user: Django User object for project access control
        projects: Optional list of project names to search
        index: Optional index name override

    Returns:
        Formatted list of symbols recommended for documentation

    Raises:
        ToolError: If analysis fails
    """
    es = get_es_client()
    if not es:
        raise ToolError("Search unavailable: Elasticsearch configuration missing")

    index_name = resolve_project_indices(user, projects, index)

    try:
        # Query for all chunks of this file that have symbols
        body = {
            "query": {
                "bool": {
                    "must": [
                        {"term": {"filePath": file_path}},
                        {"exists": {"field": "symbols"}}
                    ]
                }
            },
            "size": 100,
            "_source": ["symbols", "content", "startLine"]
        }

        response = es.search(index=index_name, body=body, request_timeout=30)

        hits = response['hits']['hits']
        if not hits:
            return f"No symbols found in file: {file_path}"

        # Collect all unique symbols
        symbols_map: Dict[str, Dict[str, Any]] = {}

        for hit in hits:
            source = hit['_source']
            symbols = source.get('symbols', [])

            for symbol in symbols:
                name = symbol.get('name', '')
                kind = symbol.get('kind', 'unknown')
                line = symbol.get('line', 0)

                if name and name not in symbols_map:
                    symbols_map[name] = {
                        'kind': kind,
                        'line': line
                    }

        if not symbols_map:
            return f"No symbols found in file: {file_path}"

        # Sort symbols by line number
        sorted_symbols = sorted(
            symbols_map.items(),
            key=lambda x: x[1]['line']
        )

        # Format output
        result_parts = [
            f"Symbols in {file_path} requiring documentation:",
            "=" * 50,
            ""
        ]

        # Group by kind
        by_kind: Dict[str, List[tuple]] = {}
        for name, info in sorted_symbols:
            kind = info['kind']
            if kind not in by_kind:
                by_kind[kind] = []
            by_kind[kind].append((name, info['line']))

        # Format by kind
        for kind in sorted(by_kind.keys()):
            result_parts.append(f"{kind.upper()}:")
            for name, line in by_kind[kind]:
                result_parts.append(f"  - {name} (line {line})")
            result_parts.append("")

        return "\n".join(result_parts)

    except Exception as e:
        logger.error(f"Elasticsearch document symbols error: {e}")
        raise ToolError(f"Document symbols failed: {str(e)}")


# =============================================================================
# GitHub Tools Helper
# =============================================================================

def _get_project_for_github(user, project_name: str) -> PathfinderProject:
    """
    Get a project by name with user access validation.

    Args:
        user: Django User object
        project_name: Name of the project

    Returns:
        PathfinderProject instance

    Raises:
        ToolError: If user lacks access or project doesn't exist
    """
    if not user or not user.is_authenticated:
        raise ToolError("Authentication required for GitHub operations")

    filters = Q(name__iexact=project_name) & Q(is_enabled=True)
    if not user.is_superuser:
        filters &= (Q(user=user) | Q(shared_with=user))

    project = PathfinderProject.objects.filter(
        filters
    ).exclude(status='disabled').first()

    if not project:
        raise ToolError(f"Project not found or access denied: {project_name}")

    return project


# =============================================================================
# GitHub Issue Formatting Helper
# =============================================================================

def _format_issue_body(
    summary: str,
    issue_type: str = "general",
    code_references: Optional[List[Dict[str, Any]]] = None,
    steps_to_reproduce: Optional[str] = None,
    expected_behavior: Optional[str] = None,
    actual_behavior: Optional[str] = None,
    environment: Optional[str] = None,
    use_case: Optional[str] = None,
    proposed_solution: Optional[str] = None,
    alternatives_considered: Optional[str] = None
) -> str:
    """
    Format issue body using appropriate template based on issue type.

    Args:
        summary: Main issue description/summary
        issue_type: Type of issue ('bug', 'feature', 'general')
        code_references: List of code reference dicts with file_path, line_start, etc.
        steps_to_reproduce: For bugs - reproduction steps
        expected_behavior: For bugs - what should happen
        actual_behavior: For bugs - what actually happens
        environment: For bugs - environment details
        use_case: For features - the problem being solved
        proposed_solution: For features - suggested implementation
        alternatives_considered: For features - other approaches considered

    Returns:
        Formatted markdown body string
    """
    sections = []

    if issue_type == "bug":
        sections.append(f"## Summary\n{summary}")

        if steps_to_reproduce:
            sections.append(f"## Steps to Reproduce\n{steps_to_reproduce}")

        if expected_behavior:
            sections.append(f"## Expected Behavior\n{expected_behavior}")

        if actual_behavior:
            sections.append(f"## Actual Behavior\n{actual_behavior}")

        if environment:
            sections.append(f"## Environment\n{environment}")

    elif issue_type == "feature":
        sections.append(f"## Summary\n{summary}")

        if use_case:
            sections.append(f"## Use Case\n{use_case}")

        if proposed_solution:
            sections.append(f"## Proposed Solution\n{proposed_solution}")

        if alternatives_considered:
            sections.append(f"## Alternatives Considered\n{alternatives_considered}")
    else:
        # General issue - just use body as-is
        sections.append(summary)

    # Add code references section if provided
    if code_references:
        code_section = "## Related Code\n"
        for ref in code_references:
            file_path = ref.get('file_path', '')
            line_start = ref.get('line_start')
            line_end = ref.get('line_end')
            snippet = ref.get('snippet', '')
            description = ref.get('description', '')

            # Build file reference
            if line_start and line_end:
                file_ref = f"**`{file_path}` (lines {line_start}-{line_end})**"
            elif line_start:
                file_ref = f"**`{file_path}` (line {line_start})**"
            else:
                file_ref = f"**`{file_path}`**"

            code_section += f"\n{file_ref}\n"
            if description:
                code_section += f"{description}\n"
            if snippet:
                # Detect language from file extension
                lang = file_path.split('.')[-1] if '.' in file_path else ''
                code_section += f"```{lang}\n{snippet}\n```\n"

        sections.append(code_section)

    # Add footer
    sections.append("\n---\n*Created via CodePathfinder*")

    return "\n\n".join(sections)


# =============================================================================
# Tool 7: github_create_issue
# =============================================================================

def github_create_issue(
    project_name: str,
    title: str,
    body: str,
    labels: Optional[List[str]] = None,
    issue_type: str = "general",
    draft: bool = False,
    code_references: Optional[List[Dict[str, Any]]] = None,
    steps_to_reproduce: Optional[str] = None,
    expected_behavior: Optional[str] = None,
    actual_behavior: Optional[str] = None,
    environment: Optional[str] = None,
    use_case: Optional[str] = None,
    proposed_solution: Optional[str] = None,
    alternatives_considered: Optional[str] = None,
    user=None
) -> str:
    """
    Create a new GitHub issue on a project's repository.

    Supports two modes:
    1. Standard mode: Create issue immediately
    2. Draft mode (draft=True): Return a preview without creating

    Args:
        project_name: Name of the project
        title: Issue title
        body: Issue body/description (becomes summary for templated issues)
        labels: Optional list of label names
        issue_type: Type of issue - 'bug', 'feature', or 'general' (default)
        draft: If True, return preview without creating
        code_references: Code references to include in the issue
        steps_to_reproduce: For bugs - reproduction steps
        expected_behavior: For bugs - what should happen
        actual_behavior: For bugs - what actually happens
        environment: For bugs - environment details
        use_case: For features - the problem being solved
        proposed_solution: For features - suggested implementation
        alternatives_considered: For features - other approaches considered
        user: Django User object for access control

    Returns:
        Formatted string with issue details or preview

    Raises:
        ToolError: If creation fails
    """
    # Build formatted body based on issue_type
    formatted_body = _format_issue_body(
        summary=body,
        issue_type=issue_type,
        code_references=code_references,
        steps_to_reproduce=steps_to_reproduce,
        expected_behavior=expected_behavior,
        actual_behavior=actual_behavior,
        environment=environment,
        use_case=use_case,
        proposed_solution=proposed_solution,
        alternatives_considered=alternatives_considered
    )

    if draft:
        # Return preview without creating
        labels_str = ', '.join(labels) if labels else 'None'
        issue_type_str = issue_type.capitalize() if issue_type != "general" else "General"
        preview = f"""## Issue Preview (Draft Mode)

**Type:** {issue_type_str}
**Title:** {title}
**Labels:** {labels_str}

---

{formatted_body}

---
*This is a preview. To create this issue, call github_create_issue again with draft=false or omit the draft parameter.*"""
        return preview

    try:
        project = _get_project_for_github(user, project_name)
        github_service = GitHubService(user, project)
        issue = github_service.create_issue(title, formatted_body, labels)

        return f"""Issue created successfully!
Number: #{issue.number}
Title: {issue.title}
URL: {issue.html_url}
State: {issue.state}
Labels: {', '.join([l.name for l in issue.labels]) if issue.labels else 'None'}"""

    except GitHubPermissionError as e:
        raise ToolError(str(e))
    except Exception as e:
        logger.error(f"GitHub create_issue error: {e}")
        raise ToolError(f"Failed to create issue: {str(e)}")


# =============================================================================
# Tool 8: github_add_comment
# =============================================================================

def github_add_comment(
    project_name: str,
    issue_number: int,
    body: str,
    user=None
) -> str:
    """
    Add a comment to a GitHub issue or pull request.

    Args:
        project_name: Name of the project
        issue_number: Issue or PR number
        body: Comment body
        user: Django User object for access control

    Returns:
        Formatted string with comment details

    Raises:
        ToolError: If comment fails
    """
    try:
        project = _get_project_for_github(user, project_name)
        github_service = GitHubService(user, project)
        comment = github_service.add_comment(issue_number, body)

        return f"""Comment added successfully!
Issue/PR: #{issue_number}
Comment ID: {comment.id}
URL: {comment.html_url}"""

    except GitHubPermissionError as e:
        raise ToolError(str(e))
    except Exception as e:
        logger.error(f"GitHub add_comment error: {e}")
        raise ToolError(f"Failed to add comment: {str(e)}")


# =============================================================================
# Tool 9: github_create_pull_request
# =============================================================================

def github_create_pull_request(
    project_name: str,
    title: str,
    body: str,
    head: str,
    base: str = 'main',
    user=None
) -> str:
    """
    Create a new GitHub pull request.

    Args:
        project_name: Name of the project
        title: PR title
        body: PR body/description
        head: Head branch name (source branch)
        base: Base branch name (target branch, default: main)
        user: Django User object for access control

    Returns:
        Formatted string with PR details

    Raises:
        ToolError: If PR creation fails
    """
    try:
        project = _get_project_for_github(user, project_name)
        github_service = GitHubService(user, project)
        pr = github_service.create_pull_request(title, body, head, base)

        return f"""Pull request created successfully!
Number: #{pr.number}
Title: {pr.title}
URL: {pr.html_url}
State: {pr.state}
Head: {pr.head.ref} -> Base: {pr.base.ref}
Mergeable: {pr.mergeable if pr.mergeable is not None else 'Checking...'}"""

    except GitHubPermissionError as e:
        raise ToolError(str(e))
    except Exception as e:
        logger.error(f"GitHub create_pull_request error: {e}")
        raise ToolError(f"Failed to create pull request: {str(e)}")


# =============================================================================
# Tool 10: github_create_branch
# =============================================================================

def github_create_branch(
    project_name: str,
    branch_name: str,
    from_ref: str = 'main',
    user=None
) -> str:
    """
    Create a new branch on a project's repository.

    Args:
        project_name: Name of the project
        branch_name: Name for the new branch
        from_ref: Source branch/ref to branch from (default: main)
        user: Django User object for access control

    Returns:
        Formatted string with branch details

    Raises:
        ToolError: If branch creation fails
    """
    try:
        project = _get_project_for_github(user, project_name)
        github_service = GitHubService(user, project)
        ref = github_service.create_branch(branch_name, from_ref)

        return f"""Branch created successfully!
Name: {branch_name}
From: {from_ref}
Ref: {ref.ref}
SHA: {ref.object.sha}"""

    except GitHubPermissionError as e:
        raise ToolError(str(e))
    except Exception as e:
        logger.error(f"GitHub create_branch error: {e}")
        raise ToolError(f"Failed to create branch: {str(e)}")


# =============================================================================
# Tool 11: github_list_branches
# =============================================================================

def github_list_branches(
    project_name: str,
    user=None
) -> str:
    """
    List all branches in a project's repository.

    Args:
        project_name: Name of the project
        user: Django User object for access control

    Returns:
        Formatted string with branch list

    Raises:
        ToolError: If listing fails
    """
    try:
        project = _get_project_for_github(user, project_name)
        github_service = GitHubService(user, project)
        branches = github_service.list_branches()
        default_branch = github_service.get_default_branch()

        result_parts = [
            f"Branches in {project_name}:",
            f"Default branch: {default_branch}",
            "=" * 40
        ]

        for branch in sorted(branches):
            marker = " (default)" if branch == default_branch else ""
            result_parts.append(f"  - {branch}{marker}")

        result_parts.append(f"\nTotal: {len(branches)} branches")
        return "\n".join(result_parts)

    except GitHubPermissionError as e:
        raise ToolError(str(e))
    except Exception as e:
        logger.error(f"GitHub list_branches error: {e}")
        raise ToolError(f"Failed to list branches: {str(e)}")


# =============================================================================
# Tool 12: github_get_repo_info
# =============================================================================

def github_get_repo_info(
    project_name: str,
    user=None
) -> str:
    """
    Get repository information for a project.

    Args:
        project_name: Name of the project
        user: Django User object for access control

    Returns:
        Formatted string with repository details

    Raises:
        ToolError: If retrieval fails
    """
    try:
        project = _get_project_for_github(user, project_name)
        github_service = GitHubService(user, project)
        info = github_service.get_repo_info()

        return f"""Repository Information:
Name: {info['name']}
Full Name: {info['full_name']}
Description: {info['description'] or 'No description'}
Default Branch: {info['default_branch']}
Visibility: {'Private' if info['private'] else 'Public'}
URL: {info['html_url']}"""

    except GitHubPermissionError as e:
        raise ToolError(str(e))
    except Exception as e:
        logger.error(f"GitHub get_repo_info error: {e}")
        raise ToolError(f"Failed to get repository info: {str(e)}")


def github_get_latest_changes(
    project_name: str,
    branch: str = None,
    limit: int = 10,
    user=None
) -> str:
    """
    Get a list of the latest commits for a project.

    Args:
        project_name: Name of the project
        branch: Optional branch name
        limit: Max commits to return
        user: Django User object for access control

    Returns:
        Formatted string with recent commits

    Raises:
        ToolError: If retrieval fails
    """
    try:
        limit = min(int(limit), 100) # Cap at 100
        project = _get_project_for_github(user, project_name)
        github_service = GitHubService(user, project)
        commits = github_service.get_recent_commits(branch=branch, limit=limit)

        if not commits:
            return f"No recent commits found for project '{project_name}'"

        result = [f"Recent commits for project '{project_name}' (branch: {branch or github_service.get_repo_info()['default_branch']}):"]
        for commit in commits:
            date_str = commit['date'][:10] if commit['date'] else 'Unknown date'
            message = commit['message'].split('\n')[0][:80] # First line, truncated
            result.append(f"- [{commit['sha'][:7]}] {date_str} - {message} ({commit['author']})")

        return "\n".join(result)

    except GitHubPermissionError as e:
        raise ToolError(str(e))
    except Exception as e:
        logger.error(f"GitHub get_latest_changes error: {e}")
        raise ToolError(f"Failed to get recent commits: {str(e)}")


# =============================================================================
# Tool 13: github_get_labels
# =============================================================================

def github_get_labels(
    project_name: str,
    user=None
) -> str:
    """
    Get available labels for a project's repository.

    Use this to discover valid labels before creating issues.

    Args:
        project_name: Name of the project
        user: Django User object for access control

    Returns:
        Formatted string with available labels

    Raises:
        ToolError: If retrieval fails
    """
    try:
        project = _get_project_for_github(user, project_name)
        github_service = GitHubService(user, project)
        labels = github_service.list_labels()

        if not labels:
            return f"No labels configured for {project_name}."

        result_parts = [f"Available labels for {project_name}:", "=" * 40]
        for label in labels:
            desc = f" - {label['description']}" if label['description'] else ""
            result_parts.append(f"  - {label['name']}{desc}")

        result_parts.append(f"\nTotal: {len(labels)} labels")
        return "\n".join(result_parts)

    except GitHubPermissionError as e:
        raise ToolError(str(e))
    except Exception as e:
        logger.error(f"GitHub get_labels error: {e}")
        raise ToolError(f"Failed to list labels: {str(e)}")


# =============================================================================
# Consolidated GitHub Tools Handlers
# =============================================================================

def github_manage_issues(
    action: str,
    project_name: str,
    title: str = None,
    body: str = None,
    issue_number: int = None,
    labels: Optional[List[str]] = None,
    issue_type: str = "general",
    draft: bool = False,
    code_references: Optional[List[Dict[str, Any]]] = None,
    steps_to_reproduce: Optional[str] = None,
    expected_behavior: Optional[str] = None,
    actual_behavior: Optional[str] = None,
    environment: Optional[str] = None,
    use_case: Optional[str] = None,
    proposed_solution: Optional[str] = None,
    alternatives_considered: Optional[str] = None,
    user=None
) -> str:
    """Consolidated tool for managing GitHub issues."""
    if action == "create_issue":
        if not title or not body:
            raise ToolError("Title and body are required for create_issue")
        return github_create_issue(
            project_name, title, body, labels, issue_type, draft,
            code_references, steps_to_reproduce, expected_behavior,
            actual_behavior, environment, use_case, proposed_solution,
            alternatives_considered, user
        )
    elif action == "add_comment":
        if not issue_number or not body:
            raise ToolError("issue_number and body are required for add_comment")
        return github_add_comment(project_name, issue_number, body, user)
    elif action == "get_labels":
        return github_get_labels(project_name, user)
    else:
        raise ToolError(f"Unknown action: {action}")

def github_manage_code(
    action: str,
    project_name: str,
    branch: str = None,
    limit: int = 10,
    branch_name: str = None,
    from_ref: str = "main",
    title: str = None,
    body: str = None,
    head: str = None,
    base: str = "main",
    user=None
) -> str:
    """Consolidated tool for managing GitHub repo and code changes."""
    if action == "get_info":
        return github_get_repo_info(project_name, user)
    elif action == "latest_changes":
        return github_get_latest_changes(project_name, branch, limit, user)
    elif action == "list_branches":
        return github_list_branches(project_name, user)
    elif action == "create_branch":
        if not branch_name:
            raise ToolError("branch_name is required for create_branch")
        return github_create_branch(project_name, branch_name, from_ref, user)
    elif action == "create_pr":
        if not title or not body or not head:
            raise ToolError("title, body, and head are required for create_pr")
        return github_create_pull_request(project_name, title, body, head, base, user)
    else:
        raise ToolError(f"Unknown action: {action}")


# =============================================================================
# Tool 14: skills_list
# =============================================================================

def skills_list(
    tags: Optional[List[str]] = None,
    curated_only: bool = False,
    user=None
) -> str:
    """
    List all available skills with optional filtering.

    Returns global skills plus the authenticated user's personal skills.

    Args:
        tags: Optional list of tags to filter by
        curated_only: If True, only return curated skills
        user: Django User object (used to include personal skills)

    Returns:
        Formatted string with skill list

    Raises:
        ToolError: If listing fails
    """
    try:
        service = SkillService()
        skills = service.list_skills(tags=tags, curated_only=curated_only, user=user)

        if not skills.exists():
            filter_desc = ""
            if tags:
                filter_desc += f" with tags: {', '.join(tags)}"
            if curated_only:
                filter_desc += " (curated only)"
            return f"No skills found{filter_desc}."

        result_parts = ["Available Skills:", "=" * 50]

        for skill in skills:
            curated_marker = " ⭐" if skill.is_curated else ""
            personal_marker = " [Personal]" if skill.scope == 'personal' else ""
            tags_str = f" [{', '.join(skill.tags)}]" if skill.tags else ""
            result_parts.append(
                f"\n{skill.name}{curated_marker}{personal_marker}{tags_str}\n"
                f"  {skill.description}\n"
                f"  Usage: {skill.usage_count} | Tools: {len(skill.allowed_tools)}"
            )

        result_parts.append(f"\nTotal: {skills.count()} skills")
        return "\n".join(result_parts)

    except Exception as e:
        logger.error(f"Skills list error: {e}")
        raise ToolError(f"Failed to list skills: {str(e)}")


# =============================================================================
# Tool 14: skills_get
# =============================================================================

def skills_get(
    name: str,
    user=None
) -> str:
    """
    Get a skill by its exact name with full details.

    Returns the skill if it's global or if it's the user's personal skill.
    Personal skills shadow global skills of the same name.

    Args:
        name: Skill name
        user: Django User object (used to access personal skills)

    Returns:
        Formatted string with skill details and instructions

    Raises:
        ToolError: If skill not found or retrieval fails
    """
    try:
        service = SkillService()
        skill = service.get_skill_by_name(name, user=user)

        if not skill:
            return f"Skill not found: {name}"

        # Increment usage count
        skill.increment_usage()

        result_parts = [
            f"Skill: {skill.name}",
            "=" * 50,
            f"\nDescription: {skill.description}",
            f"\nCurated: {'Yes ⭐' if skill.is_curated else 'No'}",
            f"Usage Count: {skill.usage_count}",
        ]

        if skill.tags:
            result_parts.append(f"Tags: {', '.join(skill.tags)}")

        if skill.allowed_tools:
            result_parts.append(f"Allowed Tools: {', '.join(skill.allowed_tools)}")

        result_parts.append(f"\n{'=' * 50}\nInstructions:\n{'=' * 50}\n")
        result_parts.append(skill.instructions)

        if skill.context_files:
            result_parts.append(f"\n{'=' * 50}\nContext Files ({len(skill.context_files)}):")
            for filename in skill.context_files.keys():
                result_parts.append(f"  - {filename}")

        return "\n".join(result_parts)

    except Exception as e:
        logger.error(f"Skills get error: {e}")
        raise ToolError(f"Failed to get skill: {str(e)}")


# =============================================================================
# Tool 15: skills_search
# =============================================================================

def skills_search(
    query: str,
    limit: int = 5,
    user=None
) -> str:
    """
    Search for skills by name, description, or tags.

    Includes the authenticated user's personal skills in results.
    Personal skills are marked with [Personal].

    Args:
        query: Search query string
        limit: Maximum number of results (default: 5)
        user: Django User object (used to include personal skills)

    Returns:
        Formatted string with matching skills

    Raises:
        ToolError: If search fails
    """
    try:
        service = SkillService()
        skills = service.search_skills(query, limit=min(limit, 20), user=user)

        if not skills:
            return f"No skills found matching: {query}"

        result_parts = [f"Skills matching '{query}':", "=" * 50]

        for skill in skills:
            curated_marker = " ⭐" if skill.is_curated else ""
            personal_marker = " [Personal]" if skill.scope == 'personal' else ""
            tags_str = f" [{', '.join(skill.tags)}]" if skill.tags else ""
            result_parts.append(
                f"\n{skill.name}{curated_marker}{personal_marker}{tags_str}\n"
                f"  {skill.description}"
            )

        result_parts.append(f"\nFound: {len(skills)} skills")
        return "\n".join(result_parts)

    except Exception as e:
        logger.error(f"Skills search error: {e}")
        raise ToolError(f"Failed to search skills: {str(e)}")


# =============================================================================
# Tool 16: skills_sync
# =============================================================================

def skills_sync(
    user=None
) -> str:
    """
    Sync skills from the configured GitHub repository.

    This is an admin-only operation that fetches SKILL.md files
    from the skills repository and updates the database.

    Args:
        user: Django User object (must be superuser)

    Returns:
        Formatted string with sync results

    Raises:
        ToolError: If sync fails or user lacks permission
    """
    # Check admin permission
    if not user or not user.is_authenticated:
        raise ToolError("Authentication required for skill sync")

    if not user.is_superuser:
        raise ToolError("Skill sync requires administrator privileges")

    try:
        service = SkillService()
        synced_skills = service.sync_from_github()

        if not synced_skills:
            return "Sync completed but no skills were found or updated."

        result_parts = [
            "Skills Sync Complete!",
            "=" * 50,
            f"\nSynced {len(synced_skills)} skills:\n"
        ]

        for skill in synced_skills:
            result_parts.append(f"  - {skill.name}: {skill.description[:50]}...")

        return "\n".join(result_parts)

    except SkillSyncError as e:
        raise ToolError(str(e))
    except Exception as e:
        logger.error(f"Skills sync error: {e}")
        raise ToolError(f"Failed to sync skills: {str(e)}")


# =============================================================================
# Tool 17: skills_import
# =============================================================================

def skills_import(
    content: str,
    user=None
) -> str:
    """
    Import a skill from SKILL.md formatted content.

    The content should follow the SKILL.md format with YAML frontmatter
    between --- markers, followed by markdown instructions.

    SKILL.md Format:
    ---
    name: skill-name
    description: Brief description of what the skill does
    allowed-tools:
      - semantic_code_search
      - read_file_from_chunks
    tags:
      - code-quality
      - review
    ---
    # Instructions

    Full instructions for the AI agent...

    Args:
        content: SKILL.md formatted content string
        user: Django User object

    Returns:
        Formatted string with import result

    Raises:
        ToolError: If import fails or validation errors occur
    """
    if not user or not user.is_authenticated:
        raise ToolError("Authentication required for skill import")

    if not content or not content.strip():
        raise ToolError("No content provided. Please provide SKILL.md formatted content.")

    try:
        service = SkillService()

        # Parse the SKILL.md content
        try:
            skill_data = service.parse_skill_md(content)
        except ValueError as e:
            raise ToolError(f"Invalid SKILL.md format: {str(e)}")

        # Validate required fields
        if not skill_data.get('name'):
            raise ToolError("Skill name is required in the YAML frontmatter")
        if not skill_data.get('description'):
            raise ToolError("Skill description is required in the YAML frontmatter")
        if not skill_data.get('instructions'):
            raise ToolError("Skill instructions are required (markdown content after frontmatter)")

        # Check for existing skill with same name
        existing = Skill.objects.filter(name=skill_data['name']).first()
        if existing:
            # Only allow update if user owns it or is superuser
            if existing.created_by != user and not user.is_superuser:
                raise ToolError(
                    f"Skill '{skill_data['name']}' already exists and belongs to another user. "
                    "Choose a different name or contact the skill owner."
                )

        # Create or update the skill
        skill, created = Skill.objects.update_or_create(
            name=skill_data['name'],
            defaults={
                'description': skill_data['description'],
                'instructions': skill_data['instructions'],
                'allowed_tools': skill_data.get('allowed_tools', []),
                'tags': skill_data.get('tags', []),
                'created_by': user if created else (existing.created_by if existing else user),
                'is_active': True,
            }
        )

        action = "Created" if created else "Updated"
        result_parts = [
            f"Skill {action} Successfully!",
            "=" * 50,
            f"\nName: {skill.name}",
            f"Description: {skill.description}",
        ]

        if skill.tags:
            result_parts.append(f"Tags: {', '.join(skill.tags)}")
        if skill.allowed_tools:
            result_parts.append(f"Allowed Tools: {', '.join(skill.allowed_tools)}")

        result_parts.append(f"\nThe skill is now available for use in the Chat interface.")

        return "\n".join(result_parts)

    except ToolError:
        raise
    except Exception as e:
        logger.error(f"Skills import error: {e}")
        raise ToolError(f"Failed to import skill: {str(e)}")


# =============================================================================
# Tool 18: skills_discover
# =============================================================================

def skills_discover(
    repo_url: str,
    branch: str = 'main',
    import_skills: list = None,
    scope: str = 'personal',
    user=None
) -> str:
    """
    Discover and optionally import skills from an external GitHub repository.

    Two-step workflow:
    1. Call without import_skills to list available skills in the repo
    2. Call again with import_skills to import selected skills

    Args:
        repo_url: GitHub repository URL
        branch: Branch to scan (default: 'main')
        import_skills: Optional list of skill names to import
        scope: 'personal' (default) or 'global' (admin only)
        user: Django User object

    Returns:
        Formatted string with discovery or import results

    Raises:
        ToolError: If authentication fails, repo is inaccessible, or import errors occur
    """
    if not user or not user.is_authenticated:
        raise ToolError("Authentication required for skill discovery")

    if scope == 'global' and not user.is_superuser:
        raise ToolError("Only administrators can import skills to the global scope")

    # Get user's GitHub token if available (for private repos)
    token = None
    try:
        if hasattr(user, 'github_settings') and user.github_settings.github_token:
            token = user.github_settings.github_token
    except Exception:
        pass

    try:
        service = SkillService()

        if not import_skills:
            # Discovery mode: list available skills
            available = service.list_skills_from_external_repo(repo_url, branch, token)

            if not available:
                return f"No skills found in {repo_url} (branch: {branch}).\n\nMake sure the repository has a 'skills/' directory with subdirectories containing SKILL.md files."

            result_parts = [
                f"Found {len(available)} skill(s) in {repo_url} (branch: {branch})",
                "=" * 60,
                ""
            ]

            for i, skill in enumerate(available, 1):
                result_parts.append(f"{i}. {skill['name']}")
                result_parts.append(f"   {skill['description']}")
                if skill.get('tags'):
                    result_parts.append(f"   Tags: {', '.join(skill['tags'])}")
                result_parts.append("")

            result_parts.append("To import skills, call this tool again with the import_skills parameter set to a list of skill names.")

            return "\n".join(result_parts)
        else:
            # Import mode: import selected skills
            results = service.import_skills_from_external_repo(
                repo_url=repo_url,
                skill_names=import_skills,
                branch=branch,
                token=token,
                user=user,
                scope=scope
            )

            result_parts = [
                f"Import Results ({scope} scope)",
                "=" * 50,
            ]

            if results['imported']:
                result_parts.append(f"\nImported ({len(results['imported'])}):")
                for name in results['imported']:
                    result_parts.append(f"  + {name}")

            if results['skipped']:
                result_parts.append(f"\nNot found ({len(results['skipped'])}):")
                for name in results['skipped']:
                    result_parts.append(f"  - {name}")

            if results['errors']:
                result_parts.append(f"\nErrors ({len(results['errors'])}):")
                for err in results['errors']:
                    result_parts.append(f"  ! {err}")

            if results['imported']:
                result_parts.append(f"\nImported skills are now available in the Chat interface.")

            return "\n".join(result_parts)

    except SkillSyncError as e:
        raise ToolError(str(e))
    except ToolError:
        raise
    except Exception as e:
        logger.error(f"Skills discover error: {e}")
        raise ToolError(f"Failed to discover/import skills: {str(e)}")


# =============================================================================
# Tool 19: skills_activate
# =============================================================================

def skills_activate(
    name: str,
    user=None
) -> str:
    """
    Activate a skill for the current conversation.

    This tool retrieves a skill's full instructions and returns them in a format
    that tells Claude to follow those instructions for the remainder of the conversation.
    Use this when you want to "become" a specific skill persona.

    Example usage in Claude Desktop:
      User: "Use the code-review-coach skill to review my code"
      Claude: [calls skills_activate with name="code-review-coach"]
      Claude: [follows the returned instructions for code review]

    Args:
        name: Exact name of the skill to activate (e.g., "code-review-coach")
        user: Django User object

    Returns:
        Formatted skill activation prompt with full instructions

    Raises:
        ToolError: If skill not found or access denied
    """
    if not user or not user.is_authenticated:
        raise ToolError("Authentication required")

    try:
        # Personal skills take precedence over global skills of the same name
        skill = None

        # First try to find user's personal version
        personal_candidate = Skill.objects.filter(
            name=name, scope='personal', created_by=user, is_active=True
        ).first()

        if personal_candidate:
            if not user.is_superuser and personal_candidate.is_hidden:
                personal_candidate = None
            else:
                skill = personal_candidate

        # Fall back to global skill
        if not skill:
            global_filters = {'name': name, 'is_active': True, 'scope': 'global'}
            if not user.is_superuser:
                global_filters['is_hidden'] = False
            skill = Skill.objects.filter(**global_filters).first()

        if not skill:
            # Provide helpful suggestions from accessible skills
            base_q = Q(is_active=True) & (
                Q(scope='global') | Q(scope='personal', created_by=user)
            )
            similar = Skill.objects.filter(base_q).filter(
                name__icontains=name.split('-')[0] if '-' in name else name[:4]
            )
            if not user.is_superuser:
                similar = similar.filter(is_hidden=False)
            similar = similar[:5]

            if similar.exists():
                suggestions = ", ".join([s.name for s in similar])
                raise ToolError(f"Skill '{name}' not found. Did you mean: {suggestions}?")
            else:
                raise ToolError(f"Skill '{name}' not found. Use skills_list or skills_search to find available skills.")

        # Track usage
        usage, created = SkillUsage.objects.get_or_create(user=user, skill=skill)
        if not created:
            usage.increment()
        skill.increment_usage()

        # Build the activation response
        tools_section = ""
        if skill.allowed_tools:
            tools_section = f"""
## Recommended Tools
When executing this skill, prefer using these tools:
{chr(10).join(f'- {tool}' for tool in skill.allowed_tools)}
"""

        personal_note = ""
        if skill.scope == 'personal':
            personal_note = "\n> **Note:** This is your personal version of this skill.\n"

        activation_response = f"""# SKILL ACTIVATED: {skill.name}

You are now operating as **{skill.name}**.
{personal_note}
{skill.description}

---

## Instructions

{skill.instructions}
{tools_section}
---

**Important:** Follow the above instructions for all subsequent messages in this conversation until the user asks you to deactivate this skill or activate a different one.

Ready to assist as {skill.name}. How can I help you?"""

        return activation_response

    except ToolError:
        raise
    except Exception as e:
        logger.error(f"Skills activate error: {e}")
        raise ToolError(f"Failed to activate skill: {str(e)}")


# =============================================================================
# Job Management Tools (Tools 20-21)
# =============================================================================

from django.utils import timezone
from projects.utils import (
    trigger_indexer_job,
    stop_indexer_job,
    check_and_update_project_status,
    validate_elasticsearch_config,
)
from projects.models import JobRun


def _resolve_project_for_job(user, project=None, project_id=None, require_write_access=False):
    """
    Resolve a project by name or ID with access control for job operations.

    Args:
        user: Django User object
        project: Project name (case-insensitive)
        project_id: Project ID
        require_write_access: If True, only owner/superuser can access

    Returns:
        PathfinderProject object

    Raises:
        ToolError: If project not found, access denied, or write access required but user is shared
    """
    if not user or not user.is_authenticated:
        raise ToolError("Authentication required")

    if not project and not project_id:
        raise ToolError("Either 'project' (name) or 'project_id' is required")

    try:
        if project_id:
            proj = PathfinderProject.objects.get(pk=project_id)
        else:
            # Case-insensitive name lookup
            proj = PathfinderProject.objects.get(name__iexact=project)
    except PathfinderProject.DoesNotExist:
        identifier = project_id if project_id else project
        raise ToolError(
            f"Project '{identifier}' not found. "
            f"Use job_status(action='list') to see available projects."
        )

    # Check access
    is_owner = proj.user == user
    is_shared = user in proj.shared_with.all()
    is_superuser = user.is_superuser

    if not (is_owner or is_shared or is_superuser):
        raise ToolError(
            f"Access denied to project '{proj.name}'. "
            f"You don't have permission to access this project."
        )

    # Check write access for shared users
    if require_write_access and is_shared and not is_owner and not is_superuser:
        raise ToolError(
            f"Read-only access to project '{proj.name}'. "
            f"Shared users cannot start, stop, or modify jobs. "
            f"Contact the project owner ({proj.user.username}) for write access."
        )

    return proj


def _get_job_logs(project, tail=100):
    """
    Fetch logs from K8s or Docker for a project.

    Args:
        project: PathfinderProject object
        tail: Number of lines to return

    Returns:
        List of log entry dicts with timestamp, level, message
    """
    import docker
    from kubernetes import client, config as k8s_config

    logs = []

    try:
        # Try Kubernetes first
        try:
            k8s_config.load_incluster_config()
        except:
            try:
                k8s_config.load_kube_config()
            except:
                # Fall back to Docker
                docker_client = docker.from_env()
                containers = docker_client.containers.list(
                    all=True,
                    filters={"label": [f"app=indexer-cli", f"project-id={project.id}"]}
                )

                if containers:
                    container = containers[0]
                    log_output = container.logs(tail=tail).decode('utf-8')
                    for line in log_output.split('\n'):
                        if line.strip():
                            logs.append({
                                'timestamp': timezone.now().isoformat(),
                                'level': 'INFO',
                                'message': line.strip()
                            })
                return logs

        # K8s logs
        v1 = client.CoreV1Api()
        namespace = "code-pathfinder"
        label_selector = f"app=indexer-cli,project-id={project.id}"

        pods = v1.list_namespaced_pod(namespace=namespace, label_selector=label_selector)

        if pods.items:
            pod = pods.items[0]
            log_output = v1.read_namespaced_pod_log(
                name=pod.metadata.name,
                namespace=namespace,
                tail_lines=tail
            )
            for line in log_output.split('\n'):
                if line.strip():
                    logs.append({
                        'timestamp': timezone.now().isoformat(),
                        'level': 'INFO',
                        'message': line.strip()
                    })

    except Exception as e:
        logger.warning(f"Failed to fetch logs: {e}")
        logs.append({
            'timestamp': timezone.now().isoformat(),
            'level': 'WARNING',
            'message': f'Could not fetch logs: {str(e)}'
        })

    return logs


def _get_index_stats(project):
    """Get Elasticsearch index statistics for a project."""
    try:
        es = get_es_client()
        if not es or not project.custom_index_name:
            return None

        stats = es.indices.stats(index=project.custom_index_name)
        index_stats = stats['indices'].get(project.custom_index_name, {})
        primaries = index_stats.get('primaries', {})

        return {
            'document_count': primaries.get('docs', {}).get('count', 0),
            'index_size_bytes': primaries.get('store', {}).get('size_in_bytes', 0),
            'index_size_mb': round(primaries.get('store', {}).get('size_in_bytes', 0) / (1024 * 1024), 2),
        }
    except Exception as e:
        logger.warning(f"Failed to get index stats: {e}")
        return None


def job_manage(
    action: str,
    project: Optional[str] = None,
    project_id: Optional[int] = None,
    project_ids: Optional[List[int]] = None,
    repository_url: Optional[str] = None,
    name: Optional[str] = None,
    branch: Optional[str] = None,
    clean_index: bool = False,
    concurrency: Optional[int] = None,
    auto_start: bool = False,
    github_token: Optional[str] = None,
    user=None,
    **kwargs
) -> str:
    """
    Manage CodePathFinder indexing jobs.

    This tool allows you to start, stop, reset, create, update, and delete
    indexing jobs for projects.

    Args:
        action: The action to perform (start, stop, reset, create, update, delete, bulk_start, bulk_stop)
        project: Project name (for single-project actions)
        project_id: Project ID (alternative to project name)
        project_ids: List of project IDs (for bulk actions)
        repository_url: GitHub repository URL (for create action)
        name: Project name (for create/update actions)
        branch: Git branch to index
        clean_index: Delete existing index before starting
        concurrency: Number of parallel workers (1-16)
        auto_start: Start indexing immediately after create
        github_token: GitHub token for private repositories
        user: Django User object

    Returns:
        Formatted result string

    Raises:
        ToolError: If operation fails
    """
    if not user or not user.is_authenticated:
        raise ToolError("Authentication required")

    # =========================================================================
    # ACTION: start
    # =========================================================================
    if action == "start":
        proj = _resolve_project_for_job(user, project, project_id, require_write_access=True)

        # Check if already running
        if proj.status in ['running', 'watching']:
            raise ToolError(
                f"Project '{proj.name}' already has a running job (status: {proj.status}). "
                f"Use job_manage(action='stop', project='{proj.name}') to stop it first, "
                f"or job_status(action='status', project='{proj.name}') to check progress."
            )

        # Validate Elasticsearch
        is_valid, error_msg = validate_elasticsearch_config()
        if not is_valid:
            raise ToolError(
                f"Elasticsearch not configured: {error_msg} "
                "Configure Elasticsearch in Settings → System before starting jobs."
            )

        # Apply options
        if clean_index:
            proj.clean_index = True
        if branch:
            proj.branch = branch
        if concurrency:
            if concurrency < 1 or concurrency > 16:
                raise ToolError("Concurrency must be between 1 and 16")
            proj.concurrency = concurrency
        proj.save()

        # Start the job
        success, msg = trigger_indexer_job(proj)
        if not success:
            raise ToolError(f"Failed to start job: {msg}")

        proj.refresh_from_db()

        return f"""=== Job Started ===
Project: {proj.name} (ID: {proj.id})
Status: {proj.status}
Started at: {timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC')}

Options:
  - Branch: {proj.branch or 'main'}
  - Clean index: {proj.clean_index}
  - Concurrency: {proj.concurrency}

Next steps:
  - Check status: job_status(action="status", project="{proj.name}")
  - View logs: job_status(action="logs", project="{proj.name}")
  - Stop job: job_manage(action="stop", project="{proj.name}")"""

    # =========================================================================
    # ACTION: stop
    # =========================================================================
    elif action == "stop":
        proj = _resolve_project_for_job(user, project, project_id, require_write_access=True)

        # Check if running
        if proj.status not in ['running', 'watching']:
            raise ToolError(
                f"Project '{proj.name}' has no running job (status: {proj.status}). "
                f"Use job_manage(action='start', project='{proj.name}') to start indexing."
            )

        previous_status = proj.status

        # Stop the job
        success, msg = stop_indexer_job(proj)

        if not success:
            if 'not found' in msg.lower():
                proj.status = 'stopped'
                proj.save()
            else:
                raise ToolError(f"Failed to stop job: {msg}")

        proj.refresh_from_db()

        return f"""=== Job Stopped ===
Project: {proj.name} (ID: {proj.id})
Previous status: {previous_status}
Current status: {proj.status}

Next steps:
  - Restart: job_manage(action="start", project="{proj.name}")
  - Check status: job_status(action="status", project="{proj.name}")
  - View history: job_status(action="history", project="{proj.name}")"""

    # =========================================================================
    # ACTION: reset
    # =========================================================================
    elif action == "reset":
        proj = _resolve_project_for_job(user, project, project_id, require_write_access=True)

        if proj.status in ['running', 'watching']:
            raise ToolError(
                f"Cannot reset project '{proj.name}' while it's running. "
                f"Use job_manage(action='stop', project='{proj.name}') first."
            )

        previous_status = proj.status
        proj.status = 'pending'
        proj.save()

        return f"""=== Project Reset ===
Project: {proj.name} (ID: {proj.id})
Previous status: {previous_status}
Current status: pending

The project is now ready to be indexed again.

Next steps:
  - Start indexing: job_manage(action="start", project="{proj.name}")
  - Start with clean: job_manage(action="start", project="{proj.name}", clean_index=true)"""

    # =========================================================================
    # ACTION: create
    # =========================================================================
    elif action == "create":
        if not repository_url:
            raise ToolError(
                "repository_url is required to create a project. "
                "Example: job_manage(action='create', repository_url='https://github.com/org/repo', name='my-repo')"
            )

        # Generate name from URL if not provided
        if not name:
            # Extract repo name from URL
            import re
            match = re.search(r'github\.com/[^/]+/([^/]+?)(?:\.git)?$', repository_url)
            if match:
                name = match.group(1)
            else:
                raise ToolError("Could not extract project name from URL. Please provide a 'name' parameter.")

        # Check if project with same name exists
        if PathfinderProject.objects.filter(name__iexact=name, user=user).exists():
            raise ToolError(
                f"Project '{name}' already exists. "
                "Choose a different name or use job_manage(action='update', ...) to modify it."
            )

        # Create project
        proj = PathfinderProject.objects.create(
            user=user,
            name=name,
            repository_url=repository_url,
            branch=branch or 'main',
            concurrency=concurrency or 4,
            status='pending',
            is_enabled=True,
        )

        # Set GitHub token if provided (stored encrypted)
        if github_token:
            proj.github_token = github_token
            proj.save()

        result = f"""=== Project Created ===
Project: {proj.name} (ID: {proj.id})
Repository: {proj.repository_url}
Branch: {proj.branch}
Status: pending

"""
        # Auto-start if requested
        if auto_start:
            is_valid, error_msg = validate_elasticsearch_config()
            if is_valid:
                success, msg = trigger_indexer_job(proj)
                if success:
                    proj.refresh_from_db()
                    result += f"""Indexing started automatically!

Next steps:
  - Check status: job_status(action="status", project="{proj.name}")
  - View logs: job_status(action="logs", project="{proj.name}")"""
                else:
                    result += f"""Auto-start failed: {msg}

Next steps:
  - Start manually: job_manage(action="start", project="{proj.name}")"""
            else:
                result += f"""Auto-start skipped (Elasticsearch not configured).

Next steps:
  - Configure Elasticsearch in Settings → System
  - Then start: job_manage(action="start", project="{proj.name}")"""
        else:
            result += f"""Next steps:
  - Start indexing: job_manage(action="start", project="{proj.name}")
  - Update settings: job_manage(action="update", project="{proj.name}", branch="develop")"""

        return result

    # =========================================================================
    # ACTION: update
    # =========================================================================
    elif action == "update":
        proj = _resolve_project_for_job(user, project, project_id, require_write_access=True)

        updates = []
        if name and name != proj.name:
            proj.name = name
            updates.append(f"name: {name}")
        if branch and branch != proj.branch:
            proj.branch = branch
            updates.append(f"branch: {branch}")
        if concurrency and concurrency != proj.concurrency:
            if concurrency < 1 or concurrency > 16:
                raise ToolError("Concurrency must be between 1 and 16")
            proj.concurrency = concurrency
            updates.append(f"concurrency: {concurrency}")

        if not updates:
            return f"No changes made to project '{proj.name}'. Provide name, branch, or concurrency to update."

        proj.save()

        return f"""=== Project Updated ===
Project: {proj.name} (ID: {proj.id})

Updated:
  - {chr(10) + '  - '.join(updates)}

Current settings:
  - Branch: {proj.branch}
  - Concurrency: {proj.concurrency}
  - Status: {proj.status}"""

    # =========================================================================
    # ACTION: delete
    # =========================================================================
    elif action == "delete":
        proj = _resolve_project_for_job(user, project, project_id, require_write_access=True)

        # Only owner or superuser can delete
        if proj.user != user and not user.is_superuser:
            raise ToolError(
                f"Only the project owner ({proj.user.username}) can delete this project."
            )

        project_name = proj.name
        project_id = proj.id

        # Stop any running job first
        if proj.status in ['running', 'watching']:
            stop_indexer_job(proj)

        # Delete Elasticsearch index
        try:
            if proj.custom_index_name:
                es = get_es_client()
                if es:
                    es.indices.delete(index=proj.custom_index_name, ignore=[404])
        except Exception as e:
            logger.warning(f"Failed to delete index: {e}")

        # Delete the project
        proj.delete()

        return f"""=== Project Deleted ===
Project: {project_name} (ID: {project_id})

The project and its Elasticsearch index have been deleted.

To create a new project:
  job_manage(action="create", repository_url="https://github.com/org/repo", name="my-project")"""

    # =========================================================================
    # ACTION: bulk_start
    # =========================================================================
    elif action == "bulk_start":
        if not project_ids:
            raise ToolError(
                "project_ids is required for bulk_start. "
                "Example: job_manage(action='bulk_start', project_ids=[1, 2, 3])"
            )

        # Validate Elasticsearch once
        is_valid, error_msg = validate_elasticsearch_config()
        if not is_valid:
            raise ToolError(f"Elasticsearch not configured: {error_msg}")

        results = []
        started = 0
        failed = 0

        for pid in project_ids:
            try:
                proj = _resolve_project_for_job(user, project_id=pid, require_write_access=True)

                if proj.status in ['running', 'watching']:
                    results.append(f"  • {proj.name} (ID: {pid}): Already running")
                    failed += 1
                    continue

                if clean_index:
                    proj.clean_index = True
                if branch:
                    proj.branch = branch
                if concurrency:
                    proj.concurrency = concurrency
                proj.save()

                success, msg = trigger_indexer_job(proj)
                if success:
                    results.append(f"  • {proj.name} (ID: {pid}): Started")
                    started += 1
                else:
                    results.append(f"  • {proj.name} (ID: {pid}): Failed - {msg}")
                    failed += 1

            except ToolError as e:
                results.append(f"  • ID {pid}: {str(e)}")
                failed += 1

        return f"""=== Bulk Start Results ===
Started: {started}/{len(project_ids)}
Failed: {failed}/{len(project_ids)}

Results:
{chr(10).join(results)}

Next steps:
  - Check status: job_status(action="list", status_filter="running")
  - Stop all: job_manage(action="bulk_stop", project_ids={project_ids})"""

    # =========================================================================
    # ACTION: bulk_stop
    # =========================================================================
    elif action == "bulk_stop":
        if not project_ids:
            raise ToolError(
                "project_ids is required for bulk_stop. "
                "Example: job_manage(action='bulk_stop', project_ids=[1, 2, 3])"
            )

        results = []
        stopped = 0
        failed = 0

        for pid in project_ids:
            try:
                proj = _resolve_project_for_job(user, project_id=pid, require_write_access=True)

                if proj.status not in ['running', 'watching']:
                    results.append(f"  • {proj.name} (ID: {pid}): Not running ({proj.status})")
                    failed += 1
                    continue

                success, msg = stop_indexer_job(proj)
                if success or 'not found' in msg.lower():
                    proj.status = 'stopped'
                    proj.save()
                    results.append(f"  • {proj.name} (ID: {pid}): Stopped")
                    stopped += 1
                else:
                    results.append(f"  • {proj.name} (ID: {pid}): Failed - {msg}")
                    failed += 1

            except ToolError as e:
                results.append(f"  • ID {pid}: {str(e)}")
                failed += 1

        return f"""=== Bulk Stop Results ===
Stopped: {stopped}/{len(project_ids)}
Failed: {failed}/{len(project_ids)}

Results:
{chr(10).join(results)}

Next steps:
  - Check status: job_status(action="list")
  - Restart all: job_manage(action="bulk_start", project_ids={project_ids})"""

    else:
        raise ToolError(
            f"Unknown action: {action}. "
            "Valid actions: start, stop, reset, create, update, delete, bulk_start, bulk_stop"
        )


def job_status(
    action: str,
    project: Optional[str] = None,
    project_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    tail: int = 100,
    page: int = 1,
    page_size: int = 20,
    user=None,
    **kwargs
) -> str:
    """
    Get status and information about CodePathFinder indexing jobs.

    Args:
        action: The type of information to retrieve (status, list, details, logs, history)
        project: Project name (required for status, details, logs, history)
        project_id: Project ID (alternative to project name)
        status_filter: Filter by status (for list action)
        tail: Number of log lines (for logs action)
        page: Page number for pagination
        page_size: Items per page
        user: Django User object

    Returns:
        Formatted status information

    Raises:
        ToolError: If operation fails
    """
    if not user or not user.is_authenticated:
        raise ToolError("Authentication required")

    # =========================================================================
    # ACTION: status
    # =========================================================================
    if action == "status":
        proj = _resolve_project_for_job(user, project, project_id)

        # Update status if running
        if proj.status in ['running', 'watching']:
            try:
                check_and_update_project_status(proj)
                proj.refresh_from_db()
            except Exception as e:
                logger.warning(f"Failed to update status: {e}")

        # Get index stats
        stats = _get_index_stats(proj)
        stats_str = ""
        if stats:
            stats_str = f"""
Index Statistics:
  - Documents: {stats['document_count']:,}
  - Size: {stats['index_size_mb']} MB"""

        status_emoji = {
            'pending': '⏳',
            'running': '🔄',
            'completed': '✅',
            'failed': '❌',
            'watching': '👀',
            'stopped': '⏹️',
            'stalled': '⚠️',
            'error': '❌',
        }.get(proj.status, '❓')

        # Build progress block for running/stalled jobs
        progress_str = ""
        if proj.status in ['running', 'watching'] or proj.current_stage:
            stage = proj.current_stage or proj.status
            pct = proj.progress_pct

            # ASCII progress bar (20 chars wide)
            filled = round(pct / 5)
            bar = '█' * filled + '░' * (20 - filled)
            progress_str = f"""
Indexing Progress:
  Stage: {stage}
  [{bar}] {pct}%"""
            if proj.total_files:
                progress_str += f"\n  Files: {proj.total_files:,} total"
            if proj.files_processed:
                progress_str += f" / ~{proj.files_processed:,} docs indexed"
            if proj.stage_message:
                progress_str += f"\n  ⚠ {proj.stage_message}"

        next_steps = []
        if proj.status in ['pending', 'completed', 'failed', 'stopped']:
            next_steps.append(f'job_manage(action="start", project="{proj.name}")')
        if proj.status in ['running', 'watching']:
            next_steps.append(f'job_manage(action="stop", project="{proj.name}")')
            next_steps.append(f'job_status(action="logs", project="{proj.name}")')
        if proj.status == 'failed':
            next_steps.append(f'job_manage(action="reset", project="{proj.name}")')
        if proj.status in ['completed', 'watching']:
            next_steps.append(f'semantic_code_search(query="...", projects=["{proj.name}"])')

        return f"""=== Project Status ===
{status_emoji} {proj.name} (ID: {proj.id})

Status: {proj.status}
Repository: {proj.repository_url}
Branch: {proj.branch or 'main'}
Enabled: {proj.is_enabled}
{progress_str}{stats_str}

Configuration:
  - Concurrency: {proj.concurrency}
  - Clean index: {proj.clean_index}
  - Watch mode: {proj.watch_mode}

Next steps:
  - {chr(10) + '  - '.join(next_steps)}"""

    # =========================================================================
    # ACTION: list
    # =========================================================================
    elif action == "list":
        # Get accessible projects
        if user.is_superuser:
            queryset = PathfinderProject.objects.all()
        else:
            queryset = PathfinderProject.objects.filter(
                Q(user=user) | Q(shared_with=user)
            ).distinct()

        # Apply status filter
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        # Order by status then name
        queryset = queryset.order_by('status', 'name')

        total_count = queryset.count()

        # Paginate
        page_size = min(page_size, 100)
        start = (page - 1) * page_size
        end = start + page_size
        projects = list(queryset[start:end])

        if not projects:
            if status_filter:
                return f"No projects found with status '{status_filter}'."
            return "No projects found. Create one with: job_manage(action='create', repository_url='https://github.com/org/repo')"

        # Group by status
        status_groups = {}
        for proj in projects:
            if proj.status not in status_groups:
                status_groups[proj.status] = []
            status_groups[proj.status].append(proj)

        # Build output
        lines = [f"=== Projects ({total_count} total) ===\n"]

        status_order = ['running', 'watching', 'pending', 'completed', 'failed', 'stopped']
        status_emoji = {
            'pending': '⏳',
            'running': '🔄',
            'completed': '✅',
            'failed': '❌',
            'watching': '👀',
            'stopped': '⏹️',
        }

        for s in status_order:
            if s in status_groups:
                emoji = status_emoji.get(s, '')
                lines.append(f"{emoji} {s.title()} ({len(status_groups[s])}):")
                for proj in status_groups[s]:
                    stats = _get_index_stats(proj)
                    stats_str = ""
                    if stats and stats['document_count'] > 0:
                        stats_str = f" - {stats['document_count']:,} docs"
                    stage_str = ""
                    if proj.current_stage and s in ('running', 'watching'):
                        pct_str = f" {proj.progress_pct}%" if proj.progress_pct else ""
                        stage_str = f" [{proj.current_stage}{pct_str}]"
                        if proj.stage_message:
                            stage_str += f" ⚠ {proj.stage_message}"
                    lines.append(f"  • {proj.name} (ID: {proj.id}){stage_str}{stats_str}")
                lines.append("")

        # Pagination info
        total_pages = (total_count + page_size - 1) // page_size
        if total_pages > 1:
            lines.append(f"Page {page}/{total_pages}")
            if page < total_pages:
                lines.append(f"Next page: job_status(action='list', page={page + 1})")

        return "\n".join(lines)

    # =========================================================================
    # ACTION: details
    # =========================================================================
    elif action == "details":
        proj = _resolve_project_for_job(user, project, project_id)

        # Get index stats
        stats = _get_index_stats(proj)
        stats_str = "Not indexed yet"
        if stats:
            stats_str = f"{stats['document_count']:,} documents, {stats['index_size_mb']} MB"

        # Get last job run
        last_run = JobRun.objects.filter(project=proj).first()
        last_run_str = "Never"
        if last_run:
            last_run_str = f"{last_run.started_at.strftime('%Y-%m-%d %H:%M')} ({last_run.final_status})"

        return f"""=== Project Details ===
Name: {proj.name}
ID: {proj.id}
Status: {proj.status}
Enabled: {proj.is_enabled}

Repository:
  - URL: {proj.repository_url}
  - Branch: {proj.branch or 'main'}

Index:
  - Name: {proj.custom_index_name or 'Not created'}
  - Stats: {stats_str}

Configuration:
  - Concurrency: {proj.concurrency}
  - Clean index: {proj.clean_index}
  - Watch mode: {proj.watch_mode}
  - Pull before index: {proj.pull_before_index}

Metadata:
  - Owner: {proj.user.username}
  - Shared with: {', '.join([u.username for u in proj.shared_with.all()]) or 'Nobody'}
  - Created: {proj.created_at.strftime('%Y-%m-%d %H:%M')}
  - Updated: {proj.updated_at.strftime('%Y-%m-%d %H:%M')}
  - Last run: {last_run_str}"""

    # =========================================================================
    # ACTION: logs
    # =========================================================================
    elif action == "logs":
        proj = _resolve_project_for_job(user, project, project_id)

        tail = min(tail, 500)
        logs = _get_job_logs(proj, tail)

        if not logs:
            return f"""=== Logs for {proj.name} ===
No logs available.

The project may not have run yet, or logs have expired.
Status: {proj.status}"""

        log_lines = []
        for entry in logs:
            ts = entry.get('timestamp', '')[:19].replace('T', ' ')
            level = entry.get('level', 'INFO')
            msg = entry.get('message', '')
            log_lines.append(f"[{ts}] {level:5} {msg}")

        return f"""=== Logs for {proj.name} ===
Status: {proj.status}
Showing last {len(logs)} lines:

{chr(10).join(log_lines)}

{'[Log output truncated]' if len(logs) >= tail else ''}"""

    # =========================================================================
    # ACTION: history
    # =========================================================================
    elif action == "history":
        proj = _resolve_project_for_job(user, project, project_id)

        # Get job runs
        page_size = min(page_size, 100)
        start = (page - 1) * page_size
        end = start + page_size

        runs = JobRun.objects.filter(project=proj).order_by('-started_at')[start:end]
        total_runs = JobRun.objects.filter(project=proj).count()

        if not runs:
            return f"""=== Job History for {proj.name} ===
No job runs recorded yet.

Start indexing with: job_manage(action="start", project="{proj.name}")"""

        lines = [f"=== Job History for {proj.name} ==="]
        lines.append(f"Total runs: {total_runs}\n")

        for run in runs:
            duration = ""
            if run.duration_seconds:
                mins, secs = divmod(run.duration_seconds, 60)
                duration = f" ({mins}m {secs}s)"

            status_emoji = {
                'completed': '✅',
                'failed': '❌',
                'running': '🔄',
                'stopped': '⏹️',
            }.get(run.final_status, '❓')

            lines.append(f"{status_emoji} {run.started_at.strftime('%Y-%m-%d %H:%M')} - {run.final_status}{duration}")

            if run.options:
                opts = []
                if run.options.get('clean_index'):
                    opts.append("clean")
                if run.options.get('branch'):
                    opts.append(f"branch={run.options['branch']}")
                if opts:
                    lines.append(f"   Options: {', '.join(opts)}")

            if run.result:
                if run.result.get('files_indexed'):
                    lines.append(f"   Indexed: {run.result['files_indexed']} files")
                if run.result.get('documents_created'):
                    lines.append(f"   Documents: {run.result['documents_created']}")

            if run.error_message:
                lines.append(f"   Error: {run.error_message[:100]}...")

            lines.append("")

        # Pagination
        total_pages = (total_runs + page_size - 1) // page_size
        if total_pages > 1:
            lines.append(f"Page {page}/{total_pages}")
            if page < total_pages:
                lines.append(f"More: job_status(action='history', project='{proj.name}', page={page + 1})")

        return "\n".join(lines)

    else:
        raise ToolError(
            f"Unknown action: {action}. "
            "Valid actions: status, list, details, logs, history"
        )


# =============================================================================
# OTel Collection Tools
# =============================================================================

def otel_configure_collection(
    action: str,
    project: Optional[str] = None,
    project_id: Optional[int] = None,
    service_name: Optional[str] = None,
    collect_traces: Optional[bool] = None,
    collect_metrics: Optional[bool] = None,
    collect_logs: Optional[bool] = None,
    label: Optional[str] = None,
    index_prefix: Optional[str] = None,
    user=None,
    **kwargs
) -> str:
    """Configure OpenTelemetry collection for a project."""
    from projects.models import OtelCollectionSettings, ProjectAPIKey
    from core.models import SystemSettings

    proj = _resolve_project_for_job(user, project, project_id, require_write_access=(action != 'status'))

    if action == 'status':
        try:
            otel = proj.otel_settings
        except OtelCollectionSettings.DoesNotExist:
            return (
                f"OTel collection not configured for '{proj.name}'.\n"
                f"To enable: otel_configure_collection(action=\"enable\", project=\"{proj.name}\")"
            )
        sys_settings = SystemSettings.get_settings()
        key_count = proj.api_keys.filter(scope='otel', is_active=True).count()
        lines = [
            f"=== OTel Collection Status: {proj.name} ===",
            f"Enabled:         {otel.enabled}",
            f"Service name:    {otel.service_name}",
            f"Collect traces:  {otel.collect_traces}",
            f"Collect metrics: {otel.collect_metrics}",
            f"Collect logs:    {otel.collect_logs}",
            f"Traces index:    {otel.traces_index}",
            f"Metrics index:   {otel.metrics_index}",
            f"Logs index:      {otel.logs_index}",
            f"Active OTel API keys: {key_count}",
            f"Global collector enabled: {sys_settings.otel_collector_enabled}",
        ]
        if sys_settings.otel_collector_endpoint:
            lines.append(f"gRPC endpoint:   {sys_settings.otel_collector_endpoint}")
        if sys_settings.otel_collector_http_endpoint:
            lines.append(f"HTTP endpoint:   {sys_settings.otel_collector_http_endpoint}")
        return "\n".join(lines)

    elif action == 'enable':
        otel, created = OtelCollectionSettings.objects.get_or_create(project=proj)
        otel.enabled = True
        if service_name is not None:
            otel.service_name = service_name
        if collect_traces is not None:
            otel.collect_traces = collect_traces
        if collect_metrics is not None:
            otel.collect_metrics = collect_metrics
        if collect_logs is not None:
            otel.collect_logs = collect_logs
        if index_prefix is not None:
            otel.traces_index = f"traces-customer.{index_prefix}"
            otel.metrics_index = f"metrics-customer.{index_prefix}"
            otel.logs_index = f"logs-customer.{index_prefix}"
        otel.save()
        verb = "Configured and enabled" if created else "Enabled"
        return (
            f"=== OTel Collection {verb} ===\n"
            f"Project:         {proj.name}\n"
            f"Service name:    {otel.service_name}\n"
            f"Collect traces:  {otel.collect_traces}\n"
            f"Collect metrics: {otel.collect_metrics}\n"
            f"Collect logs:    {otel.collect_logs}\n"
            f"Traces index:    {otel.traces_index}\n"
            f"Metrics index:   {otel.metrics_index}\n"
            f"Logs index:      {otel.logs_index}\n\n"
            f"Next steps:\n"
            f"  - Generate an API key: otel_configure_collection(action=\"generate_key\", project=\"{proj.name}\")\n"
            f"  - Get onboarding config: otel_get_onboarding_config(project=\"{proj.name}\", format=\"env\")"
        )

    elif action == 'disable':
        try:
            otel = proj.otel_settings
        except OtelCollectionSettings.DoesNotExist:
            raise ToolError(f"OTel collection is not configured for '{proj.name}'.")
        otel.enabled = False
        otel.save()
        return f"OTel collection disabled for '{proj.name}'. Existing indices and data are preserved."

    elif action == 'update':
        try:
            otel = proj.otel_settings
        except OtelCollectionSettings.DoesNotExist:
            raise ToolError(
                f"OTel collection is not configured for '{proj.name}'. "
                f"Enable it first: otel_configure_collection(action=\"enable\", project=\"{proj.name}\")"
            )
        if service_name is not None:
            otel.service_name = service_name
        if collect_traces is not None:
            otel.collect_traces = collect_traces
        if collect_metrics is not None:
            otel.collect_metrics = collect_metrics
        if collect_logs is not None:
            otel.collect_logs = collect_logs
        if index_prefix is not None:
            otel.traces_index = f"traces-customer.{index_prefix}"
            otel.metrics_index = f"metrics-customer.{index_prefix}"
            otel.logs_index = f"logs-customer.{index_prefix}"
        otel.save()
        return (
            f"=== OTel Settings Updated: {proj.name} ===\n"
            f"Service name:    {otel.service_name}\n"
            f"Traces index:    {otel.traces_index}\n"
            f"Metrics index:   {otel.metrics_index}\n"
            f"Logs index:      {otel.logs_index}\n"
            f"Collect traces:  {otel.collect_traces}\n"
            f"Collect metrics: {otel.collect_metrics}\n"
            f"Collect logs:    {otel.collect_logs}"
        )

    elif action == 'generate_key':
        try:
            otel = proj.otel_settings
        except OtelCollectionSettings.DoesNotExist:
            raise ToolError(
                f"OTel collection is not configured for '{proj.name}'. "
                f"Enable it first: otel_configure_collection(action=\"enable\", project=\"{proj.name}\")"
            )
        if not otel.enabled:
            raise ToolError(
                f"OTel collection is disabled for '{proj.name}'. "
                f"Enable it first: otel_configure_collection(action=\"enable\", project=\"{proj.name}\")"
            )
        key_label = label or "OTel Collector"
        plain_key, hashed_key, prefix = ProjectAPIKey.generate_key()
        ProjectAPIKey.objects.create(
            project=proj,
            prefix=prefix,
            hashed_key=hashed_key,
            label=key_label,
            scope='otel',
        )
        return (
            f"=== OTel API Key Generated ===\n"
            f"Project: {proj.name}\n"
            f"Label:   {key_label}\n"
            f"Prefix:  {prefix}...\n\n"
            f"API Key (save this — it will NOT be shown again):\n"
            f"  {plain_key}\n\n"
            f"Use this key as a Bearer token in your OTLP exporter headers:\n"
            f"  Authorization: Bearer {plain_key}"
        )

    else:
        raise ToolError(
            f"Unknown action: {action}. "
            "Valid actions: enable, disable, update, generate_key, status"
        )


def _otel_env_config(otel, grpc_endpoint: str, http_endpoint: str) -> str:
    return (
        f"# OpenTelemetry Environment Variables for '{otel.project.name}'\n"
        f"export OTEL_SERVICE_NAME=\"{otel.service_name}\"\n"
        f"export OTEL_RESOURCE_ATTRIBUTES=\"cpf.project.id={otel.project.pk},cpf.project.name={otel.project.name}\"\n"
        f"export OTEL_EXPORTER_OTLP_ENDPOINT=\"{http_endpoint or grpc_endpoint or '<OTLP_ENDPOINT>'}\"\n"
        f"export OTEL_EXPORTER_OTLP_HEADERS=\"Authorization=Bearer <YOUR_OTEL_API_KEY>\"\n"
        f"export OTEL_EXPORTER_OTLP_PROTOCOL=\"http/protobuf\"\n\n"
        f"# Generate an API key: otel_configure_collection(action=\"generate_key\", project=\"{otel.project.name}\")"
    )


def _otel_python_config(otel, http_endpoint: str) -> str:
    endpoint = http_endpoint or '<OTLP_HTTP_ENDPOINT>'
    return (
        f"# Python OpenTelemetry SDK setup for '{otel.project.name}'\n"
        f"# pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http\n\n"
        f"from opentelemetry import trace\n"
        f"from opentelemetry.sdk.trace import TracerProvider\n"
        f"from opentelemetry.sdk.trace.export import BatchSpanProcessor\n"
        f"from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter\n"
        f"from opentelemetry.sdk.resources import Resource\n\n"
        f"resource = Resource.create({{\n"
        f"    \"service.name\": \"{otel.service_name}\",\n"
        f"    \"cpf.project.id\": \"{otel.project.pk}\",\n"
        f"    \"cpf.project.name\": \"{otel.project.name}\",\n"
        f"}})\n\n"
        f"exporter = OTLPSpanExporter(\n"
        f"    endpoint=\"{endpoint}/v1/traces\",\n"
        f"    headers={{\"Authorization\": \"Bearer <YOUR_OTEL_API_KEY>\"}},\n"
        f")\n\n"
        f"provider = TracerProvider(resource=resource)\n"
        f"provider.add_span_processor(BatchSpanProcessor(exporter))\n"
        f"trace.set_tracer_provider(provider)\n\n"
        f"# Generate an API key: otel_configure_collection(action=\"generate_key\", project=\"{otel.project.name}\")"
    )


def _otel_node_config(otel, http_endpoint: str) -> str:
    endpoint = http_endpoint or '<OTLP_HTTP_ENDPOINT>'
    return (
        f"// Node.js OpenTelemetry SDK setup for '{otel.project.name}'\n"
        f"// npm install @opentelemetry/sdk-node @opentelemetry/exporter-trace-otlp-http\n\n"
        f"const {{ NodeSDK }} = require('@opentelemetry/sdk-node');\n"
        f"const {{ OTLPTraceExporter }} = require('@opentelemetry/exporter-trace-otlp-http');\n"
        f"const {{ Resource }} = require('@opentelemetry/resources');\n\n"
        f"const sdk = new NodeSDK({{\n"
        f"  resource: new Resource({{\n"
        f"    'service.name': '{otel.service_name}',\n"
        f"    'cpf.project.id': '{otel.project.pk}',\n"
        f"    'cpf.project.name': '{otel.project.name}',\n"
        f"  }}),\n"
        f"  traceExporter: new OTLPTraceExporter({{\n"
        f"    url: '{endpoint}/v1/traces',\n"
        f"    headers: {{ Authorization: 'Bearer <YOUR_OTEL_API_KEY>' }},\n"
        f"  }}),\n"
        f"}});\n\n"
        f"sdk.start();\n\n"
        f"// Generate an API key: otel_configure_collection(action=\"generate_key\", project=\"{otel.project.name}\")"
    )


def _otel_collector_yaml(otel, sys_settings) -> str:
    grpc = sys_settings.otel_collector_endpoint or '<OTLP_GRPC_ENDPOINT>'
    return (
        f"# OTel Collector YAML for '{otel.project.name}'\n"
        f"# Place in your otel-collector-config.yaml\n\n"
        f"receivers:\n"
        f"  otlp:\n"
        f"    protocols:\n"
        f"      grpc:\n"
        f"        endpoint: 0.0.0.0:4317\n"
        f"      http:\n"
        f"        endpoint: 0.0.0.0:4318\n\n"
        f"exporters:\n"
        f"  otlp/codepathfinder:\n"
        f"    endpoint: \"{grpc}\"\n"
        f"    headers:\n"
        f"      Authorization: \"Bearer <YOUR_OTEL_API_KEY>\"\n\n"
        f"service:\n"
        f"  pipelines:\n"
        f"    traces:\n"
        f"      receivers: [otlp]\n"
        f"      exporters: [otlp/codepathfinder]\n"
        f"    metrics:\n"
        f"      receivers: [otlp]\n"
        f"      exporters: [otlp/codepathfinder]\n"
        f"    logs:\n"
        f"      receivers: [otlp]\n"
        f"      exporters: [otlp/codepathfinder]\n\n"
        f"# Index routing — project signals land in:\n"
        f"#   Traces:  {otel.traces_index}\n"
        f"#   Metrics: {otel.metrics_index}\n"
        f"#   Logs:    {otel.logs_index}\n\n"
        f"# Generate an API key: otel_configure_collection(action=\"generate_key\", project=\"{otel.project.name}\")"
    )


def _otel_dotnet_config(otel, http_endpoint: str) -> str:
    endpoint = http_endpoint or '<OTLP_HTTP_ENDPOINT>'
    return (
        f"// .NET OpenTelemetry setup for '{otel.project.name}'\n"
        f"// dotnet add package OpenTelemetry.Exporter.OpenTelemetryProtocol\n\n"
        f"using OpenTelemetry;\n"
        f"using OpenTelemetry.Resources;\n"
        f"using OpenTelemetry.Trace;\n\n"
        f"var builder = WebApplication.CreateBuilder(args);\n\n"
        f"builder.Services.AddOpenTelemetry()\n"
        f"    .ConfigureResource(r => r\n"
        f"        .AddService(\"{otel.service_name}\")\n"
        f"        .AddAttributes(new Dictionary<string, object>\n"
        f"        {{\n"
        f"            [\"cpf.project.id\"] = \"{otel.project.pk}\",\n"
        f"            [\"cpf.project.name\"] = \"{otel.project.name}\",\n"
        f"        }}))\n"
        f"    .WithTracing(t => t\n"
        f"        .AddOtlpExporter(o =>\n"
        f"        {{\n"
        f"            o.Endpoint = new Uri(\"{endpoint}/v1/traces\");\n"
        f"            o.Headers = \"Authorization=Bearer <YOUR_OTEL_API_KEY>\";\n"
        f"        }}));\n\n"
        f"// Generate an API key: otel_configure_collection(action=\"generate_key\", project=\"{otel.project.name}\")"
    )


def _otel_java_config(otel, grpc_endpoint: str) -> str:
    endpoint = grpc_endpoint or '<OTLP_GRPC_ENDPOINT>'
    return (
        f"# Java OpenTelemetry Agent JVM flags for '{otel.project.name}'\n"
        f"# Download: https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases\n\n"
        f"java \\\n"
        f"  -javaagent:opentelemetry-javaagent.jar \\\n"
        f"  -Dotel.service.name={otel.service_name} \\\n"
        f"  -Dotel.resource.attributes=cpf.project.id={otel.project.pk},cpf.project.name={otel.project.name} \\\n"
        f"  -Dotel.exporter.otlp.endpoint={endpoint} \\\n"
        f"  -Dotel.exporter.otlp.headers=Authorization=Bearer%20<YOUR_OTEL_API_KEY> \\\n"
        f"  -jar your-app.jar\n\n"
        f"# Generate an API key: otel_configure_collection(action=\"generate_key\", project=\"{otel.project.name}\")"
    )


def otel_get_onboarding_config(
    project: Optional[str] = None,
    project_id: Optional[int] = None,
    format: str = 'env',
    user=None,
    **kwargs
) -> str:
    """Get onboarding configuration snippets for sending OTLP telemetry to a project."""
    from projects.models import OtelCollectionSettings
    from core.models import SystemSettings

    proj = _resolve_project_for_job(user, project, project_id, require_write_access=False)

    try:
        otel = proj.otel_settings
    except OtelCollectionSettings.DoesNotExist:
        raise ToolError(
            f"OTel collection is not configured for '{proj.name}'. "
            f"Enable it first: otel_configure_collection(action=\"enable\", project=\"{proj.name}\")"
        )
    if not otel.enabled:
        raise ToolError(
            f"OTel collection is disabled for '{proj.name}'. "
            f"Enable it first: otel_configure_collection(action=\"enable\", project=\"{proj.name}\")"
        )

    sys_settings = SystemSettings.get_settings()
    grpc = sys_settings.otel_collector_endpoint
    http = sys_settings.otel_collector_http_endpoint

    if format == 'env':
        return _otel_env_config(otel, grpc, http)
    elif format == 'python':
        return _otel_python_config(otel, http)
    elif format == 'node':
        return _otel_node_config(otel, http)
    elif format == 'otel_collector':
        return _otel_collector_yaml(otel, sys_settings)
    elif format == 'dotnet':
        return _otel_dotnet_config(otel, http)
    elif format == 'java':
        return _otel_java_config(otel, grpc)
    else:
        raise ToolError(
            f"Unknown format: {format}. "
            "Valid formats: env, python, node, otel_collector, dotnet, java"
        )


# =============================================================================
# OTel Query Helpers
# =============================================================================


def _build_otel_time_filter(start_time: Optional[str], end_time: Optional[str]) -> Optional[dict]:
    """
    Build an Elasticsearch range filter on @timestamp.

    Accepts ISO 8601 strings or ES relative expressions (e.g. "now-1h", "now-7d").
    """
    if not start_time and not end_time:
        return None

    range_params = {}
    if start_time:
        range_params["gte"] = start_time
    if end_time:
        range_params["lte"] = end_time
    elif start_time:
        range_params["lte"] = "now"

    return {"range": {"@timestamp": range_params}}


def _build_date_histogram_agg(agg_spec: dict) -> dict:
    """Build date_histogram aggregation with optional sub-aggs."""
    interval = agg_spec.get("interval", "1h")
    calendar_intervals = {"minute", "hour", "day", "week", "month", "quarter", "year"}

    hist_body = {"field": "@timestamp", "min_doc_count": 0}
    if interval in calendar_intervals:
        hist_body["calendar_interval"] = interval
    else:
        hist_body["fixed_interval"] = interval

    aggs = {"over_time": {"date_histogram": hist_body}}

    sub_aggs = {}

    # Optional metric sub-aggregation (e.g. avg duration per bucket)
    metric = agg_spec.get("metric")
    metric_field = agg_spec.get("metric_field")
    if metric and metric_field:
        if metric == "percentiles":
            percents = agg_spec.get("percents", [50, 95, 99])
            sub_aggs["metric_value"] = {"percentiles": {"field": metric_field, "percents": percents}}
        elif metric in ("avg", "sum", "min", "max"):
            sub_aggs["metric_value"] = {metric: {"field": metric_field}}

    # Optional group_by breakdown within each time bucket
    group_by = agg_spec.get("group_by")
    if group_by:
        size = agg_spec.get("group_by_size", 10)
        sub_aggs["breakdown"] = {"terms": {"field": group_by, "size": size}}

    if sub_aggs:
        aggs["over_time"]["aggs"] = sub_aggs

    return aggs


def _build_terms_agg(agg_spec: dict) -> dict:
    """Build terms aggregation for top-N breakdown by a field."""
    field = agg_spec.get("field")
    if not field:
        raise ToolError("terms aggregation requires 'field'")

    size = agg_spec.get("size", 10)
    aggs = {"breakdown": {"terms": {"field": field, "size": size}}}

    # Optional sub-metric within each bucket
    metric = agg_spec.get("metric")
    metric_field = agg_spec.get("metric_field")
    if metric and metric_field:
        if metric == "percentiles":
            percents = agg_spec.get("percents", [50, 95, 99])
            aggs["breakdown"]["aggs"] = {
                "metric_value": {"percentiles": {"field": metric_field, "percents": percents}}
            }
        elif metric in ("avg", "sum", "min", "max"):
            aggs["breakdown"]["aggs"] = {
                "metric_value": {metric: {"field": metric_field}}
            }

    return aggs


def _build_numeric_agg(agg_spec: dict) -> dict:
    """Build a single numeric aggregation (avg/sum/min/max/percentiles)."""
    agg_type = agg_spec.get("type")
    field = agg_spec.get("field")
    if not field:
        raise ToolError(f"{agg_type} aggregation requires 'field'")

    if agg_type == "percentiles":
        percents = agg_spec.get("percents", [50, 95, 99])
        return {"summary": {"percentiles": {"field": field, "percents": percents}}}
    else:
        return {"summary": {agg_type: {"field": field}}}


def _build_otel_aggregations(agg_spec: dict) -> dict:
    """
    Build an Elasticsearch aggregations block from a high-level spec.

    Supported types: date_histogram, terms, avg, sum, min, max, percentiles.
    """
    agg_type = agg_spec.get("type")

    if agg_type == "date_histogram":
        return _build_date_histogram_agg(agg_spec)
    elif agg_type == "terms":
        return _build_terms_agg(agg_spec)
    elif agg_type in ("avg", "sum", "min", "max", "percentiles"):
        return _build_numeric_agg(agg_spec)
    else:
        raise ToolError(
            f"Unknown aggregation type: {agg_type!r}. "
            "Valid types: date_histogram, terms, avg, sum, min, max, percentiles"
        )


def _extract_agg_data(agg_spec: dict, aggs: dict):
    """Extract the relevant portion of the ES aggs response based on spec type."""
    agg_type = agg_spec.get("type")

    if agg_type == "date_histogram":
        buckets = aggs.get("over_time", {}).get("buckets", [])
        rows = []
        for b in buckets:
            row = {
                "timestamp": b.get("key_as_string"),
                "count": b.get("doc_count", 0),
            }
            if "metric_value" in b:
                mv = b["metric_value"]
                row["metric_value"] = mv.get("values") or mv.get("value")
            if "breakdown" in b:
                row["breakdown"] = [
                    {"key": sb["key"], "count": sb["doc_count"]}
                    for sb in b["breakdown"].get("buckets", [])
                ]
            rows.append(row)
        return rows

    elif agg_type == "terms":
        buckets = aggs.get("breakdown", {}).get("buckets", [])
        rows = []
        for b in buckets:
            row = {"key": b.get("key"), "count": b.get("doc_count", 0)}
            if "metric_value" in b:
                mv = b["metric_value"]
                row["metric_value"] = mv.get("values") or mv.get("value")
            rows.append(row)
        return rows

    elif agg_type in ("avg", "sum", "min", "max"):
        return {"value": aggs.get("summary", {}).get("value")}

    elif agg_type == "percentiles":
        return {"values": aggs.get("summary", {}).get("values", {})}

    return aggs


def _format_agg_result(proj_name: str, index: str, signal_type: str,
                       agg_spec: dict, aggs_response: dict,
                       total_docs: int, time_range: Optional[dict]) -> str:
    """Format aggregation results as a header + JSON for the LLM to parse."""
    import json

    result = {
        "project": proj_name,
        "index": index,
        "signal_type": signal_type,
        "total_matching_docs": total_docs,
        "aggregation_type": agg_spec.get("type"),
        "data": _extract_agg_data(agg_spec, aggs_response),
    }
    if time_range:
        result["time_range"] = time_range

    header = (
        f"=== OTel Aggregation: {signal_type} for '{proj_name}' ===\n"
        f"Total matching documents: {total_docs}\n"
        f"Aggregation: {agg_spec.get('type', 'unknown')}\n\n"
    )
    return header + json.dumps(result, indent=2, default=str)


def _run_otel_aggregation(es, index: str, query: dict, agg_spec: dict,
                          proj_name: str, signal_type: str,
                          start_time: Optional[str], end_time: Optional[str]) -> str:
    """Execute an aggregation query and return formatted results."""
    aggs = _build_otel_aggregations(agg_spec)

    try:
        resp = es.search(
            index=index,
            body={
                "query": query,
                "size": 0,
                "aggs": aggs,
            },
            ignore_unavailable=True,
        )
    except Exception as exc:
        raise ToolError(f"Elasticsearch aggregation failed: {exc}")

    total = resp.get("hits", {}).get("total", {}).get("value", 0)
    time_range = None
    if start_time or end_time:
        time_range = {"start": start_time or "*", "end": end_time or "now"}

    return _format_agg_result(
        proj_name, index, signal_type,
        agg_spec, resp.get("aggregations", {}),
        total, time_range
    )


def otel_query_traces(
    project: Optional[str] = None,
    project_id: Optional[int] = None,
    trace_id: Optional[str] = None,
    service_name: Optional[str] = None,
    status_code: Optional[str] = None,
    limit: int = 20,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    mode: str = "raw",
    aggregation: Optional[dict] = None,
    user=None,
    **kwargs
) -> str:
    """Query OTel traces from Elasticsearch for a project."""
    from projects.models import OtelCollectionSettings

    proj = _resolve_project_for_job(user, project, project_id, require_write_access=False)

    try:
        otel = proj.otel_settings
    except OtelCollectionSettings.DoesNotExist:
        raise ToolError(
            f"OTel collection is not configured for '{proj.name}'. "
            f"Enable it first: otel_configure_collection(action=\"enable\", project=\"{proj.name}\")"
        )

    es = get_es_client()
    if es is None:
        raise ToolError("Elasticsearch not configured")

    must = []

    if trace_id:
        must.append({"term": {"trace_id": trace_id}})
    if service_name:
        must.append({"term": {"resource.attributes.service.name": service_name}})
    if status_code:
        code_map = {"OK": "Ok", "ERROR": "Error", "UNSET": "Unset"}
        must.append({"term": {"status.code": code_map.get(status_code.upper(), status_code)}})

    time_filter = _build_otel_time_filter(start_time, end_time)
    if time_filter:
        must.append(time_filter)

    query = {"bool": {"must": must}} if must else {"match_all": {}}

    # Aggregation mode
    if mode == "aggregate":
        if not aggregation:
            raise ToolError(
                "aggregation spec required when mode='aggregate'. "
                "Example: aggregation={\"type\": \"date_histogram\", \"interval\": \"1h\", "
                "\"metric\": \"avg\", \"metric_field\": \"duration\"}"
            )
        return _run_otel_aggregation(
            es, otel.traces_index, query, aggregation,
            proj.name, "traces", start_time, end_time
        )

    # Raw mode
    limit = min(max(1, limit), 100)

    try:
        resp = es.search(
            index=otel.traces_index,
            body={
                "query": query,
                "sort": [{"@timestamp": {"order": "desc"}}],
                "size": limit,
                "_source": ["@timestamp", "trace_id", "span_id", "name", "kind",
                            "status", "duration", "resource.attributes"],
            },
            ignore_unavailable=True,
        )
    except Exception as exc:
        raise ToolError(f"Elasticsearch query failed: {exc}")

    hits = resp.get("hits", {}).get("hits", [])
    total = resp.get("hits", {}).get("total", {}).get("value", 0)

    if not hits:
        return (
            f"No traces found for project '{proj.name}' in index '{otel.traces_index}'.\n"
            "Check that the OTel collector is running and your application is sending traces."
        )

    lines = [
        f"=== Traces for '{proj.name}' (showing {len(hits)} of {total}) ===",
        f"Index: {otel.traces_index}",
        "",
    ]
    for hit in hits:
        src = hit["_source"]
        svc = src.get('resource', {}).get('attributes', {}).get('service.name', '?')
        status = src.get('status', {}).get('code', 'Unset')
        lines.append(
            f"[{src.get('@timestamp', '?')}] "
            f"{src.get('name', '?')} "
            f"trace={src.get('trace_id', '?')[:16]}... "
            f"span={src.get('span_id', '?')} "
            f"status={status} "
            f"service={svc}"
        )

    return "\n".join(lines)


def otel_query_metrics(
    project: Optional[str] = None,
    project_id: Optional[int] = None,
    metric_name: Optional[str] = None,
    service_name: Optional[str] = None,
    limit: int = 20,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    mode: str = "raw",
    aggregation: Optional[dict] = None,
    user=None,
    **kwargs
) -> str:
    """Query OTel metrics from Elasticsearch for a project."""
    from projects.models import OtelCollectionSettings

    proj = _resolve_project_for_job(user, project, project_id, require_write_access=False)

    try:
        otel = proj.otel_settings
    except OtelCollectionSettings.DoesNotExist:
        raise ToolError(
            f"OTel collection is not configured for '{proj.name}'. "
            f"Enable it first: otel_configure_collection(action=\"enable\", project=\"{proj.name}\")"
        )

    es = get_es_client()
    if es is None:
        raise ToolError("Elasticsearch not configured")

    must = []

    if metric_name:
        field = f"metrics.{metric_name}"
        if "*" in metric_name:
            must.append({"query_string": {"query": f"metrics.{metric_name}:*"}})
        else:
            must.append({"exists": {"field": field}})
    if service_name:
        must.append({"term": {"resource.attributes.service.name": service_name}})

    time_filter = _build_otel_time_filter(start_time, end_time)
    if time_filter:
        must.append(time_filter)

    query = {"bool": {"must": must}} if must else {"match_all": {}}

    # Aggregation mode
    if mode == "aggregate":
        if not aggregation:
            raise ToolError(
                "aggregation spec required when mode='aggregate'. "
                "Example: aggregation={\"type\": \"date_histogram\", \"interval\": \"1h\", "
                "\"metric\": \"avg\", \"metric_field\": \"metrics.http.server.duration\"}"
            )
        return _run_otel_aggregation(
            es, otel.metrics_index, query, aggregation,
            proj.name, "metrics", start_time, end_time
        )

    # Raw mode
    limit = min(max(1, limit), 100)

    try:
        resp = es.search(
            index=otel.metrics_index,
            body={
                "query": query,
                "sort": [{"@timestamp": {"order": "desc"}}],
                "size": limit,
                "_source": ["@timestamp", "metrics", "unit", "resource.attributes"],
            },
            ignore_unavailable=True,
        )
    except Exception as exc:
        raise ToolError(f"Elasticsearch query failed: {exc}")

    hits = resp.get("hits", {}).get("hits", [])
    total = resp.get("hits", {}).get("total", {}).get("value", 0)

    if not hits:
        return (
            f"No metrics found for project '{proj.name}' in index '{otel.metrics_index}'.\n"
            "Check that the OTel collector is running and your application is sending metrics."
        )

    lines = [
        f"=== Metrics for '{proj.name}' (showing {len(hits)} of {total}) ===",
        f"Index: {otel.metrics_index}",
        "",
    ]
    for hit in hits:
        src = hit["_source"]
        svc = src.get('resource', {}).get('attributes', {}).get('service.name', '?')
        metric_values = src.get('metrics', {})
        metric_str = ", ".join(f"{k}={v}" for k, v in metric_values.items())
        lines.append(
            f"[{src.get('@timestamp', '?')}] "
            f"{metric_str} "
            f"unit={src.get('unit', '-')} "
            f"service={svc}"
        )

    return "\n".join(lines)


def otel_query_logs(
    project: Optional[str] = None,
    project_id: Optional[int] = None,
    severity: Optional[str] = None,
    service_name: Optional[str] = None,
    search: Optional[str] = None,
    trace_id: Optional[str] = None,
    limit: int = 20,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    mode: str = "raw",
    aggregation: Optional[dict] = None,
    user=None,
    **kwargs
) -> str:
    """Query OTel logs from Elasticsearch for a project."""
    from projects.models import OtelCollectionSettings

    proj = _resolve_project_for_job(user, project, project_id, require_write_access=False)

    try:
        otel = proj.otel_settings
    except OtelCollectionSettings.DoesNotExist:
        raise ToolError(
            f"OTel collection is not configured for '{proj.name}'. "
            f"Enable it first: otel_configure_collection(action=\"enable\", project=\"{proj.name}\")"
        )

    es = get_es_client()
    if es is None:
        raise ToolError("Elasticsearch not configured")

    must = []

    if severity:
        must.append({"term": {"severity_text": severity.upper()}})
    if service_name:
        must.append({"term": {"resource.attributes.service.name": service_name}})
    if trace_id:
        must.append({"term": {"trace_id": trace_id}})
    if search:
        must.append({"match": {"body.text": search}})

    time_filter = _build_otel_time_filter(start_time, end_time)
    if time_filter:
        must.append(time_filter)

    query = {"bool": {"must": must}} if must else {"match_all": {}}

    # Aggregation mode
    if mode == "aggregate":
        if not aggregation:
            raise ToolError(
                "aggregation spec required when mode='aggregate'. "
                "Example: aggregation={\"type\": \"date_histogram\", \"interval\": \"1h\", "
                "\"group_by\": \"severity_text\"}"
            )
        return _run_otel_aggregation(
            es, otel.logs_index, query, aggregation,
            proj.name, "logs", start_time, end_time
        )

    # Raw mode
    limit = min(max(1, limit), 100)

    try:
        resp = es.search(
            index=otel.logs_index,
            body={
                "query": query,
                "sort": [{"@timestamp": {"order": "desc"}}],
                "size": limit,
                "_source": [
                    "@timestamp", "severity_text", "severity_number",
                    "body", "trace_id", "span_id", "resource.attributes",
                ],
            },
            ignore_unavailable=True,
        )
    except Exception as exc:
        raise ToolError(f"Elasticsearch query failed: {exc}")

    hits = resp.get("hits", {}).get("hits", [])
    total = resp.get("hits", {}).get("total", {}).get("value", 0)

    if not hits:
        return (
            f"No logs found for project '{proj.name}' in index '{otel.logs_index}'.\n"
            "Check that the OTel collector is running and your application is sending logs."
        )

    lines = [
        f"=== Logs for '{proj.name}' (showing {len(hits)} of {total}) ===",
        f"Index: {otel.logs_index}",
        "",
    ]
    for hit in hits:
        src = hit["_source"]
        svc = src.get('resource', {}).get('attributes', {}).get('service.name', '?')
        body_preview = str(src.get("body", ""))[:120]
        lines.append(
            f"[{src.get('@timestamp', '?')}] "
            f"{src.get('severity_text', '?'):5} "
            f"service={svc} "
            f"{body_preview}"
        )

    return "\n".join(lines)


# =============================================================================
# Memories Tools
# =============================================================================

def memories_list(
    tags: Optional[List[str]] = None,
    scope: Optional[str] = None,
    memory_type: Optional[str] = None,
    user=None
) -> str:
    """List memories accessible to the user."""
    try:
        from memories.services import MemoryService
        service = MemoryService()
        memories = service.list_memories(user=user, tags=tags, scope=scope, memory_type=memory_type)
        if not memories.exists():
            return "No memories found."
        parts = ["Memories:", "=" * 50]
        for m in memories:
            scope_label = "[Org]" if m.scope == 'organization' else "[Personal]"
            type_label = f"[{m.memory_type}]"
            tags_str = f" ({', '.join(m.tags)})" if m.tags else ""
            parts.append(f"\nID {m.pk}: {m.title} {scope_label}{type_label}{tags_str}")
            # Show first 200 chars of content
            preview = m.content[:200] + ("..." if len(m.content) > 200 else "")
            parts.append(f"  {preview}")
        parts.append(f"\nTotal: {memories.count()}")
        return "\n".join(parts)
    except Exception as e:
        logger.error(f"memories_list error: {e}")
        raise ToolError(f"Failed to list memories: {e}")


def memories_get(memory_id: int, user=None) -> str:
    """Get a memory by ID."""
    try:
        from memories.services import MemoryService
        service = MemoryService()
        memory = service.get_memory(memory_id, user)
        if not memory:
            return f"Memory {memory_id} not found or access denied."
        memory.increment_usage()
        scope_label = "Organization" if memory.scope == 'organization' else "Personal"
        parts = [
            f"Memory: {memory.title}",
            "=" * 50,
            f"ID: {memory.pk}",
            f"Type: {memory.memory_type}",
            f"Scope: {scope_label}",
            f"Tags: {', '.join(memory.tags) if memory.tags else 'none'}",
            f"Usage: {memory.usage_count}",
            "",
            "Content:",
            "=" * 50,
            memory.content,
        ]
        return "\n".join(parts)
    except Exception as e:
        logger.error(f"memories_get error: {e}")
        raise ToolError(f"Failed to get memory: {e}")


def memories_search(query: str, limit: int = 5, user=None) -> str:
    """Semantic search across accessible memories."""
    try:
        from memories.services import MemoryService
        service = MemoryService()
        results = service.search_memories(query, user, limit=limit)
        if not results:
            return f"No memories found for: {query}"
        parts = [f"Memory search results for: '{query}'", "=" * 50]
        for r in results:
            scope_label = "[Org]" if r.get('scope') == 'organization' else "[Personal]"
            parts.append(f"\nID {r['id']}: {r['title']} {scope_label}")
            preview = r['content'][:200] + ("..." if len(r['content']) > 200 else "")
            parts.append(f"  {preview}")
        return "\n".join(parts)
    except Exception as e:
        logger.error(f"memories_search error: {e}")
        raise ToolError(f"Failed to search memories: {e}")


def memories_create(
    title: str,
    content: str,
    memory_type: str = 'text',
    tags: Optional[List[str]] = None,
    scope: str = 'user',
    user=None
) -> str:
    """Create a new memory."""
    try:
        from memories.services import MemoryService
        service = MemoryService()
        memory = service.create_memory(
            user=user, title=title, content=content,
            memory_type=memory_type, tags=tags, scope=scope
        )
        return f"Memory created (ID {memory.pk}): '{memory.title}' [{memory.scope}]"
    except PermissionError as e:
        raise ToolError(str(e))
    except Exception as e:
        logger.error(f"memories_create error: {e}")
        raise ToolError(f"Failed to create memory: {e}")


def memories_update(
    memory_id: int,
    title: Optional[str] = None,
    content: Optional[str] = None,
    tags: Optional[List[str]] = None,
    scope: Optional[str] = None,
    user=None
) -> str:
    """Update an existing memory."""
    try:
        from memories.services import MemoryService
        service = MemoryService()
        kwargs = {}
        if title is not None:
            kwargs['title'] = title
        if content is not None:
            kwargs['content'] = content
        if tags is not None:
            kwargs['tags'] = tags
        if scope is not None:
            kwargs['scope'] = scope
        memory = service.update_memory(memory_id, user, **kwargs)
        return f"Memory updated (ID {memory.pk}): '{memory.title}'"
    except (PermissionError, ValueError) as e:
        raise ToolError(str(e))
    except Exception as e:
        logger.error(f"memories_update error: {e}")
        raise ToolError(f"Failed to update memory: {e}")


def memories_delete(memory_id: int, user=None) -> str:
    """Soft-delete a memory."""
    try:
        from memories.services import MemoryService
        service = MemoryService()
        service.delete_memory(memory_id, user)
        return f"Memory {memory_id} deleted."
    except (PermissionError, ValueError) as e:
        raise ToolError(str(e))
    except Exception as e:
        logger.error(f"memories_delete error: {e}")
        raise ToolError(f"Failed to delete memory: {e}")


def memories_import(
    title: str,
    content: str,
    tags: Optional[List[str]] = None,
    scope: str = 'user',
    user=None
) -> str:
    """Import a markdown document as a chunked RAG memory."""
    try:
        from memories.services import MemoryService
        service = MemoryService()
        memory = service.import_document(
            user=user, title=title, content=content, tags=tags, scope=scope
        )
        char_count = len(content)
        return (
            f"Document imported (ID {memory.pk}): '{memory.title}' [{memory.scope}]\n"
            f"{char_count} characters indexed for semantic retrieval."
        )
    except PermissionError as e:
        raise ToolError(str(e))
    except Exception as e:
        logger.error(f"memories_import error: {e}")
        raise ToolError(f"Failed to import document: {e}")


# =============================================================================
# Tool Registry
# =============================================================================

# Map of tool names to functions (for dynamic dispatch)
TOOLS = {
    # Code search tools
    'semantic_code_search': semantic_code_search,
    'map_symbols_by_query': map_symbols_by_query,
    'size': size,
    'symbol_analysis': symbol_analysis,
    'read_file_from_chunks': read_file_from_chunks,
    'document_symbols': document_symbols,
    # GitHub tools
    'github_manage_issues': github_manage_issues,
    'github_manage_code': github_manage_code,
    # Skills tools
    'skills_list': skills_list,
    'skills_get': skills_get,
    'skills_search': skills_search,
    'skills_sync': skills_sync,
    'skills_import': skills_import,
    'skills_discover': skills_discover,
    'skills_activate': skills_activate,
    # Memories tools
    'memories_list': memories_list,
    'memories_get': memories_get,
    'memories_search': memories_search,
    'memories_create': memories_create,
    'memories_update': memories_update,
    'memories_delete': memories_delete,
    'memories_import': memories_import,
    # Job management tools
    'job_manage': job_manage,
    'job_status': job_status,
    # OTel collection tools
    'otel_configure_collection': otel_configure_collection,
    'otel_get_onboarding_config': otel_get_onboarding_config,
    # OTel query tools
    'otel_query_traces': otel_query_traces,
    'otel_query_metrics': otel_query_metrics,
    'otel_query_logs': otel_query_logs,
}


def execute_tool(tool_name: str, arguments: Dict[str, Any], user=None) -> str:
    """
    Execute a tool by name with the given arguments.

    Args:
        tool_name: Name of the tool to execute
        arguments: Dictionary of arguments to pass to the tool
        user: Django User object for project access control

    Returns:
        Tool execution result

    Raises:
        ToolError: If tool doesn't exist or execution fails
    """
    if tool_name not in TOOLS:
        raise ToolError(f"Unknown tool: {tool_name}")

    tool_func = TOOLS[tool_name]

    try:
        return tool_func(user=user, **arguments)
    except TypeError as e:
        raise ToolError(f"Invalid arguments for tool {tool_name}: {str(e)}")
    except Exception as e:
        logger.error(f"Tool {tool_name} execution failed: {e}")
        raise
