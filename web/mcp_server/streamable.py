"""
MCP Streamable HTTP Transport View

Implements the Streamable HTTP transport for MCP 2025-06-18 spec.
This replaces SSE with a simpler POST-based protocol where:
- Client sends JSON-RPC request via POST
- Server responds with JSON-RPC response (optionally streamed)

This is the preferred transport for remote MCP servers.
"""

from django.http import JsonResponse, StreamingHttpResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from oauth2_provider.models import AccessToken
from projects.models import ProjectAPIKey
from .tools import execute_tool, ToolError, TOOLS, TOOL_DEFINITIONS
from .protocol import JsonRpcRequest, JsonRpcResponse
import json
import logging
import os

logger = logging.getLogger(__name__)


def _get_injected_memories(tool_args: dict, user) -> str:
    """
    Auto-inject memories whose tags match string values in tool_args.

    Returns a <system_memory> block to prepend to tool results, or '' if none match.
    Per comment recommendation: wrap in <system_memory> so the LLM distinguishes
    injected facts from conversational intent regardless of client.
    """
    try:
        # Extract candidate tags from tool argument values.
        # Include both whole values (for tag list args like ['django', 'python'])
        # and individual words from longer strings (for query args like 'django orm').
        candidate_tags = set()
        for v in tool_args.values():
            if isinstance(v, str):
                candidate_tags.add(v.lower())
                # Also split on whitespace/punctuation to catch tags embedded in queries
                import re
                for word in re.split(r'[\s,;/]+', v.lower()):
                    word = word.strip('.-_')
                    if word:
                        candidate_tags.add(word)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, str):
                        candidate_tags.add(item.lower())

        if not candidate_tags:
            return ''

        from memories.services import MemoryService
        service = MemoryService()
        # Fetch all tags from accessible memories, then find matches
        matching = service.get_memories_by_tags(list(candidate_tags), user)
        if not matching:
            return ''

        blocks = []
        for memory in matching:
            # Track usage for auto-injected memories (best-effort)
            try:
                memory.increment_usage(user)
            except Exception:
                pass  # Never fail tool execution due to tracking errors

            blocks.append(f"[{memory.title}]\n{memory.content}")

        combined = "\n\n---\n\n".join(blocks)
        return f"<system_memory>\n{combined}\n</system_memory>"
    except Exception as e:
        logger.debug(f"Memory auto-injection skipped: {e}")
        return ''



