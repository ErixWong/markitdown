import base64
import io
import logging
import os
import time
from datetime import datetime
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .__about__ import __version__
from .core.auth import verify_token_or_passthrough
from .core.models import (
    SUPPORTED_FORMATS,
    CancelTaskResponse,
    HealthResponse,
    QueueStatsResponse,
    SubmitTaskResponse,
    SupportedFormatsResponse,
    TaskListItem,
    TaskListResponse,
    TaskResultResponse,
    TaskStatus,
    TaskStatusResponse,
)
from .core.sse_notifications import get_notification_service
from .core.task_processor import get_task_processor
from .core.task_queue import TaskDispatchStrategyFactory
from .core.task_store import get_task_store

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


class QueuePriorityRequest(BaseModel):
    task_id: str = Field(..., description="Task identifier to promote")


class QueueStrategyRequest(BaseModel):
    strategy: str = Field(..., description="Target strategy: fifo or ratio")
    params: dict = Field(default_factory=dict, description="Strategy parameters")


class QueueRatiosRequest(BaseModel):
    small_ratio: float = Field(..., ge=0.0, le=1.0, description="Small queue ratio")
    large_ratio: float = Field(..., ge=0.0, le=1.0, description="Large queue ratio")


class QueueTaskRequest(BaseModel):
    task_id: str = Field(..., description="Task identifier to remove")


_admin_rate_limit_store: dict = {}


def _check_admin_rate_limit(client_id: str, max_requests: int = 30, window_seconds: int = 60) -> bool:
    import time
    now = time.time()
    if client_id not in _admin_rate_limit_store:
        _admin_rate_limit_store[client_id] = []
    timestamps = _admin_rate_limit_store[client_id]
    _admin_rate_limit_store[client_id] = [t for t in timestamps if now - t < window_seconds]
    timestamps = _admin_rate_limit_store[client_id]
    if len(timestamps) >= max_requests:
        return False
    timestamps.append(now)
    return True


def verify_admin_token(authorization: Optional[str] = Header(default=None), request: Request = None):
    admin_token = os.getenv("MARKITDOWN_ADMIN_TOKEN", "")
    if not admin_token:
        raise HTTPException(status_code=401, detail="Admin authentication not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = authorization[7:]
    import secrets
    if not secrets.compare_digest(token, admin_token):
        raise HTTPException(status_code=401, detail="Invalid admin token")

    client_id = "admin"
    if request and request.client:
        client_id = request.client.host

    if not _check_admin_rate_limit(client_id):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Maximum 30 requests per 60 seconds.")

    return token


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
        enable_ocr: bool = Form(default=False, description="Enable OCR for image extraction"),
        ocr_model: Optional[str] = Form(default=None, description="OCR model name"),
        page_range: Optional[str] = Form(default=None, description="Page range for PDF"),
        silent: bool = Form(default=False, description="Suppress progress notifications"),
        _: Optional[str] = Depends(verify_token_or_passthrough),
    ):
        processor = get_task_processor()
        if processor._dispatch_strategy.is_queue_full():
            raise HTTPException(
                status_code=503,
                detail="Queue is full, please retry later",
                headers={"Retry-After": "5"}
            )
        task_store = get_task_store()
        max_file_size = get_max_file_size()
        content = await file.read()
        if len(content) > max_file_size:
            raise HTTPException(status_code=413, detail=f"File too large: {len(content)} bytes. Maximum allowed: {max_file_size} bytes")
        options = {"enable_ocr": enable_ocr, "ocr_model": ocr_model, "page_range": page_range, "silent": silent}
        task_id = task_store.generate_task_id()
        task = task_store.create_task(task_id, content, file.filename or "unknown", options)
        background_tasks.add_task(processor.start_processing, task_id)
        return SubmitTaskResponse(task_id=task_id, message="Task submitted successfully", created_at=task.created_at)

    @app.post("/tasks/base64", response_model=SubmitTaskResponse)
    async def submit_task_base64(
        background_tasks: BackgroundTasks,
        content: str,
        filename: str,
        enable_ocr: bool = Form(default=False),
        ocr_model: Optional[str] = Form(default=None),
        page_range: Optional[str] = Form(default=None),
        silent: bool = Form(default=False),
        _: Optional[str] = Depends(verify_token_or_passthrough),
    ):
        processor = get_task_processor()
        if processor._dispatch_strategy.is_queue_full():
            raise HTTPException(
                status_code=503,
                detail="Queue is full, please retry later",
                headers={"Retry-After": "5"}
            )
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

    @app.get("/admin/queue/stats", response_model=QueueStatsResponse)
    async def get_queue_stats(_: str = Depends(verify_admin_token)):
        processor = get_task_processor()
        return processor.get_queue_stats()

    @app.post("/admin/queue/priority")
    async def promote_task_priority(
        body: QueuePriorityRequest,
        _: str = Depends(verify_admin_token)
    ):
        processor = get_task_processor()
        result = await processor.promote_task(body.task_id)
        if result.get("success"):
            return JSONResponse(content={
                "task_id": body.task_id,
                "status": "promoted",
                "message": "Task promoted to head of queue",
                "previous_position": result.get("position"),
                "new_position": 1,
            })
        else:
            raise HTTPException(status_code=404, detail=result.get("error", "Task not found"))

    @app.put("/admin/queue/strategy")
    async def switch_strategy(
        body: QueueStrategyRequest,
        _: str = Depends(verify_admin_token)
    ):
        processor = get_task_processor()
        previous_strategy = processor._dispatch_strategy.strategy_name
        try:
            new_strategy = TaskDispatchStrategyFactory.create(body.strategy, **body.params)
            processor.set_dispatch_strategy(new_strategy)
            return JSONResponse(content={
                "previous_strategy": previous_strategy,
                "current_strategy": body.strategy,
                "status": "switched",
                "message": f"Strategy switched from {previous_strategy} to {body.strategy}",
            })
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Strategy switch failed: {str(e)}")

    @app.put("/admin/queue/ratios")
    async def update_ratios(
        body: QueueRatiosRequest,
        _: str = Depends(verify_admin_token)
    ):
        processor = get_task_processor()
        strategy = processor._dispatch_strategy
        if strategy.strategy_name != "ratio":
            raise HTTPException(status_code=400, detail="Ratio adjustment only available for ratio strategy")
        try:
            result = await strategy.set_ratios(body.small_ratio, body.large_ratio)
            if result.get("success"):
                return JSONResponse(content={
                    "previous_ratios": result["previous_ratios"],
                    "current_ratios": result["current_ratios"],
                    "status": "updated",
                    "message": "Ratios updated successfully",
                })
            else:
                raise HTTPException(status_code=400, detail=result.get("error", "Invalid ratios"))
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.delete("/admin/queue/task")
    async def remove_task_from_queue(
        body: QueueTaskRequest,
        _: str = Depends(verify_admin_token)
    ):
        processor = get_task_processor()
        removed = await processor.remove_task_from_queue(body.task_id)
        if removed:
            return JSONResponse(content={
                "task_id": body.task_id,
                "status": "removed",
                "message": "Task removed from queue",
            })
        else:
            raise HTTPException(status_code=404, detail="Task not found in queue")
