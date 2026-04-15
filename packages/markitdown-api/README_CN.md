# MarkItDown RESTful API 服务

> [!IMPORTANT]
> 本包为 MarkItDown 提供**标准 RESTful HTTP API**，不同于基于 MCP 的包。专为直接 HTTP 集成设计，无需 MCP 协议开销。

基于 [MarkItDown](https://github.com/microsoft/markitdown) 的 RESTful API 服务，提供：

- **标准 HTTP API** - RESTful 接口进行文件转换
- **异步任务管理** - 提交任务、跟踪进度、获取结果
- **OCR 支持** - 从 PDF、DOCX、PPTX、XLSX 中的图片提取文字
- **SSE 通知** - 通过 Server-Sent Events 实时推送进度
- **直接转换** - 小文件同步转换
- **Docker 部署** - 轻松容器化部署

## 与其他包的对比

| 功能 | markitdown (核心) | markitdown-mcp | markitdown-ocr-mcp | markitdown-api |
|------|-------------------|----------------|--------------------|----------------|
| Python API | ✅ | ❌ | ❌ | ❌ |
| CLI | ✅ | ❌ | ❌ | ❌ |
| MCP 协议 | ❌ | ✅ (STDIO) | ✅ (STDIO/HTTP) | ❌ |
| RESTful HTTP API | ❌ | ❌ | ❌ | ✅ |
| 文件传输方式 | ❌ | Base64 | Base64 | Base64 + Form Data |
| 异步方式 | ❌ | ❌ | ✅ (MCP工具 + SSE) | ✅ (REST接口 + SSE) |
| 逐页处理 | ❌ | ❌ | ✅ | ✅ |
| SSE 通知 | ❌ | ❌ | ✅ | ✅ |
| OCR 支持 | ❌ | ❌ | ✅ | ✅ |
| 任务管理 | ❌ | ❌ | ✅ | ✅ |
| 同步转换（阻塞式） | ❌ | ❌ | ❌ | ✅ |

## 安装

### 从源码安装（Monorepo）

```bash
# 在 monorepo 根目录
pip install -e packages/markitdown
pip install -e packages/markitdown-api
```

### 带 OCR 支持

```bash
pip install -e packages/markitdown-api[ocr]
```

### 从 PyPI 安装（发布后）

```bash
pip install markitdown-api
pip install markitdown-api[ocr]  # 带 OCR 支持
```

## 使用

### 启动服务

```bash
# 默认：localhost:8000
markitdown-api

# 自定义主机和端口
markitdown-api --host 127.0.0.1 --port 8000

# 自定义存储目录
markitdown-api --storage /path/to/storage

# 开发模式（自动重载）
markitdown-api --reload
```

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `MARKITDOWN_STORAGE_DIR` | 任务存储目录 | `./storage` |
| `MARKITDOWN_API_HOST` | 服务主机 | `127.0.0.1` |
| `MARKITDOWN_API_PORT` | 服务端口 | `8000` |
| `MARKITDOWN_API_KEY` | **Bearer 认证密钥** | -（禁用） |
| `MARKITDOWN_CORS_ORIGINS` | CORS 允许的来源（逗号分隔或 `*`） | `*` |
| `MARKITDOWN_MAX_FILE_SIZE` | **最大文件大小限制** | `100MB` |
| `MARKITDOWN_OCR_ENABLED` | 默认启用 OCR | `false` |
| `MARKITDOWN_OCR_API_KEY` | LLM OCR 的 API 密钥 | - |
| `MARKITDOWN_OCR_API_BASE` | API 基础 URL | `https://api.openai.com/v1` |
| `MARKITDOWN_OCR_MODEL` | OCR 模型名称 | `gpt-4o` |

### Bearer 认证

**认证可选** - 默认禁用。启用需设置 `MARKITDOWN_API_KEY`：

```bash
# 启用认证
export MARKITDOWN_API_KEY="your-secret-token"

# 启动服务
markitdown-api
```

启用认证后，所有 API 接口需要有效的 Bearer token：

```bash
# 带认证的请求
curl -X POST "http://localhost:8000/tasks" \
  -H "Authorization: Bearer your-secret-token" \
  -F "file=@document.pdf"
```

**无效 token 时：**
```json
{
  "detail": "Bearer token required. Authentication is enabled."
}
```

**健康检查接口（`/` 和 `/health`）无需认证。**

### CORS 配置

配置跨域请求允许的来源：

```bash
# 允许所有来源（默认）
export MARKITDOWN_CORS_ORIGINS="*"

# 允许特定来源
export MARKITDOWN_CORS_ORIGINS="http://localhost:3000,https://example.com"
```

**说明：** `allow_credentials`、`allow_methods`、`allow_headers` 默认允许所有，确保 Bearer 认证正常工作。

### 文件大小限制

通过 `MARKITDOWN_MAX_FILE_SIZE` 环境变量限制上传文件大小：

```bash
# 默认：100MB
export MARKITDOWN_MAX_FILE_SIZE="100MB"

# 其他格式
export MARKITDOWN_MAX_FILE_SIZE="50MB"   # 50MB
export MARKITDOWN_MAX_FILE_SIZE="1GB"    # 1GB
export MARKITDOWN_MAX_FILE_SIZE="104857600"  # 直接指定字节数
```

**超出限制时返回 413 错误：**
```json
{
  "detail": "File too large: 150000000 bytes. Maximum allowed: 100000000 bytes (100MB)"
}
```

## API 接口

| 方法 | 接口 | 说明 | 需要认证 |
|------|------|------|----------|
| GET | `/` | 根接口 - 健康检查 | 否 |
| GET | `/health` | 健康检查（含版本/运行时间） | 否 |
| POST | `/tasks` | 提交文件转换任务（multipart） | 是 |
| POST | `/tasks/base64` | 提交 Base64 编码内容任务 | 是 |
| GET | `/tasks` | 列出任务（支持筛选） | 是 |
| GET | `/tasks/{id}` | 获取任务状态和进度 | 是 |
| GET | `/tasks/{id}/result` | 获取转换结果（markdown） | 是 |
| DELETE | `/tasks/{id}` | 取消待处理/进行中的任务 | 是 |
| GET | `/tasks/{id}/events` | 订阅单个任务的 SSE 事件 | 是 |
| GET | `/tasks/events` | 订阅所有任务的 SSE 事件 | 是 |
| GET | `/formats` | 获取支持的文件格式列表 | 是 |
| POST | `/convert` | 直接同步转换 | 是 |

> **说明：** 认证是可选的。当设置了 `MARKITDOWN_API_KEY` 时，除 `/` 和 `/health` 外所有接口都需要 Bearer Token。

### 健康检查

#### `GET /`
根接口 - 健康检查。

#### `GET /health`
健康检查接口。

**响应：**
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "uptime": 3600.5
}
```

### 任务管理

#### `POST /tasks`
提交文件转换任务（multipart 上传）。

**请求：**
- `file`: 要转换的文件（multipart）
- `enable_ocr`: 启用 OCR（查询参数，默认：false）
- `ocr_model`: OCR 模型名称（查询参数）
- `page_range`: PDF 页面范围（查询参数）
- `silent`: 隐藏进度通知（查询参数）

**响应：**
```json
{
  "task_id": "task_20260413_123456_abc123",
  "message": "Task submitted successfully",
  "created_at": "2026-04-13T12:34:56Z"
}
```

**示例：**
```bash
curl -X POST "http://localhost:8000/tasks?enable_ocr=false" \
  -F "file=@document.pdf"
