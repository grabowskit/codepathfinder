# list_indices Management Command

Lists all Elasticsearch indices with document counts and storage sizes.

## Overview

The `list_indices` command queries the configured Elasticsearch cluster and displays information about all indices, including:
- Index name
- Document count
- Storage size in MB

This is useful for:
- Monitoring index growth
- Identifying large or empty indices
- Verifying project indexing status
- Troubleshooting Elasticsearch storage issues

## Prerequisites

Elasticsearch must be configured in System Settings:
1. Go to Settings > System Settings (superuser only)
2. Configure Elasticsearch endpoint or Cloud ID
3. Provide API key or username/password authentication

## Usage

### Basic Usage

```bash
# Local development
cd web && python manage.py list_indices

# Docker
docker-compose exec web python manage.py list_indices
```

### Output Formats

```bash
# Text table (default)
python manage.py list_indices

# JSON output (for scripting/automation)
python manage.py list_indices --format json
```

### Sorting Options

```bash
# Sort by name (alphabetical, default)
python manage.py list_indices --sort name

# Sort by document count (descending)
python manage.py list_indices --sort docs

# Sort by storage size (descending)
python manage.py list_indices --sort size
```

### Filtering

```bash
# Show only project indices
python manage.py list_indices --filter project-

# Show all indices including system indices
python manage.py list_indices --include-system
```

### Combined Examples

```bash
# List project indices sorted by size, as JSON
python manage.py list_indices --filter project- --sort size --format json

# Find largest indices (useful for cleanup)
python manage.py list_indices --sort size

# Docker: Get JSON output for automation
docker-compose exec web python manage.py list_indices --format json
```

## Output Examples

### Text Output

```
Elasticsearch Indices
======================================================================
  Index Name                               Documents     Size (MB)
  ---------------------------------------- ------------ ------------
  project-1                                      15,234         8.45
  project-2                                       3,456         1.23
  code-chunks                                    61,479        34.35
  ---------------------------------------- ------------ ------------
  TOTAL                                          80,169        44.03

  Found 3 indices.
```

### JSON Output

```json
{
  "success": true,
  "summary": {
    "total_indices": 3,
    "total_documents": 80169,
    "total_size_mb": 44.03
  },
  "indices": [
    {"name": "code-chunks", "doc_count": 61479, "size_bytes": 36016128, "size_mb": 34.35},
    {"name": "project-1", "doc_count": 15234, "size_bytes": 8859648, "size_mb": 8.45},
    {"name": "project-2", "doc_count": 3456, "size_bytes": 1290240, "size_mb": 1.23}
  ]
}
```

## Error Handling

| Error | Cause | Solution |
|-------|-------|----------|
| "Elasticsearch not configured" | Missing SystemSettings config | Configure ES in Settings > System |
| "Cannot connect to Elasticsearch" | ES server unreachable | Check endpoint URL and network |
| "Connection failed: 401" | Invalid credentials | Verify API key or user/password |

### Error Output Example (JSON)

```json
{
  "success": false,
  "error": "Elasticsearch not configured. Check SystemSettings in admin.",
  "indices": []
}
```

## Arguments Reference

| Argument | Values | Default | Description |
|----------|--------|---------|-------------|
| `--format` | `text`, `json` | `text` | Output format |
| `--sort` | `name`, `docs`, `size` | `name` | Sort field |
| `--filter` | string | none | Filter indices by prefix |
| `--include-system` | flag | false | Include `.` prefixed system indices |

## Related Commands

- `audit_project_indices` - Comprehensive audit of projects and their ES indices

## See Also

- [Local Elasticsearch setup](Local%20Elasticsearch%20setup.md)
- [PROJECT_DOCUMENTATION](PROJECT_DOCUMENTATION.md)
