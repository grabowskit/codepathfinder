"""OTel Collection Smoke Tests"""
import pytest


@pytest.mark.smoke
@pytest.mark.mcp
class TestOtelCollectionTools:
    def test_otel_tools_in_tools_list(self, base_url, mcp_headers, http_client):
        """OTel tools appear in MCP tools/list."""
        response = http_client.post(
            f"{base_url}/mcp/",
            json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}},
            headers=mcp_headers,
            timeout=10,
        )
        assert response.status_code == 200
        tool_names = {t['name'] for t in response.json()['result']['tools']}
        assert 'otel_configure_collection' in tool_names
        assert 'otel_get_onboarding_config' in tool_names
        assert 'otel_query_traces' in tool_names
        assert 'otel_query_metrics' in tool_names
        assert 'otel_query_logs' in tool_names

    def test_otel_query_tools_require_project(self, base_url, mcp_headers, http_client):
        """otel_query_* tools return an error when project arg is missing."""
        for tool in ('otel_query_traces', 'otel_query_metrics', 'otel_query_logs'):
            response = http_client.post(
                f"{base_url}/mcp/",
                json={
                    'jsonrpc': '2.0',
                    'id': 1,
                    'method': 'tools/call',
                    'params': {'name': tool, 'arguments': {}},
                },
                headers=mcp_headers,
                timeout=10,
            )
            assert response.status_code == 200, f"{tool} should return 200 even on error"
            result = response.json()
            # Should return an error (isError=True) rather than crashing
            assert result.get('result', {}).get('isError') or 'error' in result, (
                f"{tool} should report an error when project is missing"
            )

    def test_otlp_ingest_rejects_missing_auth(self, base_url, http_client):
        """OTLP ingest endpoints return 401 without a valid Bearer token."""
        for signal in ('traces', 'metrics', 'logs'):
            response = http_client.post(
                f"{base_url}/otel/v1/{signal}",
                data=b"",
                headers={"Content-Type": "application/x-protobuf"},
                timeout=10,
            )
            assert response.status_code == 401, (
                f"/otel/v1/{signal} should require auth, got {response.status_code}"
            )

    def test_otlp_ingest_rejects_wrong_scope(self, base_url, mcp_headers, http_client):
        """OTLP ingest endpoint rejects a non-otel-scoped key (MCP key used here)."""
        # The MCP key has 'mcp' scope, not 'otel'
        for signal in ('traces', 'metrics', 'logs'):
            response = http_client.post(
                f"{base_url}/otel/v1/{signal}",
                data=b"",
                headers={
                    "Content-Type": "application/x-protobuf",
                    "Authorization": mcp_headers.get("Authorization", ""),
                },
                timeout=10,
            )
            # Should be 401 (invalid key format) or 401 (wrong scope)
            assert response.status_code in (401, 403), (
                f"/otel/v1/{signal} should reject non-otel key, got {response.status_code}"
            )
