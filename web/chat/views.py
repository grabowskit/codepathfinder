"""
Chat views for CodePathfinder.

Provides the lightweight side-panel streaming endpoint (ChatStreamV2View) used by
the embedded panel in base.html. Side-panel conversations are stored in Elasticsearch
(index: panel_chat) via chat.es_service.

The full chat interface and PostgreSQL-backed conversations have been removed.
All chat functionality now uses Elasticsearch for persistence and LibreChat for
the full interface.
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
from django.http import JsonResponse, Http404, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.views import View
from django.db.models import Q

from projects.models import PathfinderProject

logger = logging.getLogger(__name__)


# ============================================================================
# Web UI Views (Session-based auth)
# ============================================================================

class LibreChatEmbedView(LoginRequiredMixin, View):
    """Redirect to LibreChat via its OIDC initiation endpoint.

    The nav link opens this in a new tab (target=_blank), keeping CodePathfinder
    in the original tab. The OIDC flow ensures the correct Django user is used.
    """

    def get(self, request):
        from django.shortcuts import redirect
        librechat_url = getattr(settings, 'LIBRECHAT_EXTERNAL_URL', 'https://localhost:3443')
        return redirect(f'{librechat_url}/oauth/openid')


# ============================================================================
# Chat Models API
# ============================================================================

class ChatModelsView(LoginRequiredMixin, View):
    """Return available LLM models parsed from librechat.yaml."""

    def get(self, request):
        from .librechat_config import models_for_api
        return JsonResponse({"models": models_for_api()})


# ============================================================================
# SSE Streaming Chat (V2) — Elasticsearch-backed side panel
# ============================================================================

class ChatStreamV2View(LoginRequiredMixin, View):
    """
    SSE endpoint for streaming LLM responses from the side panel.

    GET params:
        project         — project ID (optional)
        conversation    — existing conversation UUID (ES-backed)
        message         — raw message text
        model_id        — model slug from librechat.yaml (optional, uses default)
        page_context    — JSON-encoded page context from the browser (optional)

    Conversations are stored in Elasticsearch (index: panel_chat) and identified
    by UUID. For a full-featured chat interface, use LibreChat.
    """

    def get(self, request):
        user = request.user
        project_id = request.GET.get("project")
        conversation_id = request.GET.get("conversation", "").strip()
        message_text = request.GET.get("message", "").strip()
        model_slug = request.GET.get("model_id", "")
        page_context_raw = request.GET.get("page_context", "")

        # Validate conversation ID (must be UUID for ES storage)
        if conversation_id and not _is_uuid(conversation_id):
            return self._error_response("Invalid conversation ID format", status=400)

        # --- Resolve project (optional) ---
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

        # --- Validate message ---
        if not message_text:
            return self._error_response("No message provided")

        # --- Load conversation from Elasticsearch ---
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
