# MarkItDown RESTful API Server

> [!IMPORTANT]
> This package provides a **standard RESTful HTTP API** for MarkItDown, unlike the MCP-based packages. It's designed for direct HTTP integration without MCP protocol overhead.

A RESTful API server for [MarkItDown](https://github.com/microsoft/markitdown) that provides:

- **Standard HTTP API** - RESTful endpoints for file conversion
- **Async Task Management** - Submit tasks, track progress, get results
- **OCR Support** - Extract text from images in PDF, DOCX, PPTX, XLSX
- **SSE Notifications** - Real-time progress updates via Server-Sent Events
- **Direct Conversion** - Synchronous conversion for small files
- **Docker Deployment** - Easy deployment with Docker

## Comparison with Other Packages

| Feature | markitdown (Core) | markitdown-mcp | markitdown-ocr-mcp | markitdown-api |
|---------|-------------------|----------------|--------------------|----------------|
| Python API | ✅ | ❌ | ❌ | ❌ |
| CLI | ✅ | ❌ | ❌ | ❌ |
| MCP Protocol | ❌ | ✅ (STDIO) | ✅ (STDIO/HTTP) | ❌ |
| RESTful HTTP API | ❌ | ❌ | ❌ | ✅ |
| File Transfer | ❌ | Base64 | Base64 | Base64 + Form Data |
| Async Mode | ❌ | ❌ | ✅ (MCP Tools + SSE) | ✅ (REST API + SSE) |
| Page-by-Page Processing | ❌ | ❌ | ✅ | ✅ |
| SSE Notifications | ❌ | ❌ | ✅ | ✅ |
| OCR Support | ❌ | ❌ | ✅ | ✅ |
| Task Management | ❌ | ❌ | ✅ | ✅ |
| Synchronous (Blocking) Conversion | ❌ | ❌ | ❌ | ✅ |

## Installation

### From Source (Monorepo)

```bash
# In the monorepo root directory
pip install -e packages/markitdown
pip install -e packages/markitdown-api
```

### With OCR Support

```bash
pip install -e packages/markitdown-api[ocr]
```

### From PyPI (when published)

```bash
pip install markitdown-api
pip install markitdown-api[ocr]  # With OCR support
```

## Usage

### Start the Server

```bash
# Default: localhost:8000
markitdown-api

# Custom host and port
markitdown-api --host 127.0.0.1 --port 8000

# With custom storage directory
markitdown-api --storage /path/to/storage

# Development mode with auto-reload
markitdown-api --reload
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MARKITDOWN_STORAGE_DIR` | Storage directory for tasks | `./storage` |
| `MARKITDOWN_API_HOST` | Server host | `127.0.0.1` |
| `MARKITDOWN_API_PORT` | Server port | `8000` |
| `MARKITDOWN_API_KEY` | **Bearer token for API authentication** | - (disabled) |
| `MARKITDOWN_CORS_ORIGINS` | CORS allowed origins (comma-separated or `*`) | `*` |
| `MARKITDOWN_MAX_FILE_SIZE` | **Maximum file size limit** | `100MB` |
| `MARKITDOWN_OCR_ENABLED` | Enable OCR by default | `false` |
| `MARKITDOWN_OCR_API_KEY` | API key for LLM OCR | - |
| `MARKITDOWN_OCR_API_BASE` | API base URL | `https://api.openai.com/v1` |
| `MARKITDOWN_OCR_MODEL` | OCR model name | `gpt-4o` |

### Bearer Token Authentication

**Authentication is optional** - disabled by default. To enable, set `MARKITDOWN_API_KEY`:

```bash
# Enable authentication
export MARKITDOWN_API_KEY="your-secret-token"

# Start server
markitdown-api
```

When authentication is enabled, all API endpoints require a valid Bearer token:

```bash
# Request with authentication
curl -X POST "http://localhost:8000/tasks" \
  -H "Authorization: Bearer your-secret-token" \
  -F "file=@document.pdf"
```

**Without valid token:**
```json
{
  "detail": "Bearer token required. Authentication is enabled."
}
```

**Health endpoints (`/` and `/health`) do not require authentication.**

### CORS Configuration

Configure allowed origins for cross-origin requests:

```bash
# Allow all origins (default)
export MARKITDOWN_CORS_ORIGINS="*"

# Allow specific origins
export MARKITDOWN_CORS_ORIGINS="http://localhost:3000,https://example.com"
```

**Note:** `allow_credentials`, `allow_methods`, and `allow_headers` are set to allow all by default, which is required for Bearer token authentication to work properly.

### File Size Limit

Configure maximum file size via `MARKITDOWN_MAX_FILE_SIZE`:

```bash
# Default: 100MB
export MARKITDOWN_MAX_FILE_SIZE="100MB"

# Other formats
export MARKITDOWN_MAX_FILE_SIZE="50MB"   # 50MB
export MARKITDOWN_MAX_FILE_SIZE="1GB"    # 1GB
export MARKITDOWN_MAX_FILE_SIZE="104857600"  # Raw bytes
```

**When exceeded, returns 413 error:**
```json
{
  "detail": "File too large: 150000000 bytes. Maximum allowed: 100000000 bytes (100MB)"
}
```

### File Size Limit

Configure maximum file size via `MARKITDOWN_MAX_FILE_SIZE`:

```bash
# Default: 100MB
export MARKITDOWN_MAX_FILE_SIZE="100MB"

# Other formats
export MARKITDOWN_MAX_FILE_SIZE="50MB"   # 50MB
export MARKITDOWN_MAX_FILE_SIZE="1GB"    # 1GB
export MARKITDOWN_MAX_FILE_SIZE="104857600"  # Raw bytes
```

**When exceeded, returns 413 error:**
```json
{
  "detail": "File too large: 150000000 bytes. Maximum allowed: 100000000 bytes (100MB)"
}
```

## API Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/` | Health check root | No |
| GET | `/health` | Health check with version/uptime | No |
| POST | `/tasks` | Submit file conversion task (multipart) | Yes |
| POST | `/tasks/base64` | Submit task with Base64 content | Yes |
| GET | `/tasks` | List tasks with optional filter | Yes |
| GET | `/tasks/{id}` | Get task status and progress | Yes |
| GET | `/tasks/{id}/result` | Get conversion result (markdown) | Yes |
| DELETE | `/tasks/{id}` | Cancel a pending/processing task | Yes |
| GET | `/tasks/{id}/events` | Subscribe to SSE events for a task | Yes |
| GET | `/tasks/events` | Subscribe to SSE events for all tasks | Yes |
| GET | `/formats` | Get list of supported file formats | Yes |
| POST | `/convert` | Direct synchronous conversion | Yes |

> **Note:** Authentication is optional. When `MARKITDOWN_API_KEY` is set, all endpoints except `/` and `/health` require Bearer token.

### Health & Info

#### `GET /`
Root endpoint - health check.

#### `GET /health`
Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "uptime": 3600.5
}
```

### Task Management

#### `POST /tasks`
Submit a file conversion task (multipart upload).

**Request:**
- `file`: File to convert (multipart)
- `enable_ocr`: Enable OCR (query param, default: false)
- `ocr_model`: OCR model name (query param)
- `page_range`: Page range for PDF (query param)
- `silent`: Suppress progress notifications (query param)

**Response:**
```json
{
  "task_id": "task_20260413_123456_abc123",
  "message": "Task submitted successfully",
  "created_at": "2026-04-13T12:34:56Z"
}
```

**Example:**
```bash
curl -X POST "http://localhost:8000/tasks?enable_ocr=false" \
  -F "file=@document.pdf"
