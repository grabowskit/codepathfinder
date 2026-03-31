from django.urls import path, include
from .views import (
    ProjectAPIKeyListCreateView,
    ProjectAPIKeyDeleteView,
    MCPConfigView,
    MCPToolProxyView,
)

urlpatterns = [
    # Project API Key Management
    path('projects/<int:project_id>/keys/', ProjectAPIKeyListCreateView.as_view(), name='project-api-key-list-create'),
    path('projects/<int:project_id>/keys/<int:key_id>/', ProjectAPIKeyDeleteView.as_view(), name='project-api-key-delete'),
    path('projects/<int:project_id>/mcp-config/', MCPConfigView.as_view(), name='project-mcp-config'),

    # MCP Tool Proxy (Phase 3)
    path('v1/mcp/tools/call/', MCPToolProxyView.as_view(), name='mcp-tool-proxy'),

    # Jobs API (v1) - Full CRUD and job management
    path('v1/jobs/', include('api.jobs.urls')),
]
