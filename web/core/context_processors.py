"""
Global template context processors for CodePathfinder.
"""
from django.conf import settings


def librechat(request):
    """Inject librechat_url into all templates."""
    return {
        "librechat_url": getattr(settings, "LIBRECHAT_EXTERNAL_URL", "https://localhost:3443"),
    }
