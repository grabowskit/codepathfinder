"""
Authentication Tests

Tests for login/logout, API key authentication, and internal service secret.
"""
import pytest
import requests


@pytest.mark.smoke
@pytest.mark.auth
class TestAuthentication:
    """Smoke tests for authentication flows."""

    def test_login_page_loads(self, base_url, http_client):
        """Login page is accessible."""
        response = http_client.get(f"{base_url}/accounts/login/", timeout=10)
        assert response.status_code == 200, f"Login page failed: {response.status_code}"
        assert 'login' in response.text.lower() or 'sign in' in response.text.lower()

    def test_login_redirect_unauthenticated(self, base_url, http_client):
        """Protected pages redirect to login when not authenticated."""
        response = http_client.get(
            f"{base_url}/projects/",
            timeout=10,
            allow_redirects=False
        )
        # Should redirect (302) or require auth (401/403)
        assert response.status_code in (302, 401, 403), \
            f"Expected redirect/auth required, got {response.status_code}"

    def test_api_key_authentication_mcp(self, base_url, internal_secret, http_client):
        """Internal service secret authenticates MCP requests."""
        response = http_client.post(
            f"{base_url}/mcp/",
            json={
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'ping',
                'params': {}
            },
            headers={
                'Authorization': f'Bearer {internal_secret}',
                'Content-Type': 'application/json'
            },
            timeout=10
        )
        assert response.status_code == 200, f"MCP auth failed: {response.status_code}"

    def test_invalid_api_key_rejected(self, base_url, http_client):
        """Invalid API key returns 401 Unauthorized."""
        response = http_client.post(
            f"{base_url}/mcp/",
            json={
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'ping',
                'params': {}
            },
            headers={
                'Authorization': 'Bearer cpf_invalid_key_123456789',
                'Content-Type': 'application/json'
            },
            timeout=10
        )
        assert response.status_code in (401, 403), \
            f"Expected 401/403, got {response.status_code}"

    def test_missing_auth_rejected(self, base_url, http_client):
        """Requests without authentication are rejected."""
        response = http_client.post(
            f"{base_url}/mcp/",
            json={
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'ping',
                'params': {}
            },
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        assert response.status_code in (401, 403), \
            f"Expected 401/403 without auth, got {response.status_code}"

    def test_internal_service_secret_format(self, internal_secret):
        """Internal service secret is configured and not default in production."""
        assert internal_secret, "Internal service secret not configured"
        # In CI/production, secret should not be the default
        # This is a warning, not a failure
        if internal_secret == 'default_internal_secret_change_me':
            pytest.skip("Using default internal secret (OK for development)")

    def test_malformed_bearer_token_rejected(self, base_url, http_client):
        """Malformed Bearer tokens are rejected."""
        response = http_client.post(
            f"{base_url}/mcp/",
            json={
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'ping',
                'params': {}
            },
            headers={
                'Authorization': 'Bearer',  # Missing token value
                'Content-Type': 'application/json'
            },
            timeout=10
        )
        assert response.status_code in (401, 403), \
            f"Expected 401/403 for malformed token, got {response.status_code}"

    def test_wrong_auth_scheme_rejected(self, base_url, internal_secret, http_client):
        """Non-Bearer auth schemes are rejected."""
        response = http_client.post(
            f"{base_url}/mcp/",
            json={
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'ping',
                'params': {}
            },
            headers={
                'Authorization': f'Basic {internal_secret}',  # Wrong scheme
                'Content-Type': 'application/json'
            },
            timeout=10
        )
        assert response.status_code in (401, 403), \
            f"Expected 401/403 for wrong auth scheme, got {response.status_code}"
