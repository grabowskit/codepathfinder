"""
Management command: create_otel_index_templates

Creates Elasticsearch data stream index templates for customer OTel telemetry:
  - traces-customer.*
  - metrics-customer.*
  - logs-customer.*

Uses data_stream mode so indices are automatically managed as time-series data
streams, compatible with the OTel Collector ES exporter's `mapping.mode: otel`.

Includes named dynamic templates for OTel metric types (counter_long,
counter_double, gauge_long, gauge_double) required by the otel mapping mode.

Supports both self-hosted ES and Elastic Cloud Serverless (skips component
templates and shard/replica settings on Serverless).

Run once after deploy (idempotent — PUT template is a create-or-update):
  python manage.py create_otel_index_templates
"""

import copy

from django.core.management.base import BaseCommand, CommandError
from projects.utils import get_es_client


# Common OTel resource field mappings (inlined on Serverless, composed on self-hosted)
_COMMON_PROPERTIES = {
    "cpf.project.id": {"type": "keyword"},
    "cpf.project.name": {"type": "keyword"},
    "service.name": {"type": "keyword"},
    "service.version": {"type": "keyword"},
    "deployment.environment": {"type": "keyword"},
    "host.name": {"type": "keyword"},
    "@timestamp": {"type": "date"},
}

# Shared component template (self-hosted only)
_CPF_COMPONENT_TEMPLATE = {
    "template": {
        "mappings": {
            "properties": _COMMON_PROPERTIES,
        }
    }
}

_TRACES_TEMPLATE = {
    "index_patterns": ["traces-customer.*"],
    "data_stream": {},
    "composed_of": ["otel-cpf-common"],
    "template": {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 1,
        },
        "mappings": {
            "properties": {
                "trace_id": {"type": "keyword"},
                "span_id": {"type": "keyword"},
                "parent_span_id": {"type": "keyword"},
                "name": {"type": "keyword"},
                "kind": {"type": "keyword"},
                "status.code": {"type": "keyword"},
                "status.message": {"type": "text"},
                "duration": {"type": "long"},
                "start_time_unix_nano": {"type": "long"},
                "end_time_unix_nano": {"type": "long"},
            }
        },
    },
    "priority": 500,
    "_meta": {"description": "CodePathfinder customer OTel traces"},
}

_METRICS_TEMPLATE = {
    "index_patterns": ["metrics-customer.*"],
    "data_stream": {},
    "composed_of": ["otel-cpf-common"],
    "template": {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 1,
        },
        "mappings": {
            # Named dynamic templates required by OTel Collector otel mapping mode.
            # The ES exporter bulk-indexes documents with per-document dynamic_templates
            # hints (e.g. {"metrics.my_counter": "counter_long"}), so these templates
            # must be defined by name in the index template.
            "dynamic_templates": [
                {"counter_long": {
                    "path_match": "metrics.*",
                    "match_mapping_type": "long",
                    "mapping": {"type": "long"}
                }},
                {"counter_double": {
                    "path_match": "metrics.*",
                    "match_mapping_type": "double",
                    "mapping": {"type": "double"}
                }},
                {"gauge_long": {
                    "path_match": "metrics.*",
                    "match_mapping_type": "long",
                    "mapping": {"type": "long"}
                }},
                {"gauge_double": {
                    "path_match": "metrics.*",
                    "match_mapping_type": "double",
                    "mapping": {"type": "double"}
                }},
                {"label": {
                    "path_match": "attributes.*",
                    "match_mapping_type": "string",
                    "mapping": {"type": "keyword"}
                }},
            ],
            "properties": {
                "name": {"type": "keyword"},
                "description": {"type": "text"},
                "unit": {"type": "keyword"},
                "start_time_unix_nano": {"type": "long"},
                "time_unix_nano": {"type": "long"},
            },
        },
    },
    "priority": 500,
    "_meta": {"description": "CodePathfinder customer OTel metrics"},
}

_LOGS_TEMPLATE = {
    "index_patterns": ["logs-customer.*"],
    "data_stream": {},
    "composed_of": ["otel-cpf-common"],
    "template": {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 1,
        },
        "mappings": {
            "dynamic_templates": [
                {"label": {
                    "path_match": "attributes.*",
                    "match_mapping_type": "string",
                    "mapping": {"type": "keyword"}
                }},
            ],
            "properties": {
                "severity_text": {"type": "keyword"},
                "severity_number": {"type": "integer"},
                "trace_id": {"type": "keyword"},
                "span_id": {"type": "keyword"},
                # OTel mapping mode sends body as {text: "..."} not a plain string
                "body": {
                    "properties": {
                        "text": {"type": "text"}
                    }
                },
                "time_unix_nano": {"type": "long"},
            }
        },
    },
    "priority": 500,
    "_meta": {"description": "CodePathfinder customer OTel logs"},
}


def _adapt_for_serverless(template):
    """Remove features unsupported by Elastic Cloud Serverless and inline common fields."""
    body = copy.deepcopy(template)
    body.pop("composed_of", None)
    body["template"].pop("settings", None)
    body["template"]["mappings"]["properties"].update(_COMMON_PROPERTIES)
    return body


class Command(BaseCommand):
    help = "Create Elasticsearch data stream index templates for customer OTel telemetry"

    def handle(self, *args, **options):
        es = get_es_client()
        if es is None:
            raise CommandError(
                "Elasticsearch is not configured. "
                "Set elasticsearch_endpoint and credentials in System Settings."
            )

        try:
            info = es.info()
            version = info['version']['number']
            build_flavor = info['version'].get('build_flavor', '')
            self.stdout.write(f"Connected to Elasticsearch {version} (flavor: {build_flavor or 'default'})")
        except Exception as exc:
            raise CommandError(f"Cannot connect to Elasticsearch: {exc}")

        serverless = build_flavor == 'serverless'

        if not serverless:
            # Self-hosted: create shared component template first
            self._put_component_template(es, "otel-cpf-common", _CPF_COMPONENT_TEMPLATE)

        for name, body in [
            ("otel-customer-traces", _TRACES_TEMPLATE),
            ("otel-customer-metrics", _METRICS_TEMPLATE),
            ("otel-customer-logs", _LOGS_TEMPLATE),
        ]:
            if serverless:
                body = _adapt_for_serverless(body)
            self._put_index_template(es, name, body)

        self.stdout.write(self.style.SUCCESS(
            "\nAll OTel index templates created successfully.\n"
            "Data stream templates cover:\n"
            "  traces-customer.*\n"
            "  metrics-customer.*\n"
            "  logs-customer.*"
        ))

    def _put_component_template(self, es, name, body):
        try:
            es.cluster.put_component_template(name=name, body=body)
            self.stdout.write(f"  ✓ Component template: {name}")
        except Exception as exc:
            raise CommandError(f"Failed to create component template '{name}': {exc}")

    def _put_index_template(self, es, name, body):
        try:
            es.indices.put_index_template(name=name, body=body)
            self.stdout.write(f"  ✓ Index template: {name}")
        except Exception as exc:
            raise CommandError(f"Failed to create index template '{name}': {exc}")
