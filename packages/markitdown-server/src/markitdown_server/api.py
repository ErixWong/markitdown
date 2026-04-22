import base64
import io
import logging
import os
import time
from datetime import datetime

from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile, Query, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse, JSONResponse

from .__about__ import __version__
from .core.models import (
    CancelTaskResponse,
    HealthResponse,
    SubmitTaskResponse,
    SupportedFormatsResponse,
    TaskListResponse,
    TaskListItem,
    TaskResultResponse,
    TaskStatus,
    TaskStatusResponse,
    SUPPORTED_FORMATS,
)
from .core.task_store import get_task_store
from .core.task_processor import get_task_processor
from .core.sse_notifications import get_notification_service
from .core.auth import verify_token_or_passthrough

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_MAX_FILE_SIZE = 100 * 1024 * 1024


def get_max_file_size() -> int:
    env_value = os.getenv("MARKITDOWN_MAX_FILE_SIZE", "100MB")
    if env_value.endswith("GB"):
        return int(env_value[:-2]) * 1024 * 1024 * 1024
    elif env_value.endswith("MB"):
        return int(env_value[:-2]) * 1024 * 1024
    elif env_value.endswith("KB"):
        return int(env_value[:-2]) * 1024
    else:
        try:
            return int(env_value)
        except ValueError:
            logger.warning(f"Invalid MARKITDOWN_MAX_FILE_SIZE value: {env_value}, using default 100MB")
            return DEFAULT_MAX_FILE_SIZE


def create_app(enable_cors: bool = True) -> FastAPI:
    app = FastAPI(
        title="MarkItDown Server",
        description="RESTful API for converting files to Markdown",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    if enable_cors:
        from fastapi.middleware.cors import CORSMiddleware
        cors_origins = os.getenv("MARKITDOWN_CORS_ORIGINS", "*")
        if cors_origins != "*":
            cors_origins = [origin.strip() for origin in cors_origins.split(",")]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    start_time = time.time()
    register_routes(app, start_time)
    return app


def register_routes(app: FastAPI, start_time: float):
    @app.get("/", response_model=HealthResponse)
    async def root():
        return HealthResponse(status="healthy", version=__version__, uptime=time.time() - start_time)

    @app.get("/health", response_model=HealthResponse)
    async def health_check():
        return HealthResponse(status="healthy", version=__version__, uptime=time.time() - start_time)

    @app.post("/tasks", response_model=SubmitTaskResponse)
    async def submit_task(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(...),
        enable_ocr: bool = Query(default=False, description="Enable OCR for image extraction"),
        ocr_model: Optional[str] = Query(default=None, description="OCR model name"),
        page_range: Optional[str] = Query(default=None, description="Page range for PDF"),
        silent: bool = Query(default=False, description="Suppress progress notifications"),
        _: Optional[str] = Depends(verify_token_or_passthrough),
    ):
        task_store = get_task_store()
        max_file_size = get_max_file_size()
        content = await file.read()
        if len(content) > max_file_size:
            raise HTTPException(status_code=413, detail=f"File too large: {len(content)} bytes. Maximum allowed: {max_file_size} bytes")
        options = {"enable_ocr": enable_ocr, "ocr_model": ocr_model, "page_range": page_range, "silent": silent}
        task_id = task_store.generate_task_id()
        task = task_store.create_task(task_id, content, file.filename or "unknown", options)
        processor = get_task_processor()
        background_tasks.add_task(processor.start_processing, task_id)
        return SubmitTaskResponse(task_id=task_id, message="Task submitted successfully", created_at=task.created_at)

    @app.post("/tasks/base64", response_model=SubmitTaskResponse)
    async def submit_task_base64(
        background_tasks: BackgroundTasks,
        content: str,
        filename: str,
        enable_ocr: bool = Query(default=False),
        ocr_model: Optional[str] = Query(default=None),
        page_range: Optional[str] = Query(default=None),
        silent: bool = Query(default=False),
        _: Optional[str] = Depends(verify_token_or_passthrough),
    ):
        task_store = get_task_store()
        max_file_size = get_max_file_size()
        try:
            file_content = base64.b64decode(content)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid Base64 content: {e}")
        if len(file_content) > max_file_size:
            raise HTTPException(status_code=413, detail=f"File too large: {len(file_content)} bytes. Maximum allowed: {max_file_size} bytes")
        options = {"enable_ocr": enable_ocr, "ocr_model": ocr_model, "page_range": page_range, "silent": silent}
        task_id = task_store.generate_task_id()
        task = task_store.create_task(task_id, file_content, filename, options)
        processor = get_task_processor()
        background_tasks.add_task(processor.start_processing, task_id)
        return SubmitTaskResponse(task_id=task_id, message="Task submitted successfully", created_at=task.created_at)

    @app.get("/tasks/{task_id}", response_model=TaskStatusResponse)
    async def get_task_status(task_id: str, _: Optional[str] = Depends(verify_token_or_passthrough)):
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
    async def get_task_result(task_id: str, _: Optional[str] = Depends(verify_token_or_passthrough)):
        task_store = get_task_store()
        task = task_store.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.status != TaskStatus.COMPLETED:
            raise HTTPException(status_code=400, detail=f"Task status is '{task.status.value}', not 'completed'")
        return TaskResultResponse(task_id=task_id, status=task.status, markdown=task.result, error=task.error)

    @app.delete("/tasks/{task_id}", response_model=CancelTaskResponse)
    async def cancel_task(task_id: str, _: Optional[str] = Depends(verify_token_or_passthrough)):
        task_store = get_task_store()
        processor = get_task_processor()
        processor.cancel_processing(task_id)
        cancelled = task_store.cancel_task(task_id)
        if not cancelled:
            task = task_store.get_task(task_id)
            if task is None:
                raise HTTPException(status_code=404, detail="Task not found")
            else:
                return CancelTaskResponse(task_id=task_id, cancelled=False, message=f"Task already in status '{task.status.value}'")
        return CancelTaskResponse(task_id=task_id, cancelled=True, message="Task cancelled successfully")

    @app.get("/tasks", response_model=TaskListResponse)
    async def list_tasks(
        status: str = Query(default=None, description="Filter by status"),
        limit: int = Query(default=10, ge=1, le=100, description="Max results"),
        _: Optional[str] = Depends(verify_token_or_passthrough),
    ):
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

    @app.get("/tasks/{task_id}/events")
    async def task_events(task_id: str, _: Optional[str] = Depends(verify_token_or_passthrough)):
        notification_service = get_notification_service()
        return StreamingResponse(
            notification_service.event_stream(task_id),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    @app.get("/tasks/events")
    async def all_task_events(_: Optional[str] = Depends(verify_token_or_passthrough)):
        notification_service = get_notification_service()
        return StreamingResponse(
            notification_service.event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    @app.get("/formats", response_model=SupportedFormatsResponse)
    async def get_supported_formats():
        return SupportedFormatsResponse(formats=SUPPORTED_FORMATS)

    @app.post("/convert")
    async def convert_direct(file: UploadFile = File(...), _: Optional[str] = Depends(verify_token_or_passthrough)):
        from markitdown import MarkItDown
        max_file_size = get_max_file_size()
        content = await file.read()
        if len(content) > max_file_size:
            raise HTTPException(status_code=413, detail=f"File too large: {len(content)} bytes. Maximum allowed: {max_file_size} bytes")
        md = MarkItDown()
        try:
            result = md.convert_stream(io.BytesIO(content))
            return JSONResponse(content={"markdown": result.text_content})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Conversion failed: {e}")
