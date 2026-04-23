import contextlib
import logging
import os
import time
from collections.abc import AsyncIterator
from typing import Optional

import uvicorn
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.types import Receive, Scope, Send

from .__about__ import __version__
from .api import create_app as create_api_app
from .core.auth import AuthMiddleware, is_auth_enabled
from .core.middleware import LargeBodyMiddleware
from .core.sse_notifications import get_notification_service
from .mcp import mcp as mcp_instance

logger = logging.getLogger(__name__)

# Build timestamp - update this when code changes
# Format: YYYY-MM-DD HH:MM:SS
BUILD_TIME = "2026-04-23 11:40:00"


def create_unified_app(
    enable_api: bool = True,
    enable_mcp: bool = True,
) -> Starlette:
    start_time = time.time()

    services = []
    if enable_api:
        services.append("api")
    if enable_mcp:
        services.append("mcp")

    async def root_health(request: Request):
        return JSONResponse({
            "status": "healthy",
            "version": __version__,
            "build_time": BUILD_TIME,
            "uptime": time.time() - start_time,
            "services": services,
        })

    routes: list = [
        Route("/", root_health),
        Route("/health", root_health),
    ]

    if enable_api:
        api_app = create_api_app(enable_cors=False)
        routes.append(Mount("/api", app=api_app))

    session_manager = None

    if enable_mcp:
        mcp_server: Server = mcp_instance._mcp_server
        use_streaming = os.getenv("MARKITDOWN_MCP_STREAMING", "false").lower() == "true"
        mcp_messages_path = "/mcp/messages/"
        sse = SseServerTransport(mcp_messages_path)
        session_manager = StreamableHTTPSessionManager(
            app=mcp_server,
            event_store=None,
            json_response=not use_streaming,
            stateless=True,
        )

        async def handle_mcp_sse(request: Request) -> None:
            async with sse.connect_sse(
                request.scope, request.receive, request._send
            ) as (read_stream, write_stream):
                await mcp_server.run(
                    read_stream, write_stream, mcp_server.create_initialization_options()
                )

        async def handle_streamable_http(
            scope: Scope, receive: Receive, send: Send
        ) -> None:
            method = scope.get("method", "GET")
            if method == "GET" and session_manager.stateless:
                response = Response(
                    content='{"error": "Method Not Allowed: Standalone SSE stream not available in stateless mode."}',
                    status_code=405,
                    headers={"Allow": "POST"},
                )
                await response(scope, receive, send)
                return
            await session_manager.handle_request(scope, receive, send)

        async def handle_mcp_task_events(request: Request):
            task_id = request.query_params.get("task_id")
            notification_service = get_notification_service()
            return StreamingResponse(
                notification_service.event_stream(task_id),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )

        routes.extend([
            Route("/mcp/sse", endpoint=handle_mcp_sse),
            Route("/mcp/tasks/events", endpoint=handle_mcp_task_events),
            Mount("/mcp/messages/", app=sse.handle_post_message),
            Mount("/mcp", app=handle_streamable_http),
        ])

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        if enable_mcp and session_manager:
            async with session_manager.run():
                yield
        else:
            yield

    cors_origins = os.getenv("MARKITDOWN_CORS_ORIGINS", "*")
    if cors_origins != "*":
        cors_origins = [origin.strip() for origin in cors_origins.split(",")]

    return Starlette(
        routes=routes,
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=cors_origins,
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            ),
            Middleware(LargeBodyMiddleware),
            Middleware(AuthMiddleware),
        ],
        lifespan=lifespan,
    )


def run_unified_server(
    host: Optional[str] = None,
    port: Optional[int] = None,
    storage: Optional[str] = None,
    reload: bool = False,
    enable_api: bool = True,
    enable_mcp: bool = True,
):
    if storage:
        os.environ["MARKITDOWN_STORAGE_DIR"] = storage
    host = host or os.getenv("MARKITDOWN_SERVER_HOST", "127.0.0.1")
    port = port or int(os.getenv("MARKITDOWN_SERVER_PORT", "8000"))
    auth_status = "ENABLED" if is_auth_enabled() else "DISABLED"

    active = []
    if enable_api:
        active.append("api")
    if enable_mcp:
        active.append("mcp")

    print(f"\nMarkItDown Server starting...")
    print(f"  Host: {host}")
    print(f"  Port: {port}")
    print(f"  Storage: {os.getenv('MARKITDOWN_STORAGE_DIR', './storage')}")
    print(f"  Authentication: {auth_status}")
    print(f"  Services: {', '.join(active)}")
    print(f"  Endpoints:")
    if enable_api:
        print(f"    API:      http://{host}:{port}/api/")
        print(f"    API Docs: http://{host}:{port}/api/docs")
    if enable_mcp:
        print(f"    MCP SSE:  http://{host}:{port}/mcp/sse")
        print(f"    MCP HTTP: http://{host}:{port}/mcp")
    print()

    app = create_unified_app(enable_api=enable_api, enable_mcp=enable_mcp)
    uvicorn.run(app, host=host, port=port, reload=reload)
