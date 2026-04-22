import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


DEFAULT_MAX_FILE_SIZE_MB = 100


class LargeBodyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        max_mb = int(os.getenv("MARKITDOWN_MAX_FILE_SIZE_MB", DEFAULT_MAX_FILE_SIZE_MB))
        max_body_size = max_mb * 1024 * 1024
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > max_body_size:
            return Response(
                content=f"Request body too large. Maximum size is {max_body_size} bytes.",
                status_code=413,
            )
        return await call_next(request)
