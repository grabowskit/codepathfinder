"""
Detect what setup.sh and manual configuration have already done.
Used by the onboarding wizard to show pre-configured state.
"""
import os

from django.conf import settings as django_settings

from core.models import SystemSettings
from projects.models import PathfinderProject


def detect_setup_state(user):
    """Return a dict describing the current configuration state."""
    sys = SystemSettings.get_settings()

    state = {}

    # -- Elasticsearch --
    es_env_endpoint = os.getenv('ELASTICSEARCH_ENDPOINT', '')
    es_env_cloud_id = os.getenv('ELASTICSEARCH_CLOUD_ID', '')
    es_env_api_key = os.getenv('ELASTICSEARCH_API_KEY', '')
    es_db_endpoint = sys.elasticsearch_endpoint
    es_db_cloud_id = sys.elasticsearch_cloud_id

    es_from_env = bool(es_env_endpoint or es_env_cloud_id)
    es_from_db = bool(es_db_endpoint or es_db_cloud_id)
    es_configured = es_from_env or es_from_db

    state['elasticsearch'] = {
        'configured': es_configured,
        'source': 'env' if es_from_env else ('db' if es_from_db else None),
        'mode': 'cloud' if (es_env_cloud_id or es_db_cloud_id) else ('local' if es_configured else None),
        'endpoint': es_env_endpoint or es_db_endpoint or '',
        'cloud_id': es_env_cloud_id or es_db_cloud_id or '',
        'has_auth': bool(es_env_api_key or sys.elasticsearch_api_key or sys.elasticsearch_user),
    }

    # -- Admin Profile --
    state['admin_profile'] = {
        'has_email': bool(user.email),
        'has_name': bool(user.first_name or user.last_name),
        'username': user.username,
    }

    # -- LLM / LibreChat --
    librechat_url = os.getenv('LIBRECHAT_EXTERNAL_URL', '')
    oidc_key = os.getenv('OIDC_RSA_PRIVATE_KEY', '')
    state['librechat'] = {
        'url_configured': bool(librechat_url),
        'oidc_configured': bool(oidc_key),
        'url': librechat_url,
    }

    # -- First Project --
    project_count = PathfinderProject.objects.filter(user=user).count()
    state['first_project'] = {
        'has_projects': project_count > 0,
        'count': project_count,
    }

    # -- OTel (informational) --
    state['otel'] = {
        'enabled': sys.otel_collector_enabled,
        'endpoint': sys.otel_collector_endpoint,
    }

    # -- Skills Repo --
    state['skills'] = {
        'configured': bool(sys.skills_repo_url),
        'url': sys.skills_repo_url,
    }

    return state
