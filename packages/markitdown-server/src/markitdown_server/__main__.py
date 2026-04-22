import argparse

from .app import run_unified_server


def main():
    parser = argparse.ArgumentParser(
        description="MarkItDown Server - unified API and MCP server on single port"
    )
    parser.add_argument("--host", default=None, help="Host to bind to")
    parser.add_argument("--port", type=int, default=None, help="Port to listen on")
    parser.add_argument("--storage", default=None, help="Storage directory for tasks")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--no-api", action="store_true", help="Disable /api endpoints")
    parser.add_argument("--no-mcp", action="store_true", help="Disable /mcp endpoints")

    args = parser.parse_args()
    run_unified_server(
        host=args.host,
        port=args.port,
        storage=args.storage,
        reload=args.reload,
        enable_api=not args.no_api,
        enable_mcp=not args.no_mcp,
    )


if __name__ == "__main__":
    main()
