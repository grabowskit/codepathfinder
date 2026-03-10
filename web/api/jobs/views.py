"""
Views for the Jobs API.

Provides REST endpoints for managing CodePathFinder indexing jobs.
All responses are optimized for AI agent consumption with:
- Structured data in 'data' field
- Human-readable summary in 'content' field
- HATEOAS links for next actions
- Actionable error messages with remediation steps
"""

import logging
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.db.models import Q
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import SessionAuthentication
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiExample
from drf_spectacular.types import OpenApiTypes

from projects.models import PathfinderProject, ProjectAPIKey
from projects.authentication import ProjectAPIKeyAuthentication
from projects.utils import (
    trigger_indexer_job,
    stop_indexer_job,
    check_and_update_project_status,
    validate_elasticsearch_config,
    delete_elasticsearch_index,
    get_es_client,
)

from .serializers import (
    ProjectCreateSerializer,
    ProjectUpdateSerializer,
    ProjectDetailSerializer,
    JobListItemSerializer,
    JobStartSerializer,
    JobStatusSerializer,
    JobSearchSerializer,
    CrossProjectSearchSerializer,
    BulkStartSerializer,
    BulkStopSerializer,
    JobLogsSerializer,
)
from .permissions import JobManagementPermission, IsProjectOwner, CanCreateProject, IsAuthenticatedOrAPIKey
from .throttling import (
    JobStartThrottle,
    JobStopThrottle,
    JobStatusThrottle,
    JobLogsThrottle,
    JobSearchThrottle,
    JobCreateThrottle,
    BulkOperationThrottle,
)
from .exceptions import (
    JobAPIError,
    ProjectNotFoundError,
    AlreadyRunningError,
    NoRunningJobError,
    ElasticsearchNotConfiguredError,
    IndexNotReadyError,
    AccessDeniedError,
    KubernetesUnavailableError,
)

logger = logging.getLogger(__name__)


def build_links(project, request=None):
    """Build HATEOAS links for a project."""
    base_url = f'/api/v1/jobs/{project.id}'
    links = {
        'self': f'{base_url}/',
        'status': f'{base_url}/status/',
        'history': f'{base_url}/history/',
    }

    if project.status in ['running', 'watching']:
        links['stop'] = f'{base_url}/stop/'
        links['logs'] = f'{base_url}/logs/'
    else:
        links['start'] = f'{base_url}/start/'

    if project.status in ['completed', 'watching']:
        links['search'] = f'{base_url}/search/'

    if project.status == 'failed':
        links['reset'] = f'{base_url}/reset/'

    return links


def format_response(content_text, data, links=None, status_code=status.HTTP_200_OK):
    """Format a standard API response."""
    response = {
        'content': [{'type': 'text', 'text': content_text}],
        'data': data,
    }
    if links:
        response['links'] = links
    return Response(response, status=status_code)


def handle_job_error(exc):
    """Convert JobAPIError to Response."""
    if isinstance(exc, JobAPIError):
        return Response(exc.to_dict(), status=exc.status_code)
    raise exc


from .exceptions import ReadOnlyAccessError

def get_project_for_api_key(request, project_id, require_write_access=False):
    """
    Get project with permission check for API key auth.

    Args:
        request: The HTTP request
        project_id: The project ID
        require_write_access: If True, check that user can modify (not just view)

    Returns:
        The project object

    Raises:
        ProjectNotFoundError: If project doesn't exist
        AccessDeniedError: If user doesn't have access
        ReadOnlyAccessError: If require_write_access and user is shared (read-only)
    """
    try:
        project = PathfinderProject.objects.select_related('user').get(pk=project_id)
    except PathfinderProject.DoesNotExist:
        raise ProjectNotFoundError(project_id=project_id)

    # Check access
    if isinstance(request.auth, ProjectAPIKey):
        if request.auth.project_id != project.id:
            raise AccessDeniedError(project_id=project_id)
        # API key owners have full access
    elif request.user and request.user.is_authenticated:
        is_owner = project.user == request.user
        is_shared = request.user in project.shared_with.all()
        is_superuser = request.user.is_superuser

        if not (is_owner or is_shared or is_superuser):
            raise AccessDeniedError(project_id=project_id)

        # Check write access for shared users
        if require_write_access and is_shared and not is_owner and not is_superuser:
            raise ReadOnlyAccessError()

    return project


