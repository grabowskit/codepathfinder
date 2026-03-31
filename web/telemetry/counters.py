"""
In-process telemetry counters.

Thread-safe increment via Django cache. These are local daily aggregates,
never sent individually — only daily totals go to the telemetry endpoint.

All functions swallow every exception — telemetry must never affect app behavior.
"""

_PREFIX = "cpf_telem:"
_SCALAR_KEYS = ('search_count', 'index_count', 'memory_access_count')
_MCP_KEY = f"{_PREFIX}mcp_calls"
_TTL = 86400 * 2  # 2-day TTL as safety valve


def _is_enabled() -> bool:
    try:
        from django.conf import settings
        return getattr(settings, 'TELEMETRY_ENABLED', False)
    except Exception:
        return False


def increment(key: str, delta: int = 1) -> None:
    """Increment a named counter. Best-effort."""
    if not _is_enabled():
        return
    try:
        from django.core.cache import cache
        cache_key = f"{_PREFIX}{key}"
        try:
            cache.incr(cache_key, delta)
        except ValueError:
            cache.set(cache_key, delta, timeout=_TTL)
    except Exception:
        pass


def increment_mcp_call(tool_name: str) -> None:
    """Increment per-tool MCP call counter."""
    if not _is_enabled():
        return
    try:
        from django.core.cache import cache
        existing = cache.get(_MCP_KEY) or {}
        existing[tool_name] = existing.get(tool_name, 0) + 1
        cache.set(_MCP_KEY, existing, timeout=_TTL)
    except Exception:
        pass


def get_and_reset() -> dict:
    """Read all counters, reset to zero, and return the values."""
    try:
        from django.core.cache import cache
        result = {}
        for k in _SCALAR_KEYS:
            cache_key = f"{_PREFIX}{k}"
            result[k] = cache.get(cache_key, 0)
            cache.delete(cache_key)
        result['mcp_call_counts'] = cache.get(_MCP_KEY) or {}
        cache.delete(_MCP_KEY)
        return result
    except Exception:
        return {k: 0 for k in _SCALAR_KEYS} | {'mcp_call_counts': {}}
