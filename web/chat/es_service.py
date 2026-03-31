"""
Elasticsearch-backed chat session storage for the Ask CodePathfinder side panel.

Index: panel_chat
Document types (discriminated by 'type' field):
  conv — one per conversation: id, title, user_id, project_id, message_count, timestamps
  msg  — one per message: conversation_id, role, content, message_index, created_at

ES is the primary store for side-panel sessions. PostgreSQL ChatConversation/ChatMessage
are used only by the full LibreChat-connected chat interface.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

ES_INDEX = "panel_chat"


def _get_es():
    try:
        from projects.utils import get_es_client
        return get_es_client()
    except Exception as e:
        logger.warning("Could not get ES client: %s", e)
        return None


def _now():
    return datetime.now(timezone.utc).isoformat()


# ── Write operations ──────────────────────────────────────────────────────────

def save_message(conversation_id: str, user_id: int, project_id, role: str,
                 content: str, message_index: int, title: str = ""):
    """
    Index a message doc and upsert the conversation metadata doc.

    conversation_id: UUID string
    project_id: integer or None
    role: 'user' | 'assistant'
    message_index: 0-based position in conversation
    title: set from first user message; ignored if empty
    """
    es = _get_es()
    if not es:
        return

    now = _now()

    # Upsert conversation metadata
    conv_update: dict = {
        "type": "conv",
        "conversation_id": conversation_id,
        "user_id": user_id,
        "project_id": project_id,
        "updated_at": now,
        "message_count": message_index + 1,
    }
    if title:
        conv_update["title"] = title
    if message_index == 0:
        conv_update["created_at"] = now

    try:
        es.update(
            index=ES_INDEX,
            id=f"conv_{conversation_id}",
            body={"doc": conv_update, "doc_as_upsert": True},
        )
    except Exception as e:
        logger.warning("Failed to upsert conversation %s: %s", conversation_id, e)

    # Index the message
    msg_doc = {
        "type": "msg",
        "conversation_id": conversation_id,
        "user_id": user_id,
        "project_id": project_id,
        "role": role,
        "content": content,
        "message_index": message_index,
        "created_at": now,
    }
    try:
        es.index(
            index=ES_INDEX,
            id=f"msg_{conversation_id}_{message_index}",
            body=msg_doc,
        )
    except Exception as e:
        logger.warning("Failed to save message %d for conv %s: %s",
                       message_index, conversation_id, e)


def close_conversation(conversation_id: str, user_id: int, short_title: str):
    """Mark a conversation as closed with a short title (≤3 words)."""
    es = _get_es()
    if not es:
        return
    try:
        es.update(
            index=ES_INDEX,
            id=f"conv_{conversation_id}",
            body={"doc": {
                "status": "closed",
                "short_title": short_title,
                "closed_at": _now(),
            }},
        )
    except Exception as e:
        logger.warning("Failed to close conv %s: %s", conversation_id, e)


def update_title(conversation_id: str, title: str):
    """Set the conversation title. No-op if the doc doesn't exist yet."""
    es = _get_es()
    if not es or not title:
        return
    try:
        es.update(
            index=ES_INDEX,
            id=f"conv_{conversation_id}",
            body={"doc": {"title": title}},
        )
    except Exception as e:
        logger.debug("Failed to update title for conv %s: %s", conversation_id, e)


def delete_conversation(conversation_id: str, user_id: int):
    """Delete a conversation and all its messages."""
    es = _get_es()
    if not es:
        return
    try:
        es.delete_by_query(
            index=ES_INDEX,
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"conversation_id": conversation_id}},
                            {"term": {"user_id": user_id}},
                        ]
                    }
                }
            },
        )
    except Exception as e:
        logger.warning("Failed to delete conv %s: %s", conversation_id, e)


# ── Read operations ───────────────────────────────────────────────────────────

def list_conversations(user_id: int, limit: int = 30, status: Optional[str] = None) -> list[dict]:
    """
    Return conversation metadata docs for a user, newest first.

    status: "active" = not closed, "closed" = closed only (last 30 days), None = all
    Each dict has: conversation_id, title, short_title, status, updated_at,
                   closed_at, message_count, project_id
    """
    es = _get_es()
    if not es:
        return []

    filters = [
        {"term": {"type": "conv"}},
        {"term": {"user_id": user_id}},
    ]
    if status == "closed":
        filters.append({"term": {"status": "closed"}})
        filters.append({"range": {"closed_at": {"gte": "now-30d"}}})
    elif status == "active":
        filters.append({"bool": {"must_not": {"term": {"status": "closed"}}}})

    try:
        resp = es.search(
            index=ES_INDEX,
            body={
                "query": {"bool": {"filter": filters}},
                "sort": [{"updated_at": {"order": "desc"}}],
                "size": limit,
                "_source": ["conversation_id", "title", "short_title", "status",
                            "updated_at", "closed_at", "message_count", "project_id"],
            },
        )
        return [hit["_source"] for hit in resp["hits"]["hits"]]
    except Exception as e:
        logger.warning("Failed to list conversations for user %d: %s", user_id, e)
        return []


def get_messages(conversation_id: str, user_id: int) -> list[dict]:
    """
    Return message docs for a conversation, ordered by message_index ascending.

    Each dict has: role, content, message_index, created_at
    Verifies ownership via user_id.
    """
    es = _get_es()
    if not es:
        return []
    try:
        resp = es.search(
            index=ES_INDEX,
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"type": "msg"}},
                            {"term": {"conversation_id": conversation_id}},
                            {"term": {"user_id": user_id}},
                        ]
                    }
                },
                "sort": [{"message_index": {"order": "asc"}}],
                "size": 200,
                "_source": ["role", "content", "message_index", "created_at"],
            },
        )
        return [hit["_source"] for hit in resp["hits"]["hits"]]
    except Exception as e:
        logger.warning("Failed to get messages for conv %s: %s",
                       conversation_id, e)
        return []


def get_message_count(conversation_id: str, user_id: int) -> int:
    """Return the current message count for a conversation (from the conv doc)."""
    es = _get_es()
    if not es:
        return 0
    try:
        resp = es.get(index=ES_INDEX, id=f"conv_{conversation_id}",
                      _source=["message_count", "user_id"])
        src = resp.get("_source", {})
        if src.get("user_id") != user_id:
            return 0
        return src.get("message_count", 0)
    except Exception:
        return 0