```

#### `POST /tasks/base64`
提交 Base64 编码内容的任务。

**请求：**
- `content`: Base64 编码的文件内容（查询参数）
- `filename`: 原始文件名（查询参数）
- 其他参数同 multipart 上传

**示例：**
```bash
# 文件编码为 Base64
CONTENT=$(base64 -w 0 document.pdf)

curl -X POST "http://localhost:8000/tasks/base64" \
  --data-urlencode "content=$CONTENT" \
  -d "filename=document.pdf" \
  -d "enable_ocr=false"
```

#### `GET /tasks/{task_id}`
获取任务状态和进度。

**响应：**
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

**状态值：**
- `pending` - 任务已创建，等待处理
- `processing` - 正在转换
- `completed` - 转换完成
- `failed` - 转换失败
- `cancelled` - 任务已取消

#### `GET /tasks/{task_id}/result`
获取转换结果（Markdown 内容）。

**响应：**
```json
{
  "task_id": "task_20260413_123456_abc123",
  "status": "completed",
  "markdown": "# Document Title\n\nContent...",
  "error": null
}
```

#### `DELETE /tasks/{task_id}`
取消待处理或进行中的任务。

**响应：**
```json
{
  "task_id": "task_20260413_123456_abc123",
  "cancelled": true,
  "message": "Task cancelled successfully"
}
```

#### `GET /tasks`
列出任务（可选过滤）。

**查询参数：**
- `status`: 按状态过滤（可选）
- `limit`: 最大结果数（默认：10）

**响应：**
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

### SSE 通知

#### `GET /tasks/{task_id}/events`
订阅特定任务的 SSE 事件。

**事件格式：**
```
event: task_progress
data: {"task_id":"task_abc123","status":"processing","progress":45,"message":"Converting"}

