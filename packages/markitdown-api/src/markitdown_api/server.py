# SPDX-FileCopyrightText: 2024-present Microsoft Corporation
#
# SPDX-License-Identifier: MIT
"""
FastAPI RESTful API server for MarkItDown.

Provides HTTP endpoints for file conversion to Markdown.
"""

import base64
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile, Query, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer

from .__about__ import __version__
from .models import (
    CancelTaskResponse,
    ErrorResponse,
    HealthResponse,
    SubmitTaskResponse,
    SupportedFormat,
    SupportedFormatsResponse,
    TaskListResponse,
    TaskListItem,
    TaskResultResponse,
    TaskStatus,
    TaskStatusResponse,
)
from .task_store import TaskStore, get_task_store
from .task_processor import TaskProcessor, get_task_processor
from .sse_notifications import get_notification_service
from .auth import verify_token, is_auth_enabled

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Server start time for uptime calculation
_server_start_time: float = 0

# Default max file size: 100MB
DEFAULT_MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB in bytes


def get_max_file_size() -> int:
    """Get max file size from environment variable."""
    env_value = os.getenv("MARKITDOWN_MAX_FILE_SIZE", "100MB")
    
    # Parse size string (e.g., "100MB", "50MB", "1GB")
    if env_value.endswith("GB"):
        return int(env_value[:-2]) * 1024 * 1024 * 1024
    elif env_value.endswith("MB"):
        return int(env_value[:-2]) * 1024 * 1024
    elif env_value.endswith("KB"):
        return int(env_value[:-2]) * 1024
    else:
        # Try to parse as raw bytes
        try:
            return int(env_value)
        except ValueError:
            logger.warning(f"Invalid MARKITDOWN_MAX_FILE_SIZE value: {env_value}, using default 100MB")
            return DEFAULT_MAX_FILE_SIZE


def create_app() -> FastAPI:
    """Create FastAPI application."""
    global _server_start_time
    _server_start_time = time.time()
    
    app = FastAPI(
        title="MarkItDown API",
        description="RESTful API for converting files to Markdown",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    
    # Add CORS middleware from environment config
    cors_origins = os.getenv("MARKITDOWN_CORS_ORIGINS", "*")
    # Parse origins - can be "*" or comma-separated list
    if cors_origins != "*":
        cors_origins = [origin.strip() for origin in cors_origins.split(",")]
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,  # Required for Bearer token authentication
        allow_methods=["*"],     # Allow all HTTP methods
        allow_headers=["*"],     # Allow all headers
    )
    
    # Register routes
    register_routes(app)
    
    return app


