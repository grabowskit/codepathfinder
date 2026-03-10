"""
URL configuration for the chat feature.

Chat functionality is provided by LibreChat.
"""
from django.urls import path
from . import views

urlpatterns = [
    # LibreChat redirect - redirects to LibreChat via OIDC
    path('', views.LibreChatEmbedView.as_view(), name='chat_embed'),
]
