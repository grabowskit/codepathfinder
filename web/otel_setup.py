"""
Internal OpenTelemetry instrumentation for the CodePathfinder web service.

Sends traces and metrics directly to the internal OTel Collector
(http://otel-collector:4318) — no auth required since this is internal traffic.
The collector routes to Elasticsearch based on the cpf.project.id resource attribute.

Enabled via OTEL_ENABLED=true. All other config via environment variables:
  OTEL_SERVICE_NAME          - service.name in telemetry (default: codepathfinder-web)
  OTEL_COLLECTOR_ENDPOINT    - internal collector base URL (default: http://otel-collector:4318)
  CPF_PROJECT_ID             - numeric project ID for index routing (e.g. 12)
"""
import os
import logging

logger = logging.getLogger(__name__)


_initialized = False


def configure_otel():
    global _initialized
    if _initialized or os.environ.get('OTEL_ENABLED') != 'true':
        return
    _initialized = True

    from opentelemetry import trace, metrics
    from opentelemetry._logs import set_logger_provider
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.instrumentation.django import DjangoInstrumentor

    collector = os.environ.get('OTEL_COLLECTOR_ENDPOINT', 'http://otel-collector:4318')
    service_name = os.environ.get('OTEL_SERVICE_NAME', 'codepathfinder-web')
    project_id = os.environ.get('CPF_PROJECT_ID', '')

    resource = Resource(attributes={
        'service.name': service_name,
        'cpf.project.id': project_id,
    })

    # Traces
    tp = TracerProvider(resource=resource)
    tp.add_span_processor(BatchSpanProcessor(
        OTLPSpanExporter(endpoint=f"{collector}/v1/traces")
    ))
    trace.set_tracer_provider(tp)

    # Metrics (export every 30s to see data quickly)
    mp = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=f"{collector}/v1/metrics"),
            export_interval_millis=30_000,
        )],
    )
    metrics.set_meter_provider(mp)

    # Logs — bridge Python's logging module to OTel
    lp = LoggerProvider(resource=resource)
    lp.add_log_record_processor(BatchLogRecordProcessor(
        OTLPLogExporter(endpoint=f"{collector}/v1/logs")
    ))
    set_logger_provider(lp)
    # Attach handler to root logger so all Django/app logs flow to OTel
    otel_handler = LoggingHandler(level=logging.INFO, logger_provider=lp)
    logging.getLogger().addHandler(otel_handler)

    # Auto-instrument all Django HTTP requests
    DjangoInstrumentor().instrument()

    logging.getLogger(__name__).info(
        "OTel initialized: service=%s project=%s collector=%s (traces+metrics+logs)",
        service_name, project_id, collector,
    )
