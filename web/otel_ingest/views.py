"""
OTLP Auth Proxy for CodePathfinder

Validates otel-scoped project API keys and forwards OTLP requests to the
internal OTel Collector. This is the only externally-exposed OTLP endpoint
— the collector itself runs on the internal network with no auth.

Supported endpoints:
  POST /otel/v1/traces   — OTLP HTTP traces (protobuf or JSON)
  POST /otel/v1/metrics  — OTLP HTTP metrics
  POST /otel/v1/logs     — OTLP HTTP logs

Auth: Bearer <otel-scoped ProjectAPIKey>
"""

import logging
import os
import urllib.request
import urllib.error
from django.http import HttpResponse
from django.utils import timezone
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from projects.models import ProjectAPIKey

logger = logging.getLogger(__name__)

# Internal collector endpoint — overridable via env for K8s vs Docker Compose
COLLECTOR_HTTP_BASE = os.environ.get(
    "OTEL_COLLECTOR_INTERNAL_URL", "http://otel-collector:4318"
)


def _get_collector_url(signal: str) -> str:
    return f"{COLLECTOR_HTTP_BASE}/v1/{signal}"


def _authenticate_otel_key(request):
    """
    Validate the Bearer token for otel scope.

    Returns:
        (ProjectAPIKey, None) on success
        (None, error_message) on failure
    """
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    parts = auth_header.split()

    if len(parts) != 2 or parts[0] != "Bearer":
        return None, "Missing or malformed Authorization header"

    raw_key = parts[1]
    if not raw_key.startswith("cpf_"):
        return None, "Invalid API key format"

    hashed = ProjectAPIKey.hash_key(raw_key)
    try:
        api_key = ProjectAPIKey.objects.select_related("project").get(
            hashed_key=hashed,
            is_active=True,
        )
    except ProjectAPIKey.DoesNotExist:
        return None, "Invalid or revoked API key"

    if api_key.scope not in ("otel", "all"):
        return None, "API key does not have otel ingest access"

    return api_key, None


def _proxy_to_collector(signal: str, request) -> HttpResponse:
    """Validate auth and proxy to the internal OTel Collector."""
    api_key, error = _authenticate_otel_key(request)
    if error:
        logger.warning("OTel ingest auth failure: %s", error)
        return HttpResponse(error, status=401, content_type="text/plain")

    # Check that OTel collection is enabled for this project
    try:
        otel_settings = api_key.project.otel_settings
    except Exception:
        return HttpResponse(
            "OTel collection not configured for this project", status=403, content_type="text/plain"
        )

    if not otel_settings.enabled:
        return HttpResponse(
            "OTel collection is disabled for this project", status=403, content_type="text/plain"
        )

    # Forward to collector
    target_url = _get_collector_url(signal)
    content_type = request.content_type or "application/x-protobuf"

    try:
        req = urllib.request.Request(
            url=target_url,
            data=request.body,
            method="POST",
            headers={"Content-Type": content_type},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            response = HttpResponse(
                body,
                status=resp.status,
                content_type=resp.headers.get("Content-Type", "application/json"),
            )
    except urllib.error.HTTPError as e:
        body = e.read()
        logger.error("Collector returned %s for /v1/%s: %s", e.code, signal, body[:200])
        return HttpResponse(body, status=e.code, content_type="application/json")
    except Exception as exc:
        logger.error("Failed to proxy OTLP /v1/%s to collector: %s", signal, exc)
        return HttpResponse("Collector unavailable", status=503, content_type="text/plain")

    # Update last_used_at asynchronously (fire-and-forget in the same request cycle)
    ProjectAPIKey.objects.filter(pk=api_key.pk).update(last_used_at=timezone.now())

    return response


@method_decorator(csrf_exempt, name="dispatch")
class OtlpTracesView(View):
    def post(self, request):
        return _proxy_to_collector("traces", request)


@method_decorator(csrf_exempt, name="dispatch")
class OtlpMetricsView(View):
    def post(self, request):
        return _proxy_to_collector("metrics", request)


@method_decorator(csrf_exempt, name="dispatch")
class OtlpLogsView(View):
    def post(self, request):
        return _proxy_to_collector("logs", request)