class JobListCreateView(APIView):
    """
    GET  /api/v1/jobs/     - List all accessible projects with status
    POST /api/v1/jobs/     - Create a new project

    Query Parameters (GET):
        status: Filter by status (pending, running, completed, failed, watching, stopped)
        is_enabled: Filter by enabled state (true/false)
        page: Page number (default: 1)
        page_size: Items per page (default: 20, max: 100)
    """
    authentication_classes = [SessionAuthentication, ProjectAPIKeyAuthentication]
    permission_classes = [IsAuthenticatedOrAPIKey]

    def get_throttles(self):
        if self.request.method == 'POST':
            return [JobCreateThrottle()]
        return [JobStatusThrottle()]

    def get_queryset(self, request):
        """Get projects accessible to the current user/API key."""
        if isinstance(request.auth, ProjectAPIKey):
            # API key can only see its own project
            return PathfinderProject.objects.filter(pk=request.auth.project_id)

        # Session auth - show owned and shared projects
        if request.user.is_superuser:
            queryset = PathfinderProject.objects.all()
        else:
            queryset = PathfinderProject.objects.filter(
                Q(user=request.user) | Q(shared_with=request.user)
            ).distinct()

        return queryset

    @extend_schema(
        operation_id='listProjects',
        summary='List all projects with status',
        description='Returns all projects accessible to the current API key with their current status.',
        tags=['Projects'],
        parameters=[
            OpenApiParameter('status', OpenApiTypes.STR, description='Filter by status'),
            OpenApiParameter('is_enabled', OpenApiTypes.BOOL, description='Filter by enabled state'),
            OpenApiParameter('page', OpenApiTypes.INT, description='Page number'),
            OpenApiParameter('page_size', OpenApiTypes.INT, description='Items per page (max 100)'),
        ],
    )
    def get(self, request):
        """List all accessible projects with their job status."""
        queryset = self.get_queryset(request)

        # Apply filters
        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        is_enabled = request.query_params.get('is_enabled')
        if is_enabled is not None:
            queryset = queryset.filter(is_enabled=is_enabled.lower() == 'true')

        # Update status for running projects
        for project in queryset.filter(status__in=['running', 'watching']):
            try:
                check_and_update_project_status(project)
            except Exception as e:
                logger.warning(f"Failed to update status for project {project.id}: {e}")

        # Refresh queryset after status updates
        queryset = self.get_queryset(request)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if is_enabled is not None:
            queryset = queryset.filter(is_enabled=is_enabled.lower() == 'true')

        # Pagination
        page = int(request.query_params.get('page', 1))
        page_size = min(int(request.query_params.get('page_size', 20)), 100)
        total_count = queryset.count()

        start = (page - 1) * page_size
        end = start + page_size
        projects = queryset.order_by('-updated_at')[start:end]

        # Build summary
        all_projects = self.get_queryset(request)
        summary = {
            'pending': all_projects.filter(status='pending').count(),
            'running': all_projects.filter(status='running').count(),
            'completed': all_projects.filter(status='completed').count(),
            'failed': all_projects.filter(status='failed').count(),
            'watching': all_projects.filter(status='watching').count(),
            'stopped': all_projects.filter(status='stopped').count(),
        }

        serializer = JobListItemSerializer(projects, many=True)

        content_text = f"Found {total_count} project(s)"
        if summary['running']:
            content_text += f": {summary['running']} running"
        if summary['completed']:
            content_text += f", {summary['completed']} completed"

        return format_response(
            content_text=content_text,
            data={
                'projects': serializer.data,
                'pagination': {
                    'page': page,
                    'page_size': page_size,
                    'total_count': total_count,
                    'total_pages': (total_count + page_size - 1) // page_size,
                },
                'summary': summary,
            },
            links={
                'self': '/api/v1/jobs/',
                'create': '/api/v1/jobs/',
                'bulk_start': '/api/v1/jobs/bulk/start/',
                'bulk_stop': '/api/v1/jobs/bulk/stop/',
                'search': '/api/v1/jobs/search/',
            }
        )

    @extend_schema(
        operation_id='createProject',
        summary='Create a new project',
        description='Create a new project with optional auto-start for immediate indexing.',
        tags=['Projects'],
        request=ProjectCreateSerializer,
    )
    def post(self, request):
        """Create a new project."""
        # Check permission to create
        if isinstance(request.auth, ProjectAPIKey):
            if request.auth.scope != 'all':
                return Response({
                    'error': {
                        'code': 'SCOPE_INSUFFICIENT',
                        'message': "Creating projects requires 'all' scope",
                        'remediation': "Create an API key with 'all' scope to create new projects.",
                    }
                }, status=status.HTTP_403_FORBIDDEN)
            owner = request.auth.project.user
        else:
            owner = request.user

        serializer = ProjectCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'error': {
                    'code': 'INVALID_OPTIONS',
                    'message': 'Invalid project data',
                    'details': serializer.errors,
                    'remediation': 'Check the field requirements and try again.',
                }
            }, status=status.HTTP_400_BAD_REQUEST)

        # Extract auto_start and options before saving
        auto_start = serializer.validated_data.pop('auto_start', False)
        start_options = serializer.validated_data.pop('options', {})

        # Create project
        project = serializer.save(user=owner)
        logger.info(f"Project created via API: {project.name} (ID: {project.id})")

        response_data = ProjectDetailSerializer(project).data
        content_text = f"Project '{project.name}' created successfully"

        # Auto-start if requested
        if auto_start:
            # Apply start options
            if start_options:
                for key, value in start_options.items():
                    if hasattr(project, key) and value is not None:
                        setattr(project, key, value)
                project.save()

            # Validate ES config
            is_valid, error_msg = validate_elasticsearch_config()
            if not is_valid:
                content_text += f". Auto-start skipped: {error_msg}"
            else:
                project.status = 'running'
                project.save()
                success, msg = trigger_indexer_job(project)
                if success:
                    content_text += " and indexing started"
                    response_data['status'] = 'running'
                else:
                    project.status = 'pending'
                    project.save()
                    content_text += f". Auto-start failed: {msg}"

        return format_response(
            content_text=content_text,
            data=response_data,
            links=build_links(project),
            status_code=status.HTTP_201_CREATED
        )


