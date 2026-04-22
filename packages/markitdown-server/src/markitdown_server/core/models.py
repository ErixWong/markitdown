from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ConversionOptions(BaseModel):
    enable_ocr: bool = Field(default=False, description="Enable OCR for image extraction")
    ocr_model: Optional[str] = Field(default=None, description="OCR model name (e.g., gpt-4o)")
    ocr_prompt: Optional[str] = Field(default=None, description="Custom OCR prompt")
    page_range: Optional[str] = Field(default=None, description="Page range for PDF (e.g., '1-5', '1,3,5')")
    silent: bool = Field(default=False, description="Suppress progress notifications")


class SubmitTaskRequest(BaseModel):
    filename: str = Field(..., description="Original filename (used to infer format)")
    options: ConversionOptions = Field(default_factory=ConversionOptions, description="Conversion options")


class SubmitTaskResponse(BaseModel):
    task_id: str = Field(..., description="Unique task identifier")
    message: str = Field(default="Task submitted successfully", description="Status message")
    created_at: datetime = Field(..., description="Task creation timestamp")


class TaskStatusResponse(BaseModel):
    task_id: str = Field(..., description="Task identifier")
    status: TaskStatus = Field(..., description="Current task status")
    progress: int = Field(..., ge=-1, le=100, description="Progress percentage (0-100, -1 for failed/cancelled)")
    message: str = Field(..., description="Human-readable status message")
    created_at: datetime = Field(..., description="Task creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class TaskResultResponse(BaseModel):
    task_id: str = Field(..., description="Task identifier")
    status: TaskStatus = Field(..., description="Task status")
    markdown: Optional[str] = Field(default=None, description="Markdown content")
    error: Optional[str] = Field(default=None, description="Error message if failed")


class TaskListItem(BaseModel):
    task_id: str
    filename: str
    status: TaskStatus
    progress: int
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    tasks: list[TaskListItem] = Field(default_factory=list, description="List of tasks")
    total: int = Field(..., description="Total number of tasks matching filter")


class CancelTaskResponse(BaseModel):
    task_id: str = Field(..., description="Task identifier")
    cancelled: bool = Field(..., description="Whether task was cancelled")
    message: str = Field(..., description="Status message")


class SupportedFormat(BaseModel):
    extension: str = Field(..., description="File extension (e.g., '.pdf')")
    mimetype: str = Field(..., description="MIME type")
    ocr_support: bool = Field(default=False, description="Whether OCR is supported")


class SupportedFormatsResponse(BaseModel):
    formats: list[SupportedFormat] = Field(default_factory=list, description="List of supported formats")


class ErrorResponse(BaseModel):
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    detail: Optional[str] = Field(default=None, description="Detailed error information")


class HealthResponse(BaseModel):
    status: str = Field(default="healthy", description="Server health status")
    version: str = Field(..., description="Server version")
    uptime: float = Field(..., description="Server uptime in seconds")


SUPPORTED_FORMATS = [
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
