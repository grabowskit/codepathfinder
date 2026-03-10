"""
OpenAPI schema extensions for the Jobs API.

This module provides drf-spectacular decorators and examples for API documentation.
"""

from drf_spectacular.utils import (
    extend_schema,
    extend_schema_view,
    OpenApiParameter,
    OpenApiExample,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes

# Common parameters
PROJECT_ID_PARAM = OpenApiParameter(
    name='project_id',
    type=OpenApiTypes.INT,
    location=OpenApiParameter.PATH,
    description='The unique project ID',
    required=True,
)

# Common response examples
ERROR_RESPONSE_EXAMPLE = OpenApiExample(
    name='Error Response',
    value={
        'error': {
            'code': 'ERROR_CODE',
            'message': 'Human-readable error message',
            'remediation': 'Steps to fix the error',
        }
    },
    response_only=True,
)

ALREADY_RUNNING_EXAMPLE = OpenApiExample(
    name='Already Running Error',
    value={
        'error': {
            'code': 'ALREADY_RUNNING',
            'message': 'Project already has a running job',
            'remediation': 'Stop the current job first: POST /api/v1/jobs/{id}/stop/',
        }
    },
    response_only=True,
)

# Job Start schema
JOB_START_REQUEST_EXAMPLE = OpenApiExample(
    name='Start with defaults',
    value={},
    request_only=True,
    description='Start job with default options',
)

JOB_START_FULL_EXAMPLE = OpenApiExample(
    name='Full rebuild',
    value={
        'clean_index': True,
        'branch': 'develop',
        'concurrency': 8,
    },
    request_only=True,
    description='Full index rebuild with custom settings',
)

JOB_START_RESPONSE_EXAMPLE = OpenApiExample(
    name='Job Started',
    value={
        'content': [{'type': 'text', 'text': "Indexing job started for project 'my-repo'"}],
        'data': {
            'project_id': 42,
            'project_name': 'my-repo',
            'status': 'running',
            'started_at': '2024-02-09T15:33:20Z',
            'options': {
                'clean_index': False,
                'pull_before_index': False,
                'watch_mode': False,
                'branch': 'main',
                'concurrency': 4,
            },
        },
        'links': {
            'self': '/api/v1/jobs/42/status/',
            'stop': '/api/v1/jobs/42/stop/',
            'logs': '/api/v1/jobs/42/logs/',
        },
    },
    response_only=True,
)

# Job Status schema
JOB_STATUS_RESPONSE_EXAMPLE = OpenApiExample(
    name='Running Status',
    value={
        'content': [{'type': 'text', 'text': "Project 'my-repo' is running (4523 documents indexed)"}],
        'data': {
            'project_id': 42,
            'project_name': 'my-repo',
            'repository_url': 'https://github.com/org/my-repo',
            'status': 'running',
            'is_enabled': True,
            'index_name': 'project-42',
            'elasticsearch': {
                'document_count': 4523,
                'index_size_mb': 12.5,
            },
            'options': {
                'clean_index': False,
                'pull_before_index': False,
                'watch_mode': False,
                'branch': 'main',
                'concurrency': 4,
            },
        },
        'links': {
            'self': '/api/v1/jobs/42/status/',
            'stop': '/api/v1/jobs/42/stop/',
            'logs': '/api/v1/jobs/42/logs/',
        },
    },
    response_only=True,
)

# Project Create schema
PROJECT_CREATE_REQUEST_EXAMPLE = OpenApiExample(
    name='Create Project',
    value={
        'name': 'my-project',
        'repository_url': 'https://github.com/org/repo',
        'branch': 'main',
        'auto_start': True,
    },
    request_only=True,
)

PROJECT_CREATE_RESPONSE_EXAMPLE = OpenApiExample(
    name='Project Created',
    value={
        'content': [{'type': 'text', 'text': "Project 'my-project' created successfully and indexing started"}],
        'data': {
            'id': 42,
            'name': 'my-project',
            'repository_url': 'https://github.com/org/repo',
            'branch': 'main',
            'status': 'running',
            'is_enabled': True,
            'index_name': 'project-42',
        },
        'links': {
            'self': '/api/v1/jobs/42/',
            'status': '/api/v1/jobs/42/status/',
            'stop': '/api/v1/jobs/42/stop/',
        },
    },
    response_only=True,
)

# Search schema
SEARCH_REQUEST_EXAMPLE = OpenApiExample(
    name='Semantic Search',
    value={
        'query': 'authentication middleware',
        'size': 10,
        'search_type': 'semantic',
    },
    request_only=True,
)

SEARCH_RESPONSE_EXAMPLE = OpenApiExample(
    name='Search Results',
    value={
        'content': [{'type': 'text', 'text': "Found 8 results for 'authentication middleware' in project 'my-repo'"}],
        'data': {
            'project_id': 42,
            'project_name': 'my-repo',
            'query': 'authentication middleware',
            'total_results': 8,
            'results': [
                {
                    'file_path': 'src/middleware/auth.ts',
                    'start_line': 15,
                    'end_line': 45,
                    'kind': 'function',
                    'score': 0.92,
                    'content': 'export function authMiddleware(req, res, next) {...}',
                    'symbols': ['authMiddleware'],
                },
            ],
        },
    },
    response_only=True,
)

# List schema
JOB_LIST_RESPONSE_EXAMPLE = OpenApiExample(
    name='Project List',
    value={
        'content': [{'type': 'text', 'text': 'Found 3 project(s): 1 running, 2 completed'}],
        'data': {
            'projects': [
                {
                    'id': 42,
                    'name': 'my-repo',
                    'repository_url': 'https://github.com/org/my-repo',
                    'status': 'running',
                    'is_enabled': True,
                    'created_at': '2024-01-15T10:00:00Z',
                    'updated_at': '2024-02-09T15:33:20Z',
                    'links': {
                        'status': '/api/v1/jobs/42/status/',
                        'stop': '/api/v1/jobs/42/stop/',
                    },
                },
            ],
            'pagination': {
                'page': 1,
                'page_size': 20,
                'total_count': 3,
                'total_pages': 1,
            },
            'summary': {
                'pending': 0,
                'running': 1,
                'completed': 2,
                'failed': 0,
                'watching': 0,
                'stopped': 0,
            },
        },
        'links': {
            'self': '/api/v1/jobs/',
            'create': '/api/v1/jobs/',
            'bulk_start': '/api/v1/jobs/bulk/start/',
            'bulk_stop': '/api/v1/jobs/bulk/stop/',
            'search': '/api/v1/jobs/search/',
        },
    },
    response_only=True,
)

# Bulk operations schema
BULK_START_REQUEST_EXAMPLE = OpenApiExample(
    name='Bulk Start',
    value={
        'project_ids': [1, 2, 3],
        'options': {
            'clean_index': False,
            'concurrency': 4,
        },
    },
    request_only=True,
)

BULK_START_RESPONSE_EXAMPLE = OpenApiExample(
    name='Bulk Start Results',
    value={
        'content': [{'type': 'text', 'text': 'Started 2/3 jobs'}],
        'data': {
            'results': [
                {'project_id': 1, 'project_name': 'repo-1', 'success': True, 'status': 'running'},
                {'project_id': 2, 'project_name': 'repo-2', 'success': True, 'status': 'running'},
                {'project_id': 3, 'success': False, 'error': 'Already running'},
            ],
        },
        'links': {
            'list': '/api/v1/jobs/',
            'bulk_stop': '/api/v1/jobs/bulk/stop/',
        },
    },
    response_only=True,
)