class ProjectDetailView(APIView):
    """
    GET    /api/v1/jobs/{project_id}/  - Get project details
    PATCH  /api/v1/jobs/{project_id}/  - Update project settings
    DELETE /api/v1/jobs/{project_id}/  - Delete project and index
    """
    authentication_classes = [SessionAuthentication, ProjectAPIKeyAuthentication]
    permission_classes = [IsAuthenticatedOrAPIKey, JobManagementPermission]
    throttle_classes = [JobStatusThrottle]

    def get(self, request, project_id):
        """Get project details."""
        try:
            project = get_project_for_api_key(request, project_id)
        except JobAPIError as e:
            return handle_job_error(e)

        # Update status if running
        if project.status in ['running', 'watching']:
            try:
                check_and_update_project_status(project)
                project.refresh_from_db()
            except Exception as e:
                logger.warning(f"Failed to update status: {e}")

        serializer = ProjectDetailSerializer(project)
        return format_response(
            content_text=f"Project '{project.name}' details",
            data=serializer.data,
            links=build_links(project)
        )

    def patch(self, request, project_id):
        """Update project settings."""
        try:
            project = get_project_for_api_key(request, project_id)
        except JobAPIError as e:
            return handle_job_error(e)

        # Check ownership for updates
        if isinstance(request.auth, ProjectAPIKey):
            if request.auth.project_id != project.id:
                raise AccessDeniedError(project_id=project_id)
        elif not (project.user == request.user or request.user.is_superuser):
            return Response({
                'error': {
                    'code': 'READ_ONLY_ACCESS',
                    'message': 'Shared access is read-only',
                    'remediation': 'Contact the project owner to update settings.',
                }
            }, status=status.HTTP_403_FORBIDDEN)

        serializer = ProjectUpdateSerializer(project, data=request.data, partial=True)
        if not serializer.is_valid():
            return Response({
                'error': {
                    'code': 'INVALID_OPTIONS',
                    'message': 'Invalid update data',
                    'details': serializer.errors,
                    'remediation': 'Check the field requirements and try again.',
                }
            }, status=status.HTTP_400_BAD_REQUEST)

        serializer.save()
        logger.info(f"Project updated via API: {project.name} (ID: {project.id})")

        return format_response(
            content_text=f"Project '{project.name}' updated successfully",
            data=ProjectDetailSerializer(project).data,
            links=build_links(project)
        )

    def delete(self, request, project_id):
        """Delete project and its index."""
        try:
            project = get_project_for_api_key(request, project_id)
        except JobAPIError as e:
            return handle_job_error(e)

        # Check ownership for delete
        if isinstance(request.auth, ProjectAPIKey):
            if request.auth.project_id != project.id:
                raise AccessDeniedError(project_id=project_id)
        elif not (project.user == request.user or request.user.is_superuser):
            return Response({
                'error': {
                    'code': 'READ_ONLY_ACCESS',
                    'message': 'Only the project owner can delete projects',
                    'remediation': 'Contact the project owner to delete this project.',
                }
            }, status=status.HTTP_403_FORBIDDEN)

        project_name = project.name

        # Stop any running job
        if project.status in ['running', 'watching']:
            stop_indexer_job(project)

        # Delete Elasticsearch index
        delete_elasticsearch_index(project)

        # Delete project
        project.delete()
        logger.info(f"Project deleted via API: {project_name} (ID: {project_id})")

        return format_response(
            content_text=f"Project '{project_name}' deleted successfully",
            data={'deleted_project_id': project_id, 'deleted_project_name': project_name},
            links={'list': '/api/v1/jobs/', 'create': '/api/v1/jobs/'}
        )