```

#### `POST /tasks/base64`
Submit task with Base64 encoded content.

**Request:**
- `content`: Base64 encoded file content (query param)
- `filename`: Original filename (query param)
- Other options same as multipart upload

**Example:**
```bash
# Encode file to Base64
CONTENT=$(base64 -w 0 document.pdf)

curl -X POST "http://localhost:8000/tasks/base64" \
  --data-urlencode "content=$CONTENT" \
  -d "filename=document.pdf" \
  -d "enable_ocr=false"
```

#### `GET /tasks/{task_id}`
Get task status and progress.

**Response:**
```json
{
  "task_id": "task_20260413_123456_abc123",
  "status": "processing",
  "progress": 45,
  "message": "Converting to markdown",
  "created_at": "2026-04-13T12:34:56Z",
  "updated_at": "2026-04-13T12:35:15Z"
}
```

**Status Values:**
- `pending` - Task created, waiting to process
- `processing` - Currently converting
- `completed` - Conversion finished
- `failed` - Conversion failed
- `cancelled` - Task was cancelled

#### `GET /tasks/{task_id}/result`
Get conversion result (Markdown content).

**Response:**
```json
{
  "task_id": "task_20260413_123456_abc123",
  "status": "completed",
  "markdown": "# Document Title\n\nContent...",
  "error": null
}
```

#### `DELETE /tasks/{task_id}`
Cancel a pending or processing task.

**Response:**
```json
{
  "task_id": "task_20260413_123456_abc123",
  "cancelled": true,
  "message": "Task cancelled successfully"
}
```

#### `GET /tasks`
List tasks with optional filter.

**Query Params:**
- `status`: Filter by status (optional)
- `limit`: Max results (default: 10)

**Response:**
```json
{
  "tasks": [
    {
      "task_id": "task_abc123",
      "filename": "document.pdf",
      "status": "completed",
      "progress": 100,
      "created_at": "2026-04-13T12:34:56Z",
      "updated_at": "2026-04-13T12:35:30Z"
    }
  ],
  "total": 1
}
```

### SSE Notifications

#### `GET /tasks/{task_id}/events`
Subscribe to SSE events for a specific task.

**Event Format:**
```
event: task_progress
data: {"task_id":"task_abc123","status":"processing","progress":45,"message":"Converting"}

