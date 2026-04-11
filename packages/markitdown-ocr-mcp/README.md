# MarkItDown OCR MCP Server

> [!IMPORTANT]
> This package is meant for **local use** with trusted agents. When running in HTTP mode, it binds to `localhost` by default. DO NOT bind to other interfaces unless you understand the [security implications](#security-considerations).

An enhanced MCP (Model Context Protocol) server for MarkItDown with:

- **Async Task Management** - Submit tasks, track progress, get results
- **OCR Support** - Extract text from images in PDF, DOCX, PPTX, XLSX
- **SSE Notifications** - Real-time progress updates via Server-Sent Events
- **Silent Mode** - Option to suppress progress notifications for LLM agents
- **Docker Deployment** - Easy deployment with Docker

## Comparison with Official MCP

| Feature | Official `markitdown-mcp` | This `markitdown-ocr-mcp` |
|---------|---------------------------|---------------------------|
| Mode | Synchronous | Asynchronous |
| Tools | 1 (`convert_to_markdown`) | 6 (task management + helpers) |
| OCR | ❌ | ✅ |
| Progress Tracking | ❌ | ✅ |
| SSE Notifications | ❌ | ✅ |
| Silent Mode | ❌ | ✅ |
| Task Storage | ❌ | ✅ (SQLite) |
| Best For | Small files, quick conversion | Large files, OCR, batch processing |

## Installation

### From Source (Monorepo)

```bash
# In the monorepo root directory
pip install -e packages/markitdown
pip install -e packages/markitdown-ocr
pip install -e packages/markitdown-ocr-mcp
```

### With LLM Support (for OCR)

```bash
pip install -e packages/markitdown-ocr-mcp[llm]
```

## Usage

### STDIO Mode (Default)

```bash
markitdown-ocr-mcp
```

### HTTP Mode

```bash
markitdown-ocr-mcp --http --host 127.0.0.1 --port 3001
```

### With Storage Directory

```bash
markitdown-ocr-mcp --http --storage /path/to/storage
```

## MCP Tools

### Task Management Tools

#### `submit_conversion_task`

Submit a file for conversion:

```json
{
  "file_path": "/path/to/document.pdf",
  "options": {
    "enable_ocr": true,
    "ocr_model": "gpt-4o",
    "page_range": "1-10",
    "silent": false
  }
}
```

**Options:**

| Option | Type | Description | Default |
|--------|------|-------------|---------|
| `enable_ocr` | boolean | Enable OCR for image extraction | `false` |
| `ocr_model` | string | OCR model name (e.g., `gpt-4o`, `glm-ocr`) | From env |
| `page_range` | string | Page range to process (e.g., `1-5`, `1,3,5`) | All pages |
| `silent` | boolean | Suppress SSE progress notifications | `false` |

Returns: `task_id`

**Note:** Use `silent: true` when you don't want progress notifications (e.g., when an LLM agent is processing and shouldn't be interrupted by progress updates).

#### `get_task_status`

Query task progress:

```json
{
  "task_id": "task_abc123"
}
```

Returns:
```json
{
  "task_id": "task_abc123",
  "status": "processing",
  "progress": 45,
  "message": "Processing page 3/10",
  "created_at": "2026-04-10T09:30:00Z",
  "updated_at": "2026-04-10T09:32:15Z"
}
```

#### `get_task_result`

Get conversion result:

```json
{
  "task_id": "task_abc123"
}
```

Returns: Markdown content

#### `cancel_task`

Cancel a task:

```json
{
  "task_id": "task_abc123"
}
```

Returns: `true` or `false`

#### `list_tasks`

List tasks:

```json
{
  "status": "processing",
  "limit": 10
}
```

#### `get_supported_formats`

Get supported file formats.

## SSE Notifications

Subscribe to real-time task updates:

```
GET /tasks/events?task_id=task_abc123
```

### Event Types

| Event | Description |
|-------|-------------|
| `task_progress` | Progress updates during processing |
| `task_completed` | Task finished successfully |
| `task_failed` | Task failed with error |
| `task_cancelled` | Task was cancelled |

### Unified Message Format

All SSE events follow a **unified structure** with consistent fields:

```json
{
  "task_id": "task_abc123",
  "status": "processing",
  "progress": 45,
  "message": "Processing page 3/10"
}
```

**Field Descriptions:**

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | string | Unique task identifier |
| `status` | string | Task status: `pending`, `processing`, `completed`, `failed`, `cancelled` |
| `progress` | integer | Progress percentage (0-100), or -1 for failed/cancelled |
| `message` | string | Human-readable status message |

### Event-Specific Values

**task_progress:**
```json
{
  "task_id": "task_abc123",
  "status": "processing",
  "progress": 45,
  "message": "Processing page 3/10"
}
```

