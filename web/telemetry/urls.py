"""URL routing for telemetry app."""

from django.urls import path
from . import views

app_name = 'telemetry'

urlpatterns = [
    path('event', views.event_view, name='event'),
]