class JobStartView(APIView):
    """
    POST /api/v1/jobs/{project_id}/start/

    Start an indexing job for the specified project.

    Request Body:
        {
            "clean_index": false,
            "pull_before_index": false,
            "watch_mode": false,
            "branch": "main",
            "concurrency": 4
        }
    """
    authentication_classes = [SessionAuthentication, ProjectAPIKeyAuthentication]
    permission_classes = [IsAuthenticatedOrAPIKey, JobManagementPermission]
    throttle_classes = [JobStartThrottle]

    def post(self, request, project_id):
        try:
            project = get_project_for_api_key(request, project_id, require_write_access=True)

            # Check if already running
            if project.status in ['running', 'watching']:
                raise AlreadyRunningError(project_id=project_id, current_status=project.status)

            # Validate Elasticsearch configuration
            is_valid, error_msg = validate_elasticsearch_config()
            if not is_valid:
                raise ElasticsearchNotConfiguredError()
        except JobAPIError as e:
            return handle_job_error(e)

        # Parse and apply options
        serializer = JobStartSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'error': {
                    'code': 'INVALID_OPTIONS',
                    'message': 'Invalid job options',
                    'details': serializer.errors,
                    'remediation': 'Check the option values. concurrency: 1-16, branch: string.',
                }
            }, status=status.HTTP_400_BAD_REQUEST)

        # Apply options to project
        options = serializer.validated_data
        for key in ['clean_index', 'pull_before_index', 'watch_mode', 'branch', 'concurrency']:
            if key in options and options[key] is not None:
                setattr(project, key, options[key])

        # Update status and save
        project.status = 'running'
        project.save()

        # Trigger the job
        success, msg = trigger_indexer_job(project)

        if not success:
            # Rollback status
            project.status = 'pending'
            project.save()

            if 'kubernetes' in msg.lower() or 'docker' in msg.lower():
                raise KubernetesUnavailableError(details={'message': msg})

            return Response({
                'error': {
                    'code': 'JOB_START_FAILED',
                    'message': f'Failed to start indexing job: {msg}',
                    'remediation': 'Check the job configuration and try again. If this persists, contact support.',
                }
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        logger.info(f"Job started via API: {project.name} (ID: {project.id})")

        return format_response(
            content_text=f"Indexing job started for project '{project.name}'",
            data={
                'project_id': project.id,
                'project_name': project.name,
                'status': 'running',
                'started_at': timezone.now().isoformat(),
                'options': {
                    'clean_index': project.clean_index,
                    'pull_before_index': project.pull_before_index,
                    'watch_mode': project.watch_mode,
                    'branch': project.branch,
                    'concurrency': project.concurrency,
                },
            },
            links=build_links(project),
            status_code=status.HTTP_202_ACCEPTED
        )


class JobStopView(APIView):
    """
    POST /api/v1/jobs/{project_id}/stop/

    Stop a running indexing job.
    """
    authentication_classes = [SessionAuthentication, ProjectAPIKeyAuthentication]
    permission_classes = [IsAuthenticatedOrAPIKey, JobManagementPermission]
    throttle_classes = [JobStopThrottle]

    def post(self, request, project_id):
        try:
            project = get_project_for_api_key(request, project_id, require_write_access=True)

            # Check if running
            if project.status not in ['running', 'watching']:
                raise NoRunningJobError(project_id=project_id, current_status=project.status)
        except JobAPIError as e:
            return handle_job_error(e)

        previous_status = project.status

        # Stop the job
        success, msg = stop_indexer_job(project)

        if not success:
            # Job might have already completed
            if 'not found' in msg.lower():
                check_and_update_project_status(project)
                project.refresh_from_db()
                return format_response(
                    content_text=f"Job already completed for project '{project.name}'",
                    data={
                        'project_id': project.id,
                        'project_name': project.name,
                        'status': project.status,
                    },
                    links=build_links(project)
                )

            return Response({
                'error': {
                    'code': 'JOB_STOP_FAILED',
                    'message': f'Failed to stop job: {msg}',
                    'remediation': 'The job may have already completed. Check status: GET /api/v1/jobs/{project_id}/status/',
                }
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Update status
        project.status = 'stopped'
        project.save()

        logger.info(f"Job stopped via API: {project.name} (ID: {project.id})")

        return format_response(
            content_text=f"Indexing job stopped for project '{project.name}'",
            data={
                'project_id': project.id,
                'project_name': project.name,
                'previous_status': previous_status,
                'new_status': 'stopped',
                'stopped_at': timezone.now().isoformat(),
            },
            links=build_links(project)
        )


class JobStatusView(APIView):
    """
    GET /api/v1/jobs/{project_id}/status/

    Get current job status with progress information.

    Query Parameters:
        include_logs: boolean - Include last 50 lines of logs (default: false)
    """
    authentication_classes = [SessionAuthentication, ProjectAPIKeyAuthentication]
    permission_classes = [IsAuthenticatedOrAPIKey, JobManagementPermission]
    throttle_classes = [JobStatusThrottle]

    def get(self, request, project_id):
        try:
            project = get_project_for_api_key(request, project_id)
        except JobAPIError as e:
            return handle_job_error(e)

        # Update status if running
        if project.status in ['running', 'watching']:
            try:
                check_and_update_project_status(project)
                project.refresh_from_db()
            except Exception as e:
                logger.warning(f"Failed to update status: {e}")

        # Get index stats if available
        es_stats = None
        if project.status in ['completed', 'watching', 'running']:
            try:
                es_client = get_es_client()
                if es_client and project.custom_index_name:
                    if es_client.indices.exists(index=project.custom_index_name):
                        stats = es_client.indices.stats(index=project.custom_index_name)
                        index_stats = stats['indices'].get(project.custom_index_name, {})
                        primaries = index_stats.get('primaries', {})
                        es_stats = {
                            'document_count': primaries.get('docs', {}).get('count', 0),
                            'index_size_mb': round(primaries.get('store', {}).get('size_in_bytes', 0) / (1024 * 1024), 2),
                        }
            except Exception as e:
                logger.warning(f"Failed to get ES stats: {e}")

        # Build status text
        status_text = f"Project '{project.name}' is {project.status}"
        if project.status == 'running' and es_stats:
            status_text += f" ({es_stats['document_count']} documents indexed)"

        data = {
            'project_id': project.id,
            'project_name': project.name,
            'repository_url': project.repository_url,
            'status': project.status,
            'is_enabled': project.is_enabled,
            'index_name': project.custom_index_name,
            'options': {
                'clean_index': project.clean_index,
                'pull_before_index': project.pull_before_index,
                'watch_mode': project.watch_mode,
                'branch': project.branch,
                'concurrency': project.concurrency,
            },
        }

        if es_stats:
            data['elasticsearch'] = es_stats

        return format_response(
            content_text=status_text,
            data=data,
            links=build_links(project)
        )


class JobResetView(APIView):
    """
    POST /api/v1/jobs/{project_id}/reset/

    Reset a failed or stuck project back to pending status.
    """
    authentication_classes = [SessionAuthentication, ProjectAPIKeyAuthentication]
    permission_classes = [IsAuthenticatedOrAPIKey, JobManagementPermission]
    throttle_classes = [JobStopThrottle]

    def post(self, request, project_id):
        try:
            project = get_project_for_api_key(request, project_id, require_write_access=True)
        except JobAPIError as e:
            return handle_job_error(e)

        previous_status = project.status

        # Can't reset running jobs
        if project.status in ['running', 'watching']:
            return Response({
                'error': {
                    'code': 'CANNOT_RESET_RUNNING',
                    'message': 'Cannot reset a running job',
                    'remediation': f'Stop the job first: POST /api/v1/jobs/{project_id}/stop/',
                }
            }, status=status.HTTP_400_BAD_REQUEST)

        # Reset to pending
        project.status = 'pending'
        project.save()

        logger.info(f"Project reset via API: {project.name} (ID: {project.id})")

        return format_response(
            content_text=f"Project '{project.name}' reset to pending status",
            data={
                'project_id': project.id,
                'project_name': project.name,
                'previous_status': previous_status,
                'new_status': 'pending',
                'reset_at': timezone.now().isoformat(),
            },
            links=build_links(project)
        )


class JobLogsView(APIView):
    """
    GET /api/v1/jobs/{project_id}/logs/

    Fetch job logs. Supports SSE streaming.

    Query Parameters:
        tail: int - Number of lines to return (default: 100, max: 500)
        follow: boolean - Stream logs in real-time via SSE (default: false)
    """
    authentication_classes = [SessionAuthentication, ProjectAPIKeyAuthentication]
    permission_classes = [IsAuthenticatedOrAPIKey, JobManagementPermission]
    throttle_classes = [JobLogsThrottle]

    def get(self, request, project_id):
        try:
            project = get_project_for_api_key(request, project_id)
        except JobAPIError as e:
            return handle_job_error(e)

        tail = min(int(request.query_params.get('tail', 100)), 500)
        follow = request.query_params.get('follow', 'false').lower() == 'true'

        # Get logs from K8s or Docker
        logs = self._get_logs(project, tail)

        if follow:
            # Return SSE streaming response
            return self._stream_logs(project)

        return format_response(
            content_text=f"Showing last {len(logs)} log lines for project '{project.name}'",
            data={
                'project_id': project.id,
                'project_name': project.name,
                'status': project.status,
                'logs': logs,
                'truncated': len(logs) >= tail,
            },
            links=build_links(project)
        )

    def _get_logs(self, project, tail=100):
        """Fetch logs from K8s or Docker."""
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

    def _stream_logs(self, project):
        """Return SSE streaming response for logs."""
        from django.http import StreamingHttpResponse
        import json
        import time

        def event_stream():
            import docker
            from kubernetes import client, config as k8s_config

            try:
                # Try K8s first
                try:
                    k8s_config.load_incluster_config()
                except:
                    try:
                        k8s_config.load_kube_config()
                    except:
                        # Docker streaming
                        docker_client = docker.from_env()
                        containers = docker_client.containers.list(
                            filters={"label": [f"app=indexer-cli", f"project-id={project.id}"]}
                        )

                        if containers:
                            container = containers[0]
                            for line in container.logs(stream=True, follow=True):
                                log_entry = {
                                    'timestamp': timezone.now().isoformat(),
                                    'level': 'INFO',
                                    'message': line.decode('utf-8').strip()
                                }
                                yield f"event: log\ndata: {json.dumps(log_entry)}\n\n"
                        return

                # K8s streaming
                v1 = client.CoreV1Api()
                namespace = "code-pathfinder"
                label_selector = f"app=indexer-cli,project-id={project.id}"

                pods = v1.list_namespaced_pod(namespace=namespace, label_selector=label_selector)

                if pods.items:
                    pod = pods.items[0]
                    for line in v1.read_namespaced_pod_log(
                        name=pod.metadata.name,
                        namespace=namespace,
                        follow=True,
                        _preload_content=False
                    ).stream():
                        log_entry = {
                            'timestamp': timezone.now().isoformat(),
                            'level': 'INFO',
                            'message': line.decode('utf-8').strip()
                        }
                        yield f"event: log\ndata: {json.dumps(log_entry)}\n\n"

            except Exception as e:
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

            # Send done event
            project.refresh_from_db()
            yield f"event: done\ndata: {json.dumps({'final_status': project.status})}\n\n"

        response = StreamingHttpResponse(
            event_stream(),
            content_type='text/event-stream'
        )
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        return response


class JobHistoryView(APIView):
    """
    GET /api/v1/jobs/{project_id}/history/

    Query past job runs for a project.

    Query Parameters:
        start_date: datetime - Filter runs starting after this date
        end_date: datetime - Filter runs ending before this date
        status: string - Filter by final status
        page: int - Page number (default: 1)
        page_size: int - Items per page (default: 20, max: 100)
    """
    authentication_classes = [SessionAuthentication, ProjectAPIKeyAuthentication]
    permission_classes = [IsAuthenticatedOrAPIKey, JobManagementPermission]
    throttle_classes = [JobStatusThrottle]

    def get(self, request, project_id):
        try:
            project = get_project_for_api_key(request, project_id)
        except JobAPIError as e:
            return handle_job_error(e)

        # Note: JobRun model needs to be created for full history
        # For now, return current status as a single "run"
        runs = [{
            'run_id': 1,
            'job_id': f'job-{project.id}',
            'started_at': project.updated_at.isoformat() if project.updated_at else None,
            'completed_at': project.updated_at.isoformat() if project.status in ['completed', 'failed', 'stopped'] else None,
            'final_status': project.status,
            'options': {
                'clean_index': project.clean_index,
                'pull_before_index': project.pull_before_index,
                'watch_mode': project.watch_mode,
                'branch': project.branch,
                'concurrency': project.concurrency,
            },
            'result': {},
        }]

        return format_response(
            content_text=f"Found {len(runs)} job run(s) for project '{project.name}'",
            data={
                'project_id': project.id,
                'project_name': project.name,
                'runs': runs,
                'pagination': {
                    'page': 1,
                    'page_size': 20,
                    'total_count': len(runs),
                    'total_pages': 1,
                },
            },
            links=build_links(project)
        )


class JobSearchView(APIView):
    """
    POST /api/v1/jobs/{project_id}/search/

    Search indexed content in a specific project.

    Request Body:
        {
            "query": "authentication middleware",
            "size": 10,
            "search_type": "semantic"
        }
    """
    authentication_classes = [SessionAuthentication, ProjectAPIKeyAuthentication]
    permission_classes = [IsAuthenticatedOrAPIKey, JobManagementPermission]
    throttle_classes = [JobSearchThrottle]

    def post(self, request, project_id):
        try:
            project = get_project_for_api_key(request, project_id)

            # Check if index is ready
            if project.status not in ['completed', 'watching']:
                raise IndexNotReadyError(project_id=project_id, current_status=project.status)
        except JobAPIError as e:
            return handle_job_error(e)

        serializer = JobSearchSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'error': {
                    'code': 'INVALID_OPTIONS',
                    'message': 'Invalid search parameters',
                    'details': serializer.errors,
                    'remediation': 'Check the search parameters and try again.',
                }
            }, status=status.HTTP_400_BAD_REQUEST)

        query = serializer.validated_data['query']
        size = serializer.validated_data.get('size', 10)
        search_type = serializer.validated_data.get('search_type', 'semantic')

        # Perform search
        try:
            results = self._search(project, query, size, search_type)
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return Response({
                'error': {
                    'code': 'SEARCH_FAILED',
                    'message': f'Search failed: {str(e)}',
                    'remediation': 'Try again later. If this persists, check the index status.',
                }
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return format_response(
            content_text=f"Found {len(results)} results for '{query}' in project '{project.name}'",
            data={
                'project_id': project.id,
                'project_name': project.name,
                'query': query,
                'total_results': len(results),
                'results': results,
            },
            links=build_links(project)
        )

    def _search(self, project, query, size, search_type):
        """Perform search on project index."""
        es_client = get_es_client()
        if not es_client:
            raise Exception("Could not connect to Elasticsearch")

        index_name = project.custom_index_name
        if not index_name:
            raise Exception("Project has no index")

        # Build query based on search type
        if search_type == 'semantic':
            es_query = {
                "query": {
                    "multi_match": {
                        "query": query,
                        "fields": ["content", "semantic_text"],
                        "type": "best_fields"
                    }
                },
                "size": size
            }
        elif search_type == 'symbol':
            es_query = {
                "query": {
                    "nested": {
                        "path": "symbols",
                        "query": {
                            "match": {
                                "symbols.name": query
                            }
                        }
                    }
                },
                "size": size
            }
        else:  # keyword
            es_query = {
                "query": {
                    "match": {
                        "content": query
                    }
                },
                "size": size
            }

        response = es_client.search(index=index_name, body=es_query)

        results = []
        for hit in response['hits']['hits']:
            source = hit['_source']
            results.append({
                'file_path': source.get('filePath', ''),
                'start_line': source.get('startLine', 0),
                'end_line': source.get('endLine', 0),
                'kind': source.get('kind', ''),
                'score': hit['_score'],
                'content': source.get('content', '')[:500],  # Truncate content
                'symbols': [s.get('name', '') for s in source.get('symbols', [])][:5],
            })

        return results


class CrossProjectSearchView(APIView):
    """
    POST /api/v1/jobs/search/

    Search across all accessible projects.

    Request Body:
        {
            "query": "authentication",
            "project_ids": [1, 2],
            "size": 20
        }
    """
    authentication_classes = [SessionAuthentication, ProjectAPIKeyAuthentication]
    permission_classes = [IsAuthenticatedOrAPIKey]
    throttle_classes = [JobSearchThrottle]

    def post(self, request):
        serializer = CrossProjectSearchSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'error': {
                    'code': 'INVALID_OPTIONS',
                    'message': 'Invalid search parameters',
                    'details': serializer.errors,
                    'remediation': 'Check the search parameters and try again.',
                }
            }, status=status.HTTP_400_BAD_REQUEST)

        query = serializer.validated_data['query']
        size = serializer.validated_data.get('size', 10)
        project_ids = serializer.validated_data.get('project_ids', [])

        # Get accessible projects
        if isinstance(request.auth, ProjectAPIKey):
            projects = PathfinderProject.objects.filter(pk=request.auth.project_id)
        elif request.user.is_superuser:
            projects = PathfinderProject.objects.all()
        else:
            projects = PathfinderProject.objects.filter(
                Q(user=request.user) | Q(shared_with=request.user)
            ).distinct()

        # Filter by project_ids if provided
        if project_ids:
            projects = projects.filter(pk__in=project_ids)

        # Only search completed/watching projects
        projects = projects.filter(status__in=['completed', 'watching'])

        if not projects.exists():
            return format_response(
                content_text="No searchable projects found",
                data={'query': query, 'total_results': 0, 'results': []},
                links={'list': '/api/v1/jobs/'}
            )

        # Search each project
        all_results = []
        es_client = get_es_client()

        for project in projects:
            if not project.custom_index_name:
                continue

            try:
                es_query = {
                    "query": {
                        "multi_match": {
                            "query": query,
                            "fields": ["content", "semantic_text"],
                            "type": "best_fields"
                        }
                    },
                    "size": size
                }

                response = es_client.search(index=project.custom_index_name, body=es_query)

                for hit in response['hits']['hits']:
                    source = hit['_source']
                    all_results.append({
                        'project_id': project.id,
                        'project_name': project.name,
                        'file_path': source.get('filePath', ''),
                        'start_line': source.get('startLine', 0),
                        'end_line': source.get('endLine', 0),
                        'kind': source.get('kind', ''),
                        'score': hit['_score'],
                        'content': source.get('content', '')[:500],
                    })

            except Exception as e:
                logger.warning(f"Failed to search project {project.id}: {e}")

        # Sort by score and limit
        all_results.sort(key=lambda x: x['score'], reverse=True)
        all_results = all_results[:size]

        return format_response(
            content_text=f"Found {len(all_results)} results for '{query}' across {projects.count()} project(s)",
            data={
                'query': query,
                'projects_searched': projects.count(),
                'total_results': len(all_results),
                'results': all_results,
            },
            links={'list': '/api/v1/jobs/'}
        )


class BulkStartView(APIView):
    """
    POST /api/v1/jobs/bulk/start/

    Start indexing jobs for multiple projects.

    Request Body:
        {
            "project_ids": [1, 2, 3],
            "options": {
                "clean_index": false,
                "concurrency": 4
            }
        }
    """
    authentication_classes = [SessionAuthentication, ProjectAPIKeyAuthentication]
    permission_classes = [IsAuthenticatedOrAPIKey]
    throttle_classes = [BulkOperationThrottle]

    def post(self, request):
        serializer = BulkStartSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'error': {
                    'code': 'INVALID_OPTIONS',
                    'message': 'Invalid bulk start parameters',
                    'details': serializer.errors,
                    'remediation': 'Provide project_ids (list of integers, max 10) and optional options.',
                }
            }, status=status.HTTP_400_BAD_REQUEST)

        project_ids = serializer.validated_data['project_ids']
        options = serializer.validated_data.get('options', {})

        # Validate ES config once
        is_valid, error_msg = validate_elasticsearch_config()
        if not is_valid:
            raise ElasticsearchNotConfiguredError()

        results = []
        for project_id in project_ids:
            try:
                project = get_project_for_api_key(request, project_id)

                if project.status in ['running', 'watching']:
                    results.append({
                        'project_id': project_id,
                        'success': False,
                        'error': 'Already running',
                    })
                    continue

                # Apply options
                for key, value in options.items():
                    if hasattr(project, key) and value is not None:
                        setattr(project, key, value)

                project.status = 'running'
                project.save()

                success, msg = trigger_indexer_job(project)
                if not success:
                    project.status = 'pending'
                    project.save()
                    results.append({
                        'project_id': project_id,
                        'success': False,
                        'error': msg,
                    })
                else:
                    results.append({
                        'project_id': project_id,
                        'project_name': project.name,
                        'success': True,
                        'status': 'running',
                    })

            except JobAPIError as e:
                results.append({
                    'project_id': project_id,
                    'success': False,
                    'error': e.message,
                })
            except Exception as e:
                results.append({
                    'project_id': project_id,
                    'success': False,
                    'error': str(e),
                })

        successful = sum(1 for r in results if r.get('success'))

        return format_response(
            content_text=f"Started {successful}/{len(project_ids)} jobs",
            data={'results': results},
            links={'list': '/api/v1/jobs/', 'bulk_stop': '/api/v1/jobs/bulk/stop/'}
        )


