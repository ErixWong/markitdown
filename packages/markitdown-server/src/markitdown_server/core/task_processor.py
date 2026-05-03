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

from .models import QueueStatsResponse, TaskStatus
from .task_queue import FifoStrategy, QueueItem, TaskDispatchStrategy, TaskDispatchStrategyFactory
from .task_store import TaskStore

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
        dispatch_strategy: TaskDispatchStrategy = None,
        scheduler_poll_interval: float = 0.1,
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
        self._dispatch_strategy = dispatch_strategy or FifoStrategy()
        self._scheduler_poll_interval = scheduler_poll_interval
        self._scheduler_task: Optional[asyncio.Task] = None
        self._scheduler_running = False
        self._completed_count = 0
        self._failed_count = 0
        self._lock = threading.Lock()
        self._active_tasks_cache: list[dict] = []
        self._active_tasks_cache_time: float = 0
        self._active_tasks_cache_ttl: float = 2.0

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
        task = self.task_store.get_task(task_id)
        if task is None:
            logger.error(f"Task {task_id} not found in store")
            return

        loop = self._ensure_loop()

        def _enqueue_task():
            async def _async_enqueue():
                result = await self._dispatch_strategy.enqueue(
                    task_id, task.source_path, task.filename, task.options or {}
                )
                if not result.accepted:
                    self.task_store.update_task(
                        task_id,
                        status=TaskStatus.FAILED,
                        progress=-1,
                        message="Queue full",
                        error="Queue is full, try again later",
                    )
                    logger.warning(f"Task {task_id}: enqueue rejected - {result.message}")

            loop.create_task(_async_enqueue())

        loop.call_soon_threadsafe(_enqueue_task)

        if not self._scheduler_running:
            self._start_scheduler(loop)

    def _start_scheduler(self, loop: asyncio.AbstractEventLoop):
        def _start():
            if not self._scheduler_running:
                self._scheduler_running = True
                self._scheduler_task = loop.create_task(self._scheduler_loop())
                logger.info("Task scheduler started")

        loop.call_soon_threadsafe(_start)

    async def _get_markitdown_for_task(self, task_id: str, enable_ocr: bool) -> MarkItDown:
        if not enable_ocr:
            return self._markitdown
        md = self._create_ocr_markitdown()
        if md:
            logger.info(f"Task {task_id}: using MarkItDown with OCR")
            return md
        logger.warning(f"Task {task_id}: OCR requested but unavailable, using default")
        return self._markitdown

    async def _process_task(self, queue_item: QueueItem):
        task_id = queue_item.task_id
        task = self.task_store.get_task(task_id)
        if task is None:
            logger.error(f"Task {task_id} not found")
            return
        content = task.content if task.content else None
        filename = queue_item.filename or task.filename
        options = queue_item.options or task.options or {}
        task_succeeded = False
        if task_id in self._cancelled_tasks:
            logger.info(f"Task {task_id} was cancelled before processing")
            return
        self.task_store.update_task(task_id, status=TaskStatus.PROCESSING, progress=0, message="Starting conversion")
        if self.progress_callback:
            await self.progress_callback(task_id, 0, "Starting conversion")
        try:
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
            task_succeeded = True
            logger.info(f"Task {task_id} completed successfully")
        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            self.task_store.update_task(task_id, status=TaskStatus.FAILED, progress=-1, message=f"Error: {str(e)}", error=str(e))
            if self.progress_callback:
                await self.progress_callback(task_id, -1, f"Error: {str(e)}")
        finally:
            with self._lock:
                self._processing_tasks.pop(task_id, None)
                self._cancelled_tasks.discard(task_id)
                if task_succeeded:
                    self._completed_count += 1
                else:
                    self._failed_count += 1

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

    async def _scheduler_loop(self):
        logger.info("Scheduler loop started")
        try:
            while self._scheduler_running:
                active = len(self._processing_tasks)
                if active < self.max_concurrent:
                    queue_item = await self._dispatch_strategy.dequeue()
                    if queue_item:
                        task_id = queue_item.task_id
                        task = self.task_store.get_task(task_id)
                        if task and task_id not in self._cancelled_tasks:
                            with self._lock:
                                if task_id not in self._processing_tasks and task_id not in self._cancelled_tasks:
                                    self._processing_tasks[task_id] = asyncio.create_task(
                                        self._process_task(queue_item)
                                    )
                await asyncio.sleep(self._scheduler_poll_interval)
        except asyncio.CancelledError:
            logger.info("Scheduler loop cancelled")
        finally:
            self._scheduler_running = False
            logger.info("Scheduler loop stopped")

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

    def get_queue_stats(self) -> QueueStatsResponse:
        queue_stats = self._dispatch_strategy.get_stats()
        with self._lock:
            queue_stats["max_concurrent"] = self.max_concurrent
            queue_stats["total_queued"] = self._get_total_queued()
            queue_stats["total_processing"] = len(self._processing_tasks)
            queue_stats["total_completed"] = self._completed_count
            queue_stats["total_failed"] = self._failed_count
            queue_stats["active_tasks"] = self._get_active_tasks_info()
            queue_stats["fifo_queue"] = queue_stats.pop("fifo", None)
            queue_stats["small_queue"] = queue_stats.pop("small_queue", None)
            queue_stats["large_queue"] = queue_stats.pop("large_queue", None)
            queue_stats["ratio_config"] = queue_stats.pop("ratio", None)
        return QueueStatsResponse(**queue_stats)

    def _get_total_queued(self) -> int:
        stats = self._dispatch_strategy.get_stats()
        if self._dispatch_strategy.strategy_name == "fifo":
            return stats.get("fifo", {}).get("pending", 0)
        else:
            small = stats.get("small_queue", {}).get("pending", 0)
            large = stats.get("large_queue", {}).get("pending", 0)
            return small + large

    def _get_active_tasks_info(self) -> list[dict]:
        import time as _time
        now = _time.time()
        if self._processing_tasks and (now - self._active_tasks_cache_time > self._active_tasks_cache_ttl):
            info_list = []
            for task_id, task in self._processing_tasks.items():
                task_data = self.task_store.get_task(task_id)
                if task_data:
                    info_list.append({
                        "task_id": task_id,
                        "filename": task_data.filename,
                        "status": "processing",
                        "progress": task_data.progress,
                        "started_at": task_data.updated_at.isoformat() if hasattr(task_data, 'updated_at') else None,
                        "duration_seconds": 0,
                    })
            self._active_tasks_cache = info_list
            self._active_tasks_cache_time = now
        return self._active_tasks_cache

    async def promote_task(self, task_id: str) -> dict:
        return await self._dispatch_strategy.promote_task(task_id)

    async def remove_task_from_queue(self, task_id: str) -> bool:
        return await self._dispatch_strategy.remove_task(task_id)

    def set_dispatch_strategy(self, strategy: TaskDispatchStrategy):
        logger.info(f"Switching dispatch strategy from {self._dispatch_strategy.strategy_name} to {strategy.strategy_name}")
        self._dispatch_strategy = strategy