event: task_completed
data: {"task_id":"task_abc123","status":"completed","progress":100,"message":"Done"}
```

**示例（Python）：**
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
订阅所有任务的 SSE 事件。

### 支持的格式

#### `GET /formats`
获取支持的文件格式列表。

**响应：**
```json
{
  "formats": [
    {"extension": ".pdf", "mimetype": "application/pdf", "ocr_support": true},
    {"extension": ".docx", "mimetype": "...", "ocr_support": true},
    {"extension": ".txt", "mimetype": "text/plain", "ocr_support": false}
  ]
}
```

### 直接转换

#### `POST /convert`
直接同步转换（无任务跟踪）。

**请求：**
- `file`: 要转换的文件（multipart）

**响应：**
```json
{
  "markdown": "# Document Title\n\nContent..."
}
```

**示例：**
```bash
curl -X POST "http://localhost:8000/convert" \
  -F "file=@document.pdf"
```

**说明：** 适合小文件。大文件请使用异步任务接口。

## Python 客户端示例

```python
import httpx
import time

API_URL = "http://localhost:8000"

def convert_file(file_path: str) -> str:
    """将文件转换为 Markdown。"""
    
    # 提交任务
    with open(file_path, 'rb') as f:
        response = httpx.post(
            f"{API_URL}/tasks",
            files={"file": (file_path, f)},
            params={"enable_ocr": False}
        )
    
    task_id = response.json()["task_id"]
    print(f"任务已提交: {task_id}")
    
    # 等待完成
    while True:
        status = httpx.get(f"{API_URL}/tasks/{task_id}").json()
        print(f"进度: {status['progress']}% - {status['message']}")
        
        if status["status"] == "completed":
            break
        elif status["status"] == "failed":
            raise Exception(status["message"])
        
        time.sleep(1)
    
    # 获取结果
    result = httpx.get(f"{API_URL}/tasks/{task_id}/result").json()
    return result["markdown"]

# 使用
markdown = convert_file("document.pdf")
print(markdown)
```

## Docker

### 构建

```bash
# 在 monorepo 根目录
docker build -f packages/markitdown-api/Dockerfile -t markitdown-api:latest .
```

### 运行

```bash
docker run --rm -i \
  -p 8000:8000 \
  -v /path/to/storage:/app/storage \
  markitdown-api:latest
```

### 带 OCR

```bash
docker run --rm -i \
  -e MARKITDOWN_OCR_API_KEY=sk-xxx \
  -e MARKITDOWN_OCR_MODEL=gpt-4o \
  -p 8000:8000 \
  markitdown-api:latest
```

## API 文档

服务运行时，可访问交互式 API 文档：

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## 安全注意事项

- **无认证时**：服务以用户权限运行
- **本地绑定**：默认绑定 localhost
- **文件访问**：可读取用户可访问的文件
- **API 密钥安全**：切勿在日志或响应中暴露 API 密钥

## 许可证

MIT 许可证 - 详情见 [LICENSE](LICENSE)。

## 相关项目

- [markitdown](https://github.com/microsoft/markitdown) - 核心库
- [markitdown-mcp](https://github.com/microsoft/markitdown/tree/main/packages/markitdown-mcp) - MCP 服务（STDIO）
- [markitdown-ocr-mcp](../markitdown-ocr-mcp) - 带 OCR 的 MCP 服务（STDIO/HTTP/SSE）