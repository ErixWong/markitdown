"""
Tests for TaskStore functionality.
"""

import base64
import os
import tempfile
from pathlib import Path

import pytest

from markitdown_ocr_mcp._task_store import TaskStore


@pytest.fixture
def temp_storage():
    """Create temporary storage directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def task_store(temp_storage):
    """Create TaskStore instance with temporary storage."""
    return TaskStore(temp_storage)


class TestTaskStore:
    """Tests for TaskStore class."""
    
    def test_init_creates_database(self, task_store):
        """Test that TaskStore creates database on init."""
        db_path = Path(task_store.db_path)
        assert db_path.exists()
    
    def test_generate_task_id(self, task_store):
        """Test task ID generation."""
        task_id = task_store.generate_task_id()
        assert task_id.startswith("task_")
        assert len(task_id) == 17  # "task_" + 12 hex chars
    
    def test_create_task(self, task_store):
        """Test task creation."""
        task_id = task_store.generate_task_id()
        content = b"test file content"
        filename = "test.txt"
        options = {"enable_ocr": False}
        
        source_path = task_store.create_task(task_id, content, filename, options)
        
        assert Path(source_path).exists()
        assert task_id in source_path
        
        # Verify task in database
        task = task_store.get_task(task_id)
        assert task is not None
        assert task.task_id == task_id
        assert task.status == "pending"
        assert task.progress == 0
    
    def test_create_task_from_base64(self, task_store):
        """Test task creation from Base64 content."""
        content = base64.b64encode(b"test content").decode()
        filename = "test.txt"
        options = {}
        
        task_id = task_store.create_task_from_base64(content, filename, options)
        
        assert task_id.startswith("task_")
        task = task_store.get_task(task_id)
        assert task is not None
    
    def test_update_progress(self, task_store):
        """Test progress update."""
        task_id = task_store.create_task_from_base64(
            base64.b64encode(b"content").decode(),
            "test.txt",
            {}
        )
        
        task_store.update_progress(task_id, 50, "Processing...")
        
        task = task_store.get_task(task_id)
        assert task.progress == 50
        assert task.message == "Processing..."
        assert task.status == "processing"
    
    def test_complete_task(self, task_store):
        """Test task completion."""
        task_id = task_store.create_task_from_base64(
            base64.b64encode(b"content").decode(),
            "test.txt",
            {}
        )
        
        result_content = "# Test Result\n\nThis is the converted content."
        task_store.complete_task(task_id, result_content)
        
        task = task_store.get_task(task_id)
        assert task.status == "completed"
        assert task.progress == 100
        assert task.result_path is not None
        
        # Verify result file
        result = task_store.get_result(task_id)
        assert result == result_content
    
    def test_fail_task(self, task_store):
        """Test task failure."""
        task_id = task_store.create_task_from_base64(
            base64.b64encode(b"content").decode(),
            "test.txt",
            {}
        )
        
        task_store.fail_task(task_id, "Test error message")
        
        task = task_store.get_task(task_id)
        assert task.status == "failed"
        assert task.error_message == "Test error message"
    
    def test_cancel_task(self, task_store):
        """Test task cancellation."""
        task_id = task_store.create_task_from_base64(
            base64.b64encode(b"content").decode(),
            "test.txt",
            {}
        )
        
        result = task_store.cancel_task(task_id)
        assert result is True
        
        task = task_store.get_task(task_id)
        assert task.status == "cancelled"
    
    def test_cancel_completed_task(self, task_store):
        """Test that completed tasks cannot be cancelled."""
        task_id = task_store.create_task_from_base64(
            base64.b64encode(b"content").decode(),
            "test.txt",
            {}
        )
        
        task_store.complete_task(task_id, "result")
        
        result = task_store.cancel_task(task_id)
        assert result is False
        
        task = task_store.get_task(task_id)
        assert task.status == "completed"
    
    def test_get_task_status(self, task_store):
        """Test task status retrieval."""
        task_id = task_store.create_task_from_base64(
            base64.b64encode(b"content").decode(),
            "test.txt",
            {}
        )
        
        task_store.update_progress(task_id, 30, "Processing page 3")
        
        status = task_store.get_task_status(task_id)
        
        assert status["task_id"] == task_id
        assert status["status"] == "processing"
        assert status["progress"] == 30
        assert status["message"] == "Processing page 3"
    
    def test_get_task_status_not_found(self, task_store):
        """Test status for non-existent task."""
        status = task_store.get_task_status("nonexistent_task")
        assert "error" in status
    
    def test_list_tasks(self, task_store):
        """Test task listing."""
        # Create multiple tasks
        for i in range(5):
            task_store.create_task_from_base64(
                base64.b64encode(f"content {i}".encode()).decode(),
                f"test{i}.txt",
                {}
            )
        
        tasks = task_store.list_tasks(limit=10)
        assert len(tasks) == 5
    
    def test_list_tasks_with_status_filter(self, task_store):
        """Test task listing with status filter."""
        # Create tasks with different statuses
        task_id1 = task_store.create_task_from_base64(
            base64.b64encode(b"content").decode(),
            "test1.txt",
            {}
        )
        task_id2 = task_store.create_task_from_base64(
            base64.b64encode(b"content").decode(),
            "test2.txt",
            {}
        )
        
        task_store.complete_task(task_id1, "result")
        task_store.update_progress(task_id2, 50, "Processing")
        
        completed_tasks = task_store.list_tasks(status="completed", limit=10)
        assert len(completed_tasks) == 1
        assert completed_tasks[0]["task_id"] == task_id1
        
        processing_tasks = task_store.list_tasks(status="processing", limit=10)
        assert len(processing_tasks) == 1
        assert processing_tasks[0]["task_id"] == task_id2
    
    def test_date_based_storage_path(self, task_store):
        """Test that storage uses date-based directory structure."""
        task_id = task_store.create_task_from_base64(
            base64.b64encode(b"content").decode(),
            "test.txt",
            {}
        )
        
        task = task_store.get_task(task_id)
        source_path = Path(task.source_path)
        
        # Check path structure: year/month/day
        assert source_path.parent.parent.parent.name.isdigit()  # year
        assert source_path.parent.parent.name.isdigit()  # month
        assert source_path.parent.name.isdigit()  # day