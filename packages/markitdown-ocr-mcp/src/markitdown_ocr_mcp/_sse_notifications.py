"""
SSE Notification Service: Real-time task notifications via Server-Sent Events.

Provides:
- Task progress notifications
- Task completion notifications
- Client subscription management
"""

import asyncio
import json
import logging
from typing import Optional
from collections.abc import AsyncIterator

# Configure logging
logger = logging.getLogger(__name__)


class SSENotificationService:
    """
    SSE notification service for real-time task updates.
    
    Manages client subscriptions and broadcasts task events.
    """
    
    # Heartbeat interval in seconds
    HEARTBEAT_INTERVAL = 30
    
    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._all_subscribers: list[asyncio.Queue] = []
    
    def subscribe(self, task_id: Optional[str] = None) -> asyncio.Queue:
        """
        Subscribe to task notifications.
        
        Args:
            task_id: Optional task ID to subscribe to specific task.
                     If None, subscribes to all task notifications.
        
        Returns:
            asyncio.Queue to receive notifications
        """
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
        """
        Unsubscribe from notifications.
        
        Args:
            queue: Queue to unsubscribe
            task_id: Optional task ID if subscribed to specific task
        """
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
        """
        Send progress notification.
        
        Args:
            task_id: Task ID
            progress: Progress percentage (0-100)
            message: Progress message
        """
        logger.debug(f"SSE progress: task={task_id} progress={progress}% msg={message}")
        
        event_data = {
            "event": "task_progress",
            "data": {
                "task_id": task_id,
                "progress": progress,
                "message": message,
            }
        }
        await self._broadcast(event_data, task_id)
    
    async def notify_completed(self, task_id: str):
        """
        Send completion notification.
        
        Args:
            task_id: Task ID
        """
        logger.info(f"SSE notification: task {task_id} completed")
        
        event_data = {
            "event": "task_completed",
            "data": {
                "task_id": task_id,
                "status": "completed",
                "progress": 100,
            }
        }
        await self._broadcast(event_data, task_id)
    
    async def notify_failed(self, task_id: str, error: str):
        """
        Send failure notification.
        
        Args:
            task_id: Task ID
            error: Error message
        """
        logger.error(f"SSE notification: task {task_id} failed - {error}")
        
        event_data = {
            "event": "task_failed",
            "data": {
                "task_id": task_id,
                "status": "failed",
                "error": error,
            }
        }
        await self._broadcast(event_data, task_id)
    
    async def notify_cancelled(self, task_id: str):
        """
        Send cancellation notification.
        
        Args:
            task_id: Task ID
        """
        logger.info(f"SSE notification: task {task_id} cancelled")
        
        event_data = {
            "event": "task_cancelled",
            "data": {
                "task_id": task_id,
                "status": "cancelled",
            }
        }
        await self._broadcast(event_data, task_id)
    
    async def _broadcast(self, event_data: dict, task_id: str):
        """
        Broadcast event to subscribers.
        
        Args:
            event_data: Event data dictionary
            task_id: Task ID for targeted subscribers
        """
        event = event_data.get("event", "unknown")
        subscriber_count = 0
        
        # Send to task-specific subscribers
        if task_id in self._subscribers:
            for queue in self._subscribers[task_id]:
                try:
                    await queue.put(event_data)
                    subscriber_count += 1
                except asyncio.QueueFull:
                    logger.warning(f"Queue full for task {task_id} subscriber")
        
        # Send to all-task subscribers
        for queue in self._all_subscribers:
            try:
                await queue.put(event_data)
                subscriber_count += 1
            except asyncio.QueueFull:
                logger.warning(f"Queue full for all-tasks subscriber")
        
        logger.debug(f"SSE broadcast: event={event} task={task_id} subscribers={subscriber_count}")
    
    async def event_stream(self, task_id: Optional[str] = None) -> AsyncIterator[str]:
        """
        Generate SSE event stream with heartbeat.
        
        Args:
            task_id: Optional task ID to filter events
        
        Yields:
            SSE formatted strings
        """
        queue = self.subscribe(task_id)
        
        try:
            while True:
                try:
                    # Wait for event with timeout for heartbeat
                    event_data = await asyncio.wait_for(
                        queue.get(), 
                        timeout=self.HEARTBEAT_INTERVAL
                    )
                    
                    # Format as SSE
                    event = event_data.get("event", "message")
                    data = json.dumps(event_data.get("data", {}))
                    
                    yield f"event: {event}\n"
                    yield f"data: {data}\n\n"
                    
                    # Stop streaming after completion/failure/cancellation
                    if event in ("task_completed", "task_failed", "task_cancelled"):
                        break
                        
                except asyncio.TimeoutError:
                    # Send heartbeat to keep connection alive
                    yield ": heartbeat\n\n"
        finally:
            self.unsubscribe(queue, task_id)


# Global notification service instance
_notification_service: Optional[SSENotificationService] = None


def get_notification_service() -> SSENotificationService:
    """Get or create global notification service."""
    global _notification_service
    if _notification_service is None:
        _notification_service = SSENotificationService()
    return _notification_service