_task_processor: Optional[TaskProcessor] = None


def get_task_processor() -> TaskProcessor:
    global _task_processor
    if _task_processor is None:
        from .sse_notifications import get_notification_service
        from .task_store import get_task_store
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

        strategy_type = os.getenv("MARKITDOWN_DISPATCH_STRATEGY", "fifo").lower()
        strategy_params = {
            "max_queue_size": int(os.getenv("MARKITDOWN_MAX_QUEUE_SIZE", "100")),
            "queue_timeout": float(os.getenv("MARKITDOWN_QUEUE_TIMEOUT", "5.0")),
        }
        if strategy_type == "ratio":
            strategy_params["small_ratio"] = float(os.getenv("MARKITDOWN_SMALL_RATIO", "0.4"))
            strategy_params["large_ratio"] = float(os.getenv("MARKITDOWN_LARGE_RATIO", "0.6"))
            threshold_mb = int(os.getenv("MARKITDOWN_FILE_THRESHOLD_MB", "5"))
            strategy_params["file_threshold_bytes"] = threshold_mb * 1024 * 1024

        dispatch_strategy = TaskDispatchStrategyFactory.create(strategy_type, **strategy_params)

        _task_processor = TaskProcessor(
            task_store=task_store,
            enable_ocr=os.getenv("MARKITDOWN_OCR_ENABLED", "false").lower() == "true",
            progress_callback=progress_callback,
            dispatch_strategy=dispatch_strategy,
        )
    return _task_processor