def authenticate_request(request):
    """
    Authenticate the request using:
    1. Internal service secret (for LibreChat and other internal services)
    2. Project API Key (cpf_ prefix)
    3. OAuth2 Bearer token

    Returns:
        user: The authenticated user, or None if authentication fails
        error_response: A JsonResponse with error details, or None if auth succeeds
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()

    # Get token from Authorization header
    auth_header = request.headers.get('Authorization', '')

    if not auth_header.startswith('Bearer '):
        return None, JsonResponse(
            {'error': 'Missing or invalid Authorization header'},
            status=401
        )

    token_str = auth_header.split(' ', 1)[1]

    # 1. Check for internal service secret (shared via docker-compose env)
    # This allows LibreChat and other internal services to connect without manual API key creation
    internal_secret = os.getenv('CPF_INTERNAL_SERVICE_SECRET')
    if internal_secret and token_str == internal_secret:
        # If LibreChat passes X-User-Email, scope the session to that user's account.
        # LibreChat injects {{LIBRECHAT_USER_EMAIL}} per-request so each user sees only
        # their own projects. The internal secret is the trust anchor — only trusted
        # callers can use this email-based identity resolution.
        user_email = request.headers.get('X-User-Email', '').strip()
        if user_email:
            try:
                user = User.objects.get(email=user_email, is_active=True)
                logger.debug(f"Authenticated via internal service secret as user: {user.email}")
                return user, None
            except User.DoesNotExist:
                logger.warning(f"Internal service auth: no active user found for email {user_email!r}, falling back to system user")
            except User.MultipleObjectsReturned:
                logger.warning(f"Internal service auth: multiple users found for email {user_email!r}, falling back to system user")

        # Fallback: no email header, empty placeholder, or user not found
        # Use system superuser with access to all projects (backward compat)
        system_user, created = User.objects.get_or_create(
            username='__internal_service__',
            defaults={
                'is_active': True,
                'is_staff': True,
                'is_superuser': True,
                'first_name': 'Internal',
                'last_name': 'Service'
            }
        )
        # Ensure existing user has superuser privileges
        if not created and not system_user.is_superuser:
            system_user.is_superuser = True
            system_user.is_staff = True
            system_user.save(update_fields=['is_superuser', 'is_staff'])
        logger.debug("Authenticated via internal service secret (system user)")
        return system_user, None

    # 2. Check for Project API Key (starts with cpf_)
    if token_str.startswith('cpf_'):
        try:
            # Hash the key and look it up in the database
            hashed_key = ProjectAPIKey.hash_key(token_str)
            api_key_obj = ProjectAPIKey.objects.filter(
                hashed_key=hashed_key,
                is_active=True
            ).select_related('project__user').first()

            if not api_key_obj:
                return None, JsonResponse({'error': 'Invalid API Key'}, status=401)

            # Update last_used timestamp
            from django.utils import timezone
            api_key_obj.last_used_at = timezone.now()
            api_key_obj.save(update_fields=['last_used_at'])

            return api_key_obj.project.user, None
        except Exception as e:
            logger.exception("Error validating API key")
            return None, JsonResponse({'error': 'Invalid API Key'}, status=401)

    # 3. Fallback to OAuth2 Access Token
    try:
        access_token = AccessToken.objects.select_related('user').get(token=token_str)
        if not access_token.is_valid():
            return None, JsonResponse({'error': 'Token expired'}, status=401)
        return access_token.user, None
    except AccessToken.DoesNotExist:
        return None, JsonResponse({'error': 'Invalid token'}, status=401)


@method_decorator(csrf_exempt, name='dispatch')
class MCPStreamableView(View):
    """
    MCP Streamable HTTP Transport Endpoint
    
    Handles all MCP JSON-RPC methods via POST:
    - initialize
    - tools/list
    - tools/call
    - resources/list
    - ping
    """
    
    def post(self, request):
        # Authenticate using OAuth2 Bearer token or Project API Key
        user, error_response = authenticate_request(request)
        if error_response:
            return error_response
        
        # 2. Parse JSON-RPC request
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return self._mcp_response({'error': 'Invalid JSON'}, status=400)
        
        # Handle batch requests (array of requests)
        if isinstance(data, list):
            responses = [self.handle_rpc_request(req, user) for req in data]
            return self._mcp_response(responses, safe=False)
        
        # Handle single request
        method = data.get('method', '')
        response = self.handle_rpc_request(data, user)
        
        # Notifications don't get responses
        if response is None:
            return self._mcp_response({})
        
        # Check if this is an initialize request (needs session ID header)
        is_init = (method == 'initialize')
        return self._mcp_response(response, is_initialize=is_init)
    
    def _mcp_response(self, data, status=200, safe=True, is_initialize=False):
        """Create a JSON response with MCP protocol headers for Claude connector."""
        import uuid
        response = JsonResponse(data, status=status, safe=safe)
        # CORS headers
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'POST, OPTIONS, DELETE'
        response['Access-Control-Allow-Headers'] = 'Authorization, Content-Type, Mcp-Session-Id, MCP-Protocol-Version'
        # MCP Protocol headers
        response['MCP-Protocol-Version'] = '2025-06-18'
        # Session ID for initialization response
        if is_initialize:
            response['Mcp-Session-Id'] = str(uuid.uuid4())
        return response
    
    def handle_rpc_request(self, data, user):
        """Process a single JSON-RPC request and return the response dict."""
        
        rpc_id = data.get('id')
        method = data.get('method', '')
        params = data.get('params', {})
        
        # Notifications (no id) don't get responses
        is_notification = rpc_id is None
        
        response_data = None
        error_data = None
        
        try:
            if method == 'initialize':
                response_data = {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False}
                    },
                    "serverInfo": {
                        "name": "CodePathfinder",
                        "version": "1.0.0"
                    }
                }
            
            elif method == 'notifications/initialized':
                # Notification - no response needed
                return None
            
            elif method == 'tools/list':
                response_data = {"tools": TOOL_DEFINITIONS}
            
            elif method == 'tools/call':
                tool_name = params.get('name', '')
                tool_args = params.get('arguments', {})

                try:
                    result_text = execute_tool(tool_name, tool_args, user=user)
                    try:
                        from telemetry.counters import increment_mcp_call
                        increment_mcp_call(tool_name)
                    except Exception:
                        pass
                    # Auto-inject matching memories (skip memory tools to avoid recursion)
                    if not tool_name.startswith('memories_'):
                        injected = _get_injected_memories(tool_args, user)
                        if injected:
                            result_text = injected + "\n\n" + result_text
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
            
            elif method == 'resources/list':
                response_data = {"resources": []}
            
            elif method == 'prompts/list':
                response_data = {"prompts": []}
            
            elif method == 'ping':
                response_data = {}
            
            else:
                if not is_notification:
                    error_data = {"code": -32601, "message": f"Method not found: {method}"}
        
        except Exception as e:
            logger.exception(f"Error handling MCP request: {method}")
            error_data = {"code": -32603, "message": str(e)}
        
        # Build response
        if is_notification:
            return None
        
        response = {
            "jsonrpc": "2.0",
            "id": rpc_id
        }
        
        if error_data:
            response["error"] = error_data
        else:
            response["result"] = response_data
        
        return response
    
    def get(self, request):
        """
        Handle GET requests for SSE transport (HTTP+SSE transport from 2024-11-05 spec).
        Claude sends GET with Accept: text/event-stream to establish SSE connection.
        After receiving 'endpoint' event, client will POST JSON-RPC messages to that URL.
        """
        from django.http import StreamingHttpResponse
        import time
        import json
        import uuid
        
        # Generate session ID for this SSE connection
        session_id = str(uuid.uuid4())
        
        # Build the absolute URL for POSTing messages (same endpoint)
        host = request.get_host()
        scheme = 'https' if request.is_secure() or 'https' in request.headers.get('X-Forwarded-Proto', '') else 'http'
        messages_url = f"{scheme}://{host}/mcp/"
        
        def sse_stream():
            """Generate SSE stream with endpoint info and keepalives."""
            # Send endpoint event with absolute URL - this tells client where to POST
            yield f"event: endpoint\ndata: {json.dumps(messages_url)}\n\n"
            
            # Keep connection alive with heartbeats
            # The client will POST to the endpoint URL for JSON-RPC communication
            # We keep this stream open for server->client push messages (if any)
            heartbeat_count = 0
            while heartbeat_count < 300:  # Keep alive for ~5 minutes
                time.sleep(1)
                # Send comment as heartbeat to keep connection alive
                yield ": heartbeat\n\n"
                heartbeat_count += 1
        
        response = StreamingHttpResponse(
            sse_stream(),
            content_type='text/event-stream'
        )
        response['Cache-Control'] = 'no-cache'
        response['X-Accel-Buffering'] = 'no'
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS, DELETE'
        response['Access-Control-Allow-Headers'] = 'Authorization, Content-Type, Mcp-Session-Id, MCP-Protocol-Version, Accept'
        response['Mcp-Session-Id'] = session_id
        return response
    
    def options(self, request):
        """Handle CORS preflight requests."""
        response = JsonResponse({})
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS, DELETE'
        response['Access-Control-Allow-Headers'] = 'Authorization, Content-Type, Mcp-Session-Id, MCP-Protocol-Version, Accept'
        return response
    
    def delete(self, request):
        """Handle DELETE requests for session termination (MCP spec)."""
        response = JsonResponse({}, status=204)
        response['Access-Control-Allow-Origin'] = '*'
        return response