class BulkStopView(APIView):
    """
    POST /api/v1/jobs/bulk/stop/

    Stop indexing jobs for multiple projects.

    Request Body:
        {
            "project_ids": [1, 2, 3]
        }
    """
    authentication_classes = [SessionAuthentication, ProjectAPIKeyAuthentication]
    permission_classes = [IsAuthenticatedOrAPIKey]
    throttle_classes = [BulkOperationThrottle]

    def post(self, request):
        serializer = BulkStopSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'error': {
                    'code': 'INVALID_OPTIONS',
                    'message': 'Invalid bulk stop parameters',
                    'details': serializer.errors,
                    'remediation': 'Provide project_ids (list of integers, max 10).',
                }
            }, status=status.HTTP_400_BAD_REQUEST)

        project_ids = serializer.validated_data['project_ids']

        results = []
        for project_id in project_ids:
            try:
                project = get_project_for_api_key(request, project_id)

                if project.status not in ['running', 'watching']:
                    results.append({
                        'project_id': project_id,
                        'success': False,
                        'error': f'Not running (status: {project.status})',
                    })
                    continue

                success, msg = stop_indexer_job(project)
                if success:
                    project.status = 'stopped'
                    project.save()
                    results.append({
                        'project_id': project_id,
                        'project_name': project.name,
                        'success': True,
                        'status': 'stopped',
                    })
                else:
                    results.append({
                        'project_id': project_id,
                        'success': False,
                        'error': msg,
                    })

            except JobAPIError as e:
                results.append({
                    'project_id': project_id,
                    'success': False,
                    'error': e.message,
                })
            except Exception as e:
                results.append({
                    'project_id': project_id,
                    'success': False,
                    'error': str(e),
                })

        successful = sum(1 for r in results if r.get('success'))

        return format_response(
            content_text=f"Stopped {successful}/{len(project_ids)} jobs",
            data={'results': results},
            links={'list': '/api/v1/jobs/', 'bulk_start': '/api/v1/jobs/bulk/start/'}
        )
