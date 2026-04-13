# SPDX-FileCopyrightText: 2024-present Microsoft Corporation
#
# SPDX-License-Identifier: MIT
"""
Pydantic models for RESTful API request/response schemas.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Task status enumeration."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ConversionOptions(BaseModel):
    """Options for file conversion."""
    enable_ocr: bool = Field(default=False, description="Enable OCR for image extraction")
    ocr_model: Optional[str] = Field(default=None, description="OCR model name (e.g., gpt-4o)")
    ocr_prompt: Optional[str] = Field(default=None, description="Custom OCR prompt")
    page_range: Optional[str] = Field(default=None, description="Page range for PDF (e.g., '1-5', '1,3,5')")
    silent: bool = Field(default=False, description="Suppress progress notifications")


class SubmitTaskRequest(BaseModel):
    """Request to submit a conversion task."""
    filename: str = Field(..., description="Original filename (used to infer format)")
    options: ConversionOptions = Field(default_factory=ConversionOptions, description="Conversion options")


class SubmitTaskResponse(BaseModel):
    """Response after submitting a task."""
    task_id: str = Field(..., description="Unique task identifier")
    message: str = Field(default="Task submitted successfully", description="Status message")
    created_at: datetime = Field(..., description="Task creation timestamp")


class TaskStatusResponse(BaseModel):
    """Response for task status query."""
    task_id: str = Field(..., description="Task identifier")
    status: TaskStatus = Field(..., description="Current task status")
    progress: int = Field(..., ge=-1, le=100, description="Progress percentage (0-100, -1 for failed/cancelled)")
    message: str = Field(..., description="Human-readable status message")
    created_at: datetime = Field(..., description="Task creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class TaskResultResponse(BaseModel):
    """Response for task result."""
    task_id: str = Field(..., description="Task identifier")
    status: TaskStatus = Field(..., description="Task status")
    markdown: Optional[str] = Field(default=None, description="Markdown content")
    error: Optional[str] = Field(default=None, description="Error message if failed")


class TaskListItem(BaseModel):
    """Task item in list response."""
    task_id: str
    filename: str
    status: TaskStatus
    progress: int
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    """Response for task list."""
    tasks: list[TaskListItem] = Field(default_factory=list, description="List of tasks")
    total: int = Field(..., description="Total number of tasks matching filter")


class CancelTaskResponse(BaseModel):
    """Response for task cancellation."""
    task_id: str = Field(..., description="Task identifier")
    cancelled: bool = Field(..., description="Whether task was cancelled")
    message: str = Field(..., description="Status message")


class SupportedFormat(BaseModel):
    """Supported file format information."""
    extension: str = Field(..., description="File extension (e.g., '.pdf')")
    mimetype: str = Field(..., description="MIME type")
    ocr_support: bool = Field(default=False, description="Whether OCR is supported")


class SupportedFormatsResponse(BaseModel):
    """Response for supported formats."""
    formats: list[SupportedFormat] = Field(default_factory=list, description="List of supported formats")


class ErrorResponse(BaseModel):
    """Error response."""
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    detail: Optional[str] = Field(default=None, description="Detailed error information")


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(default="healthy", description="Server health status")
    version: str = Field(..., description="Server version")
    uptime: float = Field(..., description="Server uptime in seconds")