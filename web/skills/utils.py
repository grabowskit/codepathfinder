"""
Utility functions for Skills app.
"""
import logging

logger = logging.getLogger(__name__)


def track_skill_usage(skill, user):
    """
    Track skill usage atomically for both aggregate and per-user counters.

    Best-effort tracking: swallows exceptions to never fail requests.

    Args:
        skill: Skill instance
        user: Django User instance

    Returns:
        None
    """
    if not user or not user.is_authenticated:
        return

    try:
        skill.increment_usage(user)
    except Exception as e:
        logger.warning(f"Failed to track skill usage: {e}", exc_info=True)
