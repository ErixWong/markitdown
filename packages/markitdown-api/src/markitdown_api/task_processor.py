# SPDX-FileCopyrightText: 2024-present Microsoft Corporation
#
# SPDX-License-Identifier: MIT
"""
Task processor module for handling file conversions.

Processes conversion tasks asynchronously with progress tracking.
Supports page-by-page processing for PDF files with OCR.
"""

import asyncio
import io
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
from typing import Callable, List, Optional

from markitdown import MarkItDown, StreamInfo

from .models import TaskStatus
from .task_store import TaskStore, Task

# Configure logging
logger = logging.getLogger(__name__)

# Progress allocation constants
PROGRESS_INITIAL_SETUP = 10  # Initial analysis phase (5% analyze + 5% setup)
PROGRESS_PAGE_PROCESSING = 85  # Page-by-page processing phase
PROGRESS_FINAL_COMBINE = 5  # Final combine phase

# Page processing sub-stages ratio
PAGE_EXTRACT_RATIO = 0.05  # 5% of page progress for extraction
PAGE_CONVERT_RATIO = 0.85  # 85% of page progress for conversion (OCR is slow)


def parse_page_range(page_range: str, total_pages: int) -> List[int]:
    """
    Parse page range string into list of page numbers.
    
    Supports formats:
    - "1-5": pages 1 to 5
    - "1,3,5": pages 1, 3, 5
    - "1-5,7,9-11": mixed ranges
    - "": all pages
    
    Args:
        page_range: Page range string
        total_pages: Total number of pages in document
        
    Returns:
        List of page numbers (1-indexed)
        
    Raises:
        ValueError: If total_pages is not positive
    """
    if total_pages <= 0:
        raise ValueError(f"total_pages must be positive, got {total_pages}")
    
    if not page_range or not page_range.strip():
        return list(range(1, total_pages + 1))
    
    pages = []
    parts = page_range.split(",")
    
    for part in parts:
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            start = int(start.strip())
            end = int(end.strip())
            pages.extend(range(start, end + 1))
        else:
            pages.append(int(part))
    
    pages = sorted(set(pages))
    pages = [p for p in pages if 1 <= p <= total_pages]
    
    return pages


def extract_pdf_page(pdf_bytes: io.BytesIO, page_num: int) -> io.BytesIO:
    """
    Extract a single page from PDF as a new PDF BytesIO.
    
    Uses PyMuPDF for efficient page extraction.
    
    Args:
        pdf_bytes: Original PDF as BytesIO
        page_num: Page number (1-indexed)
        
    Returns:
        BytesIO containing single-page PDF
        
    Raises:
        Exception: If page extraction fails
    """
    import fitz  # PyMuPDF
    
    start_time = time.time()
    logger.debug(f"Extracting page {page_num} from PDF...")
    
    doc = None
    new_doc = None
    try:
        pdf_bytes.seek(0)
        doc = fitz.open(stream=pdf_bytes.read(), filetype="pdf")
        
        new_doc = fitz.open()
        new_doc.insert_pdf(doc, from_page=page_num - 1, to_page=page_num - 1)
        
        single_page_bytes = io.BytesIO(new_doc.tobytes())
        single_page_bytes.seek(0)
        
        elapsed = time.time() - start_time
        size_kb = len(single_page_bytes.getvalue()) / 1024
        logger.info(f"Extracted page {page_num}: {size_kb:.1f}KB in {elapsed:.2f}s")
        
        return single_page_bytes
        
    except Exception as e:
        logger.error(f"Failed to extract page {page_num}: {e}")
        raise
    finally:
        if doc:
            doc.close()
        if new_doc:
            new_doc.close()


