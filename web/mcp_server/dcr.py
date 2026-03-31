"""
OAuth 2.0 Dynamic Client Registration (DCR) View

Implements RFC 7591 for MCP clients to dynamically register themselves.
This allows Claude and other MCP clients to register automatically.
"""

from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils.crypto import get_random_string
from oauth2_provider.models import Application
from oauth2_provider.views import TokenView
from django.contrib.auth import get_user_model
import json
import logging

logger = logging.getLogger(__name__)
User = get_user_model()


@method_decorator(csrf_exempt, name='dispatch')
class CORSTokenView(TokenView):
    """
    Token endpoint with CORS support for MCP clients.
    Wraps django-oauth-toolkit's TokenView with proper CORS headers.
    """

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        return response

    def options(self, request, *args, **kwargs):
        response = JsonResponse({})
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        return response


@method_decorator(csrf_exempt, name='dispatch')
class DynamicClientRegistrationView(View):
    """
    RFC 7591: OAuth 2.0 Dynamic Client Registration Endpoint
    
    Allows MCP clients to register themselves automatically.
    POST /o/register/ with client metadata, returns client credentials.
    """
    
    def post(self, request):
        """Handle client registration requests."""
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self._error_response(
                'invalid_client_metadata',
                'Invalid JSON in request body'
            )
        
        # Extract client metadata per RFC 7591
        client_name = data.get('client_name', 'MCP Client')
        redirect_uris = data.get('redirect_uris', [])
        grant_types = data.get('grant_types', ['authorization_code'])
        response_types = data.get('response_types', ['code'])
        token_endpoint_auth_method = data.get('token_endpoint_auth_method', 'client_secret_basic')
        
        # Validate redirect URIs
        if not redirect_uris:
            # Allow public clients with no redirect URIs for MCP
            redirect_uris_str = ''
        else:
            redirect_uris_str = ' '.join(redirect_uris)
        
        # Determine client type based on token_endpoint_auth_method
        if token_endpoint_auth_method == 'none':
            client_type = Application.CLIENT_PUBLIC
        else:
            client_type = Application.CLIENT_CONFIDENTIAL
        
        # Generate client credentials
        client_id = f"mcp-{get_random_string(32)}"
        client_secret = get_random_string(64) if client_type == Application.CLIENT_CONFIDENTIAL else ''
        
        # Get a system user for DCR-created apps (use first superuser or create one)
        system_user = User.objects.filter(is_superuser=True).first()
        if not system_user:
            system_user = User.objects.first()
        
        if not system_user:
            return self._error_response(
                'server_error',
                'No users configured in the system'
            )
        
        # Create the OAuth Application
        try:
            app = Application.objects.create(
                user=system_user,
                name=client_name,
                client_id=client_id,
                client_secret=client_secret,
                client_type=client_type,
                authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
                redirect_uris=redirect_uris_str,
                skip_authorization=False,  # Require user consent for security
            )
        except Exception as e:
            logger.error(f"DCR: Failed to create application: {e}")
            return self._error_response(
                'server_error',
                'Failed to create client application'
            )
        
        # Build response per RFC 7591 Section 3.2.1
        response_data = {
            'client_id': client_id,
            'client_id_issued_at': int(app.created.timestamp()) if hasattr(app, 'created') else None,
            'client_name': client_name,
            'redirect_uris': redirect_uris,
            'grant_types': grant_types,
            'response_types': response_types,
            'token_endpoint_auth_method': token_endpoint_auth_method,
        }
        
        # Only include secret for confidential clients
        if client_type == Application.CLIENT_CONFIDENTIAL:
            response_data['client_secret'] = client_secret
            # Secret doesn't expire
            response_data['client_secret_expires_at'] = 0
        
        logger.info(f"DCR: Registered new client '{client_name}' with id '{client_id}'")
        
        response = JsonResponse(response_data, status=201)
        response['Cache-Control'] = 'no-store'
        response['Pragma'] = 'no-cache'
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Content-Type'
        return response
    
    def options(self, request):
        """Handle CORS preflight requests."""
        response = JsonResponse({})
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Content-Type'
        return response
    
    def _error_response(self, error_code, error_description, status=400):
        """Build RFC 7591 error response."""
        response = JsonResponse({
            'error': error_code,
            'error_description': error_description
        }, status=status)
        response['Access-Control-Allow-Origin'] = '*'
        return response
