from django.db import models
from django.conf import settings
from oauth2_provider.models import Application
import uuid

class MCPClientCredentials(models.Model):
    """
    Stores the OAuth Application credentials for a user to access the MCP server.
    One set of credentials per user.
    """
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='mcp_credentials')
    application = models.OneToOneField(Application, on_delete=models.CASCADE, related_name='mcp_credentials')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"MCP Credentials for {self.user.username}"

class MCPSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    active = models.BooleanField(default=True)

class MCPMessageQueue(models.Model):
    session = models.ForeignKey(MCPSession, on_delete=models.CASCADE, related_name='messages')
    event_type = models.CharField(max_length=50, default='message') # 'endpoint' or 'message'
    data = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    delivered = models.BooleanField(default=False)
