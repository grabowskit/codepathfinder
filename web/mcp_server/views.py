from django.shortcuts import render, redirect
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.utils import timezone
from oauth2_provider.models import Application
from .models import MCPClientCredentials
from projects.models import ProjectAPIKey
from django.urls import reverse
from django.utils.crypto import get_random_string
import hashlib

class MCPDashboardView(LoginRequiredMixin, View):
    template_name = 'mcp_server/dashboard.html'

    def get_or_create_credentials(self, user):
        try:
            creds = MCPClientCredentials.objects.get(user=user)
            # Ensure application exists (in case it was manually deleted)
            if not creds.application:
                # Should not happen due to CASCADE, but safer to check
                creds.delete()
                creds = self.create_credentials(user)
        except MCPClientCredentials.DoesNotExist:
            creds = self.create_credentials(user)
        return creds

    def create_credentials(self, user):
        # Create OAuth Application
        # We use a dummy redirect URI for now as this is for MCP client (non-browser flow usually, or manual token copy)
        # Client Type: Confidential
        # Grant Type: Authorization Code
        app = Application.objects.create(
            user=user,
            name=f"MCP Client - {user.username}",
            client_type=Application.CLIENT_CONFIDENTIAL,
            authorization_grant_type=Application.GRANT_AUTHORIZATION_CODE,
            redirect_uris="urn:ietf:wg:oauth:2.0:oob",
            skip_authorization=True # Auto-authorize for the owner? Optional.
        )
        creds = MCPClientCredentials.objects.create(
            user=user,
            application=app
        )
        return creds

    def get(self, request):
        creds = self.get_or_create_credentials(request.user)
        mcp_url = request.build_absolute_uri(reverse('mcp_server:sse'))
        
        # Format redirect URIs for display (one per line)
        redirect_uris_display = "\n".join(creds.application.redirect_uris.split())

        # Check if we just regenerated - display raw secret from session
        new_secret = request.session.pop('mcp_new_client_secret', None)
        if new_secret:
            client_secret = new_secret
            secret_just_regenerated = True
        else:
            # Secret is hashed in DB - tell user to regenerate if they need it
            client_secret = "(hidden - click Regenerate to get a new secret)"
            secret_just_regenerated = False

        context = {
            'client_id': creds.application.client_id,
            'client_secret': client_secret,
            'secret_just_regenerated': secret_just_regenerated,
            'redirect_uris': redirect_uris_display,
            'mcp_url': mcp_url,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        creds = self.get_or_create_credentials(request.user)
        app = creds.application

        if 'regenerate' in request.POST:
            # Regenerate ID and Secret
            new_client_id = get_random_string(32)
            new_client_secret = get_random_string(64)
            
            app.client_id = new_client_id
            app.client_secret = new_client_secret  # Will be hashed on save
            app.save()
            
            # Store raw secret in session so we can display it after redirect
            # Django OAuth Toolkit hashes the secret, so we can't retrieve it later
            request.session['mcp_new_client_secret'] = new_client_secret
            
            messages.success(request, "MCP Credentials regenerated successfully. Copy your new Client Secret now - it won't be shown again!")
            return redirect('mcp_server:dashboard')
        
        elif 'update_redirect_uris' in request.POST:
            # Normalize whitespace: replace newlines/multiple spaces with single space
            raw_uris = request.POST.get('redirect_uris', '')
            redirect_uris = " ".join(raw_uris.split())
            app.redirect_uris = redirect_uris
            app.save()
            messages.success(request, "Redirect URIs updated successfully.")
            return redirect('mcp_server:dashboard')

        return redirect('mcp_server:dashboard')

# Protocol Implementation

from django.http import StreamingHttpResponse, JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from oauth2_provider.models import AccessToken
from .models import MCPSession, MCPMessageQueue
from .protocol import JsonRpcRequest, JsonRpcResponse
from .tools import semantic_code_search, ToolError, TOOL_DEFINITIONS
import json
import time
import logging

logger = logging.getLogger(__name__)

class MCPSseView(View):
    def get(self, request):
        # 1. Authenticate (Query Param 'token' preferred for SSE from Claude)
        token_str = request.GET.get('token')
        if not token_str:
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                token_str = auth_header.split(' ')[1]
        
        if not token_str:
            return JsonResponse({'error': 'Missing authentication token'}, status=401)

        user = None
        # Check for Project API Key (starts with cpf_)
        if token_str.startswith('cpf_'):
            try:
                # Extract prefix from key (format: cpf_abc123_...)
                parts = token_str.split('_')
                if len(parts) < 2:
                    return JsonResponse({'error': 'Invalid API Key format'}, status=401)

                prefix = parts[1]  # Get the prefix after 'cpf_'

                # Find the API key by prefix and validate the full key
                api_key_obj = ProjectAPIKey.objects.filter(
                    prefix=prefix,
                    is_active=True
                ).first()

                if not api_key_obj or not api_key_obj.validate_key(token_str):
                    return JsonResponse({'error': 'Invalid API Key'}, status=401)

                # Update last used timestamp
                api_key_obj.last_used_at = timezone.now()
                api_key_obj.save(update_fields=['last_used_at'])

                # Use the project owner as the session user
                user = api_key_obj.project.user
            except Exception as e:
                logger.error(f"API key validation error: {e}")
                return JsonResponse({'error': 'Invalid API Key'}, status=401)
        else:
            # Fallback to OAuth2
            try:
                access_token = AccessToken.objects.select_related('user', 'application').get(token=token_str)
                if not access_token.is_valid():
                     return JsonResponse({'error': 'Token expired'}, status=401)
                user = access_token.user
            except AccessToken.DoesNotExist:
                 return JsonResponse({'error': 'Invalid token'}, status=401)

        # 2. Create Session
        session = MCPSession.objects.create(user=user)
        
        # 3. Create initial 'endpoint' event
        # Endpoint URL must be absolute or relative? 
        # Claude Desktop expects relative to SSE stream or absolute. Absolute is safer.
        endpoint_url = request.build_absolute_uri(reverse('mcp_server:messages')) + f"?sessionId={session.id}"
        
        MCPMessageQueue.objects.create(
            session=session,
            event_type='endpoint',
            data=endpoint_url
        )

        # 4. Stream Response
        def event_stream():
            logger.info(f"SSE Connected: {session.id}")
            try:
                while True:
                    # Check DB for messages
                    # This is inefficient for high scale but works for "Native Django" requirement
                    messages = MCPMessageQueue.objects.filter(session=session, delivered=False).order_by('created_at')
                    
                    if messages.exists():
                        for msg in messages:
                            event_type = msg.event_type
                            data_str = str(msg.data) if isinstance(msg.data, str) else json.dumps(msg.data)
                            
                            yield f"event: {event_type}\n"
                            yield f"data: {data_str}\n\n"
                            
                            msg.delivered = True
                            msg.save()
                    
                    time.sleep(0.5) # Polling interval
            except GeneratorExit:
                logger.info(f"SSE Disconnected: {session.id}")
                session.active = False
                session.save()

        response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no' # For Nginx
        return response

@method_decorator(csrf_exempt, name='dispatch')
class MCPMessageView(View):
    def post(self, request):
        # 1. Authenticate? Or trust SessionID?
        # Protocol: Client requests `endpoint`.
        # We can require Token again or trust SessionID if it's unguessable UUID.
        # But for security, better to require Token in Authorizaton header too.
        # However, `mcp-server-sse-client` might not send auth header on POST if not configured.
        # Our dashboard config passes `env` vars.
        # Let's require the token from header if available, fallback to session ownership check?
        
        session_id = request.GET.get('sessionId')
        if not session_id:
             return JsonResponse({'error': 'Missing sessionId'}, status=400)
        
        try:
            session = MCPSession.objects.get(id=session_id)
        except MCPSession.DoesNotExist:
             return JsonResponse({'error': 'Invalid session'}, status=404)

        try:
            data = json.loads(request.body)
            rpc_req = JsonRpcRequest(
                jsonrpc=data.get('jsonrpc'),
                method=data.get('method'),
                params=data.get('params'),
                id=data.get('id')
            )
        except Exception:
             return JsonResponse({'error': 'Invalid JSON-RPC'}, status=400)

        # Handle Method
        response_data = None
        error_data = None
        
        method = rpc_req.method
        
        if method == 'initialize':
            response_data = {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                    "resources": {}
                },
                "serverInfo": {
                    "name": "CodePathfinder",
                    "version": "1.0.0"
                }
            }
        elif method == 'notifications/initialized':
             # Do nothing, just ack? Notification has no ID, so no response.
             pass
             
        elif method == 'tools/list':
            response_data = {
                "tools": TOOL_DEFINITIONS
            }
            
        elif method == 'tools/call':
            params = rpc_req.params or {}
            name = params.get('name')
            args = params.get('arguments', {})

            # Import execute_tool for dynamic dispatch
            from .tools import execute_tool

            try:
                # Execute the tool dynamically with user context
                result_text = execute_tool(name, args, user=session.user)
                response_data = {
                    "content": [
                        {
                            "type": "text",
                            "text": result_text
                        }
                    ]
                }
            except ToolError as e:
                error_data = {"code": -32603, "message": str(e)}
            except Exception as e:
                logger.error(f"Tool execution error: {e}")
                error_data = {"code": -32603, "message": f"Tool execution failed: {str(e)}"}
                
        elif method == 'resources/list':
             response_data = {"resources": []}
             
        elif method == 'ping':
             response_data = {}
             
        else:
             # Ignore unknown notifications, error on requests
             if rpc_req.id is not None:
                 error_data = {"code": -32601, "message": "Method not found"}

        # Send Response via SSE (Queue)
        if rpc_req.id is not None:
            resp = JsonRpcResponse(id=rpc_req.id, result=response_data, error=error_data)
            MCPMessageQueue.objects.create(
                session=session,
                event_type='message',
                data=resp.to_dict()
            )
            
        return HttpResponse("Accepted", status=202)


