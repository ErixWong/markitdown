import asyncio
import io
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Callable, List, Optional

from markitdown import MarkItDown, StreamInfo

from .models import TaskStatus
from .task_store import TaskStore, Task

logger = logging.getLogger(__name__)

PROGRESS_INITIAL_SETUP = 10
PROGRESS_PAGE_PROCESSING = 85
PAGE_EXTRACT_RATIO = 0.05
PAGE_CONVERT_RATIO = 0.85


def parse_page_range(page_range: str, total_pages: int) -> List[int]:
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
    import fitz
    start_time = time.time()
    logger.debug(f"Extracting page {page_num} from PDF...")
    try:
        pdf_bytes.seek(0)
        doc = fitz.open(stream=pdf_bytes.read(), filetype="pdf")
        new_doc = fitz.open()
        new_doc.insert_pdf(doc, from_page=page_num - 1, to_page=page_num - 1)
        single_page_bytes = io.BytesIO(new_doc.tobytes())
        new_doc.close()
        doc.close()
        single_page_bytes.seek(0)
        elapsed = time.time() - start_time
        size_kb = len(single_page_bytes.getvalue()) / 1024
        logger.info(f"Extracted page {page_num}: {size_kb:.1f}KB in {elapsed:.2f}s")
        return single_page_bytes
    except Exception as e:
        logger.error(f"Failed to extract page {page_num}: {e}")
        raise


def get_pdf_page_count(pdf_bytes: io.BytesIO) -> int:
    import fitz
    logger.debug("Getting PDF page count...")
    pdf_bytes.seek(0)
    doc = fitz.open(stream=pdf_bytes.read(), filetype="pdf")
    page_count = doc.page_count
    doc.close()
    logger.info(f"PDF has {page_count} pages")
    return page_count


