from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

from core.health import health_check
from mcp_server.oauth_metadata import (
    ProtectedResourceMetadataView,
    AuthorizationServerMetadataView,
)
from mcp_server.dcr import DynamicClientRegistrationView, CORSTokenView
from mcp_server.streamable import MCPStreamableView
from oauth2_provider.views import ConnectDiscoveryInfoView

urlpatterns = [
    # OAuth 2.1 Metadata (MCP 2025-06-18 Spec)
    path('.well-known/oauth-protected-resource', ProtectedResourceMetadataView.as_view(), name='oauth_protected_resource'),
    path('.well-known/oauth-authorization-server', AuthorizationServerMetadataView.as_view(), name='oauth_authorization_server'),

    path('health/', health_check, name='health_check'),
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('accounts/', include('allauth.urls')),
    # DCR and Token endpoints with CORS (must be before oauth2_provider.urls to override)
    path('o/register/', DynamicClientRegistrationView.as_view(), name='oauth2_register'),
    path('o/token/', CORSTokenView.as_view(), name='oauth2_token'),
    # Serve OIDC discovery doc without trailing slash so openid-client doesn't get a 301
    path('o/.well-known/openid-configuration', ConnectDiscoveryInfoView.as_view(), name='oidc_discovery_no_slash'),
    path('o/', include('oauth2_provider.urls', namespace='oauth2_provider')),  # OAuth2 endpoints
    # MCP endpoint - handle both /mcp and /mcp/ to avoid 301 redirects on POST
    path('mcp', MCPStreamableView.as_view(), name='mcp_streamable_no_slash'),
    path('mcp/', include('mcp_server.urls')),
    path('api/', include('api.urls')),  # REST API endpoints
    # OpenAPI Documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    path('projects/', include('projects.urls')),
    path('skills/', include('skills.urls')),  # Skills management
    path('otel/', include('otel_ingest.urls')),  # OTLP auth proxy (customer telemetry ingest)
    path('chat/', include('chat.urls')),  # LibreChat integration
    path('accounts/profile/', RedirectView.as_view(pattern_name='project_list', permanent=False)),
    # path('', RedirectView.as_view(pattern_name='project_list', permanent=False), name='home'),
]
