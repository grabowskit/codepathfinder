from django.urls import path
from . import views

urlpatterns = [
    path('', views.MemoryListView.as_view(), name='memory_list'),
    path('create/', views.MemoryCreateView.as_view(), name='memory_create'),
    path('import/', views.MemoryImportView.as_view(), name='memory_import'),
    path('api/search/', views.MemorySearchAPIView.as_view(), name='memory_search_api'),
    path('<int:pk>/', views.MemoryDetailView.as_view(), name='memory_detail'),
    path('<int:pk>/edit/', views.MemoryUpdateView.as_view(), name='memory_update'),
    path('<int:pk>/delete/', views.MemoryDeleteView.as_view(), name='memory_delete'),
]
