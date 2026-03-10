from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import UserRateThrottle
from django.shortcuts import get_object_or_404
from django.utils import timezone
from projects.models import PathfinderProject, ProjectAPIKey
from projects.serializers import ProjectAPIKeySerializer, ProjectAPIKeyListSerializer
from projects.authentication import ProjectAPIKeyAuthentication
from mcp_server.tools import execute_tool, ToolError
import logging

logger = logging.getLogger(__name__)


class ProjectPermission(permissions.BasePermission):
    """
    Custom permission to only allow owners of a project to manage it.
    """
    def has_permission(self, request, view):
        project_id = view.kwargs.get('project_id')
        if not project_id:
            return False

        project = get_object_or_404(PathfinderProject, pk=project_id)

        # Check if user is the owner or has shared access
        return project.user == request.user or request.user in project.shared_with.all()


class ProjectAPIKeyListCreateView(generics.ListCreateAPIView):
    """
    GET /api/projects/{project_id}/keys/ - List all API keys for a project
    POST /api/projects/{project_id}/keys/ - Create a new API key
    """
    permission_classes = [permissions.IsAuthenticated, ProjectPermission]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ProjectAPIKeySerializer
        return ProjectAPIKeyListSerializer

    def get_queryset(self):
        project_id = self.kwargs['project_id']
        return ProjectAPIKey.objects.filter(project_id=project_id)

    def perform_create(self, serializer):
        project_id = self.kwargs['project_id']
        project = get_object_or_404(PathfinderProject, pk=project_id)

        # Only allow project owner to create keys
        if project.user != self.request.user:
            raise permissions.PermissionDenied("Only the project owner can create API keys")

        serializer.save(project=project)


class ProjectAPIKeyDeleteView(generics.DestroyAPIView):
    """
    DELETE /api/projects/{project_id}/keys/{key_id}/ - Revoke (delete) an API key
    """
    permission_classes = [permissions.IsAuthenticated, ProjectPermission]
    queryset = ProjectAPIKey.objects.all()
    lookup_url_kwarg = 'key_id'

    def get_queryset(self):
        project_id = self.kwargs['project_id']
        return ProjectAPIKey.objects.filter(project_id=project_id)

    def perform_destroy(self, instance):
        # Only allow project owner to delete keys
        if instance.project.user != self.request.user:
            raise permissions.PermissionDenied("Only the project owner can revoke API keys")

        instance.delete()


class MCPConfigView(APIView):
    """
    GET /api/projects/{project_id}/mcp-config/ - Get Claude Desktop configuration snippet
    """
    permission_classes = [permissions.IsAuthenticated, ProjectPermission]

    def get(self, request, project_id):
        project = get_object_or_404(PathfinderProject, pk=project_id)

        # Generate config snippet
        config = {
            "mcpServers": {
                f"codepathfinder-{project.name.lower().replace(' ', '-')}": {
                    "command": "npx",
                    "args": ["-y", "@codepathfinder/mcp-bridge"],
                    "env": {
                        "CODEPATHFINDER_API_KEY": "YOUR_API_KEY_HERE",
                        "CODEPATHFINDER_API_ENDPOINT": request.build_absolute_uri('/api/v1/mcp/tools/call/')
                    }
                }
            }
        }

        return Response({
            "config": config,
            "instructions": [
                "1. Copy the config above to your Claude Desktop config file:",
                "   - macOS: ~/Library/Application Support/Claude/claude_desktop_config.json",
                "   - Windows: %APPDATA%/Claude/claude_desktop_config.json",
                "2. Replace YOUR_API_KEY_HERE with your actual API key",
                "3. Restart Claude Desktop",
                "4. The MCP server will be available as 'codepathfinder-{}'".format(project.name.lower().replace(' ', '-'))
            ]
        })


class ProjectAPIKeyRateThrottle(UserRateThrottle):
    """
    Rate throttle for project API key requests.
    Limit: 60 requests per minute per API key.
    """
    scope = 'project_api_key'

    def get_cache_key(self, request, view):
        """
        Generate cache key based on API key instead of user.
        """
        if request.auth and isinstance(request.auth, ProjectAPIKey):
            return f'throttle_project_api_key_{request.auth.id}'
        return None  # Don't throttle if no API key


class MCPToolProxyView(APIView):
    """
    MCP Tool Proxy Endpoint

    POST /api/v1/mcp/tools/call/

    This endpoint accepts tool call requests from the MCP bridge and routes them
    to the appropriate Python tool implementation.

    Authentication: Project API Key (Bearer token)
    Rate Limit: 60 requests/minute per API key

    Request Body:
        {
            "name": "tool_name",
            "arguments": {
                "arg1": "value1",
                "arg2": "value2"
            }
        }

    Response:
        {
            "content": [
                {
                    "type": "text",
                    "text": "Tool result content here"
                }
            ]
        }

    Error Response:
        {
            "error": "Error message",
            "tool": "tool_name"
        }
    """

    authentication_classes = [ProjectAPIKeyAuthentication]
    permission_classes = []  # Authentication is sufficient, no additional permissions needed
    throttle_classes = [ProjectAPIKeyRateThrottle]

    def post(self, request):
        """
        Execute a tool and return MCP-formatted response.

        The request.user is the PathfinderProject (set by ProjectAPIKeyAuthentication)
        The request.auth is the ProjectAPIKey instance
        """
        # Extract tool name and arguments
        tool_name = request.data.get('name')
        arguments = request.data.get('arguments', {})

        if not tool_name:
            return Response(
                {'error': 'Tool name is required', 'field': 'name'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get the project and API key from authentication
        project = request.user  # This is PathfinderProject (set by auth backend)
        api_key = request.auth  # This is ProjectAPIKey (set by auth backend)

        # Verify authentication (should be handled by DRF but double-check)
        if not api_key or not isinstance(api_key, ProjectAPIKey):
            return Response(
                {'error': 'Valid API key required'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Log the tool call
        logger.info(
            f"Tool call: {tool_name} | Project: {project.name} | "
            f"API Key: {api_key.prefix} | Args: {list(arguments.keys())}"
        )

        try:
            # Execute the tool
            # Inject the project owner as the user context
            # This allows resolve_project_indices to find accessible projects
            arguments['user'] = project.user
            result = execute_tool(tool_name, arguments)

            # Update last_used_at timestamp for the API key
            api_key.last_used_at = timezone.now()
            api_key.save(update_fields=['last_used_at'])

            # Return MCP-formatted response
            return Response({
                'content': [
                    {
                        'type': 'text',
                        'text': result
                    }
                ]
            }, status=status.HTTP_200_OK)

        except ToolError as e:
            # Tool-specific error (e.g., unknown tool, invalid arguments)
            logger.warning(f"Tool error: {tool_name} - {str(e)}")
            return Response(
                {
                    'error': str(e),
                    'tool': tool_name
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        except Exception as e:
            # Unexpected error
            logger.error(f"Unexpected error executing tool {tool_name}: {e}", exc_info=True)
            return Response(
                {
                    'error': 'Internal server error',
                    'tool': tool_name,
                    'detail': str(e) if request.user.is_staff else 'An error occurred'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
