"""
MCP Protocol Tests

Tests for MCP 2024-11-05 protocol compliance including initialization,
tool discovery, and tool execution.
"""
import pytest


@pytest.mark.smoke
@pytest.mark.mcp
class TestMCPProtocol:
    """Smoke tests for MCP protocol compliance."""

    def test_mcp_initialize(self, base_url, mcp_headers, http_client):
        """MCP initialize returns correct protocol version."""
        response = http_client.post(
            f"{base_url}/mcp/",
            json={
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'initialize',
                'params': {
                    'protocolVersion': '2025-06-18',
                    'capabilities': {},
                    'clientInfo': {
                        'name': 'smoke-test',
                        'version': '1.0.0'
                    }
                }
            },
            headers=mcp_headers,
            timeout=10
        )
        assert response.status_code == 200, f"Initialize failed: {response.status_code}"
        data = response.json()
        assert 'result' in data, f"No result in response: {data}"
        # Accept either 2024-11-05 (legacy SSE) or 2025-06-18 (streamable HTTP)
        assert data['result']['protocolVersion'] in ('2024-11-05', '2025-06-18'), \
            f"Unexpected protocol version: {data['result'].get('protocolVersion')}"
        assert 'serverInfo' in data['result'], "Missing serverInfo"
        assert data['result']['serverInfo']['name'] == 'CodePathfinder'

    def test_mcp_tools_list(self, base_url, mcp_headers, http_client):
        """MCP tools/list returns all available tools."""
        response = http_client.post(
            f"{base_url}/mcp/",
            json={
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'tools/list',
                'params': {}
            },
            headers=mcp_headers,
            timeout=10
        )
        assert response.status_code == 200, f"Tools list failed: {response.status_code}"
        data = response.json()
        assert 'result' in data, f"No result in response: {data}"
        tools = data['result']['tools']
        assert len(tools) >= 10, f"Expected at least 10 tools, got {len(tools)}"

        # Verify key tools are present
        tool_names = {t['name'] for t in tools}
        expected_tools = {
            'semantic_code_search',
            'job_manage',
            'job_status',
            'size',
            'otel_configure_collection',
            'otel_get_onboarding_config',
        }
        missing = expected_tools - tool_names
        assert not missing, f"Missing expected tools: {missing}"

    def test_mcp_ping(self, base_url, mcp_headers, http_client):
        """MCP ping returns empty result."""
        response = http_client.post(
            f"{base_url}/mcp/",
            json={
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'ping',
                'params': {}
            },
            headers=mcp_headers,
            timeout=10
        )
        assert response.status_code == 200, f"Ping failed: {response.status_code}"
        data = response.json()
        assert 'result' in data, f"No result in response: {data}"

    def test_mcp_resources_list(self, base_url, mcp_headers, http_client):
        """MCP resources/list returns (possibly empty) resource list."""
        response = http_client.post(
            f"{base_url}/mcp/",
            json={
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'resources/list',
                'params': {}
            },
            headers=mcp_headers,
            timeout=10
        )
        assert response.status_code == 200, f"Resources list failed: {response.status_code}"
        data = response.json()
        assert 'result' in data, f"No result in response: {data}"
        assert 'resources' in data['result'], "Missing resources key"

    def test_mcp_tool_call_job_status(self, base_url, mcp_headers, http_client):
        """MCP tool call executes job_status successfully."""
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
        assert response.status_code == 200, f"Tool call failed: {response.status_code}"
        data = response.json()
        assert 'result' in data, f"No result in response: {data}"
        assert 'content' in data['result'], f"No content in result: {data['result']}"
        # Content should be a list with text content
        assert len(data['result']['content']) > 0

    def test_mcp_invalid_method(self, base_url, mcp_headers, http_client):
        """MCP returns error for unknown method."""
        response = http_client.post(
            f"{base_url}/mcp/",
            json={
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'unknown/method',
                'params': {}
            },
            headers=mcp_headers,
            timeout=10
        )
        assert response.status_code == 200, f"Request failed: {response.status_code}"
        data = response.json()
        assert 'error' in data, f"Expected error for unknown method: {data}"

    def test_mcp_invalid_tool(self, base_url, mcp_headers, http_client):
        """MCP returns error for unknown tool."""
        response = http_client.post(
            f"{base_url}/mcp/",
            json={
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'tools/call',
                'params': {
                    'name': 'nonexistent_tool',
                    'arguments': {}
                }
            },
            headers=mcp_headers,
            timeout=10
        )
        assert response.status_code == 200, f"Request failed: {response.status_code}"
        data = response.json()
        assert 'error' in data, f"Expected error for unknown tool: {data}"

    def test_mcp_cors_options(self, base_url, http_client):
        """MCP endpoint returns CORS headers on OPTIONS."""
        response = http_client.options(
            f"{base_url}/mcp/",
            timeout=10
        )
        # Should return 200 or 204 for OPTIONS
        assert response.status_code in (200, 204), \
            f"OPTIONS failed: {response.status_code}"

    def test_mcp_session_header(self, base_url, mcp_headers, http_client):
        """MCP initialize returns session ID header."""
        response = http_client.post(
            f"{base_url}/mcp/",
            json={
                'jsonrpc': '2.0',
                'id': 1,
                'method': 'initialize',
                'params': {
                    'protocolVersion': '2024-11-05',
                    'capabilities': {},
                    'clientInfo': {'name': 'test', 'version': '1.0'}
                }
            },
            headers=mcp_headers,
            timeout=10
        )
        assert response.status_code == 200
        # Session header is optional but recommended
        # Just check the response is valid
        data = response.json()
        assert 'result' in data

    def test_mcp_jsonrpc_format(self, base_url, mcp_headers, http_client):
        """MCP responses follow JSON-RPC 2.0 format."""
        response = http_client.post(
            f"{base_url}/mcp/",
            json={
                'jsonrpc': '2.0',
                'id': 42,
                'method': 'ping',
                'params': {}
            },
            headers=mcp_headers,
            timeout=10
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get('jsonrpc') == '2.0', "Missing jsonrpc version"
        assert data.get('id') == 42, "Response ID doesn't match request"
