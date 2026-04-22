import os
from typing import Optional

try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
    else:
        load_dotenv()
except ImportError:
    pass

from mcp.server.fastmcp import FastMCP

from .core.task_store import get_task_store
from .core.task_processor import get_task_processor
from .core.models import SUPPORTED_FORMATS


mcp = FastMCP("markitdown-server")


@mcp.tool()
async def submit_conversion_task(
    content: str = "",
    filename: str = "",
    file_path: str = "",
    options: Optional[dict] = None,
) -> dict:
    options = options or {}
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
    task_store = get_task_store()
    task = task_store.get_task(task_id)
    base = {"task_id": task_id, "created_at": task.created_at.isoformat() if task and task.created_at else None}
    if task is None:
        return {**base, "status": "not_found", "error": f"Task '{task_id}' not found"}
    if task.status.value in ["pending", "processing"]:
        return {**base, "status": task.status.value, "progress": task.progress, "message": task.message, "updated_at": task.updated_at.isoformat() if task.updated_at else None}
    if task.status.value in ["failed", "cancelled"]:
        return {**base, "status": task.status.value, "message": task.message, "updated_at": task.updated_at.isoformat() if task.updated_at else None, "error": task.message if task.status.value == "failed" else "Task was cancelled"}
    if task.status.value == "completed":
        result = task_store.get_result(task_id)
        return {**base, "status": "completed", "result": result if result else "Error: Result not available", "completed_at": task.updated_at.isoformat() if task.updated_at else None}
    return {**base, "status": task.status.value, "error": f"Unknown task status: {task.status.value}"}


@mcp.tool()
async def cancel_task(task_id: str) -> bool:
    task_store = get_task_store()
    processor = get_task_processor()
    processor.cancel_processing(task_id)
    return task_store.cancel_task(task_id)


@mcp.tool()
async def list_tasks(status: str = "", limit: int = 10) -> list[dict]:
    task_store = get_task_store()
    return task_store.list_tasks(status, limit)


@mcp.tool()
async def get_supported_formats() -> list[dict]:
    return [{"extension": f.extension, "mimetype": f.mimetype, "ocr_support": f.ocr_support} for f in SUPPORTED_FORMATS]
