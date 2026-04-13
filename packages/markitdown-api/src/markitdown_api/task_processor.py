# SPDX-FileCopyrightText: 2024-present Microsoft Corporation
#
# SPDX-License-Identifier: MIT
"""
Task processor module for handling file conversions.

Processes conversion tasks asynchronously with progress tracking.
"""

import asyncio
import io
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable, Optional

from markitdown import MarkItDown

from .models import TaskStatus
from .task_store import TaskStore, Task

# Configure logging
logger = logging.getLogger(__name__)


class TaskProcessor:
    """
    Task processor for file conversion.
    
    Handles async task processing with progress callbacks.
    """
    
    def __init__(
        self,
        task_store: TaskStore,
        enable_ocr: bool = False,
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
        max_concurrent: int = 3,
    ):
        """
        Initialize task processor.
        
        Args:
            task_store: Task storage instance
            enable_ocr: Enable OCR by default
            progress_callback: Async callback for progress updates
            max_concurrent: Maximum concurrent processing tasks
        """
        self.task_store = task_store
        self.enable_ocr = enable_ocr
        self.progress_callback = progress_callback
        self.max_concurrent = max_concurrent
        
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self._processing_tasks: dict[str, asyncio.Task] = {}
        self._cancelled_tasks: set[str] = set()
        
        # Initialize MarkItDown
        self._markitdown = self._create_markitdown()
    
    def _create_markitdown(self) -> MarkItDown:
        """Create MarkItDown instance with OCR support if enabled."""
        enable_ocr = os.getenv("MARKITDOWN_OCR_ENABLED", "false").lower() == "true" or self.enable_ocr
        
        if enable_ocr:
            try:
                # Try to use OCR-enabled MarkItDown
                from markitdown_ocr import MarkItDownOCR
                return MarkItDownOCR(enable_plugins=True)
            except ImportError:
                logger.warning("markitdown-ocr not installed, using standard MarkItDown")
                return MarkItDown(enable_plugins=True)
        else:
            return MarkItDown(enable_plugins=False)
    
    def start_processing(self, task_id: str):
        """
        Start processing a task in background.
        
        Args:
            task_id: Task ID to process
        """
        # Create async task for processing
        async def process_wrapper():
            await self._process_task(task_id)
        
        # Run in background
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        task = loop.create_task(process_wrapper())
        self._processing_tasks[task_id] = task
        
        # Run loop in thread
        threading.Thread(
            target=loop.run_forever,
            daemon=True
        ).start()
    
    async def _process_task(self, task_id: str):
        """
        Process a conversion task.
        
        Args:
            task_id: Task ID to process
        """
        task = self.task_store.get_task(task_id)
        if task is None:
            logger.error(f"Task {task_id} not found")
            return
        
        # Check if cancelled
        if task_id in self._cancelled_tasks:
            logger.info(f"Task {task_id} was cancelled before processing")
            return
        
        # Update status to processing
        self.task_store.update_task(
            task_id,
            status=TaskStatus.PROCESSING,
            progress=0,
            message="Starting conversion"
        )
        
        if self.progress_callback:
            await self.progress_callback(task_id, 0, "Starting conversion")
        
        try:
            # Get file content
            content = task.content
            filename = task.filename
            
            # Get options
            options = task.options or {}
            enable_ocr = options.get("enable_ocr", self.enable_ocr)
            page_range = options.get("page_range")
            silent = options.get("silent", False)
            
            logger.info(f"Processing task {task_id}: {filename}, OCR={enable_ocr}")
            
            # Create appropriate MarkItDown instance
            md = self._markitdown
            if enable_ocr and not isinstance(md, MarkItDown):
                try:
                    from markitdown_ocr import MarkItDownOCR
                    md = MarkItDownOCR(enable_plugins=True)
                except ImportError:
                    logger.warning("OCR requested but markitdown-ocr not available")
            
            # Update progress
            self.task_store.update_task(task_id, progress=10, message="Reading file")
            if self.progress_callback and not silent:
                await self.progress_callback(task_id, 10, "Reading file")
            
            # Check cancellation
            if task_id in self._cancelled_tasks:
                self.task_store.update_task(
                    task_id,
                    status=TaskStatus.CANCELLED,
                    progress=-1,
                    message="Task cancelled"
                )
                if self.progress_callback:
                    await self.progress_callback(task_id, -1, "Task cancelled")
                return
            
            # Convert file
            self.task_store.update_task(task_id, progress=30, message="Converting to markdown")
            if self.progress_callback and not silent:
                await self.progress_callback(task_id, 30, "Converting to markdown")
            
            # Run conversion in thread pool
            result = await asyncio.get_event_loop().run_in_executor(
                self._executor,
                lambda: md.convert_stream(io.BytesIO(content))
            )
            
            # Check cancellation
            if task_id in self._cancelled_tasks:
                self.task_store.update_task(
                    task_id,
                    status=TaskStatus.CANCELLED,
                    progress=-1,
                    message="Task cancelled"
                )
                if self.progress_callback:
                    await self.progress_callback(task_id, -1, "Task cancelled")
                return
            
            # Update progress
            self.task_store.update_task(task_id, progress=80, message="Processing result")
            if self.progress_callback and not silent:
                await self.progress_callback(task_id, 80, "Processing result")
            
            # Save result
            markdown_content = result.text_content
            
            # Complete task
            self.task_store.update_task(
                task_id,
                status=TaskStatus.COMPLETED,
                progress=100,
                message="Conversion completed",
                result=markdown_content
            )
            
            if self.progress_callback:
                await self.progress_callback(task_id, 100, "Conversion completed")
            
            logger.info(f"Task {task_id} completed successfully")
            
        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            
            self.task_store.update_task(
                task_id,
                status=TaskStatus.FAILED,
                progress=-1,
                message=f"Error: {str(e)}",
                error=str(e)
            )
            
            if self.progress_callback:
                await self.progress_callback(task_id, -1, f"Error: {str(e)}")
        
        finally:
            # Clean up
            self._processing_tasks.pop(task_id, None)
            self._cancelled_tasks.discard(task_id)
    
    def cancel_processing(self, task_id: str) -> bool:
        """
        Cancel a processing task.
        
        Args:
            task_id: Task ID to cancel
            
        Returns:
            True if cancellation was initiated
        """
        self._cancelled_tasks.add(task_id)
        
        # Cancel async task if running
        if task_id in self._processing_tasks:
            task = self._processing_tasks[task_id]
            task.cancel()
            return True
        
        return False
    
    def get_active_count(self) -> int:
        """Get number of active processing tasks."""
        return len(self._processing_tasks)


# Global task processor instance
_task_processor: Optional[TaskProcessor] = None


def get_task_processor() -> TaskProcessor:
    """Get or create global TaskProcessor instance."""
    global _task_processor
    if _task_processor is None:
        from .task_store import get_task_store
        from .sse_notifications import get_notification_service
        
        task_store = get_task_store()
        notification_service = get_notification_service()
        
        async def progress_callback(task_id: str, progress: int, message: str):
            """Progress callback for SSE notifications."""
            task = task_store.get_task(task_id)
            silent = task.options.get("silent", False) if task else False
            
            if not silent:
                await notification_service.notify_progress(task_id, progress, message)
            
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