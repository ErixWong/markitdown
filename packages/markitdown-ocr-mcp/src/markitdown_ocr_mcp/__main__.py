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
import sys
from collections.abc import AsyncIterator
from typing import Optional

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import StreamingResponse
from starlette.routing import Route, Mount
from mcp.server.sse import SseServerTransport
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.types import Receive, Scope, Send
import uvicorn

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
        
        def progress_callback(task_id: str, progress: int, message: str):
            """Callback to send SSE notifications on progress.
            
            Uses asyncio.ensure_future which is safe to call from 
            synchronous context when event loop is running.
            """
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(
                        notification_service.notify_progress(task_id, progress, message)
                    )
                )
                if progress == 100:
                    loop.call_soon_threadsafe(
                        lambda: asyncio.ensure_future(
                            notification_service.notify_completed(task_id)
                        )
                    )
                elif progress < 0:
                    loop.call_soon_threadsafe(
                        lambda: asyncio.ensure_future(
                            notification_service.notify_failed(task_id, message)
                        )
                    )
            except RuntimeError:
                # No running event loop, skip notification
                pass
        
        _task_processor = TaskProcessor(
            task_store=get_task_store(),
            enable_ocr=os.getenv("MARKITDOWN_OCR_ENABLED", "false").lower() == "true",
            progress_callback=progress_callback,
        )
    return _task_processor


# =============================================================================
# MCP Tools
# =============================================================================

@mcp.tool()
async def submit_conversion_task(
    content: str,
    filename: str,
    options: dict = {}
) -> str:
    """
    Submit a file conversion task.
    
    Args:
        content: Base64 encoded file content
        filename: Original filename (used to infer format)
        options: Optional configuration:
            - enable_ocr: Whether to enable OCR (default: false)
            - ocr_prompt: Custom OCR prompt
            - ocr_model: OCR model name
    
    Returns:
        task_id: Unique task identifier for tracking
    """
    task_store = get_task_store()
    task_id = task_store.create_task_from_base64(content, filename, options)
    
    # Start processing in background
    processor = get_task_processor()
    processor.start_processing(task_id)
    
    return task_id


@mcp.tool()
async def get_task_status(task_id: str) -> dict:
    """
    Get task status and progress.
    
    Args:
        task_id: Task ID to query
    
    Returns:
        Task status information:
            - task_id: Task identifier
            - status: pending/processing/completed/failed/cancelled
            - progress: 0-100
            - message: Progress message
            - created_at: Creation timestamp
            - updated_at: Last update timestamp
    """
    task_store = get_task_store()
    return task_store.get_task_status(task_id)


@mcp.tool()
async def get_task_result(task_id: str) -> str:
    """
    Get conversion result (Markdown content).
    
    Args:
        task_id: Task ID to get result for
    
    Returns:
        Markdown content of the conversion result
        
    Error:
        Returns error message if task is not completed or not found
    """
    task_store = get_task_store()
    result = task_store.get_result(task_id)
    
    if result is None:
        task = task_store.get_task(task_id)
        if task is None:
            return "Error: Task not found"
        elif task.status != "completed":
            return f"Error: Task status is '{task.status}', not 'completed'"
        else:
            return "Error: Result not available"
    
    return result


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
    """Create Starlette application with HTTP and SSE support."""
    sse = SseServerTransport("/messages/")
    session_manager = StreamableHTTPSessionManager(
        app=mcp_server,
        event_store=None,
        json_response=True,
        stateless=True,
    )
    
    async def handle_sse(request: Request) -> None:
        """Handle SSE connections for MCP."""
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
        """Handle Streamable HTTP requests."""
        await session_manager.handle_request(scope, receive, send)
    
    async def handle_task_events(request: Request) -> StreamingResponse:
        """Handle SSE endpoint for task notifications."""
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
        help="Host to bind to (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to listen on (default: 3001)",
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
        host = args.host if args.host else "127.0.0.1"
        
        if args.host and args.host not in ("127.0.0.1", "localhost"):
            print(
                "\n"
                "WARNING: Binding to non-localhost interface.\n"
                "This exposes the server to other machines.\n"
                "The server has NO authentication.\n"
                "Only proceed if you understand the security implications.\n",
                file=sys.stderr,
            )
        
        starlette_app = create_starlette_app(mcp_server, debug=True)
        port = args.port if args.port else 3001
        uvicorn.run(starlette_app, host=host, port=port)
    else:
        # STDIO mode
        mcp.run()


if __name__ == "__main__":
    main()