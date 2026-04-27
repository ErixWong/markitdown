# MarkItDown Server

Unified server providing both REST API and MCP protocol on a single port for MarkItDown file conversion with OCR support.

## Usage

### Default: Both API + MCP

```bash
markitdown-server --host 127.0.0.1 --port 8000
```

Endpoints:
- `/health` - Health check (includes active services)
- `/api/` - REST API
- `/api/docs` - Swagger UI
- `/mcp` - MCP HTTP endpoint
- `/mcp/sse` - MCP SSE endpoint

### Selective Enable/Disable

```bash
# API only (disable MCP)
markitdown-server --no-mcp

# MCP only (disable API)
markitdown-server --no-api
```

### REST API Endpoints

All API endpoints are under `/api/`:

- `POST /api/tasks` - Submit conversion task
- `GET /api/tasks/{task_id}` - Get task status
- `GET /api/tasks/{task_id}/result` - Get conversion result
- `DELETE /api/tasks/{task_id}` - Cancel task
- `GET /api/tasks` - List tasks
- `GET /api/tasks/{task_id}/events` - SSE progress notifications
- `GET /api/formats` - Supported formats
- `POST /api/convert` - Direct synchronous conversion

### MCP Tools

MCP tools (via `/mcp` or `/mcp/sse`):

- `submit_conversion_task` - Submit file for conversion
- `get_task` - Get task status and result
- `cancel_task` - Cancel running task
- `list_tasks` - List tasks
- `get_supported_formats` - List supported formats

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MARKITDOWN_STORAGE_DIR` | `./storage` | Storage directory for tasks |
| `MARKITDOWN_SERVER_HOST` | `127.0.0.1` | Host to bind to |
| `MARKITDOWN_SERVER_PORT` | `8000` | Port to listen on |
| `MARKITDOWN_API_KEY` | _(empty)_ | Enable Bearer token auth (min 32 chars) |
| `MARKITDOWN_OCR_ENABLED` | `false` | Enable OCR by default |
| `MARKITDOWN_OCR_API_KEY` | _(empty)_ | **Required for OCR**: OpenAI-compatible API key |
| `MARKITDOWN_OCR_API_BASE` | _(empty)_ | Custom API base URL (Azure, DeepSeek, etc.) |
| `MARKITDOWN_OCR_MODEL` | `gpt-4o` | LLM Vision model for OCR |
| `MARKITDOWN_MAX_FILE_SIZE` | `100MB` | Max file size (supports KB/MB/GB) |
| `MARKITDOWN_MAX_FILE_SIZE_MB` | `100` | Max file size in MB (alternative) |
| `MARKITDOWN_CORS_ORIGINS` | `*` | CORS origins (comma-separated) |
| `MARKITDOWN_MCP_STREAMING` | `false` | Enable MCP streaming response |
| `MARKITDOWN_SSE_HEARTBEAT` | `30` | SSE heartbeat interval in seconds |

## Docker

### docker build + run

```bash
# Build
docker build -t markitdown-server packages/markitdown-server

# Both API + MCP (default)
docker run -p 8000:8000 markitdown-server

# API only
docker run -p 8000:8000 markitdown-server --no-mcp

# MCP only
docker run -p 8000:8000 markitdown-server --no-api
```

### docker compose

```bash
# Both services (default)
docker compose -f packages/markitdown-server/docker-compose.yml up -d

# With .env file
cp packages/markitdown-server/.env.example packages/markitdown-server/.env
# edit .env, then:
docker compose -f packages/markitdown-server/docker-compose.yml up -d
```

To enable only one service, edit `docker-compose.yml` and uncomment the corresponding profile, or override the command:

```bash
# API only
docker compose -f packages/markitdown-server/docker-compose.yml run --rm markitdown-server --no-mcp

# MCP only
docker compose -f packages/markitdown-server/docker-compose.yml run --rm markitdown-server --no-api
```

## Reverse Proxy (Nginx)

When deploying behind Nginx with HTTPS, the backend may return `307` redirects with `http://` in the `Location` header (e.g., `/mcp` → `/mcp/`). This causes clients to follow the redirect to plain HTTP, which fails. Add `proxy_redirect` to fix this:

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate     /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    location / {
        client_max_body_size 100m;
        proxy_pass http://127.0.0.1:8000;
        proxy_redirect http:// $scheme://;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

`proxy_redirect http:// $scheme://;` rewrites the backend's `Location: http://...` to `https://...`, ensuring redirects work correctly through the reverse proxy.

## MCP Client Configuration

For Claude Desktop or other MCP clients using SSE:

```json
{
  "mcpServers": {
    "markitdown": {
      "url": "http://127.0.0.1:8000/mcp/sse"
    }
  }
}
```

For streamable HTTP:

```json
{
  "mcpServers": {
    "markitdown": {
      "url": "http://127.0.0.1:8000/mcp",
      "transport": "http"
    }
  }
}
```