def register_routes(app: FastAPI):
    """Register all API routes."""
    
    # =============================================================================
    # Health & Info
    # =============================================================================
    
    @app.get("/", response_model=HealthResponse)
    async def root():
        """Root endpoint - health check."""
        return HealthResponse(
            status="healthy",
            version=__version__,
            uptime=time.time() - _server_start_time
        )
    
    @app.get("/health", response_model=HealthResponse)
    async def health_check():
        """Health check endpoint."""
        return HealthResponse(
            status="healthy",
            version=__version__,
            uptime=time.time() - _server_start_time
        )
    
    # =============================================================================
    # Task Management
    # =============================================================================
    
    @app.post("/tasks", response_model=SubmitTaskResponse)
    async def submit_task(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        enable_ocr: bool = Query(default=False, description="Enable OCR for image extraction"),
        ocr_model: Optional[str] = Query(default=None, description="OCR model name"),
        page_range: Optional[str] = Query(default=None, description="Page range for PDF"),
        silent: bool = Query(default=False, description="Suppress progress notifications"),
        _: Optional[str] = Depends(verify_token),
    ):
        """
        Submit a file conversion task.
        
        Upload a file for conversion to Markdown. The task is processed asynchronously.
        
        **Parameters:**
        - `file`: File to convert (multipart upload)
        - `enable_ocr`: Enable OCR for images in documents
        - `ocr_model`: OCR model name (e.g., 'gpt-4o')
        - `page_range`: Page range for PDF (e.g., '1-5', '1,3,5')
        - `silent`: Suppress progress notifications
        
        **Returns:**
        - `task_id`: Unique task identifier for tracking
        """
        task_store = get_task_store()
        max_file_size = get_max_file_size()
        
        # Read file content
        content = await file.read()
        
        # Validate file size
        if len(content) > max_file_size:
            raise HTTPException(
                status_code=413,
                detail=f"File too large: {len(content)} bytes. Maximum allowed: {max_file_size} bytes ({max_file_size // (1024*1024)}MB)"
            )
        
        # Build options
        options = {
            "enable_ocr": enable_ocr,
            "ocr_model": ocr_model,
            "page_range": page_range,
            "silent": silent,
        }
        
        # Create task
        task_id = task_store.generate_task_id()
        task = task_store.create_task(task_id, content, file.filename or "unknown", options)
        
        # Start processing in background
        processor = get_task_processor()
        background_tasks.add_task(processor.start_processing, task_id)
        
        return SubmitTaskResponse(
            task_id=task_id,
            message="Task submitted successfully",
            created_at=task.created_at
        )
    
    @app.post("/tasks/base64", response_model=SubmitTaskResponse)
    async def submit_task_base64(
        background_tasks: BackgroundTasks,
        content: str,
        filename: str,
        enable_ocr: bool = Query(default=False),
        ocr_model: Optional[str] = Query(default=None),
        page_range: Optional[str] = Query(default=None),
        silent: bool = Query(default=False),
        _: Optional[str] = Depends(verify_token),
    ):
        """
        Submit a file conversion task with Base64 encoded content.
        
        **Parameters:**
        - `content`: Base64 encoded file content
        - `filename`: Original filename (used to infer format)
        - Other options same as multipart upload
        
        **Returns:**
        - `task_id`: Unique task identifier
        """
        task_store = get_task_store()
        max_file_size = get_max_file_size()
        
        # Decode Base64 content
        try:
            file_content = base64.b64decode(content)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid Base64 content: {e}")
        
        # Validate file size
        if len(file_content) > max_file_size:
            raise HTTPException(
                status_code=413,
                detail=f"File too large: {len(file_content)} bytes. Maximum allowed: {max_file_size} bytes ({max_file_size // (1024*1024)}MB)"
            )
        
        # Build options
        options = {
            "enable_ocr": enable_ocr,
            "ocr_model": ocr_model,
            "page_range": page_range,
            "silent": silent,
        }
        
        # Create task
        task_id = task_store.generate_task_id()
        task = task_store.create_task(task_id, file_content, filename, options)
        
        # Start processing
        processor = get_task_processor()
        background_tasks.add_task(processor.start_processing, task_id)
        
        return SubmitTaskResponse(
            task_id=task_id,
            message="Task submitted successfully",
            created_at=task.created_at
        )
    
    @app.get("/tasks/{task_id}", response_model=TaskStatusResponse)
    async def get_task_status(task_id: str, _: Optional[str] = Depends(verify_token)):
        """
        Get task status and progress.
        
        **Parameters:**
        - `task_id`: Task ID to query
        
        **Returns:**
        - Task status information including progress percentage
        """
        task_store = get_task_store()
        status = task_store.get_task_status(task_id)
        
        if status["status"] == "not_found":
            raise HTTPException(status_code=404, detail="Task not found")
        
        return TaskStatusResponse(
            task_id=status["task_id"],
            status=TaskStatus(status["status"]),
            progress=status["progress"],
            message=status["message"],
            created_at=datetime.fromisoformat(status["created_at"]),
            updated_at=datetime.fromisoformat(status["updated_at"]),
        )
    
    @app.get("/tasks/{task_id}/result", response_model=TaskResultResponse)
    async def get_task_result(task_id: str, _: Optional[str] = Depends(verify_token)):
        """
        Get conversion result (Markdown content).
        
        **Parameters:**
        - `task_id`: Task ID to get result for
        
        **Returns:**
        - Markdown content of the conversion result
        
        **Error:**
        - 404 if task not found
        - 400 if task not completed
        """
        task_store = get_task_store()
        task = task_store.get_task(task_id)
        
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        
        if task.status != TaskStatus.COMPLETED:
            raise HTTPException(
                status_code=400,
                detail=f"Task status is '{task.status.value}', not 'completed'"
            )
        
        return TaskResultResponse(
            task_id=task_id,
            status=task.status,
            markdown=task.result,
            error=task.error
        )
    
    @app.delete("/tasks/{task_id}", response_model=CancelTaskResponse)
    async def cancel_task(task_id: str, _: Optional[str] = Depends(verify_token)):
        """
        Cancel a pending or processing task.
        
        **Parameters:**
        - `task_id`: Task ID to cancel
        
        **Returns:**
        - Whether task was cancelled
        """
        task_store = get_task_store()
        processor = get_task_processor()
        
        # Cancel in processor
        processor.cancel_processing(task_id)
        
        # Cancel in store
        cancelled = task_store.cancel_task(task_id)
        
        if not cancelled:
            task = task_store.get_task(task_id)
            if task is None:
                raise HTTPException(status_code=404, detail="Task not found")
            else:
                return CancelTaskResponse(
                    task_id=task_id,
                    cancelled=False,
                    message=f"Task already in status '{task.status.value}'"
                )
        
        return CancelTaskResponse(
            task_id=task_id,
            cancelled=True,
            message="Task cancelled successfully"
        )
    
    @app.get("/tasks", response_model=TaskListResponse)
    async def list_tasks(
        status: Optional[str] = Query(default=None, description="Filter by status"),
        limit: int = Query(default=10, ge=1, le=100, description="Max results"),
        _: Optional[str] = Depends(verify_token),
    ):
        """
        List tasks with optional status filter.
        
        **Parameters:**
        - `status`: Optional status filter (pending/processing/completed/failed/cancelled)
        - `limit`: Maximum number of tasks to return
        
        **Returns:**
        - List of tasks matching filter
        """
        task_store = get_task_store()
        tasks = task_store.list_tasks(status, limit)
        
        return TaskListResponse(
            tasks=[
                TaskListItem(
                    task_id=t["task_id"],
                    filename=t["filename"],
                    status=TaskStatus(t["status"]),
                    progress=t["progress"],
                    created_at=datetime.fromisoformat(t["created_at"]),
                    updated_at=datetime.fromisoformat(t["updated_at"]),
                )
                for t in tasks
            ],
            total=len(tasks)
        )
    
    # =============================================================================
    # SSE Notifications
    # =============================================================================
    
    @app.get("/tasks/{task_id}/events")
    async def task_events(task_id: str, _: Optional[str] = Depends(verify_token)):
        """
        SSE endpoint for real-time task notifications.
        
        Subscribe to Server-Sent Events for task progress updates.
        
        **Parameters:**
        - `task_id`: Task ID to subscribe to
        
        **Returns:**
        - SSE stream with progress events
        """
        notification_service = get_notification_service()
        
        return StreamingResponse(
            notification_service.event_stream(task_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )
    
    @app.get("/tasks/events")
    async def all_task_events(_: Optional[str] = Depends(verify_token)):
        """
        SSE endpoint for all task notifications.
        
        Subscribe to Server-Sent Events for all task updates.
        
        **Returns:**
        - SSE stream with all task events
        """
        notification_service = get_notification_service()
        
        return StreamingResponse(
            notification_service.event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )
    
    # =============================================================================
    # Supported Formats
    # =============================================================================
    
    @app.get("/formats", response_model=SupportedFormatsResponse)
    async def get_supported_formats():
        """
        Get list of supported file formats.
        
        **Returns:**
        - List of supported formats with OCR support information
        """
        return SupportedFormatsResponse(
            formats=[
                SupportedFormat(extension=".pdf", mimetype="application/pdf", ocr_support=True),
                SupportedFormat(extension=".docx", mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document", ocr_support=True),
                SupportedFormat(extension=".xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ocr_support=True),
                SupportedFormat(extension=".pptx", mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation", ocr_support=True),
                SupportedFormat(extension=".html", mimetype="text/html", ocr_support=False),
                SupportedFormat(extension=".epub", mimetype="application/epub+zip", ocr_support=False),
                SupportedFormat(extension=".csv", mimetype="text/csv", ocr_support=False),
                SupportedFormat(extension=".json", mimetype="application/json", ocr_support=False),
                SupportedFormat(extension=".xml", mimetype="application/xml", ocr_support=False),
                SupportedFormat(extension=".zip", mimetype="application/zip", ocr_support=False),
                SupportedFormat(extension=".txt", mimetype="text/plain", ocr_support=False),
                SupportedFormat(extension=".md", mimetype="text/markdown", ocr_support=False),
                SupportedFormat(extension=".ipynb", mimetype="application/x-ipynb+json", ocr_support=False),
                SupportedFormat(extension=".jpg", mimetype="image/jpeg", ocr_support=True),
                SupportedFormat(extension=".png", mimetype="image/png", ocr_support=True),
                SupportedFormat(extension=".gif", mimetype="image/gif", ocr_support=True),
            ]
        )
    
    # =============================================================================
    # Direct Conversion (Synchronous)
    # =============================================================================
    
    @app.post("/convert")
    async def convert_direct(file: UploadFile = File(...), _: Optional[str] = Depends(verify_token)):
        """
        Direct synchronous file conversion.
        
        Convert a file to Markdown immediately (no task tracking).
        
        **Parameters:**
        - `file`: File to convert
        
        **Returns:**
        - Markdown content directly
        
        **Note:** This is a synchronous operation, suitable for small files.
        """
        from markitdown import MarkItDown
        import io
        
        max_file_size = get_max_file_size()
        content = await file.read()
        
        # Validate file size
        if len(content) > max_file_size:
            raise HTTPException(
                status_code=413,
                detail=f"File too large: {len(content)} bytes. Maximum allowed: {max_file_size} bytes ({max_file_size // (1024*1024)}MB)"
            )
        
        md = MarkItDown()
        
        try:
            result = md.convert_stream(io.BytesIO(content))
            return JSONResponse(content={"markdown": result.text_content})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Conversion failed: {e}")


def run_server():
    """Run the API server."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Run MarkItDown RESTful API Server")
    
    parser.add_argument(
        "--host",
        default=None,
        help="Host to bind to (default: from MARKITDOWN_API_HOST env or 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to listen on (default: from MARKITDOWN_API_PORT env or 8000)",
    )
    parser.add_argument(
        "--storage",
        default=None,
        help="Storage directory for tasks (default: ./storage)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )
    
    args = parser.parse_args()
    
    # Set storage directory
    if args.storage:
        os.environ["MARKITDOWN_STORAGE_DIR"] = args.storage
    
    # Get host and port
    host = args.host or os.getenv("MARKITDOWN_API_HOST", "127.0.0.1")
    port = args.port or int(os.getenv("MARKITDOWN_API_PORT", "8000"))
    
    # Security warning for non-localhost
    if host not in ("127.0.0.1", "localhost", "0.0.0.0"):
        auth_status = "ENABLED" if is_auth_enabled() else "DISABLED"
        print(
            "\n"
            f"WARNING: Binding to non-localhost interface.\n"
            f"This exposes the server to other machines.\n"
            f"Authentication: {auth_status}\n"
            "Only proceed if you understand the security implications.\n",
            file=__import__('sys').stderr,
        )
    
    auth_status = "ENABLED" if is_auth_enabled() else "DISABLED"
    print(f"\nMarkItDown API Server starting...")
    print(f"  Host: {host}")
    print(f"  Port: {port}")
    print(f"  Docs: http://{host}:{port}/docs")
    print(f"  Storage: {os.getenv('MARKITDOWN_STORAGE_DIR', './storage')}")
    print(f"  Authentication: {auth_status}")
    if is_auth_enabled():
        print(f"  API Key: Set via MARKITDOWN_API_KEY environment variable")
    print()
    
    # Create and run app
    app = create_app()
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=args.reload,
    )