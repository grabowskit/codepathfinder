"""
Request logging middleware.

Logs every HTTP request with method, path, status code, duration, and user.
Flows through the OTel logging pipeline into Elasticsearch.
"""
import logging
import time

logger = logging.getLogger('core.requests')


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self._ensured_otel = False

    def __call__(self, request):
        if not self._ensured_otel:
            self._ensured_otel = True
            self._ensure_otel_handler()
        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = (time.monotonic() - start) * 1000

        user = getattr(request, 'user', None)
        username = user.username if user and user.is_authenticated else 'anonymous'

        # Skip health checks to reduce noise
        if request.path == '/health/':
            return response

        level = logging.WARNING if response.status_code >= 400 else logging.INFO
        logger.log(
            level,
            "%s %s %d %.0fms user=%s",
            request.method,
            request.path,
            response.status_code,
            duration_ms,
            username,
        )

        return response

    @staticmethod
    def _ensure_otel_handler():
        """Ensure the OTel LoggingHandler is on the root logger.

        Django's dictConfig(LOGGING) may have wiped it after AppConfig.ready()
        added it. Re-attach if missing.
        """
        import os
        if os.environ.get('OTEL_ENABLED') != 'true':
            return

        root = logging.getLogger()
        has_otel = any(
            type(h).__name__ == 'LoggingHandler' for h in root.handlers
        )
        if has_otel:
            return

        try:
            from opentelemetry._logs import get_logger_provider
            from opentelemetry.sdk._logs import LoggingHandler

            lp = get_logger_provider()
            # Only attach if we have a real (not proxy) LoggerProvider
            if type(lp).__name__ == 'LoggerProvider':
                handler = LoggingHandler(level=logging.INFO, logger_provider=lp)
                root.addHandler(handler)
                logger.info("Re-attached OTel LoggingHandler to root logger (pid=%s)", os.getpid())
        except Exception:
            pass
