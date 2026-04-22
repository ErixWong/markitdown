import asyncio
import json
import logging
import os
from typing import Optional
from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


def get_heartbeat_interval() -> int:
    env_value = os.getenv("MARKITDOWN_SSE_HEARTBEAT", "30")
    try:
        return int(env_value)
    except ValueError:
        logger.warning(f"Invalid MARKITDOWN_SSE_HEARTBEAT value: {env_value}, using default 30")
        return 30


class SSENotificationService:
    def __init__(self):
        self._heartbeat_interval = get_heartbeat_interval()
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._all_subscribers: list[asyncio.Queue] = []

    def subscribe(self, task_id: Optional[str] = None) -> asyncio.Queue:
        queue = asyncio.Queue()
        if task_id:
            if task_id not in self._subscribers:
                self._subscribers[task_id] = []
            self._subscribers[task_id].append(queue)
            logger.info(f"SSE client subscribed to task {task_id}")
        else:
            self._all_subscribers.append(queue)
            logger.info(f"SSE client subscribed to all tasks")
        return queue

    def unsubscribe(self, queue: asyncio.Queue, task_id: Optional[str] = None):
        if task_id and task_id in self._subscribers:
            try:
                self._subscribers[task_id].remove(queue)
                if not self._subscribers[task_id]:
                    del self._subscribers[task_id]
                logger.info(f"SSE client unsubscribed from task {task_id}")
            except ValueError:
                pass
        else:
            try:
                self._all_subscribers.remove(queue)
                logger.info(f"SSE client unsubscribed from all tasks")
            except ValueError:
                pass

    async def notify_progress(self, task_id: str, progress: int, message: str):
        logger.debug(f"SSE progress: task={task_id} progress={progress}% msg={message}")
        event_data = {
            "event": "task_progress",
            "data": {
                "task_id": task_id,
                "status": "processing",
                "progress": progress,
                "message": message,
            }
        }
        await self._broadcast(event_data, task_id)

    async def notify_completed(self, task_id: str):
        logger.info(f"SSE notification: task {task_id} completed")
        event_data = {
            "event": "task_completed",
            "data": {
                "task_id": task_id,
                "status": "completed",
                "progress": 100,
                "message": "Conversion completed",
            }
        }
        await self._broadcast(event_data, task_id)

    async def notify_failed(self, task_id: str, error: str):
        logger.error(f"SSE notification: task {task_id} failed - {error}")
        event_data = {
            "event": "task_failed",
            "data": {
                "task_id": task_id,
                "status": "failed",
                "progress": -1,
                "message": error,
            }
        }
        await self._broadcast(event_data, task_id)

    async def notify_cancelled(self, task_id: str):
        logger.info(f"SSE notification: task {task_id} cancelled")
        event_data = {
            "event": "task_cancelled",
            "data": {
                "task_id": task_id,
                "status": "cancelled",
                "progress": -1,
                "message": "Task cancelled",
            }
        }
        await self._broadcast(event_data, task_id)

    async def _broadcast(self, event_data: dict, task_id: str):
        event = event_data.get("event", "unknown")
        subscriber_count = 0
        if task_id in self._subscribers:
            for queue in self._subscribers[task_id]:
                try:
                    await queue.put(event_data)
                    subscriber_count += 1
                except asyncio.QueueFull:
                    logger.warning(f"Queue full for task {task_id} subscriber")
        for queue in self._all_subscribers:
            try:
                await queue.put(event_data)
                subscriber_count += 1
            except asyncio.QueueFull:
                logger.warning(f"Queue full for all-tasks subscriber")
        logger.debug(f"SSE broadcast: event={event} task={task_id} subscribers={subscriber_count}")

    async def event_stream(self, task_id: Optional[str] = None) -> AsyncIterator[str]:
        queue = self.subscribe(task_id)
        try:
            while True:
                try:
                    event_data = await asyncio.wait_for(
                        queue.get(),
                        timeout=self._heartbeat_interval
                    )
                    event = event_data.get("event", "message")
                    data = json.dumps(event_data.get("data", {}))
                    yield f"event: {event}\n"
                    yield f"data: {data}\n\n"
                    if event in ("task_completed", "task_failed", "task_cancelled"):
                        break
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            self.unsubscribe(queue, task_id)


_notification_service: Optional[SSENotificationService] = None


def get_notification_service() -> SSENotificationService:
    global _notification_service
    if _notification_service is None:
        _notification_service = SSENotificationService()
    return _notification_service