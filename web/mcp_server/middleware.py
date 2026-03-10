"""
Request logging middleware to debug MCP connections.
"""
import logging

logger = logging.getLogger(__name__)


class RequestDebugMiddleware:
    """Log all incoming requests for debugging MCP connector issues."""
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Log request details
        logger.info(
            f"MCP_DEBUG: {request.method} {request.path} "
            f"Headers: {dict(request.headers)} "
            f"Query: {dict(request.GET)}"
        )
        
        # Get response
        response = self.get_response(request)
        
        # Log response status
        logger.info(
            f"MCP_DEBUG_RESPONSE: {request.path} -> {response.status_code}"
        )
        
        return response
