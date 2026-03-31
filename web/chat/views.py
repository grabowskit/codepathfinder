"""
Chat views for CodePathfinder.

Provides both the full ChatInterfaceView (/chat/<project_id>) and the lightweight
side-panel streaming endpoint (ChatStreamV2View) used by the embedded panel in base.html.

Side-panel conversations are stored in Elasticsearch (index: panel_chat) via
chat.es_service. The conversation_id for panel sessions is a UUID string; the full
chat interface continues to use integer PostgreSQL IDs.
"""
import json
import logging
import re

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


def _is_uuid(s: str) -> bool:
    return bool(_UUID_RE.match(s)) if s else False

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import render, get_object_or_404
from django.views import View
from django.db.models import Q
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from projects.models import PathfinderProject
from projects.authentication import ChatAPIKeyAuthentication
from .models import ChatConversation, ChatMessage
from .serializers import (
    ChatConversationSerializer,
    ChatConversationListSerializer,
)
from .throttling import ChatRateThrottle

logger = logging.getLogger(__name__)


# Error codes for API responses
class ErrorCode:
    CONVERSATION_LIMIT = 'CONVERSATION_LIMIT'
    INTERNAL_ERROR = 'INTERNAL_ERROR'


# ============================================================================
# Web UI Views (Session-based auth)
# ============================================================================

class ProjectSelectView(LoginRequiredMixin, View):
    """View to select a project for chat - redirects to favorite or first available."""

    def get(self, request):
        user = request.user
        
        # Get available projects
        if user.is_superuser:
            projects = PathfinderProject.objects.filter(
                is_enabled=True, 
                status__in=['completed', 'watching', 'stopped']
            )
        else:
            projects = PathfinderProject.objects.filter(
                Q(user=user) | Q(shared_with=user),
                is_enabled=True,
                status__in=['completed', 'watching', 'stopped']
            ).distinct()
        
        # Check if user has a valid favorite project
        if user.favorite_chat_project and user.favorite_chat_project in projects:
            from django.shortcuts import redirect
            return redirect('chat_interface', project_id=user.favorite_chat_project.id)
        
        # Otherwise redirect to first available project
        first_project = projects.first()
        if first_project:
            from django.shortcuts import redirect
            return redirect('chat_interface', project_id=first_project.id)
        
        # No projects available - show empty state
        return render(request, 'chat/project_select.html', {'projects': []})


class LibreChatEmbedView(LoginRequiredMixin, View):
    """Redirect to LibreChat via its OIDC initiation endpoint.

    The nav link opens this in a new tab (target=_blank), keeping CodePathfinder
    in the original tab. The OIDC flow ensures the correct Django user is used.
    """

    def get(self, request):
        from django.shortcuts import redirect
        librechat_url = getattr(settings, 'LIBRECHAT_EXTERNAL_URL', 'https://localhost:3443')
        return redirect(f'{librechat_url}/oauth/openid')


class ChatInterfaceView(LoginRequiredMixin, View):
    """Main chat interface view."""
    template_name = 'chat/chat_interface.html'

    def get(self, request, project_id):
        user = request.user
        project = get_object_or_404(PathfinderProject, id=project_id)

        # Check access
        if not user.is_superuser:
            has_access = (
                project.user == user or
                project.shared_with.filter(id=user.id).exists()
            )
            if not has_access:
                raise Http404("Project not found")

        # Check project is indexed and enabled
        if project.status not in ['completed', 'watching'] or not project.is_enabled:
            return render(request, 'chat/project_not_ready.html', {
                'project': project
            })

        # Get all available projects for the sidebar dropdown
        if user.is_superuser:
            all_projects = PathfinderProject.objects.filter(
                is_enabled=True,
                status__in=['completed', 'watching', 'stopped']
            ).order_by('name')
        else:
            all_projects = PathfinderProject.objects.filter(
                Q(user=user) | Q(shared_with=user),
                is_enabled=True,
                status__in=['completed', 'watching', 'stopped']
            ).distinct().order_by('name')

        # Get or list conversations
        conversations = ChatConversation.objects.filter(
            user=user,
            project=project
        )[:10]

        conversation_id = request.GET.get('conversation')
        conversation = None
        messages = []

        if conversation_id:
            conversation = get_object_or_404(
                ChatConversation,
                id=conversation_id,
                user=user,
                project=project
            )
            messages = list(conversation.messages.all())

        # Check if current project is user's favorite
        is_favorite = user.favorite_chat_project_id == project.id

        return render(request, self.template_name, {
            'project': project,
            'all_projects': all_projects,
            'conversations': conversations,
            'conversation': conversation,
            'messages': messages,
            'is_favorite': is_favorite,
        })


