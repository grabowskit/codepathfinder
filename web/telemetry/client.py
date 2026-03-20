"""
OSS telemetry client for CodePathfinder.

Sends anonymous usage events to the CodePathfinder telemetry endpoint.
Uses only Python stdlib — no extra dependencies.

Privacy: only sends installation_id (random UUID), version, and numeric counts.
No PII, no repo names, no file contents, no IP addresses stored.

Opt-out: set TELEMETRY_ENABLED=false in .env
What we collect: https://codepathfinder.com/docs/telemetry (or docs/TELEMETRY.md)
"""

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

TELEMETRY_ENDPOINT = "https://codepathfinder.com/telemetry/event"


def is_enabled() -> bool:
    """Telemetry is enabled by default. Set TELEMETRY_ENABLED=false to opt out."""
    val = os.getenv('TELEMETRY_ENABLED', 'true').strip().lower()
    return val in ('true', '1', 'yes')


def _get_installation_id() -> str:
    return os.getenv('INSTALLATION_ID', '').strip()


def _send(event_type: str, payload: dict) -> None:
    """Fire-and-forget HTTP POST. Eats all exceptions silently."""
    if not is_enabled():
        return
    installation_id = _get_installation_id()
    if not installation_id:
        return

    version = os.getenv('CPF_VERSION', 'unknown')
    doc = {
        "event_type": event_type,
        "installation_id": installation_id,
        "version": version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **payload,
    }

    def _do_send():
        try:
            body = json.dumps(doc).encode('utf-8')
            req = urllib.request.Request(
                TELEMETRY_ENDPOINT,
                data=body,
                method='POST',
                headers={
                    'Content-Type': 'application/json',
                    'User-Agent': f'cpf/{version}',
                },
            )
            with urllib.request.urlopen(req, timeout=5):
                pass
        except Exception:
            pass  # Never raise, never log — telemetry must be invisible on failure

    t = threading.Thread(target=_do_send, daemon=True)
    t.start()


def send_install_event(os_type: str, es_mode: str, llm_providers_count: int, org_name: str = '') -> None:
    """Send an install event (called from setup.sh via management command or curl)."""
    payload = {
        'os_type': os_type,
        'es_mode': es_mode,
        'llm_providers_count': llm_providers_count,
    }
    if org_name:
        payload['org_name'] = org_name
    _send('install', payload)


def send_startup_event(uptime_count: int) -> None:
    """Send a startup event (called from CoreConfig.ready())."""
    _send('startup', {'uptime_count': uptime_count})


def send_feature_counts(
    search_count: int,
    index_count: int,
    mcp_call_counts: dict,
    memory_access_count: int,
) -> None:
    """Send aggregated daily feature counts (called from management command)."""
    _send('feature_counts', {
        'search_count': search_count,
        'index_count': index_count,
        'mcp_call_counts': mcp_call_counts,
        'memory_access_count': memory_access_count,
    })
