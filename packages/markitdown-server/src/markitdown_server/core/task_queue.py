import asyncio
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Union

logger = logging.getLogger(__name__)


class QueueFullError(Exception):
    """Queue is full, task cannot be enqueued."""
    pass


@dataclass
class QueueItem:
    task_id: str
    source_path: Optional[str] = None
    filename: Optional[str] = None
    options: Optional[dict] = None


@dataclass
class QueueResult:
    accepted: bool
    task_id: str
    position: int = 0
    message: str = ""


class TaskDispatchStrategy(ABC):
    @property
    @abstractmethod
    def strategy_name(self) -> str:
        ...

    @abstractmethod
    async def enqueue(self, task_id: str, task_content: Union[bytes, str, None], filename: str, options: dict) -> QueueResult:
        ...

    @abstractmethod
    async def dequeue(self) -> Optional[QueueItem]:
        ...

    @abstractmethod
    def get_stats(self) -> dict:
        ...

    @abstractmethod
    async def promote_task(self, task_id: str) -> dict:
        ...

    @abstractmethod
    async def remove_task(self, task_id: str) -> bool:
        ...

    @abstractmethod
    def get_queue_position(self, task_id: str) -> Optional[int]:
        ...

    @abstractmethod
    def is_queue_full(self) -> bool:
        ...


class FifoStrategy(TaskDispatchStrategy):
    def __init__(self, max_queue_size: int = 100, queue_timeout: float = 5.0):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._positions: dict[str, int] = {}
        self._task_index: dict[str, int] = {}
        self._counter: int = 0
        self.max_queue_size = max_queue_size
        self.queue_timeout = queue_timeout

    @property
    def strategy_name(self) -> str:
        return "fifo"

    async def enqueue(self, task_id: str, task_content: Union[bytes, str, None], filename: str, options: dict) -> QueueResult:
        self._counter += 1
        position = self._counter
        self._positions[task_id] = position
        source_path = None
        if isinstance(task_content, str):
            source_path = task_content
            task_content = None

        self._task_index[task_id] = self._queue.qsize()

        try:
            await asyncio.wait_for(
                self._queue.put((position, task_id, source_path, filename, options)),
                timeout=self.queue_timeout,
            )
            return QueueResult(
                accepted=True,
                task_id=task_id,
                position=self._queue.qsize(),
                message=f"Task queued at position {self._queue.qsize()}",
            )
        except asyncio.TimeoutError:
            self._positions.pop(task_id, None)
            return QueueResult(
                accepted=False,
                task_id=task_id,
                message="Queue is full, try again later",
            )

    async def dequeue(self) -> Optional[QueueItem]:
        try:
            position, task_id, source_path, filename, options = await asyncio.wait_for(
                self._queue.get(), timeout=0.1
            )
            self._positions.pop(task_id, None)
            self._task_index.pop(task_id, None)
            for i, key in enumerate(self._task_index):
                self._task_index[key] = i
            return QueueItem(task_id=task_id, source_path=source_path, filename=filename, options=options)
        except asyncio.TimeoutError:
            return None

    def get_task(self, task_id: str) -> Optional[tuple]:
        if task_id not in self._task_index:
            return None
        target_idx = self._task_index[task_id]
        items = []
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                items.append(item)
            except asyncio.QueueEmpty:
                break
        for item in items:
            self._queue.put_nowait(item)
        if 0 <= target_idx < len(items):
            return items[target_idx]
        return None

    def get_queue_item(self, task_id: str) -> Optional[tuple]:
        return self.get_task(task_id)

    def get_stats(self) -> dict:
        pending = self._queue.qsize()
        return {
            "strategy": "fifo",
            "fifo": {
                "pending": pending,
                "capacity": self.max_queue_size,
                "utilization": round(pending / self.max_queue_size, 4) if self.max_queue_size > 0 else 0,
            },
            "ratio": None,
        }

    async def promote_task(self, task_id: str) -> dict:
        if task_id not in self._positions:
            return {"success": False, "error": "Task not found in queue"}

        items = []
        task_item = None
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                if item[1] == task_id:
                    task_item = item
                else:
                    items.append(item)
            except asyncio.QueueEmpty:
                break

        new_position = 0
        self._queue.put_nowait((new_position, task_id, task_item[2], task_item[3], task_item[4]))

        for idx, item in enumerate(items):
            self._queue.put_nowait((idx + 1, item[1], item[2], item[3], item[4]))

        self._positions[task_id] = new_position
        self._task_index[task_id] = 0
        for idx, item in enumerate(items):
            if item[1] in self._task_index:
                self._task_index[item[1]] = idx + 1
        return {"success": True, "position": new_position}

    async def remove_task(self, task_id: str) -> bool:
        if task_id not in self._positions:
            return False

        items = []
        found = False
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                if item[1] == task_id:
                    found = True
                else:
                    items.append(item)
            except asyncio.QueueEmpty:
                break

        for item in items:
            self._queue.put_nowait(item)

        self._positions.pop(task_id, None)
        self._task_index.pop(task_id, None)
        for idx, key in enumerate(self._task_index):
            self._task_index[key] = idx
        return found

    def get_queue_position(self, task_id: str) -> Optional[int]:
        return self._positions.get(task_id)

    def is_queue_full(self) -> bool:
        return self._queue.full()


