"""
Project API Key Authentication for Django REST Framework

This module provides custom authentication for project-scoped API keys.
API keys are passed in the Authorization header as Bearer tokens.
"""

import logging
from typing import Optional, Tuple
from django.utils import timezone
from rest_framework import authentication, exceptions
from .models import ProjectAPIKey, PathfinderProject

logger = logging.getLogger(__name__)


class ProjectAPIKeyAuthentication(authentication.BaseAuthentication):
    """
    Authentication backend for project-scoped API keys.

    API keys are passed in the Authorization header:
        Authorization: Bearer cpf_abc123_xyz789...

    This backend:
    1. Extracts the API key from the Authorization header
    2. Hashes the key and looks it up in the database
    3. Validates that the key is active
    4. Validates the scope if required_scope is set
    5. Attaches the project to the request
    6. Updates the last_used_at timestamp
    """

    keyword = 'Bearer'
    required_scope = None  # Subclasses can override for scope-specific auth

    def authenticate(self, request) -> Optional[Tuple[PathfinderProject, ProjectAPIKey]]:
        """
        Authenticate the request using a project API key.

        Args:
            request: The incoming HTTP request

        Returns:
            Tuple of (project, api_key) if authentication succeeds, None otherwise

        Raises:
            AuthenticationFailed: If the API key is invalid or inactive
        """
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')

        if not auth_header:
            # No Authorization header - let other auth backends try
            return None

        # Parse the Authorization header
        parts = auth_header.split()

        if len(parts) != 2:
            # Malformed header - let other auth backends try
            return None

        if parts[0] != self.keyword:
            # Not a Bearer token - let other auth backends try
            return None

        api_key_value = parts[1]

        # Validate key format (should start with "cpf_")
        if not api_key_value.startswith('cpf_'):
            raise exceptions.AuthenticationFailed('Invalid API key format')

        # Hash the provided key
        hashed_key = ProjectAPIKey.hash_key(api_key_value)

        # Look up the key in the database
        try:
            api_key = ProjectAPIKey.objects.select_related('project', 'project__user').get(
                hashed_key=hashed_key
            )
        except ProjectAPIKey.DoesNotExist:
            logger.warning(f"Invalid API key attempt: {api_key_value[:15]}...")
            raise exceptions.AuthenticationFailed('Invalid API key')

        # Check if key is active
        if not api_key.is_active:
            logger.warning(f"Inactive API key used: {api_key.prefix}")
            raise exceptions.AuthenticationFailed('API key has been revoked')

        # Check scope if required
        if self.required_scope and not self._check_scope(api_key, self.required_scope):
            logger.warning(f"API key {api_key.prefix} lacks required scope: {self.required_scope}")
            raise exceptions.AuthenticationFailed(
                f'API key does not have {self.required_scope} access. '
                f'Current scope: {api_key.scope}'
            )

        # Update last_used_at timestamp (async to avoid blocking)
        # Note: We'll update this in the view after successful execution
        # to avoid database writes on every auth check

        # Return project as the "user" and api_key as credentials
        # DRF will set request.user = project and request.auth = api_key
        logger.info(f"API key authenticated: {api_key.prefix} for project {api_key.project.name}")

        return (api_key.project, api_key)

    def _check_scope(self, api_key: ProjectAPIKey, required_scope: str) -> bool:
        """
        Check if the API key has the required scope.

        Args:
            api_key: The API key to check
            required_scope: The required scope ('mcp', 'chat', or 'all')

        Returns:
            True if the key has access, False otherwise
        """
        # 'all' scope grants access to everything
        if api_key.scope == 'all':
            return True
        # Exact scope match
        return api_key.scope == required_scope

    def authenticate_header(self, request) -> str:
        """
        Return the WWW-Authenticate header value for 401 responses.

        Args:
            request: The incoming HTTP request

        Returns:
            The authentication header value
        """
        return self.keyword


class ChatAPIKeyAuthentication(ProjectAPIKeyAuthentication):
    """
    Authentication backend specifically for chat endpoints.
    Requires 'chat' or 'all' scope.
    """
    required_scope = 'chat'


class MCPAPIKeyAuthentication(ProjectAPIKeyAuthentication):
    """
    Authentication backend specifically for MCP endpoints.
    Requires 'mcp' or 'all' scope.
    """
    required_scope = 'mcp'
