"""
Project Management Tests

Tests for project listing, creation, and access control via MCP tools.
"""
import pytest


@pytest.mark.smoke
@pytest.mark.projects
class TestProjectManagement:
    """Smoke tests for project management."""

    def test_projects_page_requires_auth(self, base_url, http_client):
        """Projects page requires authentication."""
        response = http_client.get(
            f"{base_url}/projects/",
            timeout=10,
            allow_redirects=False
        )
        # Should redirect to login or return auth error
        assert response.status_code in (302, 401, 403), \
            f"Expected auth required, got {response.status_code}"

    def test_job_list_via_mcp(self, base_url, mcp_headers, http_client):
        """Can list projects/jobs via MCP job_status tool."""
        response = http_client.post(
            f"{base_url}/mcp/",
            json={
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'tools/call',
                'params': {
                    'name': 'job_status',
                    'arguments': {
                        'action': 'list'
                    }
                }
            },
            headers=mcp_headers,
            timeout=30
        )
        assert response.status_code == 200, f"Job list failed: {response.status_code}"
        data = response.json()
        assert 'result' in data, f"No result in response: {data}"
        assert 'content' in data['result'], f"No content in result: {data['result']}"

    def test_job_status_action(self, base_url, mcp_headers, http_client):
        """job_status tool accepts status action."""
        response = http_client.post(
            f"{base_url}/mcp/",
            json={
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'tools/call',
                'params': {
                    'name': 'job_status',
                    'arguments': {
                        'action': 'list',
                        'status_filter': 'all'
                    }
                }
            },
            headers=mcp_headers,
            timeout=30
        )
        assert response.status_code == 200, f"Job status failed: {response.status_code}"

    def test_size_tool_returns_stats(self, base_url, mcp_headers, http_client):
        """size tool returns index statistics."""
        response = http_client.post(
            f"{base_url}/mcp/",
            json={
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'tools/call',
                'params': {
                    'name': 'size',
                    'arguments': {}
                }
            },
            headers=mcp_headers,
            timeout=30
        )
        assert response.status_code == 200, f"Size tool failed: {response.status_code}"
        data = response.json()
        # Should have result or error (error OK if no projects indexed)
        assert 'result' in data or 'error' in data

    def test_api_projects_endpoint(self, base_url, http_client):
        """API projects endpoint exists (even if auth required)."""
        response = http_client.get(
            f"{base_url}/api/v1/jobs/",
            timeout=10
        )
        # Should return 401/403 without auth, not 404
        assert response.status_code in (200, 401, 403), \
            f"API endpoint missing, got {response.status_code}"

    def test_project_creation_requires_auth(self, base_url, http_client):
        """Project creation requires authentication."""
        response = http_client.post(
            f"{base_url}/api/v1/jobs/",
            json={
                'name': 'test-project',
                'repository_url': 'https://github.com/test/test'
            },
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        assert response.status_code in (401, 403), \
            f"Expected auth required for creation, got {response.status_code}"
