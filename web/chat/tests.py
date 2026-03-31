"""
Tests for the chat feature.

Chat functionality is provided by LibreChat. Tests verify the redirect view works correctly.
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

User = get_user_model()


class LibreChatEmbedViewTests(TestCase):
    """Tests for the LibreChat redirect view."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )

    def test_chat_embed_requires_login(self):
        """Test that chat embed view requires authentication."""
        response = self.client.get(reverse('chat_embed'), follow=True)
        self.assertIn('login', response.request['PATH_INFO'])

    def test_chat_embed_authenticated_redirects(self):
        """Test that authenticated users are redirected to LibreChat."""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('chat_embed'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/oauth/openid', response['Location'])
