def test_import():
    from markitdown_server import __version__
    assert __version__ == "0.1.0"


def test_import_core():
    from markitdown_server.core.models import TaskStatus, SUPPORTED_FORMATS
    from markitdown_server.core.task_store import TaskStore
    from markitdown_server.core.sse_notifications import SSENotificationService
    assert TaskStatus.PENDING.value == "pending"
    assert len(SUPPORTED_FORMATS) > 0


def test_import_api():
    from markitdown_server.api import create_app
    app = create_app()
    assert app.title == "MarkItDown Server"


def test_import_mcp():
    from markitdown_server.mcp import mcp
    assert mcp.name == "markitdown-server"


def test_unified_full():
    from markitdown_server.app import create_unified_app
    app = create_unified_app(enable_api=True, enable_mcp=True)
    routes = [r.path for r in app.routes]
    assert "/" in routes
    assert "/health" in routes
    assert "/api" in routes
    assert "/mcp" in routes
    assert "/mcp/sse" in routes


def test_unified_api_only():
    from markitdown_server.app import create_unified_app
    app = create_unified_app(enable_api=True, enable_mcp=False)
    routes = [r.path for r in app.routes]
    assert "/api" in routes
    assert "/mcp" not in routes


def test_unified_mcp_only():
    from markitdown_server.app import create_unified_app
    app = create_unified_app(enable_api=False, enable_mcp=True)
    routes = [r.path for r in app.routes]
    assert "/mcp" in routes
    assert "/mcp/sse" in routes
    assert "/api" not in routes
