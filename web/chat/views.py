"""
Chat views for CodePathfinder.

Chat functionality is provided by LibreChat. This view redirects users to
LibreChat via its OIDC initiation endpoint, ensuring the correct Django user
session is used.
"""
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views import View


class LibreChatEmbedView(LoginRequiredMixin, View):
    """Redirect to LibreChat via its OIDC initiation endpoint."""

    def get(self, request):
        librechat_url = getattr(settings, 'LIBRECHAT_EXTERNAL_URL', 'https://localhost:3443')
        return redirect(f'{librechat_url}/oauth/openid')
