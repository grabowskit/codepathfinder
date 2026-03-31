"""
Rate limiting for the Jobs API.

Different endpoints have different rate limits based on their impact:
- Job start: 10/hour (expensive operation)
- Job stop: 20/hour (reasonable control)
- Status checks: 120/minute (frequent polling expected)
- Log fetching: 30/minute (expensive I/O)
- Search: 60/minute (match existing MCP rate)
"""

from rest_framework.throttling import UserRateThrottle
from projects.models import ProjectAPIKey


class JobAPIKeyThrottleMixin:
    """
    Mixin to throttle by API key ID instead of user.
    """

    def get_cache_key(self, request, view):
        """Generate cache key based on API key instead of user."""
        if request.auth and isinstance(request.auth, ProjectAPIKey):
            return f'throttle_{self.scope}_{request.auth.id}'
        # Fall back to user-based throttling for session auth
        if request.user and request.user.is_authenticated:
            return f'throttle_{self.scope}_user_{request.user.id}'
        return None


class JobStartThrottle(JobAPIKeyThrottleMixin, UserRateThrottle):
    """
    Rate throttle for job start requests.
    Limit: 10 requests per hour per API key.

    Starting jobs is an expensive operation that creates Kubernetes jobs
    or Docker containers, so we limit it more strictly.
    """
    scope = 'job_start'


class JobStopThrottle(JobAPIKeyThrottleMixin, UserRateThrottle):
    """
    Rate throttle for job stop requests.
    Limit: 20 requests per hour per API key.

    More generous than start since stopping is less resource-intensive.
    """
    scope = 'job_stop'


class JobStatusThrottle(JobAPIKeyThrottleMixin, UserRateThrottle):
    """
    Rate throttle for job status checks.
    Limit: 120 requests per minute per API key.

    Very generous limit since AI agents may poll frequently
    to monitor job progress.
    """
    scope = 'job_status'


class JobLogsThrottle(JobAPIKeyThrottleMixin, UserRateThrottle):
    """
    Rate throttle for log fetching.
    Limit: 30 requests per minute per API key.

    More restrictive because log fetching involves reading
    from Kubernetes pods or Docker containers.
    """
    scope = 'job_logs'


class JobSearchThrottle(JobAPIKeyThrottleMixin, UserRateThrottle):
    """
    Rate throttle for search requests.
    Limit: 60 requests per minute per API key.

    Matches the existing MCP tool proxy rate limit.
    """
    scope = 'job_search'


class JobCreateThrottle(JobAPIKeyThrottleMixin, UserRateThrottle):
    """
    Rate throttle for project creation.
    Limit: 20 requests per hour per API key.

    Prevents spam creation of projects.
    """
    scope = 'job_create'


class BulkOperationThrottle(JobAPIKeyThrottleMixin, UserRateThrottle):
    """
    Rate throttle for bulk operations.
    Limit: 5 requests per hour per API key.

    Very restrictive since bulk operations affect multiple projects.
    """
    scope = 'job_bulk'