**task_completed:**
```json
{
  "task_id": "task_abc123",
  "status": "completed",
  "progress": 100,
  "message": "Conversion completed"
}
```

**task_failed:**
```json
{
  "task_id": "task_abc123",
  "status": "failed",
  "progress": -1,
  "message": "Error: OCR service unavailable"
}
```

**task_cancelled:**
```json
{
  "task_id": "task_abc123",
  "status": "cancelled",
  "progress": -1,
  "message": "Task cancelled"
}
```

### SSE Client Example (Python)

```python
import httpx
import json

def listen_sse(task_id: str):
    url = f"http://127.0.0.1:3000/tasks/events?task_id={task_id}"
    
    with httpx.stream("GET", url, timeout=None) as response:
        for line in response.iter_lines():
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip())
                # All events have unified structure
                status = data.get("status")
                progress = data.get("progress")
                message = data.get("message")
                print(f"[{event_type}] {status}: {progress}% - {message}")
```

## Silent Mode

When submitting a task with `silent: true`, the server will:
- **NOT** send SSE progress notifications
- Still process the task normally
- Still update task status in the database
- Still send completion/failure notifications (but without progress updates)

**Use Case:** When an LLM agent submits a conversion task and shouldn't receive intermediate progress updates that could interrupt its thought process.

```json
{
  "file_path": "/path/to/document.pdf",
  "options": {
    "enable_ocr": true,
    "silent": true
  }
}
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MARKITDOWN_STORAGE_DIR` | Storage directory for tasks | `./storage` |
| `MARKITDOWN_OCR_ENABLED` | Enable OCR by default | `false` |
| `MARKITDOWN_OCR_API_KEY` | API key for LLM OCR | - |
| `MARKITDOWN_OCR_API_BASE` | API base URL | `https://api.openai.com/v1` |
| `MARKITDOWN_OCR_MODEL` | OCR model name | `gpt-4o` |
| `MARKITDOWN_OCR_TIMEOUT` | OCR API timeout in seconds | `120` |
| `MARKITDOWN_MAX_CONCURRENT` | Maximum concurrent tasks | `3` |
| `MARKITDOWN_MAX_FILE_SIZE_MB` | Maximum file size in MB | `100` |
| `MARKITDOWN_MCP_HOST` | HTTP server host | `127.0.0.1` |
| `MARKITDOWN_MCP_PORT` | HTTP server port | `3001` |

## Docker

### Build

```bash
# In monorepo root
docker build -f packages/markitdown-ocr-mcp/Dockerfile -t markitdown-ocr-mcp:latest .
```

### Run (STDIO Mode)

```bash
docker run --rm -i markitdown-ocr-mcp:latest
```

### Run (HTTP Mode)

```bash
docker run --rm -i \
  -e MARKITDOWN_OCR_API_KEY=sk-xxx \
  -e MARKITDOWN_OCR_MODEL=gpt-4o \
  -p 3001:3001 \
  -v /path/to/storage:/app/storage \
  markitdown-ocr-mcp:latest \
  --http --host 0.0.0.0 --port 3001
```

### Claude Desktop Configuration

**STDIO Mode:**
```json
{
  "mcpServers": {
    "markitdown-ocr": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "MARKITDOWN_OCR_API_KEY=sk-xxx",
        "-e", "MARKITDOWN_OCR_MODEL=gpt-4o",
        "markitdown-ocr-mcp:latest"
      ]
    }
  }
}
```

**HTTP Mode:**
```json
{
  "mcpServers": {
    "markitdown-ocr": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "MARKITDOWN_OCR_API_KEY=sk-xxx",
        "-e", "MARKITDOWN_OCR_MODEL=gpt-4o",
        "-v", "/home/user/storage:/app/storage",
        "-p", "3001:3001",
        "markitdown-ocr-mcp:latest",
        "--http", "--host", "0.0.0.0", "--port", "3001"
      ]
    }
  }
}
```

## Storage Structure

```
storage/
├── 2026/
│   ├── 04/
│   │   ├── 10/
│   │   │   ├── task_abc123_source.pdf
│   │   │   ├── task_abc123_result.md
│   │   │   └── ...
│   │   └── 11/
│   └── 05/
├── tasks.db  # SQLite database
```

## Security Considerations

- **No Authentication**: Server runs with user privileges
- **Localhost Binding**: HTTP mode binds to localhost by default
- **File Access**: Can read files accessible to the user
- **API Key Security**: Never expose API keys in logs or responses

## License

MIT License - See [LICENSE](LICENSE) for details.

## Related Projects

- [markitdown](https://github.com/microsoft/markitdown) - Core library
- [markitdown-mcp](https://github.com/microsoft/markitdown/tree/main/packages/markitdown-mcp) - Official MCP server
- [markitdown-ocr](../markitdown-ocr) - OCR plugin
