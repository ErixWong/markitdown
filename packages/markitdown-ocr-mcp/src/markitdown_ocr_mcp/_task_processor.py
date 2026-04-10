"""
Task Processor: Handles conversion tasks asynchronously.

Processes tasks from TaskStore using MarkItDown with OCR support.
"""

import asyncio
import io
from typing import Callable, Optional

from markitdown import MarkItDown, StreamInfo

from ._task_store import TaskStore


class TaskProcessor:
    """
    Processes conversion tasks asynchronously.
    
    Uses MarkItDown with OCR plugin for document conversion.
    Supports progress callbacks for real-time updates.
    """
    
    def __init__(
        self,
        task_store: TaskStore,
        enable_ocr: bool = False,
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
    ):
        """
        Initialize task processor.
        
        Args:
            task_store: TaskStore instance for task management
            enable_ocr: Whether to enable OCR plugin by default
            progress_callback: Optional callback for progress updates (task_id, progress, message)
        """
        self.task_store = task_store
        self.enable_ocr = enable_ocr
        self.progress_callback = progress_callback
        self._processing_tasks: dict[str, asyncio.Task] = {}
    
    def _on_progress(self, task_id: str, current: int, total: int, message: str):
        """Internal progress handler that updates TaskStore and calls callback."""
        progress = int(current / total * 100) if total > 0 else 0
        self.task_store.update_progress(task_id, progress, message)
        
        if self.progress_callback:
            self.progress_callback(task_id, progress, message)
    
    async def process_task(self, task_id: str):
        """
        Process a single conversion task.
        
        Args:
            task_id: Task ID to process
        """
        task = self.task_store.get_task(task_id)
        if not task:
            return
        
        # Update status to processing
        self.task_store.update_progress(task_id, 0, "Starting conversion...")
        
        try:
            # Read source file
            with open(task.source_path, 'rb') as f:
                file_stream = io.BytesIO(f.read())
            
            # Determine options
            options = task.options
            enable_ocr = options.get("enable_ocr", self.enable_ocr)
            
            # Create MarkItDown instance
            mid = MarkItDown(enable_plugins=enable_ocr)
            
            # Get filename for StreamInfo
            filename = task.source_path.split("_source_")[-1] if "_source_" in task.source_path else "document"
            
            # Create stream info
            stream_info = StreamInfo(filename=filename)
            
            # Simulate progress for now (real progress requires converter modification)
            self._on_progress(task_id, 1, 10, "Reading document...")
            
            # Perform conversion
            result = mid.convert_stream(file_stream, stream_info=stream_info)
            
            self._on_progress(task_id, 9, 10, "Processing complete...")
            
            # Save result
            self.task_store.complete_task(task_id, result.markdown)
            
            self._on_progress(task_id, 10, 10, "Conversion completed")
            
        except Exception as e:
            self.task_store.fail_task(task_id, str(e))
            if self.progress_callback:
                self.progress_callback(task_id, -1, f"Error: {str(e)}")
    
    async def process_task_async(self, task_id: str):
        """
        Start async processing of a task.
        
        Args:
            task_id: Task ID to process
        """
        # Create async task
        task = asyncio.create_task(self.process_task(task_id))
        self._processing_tasks[task_id] = task
        
        # Wait for completion
        try:
            await task
        finally:
            self._processing_tasks.pop(task_id, None)
    
    def start_processing(self, task_id: str) -> asyncio.Task:
        """
        Start processing a task in background.
        
        Args:
            task_id: Task ID to process
        
        Returns:
            asyncio.Task object
        """
        task = asyncio.create_task(self.process_task(task_id))
        self._processing_tasks[task_id] = task
        return task
    
    def cancel_processing(self, task_id: str) -> bool:
        """
        Cancel a running task.
        
        Args:
            task_id: Task ID to cancel
        
        Returns:
            True if task was cancelled, False otherwise
        """
        if task_id in self._processing_tasks:
            self._processing_tasks[task_id].cancel()
            self._processing_tasks.pop(task_id, None)
            return True
        return False
    
    def get_active_task_count(self) -> int:
        """Get number of currently processing tasks."""
        return len(self._processing_tasks)