class RatioStrategy(TaskDispatchStrategy):
    def __init__(
        self,
        small_ratio: float = 0.4,
        large_ratio: float = 0.6,
        file_threshold_bytes: int = 5 * 1024 * 1024,
        max_queue_size: int = 100,
        queue_timeout: float = 5.0,
    ):
        small_capacity = int(max_queue_size * small_ratio)
        large_capacity = max_queue_size - small_capacity

        self._small_queue: asyncio.Queue = asyncio.Queue(maxsize=small_capacity)
        self._large_queue: asyncio.Queue = asyncio.Queue(maxsize=large_capacity)

        self._small_counter = 0
        self._large_counter = 0

        self._small_positions: dict[str, int] = {}
        self._large_positions: dict[str, int] = {}

        self.small_ratio = small_ratio
        self.large_ratio = large_ratio
        self.file_threshold_bytes = file_threshold_bytes
        self.max_queue_size = max_queue_size
        self.queue_timeout = queue_timeout

    @property
    def strategy_name(self) -> str:
        return "ratio"

    def _get_queue_for_task(self, task_content: bytes = None, source_path: str = None):
        file_size = 0
        if task_content is not None:
            file_size = len(task_content)
        elif source_path is not None:
            import os
            file_size = os.path.getsize(source_path)

        if file_size < self.file_threshold_bytes:
            return self._small_queue, self._small_positions, "_small_counter"
        return self._large_queue, self._large_positions, "_large_counter"

    async def enqueue(self, task_id: str, task_content: Union[bytes, str, None], filename: str, options: dict) -> QueueResult:
        source_path = None
        if isinstance(task_content, str):
            source_path = task_content
            task_content = None

        queue, positions, counter_name = self._get_queue_for_task(task_content, source_path)

        global_counter = getattr(self, counter_name) + 1
        setattr(self, counter_name, global_counter)
        position = global_counter
        positions[task_id] = position

        try:
            await asyncio.wait_for(
                queue.put((position, task_id, source_path, filename, options)),
                timeout=self.queue_timeout,
            )
            file_size = len(task_content) if task_content else (os.path.getsize(source_path) if source_path else 0)
            channel = "small" if file_size < self.file_threshold_bytes else "large"
            return QueueResult(
                accepted=True,
                task_id=task_id,
                position=queue.qsize(),
                message=f"Task queued in {channel} queue",
            )
        except asyncio.TimeoutError:
            positions.pop(task_id, None)
            return QueueResult(
                accepted=False,
                task_id=task_id,
                message="Queue is full, try again later",
            )

    async def dequeue(self) -> Optional[QueueItem]:
        try:
            position, task_id, source_path, filename, options = await asyncio.wait_for(
                self._small_queue.get(), timeout=0.05
            )
            self._small_positions.pop(task_id, None)
            return QueueItem(task_id=task_id, source_path=source_path, filename=filename, options=options)
        except asyncio.TimeoutError:
            pass

        try:
            position, task_id, source_path, filename, options = await asyncio.wait_for(
                self._large_queue.get(), timeout=0.05
            )
            self._large_positions.pop(task_id, None)
            return QueueItem(task_id=task_id, source_path=source_path, filename=filename, options=options)
        except asyncio.TimeoutError:
            return None

    def get_stats(self) -> dict:
        small_pending = self._small_queue.qsize()
        large_pending = self._large_queue.qsize()
        small_capacity = self._small_queue.maxsize
        large_capacity = self._large_queue.maxsize
        return {
            "strategy": "ratio",
            "small_queue": {
                "pending": small_pending,
                "capacity": small_capacity,
                "utilization": round(small_pending / small_capacity, 4) if small_capacity > 0 else 0,
            },
            "large_queue": {
                "pending": large_pending,
                "capacity": large_capacity,
                "utilization": round(large_pending / large_capacity, 4) if large_capacity > 0 else 0,
            },
            "ratio": {
                "small": self.small_ratio,
                "large": self.large_ratio,
            },
        }

    async def promote_task(self, task_id: str) -> dict:
        positions = None
        target_queue = None

        if task_id in self._small_positions:
            positions = self._small_positions
            target_queue = self._small_queue
        elif task_id in self._large_positions:
            positions = self._large_positions
            target_queue = self._large_queue
        else:
            return {"success": False, "error": "Task not found in queue"}

        items = []
        task_item = None
        while not target_queue.empty():
            try:
                item = target_queue.get_nowait()
                if item[1] == task_id:
                    task_item = item
                else:
                    items.append(item)
            except asyncio.QueueEmpty:
                break

        if task_item is None:
            return {"success": False, "error": "Task not found in queue"}

        new_position = 0
        target_queue.put_nowait((new_position, task_id, task_item[2], task_item[3], task_item[4]))

        for idx, item in enumerate(items):
            target_queue.put_nowait((idx + 1, item[1], item[2], item[3], item[4]))

        positions[task_id] = new_position
        return {"success": True, "position": new_position}

    async def remove_task(self, task_id: str) -> bool:
        found = False
        items = []

        if task_id in self._small_positions:
            items = []
            while not self._small_queue.empty():
                try:
                    item = self._small_queue.get_nowait()
                    if item[1] == task_id:
                        found = True
                    else:
                        items.append(item)
                except asyncio.QueueEmpty:
                    break
            for item in items:
                self._small_queue.put_nowait(item)
            self._small_positions.pop(task_id, None)
            return found

        if task_id in self._large_positions:
            items = []
            while not self._large_queue.empty():
                try:
                    item = self._large_queue.get_nowait()
                    if item[1] == task_id:
                        found = True
                    else:
                        items.append(item)
                except asyncio.QueueEmpty:
                    break
            for item in items:
                self._large_queue.put_nowait(item)
            self._large_positions.pop(task_id, None)
            return found

        return False

    async def set_ratios(self, small_ratio: float, large_ratio: float) -> dict:
        if abs(small_ratio + large_ratio - 1.0) > 0.001:
            return {"success": False, "error": "Ratios must sum to 1.0"}
        if not (0 < small_ratio < 1.0 and 0 < large_ratio < 1.0):
            return {"success": False, "error": "Ratios must be between 0 and 1"}

        old_small = self.small_ratio
        old_large = self.large_ratio
        self.small_ratio = small_ratio
        self.large_ratio = large_ratio

        return {
            "success": True,
            "previous_ratios": {"small": old_small, "large": old_large},
            "current_ratios": {"small": small_ratio, "large": large_ratio},
        }

    def get_queue_position(self, task_id: str) -> Optional[int]:
        if task_id in self._small_positions:
            return self._small_positions[task_id]
        if task_id in self._large_positions:
            return self._large_positions[task_id]
        return None

    def is_queue_full(self) -> bool:
        return self._small_queue.full() and self._large_queue.full()


class TaskDispatchStrategyFactory:
    @staticmethod
    def create(strategy_type: str = "fifo", **kwargs) -> TaskDispatchStrategy:
        if strategy_type == "fifo":
            return FifoStrategy(
                max_queue_size=kwargs.get("max_queue_size", 100),
                queue_timeout=kwargs.get("queue_timeout", 5.0),
            )
        elif strategy_type == "ratio":
            return RatioStrategy(
                small_ratio=kwargs.get("small_ratio", 0.4),
                large_ratio=kwargs.get("large_ratio", 0.6),
                file_threshold_bytes=kwargs.get("file_threshold_bytes", 5 * 1024 * 1024),
                max_queue_size=kwargs.get("max_queue_size", 100),
                queue_timeout=kwargs.get("queue_timeout", 5.0),
            )
        else:
            raise ValueError(f"Unknown strategy type: {strategy_type}")
