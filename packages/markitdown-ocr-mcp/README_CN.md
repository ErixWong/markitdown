# MarkItDown OCR MCP 服务器

> [!IMPORTANT]
> 此软件包适用于与受信任的代理进行**本地使用**。在 HTTP 模式下运行时，默认绑定到 `localhost`。除非您了解[安全注意事项](#安全注意事项)，否则不要绑定到其他接口。

一个增强型的 MCP（模型上下文协议）服务器，用于 MarkItDown，具有以下功能：

- **异步任务管理** - 提交任务、跟踪进度、获取结果
- **OCR 支持** - 从 PDF、DOCX、PPTX、XLSX 中的图像提取文本
- **SSE 通知** - 通过服务器发送事件实时获取进度更新
- **静默模式** - 为 LLM 代理提供抑制进度通知的选项
- **Docker 部署** - 使用 Docker 轻松部署

## 与官方 MCP 的比较

| 功能 | 官方 `markitdown-mcp` | 此 `markitdown-ocr-mcp` |
|------|----------------------|------------------------|
| 模式 | 同步 | 异步 |
| 工具 | 1 个 (`convert_to_markdown`) | 6 个（任务管理 + 辅助工具） |
| OCR | ❌ | ✅ |
| 进度跟踪 | ❌ | ✅ |
| SSE 通知 | ❌ | ✅ |
| 静默模式 | ❌ | ✅ |
| 任务存储 | ❌ | ✅ (SQLite) |
| 最适合 | 小文件、快速转换 | 大文件、OCR、批处理 |

## 安装

### 从源码安装（Monorepo）

```bash
# 在 monorepo 根目录下
pip install -e packages/markitdown
pip install -e packages/markitdown-ocr
pip install -e packages/markitdown-ocr-mcp
```

### 带 LLM 支持（用于 OCR）

```bash
pip install -e packages/markitdown-ocr-mcp[llm]
```

## 使用方法

### STDIO 模式（默认）

```bash
markitdown-ocr-mcp
```

### HTTP 模式

```bash
markitdown-ocr-mcp --http --host 127.0.0.1 --port 3001
```

### 指定存储目录

```bash
markitdown-ocr-mcp --http --storage /path/to/storage
```

## MCP 工具

| 工具 | 说明 | 参数 | 传输方式 |
|------|------|------|----------|
| `submit_conversion_task` | 提交文件转换任务 | `file_path`, `options` (enable_ocr, ocr_model, page_range, silent) | STDIO / HTTP |
| `get_task_status` | 查询任务进度 | `task_id` | STDIO / HTTP |
| `get_task_result` | 获取转换结果（markdown） | `task_id` | STDIO / HTTP |
| `cancel_task` | 取消待处理/进行中的任务 | `task_id` | STDIO / HTTP |
| `list_tasks` | 列出任务（支持筛选） | `status`, `limit` | STDIO / HTTP |
| `get_supported_formats` | 获取支持的文件格式列表 | 无 | STDIO / HTTP |

> **说明：** 在 HTTP 模式下运行时，如果设置了 `MARKITDOWN_API_KEY`，所有 HTTP 连接需要在请求头中携带 Bearer Token 进行认证。STDIO 模式无需认证。

#### `submit_conversion_task`

提交文件进行转换：

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

**选项：**

| 选项 | 类型 | 描述 | 默认值 |
|------|------|------|--------|
| `enable_ocr` | 布尔值 | 启用 OCR 进行图像提取 | `false` |
| `ocr_model` | 字符串 | OCR 模型名称（例如 `gpt-4o`、`glm-ocr`） | 从环境变量获取 |
| `page_range` | 字符串 | 要处理的页面范围（例如 `1-5`、`1,3,5`） | 所有页面 |
| `silent` | 布尔值 | 抑制 SSE 进度通知 | `false` |

返回：`task_id`

**注意：** 当您不需要进度通知时使用 `silent: true`（例如，当 LLM 代理正在处理时，不应被进度更新打断）。

#### `get_task_status`

查询任务进度：

```json
{
  "task_id": "task_abc123"
}
```

返回：
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

获取转换结果：

```json
{
  "task_id": "task_abc123"
}
```

返回：Markdown 内容

#### `cancel_task`

取消任务：

```json
{
  "task_id": "task_abc123"
}
```

返回：`true` 或 `false`

#### `list_tasks`

列出任务：

```json
{
  "status": "processing",
  "limit": 10
}
```

#### `get_supported_formats`

获取支持的文件格式。

## SSE 通知

订阅实时任务更新：

```
GET /tasks/events?task_id=task_abc123
```

### 事件类型

| 事件 | 描述 |
|------|------|
| `task_progress` | 处理期间的进度更新 |
| `task_completed` | 任务成功完成 |
| `task_failed` | 任务失败并返回错误 |
| `task_cancelled` | 任务被取消 |

### 统一消息格式

所有 SSE 事件都遵循**统一结构**，具有一致的字段：

```json
{
  "task_id": "task_abc123",
  "status": "processing",
  "progress": 45,
  "message": "Processing page 3/10"
}
```

**字段描述：**

| 字段 | 类型 | 描述 |
|------|------|------|
| `task_id` | 字符串 | 唯一任务标识符 |
| `status` | 字符串 | 任务状态：`pending`、`processing`、`completed`、`failed`、`cancelled` |
| `progress` | 整数 | 进度百分比 (0-100)，失败/取消时为 -1 |
| `message` | 字符串 | 人类可读的状态消息 |

### 事件特定值

**task_progress：**
```json
{
  "task_id": "task_abc123",
  "status": "processing",
  "progress": 45,
  "message": "Processing page 3/10"
}
```

**task_completed：**
```json
{
  "task_id": "task_abc123",
  "status": "completed",
  "progress": 100,
  "message": "Conversion completed"
}
```

**task_failed：**
```json
{
  "task_id": "task_abc123",
  "status": "failed",
  "progress": -1,
  "message": "Error: OCR service unavailable"
}
```

**task_cancelled：**
```json
{
  "task_id": "task_abc123",
  "status": "cancelled",
  "progress": -1,
  "message": "Task cancelled"
}
```

### SSE 客户端示例（Python）

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
                # 所有事件都有统一结构
                status = data.get("status")
                progress = data.get("progress")
                message = data.get("message")
                print(f"[{event_type}] {status}: {progress}% - {message}")
```

## 静默模式

当使用 `silent: true` 提交任务时，服务器将：
- **不发送** SSE 进度通知
- 仍然正常处理任务
- 仍然在数据库中更新任务状态
- 仍然发送完成/失败通知（但没有进度更新）

**使用场景：** 当 LLM 代理提交转换任务时，不应收到可能打断其思考过程的中间进度更新。

```json
{
  "file_path": "/path/to/document.pdf",
  "options": {
    "enable_ocr": true,
    "silent": true
  }
}
```

## 环境变量

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `MARKITDOWN_STORAGE_DIR` | 任务存储目录 | `./storage` |
| `MARKITDOWN_API_KEY` | **HTTP认证的 Bearer Token** | -（禁用） |
| `MARKITDOWN_OCR_ENABLED` | 默认启用 OCR | `false` |
| `MARKITDOWN_OCR_API_KEY` | LLM OCR 的 API 密钥 | - |
| `MARKITDOWN_OCR_API_BASE` | API 基础 URL | `https://api.openai.com/v1` |
| `MARKITDOWN_OCR_MODEL` | OCR 模型名称 | `gpt-4o` |
| `MARKITDOWN_OCR_TIMEOUT` | OCR API 超时时间（秒） | `120` |
| `MARKITDOWN_MAX_CONCURRENT` | 最大并发任务数 | `3` |
| `MARKITDOWN_MAX_FILE_SIZE_MB` | 最大文件大小（MB） | `100` |
| `MARKITDOWN_MCP_HOST` | HTTP 服务器主机 | `127.0.0.1` |
| `MARKITDOWN_MCP_PORT` | HTTP 服务器端口 | `3001` |

### Bearer Token 认证

**认证是可选的** - 默认禁用。启用需设置 `MARKITDOWN_API_KEY`：

```bash
# 启用认证（最少32字符，需包含字母和数字）
export MARKITDOWN_API_KEY="your-secret-token-32-chars-min-with-mixed-123"

# 启动服务
markitdown-ocr-mcp --http
```

**Token 要求：**
- 最少 32 个字符
- 必须同时包含字母和数字
- 弱 Token（< 32 字符）将被拒绝，认证禁用

启用认证后，所有 HTTP 接口都需要有效的 Bearer Token：

```bash
# 带认证的请求
curl -X POST "http://localhost:3001/mcp" \
  -H "Authorization: Bearer your-secret-token" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "method": "tools/list", "id": 1}'
```

**SSE 端点带认证：**
```bash
curl -N "http://localhost:3001/tasks/events" \
  -H "Authorization: Bearer your-secret-token"
```

**无效 token 时：**
```json
{
  "detail": "Bearer token required. Authentication is enabled."
}
```

**说明：** 健康检查接口（`/` 和 `/health`）无需认证。

## Docker

### 构建

```bash
# 在 monorepo 根目录下
docker build -f packages/markitdown-ocr-mcp/Dockerfile -t markitdown-ocr-mcp:latest .
```

### 运行（STDIO 模式）

```bash
docker run --rm -i markitdown-ocr-mcp:latest
```

### 运行（HTTP 模式）

```bash
docker run --rm -i \
  -e MARKITDOWN_API_KEY=your-secret-token \
  -e MARKITDOWN_OCR_API_KEY=sk-xxx \
  -e MARKITDOWN_OCR_MODEL=gpt-4o \
  -p 3001:3001 \
  -v /path/to/storage:/app/storage \
  markitdown-ocr-mcp:latest \
  --http --host 0.0.0.0 --port 3001
```

**启用认证：**
```bash
docker run --rm -i \
  -e MARKITDOWN_API_KEY=your-secret-token \
  -e MARKITDOWN_OCR_API_KEY=sk-xxx \
  -e MARKITDOWN_OCR_MODEL=gpt-4o \
  -p 3001:3001 \
  -v /path/to/storage:/app/storage \
  markitdown-ocr-mcp:latest \
  --http --host 0.0.0.0 --port 3001
```

### Claude Desktop 配置

**STDIO 模式：**
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

**HTTP 模式（带认证）：**
```json
{
  "mcpServers": {
    "markitdown-ocr": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "MARKITDOWN_API_KEY=your-secret-token",
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

**HTTP 模式（无认证，仅本地）：**
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

## 存储结构

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
├── tasks.db  # SQLite 数据库
```

## 安全注意事项

### Bearer Token 认证（HTTP 模式）

在 HTTP 模式下运行时，可以启用可选的 Bearer Token 认证：

```bash
export MARKITDOWN_API_KEY="your-secret-token"
markitdown-ocr-mcp --http
```

启用后：
- 所有 HTTP 接口需要有效的 `Authorization: Bearer <token>` 头部
- 健康检查接口（`/` 和 `/health`）无需认证即可访问
- STDIO 模式不受影响（认证仅适用于 HTTP 传输）

**最佳实践：**
- 使用强随机生成的 Token
- 切勿在日志或客户端代码中暴露 `MARKITDOWN_API_KEY`
- 绑定到非 localhost 接口时，**务必启用认证**

### 一般安全

- **认证**：通过 `MARKITDOWN_API_KEY` 可选启用（默认禁用）
- **本地主机绑定**：HTTP 模式默认绑定到 localhost
- **文件访问**：可以读取用户可访问的文件
- **API 密钥安全**：切勿在日志或响应中暴露 API 密钥

## 许可证

MIT 许可证 - 详情请参见 [LICENSE](LICENSE)。

## 相关项目

- [markitdown](https://github.com/microsoft/markitdown) - 核心库
- [markitdown-mcp](https://github.com/microsoft/markitdown/tree/main/packages/markitdown-mcp) - 官方 MCP 服务器
- [markitdown-ocr](../markitdown-ocr) - OCR 插件