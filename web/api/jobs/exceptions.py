"""
Custom exceptions for the Jobs API.

These exceptions provide AI-agent friendly error messages with:
- Machine-readable error codes
- Human-readable messages
- Actionable remediation steps
"""

from rest_framework import status


class JobAPIError(Exception):
    """
    Base exception for Jobs API errors.

    Provides structured error responses optimized for AI agent consumption.
    """

    def __init__(
        self,
        code: str,
        message: str,
        remediation: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict = None
    ):
        self.code = code
        self.message = message
        self.remediation = remediation
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)

    def to_dict(self) -> dict:
        """Convert exception to API response format."""
        error_dict = {
            'error': {
                'code': self.code,
                'message': self.message,
                'remediation': self.remediation,
            }
        }
        if self.details:
            error_dict['error']['details'] = self.details
        return error_dict


# Authentication Errors (401)
class InvalidAPIKeyError(JobAPIError):
    """Raised when API key format is invalid."""

    def __init__(self, details: dict = None):
        super().__init__(
            code='INVALID_API_KEY',
            message='Invalid API key format',
            remediation="API keys must start with 'cpf_'. Generate a new key from the project dashboard at /projects/{project_id}/keys/",
            status_code=status.HTTP_401_UNAUTHORIZED,
            details=details
        )


class APIKeyRevokedError(JobAPIError):
    """Raised when API key has been deactivated."""

    def __init__(self, details: dict = None):
        super().__init__(
            code='API_KEY_REVOKED',
            message='API key has been revoked',
            remediation='This key is no longer active. Generate a new key from the project dashboard.',
            status_code=status.HTTP_401_UNAUTHORIZED,
            details=details
        )


# Authorization Errors (403)
class AccessDeniedError(JobAPIError):
    """Raised when API key doesn't have access to the project."""

    def __init__(self, project_id: int = None, details: dict = None):
        remediation = 'Use an API key created for this specific project.'
        if project_id:
            remediation = f'Use an API key created for project {project_id}. List your projects: GET /api/v1/jobs/'
        super().__init__(
            code='ACCESS_DENIED',
            message='API key does not have access to this project',
            remediation=remediation,
            status_code=status.HTTP_403_FORBIDDEN,
            details=details
        )


class ScopeInsufficientError(JobAPIError):
    """Raised when API key scope doesn't allow the operation."""

    def __init__(self, required_scope: str, current_scope: str, details: dict = None):
        super().__init__(
            code='SCOPE_INSUFFICIENT',
            message=f"API key scope is insufficient for this operation",
            remediation=f"This operation requires '{required_scope}' or 'all' scope. Current scope: '{current_scope}'. Create a new API key with the required scope.",
            status_code=status.HTTP_403_FORBIDDEN,
            details=details
        )


class ReadOnlyAccessError(JobAPIError):
    """Raised when shared user tries to modify a project."""

    def __init__(self, details: dict = None):
        super().__init__(
            code='READ_ONLY_ACCESS',
            message='Shared access is read-only',
            remediation='Contact the project owner to perform this action, or use an API key from a project you own.',
            status_code=status.HTTP_403_FORBIDDEN,
            details=details
        )


# Resource Errors (404)
class ProjectNotFoundError(JobAPIError):
    """Raised when project doesn't exist."""

    def __init__(self, project_id: int = None, details: dict = None):
        msg = 'Project not found'
        if project_id:
            msg = f'Project {project_id} not found'
        super().__init__(
            code='PROJECT_NOT_FOUND',
            message=msg,
            remediation='Verify the project ID. List available projects: GET /api/v1/jobs/',
            status_code=status.HTTP_404_NOT_FOUND,
            details=details
        )


class JobNotFoundError(JobAPIError):
    """Raised when job/run doesn't exist."""

    def __init__(self, project_id: int = None, details: dict = None):
        super().__init__(
            code='JOB_NOT_FOUND',
            message='No job found for this project',
            remediation=f'The project may not have been indexed yet. Start a job: POST /api/v1/jobs/{project_id}/start/' if project_id else 'Start an indexing job first.',
            status_code=status.HTTP_404_NOT_FOUND,
            details=details
        )


