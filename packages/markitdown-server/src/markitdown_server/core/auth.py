import os
import re
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from urllib.parse import urlparse


security = HTTPBearer(
    auto_error=False,
    description="Bearer token authentication. Set MARKITDOWN_API_KEY environment variable to enable."
)


def get_api_key() -> Optional[str]:
    return os.getenv("MARKITDOWN_API_KEY", "").strip()


def is_auth_enabled() -> bool:
    return bool(get_api_key())


def is_strong_token(key: str) -> bool:
    return len(key) >= 32 and bool(re.search(r'[A-Za-z].*\d|\d.*[A-Za-z]', key))


class AuthMiddleware(BaseHTTPMiddleware):
    @staticmethod
    def _is_valid_origin(origin: str, host: str) -> bool:
        if not origin or origin == "null":
            return True
        try:
            origin_parts = urlparse(origin)
            origin_hostname = origin_parts.hostname
            origin_port = origin_parts.port
            if origin_port is None:
                if origin_parts.scheme == "https":
                    origin_port = 443
                elif origin_parts.scheme == "http":
                    origin_port = 80
            host_parts = host.split(":")
            host_hostname = host_parts[0]
            host_port = int(host_parts[1]) if len(host_parts) > 1 else None
            if host_port is None:
                if origin_parts.scheme == "https":
                    host_port = 443
                elif origin_parts.scheme == "http":
                    host_port = 80
            if origin_hostname == host_hostname and origin_port == host_port:
                return True
            if host_hostname in ("localhost", "127.0.0.1"):
                if origin_hostname in ("localhost", "127.0.0.1", None):
                    return True
            return False
        except Exception:
            return False

    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")
        host = request.headers.get("host", "")
        if origin and not self._is_valid_origin(origin, host):
            return Response(
                content='{"detail": "Forbidden: Invalid Origin header. DNS rebinding attack detected."}',
                status_code=403,
            )
        api_key = get_api_key()
        if not api_key:
            return await call_next(request)
        if not is_strong_token(api_key):
            return await call_next(request)
        path = request.url.path
        if path in ("/", "/health") or path.startswith("/api/docs") or path.startswith("/api/redoc") or path.startswith("/api/openapi") or path.startswith("/api/formats") or path.startswith("/api/health"):
            return await call_next(request)
        auth_header = request.headers.get("authorization")
        if not auth_header:
            return Response(
                content='{"detail": "Bearer token required. Authentication is enabled."}',
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return Response(
                content='{"detail": "Invalid authorization header format. Use: Bearer <token>"}',
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = parts[1]
        if not secrets.compare_digest(token, api_key):
            return Response(
                content='{"detail": "Invalid Bearer token"}',
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)


async def verify_token_or_passthrough(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[str]:
    api_key = get_api_key()
    if not api_key:
        return None
    if credentials is None:
        return None
    token = credentials.credentials
    if not secrets.compare_digest(token, api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token