class TaskProcessor:
    def __init__(
        self,
        task_store: TaskStore,
        enable_ocr: bool = False,
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
        max_concurrent: int = 3,
    ):
        self.task_store = task_store
        self.enable_ocr = enable_ocr
        self.progress_callback = progress_callback
        self.max_concurrent = max_concurrent
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self._processing_tasks: dict[str, asyncio.Task] = {}
        self._cancelled_tasks: set[str] = set()
        self._markitdown = self._create_markitdown()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_lock = threading.Lock()
        self._loop_thread: Optional[threading.Thread] = None

    def _create_ocr_markitdown(self) -> Optional[MarkItDown]:
        try:
            from openai import OpenAI
            api_key = os.getenv("MARKITDOWN_OCR_API_KEY")
            api_base = os.getenv("MARKITDOWN_OCR_API_BASE")
            model = os.getenv("MARKITDOWN_OCR_MODEL", "gpt-4o")
            if not api_key:
                logger.warning("MARKITDOWN_OCR_API_KEY not set, OCR will not work")
                return None
            client = OpenAI(api_key=api_key, base_url=api_base or None)
            md = MarkItDown(enable_plugins=True, llm_client=client, llm_model=model)
            logger.info("Created MarkItDown with OCR support")
            return md
        except ImportError as e:
            logger.warning(f"markitdown-ocr or openai not installed: {e}")
            return None

    def _create_markitdown(self) -> MarkItDown:
        enable_ocr = os.getenv("MARKITDOWN_OCR_ENABLED", "false").lower() == "true" or self.enable_ocr
        if enable_ocr:
            md = self._create_ocr_markitdown()
            if md:
                return md
            return MarkItDown(enable_plugins=True)
        return MarkItDown(enable_plugins=False)

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._loop_lock:
            if self._loop is None or not self._loop.is_running():
                self._loop = asyncio.new_event_loop()
                self._loop_thread = threading.Thread(target=self._loop.run_forever, daemon=True)
                self._loop_thread.start()
                logger.info(f"TaskProcessor: started shared event loop in thread {self._loop_thread.name}")
        return self._loop

    def start_processing(self, task_id: str):
        loop = self._ensure_loop()

        def _create_and_track():
            task = loop.create_task(self._process_task(task_id))
            self._processing_tasks[task_id] = task

        loop.call_soon_threadsafe(_create_and_track)

    async def _get_markitdown_for_task(self, task_id: str, enable_ocr: bool) -> MarkItDown:
        if not enable_ocr:
            return self._markitdown
        md = self._create_ocr_markitdown()
        if md:
            logger.info(f"Task {task_id}: using MarkItDown with OCR")
            return md
        logger.warning(f"Task {task_id}: OCR requested but unavailable, using default")
        return self._markitdown

    async def _process_task(self, task_id: str):
        task = self.task_store.get_task(task_id)
        if task is None:
            logger.error(f"Task {task_id} not found")
            return
        if task_id in self._cancelled_tasks:
            logger.info(f"Task {task_id} was cancelled before processing")
            return
        self.task_store.update_task(task_id, status=TaskStatus.PROCESSING, progress=0, message="Starting conversion")
        if self.progress_callback:
            await self.progress_callback(task_id, 0, "Starting conversion")
        try:
            content = task.content
            filename = task.filename
            options = task.options or {}
            enable_ocr = options.get("enable_ocr", self.enable_ocr)
            page_range = options.get("page_range")
            silent = options.get("silent", False)
            logger.info(f"Processing task {task_id}: {filename}, OCR={enable_ocr}")
            md = await self._get_markitdown_for_task(task_id, enable_ocr)
            self.task_store.update_task(task_id, progress=10, message="Reading file")
            if self.progress_callback and not silent:
                await self.progress_callback(task_id, 10, "Reading file")
            if task_id in self._cancelled_tasks:
                self.task_store.update_task(task_id, status=TaskStatus.CANCELLED, progress=-1, message="Task cancelled")
                if self.progress_callback:
                    await self.progress_callback(task_id, -1, "Task cancelled")
                return
            is_pdf = filename.lower().endswith(".pdf")
            if is_pdf and enable_ocr:
                logger.info(f"Task {task_id}: using page-by-page PDF processing")
                await self._process_pdf_page_by_page(task_id, content, filename, page_range, md, silent)
            else:
                logger.info(f"Task {task_id}: using whole-file processing")
                await self._process_whole_file(task_id, content, filename, md, silent)
            logger.info(f"Task {task_id} completed successfully")
        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            self.task_store.update_task(task_id, status=TaskStatus.FAILED, progress=-1, message=f"Error: {str(e)}", error=str(e))
            if self.progress_callback:
                await self.progress_callback(task_id, -1, f"Error: {str(e)}")
        finally:
            self._processing_tasks.pop(task_id, None)
            self._cancelled_tasks.discard(task_id)

    async def _process_pdf_page_by_page(self, task_id: str, pdf_bytes: bytes, filename: str, page_range: Optional[str], md: MarkItDown, silent: bool):
        page_process_start = time.time()
        await self._report_progress(task_id, 5, "Analyzing PDF...", silent)
        try:
            total_pages = await asyncio.get_event_loop().run_in_executor(self._executor, get_pdf_page_count, io.BytesIO(pdf_bytes))
        except Exception as e:
            logger.warning(f"PyMuPDF failed, using pdfplumber fallback: {e}")
            import pdfplumber
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                total_pages = len(pdf.pages)
        pages_to_process = parse_page_range(page_range or "", total_pages)
        logger.info(f"Task {task_id}: total_pages={total_pages} pages_to_process={pages_to_process}")
        if not pages_to_process:
            logger.error(f"Task {task_id}: no valid pages in range '{page_range}'")
            self.task_store.update_task(task_id, status=TaskStatus.FAILED, progress=-1, message=f"No valid pages in range: {page_range}", error=f"No valid pages in range: {page_range}")
            if self.progress_callback:
                await self.progress_callback(task_id, -1, "Error: No valid pages in range")
            return
        await self._report_progress(task_id, PROGRESS_INITIAL_SETUP, f"Processing {len(pages_to_process)} of {total_pages} pages...", silent)
        markdown_parts = []
        pages_done = 0
        total_pages_to_process = len(pages_to_process)
        progress_per_page = float(PROGRESS_PAGE_PROCESSING) / total_pages_to_process
        for page_num in pages_to_process:
            page_start = time.time()
            if task_id in self._cancelled_tasks:
                logger.info(f"Task {task_id}: cancelled at page {page_num}")
                self.task_store.update_task(task_id, status=TaskStatus.CANCELLED, progress=-1, message="Task cancelled")
                if self.progress_callback:
                    await self.progress_callback(task_id, -1, "Task cancelled")
                return
            extract_progress = PROGRESS_INITIAL_SETUP + int(pages_done * progress_per_page + PAGE_EXTRACT_RATIO * progress_per_page)
            convert_progress = PROGRESS_INITIAL_SETUP + int(pages_done * progress_per_page + PAGE_CONVERT_RATIO * progress_per_page)
            await self._report_progress(task_id, extract_progress, f"Extracting page {page_num}/{total_pages}...", silent)
            try:
                single_page_bytes = await asyncio.get_event_loop().run_in_executor(self._executor, extract_pdf_page, io.BytesIO(pdf_bytes), page_num)
            except Exception as e:
                logger.error(f"Task {task_id}: failed to extract page {page_num}: {e}")
                markdown_parts.append(f"\n## Page {page_num}\n\n*[Error extracting page: {str(e)}]*\n")
                pages_done += 1
                continue
            await self._report_progress(task_id, convert_progress, f"Converting page {page_num}/{total_pages} (OCR)...", silent)
            stream_info = StreamInfo(filename=filename)
            try:
                convert_start = time.time()
                result = await asyncio.get_event_loop().run_in_executor(self._executor, partial(md.convert_stream, single_page_bytes, stream_info=stream_info))
                convert_elapsed = time.time() - convert_start
                if result.text_content and result.text_content.strip():
                    markdown_parts.append(f"\n## Page {page_num}\n\n{result.text_content.strip()}")
                    logger.info(f"Task {task_id}: page {page_num} converted in {convert_elapsed:.2f}s, {len(result.text_content)} chars")
                else:
                    markdown_parts.append(f"\n## Page {page_num}\n\n*[No content extracted]*\n")
                    logger.warning(f"Task {task_id}: page {page_num} - no content extracted (OCR may have failed)")
            except Exception as e:
                logger.error(f"Task {task_id}: failed to convert page {page_num}: {e}")
                markdown_parts.append(f"\n## Page {page_num}\n\n*[Error converting page: {str(e)}]*\n")
            page_elapsed = time.time() - page_start
            logger.debug(f"Task {task_id}: page {page_num} total time {page_elapsed:.2f}s")
            pages_done += 1
        final_markdown = "\n".join(markdown_parts).strip()
        total_elapsed = time.time() - page_process_start
        logger.info(f"Task {task_id}: processed {pages_done} pages in {total_elapsed:.2f}s, total {len(final_markdown)} chars")
        self.task_store.update_task(task_id, status=TaskStatus.COMPLETED, progress=100, message="Conversion completed", result=final_markdown)
        if self.progress_callback:
            await self.progress_callback(task_id, 100, "Conversion completed")

    async def _process_whole_file(self, task_id: str, content: bytes, filename: str, md: MarkItDown, silent: bool):
        self.task_store.update_task(task_id, progress=30, message="Converting to markdown")
        if self.progress_callback and not silent:
            await self.progress_callback(task_id, 30, "Converting to markdown")
        if task_id in self._cancelled_tasks:
            self.task_store.update_task(task_id, status=TaskStatus.CANCELLED, progress=-1, message="Task cancelled")
            if self.progress_callback:
                await self.progress_callback(task_id, -1, "Task cancelled")
            return
        result = await asyncio.get_event_loop().run_in_executor(self._executor, lambda: md.convert_stream(io.BytesIO(content)))
        if task_id in self._cancelled_tasks:
            self.task_store.update_task(task_id, status=TaskStatus.CANCELLED, progress=-1, message="Task cancelled")
            if self.progress_callback:
                await self.progress_callback(task_id, -1, "Task cancelled")
            return
        self.task_store.update_task(task_id, progress=80, message="Processing result")
        if self.progress_callback and not silent:
            await self.progress_callback(task_id, 80, "Processing result")
        markdown_content = result.text_content
        self.task_store.update_task(task_id, status=TaskStatus.COMPLETED, progress=100, message="Conversion completed", result=markdown_content)
        if self.progress_callback:
            await self.progress_callback(task_id, 100, "Conversion completed")

    async def _report_progress(self, task_id: str, progress: int, message: str, silent: bool = False):
        self.task_store.update_task(task_id, progress=progress, message=message)
        if self.progress_callback and not silent:
            await self.progress_callback(task_id, progress, message)

    def cancel_processing(self, task_id: str) -> bool:
        self._cancelled_tasks.add(task_id)
        if task_id in self._processing_tasks:
            task = self._processing_tasks[task_id]
            if self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(task.cancel)
            return True
        return False

    def get_active_count(self) -> int:
        return len(self._processing_tasks)


_task_processor: Optional[TaskProcessor] = None


def get_task_processor() -> TaskProcessor:
    global _task_processor
    if _task_processor is None:
        from .task_store import get_task_store
        from .sse_notifications import get_notification_service
        task_store = get_task_store()
        notification_service = get_notification_service()
        async def progress_callback(task_id: str, progress: int, message: str):
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