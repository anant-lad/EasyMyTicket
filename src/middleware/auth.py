"""
Auth middleware: accepts Bearer JWT token OR X-API-Key header.
Skips auth for health/docs/auth endpoints.
"""
import json
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

log = logging.getLogger(__name__)

SKIP_PATHS = {
    "/api/health", "/healthz", "/readyz", "/", "/docs", "/redoc", "/openapi.json",
    "/api/auth/login",
}
SKIP_PREFIXES = ("/docs", "/openapi", "/ws/", "/api/agent/installer")


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in SKIP_PATHS or any(path.startswith(p) for p in SKIP_PREFIXES):
            return await call_next(request)

        from src.config import Config
        valid_keys = Config.get_valid_api_keys()

        # --- Try Bearer JWT first ---
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            from src.auth.jwt_handler import decode_token
            payload = decode_token(token)
            if payload:
                return await call_next(request)
            # Invalid JWT — fall through to check API key before rejecting

        # --- Try X-API-Key ---
        api_key = request.headers.get("X-API-Key", "")
        if valid_keys and api_key in valid_keys:
            return await call_next(request)

        # --- No valid keys configured (dev mode) → allow all ---
        if not valid_keys:
            return await call_next(request)

        log.warning("Unauthorized request from %s %s",
                    request.client.host if request.client else "?", path)
        return Response(
            content=json.dumps({"detail": "Authentication required. Provide a Bearer token or X-API-Key."}),
            status_code=401,
            media_type="application/json",
        )
