"""
Skills URL Configuration.
"""
from django.urls import path
from . import views

urlpatterns = [
    # Main views
    path('', views.SkillListView.as_view(), name='skill_list'),
    path('create/', views.SkillCreateView.as_view(), name='skill_create'),
    path('sync/', views.SkillSyncView.as_view(), name='skill_sync'),
    path('sync-personal/', views.UserSkillSyncView.as_view(), name='skill_sync_personal'),
    path('import/', views.SkillImportView.as_view(), name='skill_import'),
    path('import-external/', views.ExternalImportView.as_view(), name='skill_import_external'),

    # API endpoints for Chat skill selector
    path('api/search/', views.SkillSearchAPIView.as_view(), name='skill_api_search'),
    path('api/top/', views.TopSkillsAPIView.as_view(), name='skill_api_top'),
    path('api/tools/', views.AvailableToolsAPIView.as_view(), name='skill_api_tools'),
    path('api/tags/', views.SkillTagsAPIView.as_view(), name='skill_api_tags'),
    path('api/toggle-visibility/<int:skill_id>/', views.SkillToggleVisibilityView.as_view(), name='skill_toggle_visibility'),

    # Detail routes (keep last due to <str:name> pattern)
    path('<str:name>/', views.SkillDetailView.as_view(), name='skill_detail'),
    path('<str:name>/edit/', views.SkillUpdateView.as_view(), name='skill_edit'),
    path('<str:name>/delete/', views.SkillDeleteView.as_view(), name='skill_delete'),
    path('<str:name>/fork/', views.SkillForkView.as_view(), name='skill_fork'),
]
