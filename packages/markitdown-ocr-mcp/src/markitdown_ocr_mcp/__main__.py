"""
MarkItDown OCR MCP Server

Enhanced MCP server with:
- Async task management
- OCR support
- SSE notifications
- Progress tracking
"""

import asyncio
import contextlib
import os
import re
import secrets
import sys
from collections.abc import AsyncIterator
from typing import Optional
from urllib.parse import urlparse

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    # Try to load .env from package directory
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"Loaded .env from: {env_path}")
    else:
        # Also try current working directory
        load_dotenv()
except ImportError:
    print("Warning: python-dotenv not installed, .env file will not be loaded")

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route, Mount
from mcp.server.sse import SseServerTransport
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.types import Receive, Scope, Send
import uvicorn


# Default maximum file size (100MB)
DEFAULT_MAX_FILE_SIZE_MB = 100


def get_max_file_size() -> int:
    """Get maximum file size from environment variable (in bytes)."""
    max_mb = int(os.getenv("MARKITDOWN_MAX_FILE_SIZE_MB", DEFAULT_MAX_FILE_SIZE_MB))
    return max_mb * 1024 * 1024


# Maximum request body size (read from env)
MAX_BODY_SIZE = get_max_file_size()


class LargeBodyMiddleware(BaseHTTPMiddleware):
    """Middleware to allow large request bodies."""
    
    async def dispatch(self, request: Request, call_next):
        # Check content-length header if present
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_BODY_SIZE:
            return Response(
                content=f"Request body too large. Maximum size is {MAX_BODY_SIZE} bytes.",
                status_code=413,
            )
        return await call_next(request)


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware to verify Bearer token and Origin header for HTTP endpoints."""
    
    @staticmethod
    def _is_strong_token(key: str) -> bool:
        """Check if API key meets minimum security requirements."""
        # Minimum 32 characters with mixed alphanumeric
        return len(key) >= 32 and bool(re.search(r'[A-Za-z].*\d|\d.*[A-Za-z]', key))
    
    @staticmethod
    def _is_valid_origin(origin: str, host: str) -> bool:
        """
        Validate Origin header to prevent DNS rebinding attacks.
        
        Per MCP 2025-11-25 spec:
        Servers MUST validate the Origin header on all incoming connections.
        If the Origin header is present and invalid, servers MUST respond with HTTP 403.
        
        Valid origins:
        - Same origin (matches Host header)
        - localhost / 127.0.0.1 when server is localhost
        - null origin (for local file:// origins)
        """
        if not origin or origin == "null":
            return True
        
        try:
            origin_parts = urlparse(origin)
            origin_hostname = origin_parts.hostname
            origin_port = origin_parts.port
            
            # Fill default port for origin if not explicitly specified
            if origin_port is None:
                if origin_parts.scheme == "https":
                    origin_port = 443
                elif origin_parts.scheme == "http":
                    origin_port = 80
            
            # Parse Host header
            host_parts = host.split(":")
            host_hostname = host_parts[0]
            host_port = int(host_parts[1]) if len(host_parts) > 1 else None
            
            # Fill default port for host if not explicitly specified
            if host_port is None:
                if origin_parts.scheme == "https":
                    host_port = 443
                elif origin_parts.scheme == "http":
                    host_port = 80
            
            # Check if same origin (hostname + port match)
            if origin_hostname == host_hostname and origin_port == host_port:
                return True
            
            # Allow localhost origins when server is localhost
            if host_hostname in ("localhost", "127.0.0.1"):
                if origin_hostname in ("localhost", "127.0.0.1", None):
                    return True
            
            return False
        except Exception:
            return False
    
    async def dispatch(self, request: Request, call_next):
        # Per MCP 2025-11-25 spec: Validate Origin header to prevent DNS rebinding attacks
        origin = request.headers.get("origin")
        host = request.headers.get("host", "")
        
        if origin and not self._is_valid_origin(origin, host):
            return Response(
                content='{"detail": "Forbidden: Invalid Origin header. DNS rebinding attack detected."}',
                status_code=403,
            )
        
        api_key = os.getenv("MARKITDOWN_API_KEY", "").strip()
        
        # If no API key configured or empty string, skip authentication
        if not api_key:
            return await call_next(request)
        
        # Validate token strength (weak tokens are rejected)
        if not self._is_strong_token(api_key):
            logger = getattr(call_next.__self__, 'logger', None)
            if logger:
                logger.error("MARKITDOWN_API_KEY too weak (< 32 chars or no mixed alphanumeric). Authentication disabled.")
            return await call_next(request)
        
        # Check if this is a health check endpoint (allow without auth)
        if request.url.path in ["/", "/health"]:
            return await call_next(request)
        
        # Verify Bearer token
        auth_header = request.headers.get("authorization")
        if not auth_header:
            return Response(
                content='{"detail": "Bearer token required. Authentication is enabled."}',
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Parse Bearer token
        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return Response(
                content='{"detail": "Invalid authorization header format. Use: Bearer <token>"}',
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        token = parts[1]
        # Timing-safe comparison to prevent timing attacks
        if not secrets.compare_digest(token, api_key):
            return Response(
                content='{"detail": "Invalid Bearer token"}',
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        return await call_next(request)

from ._task_store import TaskStore
from ._task_processor import TaskProcessor
from ._sse_notifications import get_notification_service


# Initialize FastMCP server
mcp = FastMCP("markitdown-ocr-mcp")

# Global instances
_task_store: Optional[TaskStore] = None
_task_processor: Optional[TaskProcessor] = None


def get_task_store() -> TaskStore:
    """Get or create global TaskStore instance."""
    global _task_store
    if _task_store is None:
        storage_dir = os.getenv("MARKITDOWN_STORAGE_DIR", "./storage")
        _task_store = TaskStore(storage_dir)
    return _task_store


def get_task_processor() -> TaskProcessor:
    """Get or create global TaskProcessor instance."""
    global _task_processor
    if _task_processor is None:
        notification_service = get_notification_service()
        task_store = get_task_store()
        
        async def progress_callback(task_id: str, progress: int, message: str):
            """Async callback to send SSE notifications on progress.
            
            This is called from async context in process_task, so we can
            directly await the notification methods.
            
            Supports silent mode: if task options have silent=true,
            only completion/failure notifications are sent.
            """
            # Check if silent mode is enabled for this task
            task = task_store.get_task(task_id)
            silent = task.options.get("silent", False) if task else False
            
            if not silent:
                # Send progress notification
                await notification_service.notify_progress(task_id, progress, message)
            
            # Always send completion/failure notifications
            if progress == 100:
                await notification_service.notify_completed(task_id)
            elif progress < 0:
                await notification_service.notify_failed(task_id, message)
        
        _task_processor = TaskProcessor(
            task_store=task_store,
            enable_ocr=os.getenv("MARKITDOWN_OCR_ENABLED", "false").lower() == "true",
            progress_callback=progress_callback,
        )
    return _task_processor


# =============================================================================
# MCP Tools
# =============================================================================

@mcp.tool()
async def submit_conversion_task(
    content: str = "",
    filename: str = "",
    file_path: str = "",
    options: dict = {}
) -> dict:
    """
    Submit a file conversion task.
    
    Args:
        content: Base64 encoded file content (for small files < 4MB)
        filename: Original filename (used to infer format)
        file_path: Local file path on server (for large files, bypasses HTTP size limit)
        options: Optional configuration:
            - enable_ocr: Whether to enable OCR (default: false)
            - page_range: Page range for PDF processing (e.g., "1-5", "1,3,5-10", "" for all pages)
            - silent: Silent mode - only notify on completion/failure, no progress updates (default: false)
            - ocr_prompt: Custom OCR prompt
            - ocr_model: OCR model name
    
    Returns:
        Dictionary containing:
        - task_id: Unique task identifier for tracking
        - status: "submitted"
    
    Note:
        For files larger than 4MB, use file_path parameter instead of content.
        The file_path should be a valid path on the server's filesystem.
        
        When enable_ocr is true for PDF files, the document is processed page-by-page.
        Use get_task to poll progress and retrieve results.
        
        Set silent=true to avoid progress notifications - useful when LLM doesn't want
        to be disturbed by progress updates. Only completion/failure events will be sent.
    """
    task_store = get_task_store()
    
    if file_path:
        if not os.path.exists(file_path):
            return {"task_id": "", "status": "error", "error": f"File not found: {file_path}"}
        
        with open(file_path, 'rb') as f:
            file_content = f.read()
        
        if not filename:
            filename = os.path.basename(file_path)
        
        task_id = task_store.generate_task_id()
        task_store.create_task(task_id, file_content, filename, options)
    else:
        if not content:
            return {"task_id": "", "status": "error", "error": "Either content or file_path must be provided"}
        task_id = task_store.create_task_from_base64(content, filename, options)
    
    processor = get_task_processor()
    processor.start_processing(task_id)
    
    return {"task_id": task_id, "status": "submitted"}


@mcp.tool()
async def get_task(task_id: str) -> dict:
    """
    Get task status and result.
    
    Unified tool for querying task information. Returns different content based on task state:
    - If processing: returns progress information
    - If completed: returns the conversion result (Markdown content)
    - If failed: returns error information
    
    Args:
        task_id: Task ID to query
    
    Returns:
        Dictionary containing:
        - task_id: Task identifier
        - status: Task status (pending/processing/completed/failed/cancelled/not_found)
        - For processing status: progress (0-100), message, created_at, updated_at
        - For completed status: result (Markdown content), created_at, completed_at
        - For failed/cancelled status: error message, created_at, updated_at
    
    Note:
        In Streamable HTTP mode (SSE), clients can receive real-time progress 
        notifications without polling. In JSON response mode, use this tool 
        to poll for progress and results.
    """
    task_store = get_task_store()
    task = task_store.get_task(task_id)
    
    base = {
        "task_id": task_id,
        "created_at": task.created_at.isoformat() if task and task.created_at else None,
    }
    
    if task is None:
        return {**base, "status": "not_found", "error": f"Task '{task_id}' not found"}
    
    if task.status in ["pending", "processing"]:
        return {
            **base,
            "status": task.status,
            "progress": task.progress,
            "message": task.message,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        }
    
    if task.status in ["failed", "cancelled"]:
        return {
            **base,
            "status": task.status,
            "message": task.message,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
            "error": task.message if task.status == "failed" else "Task was cancelled",
        }
    
    if task.status == "completed":
        result = task_store.get_result(task_id)
        return {
            **base,
            "status": "completed",
            "result": result if result else "Error: Result not available",
            "completed_at": task.updated_at.isoformat() if task.updated_at else None,
        }
    
    return {**base, "status": task.status, "error": f"Unknown task status: {task.status}"}


@mcp.tool()
async def cancel_task(task_id: str) -> bool:
    """
    Cancel a pending or processing task.
    
    Args:
        task_id: Task ID to cancel
    
    Returns:
        True if task was cancelled, False if task was already completed or not found
    """
    task_store = get_task_store()
    processor = get_task_processor()
    
    # Cancel in processor if running
    processor.cancel_processing(task_id)
    
    # Cancel in store
    return task_store.cancel_task(task_id)


@mcp.tool()
async def list_tasks(
    status: str = "",
    limit: int = 10
) -> list[dict]:
    """
    List tasks with optional status filter.
    
    Args:
        status: Optional status filter (pending/processing/completed/failed/cancelled)
        limit: Maximum number of tasks to return (default: 10)
    
    Returns:
        List of task information dictionaries
    """
    task_store = get_task_store()
    return task_store.list_tasks(status, limit)


@mcp.tool()
async def get_supported_formats() -> list[dict]:
    """
    Get list of supported file formats.
    
    Returns:
        List of supported format information:
            - extension: File extension
            - mimetype: MIME type
            - ocr_support: Whether OCR is supported
    """
    return [
        {"extension": ".pdf", "mimetype": "application/pdf", "ocr_support": True},
        {"extension": ".docx", "mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "ocr_support": True},
        {"extension": ".xlsx", "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "ocr_support": True},
        {"extension": ".pptx", "mimetype": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "ocr_support": True},
        {"extension": ".html", "mimetype": "text/html", "ocr_support": False},
        {"extension": ".epub", "mimetype": "application/epub+zip", "ocr_support": False},
        {"extension": ".csv", "mimetype": "text/csv", "ocr_support": False},
        {"extension": ".json", "mimetype": "application/json", "ocr_support": False},
        {"extension": ".xml", "mimetype": "application/xml", "ocr_support": False},
        {"extension": ".zip", "mimetype": "application/zip", "ocr_support": False},
        {"extension": ".txt", "mimetype": "text/plain", "ocr_support": False},
        {"extension": ".md", "mimetype": "text/markdown", "ocr_support": False},
        {"extension": ".ipynb", "mimetype": "application/x-ipynb+json", "ocr_support": False},
        {"extension": ".jpg", "mimetype": "image/jpeg", "ocr_support": True},
        {"extension": ".png", "mimetype": "image/png", "ocr_support": True},
        {"extension": ".gif", "mimetype": "image/gif", "ocr_support": True},
    ]


# =============================================================================
# HTTP/SSE Server
# =============================================================================

def create_starlette_app(mcp_server: Server, *, debug: bool = False) -> Starlette:
    """
    Create Starlette application with HTTP and SSE support.
    
    Supports two MCP transport modes (configurable via MARKITDOWN_MCP_STREAMING env):
    - JSON Response Mode (default): Simple request/response, use get_task tool to poll progress
    - SSE Stream Mode: Real-time progress notifications in MCP SSE stream
    """
    # Check if SSE streaming mode is enabled (for real-time progress in MCP stream)
    # If True: Use SSE streams for MCP communication (real-time progress notifications)
    # If False (default): Use simple JSON responses (poll via get_task tool)
    use_streaming = os.getenv("MARKITDOWN_MCP_STREAMING", "false").lower() == "true"
    
    sse = SseServerTransport("/messages/")
    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        event_store=None,
        json_response=not use_streaming,  # JSON mode when not streaming
        stateless=True,
    )
    
    async def handle_sse(request: Request) -> None:
        """Handle legacy SSE connections for MCP (deprecated HTTP+SSE transport)."""
        async with sse.connect_sse(
            request.scope,
            request.receive,
            request._send,
        ) as (read_stream, write_stream):
            await mcp_server.run(
                read_stream,
                write_stream,
                mcp_server.create_initialization_options(),
            )
    
    async def handle_streamable_http(
        scope: Scope, receive: Receive, send: Send
    ) -> None:
        """
        Handle Streamable HTTP requests.
        
        Per MCP 2025-11-25 spec:
        - POST: Handle JSON-RPC messages
        - GET: In stateless mode, return 405 Method Not Allowed (no standalone SSE stream)
        - DELETE: Return 405 (session termination not supported in stateless mode)
        
        Mode behavior:
        - JSON mode (default): Simple request/response, clients poll get_task for progress
        - SSE mode: Real-time progress notifications in MCP stream (set MARKITDOWN_MCP_STREAMING=true)
        """
        method = scope.get("method", "GET")
        
        # In stateless mode, GET requests should return 405
        # Per spec: "The server MUST either return Content-Type: text/event-stream ...
        # or else return HTTP 405 Method Not Allowed, indicating that the server does
        # not offer an SSE stream at this endpoint."
        if method == "GET" and session_manager.stateless:
            response = Response(
                content='{"error": "Method Not Allowed: Standalone SSE stream not available in stateless mode. Use POST for MCP requests."}',
                status_code=405,
                headers={"Allow": "POST"},
            )
            await response(scope, receive, send)
            return
        
        await session_manager.handle_request(scope, receive, send)
    
    async def handle_task_events(request: Request) -> StreamingResponse:
        """
        Handle SSE endpoint for task notifications (custom extension, not part of MCP protocol).
        
        This endpoint provides real-time task progress updates via SSE for clients that
        need streaming updates but are using JSON response mode for MCP.
        
        In Streamable HTTP mode (MARKITDOWN_MCP_STREAMING=true), progress notifications
        are sent directly in the MCP SSE stream instead of through this endpoint.
        """
        task_id = request.query_params.get("task_id")
        notification_service = get_notification_service()
        
        return StreamingResponse(
            notification_service.event_stream(task_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )
    
    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        """Context manager for session manager."""
        async with session_manager.run():
            print("MarkItDown OCR MCP Server started!")
            try:
                yield
            finally:
                print("Server shutting down...")
    
    return Starlette(
        debug=debug,
        routes=[
            Route("/sse", endpoint=handle_sse),
            Route("/tasks/events", endpoint=handle_task_events),
            Mount("/mcp", app=handle_streamable_http),
            Mount("/messages/", app=sse.handle_post_message),
        ],
        lifespan=lifespan,
        middleware=[
            Middleware(LargeBodyMiddleware),
            Middleware(AuthMiddleware),
        ],
    )


def main():
    """Main entry point."""
    import argparse
    
    mcp_server = mcp._mcp_server
    
    parser = argparse.ArgumentParser(description="Run MarkItDown OCR MCP Server")
    
    parser.add_argument(
        "--http",
        action="store_true",
        help="Run with Streamable HTTP and SSE transport (default: STDIO)",
    )
    parser.add_argument(
        "--sse",
        action="store_true",
        help="(Deprecated) Alias for --http",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Host to bind to (default: from MARKITDOWN_MCP_HOST env or 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to listen on (default: from MARKITDOWN_MCP_PORT env or 3001)",
    )
    parser.add_argument(
        "--storage",
        default=None,
        help="Storage directory for tasks (default: ./storage)",
    )
    
    args = parser.parse_args()
    
    # Set storage directory
    if args.storage:
        os.environ["MARKITDOWN_STORAGE_DIR"] = args.storage
    
    use_http = args.http or args.sse
    
    if not use_http and (args.host or args.port):
        parser.error(
            "Host and port arguments are only valid with --http mode."
        )
        sys.exit(1)
    
    if use_http:
        # Read host from args or env or default
        host = args.host if args.host else os.getenv("MARKITDOWN_MCP_HOST", "127.0.0.1")
        
        # Check if authentication is enabled
        api_key = os.getenv("MARKITDOWN_API_KEY", "").strip()
        auth_enabled = bool(api_key)
        
        if args.host and args.host not in ("127.0.0.1", "localhost"):
            if auth_enabled:
                print(
                    "\n"
                    "WARNING: Binding to non-localhost interface.\n"
                    "Authentication is ENABLED via MARKITDOWN_API_KEY.\n"
                    "All HTTP endpoints require a valid Bearer token.\n"
                    "Only proceed if you understand the security implications.\n",
                    file=sys.stderr,
                )
            else:
                print(
                    "\n"
                    "WARNING: Binding to non-localhost interface.\n"
                    "This exposes the server to other machines.\n"
                    "The server has NO authentication.\n"
                    "Consider setting MARKITDOWN_API_KEY to enable Bearer token auth.\n"
                    "Only proceed if you understand the security implications.\n",
                    file=sys.stderr,
                )
        
        starlette_app = create_starlette_app(mcp_server, debug=True)
        # Read port from args or env or default
        port = args.port if args.port else int(os.getenv("MARKITDOWN_MCP_PORT", "3001"))
        # Use uvicorn Config to set larger request body size (100MB)
        config = uvicorn.Config(
            starlette_app,
            host=host,
            port=port,
            limit_max_requests=100 * 1024 * 1024,  # 100MB - this controls request body size
        )
        server = uvicorn.Server(config)
        server.run()
    else:
        # STDIO mode
        mcp.run()


if __name__ == "__main__":
    main()