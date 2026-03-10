from django.urls import path
from . import views
from .streamable import MCPStreamableView

app_name = 'mcp_server'

urlpatterns = [
    # MCP Streamable HTTP transport (MCP 2025-06-18) - primary endpoint for Claude Desktop
    # Both with and without trailing slash to avoid 301 redirect on POST
    path('', MCPStreamableView.as_view(), name='streamable'),

    # Dashboard moved to /mcp/dashboard/
    path('dashboard/', views.MCPDashboardView.as_view(), name='dashboard'),

    # Legacy SSE transport (MCP 2024-11-05)
    path('sse/', views.MCPSseView.as_view(), name='sse'),
    path('messages/', views.MCPMessageView.as_view(), name='messages'),
]
