import base64
import pytest
from httpx import ASGITransport, AsyncClient

from markitdown_server.app import create_unified_app


@pytest.fixture
def app():
    return create_unified_app()


@pytest.mark.anyio
async def test_health_unified_root(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "healthy"
        assert "services" in body
        assert "api" in body["services"]
        assert "mcp" in body["services"]


@pytest.mark.anyio
async def test_health_api_sub(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "healthy"


@pytest.mark.anyio
async def test_api_formats(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/formats")
        assert r.status_code == 200
        fmts = r.json()["formats"]
        assert len(fmts) > 0


@pytest.mark.anyio
async def test_api_submit_base64(app):
    content = base64.b64encode(b"Hello World, this is a test file.").decode()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/api/tasks/base64", params={"content": content, "filename": "test.txt"})
        assert r.status_code == 200
        body = r.json()
        assert "task_id" in body


@pytest.mark.anyio
async def test_api_list_tasks(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/tasks")
        assert r.status_code == 200
        body = r.json()
        assert "tasks" in body
        assert "total" in body


@pytest.mark.anyio
async def test_api_convert_direct(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/api/convert",
            files={"file": ("test.txt", b"Hello World", "text/plain")}
        )
        assert r.status_code == 200
        body = r.json()
        assert "markdown" in body


@pytest.mark.anyio
async def test_mcp_tools_exist(app):
    from markitdown_server.mcp import mcp
    tools = list(mcp._tool_manager.list_tools())
    tool_names = [t.name for t in tools]
    assert "submit_conversion_task" in tool_names
    assert "get_task" in tool_names
    assert "cancel_task" in tool_names
    assert "list_tasks" in tool_names
    assert "get_supported_formats" in tool_names


def test_unified_routes():
    app = create_unified_app()
    routes = [r.path for r in app.routes]
    assert "/" in routes
    assert "/health" in routes
    assert "/api" in routes
    assert "/mcp" in routes
    assert "/mcp/sse" in routes
    assert "/mcp/tasks/events" in routes
