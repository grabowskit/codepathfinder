"""
MemoryService: PostgreSQL CRUD + Elasticsearch sync + permission enforcement.

Elasticsearch index: 'memories'
  - memory_id (integer)
  - title (text)
  - content (text)
  - content_semantic (semantic_text via ELSER)
  - tags (keyword)
  - scope (keyword)
  - memory_type (keyword)
  - user_id (integer)
  - chunk_index (integer)  -- 0 for text, 0..N for document chunks
  - created_at (date)
"""

import logging
import math
from typing import List, Optional

from django.db.models import Q
from django.utils import timezone

from .models import Memory, MemoryUsage

logger = logging.getLogger(__name__)

CHUNK_SIZE = 2000  # characters per ES document for document-type memories
ES_INDEX = 'memories'


def _get_es_client():
    try:
        from projects.utils import get_es_client
        return get_es_client()
    except Exception as e:
        logger.warning(f"Could not get ES client: {e}")
        return None


def _get_inference_id():
    try:
        from core.models import SystemSettings
        s = SystemSettings.get_settings()
        return s.inference_id or '.elser-2-elasticsearch'
    except Exception:
        return '.elser-2-elasticsearch'


class MemoryService:

    # ------------------------------------------------------------------
    # Permission helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _can_manage_org(user) -> bool:
        return user and user.is_authenticated and user.is_staff

    @staticmethod
    def _access_filter(user):
        """Queryset filter: org memories + user's own memories."""
        if not user or not user.is_authenticated:
            return Q(scope=Memory.SCOPE_ORGANIZATION, is_active=True, is_hidden=False)
        return (
            Q(scope=Memory.SCOPE_ORGANIZATION) |
            Q(scope=Memory.SCOPE_USER, created_by=user)
        ) & Q(is_active=True, is_hidden=False)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def list_memories(self, user, tags: Optional[List[str]] = None,
                      scope: Optional[str] = None,
                      memory_type: Optional[str] = None):
        qs = Memory.objects.filter(self._access_filter(user))
        if scope:
            qs = qs.filter(scope=scope)
        if memory_type:
            qs = qs.filter(memory_type=memory_type)
        if tags:
            # All given tags must appear in the memory's tags list
            for tag in tags:
                qs = qs.filter(tags__contains=[tag])
        return qs.select_related('created_by')

    def get_memory(self, memory_id: int, user) -> Optional[Memory]:
        return Memory.objects.filter(
            self._access_filter(user), pk=memory_id
        ).first()

    def create_memory(self, user, title: str, content: str,
                      memory_type: str = Memory.TYPE_TEXT,
                      tags: Optional[List[str]] = None,
                      scope: str = Memory.SCOPE_USER) -> Memory:
        if scope == Memory.SCOPE_ORGANIZATION and not self._can_manage_org(user):
            raise PermissionError("Only admins can create organization memories")

        memory = Memory.objects.create(
            title=title,
            content=content,
            memory_type=memory_type,
            tags=tags or [],
            scope=scope,
            created_by=user,
        )
        self._index_memory(memory)
        return memory

    def update_memory(self, memory_id: int, user, **kwargs) -> Memory:
        memory = Memory.objects.filter(pk=memory_id).first()
        if not memory:
            raise ValueError(f"Memory {memory_id} not found")
        if memory.scope == Memory.SCOPE_ORGANIZATION and not self._can_manage_org(user):
            raise PermissionError("Only admins can update organization memories")
        if memory.scope == Memory.SCOPE_USER and memory.created_by != user:
            raise PermissionError("You can only edit your own memories")

        for field, value in kwargs.items():
            if hasattr(memory, field):
                setattr(memory, field, value)
        memory.save()
        self._index_memory(memory)
        return memory

    def delete_memory(self, memory_id: int, user):
        memory = Memory.objects.filter(pk=memory_id).first()
        if not memory:
            raise ValueError(f"Memory {memory_id} not found")
        if memory.scope == Memory.SCOPE_ORGANIZATION and not self._can_manage_org(user):
            raise PermissionError("Only admins can delete organization memories")
        if memory.scope == Memory.SCOPE_USER and memory.created_by != user:
            raise PermissionError("You can only delete your own memories")

        memory.is_hidden = True
        memory.is_active = False
        memory.deleted_at = timezone.now()
        memory.deleted_by = user
        memory.save()
        self._delete_from_es(memory_id)

    def import_document(self, user, title: str, content: str,
                        tags: Optional[List[str]] = None,
                        scope: str = Memory.SCOPE_USER) -> Memory:
        """Import a markdown document, chunking it into ES docs for retrieval."""
        if scope == Memory.SCOPE_ORGANIZATION and not self._can_manage_org(user):
            raise PermissionError("Only admins can create organization memories")

        memory = Memory.objects.create(
            title=title,
            content=content,
            memory_type=Memory.TYPE_DOCUMENT,
            tags=tags or [],
            scope=scope,
            created_by=user,
        )
        self._index_memory_chunks(memory, content)
        return memory

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_memories(self, query: str, user, limit: int = 5) -> List[dict]:
        """Semantic search via ELSER, scoped to org + user's own memories."""
        try:
            from telemetry.counters import increment
            increment('memory_access_count')
        except Exception:
            pass
        es = _get_es_client()
        if not es:
            return self._fallback_text_search(query, user, limit)

        user_id = user.pk if (user and user.is_authenticated) else None

        # Build scope filter
        scope_clauses = [{"term": {"scope": Memory.SCOPE_ORGANIZATION}}]
        if user_id:
            scope_clauses.append({
                "bool": {
                    "filter": [
                        {"term": {"scope": Memory.SCOPE_USER}},
                        {"term": {"user_id": user_id}},
                    ]
                }
            })

        body = {
            "query": {
                "bool": {
                    "must": [
                        {
                            "semantic": {
                                "field": "content_semantic",
                                "query": query,
                            }
                        }
                    ],
                    "filter": [
                        {"should": scope_clauses, "minimum_should_match": 1}
                    ],
                }
            },
            "size": limit,
            "_source": ["memory_id", "title", "content", "tags", "scope", "memory_type", "chunk_index"],
        }

        try:
            resp = es.search(index=ES_INDEX, body=body)
            results = []
            seen_ids = set()
            for hit in resp['hits']['hits']:
                src = hit['_source']
                mid = src.get('memory_id')
                if mid in seen_ids:
                    continue
                seen_ids.add(mid)
                results.append({
                    'id': mid,
                    'title': src.get('title', ''),
                    'content': src.get('content', ''),
                    'tags': src.get('tags', []),
                    'scope': src.get('scope', ''),
                    'memory_type': src.get('memory_type', ''),
                    'score': hit['_score'],
                })
            return results
        except Exception as e:
            logger.warning(f"ES semantic search failed, falling back: {e}")
            return self._fallback_text_search(query, user, limit)

    def _fallback_text_search(self, query: str, user, limit: int) -> List[dict]:
        qs = Memory.objects.filter(
            self._access_filter(user)
        ).filter(
            Q(title__icontains=query) | Q(content__icontains=query)
        )[:limit]
        return [m.to_dict() for m in qs]

    def get_memories_by_tags(self, tags: List[str], user) -> List[Memory]:
        """Tag-based match for auto-injection. Returns all matching memories."""
        if not tags:
            return []
        qs = Memory.objects.filter(self._access_filter(user))
        tag_filter = Q()
        for tag in tags:
            tag_filter |= Q(tags__contains=[tag])
        return list(qs.filter(tag_filter))

    # ------------------------------------------------------------------
    # Elasticsearch sync
    # ------------------------------------------------------------------

    def _index_memory(self, memory: Memory):
        """Index a single (text) memory — one ES document."""
        es = _get_es_client()
        if not es:
            return
        try:
            doc = {
                'memory_id': memory.pk,
                'title': memory.title,
                'content': memory.content,
                'content_semantic': memory.content,
                'tags': memory.tags,
                'scope': memory.scope,
                'memory_type': memory.memory_type,
                'user_id': memory.created_by_id,
                'chunk_index': 0,
                'created_at': memory.created_at.isoformat() if memory.created_at else None,
            }
            es.index(index=ES_INDEX, id=f"{memory.pk}_0", document=doc)
        except Exception as e:
            logger.warning(f"Failed to index memory {memory.pk}: {e}")

    def _index_memory_chunks(self, memory: Memory, content: str):
        """Chunk a document-type memory and index each chunk."""
        es = _get_es_client()
        if not es:
            return
        try:
            chunks = _split_content(content, CHUNK_SIZE)
            for i, chunk in enumerate(chunks):
                doc = {
                    'memory_id': memory.pk,
                    'title': memory.title,
                    'content': chunk,
                    'content_semantic': chunk,
                    'tags': memory.tags,
                    'scope': memory.scope,
                    'memory_type': memory.memory_type,
                    'user_id': memory.created_by_id,
                    'chunk_index': i,
                    'created_at': memory.created_at.isoformat() if memory.created_at else None,
                }
                es.index(index=ES_INDEX, id=f"{memory.pk}_{i}", document=doc)
        except Exception as e:
            logger.warning(f"Failed to index memory chunks for {memory.pk}: {e}")

    def _delete_from_es(self, memory_id: int):
        es = _get_es_client()
        if not es:
            return
        try:
            es.delete_by_query(
                index=ES_INDEX,
                body={"query": {"term": {"memory_id": memory_id}}}
            )
        except Exception as e:
            logger.warning(f"Failed to delete memory {memory_id} from ES: {e}")


def _split_content(content: str, chunk_size: int) -> List[str]:
    """Split content into chunks of ~chunk_size chars, respecting paragraph breaks."""
    if len(content) <= chunk_size:
        return [content]

    paragraphs = content.split('\n\n')
    chunks = []
    current = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)
        if current_len + para_len > chunk_size and current:
            chunks.append('\n\n'.join(current))
            current = [para]
            current_len = para_len
        else:
            current.append(para)
            current_len += para_len + 2  # +2 for \n\n

    if current:
        chunks.append('\n\n'.join(current))

    return chunks
