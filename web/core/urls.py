from django.urls import path
from django.contrib.auth import views as auth_views
from django.views.generic import RedirectView
from . import views

urlpatterns = [
    # Core app URLs
    path('login/', RedirectView.as_view(pattern_name='account_login', permanent=True), name='login'),
    path('logout/', views.SSOLogoutView.as_view(), name='logout'),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('users/', views.AdminUserListView.as_view(), name='admin_user_list'),
    path('users/create/', views.AdminUserCreateView.as_view(), name='admin_user_create'),
    path('docs/', views.DocumentationView.as_view(), name='documentation'),
    path('beta/', views.BetaSignupView.as_view(), name='beta_signup'),
    path('beta/approve/<str:token>/', views.ApproveBetaUserView.as_view(), name='approve_beta_user'),
    path('delete-account/', views.DeleteAccountView.as_view(), name='delete_account'),
    path('users/<int:pk>/edit/', views.AdminUserUpdateView.as_view(), name='admin_user_edit'),
    path('users/<int:pk>/delete/', views.AdminUserDeleteView.as_view(), name='admin_user_delete'),
    path('settings/', views.AdminSettingsView.as_view(), name='admin_settings'),
    path('setup/', views.SetupWizardView.as_view(), name='setup_wizard'),
    path('setup/restart/', views.RestartWizardView.as_view(), name='restart_wizard'),
    path('', views.LandingPageView.as_view(), name='home'),
]
