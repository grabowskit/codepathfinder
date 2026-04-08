"""
Telemetry event ingestion endpoint for OSS installations.

Receives anonymous usage events from self-hosted CodePathfinder instances
and stores them in Elasticsearch for product analytics.

Privacy: Only installation_id (random UUID), version, and numeric counts.
No PII, no repo names, no code, no search queries.
"""

import json
import logging
from datetime import datetime
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Rate limiting: max 100 events per installation_id per hour
RATE_LIMIT_KEY_PREFIX = "telemetry_rate:"
RATE_LIMIT_MAX = 100
RATE_LIMIT_WINDOW = 3600  # 1 hour in seconds


def _get_es_client():
    """Get ES client or None if unavailable."""
    try:
        from projects.utils import get_es_client
        return get_es_client()
    except Exception as e:
        logger.warning("Could not get ES client for telemetry: %s", e)
        return None


def _check_rate_limit(installation_id: str) -> bool:
    """
    Check if installation_id has exceeded rate limit.
    Returns True if allowed, False if rate limited.
    """
    cache_key = f"{RATE_LIMIT_KEY_PREFIX}{installation_id}"
    try:
        count = cache.get(cache_key, 0)
        if count >= RATE_LIMIT_MAX:
            return False
        # Increment counter
        cache.set(cache_key, count + 1, timeout=RATE_LIMIT_WINDOW)
        return True
    except Exception as e:
        logger.warning("Rate limit check failed: %s", e)
        return True  # Allow on failure


def _validate_event(data: dict) -> tuple[bool, str]:
    """
    Validate telemetry event payload.
    Returns (is_valid, error_message).
    """
    required_fields = ['event_type', 'installation_id', 'version', 'timestamp']
    for field in required_fields:
        if field not in data:
            return False, f"Missing required field: {field}"

    # Validate event_type
    valid_types = ['install', 'startup', 'feature_counts']
    if data['event_type'] not in valid_types:
        return False, f"Invalid event_type: {data['event_type']}"

    # Validate timestamp format
    try:
        datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return False, "Invalid timestamp format"

    # Type-specific validation
    event_type = data['event_type']
    if event_type == 'install':
        if 'os_type' not in data or 'es_mode' not in data:
            return False, "install event missing os_type or es_mode"
    elif event_type == 'startup':
        if 'uptime_count' not in data:
            return False, "startup event missing uptime_count"
    elif event_type == 'feature_counts':
        required = ['search_count', 'index_count', 'mcp_call_counts', 'memory_access_count']
        for field in required:
            if field not in data:
                return False, f"feature_counts event missing {field}"

    return True, ""


def _store_event(data: dict) -> bool:
    """
    Store event to Elasticsearch.
    Returns True on success, False on failure.
    Index format: oss-telemetry-YYYY.MM
    """
    es = _get_es_client()
    if not es:
        logger.error("ES client unavailable, cannot store telemetry event")
        return False

    try:
        # Parse timestamp to determine index name
        ts = datetime.fromisoformat(data['timestamp'].replace('Z', '+00:00'))
        index_name = f"oss-telemetry-{ts.strftime('%Y.%m')}"

        # Add server-side metadata
        doc = {
            **data,
            'received_at': datetime.utcnow().isoformat(),
        }

        # Index the document
        es.index(
            index=index_name,
            document=doc,
            refresh=False,  # Async refresh, no need for immediate visibility
        )
        logger.info(
            "Stored telemetry event: type=%s, installation_id=%s, version=%s",
            data['event_type'],
            data['installation_id'][:8],  # Log only prefix for privacy
            data['version']
        )
        return True
    except Exception as e:
        logger.error("Failed to store telemetry event: %s", e, exc_info=True)
        return False


@csrf_exempt
@require_http_methods(["POST"])
def event_view(request):
    """
    POST /telemetry/event

    Accepts telemetry events from OSS installations.

    Request body (JSON):
    {
        "event_type": "install|startup|feature_counts",
        "installation_id": "uuid-string",
        "version": "version-string",
        "timestamp": "ISO8601-timestamp",
        ... event-specific fields ...
    }

    Returns:
        200 OK: {"status": "ok"}
        400 Bad Request: {"error": "validation error message"}
        429 Too Many Requests: {"error": "rate limit exceeded"}
        500 Internal Server Error: {"error": "failed to store event"}
    """
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    # Validate payload
    is_valid, error = _validate_event(data)
    if not is_valid:
        logger.warning("Invalid telemetry event: %s", error)
        return JsonResponse({'error': error}, status=400)

    # Rate limiting
    installation_id = data['installation_id']
    if not _check_rate_limit(installation_id):
        logger.warning("Rate limit exceeded for installation_id: %s", installation_id[:8])
        return JsonResponse({'error': 'Rate limit exceeded'}, status=429)

    # Store to Elasticsearch
    success = _store_event(data)
    if not success:
        return JsonResponse({'error': 'Failed to store event'}, status=500)

    return JsonResponse({'status': 'ok'})