# Validation Errors (400)
class AlreadyRunningError(JobAPIError):
    """Raised when trying to start a job that's already running."""

    def __init__(self, project_id: int, current_status: str, details: dict = None):
        super().__init__(
            code='ALREADY_RUNNING',
            message='Project already has a running job',
            remediation=f'Stop the current job first: POST /api/v1/jobs/{project_id}/stop/, or wait for it to complete. Current status: {current_status}',
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details
        )


class NoRunningJobError(JobAPIError):
    """Raised when trying to stop a job that isn't running."""

    def __init__(self, project_id: int, current_status: str, details: dict = None):
        super().__init__(
            code='NO_RUNNING_JOB',
            message='No running job found for this project',
            remediation=f'The project is not currently indexing. Current status: {current_status}. To start indexing: POST /api/v1/jobs/{project_id}/start/',
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details
        )


class InvalidOptionsError(JobAPIError):
    """Raised when job options are invalid."""

    def __init__(self, field: str, message: str, valid_values: str = None, details: dict = None):
        remediation = f'Check the value for "{field}". {message}'
        if valid_values:
            remediation += f' Valid values: {valid_values}'
        super().__init__(
            code='INVALID_OPTIONS',
            message=f'Invalid job option: {field}',
            remediation=remediation,
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details
        )


class IndexNotReadyError(JobAPIError):
    """Raised when trying to search an index that isn't ready."""

    def __init__(self, project_id: int, current_status: str, details: dict = None):
        super().__init__(
            code='INDEX_NOT_READY',
            message='Project index is not ready for search',
            remediation=f'Wait for the indexing job to complete. Current status: {current_status}. Check status: GET /api/v1/jobs/{project_id}/status/',
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details
        )


# Configuration Errors (400)
class ElasticsearchNotConfiguredError(JobAPIError):
    """Raised when Elasticsearch is not configured."""

    def __init__(self, missing_fields: list = None, details: dict = None):
        msg = 'Elasticsearch configuration is incomplete'
        remediation = 'Configure Elasticsearch in Settings > System. Required: endpoint or cloud_id, and api_key or username/password.'
        if missing_fields:
            remediation = f'Missing configuration: {", ".join(missing_fields)}. {remediation}'
        super().__init__(
            code='ELASTICSEARCH_NOT_CONFIGURED',
            message=msg,
            remediation=remediation,
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details
        )


class GitHubTokenMissingError(JobAPIError):
    """Raised when GitHub token is required but missing."""

    def __init__(self, project_id: int = None, details: dict = None):
        super().__init__(
            code='GITHUB_TOKEN_MISSING',
            message='GitHub token required for private repository',
            remediation=f'Add a GitHub token to the project: PATCH /api/v1/jobs/{project_id}/ with {{"github_token": "ghp_xxx"}}' if project_id else 'Add a GitHub token to the project settings.',
            status_code=status.HTTP_400_BAD_REQUEST,
            details=details
        )


# Infrastructure Errors (503)
class KubernetesUnavailableError(JobAPIError):
    """Raised when Kubernetes is not available."""

    def __init__(self, details: dict = None):
        super().__init__(
            code='KUBERNETES_UNAVAILABLE',
            message='Job orchestration service unavailable',
            remediation='The system is temporarily unable to start jobs. Try again in a few minutes. If this persists, contact support.',
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details=details
        )


class ElasticsearchUnavailableError(JobAPIError):
    """Raised when Elasticsearch is not responding."""

    def __init__(self, details: dict = None):
        super().__init__(
            code='ELASTICSEARCH_UNAVAILABLE',
            message='Search service unavailable',
            remediation='Elasticsearch is not responding. Try again in a few minutes. If this persists, check the Elasticsearch configuration in Settings > System.',
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details=details
        )


# Rate Limit Error (429)
class RateLimitExceededError(JobAPIError):
    """Raised when rate limit is exceeded."""

    def __init__(self, retry_after: int, limit: str, details: dict = None):
        super().__init__(
            code='RATE_LIMIT_EXCEEDED',
            message='Rate limit exceeded',
            remediation=f'Wait {retry_after} seconds before retrying. Rate limit: {limit}.',
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            details=details
        )
