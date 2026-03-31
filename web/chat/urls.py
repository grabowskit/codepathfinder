"""
URL configuration for the chat feature.
"""
from django.urls import path
from . import views
from . import views_artifacts

# Web UI URLs
urlpatterns = [
    # Side panel streaming endpoint — used by both the full interface and the embedded panel
    path('stream/', views.ChatStreamV2View.as_view(), name='chat_stream_v2'),

    # Side panel session persistence (Elasticsearch-backed)
    path('panel/sessions/', views.ChatPanelSessionsView.as_view(), name='chat_panel_sessions'),
    path('panel/sessions/<str:conversation_id>/', views.ChatPanelSessionMessagesView.as_view(), name='chat_panel_session_messages'),
    path('panel/sessions/<str:conversation_id>/close/', views.ChatPanelCloseView.as_view(), name='chat_panel_session_close'),

    # Model list API — feeds the model selector dropdown
    path('models/', views.ChatModelsView.as_view(), name='chat_models'),

    # Full chat interface per project
    path('<int:project_id>/', views.ChatInterfaceView.as_view(), name='chat_interface'),

    # Conversation management
    path('conversation/create/', views.ChatConversationCreateView.as_view(), name='chat_conversation_create'),
    path('conversation/<int:pk>/delete/', views.ChatConversationDeleteView.as_view(), name='chat_conversation_delete'),
    path('conversation/<int:pk>/export/', views.ChatConversationExportView.as_view(), name='chat_conversation_export'),

    # Favorite project
    path('favorite/<int:project_id>/', views.SetFavoriteProjectView.as_view(), name='chat_favorite'),

    # LibreChat redirect (kept so existing links still work)
    path('', views.LibreChatEmbedView.as_view(), name='chat_embed'),

    # Artifact endpoints
    path('conversation/<int:conversation_id>/artifacts/', views_artifacts.ArtifactListView.as_view(), name='artifact_list'),
    path('conversation/<int:conversation_id>/artifacts/<str:identifier>/', views_artifacts.ArtifactDetailView.as_view(), name='artifact_detail'),
    path('conversation/<int:conversation_id>/artifacts/<str:identifier>/versions/', views_artifacts.ArtifactVersionListView.as_view(), name='artifact_versions'),
    path('conversation/<int:conversation_id>/artifacts/<str:identifier>/download/', views_artifacts.ArtifactDownloadView.as_view(), name='artifact_download'),
    path('conversation/<int:conversation_id>/artifacts/<str:identifier>/share/', views_artifacts.ArtifactShareView.as_view(), name='artifact_share'),
    path('conversation/<int:conversation_id>/artifacts/<str:identifier>/promote/', views_artifacts.ArtifactPromoteView.as_view(), name='artifact_promote'),

    # Public artifact sharing (no auth required)
    path('artifact/share/<str:share_token>/', views_artifacts.ArtifactPublicView.as_view(), name='artifact_public'),
    path('artifact/render/<str:share_token>/', views_artifacts.ArtifactRenderView.as_view(), name='artifact_render'),
    path('artifact/sandbox/<str:share_token>/', views_artifacts.ArtifactSandboxView.as_view(), name='artifact_sandbox'),
]

# Public API URLs
api_urlpatterns = [
    path('conversations/', views.APIConversationListView.as_view(), name='api_chat_conversations'),
    path('conversations/<int:conversation_id>/', views.APIConversationDetailView.as_view(), name='api_chat_conversation_detail'),
]