class ChatConversationCreateView(LoginRequiredMixin, View):
    """Create a new conversation and initial message via POST."""

    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        project_id = data.get('project_id')
        message_content = data.get('message', '').strip()

        if not project_id:
            return JsonResponse({'error': 'Missing project_id'}, status=400)
        
        # Determine the user properly
        user = request.user
        
        # Get project
        project = get_object_or_404(PathfinderProject, id=project_id)
        
        # Check access
        if not user.is_superuser:
            has_access = (
                project.user == user or
                project.shared_with.filter(id=user.id).exists()
            )
            if not has_access:
                return JsonResponse({'error': 'Access denied'}, status=403)

        # Check conversation limit
        conv_count = ChatConversation.objects.filter(
            user=user,
            project=project
        ).count()

        if conv_count >= settings.CHAT_MAX_CONVERSATIONS_PER_PROJECT:
            # Delete oldest conversation
            oldest = ChatConversation.objects.filter(
                user=user,
                project=project
            ).order_by('updated_at').first()
            if oldest:
                oldest.delete()

        # Create conversation
        conversation = ChatConversation.objects.create(
            user=user,
            project=project
        )
        
        message = None
        if message_content:
             # Create initial message if provided
            message = ChatMessage.objects.create(
                conversation=conversation,
                role='user',
                content=message_content
            )
            conversation.generate_title()
            
        return JsonResponse({
            'conversation_id': conversation.id,
            'message_id': message.id if message else None
        })


# ============================================================================
# Public API Views (API key auth)
# ============================================================================

