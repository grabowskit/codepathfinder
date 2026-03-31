from django.urls import path
from .views import OtlpTracesView, OtlpMetricsView, OtlpLogsView

urlpatterns = [
    path("v1/traces", OtlpTracesView.as_view(), name="otlp_traces"),
    path("v1/metrics", OtlpMetricsView.as_view(), name="otlp_metrics"),
    path("v1/logs", OtlpLogsView.as_view(), name="otlp_logs"),
]
