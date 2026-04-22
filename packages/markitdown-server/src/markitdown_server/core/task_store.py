import base64
import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .models import TaskStatus


@dataclass
class Task:
    task_id: str
    filename: str
    content: bytes
    options: dict = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    message: str = "Task created"
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_path: Optional[str] = None
    result_path: Optional[str] = None


class TaskStore:
    def __init__(self, storage_dir: str = "./storage"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.storage_dir / "tasks.db")
        self._lock = threading.Lock()
        self._local = threading.local()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self):
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
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at)")
        conn.commit()

    def _get_date_path(self) -> Path:
        now = datetime.now(timezone.utc)
        path = self.storage_dir / str(now.year) / f"{now.month:02d}" / f"{now.day:02d}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def generate_task_id(self) -> str:
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
        options = options or {}
        date_path = self._get_date_path()
        source_path = str(date_path / f"{task_id}_source_{filename}")
        
        with open(source_path, 'wb') as f:
            f.write(content)
        
        task = Task(
            task_id=task_id,
            filename=filename,
            content=content,
            options=options,
            status=TaskStatus.PENDING,
            source_path=source_path,
        )
        
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tasks (task_id, filename, source_path, options, status, progress, message, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task.task_id,
                task.filename,
                task.source_path,
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
        content = base64.b64decode(content_b64)
        task_id = self.generate_task_id()
        self.create_task(task_id, content, filename, options)
        return task_id

    def get_task(self, task_id: str) -> Optional[Task]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT task_id, filename, source_path, options, status, progress, message, result, error, created_at, updated_at, result_path
                FROM tasks WHERE task_id = ?
            """, (task_id,))
            row = cursor.fetchone()
            
            if row is None:
                return None
            
            content = b""
            if row['source_path'] and os.path.exists(row['source_path']):
                with open(row['source_path'], 'rb') as f:
                    content = f.read()
            
            return Task(
                task_id=row['task_id'],
                filename=row['filename'],
                content=content,
                options=json.loads(row['options']) if row['options'] else {},
                status=TaskStatus(row['status']),
                progress=row['progress'],
                message=row['message'] or "",
                result=row['result'],
                error=row['error'],
                created_at=datetime.fromisoformat(row['created_at']),
                updated_at=datetime.fromisoformat(row['updated_at']),
                source_path=row['source_path'],
                result_path=row['result_path'],
            )

    def get_task_status(self, task_id: str) -> dict:
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
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT task_id FROM tasks WHERE task_id = ?", (task_id,))
            if cursor.fetchone() is None:
                return False
            
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
                date_path = self._get_date_path()
                result_path = str(date_path / f"{task_id}_result.md")
                with open(result_path, 'w', encoding='utf-8') as f:
                    f.write(result)
                updates.append("result_path = ?")
                values.append(result_path)
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

    def update_progress(self, task_id: str, progress: int, message: str):
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE tasks SET status = ?, progress = ?, message = ?, updated_at = ?
                WHERE task_id = ?
            """, (TaskStatus.PROCESSING.value, progress, message, datetime.now(timezone.utc).isoformat(), task_id))
            conn.commit()

    def complete_task(self, task_id: str, result: str):
        self.update_task(task_id, status=TaskStatus.COMPLETED, progress=100, message="Conversion completed", result=result)

    def fail_task(self, task_id: str, error: str):
        self.update_task(task_id, status=TaskStatus.FAILED, progress=-1, message=error, error=error)

    def get_result(self, task_id: str) -> Optional[str]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT result, status, result_path FROM tasks WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            if row is None:
                return None
            if row['status'] != 'completed':
                return None
            if row['result']:
                return row['result']
            if row['result_path'] and os.path.exists(row['result_path']):
                with open(row['result_path'], 'r', encoding='utf-8') as f:
                    return f.read()
            return None

    def cancel_task(self, task_id: str) -> bool:
        task = self.get_task(task_id)
        if task is None:
            return False
        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return False
        return self.update_task(task_id, status=TaskStatus.CANCELLED, progress=-1, message="Task cancelled")

    def list_tasks(self, status: str = None, limit: int = 10) -> list[dict]:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            if status:
                cursor.execute("""
                    SELECT task_id, filename, status, progress, message, created_at, updated_at
                    FROM tasks WHERE status = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (status, limit))
            else:
                cursor.execute("""
                    SELECT task_id, filename, status, progress, message, created_at, updated_at
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
                    "message": row['message'] or "",
                    "created_at": row['created_at'],
                    "updated_at": row['updated_at'],
                }
                for row in rows
            ]

    def delete_task(self, task_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT source_path, result_path FROM tasks WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            if row:
                if row['source_path']:
                    Path(row['source_path']).unlink(missing_ok=True)
                if row['result_path']:
                    Path(row['result_path']).unlink(missing_ok=True)
            cursor.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted


_task_store: Optional[TaskStore] = None


def get_task_store() -> TaskStore:
    global _task_store
    if _task_store is None:
        storage_dir = os.getenv("MARKITDOWN_STORAGE_DIR", "./storage")
        _task_store = TaskStore(storage_dir)
    return _task_store