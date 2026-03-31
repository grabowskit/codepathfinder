"""
LibreChat Integration Tests

Tests for LibreChat service availability and MCP integration.
"""
import pytest
import requests


@pytest.mark.smoke
@pytest.mark.librechat
class TestLibreChatIntegration:
    """Smoke tests for LibreChat integration."""

    def test_librechat_health(self, librechat_url):
        """LibreChat service responds on port 3080."""
        try:
            response = requests.get(
                f"{librechat_url}/",
                timeout=10,
                allow_redirects=True
            )
            # Any response means service is up
            assert response.status_code in (200, 302, 401), \
                f"LibreChat not responding: {response.status_code}"
        except requests.exceptions.ConnectionError:
            pytest.skip("LibreChat not running")

    def test_librechat_api_health(self, librechat_url):
        """LibreChat API health endpoint responds."""
        try:
            response = requests.get(
                f"{librechat_url}/api/health",
                timeout=10
            )
            # Health endpoint should return 200
            assert response.status_code == 200, \
                f"LibreChat API health failed: {response.status_code}"
        except requests.exceptions.ConnectionError:
            pytest.skip("LibreChat not running")

    def test_librechat_can_reach_mcp(self, base_url, internal_secret):
        """
        Verify the MCP endpoint is reachable with internal secret.

        This simulates what LibreChat does when connecting to CodePathfinder.
        """
        try:
            response = requests.post(
                f"{base_url}/mcp/",
                json={
                    'jsonrpc': '2.0',
                    'id': 1,
                    'method': 'initialize',
                    'params': {
                        'protocolVersion': '2024-11-05',
                        'capabilities': {},
                        'clientInfo': {
                            'name': 'librechat-integration-test',
                            'version': '1.0.0'
                        }
                    }
                },
                headers={
                    'Authorization': f'Bearer {internal_secret}',
                    'Content-Type': 'application/json'
                },
                timeout=10,
                verify=False
            )
            assert response.status_code == 200, \
                f"MCP not reachable: {response.status_code}"
            data = response.json()
            assert 'result' in data, f"Invalid MCP response: {data}"
        except requests.exceptions.ConnectionError as e:
            pytest.fail(f"Cannot reach MCP endpoint: {e}")

    def test_librechat_mcp_tools_available(self, base_url, internal_secret):
        """
        Verify MCP tools are discoverable via internal secret auth.

        This is what LibreChat uses to populate its tool list.
        """
        try:
            response = requests.post(
                f"{base_url}/mcp/",
                json={
                    'jsonrpc': '2.0',
                    'id': 1,
                    'method': 'tools/list',
                    'params': {}
                },
                headers={
                    'Authorization': f'Bearer {internal_secret}',
                    'Content-Type': 'application/json'
                },
                timeout=10,
                verify=False
            )
            assert response.status_code == 200
            data = response.json()
            assert 'result' in data
            tools = data['result']['tools']
            assert len(tools) >= 10, f"Expected at least 10 tools, got {len(tools)}"

            # Log available tools for debugging
            tool_names = [t['name'] for t in tools]
            print(f"Available MCP tools: {tool_names}")
        except requests.exceptions.ConnectionError as e:
            pytest.fail(f"Cannot reach MCP endpoint: {e}")