def get_pdf_page_count(pdf_bytes: io.BytesIO) -> int:
    """
    Get total page count from PDF.
    
    Args:
        pdf_bytes: PDF as BytesIO
        
    Returns:
        Number of pages
    """
    import fitz  # PyMuPDF
    
    logger.debug("Getting PDF page count...")
    
    pdf_bytes.seek(0)
    doc = fitz.open(stream=pdf_bytes.read(), filetype="pdf")
    page_count = doc.page_count
    doc.close()
    
    logger.info(f"PDF has {page_count} pages")
    return page_count


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
            
            # Check if it's a PDF and we should process page-by-page
            is_pdf = filename.lower().endswith(".pdf")
            
            if is_pdf and enable_ocr:
                # Process PDF page-by-page for better progress
                logger.info(f"Task {task_id}: using page-by-page PDF processing")
                await self._process_pdf_page_by_page(
                    task_id, content, filename, page_range, enable_ocr, silent
                )
            else:
                # Process as a whole (non-PDF or non-OCR)
                logger.info(f"Task {task_id}: using whole-file processing")
                await self._process_whole_file(
                    task_id, content, filename, enable_ocr, silent
                )
            
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
    
    async def _process_pdf_page_by_page(
        self,
        task_id: str,
        pdf_bytes: bytes,
        filename: str,
        page_range: Optional[str],
        enable_ocr: bool,
        silent: bool
    ):
        """
        Process PDF page-by-page with real-time progress.
        
        Args:
            task_id: Task ID
            pdf_bytes: PDF content as bytes
            filename: Original filename
            page_range: Page range string (e.g., "1-5" or "1,3,5")
            enable_ocr: Whether to enable OCR
            silent: Suppress progress notifications
        """
        page_process_start = time.time()
        
        # Get total page count (5% progress for analysis)
        await self._report_progress(task_id, 5, "Analyzing PDF...", silent)
        
        try:
            total_pages = await asyncio.get_event_loop().run_in_executor(
                self._executor,
                get_pdf_page_count,
                io.BytesIO(pdf_bytes)
            )
        except Exception as e:
            logger.warning(f"PyMuPDF failed, using pdfplumber fallback: {e}")
            import pdfplumber
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                total_pages = len(pdf.pages)
        
        # Parse page range
        pages_to_process = parse_page_range(page_range, total_pages)
        logger.info(f"Task {task_id}: total_pages={total_pages} pages_to_process={pages_to_process}")
        
        if not pages_to_process:
            logger.error(f"Task {task_id}: no valid pages in range '{page_range}'")
            self.task_store.update_task(
                task_id,
                status=TaskStatus.FAILED,
                progress=-1,
                message=f"No valid pages in range: {page_range}",
                error=f"No valid pages in range: {page_range}"
            )
            if self.progress_callback:
                await self.progress_callback(task_id, -1, f"Error: No valid pages in range")
            return
        
        # Progress setup complete (10% = INITIAL_SETUP)
        await self._report_progress(
            task_id, PROGRESS_INITIAL_SETUP, 
            f"Processing {len(pages_to_process)} of {total_pages} pages...",
            silent
        )
        
        # Create MarkItDown instance
        md = self._markitdown
        if enable_ocr:
            try:
                from markitdown_ocr import MarkItDownOCR
                md = MarkItDownOCR(enable_plugins=True)
            except ImportError:
                logger.warning("OCR requested but markitdown-ocr not available")
        
        # Process each page
        # Progress allocation:
        # - PROGRESS_INITIAL_SETUP: Initial setup (already reported)
        # - PROGRESS_PAGE_PROCESSING: Page processing (each page = 85/total_pages %)
        #   - Each page: PAGE_EXTRACT_RATIO extract, PAGE_CONVERT_RATIO convert (OCR is slow)
        # - PROGRESS_FINAL_COMBINE: Final combine
        markdown_parts = []
        pages_done = 0
        total_pages_to_process = len(pages_to_process)
        progress_per_page = float(PROGRESS_PAGE_PROCESSING) / total_pages_to_process
        
        for page_num in pages_to_process:
            page_start = time.time()
            
            # Check if cancelled
            if task_id in self._cancelled_tasks:
                logger.info(f"Task {task_id}: cancelled at page {page_num}")
                self.task_store.update_task(
                    task_id,
                    status=TaskStatus.CANCELLED,
                    progress=-1,
                    message="Task cancelled"
                )
                if self.progress_callback:
                    await self.progress_callback(task_id, -1, "Task cancelled")
                return
            
            # Calculate progress for this page using constants
            extract_progress = PROGRESS_INITIAL_SETUP + int(pages_done * progress_per_page + PAGE_EXTRACT_RATIO * progress_per_page)
            convert_progress = PROGRESS_INITIAL_SETUP + int(pages_done * progress_per_page + PAGE_CONVERT_RATIO * progress_per_page)
            
            # Extract single page
            await self._report_progress(
                task_id, 
                extract_progress,
                f"Extracting page {page_num}/{total_pages}...",
                silent
            )
            
            try:
                single_page_bytes = await asyncio.get_event_loop().run_in_executor(
                    self._executor,
                    extract_pdf_page,
                    io.BytesIO(pdf_bytes),
                    page_num
                )
            except Exception as e:
                logger.error(f"Task {task_id}: failed to extract page {page_num}: {e}")
                markdown_parts.append(f"\n## Page {page_num}\n\n*[Error extracting page: {str(e)}]*\n")
                pages_done += 1
                continue
            
            # Convert single page (OCR - the slow part)
            await self._report_progress(
                task_id,
                convert_progress,
                f"Converting page {page_num}/{total_pages} (OCR)...",
                silent
            )
            
            stream_info = StreamInfo(filename=filename)
            
            try:
                convert_start = time.time()
                result = await asyncio.get_event_loop().run_in_executor(
                    self._executor,
                    partial(md.convert_stream, single_page_bytes, stream_info=stream_info)
                )
                convert_elapsed = time.time() - convert_start
                
                if result.text_content and result.text_content.strip():
                    markdown_parts.append(f"\n## Page {page_num}\n\n{result.text_content.strip()}")
                    logger.info(f"Task {task_id}: page {page_num} converted in {convert_elapsed:.2f}s, {len(result.text_content)} chars")
                else:
                    markdown_parts.append(f"\n## Page {page_num}\n\n*[No content extracted]*\n")
                    logger.warning(f"Task {task_id}: page {page_num} - no content extracted")
                    
            except Exception as e:
                logger.error(f"Task {task_id}: failed to convert page {page_num}: {e}")
                markdown_parts.append(f"\n## Page {page_num}\n\n*[Error converting page: {str(e)}]*\n")
            
            page_elapsed = time.time() - page_start
            logger.debug(f"Task {task_id}: page {page_num} total time {page_elapsed:.2f}s")
            
            pages_done += 1
        
        # Combine results
        final_markdown = "\n".join(markdown_parts).strip()
        
        total_elapsed = time.time() - page_process_start
        logger.info(f"Task {task_id}: processed {pages_done} pages in {total_elapsed:.2f}s, total {len(final_markdown)} chars")
        
        # Complete task
        self.task_store.update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            message="Conversion completed",
            result=final_markdown
        )
        
        if self.progress_callback:
            await self.progress_callback(task_id, 100, "Conversion completed")
    
    async def _process_whole_file(
        self,
        task_id: str,
        content: bytes,
        filename: str,
        enable_ocr: bool,
        silent: bool
    ):
        """
        Process file as a whole (non-PDF or non-OCR mode).
        
        Args:
            task_id: Task ID
            content: File content as bytes
            filename: Original filename
            enable_ocr: Whether to enable OCR
            silent: Suppress progress notifications
        """
        # Update progress
        self.task_store.update_task(task_id, progress=30, message="Converting to markdown")
        if self.progress_callback and not silent:
            await self.progress_callback(task_id, 30, "Converting to markdown")
        
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
        
        # Run conversion in thread pool
        md = self._markitdown
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
    
    async def _report_progress(self, task_id: str, progress: int, message: str, silent: bool = False):
        """
        Report progress to TaskStore and callback.
        
        Args:
            task_id: Task ID
            progress: Progress percentage (0-100)
            message: Progress message
            silent: Suppress callback notifications
        """
        self.task_store.update_task(task_id, progress=progress, message=message)
        
        if self.progress_callback and not silent:
            await self.progress_callback(task_id, progress, message)
    
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