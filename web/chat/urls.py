"""
URL configuration for the chat feature.
"""
from django.urls import path
from . import views

# Web UI URLs
urlpatterns = [
    # Side panel streaming endpoint — Elasticsearch-backed
    path('stream/', views.ChatStreamV2View.as_view(), name='chat_stream_v2'),

    # Side panel session persistence (Elasticsearch-backed)
    path('panel/sessions/', views.ChatPanelSessionsView.as_view(), name='chat_panel_sessions'),
    path('panel/sessions/<str:conversation_id>/', views.ChatPanelSessionMessagesView.as_view(), name='chat_panel_session_messages'),
    path('panel/sessions/<str:conversation_id>/close/', views.ChatPanelCloseView.as_view(), name='chat_panel_session_close'),

    # Model list API — feeds the model selector dropdown
    path('models/', views.ChatModelsView.as_view(), name='chat_models'),

    # LibreChat redirect (kept so existing links still work)
    path('', views.LibreChatEmbedView.as_view(), name='chat_embed'),
]

# Note: PostgreSQL-backed conversation management and artifact views have been removed.
# Use LibreChat (https://chat.codepathfinder.com/) for full-featured chat interface.
