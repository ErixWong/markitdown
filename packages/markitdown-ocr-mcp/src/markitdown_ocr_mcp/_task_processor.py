"""
Task Processor: Handles conversion tasks asynchronously.

Processes tasks from TaskStore using MarkItDown with OCR support.
Supports page-by-page processing for PDF files with real-time progress.
"""

import asyncio
import io
import re
import os
import tempfile
import logging
import time
from typing import Callable, Optional, Awaitable, List

from markitdown import MarkItDown, StreamInfo

from ._task_store import TaskStore

# Configure logging
logger = logging.getLogger(__name__)


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
    """
    if not page_range or not page_range.strip():
        return list(range(1, total_pages + 1))
    
    pages = []
    parts = page_range.split(",")
    
    for part in parts:
        part = part.strip()
        if "-" in part:
            # Range like "1-5"
            start, end = part.split("-", 1)
            start = int(start.strip())
            end = int(end.strip())
            pages.extend(range(start, end + 1))
        else:
            # Single page like "3"
            pages.append(int(part))
    
    # Validate and deduplicate
    pages = sorted(set(pages))
    
    # Filter out invalid pages
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
    """
    import fitz  # PyMuPDF
    
    start_time = time.time()
    logger.debug(f"Extracting page {page_num} from PDF...")
    
    try:
        pdf_bytes.seek(0)
        doc = fitz.open(stream=pdf_bytes.read(), filetype="pdf")
        
        # Create new PDF with single page
        new_doc = fitz.open()
        new_doc.insert_pdf(doc, from_page=page_num - 1, to_page=page_num - 1)  # 0-indexed
        doc.close()
        
        # Export to BytesIO
        single_page_bytes = io.BytesIO(new_doc.tobytes())
        new_doc.close()
        single_page_bytes.seek(0)
        
        elapsed = time.time() - start_time
        size_kb = len(single_page_bytes.getvalue()) / 1024
        logger.info(f"Extracted page {page_num}: {size_kb:.1f}KB in {elapsed:.2f}s")
        
        return single_page_bytes
        
    except Exception as e:
        logger.error(f"Failed to extract page {page_num}: {e}")
        raise


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
    Processes conversion tasks asynchronously.
    
    Uses MarkItDown with OCR plugin for document conversion.
    Supports page-by-page processing for PDFs with real-time progress.
    """
    
    def __init__(
        self,
        task_store: TaskStore,
        enable_ocr: bool = False,
        progress_callback: Optional[Callable[[str, int, str], Awaitable[None]]] = None,
    ):
        """
        Initialize task processor.
        
        Args:
            task_store: TaskStore instance for task management
            enable_ocr: Whether to enable OCR plugin by default
            progress_callback: Optional async callback for progress updates (task_id, progress, message)
        """
        self.task_store = task_store
        self.enable_ocr = enable_ocr
        self.progress_callback = progress_callback
        self._processing_tasks: dict[str, asyncio.Task] = {}
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
    
    async def _report_progress(self, task_id: str, progress: int, message: str):
        """
        Report progress to TaskStore and callback.
        
        Args:
            task_id: Task ID
            progress: Progress percentage (0-100)
            message: Progress message
        """
        # Update TaskStore (synchronous)
        self.task_store.update_progress(task_id, progress, message)
        
        # Call async callback
        if self.progress_callback:
            await self.progress_callback(task_id, progress, message)
    
    async def process_task(self, task_id: str):
        """
        Process a single conversion task.
        
        For PDF files, processes page-by-page for better progress reporting.
        For other files, processes as a whole.
        
        Args:
            task_id: Task ID to process
        """
        start_time = time.time()
        
        # Store the current event loop for thread-safe callbacks
        self._event_loop = asyncio.get_running_loop()
        
        task = self.task_store.get_task(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found")
            return
        
        logger.info(f"Processing task {task_id}: {task.source_path}")
        
        # Update status to processing
        await self._report_progress(task_id, 0, "Starting conversion...")
        
        try:
            # Read source file
            with open(task.source_path, 'rb') as f:
                file_bytes = io.BytesIO(f.read())
            
            # Determine options
            options = task.options
            enable_ocr = options.get("enable_ocr", self.enable_ocr)
            page_range = options.get("page_range", "")
            
            # Get filename for StreamInfo
            filename = task.source_path.split("_source_")[-1] if "_source_" in task.source_path else "document"
            
            logger.info(f"Task {task_id}: filename={filename} ocr={enable_ocr} page_range={page_range}")
            
            # Check if it's a PDF and we should process page-by-page
            is_pdf = filename.lower().endswith(".pdf")
            
            if is_pdf and enable_ocr:
                # Process PDF page-by-page for better progress
                logger.info(f"Task {task_id}: using page-by-page PDF processing")
                await self._process_pdf_page_by_page(
                    task_id, file_bytes, filename, page_range, enable_ocr
                )
            else:
                # Process as a whole (non-PDF or non-OCR)
                logger.info(f"Task {task_id}: using whole-file processing")
                await self._process_whole_file(
                    task_id, file_bytes, filename, enable_ocr
                )
            
            elapsed = time.time() - start_time
            logger.info(f"Task {task_id} completed in {elapsed:.2f}s")
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"Task {task_id} failed after {elapsed:.2f}s: {e}")
            self.task_store.fail_task(task_id, str(e))
            if self.progress_callback:
                await self.progress_callback(task_id, -1, f"Error: {str(e)}")
    
    async def _process_pdf_page_by_page(
        self,
        task_id: str,
        pdf_bytes: io.BytesIO,
        filename: str,
        page_range: str,
        enable_ocr: bool
    ):
        """
        Process PDF page-by-page with real-time progress.
        
        Args:
            task_id: Task ID
            pdf_bytes: PDF content as BytesIO
            filename: Original filename
            page_range: Page range string (e.g., "1-5" or "1,3,5")
            enable_ocr: Whether to enable OCR
        """
        page_process_start = time.time()
        
        # Get total page count
        await self._report_progress(task_id, 5, "Analyzing PDF...")
        
        try:
            total_pages = await asyncio.to_thread(get_pdf_page_count, pdf_bytes)
        except Exception as e:
            logger.warning(f"PyMuPDF failed, using pdfplumber fallback: {e}")
            # Fallback: use pdfplumber
            import pdfplumber
            pdf_bytes.seek(0)
            with pdfplumber.open(pdf_bytes) as pdf:
                total_pages = len(pdf.pages)
        
        # Parse page range
        pages_to_process = parse_page_range(page_range, total_pages)
        logger.info(f"Task {task_id}: total_pages={total_pages} pages_to_process={pages_to_process}")
        
        if not pages_to_process:
            logger.error(f"Task {task_id}: no valid pages in range '{page_range}'")
            self.task_store.fail_task(task_id, f"No valid pages in range: {page_range}")
            if self.progress_callback:
                await self.progress_callback(task_id, -1, f"Error: No valid pages in range")
            return
        
        await self._report_progress(
            task_id, 10, 
            f"Processing {len(pages_to_process)} of {total_pages} pages..."
        )
        
        # Create MarkItDown instance
        mid = MarkItDown(enable_plugins=enable_ocr)
        
        # Process each page
        markdown_parts = []
        pages_done = 0
        
        for page_num in pages_to_process:
            page_start = time.time()
            
            # Check if task was cancelled
            if task_id in self._processing_tasks:
                task_obj = self._processing_tasks[task_id]
                if task_obj.cancelled():
                    logger.info(f"Task {task_id}: cancelled at page {page_num}")
                    self.task_store.cancel_task(task_id)
                    return
            
            # Extract single page
            await self._report_progress(
                task_id, 
                10 + int((pages_done / len(pages_to_process)) * 85),
                f"Extracting page {page_num}/{total_pages}..."
            )
            
            try:
                single_page_bytes = await asyncio.to_thread(
                    extract_pdf_page, pdf_bytes, page_num
                )
            except Exception as e:
                logger.error(f"Task {task_id}: failed to extract page {page_num}: {e}")
                markdown_parts.append(f"\n## Page {page_num}\n\n*[Error extracting page: {str(e)}]*\n")
                pages_done += 1
                continue
            
            # Convert single page
            await self._report_progress(
                task_id,
                10 + int((pages_done / len(pages_to_process)) * 85) + 5,
                f"Converting page {page_num}/{total_pages}..."
            )
            
            stream_info = StreamInfo(filename=filename)
            
            try:
                convert_start = time.time()
                result = await asyncio.to_thread(
                    mid.convert_stream,
                    single_page_bytes,
                    stream_info=stream_info
                )
                convert_elapsed = time.time() - convert_start
                
                if result.markdown and result.markdown.strip():
                    # Add page header
                    markdown_parts.append(f"\n## Page {page_num}\n\n{result.markdown.strip()}")
                    logger.info(f"Task {task_id}: page {page_num} converted in {convert_elapsed:.2f}s, {len(result.markdown)} chars")
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
        
        # Save result
        self.task_store.complete_task(task_id, final_markdown)
        
        # Report completion
        if self.progress_callback:
            await self.progress_callback(task_id, 100, "Conversion completed")
    
    async def _process_whole_file(
        self,
        task_id: str,
        file_bytes: io.BytesIO,
        filename: str,
        enable_ocr: bool
    ):
        """
        Process file as a whole (non-PDF or non-OCR mode).
        
        Args:
            task_id: Task ID
            file_bytes: File content as BytesIO
            filename: Original filename
            enable_ocr: Whether to enable OCR
        """
        await self._report_progress(task_id, 10, "Reading document...")
        
        # Create MarkItDown instance
        mid = MarkItDown(enable_plugins=enable_ocr)
        
        # Create stream info
        stream_info = StreamInfo(filename=filename)
        
        await self._report_progress(task_id, 20, "Converting document...")
        
        # Perform conversion in a separate thread
        result = await asyncio.to_thread(
            mid.convert_stream,
            file_bytes,
            stream_info=stream_info
        )
        
        # Save result
        self.task_store.complete_task(task_id, result.markdown)
        
        # Report completion
        if self.progress_callback:
            await self.progress_callback(task_id, 100, "Conversion completed")
    
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