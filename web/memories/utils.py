"""
Utility functions for Memories app.
"""
import logging

logger = logging.getLogger(__name__)


def track_memory_usage(memory, user):
    """
    Track memory usage atomically for both aggregate and per-user counters.

    Best-effort tracking: swallows exceptions to never fail requests.

    Args:
        memory: Memory instance
        user: Django User instance

    Returns:
        None
    """
    if not user or not user.is_authenticated:
        return

    try:
        memory.increment_usage(user)
    except Exception as e:
        logger.warning(f"Failed to track memory usage: {e}", exc_info=True)
