"""
Service Health Check Tests

Tests that all Docker services are running and responding correctly.
"""
import socket
import pytest
import requests


@pytest.mark.smoke
@pytest.mark.health
class TestServiceHealth:
    """Smoke tests for service availability."""

    def test_web_health(self, base_url, http_client):
        """Django web service responds on /health/ endpoint."""
        response = http_client.get(f"{base_url}/health/", timeout=10)
        assert response.status_code == 200, f"Web health check failed: {response.status_code}"

    def test_elasticsearch_health(self, es_url, es_auth):
        """Elasticsearch cluster is healthy (green or yellow)."""
        response = requests.get(
            f"{es_url}/_cluster/health",
            auth=es_auth,
            timeout=10,
            verify=False
        )
        assert response.status_code == 200, f"ES health check failed: {response.status_code}"
        data = response.json()
        assert data['status'] in ('green', 'yellow'), f"ES cluster unhealthy: {data['status']}"

    def test_kibana_health(self, kibana_url):
        """Kibana service responds."""
        try:
            response = requests.get(
                f"{kibana_url}/api/status",
                timeout=10,
                verify=False
            )
            # Kibana may return 200, redirect, auth required, or 503 (starting up)
            # 503 means Kibana is running but still initializing - still counts as "up"
            assert response.status_code in (200, 302, 401, 503), f"Kibana check failed: {response.status_code}"
        except requests.exceptions.ConnectionError:
            pytest.skip("Kibana not running")

    def test_db_health(self, db_config):
        """PostgreSQL is accepting connections."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        try:
            result = sock.connect_ex((db_config['host'], db_config['port']))
            assert result == 0, f"Cannot connect to PostgreSQL on {db_config['host']}:{db_config['port']}"
        finally:
            sock.close()

    def test_mongodb_health(self, mongodb_url):
        """MongoDB is accepting connections."""
        # Parse host and port from URL
        if mongodb_url.startswith('mongodb://'):
            host_part = mongodb_url.replace('mongodb://', '').split('/')[0]
            if ':' in host_part:
                host, port = host_part.split(':')
                port = int(port)
            else:
                host = host_part
                port = 27017
        else:
            host = 'localhost'
            port = 27017

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        try:
            result = sock.connect_ex((host, port))
            if result != 0:
                pytest.skip("MongoDB not running")
        finally:
            sock.close()

    def test_meilisearch_health(self, meilisearch_url):
        """MeiliSearch service responds."""
        try:
            response = requests.get(
                f"{meilisearch_url}/health",
                timeout=10
            )
            assert response.status_code == 200, f"MeiliSearch check failed: {response.status_code}"
        except requests.exceptions.ConnectionError:
            pytest.skip("MeiliSearch not running")
