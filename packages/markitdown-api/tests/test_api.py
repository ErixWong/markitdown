# SPDX-FileCopyrightText: 2024-present Microsoft Corporation
#
# SPDX-License-Identifier: MIT
"""
Tests for MarkItDown RESTful API.
"""

import io
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from markitdown_api.server import create_app
from markitdown_api.task_store import TaskStore, Task
from markitdown_api.models import TaskStatus


@pytest.fixture
def temp_storage():
    """Create temporary storage directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def task_store(temp_storage):
    """Create TaskStore with temporary storage."""
    return TaskStore(temp_storage)


@pytest.fixture
def client(temp_storage):
    """Create test client with temporary storage."""
    # Set storage directory
    os.environ["MARKITDOWN_STORAGE_DIR"] = temp_storage
    
    app = create_app()
    return TestClient(app)


class TestHealthEndpoints:
    """Tests for health check endpoints."""
    
    def test_root_endpoint(self, client):
        """Test root endpoint returns health status."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "uptime" in data
    
    def test_health_endpoint(self, client):
        """Test /health endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestFormatEndpoints:
    """Tests for supported formats endpoint."""
    
    def test_get_formats(self, client):
        """Test getting supported formats."""
        response = client.get("/formats")
        assert response.status_code == 200
        data = response.json()
        assert "formats" in data
        assert len(data["formats"]) > 0
        
        # Check PDF format
        pdf_format = next(f for f in data["formats"] if f["extension"] == ".pdf")
        assert pdf_format["ocr_support"] == True


class TestTaskEndpoints:
    """Tests for task management endpoints."""
    
    def test_submit_task_multipart(self, client):
        """Test submitting task with multipart upload."""
        # Create a simple test file
        test_content = b"Hello, World!"
        test_file = io.BytesIO(test_content)
        
        response = client.post(
            "/tasks",
            files={"file": ("test.txt", test_file, "text/plain")},
            data={"enable_ocr": "false"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "task_id" in data
        assert data["message"] == "Task submitted successfully"
    
    def test_submit_task_base64(self, client):
        """Test submitting task with Base64 content."""
        import base64
        
        test_content = b"Hello, World!"
        content_b64 = base64.b64encode(test_content).decode()
        
        response = client.post(
            "/tasks/base64",
            params={
                "content": content_b64,
                "filename": "test.txt",
                "enable_ocr": False
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "task_id" in data
    
    def test_get_task_status_not_found(self, client):
        """Test getting status for non-existent task."""
        response = client.get("/tasks/nonexistent_task_id")
        assert response.status_code == 404
    
    def test_list_tasks(self, client):
        """Test listing tasks."""
        response = client.get("/tasks")
        assert response.status_code == 200
        data = response.json()
        assert "tasks" in data
        assert "total" in data
    
    def test_list_tasks_with_status_filter(self, client):
        """Test listing tasks with status filter."""
        response = client.get("/tasks?status=completed")
        assert response.status_code == 200
        data = response.json()
        assert "tasks" in data


class TestDirectConversion:
    """Tests for direct conversion endpoint."""
    
    @patch('markitdown.MarkItDown')
    def test_convert_direct(self, mock_markitdown, client):
        """Test direct synchronous conversion."""
        # Mock MarkItDown
        mock_md = MagicMock()
        mock_result = MagicMock()
        mock_result.text_content = "# Test Markdown"
        mock_md.convert_stream.return_value = mock_result
        mock_markitdown.return_value = mock_md
        
        # Create test file
        test_content = b"Test content"
        test_file = io.BytesIO(test_content)
        
        response = client.post(
            "/convert",
            files={"file": ("test.txt", test_file, "text/plain")}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "markdown" in data


class TestTaskStore:
    """Tests for TaskStore class."""
    
    def test_create_task(self, task_store):
        """Test creating a task."""
        task_id = task_store.generate_task_id()
        content = b"Test content"
        
        task = task_store.create_task(task_id, content, "test.txt")
        
        assert task.task_id == task_id
        assert task.filename == "test.txt"
        assert task.status == TaskStatus.PENDING
    
    def test_get_task(self, task_store):
        """Test getting a task."""
        task_id = task_store.generate_task_id()
        content = b"Test content"
        
        task_store.create_task(task_id, content, "test.txt")
        retrieved = task_store.get_task(task_id)
        
        assert retrieved is not None
        assert retrieved.task_id == task_id
    
    def test_get_task_not_found(self, task_store):
        """Test getting non-existent task."""
        task = task_store.get_task("nonexistent")
        assert task is None
    
    def test_update_task(self, task_store):
        """Test updating task status."""
        task_id = task_store.generate_task_id()
        content = b"Test content"
        
        task_store.create_task(task_id, content, "test.txt")
        
        result = task_store.update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            message="Done",
            result="# Markdown"
        )
        
        assert result == True
        
        task = task_store.get_task(task_id)
        assert task.status == TaskStatus.COMPLETED
        assert task.progress == 100
    
    def test_cancel_task(self, task_store):
        """Test cancelling a task."""
        task_id = task_store.generate_task_id()
        content = b"Test content"
        
        task_store.create_task(task_id, content, "test.txt")
        
        result = task_store.cancel_task(task_id)
        assert result == True
        
        task = task_store.get_task(task_id)
        assert task.status == TaskStatus.CANCELLED
    
    def test_cancel_completed_task(self, task_store):
        """Test cancelling a completed task (should fail)."""
        task_id = task_store.generate_task_id()
        content = b"Test content"
        
        task_store.create_task(task_id, content, "test.txt")
        task_store.update_task(task_id, status=TaskStatus.COMPLETED, progress=100)
        
        result = task_store.cancel_task(task_id)
        assert result == False
    
    def test_list_tasks(self, task_store):
        """Test listing tasks."""
        # Create multiple tasks
        for i in range(3):
            task_id = task_store.generate_task_id()
            task_store.create_task(task_id, b"content", f"test{i}.txt")
        
        tasks = task_store.list_tasks()
        assert len(tasks) >= 3


class TestSSENotifications:
    """Tests for SSE notification service."""
    
    def test_subscribe_unsubscribe(self):
        """Test SSE subscription."""
        from markitdown_api.sse_notifications import SSENotificationService
        
        service = SSENotificationService()
        queue = service.subscribe("test_task")
        
        assert queue is not None
        
        service.unsubscribe(queue, "test_task")
    
    @pytest.mark.asyncio
    async def test_notify_progress(self):
        """Test progress notification."""
        from markitdown_api.sse_notifications import SSENotificationService
        
        service = SSENotificationService()
        queue = service.subscribe("test_task")
        
        await service.notify_progress("test_task", 50, "Processing")
        
        event = await queue.get()
        assert event["event"] == "task_progress"
        assert event["data"]["progress"] == 50