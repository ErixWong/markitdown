"""
Task Store: SQLite-based task management and storage.

Provides:
- Task creation and status tracking
- Progress updates
- Result storage
- File storage with date-based directory structure
"""

import base64
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass
import uuid


@dataclass
class TaskInfo:
    """Task information structure."""
    task_id: str
    status: str  # pending, processing, completed, failed, cancelled
    progress: int  # 0-100
    message: str
    created_at: datetime
    updated_at: datetime
    source_path: Optional[str]
    result_path: Optional[str]
    options: dict
    error_message: Optional[str]


class TaskStore:
    """
    SQLite-based task storage with file management.
    
    Directory structure:
        storage/
        ├── 2026/
        │   ├── 04/
        │   │   ├── 10/
        │   │   │   ├── task_abc123_source.pdf
        │   │   │   ├── task_abc123_result.md
        │   │   │   └── ...
        ├── tasks.db
    """
    
    def __init__(self, storage_dir: str = "./storage"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.storage_dir / "tasks.db")
        self._init_db()
    
    def _init_db(self):
        """Initialize SQLite database with task table."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    status TEXT DEFAULT 'pending',
                    progress INTEGER DEFAULT 0,
                    message TEXT,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP,
                    source_path TEXT,
                    result_path TEXT,
                    options_json TEXT,
                    error_message TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_created ON tasks(created_at)")
            conn.commit()
    
    def _get_date_path(self) -> Path:
        """Get storage path organized by date (year/month/day)."""
        now = datetime.now()
        path = self.storage_dir / str(now.year) / f"{now.month:02d}" / f"{now.day:02d}"
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def generate_task_id(self) -> str:
        """Generate a unique task ID."""
        return f"task_{uuid.uuid4().hex[:12]}"
    
    def create_task(
        self,
        task_id: str,
        source_content: bytes,
        filename: str,
        options: dict
    ) -> str:
        """
        Create a new task and save source file.
        
        Args:
            task_id: Unique task identifier
            source_content: Raw file content (bytes)
            filename: Original filename
            options: Task options (ocr_enabled, etc.)
        
        Returns:
            Path to saved source file
        """
        date_path = self._get_date_path()
        source_path = str(date_path / f"{task_id}_source_{filename}")
        
        # Save source file
        with open(source_path, 'wb') as f:
            f.write(source_content)
        
        # Create database record
        now = datetime.now()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO tasks (task_id, source_path, options_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (task_id, source_path, json.dumps(options), now, now))
            conn.commit()
        
        return source_path
    
    def create_task_from_base64(
        self,
        content: str,
        filename: str,
        options: dict
    ) -> str:
        """
        Create a new task from Base64 encoded content.
        
        Args:
            content: Base64 encoded file content
            filename: Original filename
            options: Task options
        
        Returns:
            Task ID
        """
        task_id = self.generate_task_id()
        source_content = base64.b64decode(content)
        self.create_task(task_id, source_content, filename, options)
        return task_id
    
    def update_progress(self, task_id: str, progress: int, message: str):
        """Update task progress and message."""
        now = datetime.now()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE tasks 
                SET progress=?, message=?, updated_at=?, status='processing'
                WHERE task_id=?
            """, (progress, message, now, task_id))
            conn.commit()
    
    def complete_task(self, task_id: str, result_content: str):
        """Mark task as completed and save result."""
        date_path = self._get_date_path()
        result_path = str(date_path / f"{task_id}_result.md")
        
        # Save result file
        with open(result_path, 'w', encoding='utf-8') as f:
            f.write(result_content)
        
        # Update database
        now = datetime.now()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE tasks 
                SET status='completed', progress=100, result_path=?, updated_at=?
                WHERE task_id=?
            """, (result_path, now, task_id))
            conn.commit()
    
    def fail_task(self, task_id: str, error_message: str):
        """Mark task as failed with error message."""
        now = datetime.now()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE tasks 
                SET status='failed', error_message=?, updated_at=?
                WHERE task_id=?
            """, (error_message, now, task_id))
            conn.commit()
    
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending or processing task."""
        now = datetime.now()
        with sqlite3.connect(self.db_path) as conn:
            result = conn.execute("""
                UPDATE tasks 
                SET status='cancelled', updated_at=?
                WHERE task_id=? AND status IN ('pending', 'processing')
            """, (now, task_id))
            conn.commit()
            return result.rowcount > 0
    
    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """Get task information by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            
            if row:
                return TaskInfo(
                    task_id=row["task_id"],
                    status=row["status"],
                    progress=row["progress"],
                    message=row["message"] or "",
                    created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(),
                    updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else datetime.now(),
                    source_path=row["source_path"],
                    result_path=row["result_path"],
                    options=json.loads(row["options_json"] or "{}"),
                    error_message=row["error_message"],
                )
        return None
    
    def get_task_status(self, task_id: str) -> dict:
        """Get task status as dictionary (for MCP tool response)."""
        task = self.get_task(task_id)
        if not task:
            return {"error": "Task not found"}
        
        return {
            "task_id": task.task_id,
            "status": task.status,
            "progress": task.progress,
            "message": task.message,
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
        }
    
    def get_result(self, task_id: str) -> Optional[str]:
        """Get conversion result (Markdown content)."""
        task = self.get_task(task_id)
        if task and task.status == "completed" and task.result_path:
            with open(task.result_path, 'r', encoding='utf-8') as f:
                return f.read()
        return None
    
    def list_tasks(self, status: str = "", limit: int = 10) -> list[dict]:
        """List tasks with optional status filter."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            if status:
                rows = conn.execute("""
                    SELECT task_id, status, progress, message, created_at, updated_at
                    FROM tasks WHERE status=? 
                    ORDER BY created_at DESC LIMIT ?
                """, (status, limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT task_id, status, progress, message, created_at, updated_at
                    FROM tasks 
                    ORDER BY created_at DESC LIMIT ?
                """, (limit,)).fetchall()
            
            return [
                {
                    "task_id": row["task_id"],
                    "status": row["status"],
                    "progress": row["progress"],
                    "message": row["message"] or "",
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                for row in rows
            ]
    
    def cleanup_old_tasks(self, days: int = 7):
        """Remove tasks and files older than specified days."""
        cutoff = datetime.now() - datetime.timedelta(days=days)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            old_tasks = conn.execute("""
                SELECT task_id, source_path, result_path 
                FROM tasks WHERE created_at < ?
            """, (cutoff.isoformat(),)).fetchall()
            
            # Delete files
            for task in old_tasks:
                if task["source_path"]:
                    Path(task["source_path"]).unlink(missing_ok=True)
                if task["result_path"]:
                    Path(task["result_path"]).unlink(missing_ok=True)
            
            # Delete database records
            conn.execute("DELETE FROM tasks WHERE created_at < ?", (cutoff.isoformat(),))
            conn.commit()