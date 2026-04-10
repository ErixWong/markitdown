# MarkItDown OCR MCP Server

> [!IMPORTANT]
> This package is meant for **local use** with trusted agents. When running in HTTP mode, it binds to `localhost` by default. DO NOT bind to other interfaces unless you understand the [security implications](#security-considerations).

An enhanced MCP (Model Context Protocol) server for MarkItDown with:

- **Async Task Management** - Submit tasks, track progress, get results
- **OCR Support** - Extract text from images in PDF, DOCX, PPTX, XLSX
- **SSE Notifications** - Real-time progress updates via Server-Sent Events
- **Docker Deployment** - Easy deployment with Docker

## Comparison with Official MCP

| Feature | Official `markitdown-mcp` | This `markitdown-ocr-mcp` |
|---------|---------------------------|---------------------------|
| Mode | Synchronous | Asynchronous |
| Tools | 1 (`convert_to_markdown`) | 6 (task management + helpers) |
| OCR | ❌ | ✅ |
| Progress Tracking | ❌ | ✅ |
| SSE Notifications | ❌ | ✅ |
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
  "content": "base64_encoded_file_content",
  "filename": "document.pdf",
  "options": {
    "enable_ocr": true,
    "ocr_model": "gpt-4o"
  }
}
```

Returns: `task_id`

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

Event types:
- `task_progress` - Progress updates
- `task_completed` - Task finished successfully
- `task_failed` - Task failed with error
- `task_cancelled` - Task was cancelled

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MARKITDOWN_STORAGE_DIR` | Storage directory for tasks | `./storage` |
| `MARKITDOWN_OCR_ENABLED` | Enable OCR by default | `false` |
| `MARKITDOWN_OCR_API_KEY` | API key for LLM OCR | - |
| `MARKITDOWN_OCR_API_BASE` | API base URL | `https://api.openai.com/v1` |
| `MARKITDOWN_OCR_MODEL` | OCR model name | `gpt-4o` |
| `MARKITDOWN_MAX_IMAGE_DIMENSION` | Max image size for OCR | `1500` |

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