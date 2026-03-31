"""
Pytest fixtures for CodePathfinder smoke tests.

These fixtures provide reusable components for testing services,
authentication, and API endpoints.
"""
import os
import sys
import pytest
import requests
import urllib3

# Suppress SSL warnings for self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Add web directory to path for Django imports
WEB_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'web')
if WEB_DIR not in sys.path:
    sys.path.insert(0, WEB_DIR)

# Load .env from project root so ELASTICSEARCH_PASSWORD etc. are available
_ROOT = os.path.join(os.path.dirname(__file__), '..', '..')
_dotenv_path = os.path.join(_ROOT, '.env')
if os.path.exists(_dotenv_path):
    with open(_dotenv_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _, _v = _line.partition('=')
                os.environ.setdefault(_k.strip(), _v.strip())


@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL for web service HTTP tests (uses HTTPS by default due to nginx redirect)."""
    return os.getenv('SMOKE_TEST_BASE_URL', 'https://localhost:8443')


@pytest.fixture(scope="session")
def es_url() -> str:
    """Elasticsearch URL."""
    return os.getenv('SMOKE_TEST_ES_URL', 'http://localhost:9200')


@pytest.fixture(scope="session")
def es_password() -> str:
    """Elasticsearch password."""
    return os.getenv('ELASTICSEARCH_PASSWORD', 'changeme')


@pytest.fixture(scope="session")
def es_auth(es_password) -> tuple:
    """Elasticsearch authentication tuple."""
    return ('elastic', es_password)


@pytest.fixture(scope="session")
def mongodb_url() -> str:
    """MongoDB connection URL."""
    return os.getenv('SMOKE_TEST_MONGODB_URL', 'mongodb://localhost:27017')


@pytest.fixture(scope="session")
def meilisearch_url() -> str:
    """MeiliSearch URL."""
    return os.getenv('SMOKE_TEST_MEILISEARCH_URL', 'http://localhost:7700')


@pytest.fixture(scope="session")
def librechat_url() -> str:
    """LibreChat URL."""
    return os.getenv('SMOKE_TEST_LIBRECHAT_URL', 'http://localhost:3080')


@pytest.fixture(scope="session")
def kibana_url() -> str:
    """Kibana URL."""
    return os.getenv('SMOKE_TEST_KIBANA_URL', 'http://localhost:5601')


@pytest.fixture(scope="session")
def internal_secret() -> str:
    """Internal service secret for MCP authentication."""
    return os.getenv('CPF_INTERNAL_SERVICE_SECRET', 'default_internal_secret_change_me')


@pytest.fixture(scope="session")
def db_config() -> dict:
    """PostgreSQL database configuration."""
    return {
        'host': os.getenv('POSTGRES_HOST', 'localhost'),
        'port': int(os.getenv('POSTGRES_PORT', '5432')),
        'database': os.getenv('POSTGRES_DB', 'codepathfinder'),
        'user': os.getenv('POSTGRES_USER', 'postgres'),
        'password': os.getenv('POSTGRES_PASSWORD', 'postgres'),
    }


@pytest.fixture(scope="session")
def http_client() -> requests.Session:
    """
    Reusable HTTP session with default settings.

    Configured for local development with:
    - SSL verification disabled (self-signed certs)
    - 30 second timeout
    """
    session = requests.Session()
    session.verify = False
    session.timeout = 30
    return session


@pytest.fixture(scope="function")
def mcp_headers(internal_secret) -> dict:
    """Headers for MCP API requests with internal secret auth."""
    return {
        'Authorization': f'Bearer {internal_secret}',
        'Content-Type': 'application/json',
    }


def mcp_request(method: str, id: int = 1, params: dict = None) -> dict:
    """Helper to build JSON-RPC request for MCP."""
    request = {
        'jsonrpc': '2.0',
        'id': id,
        'method': method,
    }
    if params is not None:
        request['params'] = params
    return request
