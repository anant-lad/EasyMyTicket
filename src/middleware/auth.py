"""
API key authentication middleware.
Reads X-API-Key header; skips auth for health/docs endpoints.
"""
import json
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

log = logging.getLogger(__name__)

SKIP_PATHS = {"/api/health", "/healthz", "/readyz", "/", "/docs", "/redoc", "/openapi.json"}


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in SKIP_PATHS or request.url.path.startswith("/docs"):
            return await call_next(request)

        from src.config import Config
        valid_keys = Config.get_valid_api_keys()

        # If no keys configured (dev mode), allow all requests
        if not valid_keys:
            return await call_next(request)

        api_key = request.headers.get("X-API-Key", "")
        if not api_key or api_key not in valid_keys:
            log.warning("Rejected request with invalid API key from %s %s",
                        request.client.host if request.client else "?",
                        request.url.path)
            return Response(
                content=json.dumps({"detail": "Invalid or missing API key"}),
                status_code=401,
                media_type="application/json",
            )

        return await call_next(request)
