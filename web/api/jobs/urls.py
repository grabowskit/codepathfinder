"""
URL routing for the Jobs API.

Base URL: /api/v1/jobs/

Endpoints:
- GET    /                           List all projects with status
- POST   /                           Create a new project
- GET    /{project_id}/              Get project details
- PATCH  /{project_id}/              Update project settings
- DELETE /{project_id}/              Delete project and index
- POST   /{project_id}/start/        Start indexing job
- POST   /{project_id}/stop/         Stop running job
- GET    /{project_id}/status/       Get current job status
- GET    /{project_id}/logs/         Fetch job logs (supports SSE)
- POST   /{project_id}/reset/        Reset failed project
- GET    /{project_id}/history/      Query past job runs
- POST   /{project_id}/search/       Search indexed content
- POST   /bulk/start/                Start multiple jobs
- POST   /bulk/stop/                 Stop multiple jobs
- POST   /search/                    Search across all projects
"""

from django.urls import path
from . import views

app_name = 'jobs'

urlpatterns = [
    # Project list and create
    path('', views.JobListCreateView.as_view(), name='list-create'),

    # Cross-project search
    path('search/', views.CrossProjectSearchView.as_view(), name='cross-project-search'),

    # Bulk operations
    path('bulk/start/', views.BulkStartView.as_view(), name='bulk-start'),
    path('bulk/stop/', views.BulkStopView.as_view(), name='bulk-stop'),

    # Project detail, update, delete
    path('<int:project_id>/', views.ProjectDetailView.as_view(), name='detail'),

    # Job operations
    path('<int:project_id>/start/', views.JobStartView.as_view(), name='start'),
    path('<int:project_id>/stop/', views.JobStopView.as_view(), name='stop'),
    path('<int:project_id>/status/', views.JobStatusView.as_view(), name='status'),
    path('<int:project_id>/logs/', views.JobLogsView.as_view(), name='logs'),
    path('<int:project_id>/reset/', views.JobResetView.as_view(), name='reset'),
    path('<int:project_id>/history/', views.JobHistoryView.as_view(), name='history'),
    path('<int:project_id>/search/', views.JobSearchView.as_view(), name='search'),
]
