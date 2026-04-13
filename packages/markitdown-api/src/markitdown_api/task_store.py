# SPDX-FileCopyrightText: 2024-present Microsoft Corporation
#
# SPDX-License-Identifier: MIT
"""
Task storage module for managing conversion tasks.

Provides SQLite-based persistence for task state and results.
"""

import base64
import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

from .models import TaskStatus


@dataclass
class Task:
    """Task data structure."""
    task_id: str
    filename: str
    content: bytes  # Original file content
    options: dict = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    message: str = "Task created"
    result: Optional[str] = None  # Markdown result
    error: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class TaskStore:
    """
    SQLite-based task storage.
    
    Manages task lifecycle and persistence.
    """
    
    def __init__(self, storage_dir: str = "./storage"):
        """Initialize task store with storage directory."""
        self.storage_dir = storage_dir
        self._lock = threading.Lock()
        self._local = threading.local()
        
        # Ensure storage directory exists
        os.makedirs(storage_dir, exist_ok=True)
        
        # Initialize database
        self._init_db()
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            db_path = os.path.join(self.storage_dir, "tasks.db")
            self._local.conn = sqlite3.connect(db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn
    
    def _init_db(self):
        """Initialize database schema."""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                source_path TEXT,
                result_path TEXT,
                options TEXT,
                status TEXT NOT NULL,
                progress INTEGER DEFAULT 0,
                message TEXT,
                result TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at)
        """)
        
        conn.commit()
    
    def generate_task_id(self) -> str:
        """Generate unique task ID."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        random_hash = hashlib.md5(os.urandom(16)).hexdigest()[:8]
        return f"task_{timestamp}_{random_hash}"
    
    def create_task(
        self,
        task_id: str,
        content: bytes,
        filename: str,
        options: dict = None
    ) -> Task:
        """
        Create a new task.
        
        Args:
            task_id: Unique task identifier
            content: File content as bytes
            filename: Original filename
            options: Conversion options
            
        Returns:
            Created Task object
        """
        options = options or {}
        
        task = Task(
            task_id=task_id,
            filename=filename,
            content=content,
            options=options,
            status=TaskStatus.PENDING,
            progress=0,
            message="Task created",
        )
        
        # Save file content to disk and get path
        source_path = self._save_file_content(task_id, content, filename)
        
        # Save to database with source_path
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO tasks (task_id, filename, source_path, options, status, progress, message, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task.task_id,
                task.filename,
                source_path,
                json.dumps(task.options),
                task.status.value,
                task.progress,
                task.message,
                task.created_at.isoformat(),
                task.updated_at.isoformat(),
            ))
            
            conn.commit()
        
        return task
    
    def create_task_from_base64(
        self,
        content_b64: str,
        filename: str,
        options: dict = None
    ) -> str:
        """
        Create task from Base64 encoded content.
        
        Args:
            content_b64: Base64 encoded file content
            filename: Original filename
            options: Conversion options
            
        Returns:
            Task ID
        """
        content = base64.b64decode(content_b64)
        task_id = self.generate_task_id()
        self.create_task(task_id, content, filename, options)
        return task_id
    
    def _save_file_content(self, task_id: str, content: bytes, filename: str) -> str:
        """Save file content to disk and return the path."""
        # Create date-based directory structure
        now = datetime.now(timezone.utc)
        date_dir = os.path.join(
            self.storage_dir,
            str(now.year),
            f"{now.month:02d}",
            f"{now.day:02d}"
        )
        os.makedirs(date_dir, exist_ok=True)
        
        # Save source file
        source_path = os.path.join(date_dir, f"{task_id}_source_{filename}")
        with open(source_path, 'wb') as f:
            f.write(content)
        
        return source_path
    
    def _save_result(self, task_id: str, result: str):
        """Save conversion result to disk."""
        now = datetime.now(timezone.utc)
        date_dir = os.path.join(
            self.storage_dir,
            str(now.year),
            f"{now.month:02d}",
            f"{now.day:02d}"
        )
        os.makedirs(date_dir, exist_ok=True)
        
        result_path = os.path.join(date_dir, f"{task_id}_result.md")
        with open(result_path, 'w', encoding='utf-8') as f:
            f.write(result)
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT task_id, filename, source_path, options, status, progress, message, result, error, created_at, updated_at
                FROM tasks WHERE task_id = ?
            """, (task_id,))
            
            row = cursor.fetchone()
            
            if row is None:
                return None
            
            # Load content from disk using stored path
            content = self._load_file_content_from_path(row['source_path'])
            
            return Task(
                task_id=row['task_id'],
                filename=row['filename'],
                content=content,
                options=json.loads(row['options']) if row['options'] else {},
                status=TaskStatus(row['status']),
                progress=row['progress'],
                message=row['message'],
                result=row['result'],
                error=row['error'],
                created_at=datetime.fromisoformat(row['created_at']),
                updated_at=datetime.fromisoformat(row['updated_at']),
            )
    
    def _load_file_content_from_path(self, source_path: Optional[str]) -> bytes:
        """Load file content from stored path."""
        if source_path and os.path.exists(source_path):
            with open(source_path, 'rb') as f:
                return f.read()
        return b""
    
    def get_task_status(self, task_id: str) -> dict:
        """Get task status as dictionary."""
        task = self.get_task(task_id)
        if task is None:
            return {
                "task_id": task_id,
                "status": "not_found",
                "progress": -1,
                "message": "Task not found",
                "created_at": None,
                "updated_at": None,
            }
        
        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "progress": task.progress,
            "message": task.message,
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
        }
    
    def update_task(
        self,
        task_id: str,
        status: TaskStatus = None,
        progress: int = None,
        message: str = None,
        result: str = None,
        error: str = None
    ) -> bool:
        """
        Update task state.
        
        Args:
            task_id: Task ID to update
            status: New status (optional)
            progress: New progress (optional)
            message: New message (optional)
            result: Conversion result (optional)
            error: Error message (optional)
            
        Returns:
            True if updated, False if task not found
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # Check if task exists
            cursor.execute("SELECT task_id FROM tasks WHERE task_id = ?", (task_id,))
            if cursor.fetchone() is None:
                return False
            
            # Build update query
            updates = []
            values = []
            
            if status is not None:
                updates.append("status = ?")
                values.append(status.value)
            
            if progress is not None:
                updates.append("progress = ?")
                values.append(progress)
            
            if message is not None:
                updates.append("message = ?")
                values.append(message)
            
            if result is not None:
                updates.append("result = ?")
                values.append(result)
                self._save_result(task_id, result)
            
            if error is not None:
                updates.append("error = ?")
                values.append(error)
            
            updates.append("updated_at = ?")
            values.append(datetime.now(timezone.utc).isoformat())
            
            values.append(task_id)
            
            cursor.execute(
                f"UPDATE tasks SET {', '.join(updates)} WHERE task_id = ?",
                values
            )
            
            conn.commit()
            return True
    
    def get_result(self, task_id: str) -> Optional[str]:
        """Get conversion result for completed task."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT result, status FROM tasks WHERE task_id = ?
            """, (task_id,))
            
            row = cursor.fetchone()
            
            if row is None:
                return None
            
            if row['status'] != 'completed':
                return None
            
            return row['result']
    
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task."""
        task = self.get_task(task_id)
        if task is None:
            return False
        
        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return False
        
        return self.update_task(
            task_id,
            status=TaskStatus.CANCELLED,
            progress=-1,
            message="Task cancelled"
        )
    
    def list_tasks(self, status: str = None, limit: int = 10) -> list[dict]:
        """List tasks with optional status filter."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            if status:
                cursor.execute("""
                    SELECT task_id, filename, status, progress, created_at, updated_at
                    FROM tasks WHERE status = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (status, limit))
            else:
                cursor.execute("""
                    SELECT task_id, filename, status, progress, created_at, updated_at
                    FROM tasks
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,))
            
            rows = cursor.fetchall()
            
            return [
                {
                    "task_id": row['task_id'],
                    "filename": row['filename'],
                    "status": row['status'],
                    "progress": row['progress'],
                    "created_at": row['created_at'],
                    "updated_at": row['updated_at'],
                }
                for row in rows
            ]
    
    def delete_task(self, task_id: str) -> bool:
        """Delete a task and its files."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            cursor.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
        
        # Delete files
        # (Implementation would search and delete files from storage)
        
        return deleted


# Global task store instance
_task_store: Optional[TaskStore] = None


def get_task_store() -> TaskStore:
    """Get or create global TaskStore instance."""
    global _task_store
    if _task_store is None:
        storage_dir = os.getenv("MARKITDOWN_STORAGE_DIR", "./storage")
        _task_store = TaskStore(storage_dir)
    return _task_store