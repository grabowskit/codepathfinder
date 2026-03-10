"""
OpenAPI authentication extensions for drf-spectacular.

Registers the custom authentication classes with the schema generator.
"""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class ProjectAPIKeyAuthExtension(OpenApiAuthenticationExtension):
    """
    OpenAPI extension for ProjectAPIKeyAuthentication.
    """
    target_class = 'projects.authentication.ProjectAPIKeyAuthentication'
    name = 'ProjectAPIKeyAuth'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'http',
            'scheme': 'bearer',
            'bearerFormat': 'cpf_<prefix>_<secret>',
            'description': 'Project API Key. Format: Bearer cpf_<prefix>_<secret>',
        }


class MCPAPIKeyAuthExtension(OpenApiAuthenticationExtension):
    """
    OpenAPI extension for MCPAPIKeyAuthentication.
    """
    target_class = 'projects.authentication.MCPAPIKeyAuthentication'
    name = 'MCPAPIKeyAuth'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'http',
            'scheme': 'bearer',
            'bearerFormat': 'cpf_<prefix>_<secret>',
            'description': 'MCP-scoped API Key. Format: Bearer cpf_<prefix>_<secret>',
        }


class ChatAPIKeyAuthExtension(OpenApiAuthenticationExtension):
    """
    OpenAPI extension for ChatAPIKeyAuthentication.
    """
    target_class = 'projects.authentication.ChatAPIKeyAuthentication'
    name = 'ChatAPIKeyAuth'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'http',
            'scheme': 'bearer',
            'bearerFormat': 'cpf_<prefix>_<secret>',
            'description': 'Chat-scoped API Key. Format: Bearer cpf_<prefix>_<secret>',
        }
