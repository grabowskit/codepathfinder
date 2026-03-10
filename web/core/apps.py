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
