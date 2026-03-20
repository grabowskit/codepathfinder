"""
Management command: send_telemetry_heartbeat

Sends aggregated daily feature usage counts to the CodePathfinder telemetry endpoint.
Reads counter values from Django cache and resets them to zero.

Run daily (e.g. add to docker-compose as a scheduled one-shot service, or cron):
  python manage.py send_telemetry_heartbeat
"""

from django.core.management.base import BaseCommand
from telemetry.client import send_feature_counts, is_enabled
from telemetry.counters import get_and_reset


class Command(BaseCommand):
    help = 'Send daily telemetry heartbeat (feature_counts event)'

    def handle(self, *args, **options):
        if not is_enabled():
            self.stdout.write("Telemetry disabled (TELEMETRY_ENABLED=false). Skipping.")
            return

        counts = get_and_reset()
        send_feature_counts(
            search_count=counts.get('search_count', 0),
            index_count=counts.get('index_count', 0),
            mcp_call_counts=counts.get('mcp_call_counts', {}),
            memory_access_count=counts.get('memory_access_count', 0),
        )
        self.stdout.write(self.style.SUCCESS(f"Sent feature_counts: {counts}"))