class APIConversationListView(APIView):
    """List and create conversations via API."""
    authentication_classes = [ChatAPIKeyAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ChatRateThrottle]

    def get(self, request):
        """List conversations for the authenticated project."""
        project = request.user  # API key auth sets project as user
        api_key = request.auth

        conversations = ChatConversation.objects.filter(
            user=api_key.project.user,
            project=project
        )
        serializer = ChatConversationListSerializer(conversations, many=True)
        return Response(serializer.data)

    def post(self, request):
        """Create a new conversation."""
        project = request.user
        api_key = request.auth
        user = api_key.project.user

        # Check conversation limit
        conv_count = ChatConversation.objects.filter(
            user=user,
            project=project
        ).count()

        if conv_count >= settings.CHAT_MAX_CONVERSATIONS_PER_PROJECT:
            return Response(
                {
                    'error': {
                        'code': ErrorCode.CONVERSATION_LIMIT,
                        'message': f'Maximum {settings.CHAT_MAX_CONVERSATIONS_PER_PROJECT} conversations per project'
                    }
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        conversation = ChatConversation.objects.create(
            user=user,
            project=project
        )
        serializer = ChatConversationSerializer(conversation)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class APIConversationDetailView(APIView):
    """Get or delete a specific conversation."""
    authentication_classes = [ChatAPIKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, conversation_id):
        project = request.user
        api_key = request.auth

        conversation = get_object_or_404(
            ChatConversation,
            id=conversation_id,
            user=api_key.project.user,
            project=project
        )
        serializer = ChatConversationSerializer(conversation)
        return Response(serializer.data)

    def delete(self, request, conversation_id):
        project = request.user
        api_key = request.auth

        conversation = get_object_or_404(
            ChatConversation,
            id=conversation_id,
            user=api_key.project.user,
            project=project
        )
        conversation.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# APIChatSendView removed - chat functionality now provided by LibreChat


class ChatConversationDeleteView(LoginRequiredMixin, View):
    """Delete a specific conversation."""

    def post(self, request, pk):
        conversation = get_object_or_404(ChatConversation, pk=pk, user=request.user)
        conversation.delete()
        return JsonResponse({'status': 'success'})


class SetFavoriteProjectView(LoginRequiredMixin, View):
    """Set or clear the user's favorite chat project."""

    def post(self, request, project_id):
        user = request.user
        project = get_object_or_404(PathfinderProject, id=project_id)

        # Check access
        if not user.is_superuser:
            has_access = (
                project.user == user or
                project.shared_with.filter(id=user.id).exists()
            )
            if not has_access:
                return JsonResponse({'error': 'Access denied'}, status=403)

        # Toggle favorite: if already favorite, clear it; otherwise set it
        if user.favorite_chat_project_id == project.id:
            user.favorite_chat_project = None
            is_favorite = False
        else:
            user.favorite_chat_project = project
            is_favorite = True
        
        user.save(update_fields=['favorite_chat_project'])
        
        return JsonResponse({
            'status': 'success',
            'is_favorite': is_favorite,
            'project_id': project.id
        })


class ChatConversationExportView(LoginRequiredMixin, View):
    """Export a conversation as a Markdown file."""

    def get(self, request, pk):
        conversation = get_object_or_404(ChatConversation, pk=pk, user=request.user)

        # Build markdown content
        content = [f"# {conversation.title or 'Untitled Conversation'}\n"]
        content.append(f"**Project:** {conversation.project.name}")
        content.append(f"**Date:** {conversation.created_at.strftime('%Y-%m-%d %H:%M')}\n")

        for msg in conversation.messages.all().order_by('created_at'):
            role_title = "User" if msg.role == 'user' else "Assistant"
            content.append(f"## {role_title}")
            content.append(f"{msg.content}\n")

        markdown_text = "\n".join(content)

        # Create file response
        response = HttpResponse(markdown_text, content_type='text/markdown')
        filename = f"conversation-{conversation.id}.md"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        return response


# ============================================================================
# Chat Models API
# ============================================================================

class ChatModelsView(LoginRequiredMixin, View):
    """Return available LLM models parsed from librechat.yaml."""

    def get(self, request):
        from .librechat_config import models_for_api
        return JsonResponse({"models": models_for_api()})


# ============================================================================
# SSE Streaming Chat (V2) — used by both the full chat interface and side panel
# ============================================================================

class ChatStreamV2View(LoginRequiredMixin, View):
    """
    SSE endpoint for streaming LLM responses.

    GET params:
        project         — project ID (optional)
        conversation    — existing conversation ID: integer (PostgreSQL) or UUID (ES panel)
        message_id      — ID of a pre-saved ChatMessage (preferred; PostgreSQL only)
        message         — raw message text
        model_id        — model slug from librechat.yaml (optional, uses default)
        page_context    — JSON-encoded page context from the browser (optional)

    If conversation is a UUID the request is treated as a side-panel session:
      - History and persistence use Elasticsearch (chat.es_service).
      - No PostgreSQL ChatConversation is created.
    If conversation is an integer (or blank with a project), PostgreSQL is used.
    """

    def get(self, request):
        user = request.user
        project_id = request.GET.get("project")
        conversation_id = request.GET.get("conversation", "").strip()
        message_id = request.GET.get("message_id")
        message_text = request.GET.get("message", "").strip()
        model_slug = request.GET.get("model_id", "")
        page_context_raw = request.GET.get("page_context", "")

        # Detect panel (ES) vs full-chat (PostgreSQL) mode
        panel_mode = _is_uuid(conversation_id)

        # --- Resolve project (optional in panel mode) ---
        project = None
        if project_id:
            project = get_object_or_404(PathfinderProject, id=project_id)
            if not user.is_superuser:
                has_access = (
                    project.user == user or
                    project.shared_with.filter(id=user.id).exists()
                )
                if not has_access:
                    return self._error_response("Access denied", status=403)
        elif not panel_mode:
            # Full-chat mode: fall back to user's favorite project
            if hasattr(user, "favorite_chat_project") and user.favorite_chat_project:
                project = user.favorite_chat_project

        # --- Resolve model ---
        from .librechat_config import get_model_by_id, get_default_model
        model_config = get_model_by_id(model_slug) if model_slug else None
        if not model_config:
            model_config = get_default_model()
        if not model_config:
            return self._error_response(
                "No LLM models configured. Add ANTHROPIC_API_KEY or configure librechat.yaml."
            )

        # --- Parse page context ---
        page_context = None
        if page_context_raw:
            try:
                page_context = json.loads(page_context_raw)
            except json.JSONDecodeError:
                pass

        # ── Panel mode (ES) ────────────────────────────────────────────────────
        if panel_mode:
            if not message_text:
                return self._error_response("No message provided")

            from . import es_service
            _conv_id = conversation_id
            _proj_id = project.id if project else None

            # Load prior history from ES, then append current message
            es_messages = es_service.get_messages(_conv_id, user.id)
            msg_index_user = len(es_messages)
            # Include the current user message in history sent to the LLM
            all_es_messages = list(es_messages) + [{"role": "user", "content": message_text}]

            # Persist user message to ES
            title = message_text[:50] + ("..." if len(message_text) > 50 else "")
            es_service.save_message(
                conversation_id=_conv_id,
                user_id=user.id,
                project_id=_proj_id,
                role="user",
                content=message_text,
                message_index=msg_index_user,
                title=title if msg_index_user == 0 else "",
            )

            _model_config = model_config
            _project = project
            _page_context = page_context
            _message_text = message_text

            def panel_event_stream():
                from .llm_stream import generate_stream
                import json as _json

                full_text = ""
                try:
                    for chunk in generate_stream(
                        user_message=_message_text,
                        db_messages=all_es_messages,
                        model_config=_model_config,
                        project=_project,
                        user=user,
                        page_context=_page_context,
                    ):
                        if chunk.startswith("event: text\n"):
                            try:
                                data_line = chunk.strip().split("\n")[1]
                                full_text += _json.loads(data_line[len("data: "):])
                            except Exception:
                                pass
                        yield chunk

                    # Save assistant response to ES
                    if full_text:
                        es_service.save_message(
                            conversation_id=_conv_id,
                            user_id=user.id,
                            project_id=_proj_id,
                            role="assistant",
                            content=full_text,
                            message_index=msg_index_user + 1,
                        )

                    yield f"event: done\ndata: {_json.dumps({'conversation_id': _conv_id})}\n\n"

                except Exception as e:
                    logger.exception("Panel stream generation failed")
                    yield f"event: error\ndata: {_json.dumps({'message': str(e)})}\n\n"

            response = StreamingHttpResponse(
                panel_event_stream(), content_type="text/event-stream"
            )
            response["Cache-Control"] = "no-cache"
            response["X-Accel-Buffering"] = "no"
            return response

        # ── Full-chat mode (PostgreSQL) ────────────────────────────────────────
        conversation = None
        if project:
            if conversation_id:
                conversation = get_object_or_404(
                    ChatConversation, id=conversation_id, user=user, project=project
                )
            else:
                conv_count = ChatConversation.objects.filter(user=user, project=project).count()
                if conv_count >= settings.CHAT_MAX_CONVERSATIONS_PER_PROJECT:
                    oldest = ChatConversation.objects.filter(
                        user=user, project=project
                    ).order_by("updated_at").first()
                    if oldest:
                        oldest.delete()
                conversation = ChatConversation.objects.create(user=user, project=project)

        if message_id:
            user_msg = get_object_or_404(ChatMessage, id=message_id, conversation__user=user)
            message_text = user_msg.content
        elif message_text:
            if conversation:
                ChatMessage.objects.create(
                    conversation=conversation,
                    role="user",
                    content=message_text,
                )
                if not conversation.title:
                    conversation.generate_title()
        else:
            return self._error_response("No message provided")

        if conversation and not conversation.title:
            conversation.generate_title()

        all_messages = (
            list(conversation.messages.all().order_by("created_at")) if conversation else []
        )

        _conversation = conversation
        _model_config = model_config
        _project = project
        _page_context = page_context
        _message_text = message_text

        def event_stream():
            from .llm_stream import generate_stream
            import json as _json

            full_text = ""
            try:
                for chunk in generate_stream(
                    user_message=_message_text,
                    db_messages=all_messages,
                    model_config=_model_config,
                    project=_project,
                    user=user,
                    page_context=_page_context,
                ):
                    if chunk.startswith("event: text\n"):
                        try:
                            data_line = chunk.strip().split("\n")[1]
                            full_text += _json.loads(data_line[len("data: "):])
                        except Exception:
                            pass
                    yield chunk

                if full_text and _conversation:
                    ChatMessage.objects.create(
                        conversation=_conversation,
                        role="assistant",
                        content=full_text,
                        tool_calls=[],
                    )

                conv_id = _conversation.id if _conversation else None
                yield f"event: done\ndata: {_json.dumps({'conversation_id': conv_id})}\n\n"

            except Exception as e:
                logger.exception("Stream generation failed")
                yield f"event: error\ndata: {_json.dumps({'message': str(e)})}\n\n"

        response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response

    def _error_response(self, message, status=400):
        """Return a StreamingHttpResponse with a single error event."""
        import json as _json

        def _gen():
            yield f"event: error\ndata: {_json.dumps({'message': message})}\n\n"

        resp = StreamingHttpResponse(_gen(), content_type="text/event-stream")
        resp["Cache-Control"] = "no-cache"
        resp.status_code = status
        return resp


# ============================================================================
# Side Panel Session Views (Elasticsearch-backed)
# ============================================================================

class ChatPanelSessionsView(LoginRequiredMixin, View):
    """
    GET  /chat/panel/sessions/  — list the current user's side-panel conversations
    DELETE /chat/panel/sessions/<uuid>/  — delete a conversation
    """

    def get(self, request):
        from . import es_service
        status_filter = request.GET.get("status")  # "active", "closed", or None (all)
        conversations = es_service.list_conversations(request.user.id, limit=50, status=status_filter)
        return JsonResponse({"conversations": conversations})


class ChatPanelSessionMessagesView(LoginRequiredMixin, View):
    """
    GET /chat/panel/sessions/<uuid>/  — return messages for a conversation
    DELETE /chat/panel/sessions/<uuid>/  — delete a conversation and its messages
    """

    def get(self, request, conversation_id):
        if not _is_uuid(conversation_id):
            return JsonResponse({"error": "Invalid conversation ID"}, status=400)
        from . import es_service
        messages = es_service.get_messages(conversation_id, request.user.id)
        return JsonResponse({"messages": messages})

    def delete(self, request, conversation_id):
        if not _is_uuid(conversation_id):
            return JsonResponse({"error": "Invalid conversation ID"}, status=400)
        from . import es_service
        es_service.delete_conversation(conversation_id, request.user.id)
        return JsonResponse({"status": "deleted"})


class ChatPanelCloseView(LoginRequiredMixin, View):
    """
    POST /chat/panel/sessions/<uuid>/close/
    Mark a side-panel conversation as closed and save a short title (≤3 words).
    """

    def post(self, request, conversation_id):
        if not _is_uuid(conversation_id):
            return JsonResponse({"error": "Invalid conversation ID"}, status=400)
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            data = {}
        short_title = (data.get("short_title") or "Chat")[:30]
        from . import es_service
        es_service.close_conversation(conversation_id, request.user.id, short_title)
        return JsonResponse({"status": "closed"})
