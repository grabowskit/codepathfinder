from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        import core.signals  # noqa: F401 — register auth event handlers

        # Initialize OTel AFTER Django's logging config has been applied,
        # so our LoggingHandler doesn't get wiped by dictConfig(LOGGING).
        from otel_setup import configure_otel
        configure_otel()

        # OSS telemetry: fire startup event (fire-and-forget, never blocks startup)
        try:
            from telemetry.client import send_startup_event, is_enabled
            if is_enabled():
                from django.core.cache import cache
                count = (cache.get('cpf_startup_count') or 0) + 1
                cache.set('cpf_startup_count', count, timeout=None)
                send_startup_event(uptime_count=count)
        except Exception:
            pass