event: task_completed
data: {"task_id":"task_abc123","status":"completed","progress":100,"message":"Done"}
```

**Example (Python):**
```python
import httpx

def listen_progress(task_id: str):
    url = f"http://localhost:8000/tasks/{task_id}/events"
    
    with httpx.stream("GET", url, timeout=None) as response:
        for line in response.iter_lines():
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
                print(f"[{event_type}] {data['progress']}% - {data['message']}")
```

#### `GET /tasks/events`
Subscribe to SSE events for all tasks.

### Supported Formats

#### `GET /formats`
Get list of supported file formats.

**Response:**
```json
{
  "formats": [
    {"extension": ".pdf", "mimetype": "application/pdf", "ocr_support": true},
    {"extension": ".docx", "mimetype": "...", "ocr_support": true},
    {"extension": ".txt", "mimetype": "text/plain", "ocr_support": false}
  ]
}
```

### Direct Conversion

#### `POST /convert`
Direct synchronous conversion (no task tracking).

**Request:**
- `file`: File to convert (multipart)

**Response:**
```json
{
  "markdown": "# Document Title\n\nContent..."
}
```

**Example:**
```bash
curl -X POST "http://localhost:8000/convert" \
  -F "file=@document.pdf"
```

**Note:** This is suitable for small files. For large files, use the async task endpoints.

## Python Client Example

```python
import httpx
import time

API_URL = "http://localhost:8000"

def convert_file(file_path: str) -> str:
    """Convert a file to Markdown."""
    
    # Submit task
    with open(file_path, 'rb') as f:
        response = httpx.post(
            f"{API_URL}/tasks",
            files={"file": (file_path, f)},
            params={"enable_ocr": False}
        )
    
    task_id = response.json()["task_id"]
    print(f"Task submitted: {task_id}")
    
    # Wait for completion
    while True:
        status = httpx.get(f"{API_URL}/tasks/{task_id}").json()
        print(f"Progress: {status['progress']}% - {status['message']}")
        
        if status["status"] == "completed":
            break
        elif status["status"] == "failed":
            raise Exception(status["message"])
        
        time.sleep(1)
    
    # Get result
    result = httpx.get(f"{API_URL}/tasks/{task_id}/result").json()
    return result["markdown"]

# Usage
markdown = convert_file("document.pdf")
print(markdown)
```

## Docker

### Build

```bash
# In monorepo root
docker build -f packages/markitdown-api/Dockerfile -t markitdown-api:latest .
```

### Run

```bash
docker run --rm -i \
  -p 8000:8000 \
  -v /path/to/storage:/app/storage \
  markitdown-api:latest
```

### With OCR

```bash
docker run --rm -i \
  -e MARKITDOWN_OCR_API_KEY=sk-xxx \
  -e MARKITDOWN_OCR_MODEL=gpt-4o \
  -p 8000:8000 \
  markitdown-api:latest
```

## API Documentation

When the server is running, access interactive API docs:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Security Considerations

- **No Authentication**: Server runs with user privileges
- **Localhost Binding**: Binds to localhost by default
- **File Access**: Can read files accessible to the user
- **API Key Security**: Never expose API keys in logs or responses

## License

MIT License - See [LICENSE](LICENSE) for details.

## Related Projects

- [markitdown](https://github.com/microsoft/markitdown) - Core library
- [markitdown-mcp](https://github.com/microsoft/markitdown/tree/main/packages/markitdown-mcp) - MCP server (STDIO)
- [markitdown-ocr-mcp](../markitdown-ocr-mcp) - MCP server with OCR (STDIO/HTTP/SSE)