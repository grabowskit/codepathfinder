"""
OAuth 2.1 Metadata Views for MCP 2025-06-18 Specification

Implements:
- RFC9728: OAuth 2.0 Protected Resource Metadata
- RFC8414: OAuth 2.0 Authorization Server Metadata
"""

from django.http import JsonResponse
from django.views import View
from django.urls import reverse


class ProtectedResourceMetadataView(View):
    """
    RFC9728: OAuth 2.0 Protected Resource Metadata

    Endpoint: /.well-known/oauth-protected-resource

    Tells MCP clients which authorization server(s) can issue tokens
    for this protected resource.

    Note: Returns 404 for internal Docker requests (host=web or web:8000)
    to allow internal services to use Bearer tokens without OAuth flow.
    """

    def get(self, request):
        # Check if this is an internal Docker request
        # Internal services (like LibreChat) should use Bearer token directly
        # without OAuth discovery flow
        host = request.get_host()
        if host in ('web', 'web:8000', 'web:80'):
            from django.http import HttpResponseNotFound
            return HttpResponseNotFound()

        # Build the base URL for the authorization server
        base_url = request.build_absolute_uri('/').rstrip('/')

        metadata = {
            "resource": base_url,
            "authorization_servers": [
                base_url  # Issuer URL, client will append /.well-known/oauth-authorization-server
            ],
            "bearer_methods_supported": ["header"],
            "resource_documentation": f"{base_url}/docs/mcp",
        }

        response = JsonResponse(metadata)
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        return response
    
    def options(self, request):
        response = JsonResponse({})
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
        return response


class AuthorizationServerMetadataView(View):
    """
    RFC8414: OAuth 2.0 Authorization Server Metadata
    
    Endpoint: /.well-known/oauth-authorization-server
    
    Provides OAuth 2.1 server configuration for MCP clients.
    Uses django-oauth-toolkit endpoints.
    """
    
    def get(self, request):
        base_url = request.build_absolute_uri('/').rstrip('/')
        
        metadata = {
            "issuer": base_url,
            "authorization_endpoint": f"{base_url}/o/authorize/",
            "token_endpoint": f"{base_url}/o/token/",
            "revocation_endpoint": f"{base_url}/o/revoke_token/",
            "introspection_endpoint": f"{base_url}/o/introspect/",
            "registration_endpoint": f"{base_url}/o/register/",  # RFC 7591 DCR endpoint
            "scopes_supported": ["read", "write", "mcp"],
            "response_types_supported": ["code"],
            "response_modes_supported": ["query"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": [
                "client_secret_basic",
                "client_secret_post",
                "none"  # For public clients
            ],
            "code_challenge_methods_supported": ["S256"],  # PKCE required by OAuth 2.1
            "service_documentation": f"{base_url}/docs/api",
        }
        
        response = JsonResponse(metadata)
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        return response
    
    def options(self, request):
        response = JsonResponse({})
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
        return response
