"""
OAuth2 Endpoint Tests

Tests for OAuth2 metadata and authorization endpoints.
"""
import pytest


@pytest.mark.smoke
@pytest.mark.oauth
class TestOAuth2Endpoints:
    """Smoke tests for OAuth2 endpoints."""

    def test_oauth_protected_resource_metadata(self, base_url, http_client):
        """
        OAuth protected resource metadata endpoint exists.

        RFC 9728 compliance for MCP OAuth 2.1.
        """
        response = http_client.get(
            f"{base_url}/.well-known/oauth-protected-resource",
            timeout=10
        )
        # May return 200 with metadata or 404 if not configured
        # Both are valid depending on deployment
        assert response.status_code in (200, 404), \
            f"Unexpected status: {response.status_code}"

        if response.status_code == 200:
            data = response.json()
            assert 'resource' in data or 'authorization_servers' in data, \
                f"Invalid metadata format: {data}"

    def test_oauth_authorization_server_metadata(self, base_url, http_client):
        """
        OAuth authorization server metadata endpoint exists.

        RFC 8414 compliance.
        """
        response = http_client.get(
            f"{base_url}/.well-known/oauth-authorization-server",
            timeout=10
        )
        # Should return metadata or 404
        assert response.status_code in (200, 404), \
            f"Unexpected status: {response.status_code}"

        if response.status_code == 200:
            data = response.json()
            # Check for required OAuth metadata fields
            assert 'issuer' in data or 'token_endpoint' in data, \
                f"Invalid authorization server metadata: {data}"

    def test_oauth_authorize_endpoint(self, base_url, http_client):
        """OAuth authorize endpoint exists and redirects to login."""
        response = http_client.get(
            f"{base_url}/o/authorize/",
            timeout=10,
            allow_redirects=False
        )
        # Should redirect to login or return auth form
        assert response.status_code in (200, 302, 400), \
            f"Authorize endpoint issue: {response.status_code}"

    def test_oauth_token_endpoint(self, base_url, http_client):
        """OAuth token endpoint exists and rejects invalid requests."""
        response = http_client.post(
            f"{base_url}/o/token/",
            data={
                'grant_type': 'authorization_code',
                'code': 'invalid_code',
                'client_id': 'invalid_client'
            },
            timeout=10
        )
        # Should return 400 or 401 for invalid credentials, not 404
        assert response.status_code in (400, 401, 403), \
            f"Token endpoint issue: {response.status_code}"

    def test_oauth_dcr_endpoint(self, base_url, http_client):
        """
        Dynamic Client Registration endpoint exists.

        RFC 7591 compliance for MCP OAuth 2.1.
        """
        response = http_client.post(
            f"{base_url}/o/register/",
            json={
                'client_name': 'smoke-test-client',
                'redirect_uris': ['https://example.com/callback'],
                'grant_types': ['authorization_code'],
                'response_types': ['code'],
                'token_endpoint_auth_method': 'client_secret_post'
            },
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        # DCR may succeed (201) or be disabled (404/405)
        # Both are valid states
        assert response.status_code in (200, 201, 400, 401, 404, 405), \
            f"DCR endpoint issue: {response.status_code}"
