from django.urls import path
from . import views

urlpatterns = [
    path('', views.ProjectListView.as_view(), name='project_list'),
    path('create/', views.ProjectCreateView.as_view(), name='project_create'),
    path('<int:pk>/action/', views.ProjectActionView.as_view(), name='project_action'),
    path('edit/<int:pk>/', views.ProjectUpdateView.as_view(), name='project_edit'),
    path('clone/<int:pk>/', views.ProjectCloneView.as_view(), name='project_clone'),
    path('share/<int:pk>/', views.ProjectShareView.as_view(), name='project_share'),
    path('api-keys/<int:pk>/', views.ProjectAPIKeysView.as_view(), name='project_api_keys'),
    path('job-logs/', views.GetJobLogsView.as_view(), name='job_logs'),
    path('statuses/', views.GetProjectStatusesView.as_view(), name='project_statuses'),
    path('<int:pk>/index-stats/', views.GetIndexStatsView.as_view(), name='index_stats'),
]
