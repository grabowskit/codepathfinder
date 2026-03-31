"""
Permission classes for the Jobs API.

Implements authorization rules:
- Owner: Full access (start, stop, update, delete)
- Shared user: Read-only (status, logs, search, history)
- Admin: Full access to all projects
"""

from rest_framework import permissions
from projects.models import PathfinderProject, ProjectAPIKey


class IsAuthenticatedOrAPIKey(permissions.BasePermission):
    """
    Custom permission that allows either:
    - Authenticated session users
    - Valid API key authentication

    This replaces IsAuthenticated for endpoints that support both auth methods.
    """

    def has_permission(self, request, view):
        # API key auth
        if isinstance(request.auth, ProjectAPIKey):
            return True

        # Session auth
        if request.user and hasattr(request.user, 'is_authenticated') and request.user.is_authenticated:
            return True

        return False


class JobManagementPermission(permissions.BasePermission):
    """
    Permission class for job management operations.

    Authorization matrix:
    - Owner: Full access
    - Shared users: Read-only (status, logs, search, history)
    - Superuser: Full access to all projects

    Required scope: 'mcp' or 'all'
    """

    # Actions that shared users can perform
    READ_ONLY_ACTIONS = {'status', 'logs', 'search', 'history', 'list', 'retrieve'}

    message = 'You do not have permission to perform this action on this project.'

    def has_permission(self, request, view):
        """Check if the request has permission to access the view."""
        # Superusers always have access
        if hasattr(request, 'user') and hasattr(request.user, 'is_superuser') and request.user.is_superuser:
            return True

        # Check if authenticated via API key
        if isinstance(request.auth, ProjectAPIKey):
            api_key = request.auth

            # Check scope
            if api_key.scope not in ['mcp', 'all']:
                self.message = f"API key scope '{api_key.scope}' is insufficient. Required: 'mcp' or 'all'."
                return False

            return True

        # Session-based auth for web users
        if request.user and request.user.is_authenticated:
            return True

        return False

    def has_object_permission(self, request, view, obj):
        """Check if the request has permission for the specific object."""
        # Superusers always have access
        if hasattr(request, 'user') and hasattr(request.user, 'is_superuser') and request.user.is_superuser:
            return True

        # Determine the project
        if isinstance(obj, PathfinderProject):
            project = obj
        elif hasattr(obj, 'project'):
            project = obj.project
        else:
            return False

        # Get the action name
        action = getattr(view, 'action', None) or view.kwargs.get('action', 'unknown')

        # API key authentication
        if isinstance(request.auth, ProjectAPIKey):
            api_key = request.auth

            # API key must be for this project
            if api_key.project_id != project.id:
                self.message = f'API key is not authorized for project {project.id}.'
                return False

            # Check if this is a read-only action
            if action in self.READ_ONLY_ACTIONS:
                return True

            # For write actions, the API key's project owner must match
            # (API keys can only modify their own project)
            return True

        # Session-based auth
        if request.user and request.user.is_authenticated:
            # Owner has full access
            if project.user == request.user:
                return True

            # Shared users have read-only access
            if request.user in project.shared_with.all():
                if action in self.READ_ONLY_ACTIONS:
                    return True
                self.message = 'Shared access is read-only. Contact the project owner to perform this action.'
                return False

        return False


class IsProjectOwner(permissions.BasePermission):
    """
    Permission that only allows project owners.
    Used for destructive operations like delete.
    """

    message = 'Only the project owner can perform this action.'

    def has_object_permission(self, request, view, obj):
        if isinstance(obj, PathfinderProject):
            project = obj
        elif hasattr(obj, 'project'):
            project = obj.project
        else:
            return False

        # Superusers always have access
        if hasattr(request, 'user') and hasattr(request.user, 'is_superuser') and request.user.is_superuser:
            return True

        # API key auth - check project ownership
        if isinstance(request.auth, ProjectAPIKey):
            return request.auth.project_id == project.id

        # Session auth - check user ownership
        if request.user and request.user.is_authenticated:
            return project.user == request.user

        return False


class CanCreateProject(permissions.BasePermission):
    """
    Permission for creating new projects.
    Any authenticated user or valid API key can create projects.
    """

    def has_permission(self, request, view):
        # API key with 'all' scope can create projects
        if isinstance(request.auth, ProjectAPIKey):
            if request.auth.scope == 'all':
                return True
            self.message = "Creating projects requires an API key with 'all' scope."
            return False

        # Authenticated session users can create projects
        if request.user and request.user.is_authenticated:
            return True

        return False
