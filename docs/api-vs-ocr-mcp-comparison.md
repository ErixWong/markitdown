# markitdown-api vs markitdown-ocr-mcp 对比分析

## 概述

本文档详细对比了 MarkItDown 项目中的两个服务包：`markitdown-api`（RESTful HTTP API）和 `markitdown-ocr-mcp`（MCP 协议服务器）。

## 架构对比

### 核心架构

| 特性 | markitdown-api | markitdown-ocr-mcp |
|------|----------------|--------------------|
| **协议** | RESTful HTTP API | MCP (Model Context Protocol) |
| **Web 框架** | FastAPI | Starlette + MCP SDK |
| **通信方式** | HTTP/HTTPS | STDIO 或 HTTP/SSE |
| **主要用途** | 传统 Web 服务集成 | LLM Agent 集成 |
| **默认端口** | 8000 | 3001 |

### 技术栈

**markitdown-api:**
- FastAPI (Web 框架)
- Uvicorn (ASGI 服务器)
- Pydantic (数据验证)
- SQLite (任务存储)
- python-multipart (文件上传)

**markitdown-ocr-mcp:**
- MCP SDK (Model Context Protocol)
- Starlette (Web 框架)
- Uvicorn (ASGI 服务器)
- SQLite (任务存储)
- python-dotenv (环境变量)

## 功能特性对比

### 核心功能

| 功能 | markitdown-api | markitdown-ocr-mcp |
|------|----------------|--------------------|
| 文件转换 | ✅ | ✅ |
| 异步任务管理 | ✅ | ✅ |
| OCR 支持 | ✅ (通过 markitdown-ocr) | ✅ (通过 markitdown-ocr) |
| SSE 实时通知 | ✅ | ✅ |
| Silent 模式 | ✅ | ✅ |
| 分页处理 (PDF) | ✅ (2026-04-15 新增) | ✅ |
| Bearer Token 认证 | ✅ | ❌ |
| CORS 配置 | ✅ | ❌ |
| 直接同步转换 | ✅ (`/convert`) | ❌ |
| Base64 上传 | ✅ | ✅ (MCP 工具) |
| 文件路径上传 | ❌ | ✅ (server 本地文件) |

### OCR 功能对比

**markitdown-api:**
- OCR 作为可选功能 (`[ocr]` 依赖)
- 通过环境变量 `MARKITDOWN_OCR_ENABLED` 启用
- 使用 `markitdown-ocr` 插件
- **2026-04-15 更新**: 支持 PDF 逐页处理
- 支持页码范围选择 (`page_range` 参数)
- 使用 PyMuPDF 进行 PDF 页面提取

**markitdown-ocr-mcp:**
- OCR 为核心功能
- 支持 PDF 逐页处理
- 支持页码范围选择 (`page_range` 参数)
- 实时进度更新 (每页处理进度)
- 使用 PyMuPDF 进行 PDF 页面提取

### 任务管理

两者都提供:
- SQLite 持久化存储
- 任务状态跟踪 (pending/processing/completed/failed/cancelled)
- 进度百分比更新
- 日期分层的文件存储结构

**差异:**

| 特性 | markitdown-api | markitdown-ocr-mcp |
|------|----------------|--------------------|
| 任务 ID 生成 | `task_{timestamp}_{hash}` | `task_{uuid}` |
| 最大并发数 | 可配置 (默认 3) | 无限制 |
| 任务取消 | ✅ | ✅ |
| 任务列表过滤 | ✅ (按状态) | ✅ (按状态) |
| 自动清理旧任务 | ❌ | ✅ (`cleanup_old_tasks`) |

## API 接口对比

### markitdown-api 端点

```
GET  /                      # 健康检查
GET  /health                # 健康检查
POST /tasks                 # 提交任务 (multipart)
POST /tasks/base64          # 提交任务 (Base64)
GET  /tasks/{task_id}       # 查询状态
GET  /tasks/{task_id}/result # 获取结果
DELETE /tasks/{task_id}     # 取消任务
GET  /tasks                 # 任务列表
GET  /tasks/{task_id}/events # SSE (单任务)
GET  /tasks/events          # SSE (所有任务)
GET  /formats               # 支持格式
POST /convert               # 直接转换
```

### markitdown-ocr-mcp 工具

```
submit_conversion_task      # 提交转换任务
get_task_status            # 查询状态
get_task_result            # 获取结果
cancel_task                # 取消任务
list_tasks                 # 任务列表
get_supported_formats      # 支持格式
```

### HTTP/SSE 端点 (markitdown-ocr-mcp)

```
GET  /sse                   # MCP SSE 连接
POST /messages/            # MCP 消息
GET  /tasks/events         # SSE 通知
```

## 代码实现对比

### TaskStore 实现

**相似点:**
- 都使用 SQLite 存储任务元数据
- 都使用文件系统存储源文件和结果
- 都采用日期分层目录结构 (`YYYY/MM/DD/`)
- 都提供线程安全的数据库连接

**差异:**

```python
# markitdown-api: Task 数据类
@dataclass
class Task:
    task_id: str
    filename: str
    content: bytes  # 内存中保留内容
    options: dict
    status: TaskStatus
    # ...

# markitdown-ocr-mcp: TaskInfo 数据类
@dataclass
class TaskInfo:
    task_id: str
    status: str
    progress: int
    source_path: str  # 仅存储路径
    result_path: str
    # ...
```

**关键区别:**
- `markitdown-api` 在 Task 对象中保留文件内容 (bytes)
- `markitdown-ocr-mcp` 仅存储文件路径，按需读取

### TaskProcessor 实现

**markitdown-api:**
```python
# 简单整文件处理
async def _process_task(self, task_id: str):
    content = task.content
    result = md.convert_stream(io.BytesIO(content))
    # 保存结果
```

**markitdown-ocr-mcp:**
```python
# 支持 PDF 逐页处理
async def process_task(self, task_id: str):
    if is_pdf and enable_ocr:
        await self._process_pdf_page_by_page(...)
    else:
        await self._process_whole_file(...)
```

**逐页处理优势:**
1. 更精确的进度报告 (每页独立进度)
2. 支持页码范围选择
3. 单页失败不影响其他页面
4. 更好的 OCR 性能监控

### SSE 通知实现

两者实现几乎相同:
- 都使用 `asyncio.Queue` 管理订阅
- 都支持心跳机制 (30 秒)
- 都支持特定任务和全局订阅
- 都使用统一的事件格式

**统一事件格式:**
```json
{
  "task_id": "task_abc123",
  "status": "processing",
  "progress": 45,
  "message": "Processing page 3/10"
}
```

### 认证与安全

**markitdown-api:**
- ✅ Bearer Token 认证
- ✅ CORS 配置
- ✅ 可选认证 (健康端点免认证)
- ✅ 文件大小限制 (默认 100MB)

**markitdown-ocr-mcp:**
- ❌ 无认证机制
- ❌ 无 CORS 配置
- ✅ 文件大小限制 (默认 100MB)
- ⚠️ 设计用于本地可信环境

## 配置对比

### 环境变量

**markitdown-api:**
```bash
MARKITDOWN_STORAGE_DIR         # 存储目录
MARKITDOWN_API_HOST            # 服务器主机
MARKITDOWN_API_PORT            # 服务器端口
MARKITDOWN_API_KEY             # Bearer Token
MARKITDOWN_CORS_ORIGINS        # CORS 来源
MARKITDOWN_MAX_FILE_SIZE       # 最大文件大小
MARKITDOWN_OCR_ENABLED         # 启用 OCR
MARKITDOWN_OCR_API_KEY         # OCR API 密钥
MARKITDOWN_OCR_API_BASE        # OCR API 地址
MARKITDOWN_OCR_MODEL           # OCR 模型
MARKITDOWN_SSE_HEARTBEAT       # SSE 心跳间隔
```

**markitdown-ocr-mcp:**
```bash
MARKITDOWN_STORAGE_DIR         # 存储目录
MARKITDOWN_OCR_ENABLED         # 启用 OCR
MARKITDOWN_OCR_API_KEY         # OCR API 密钥
MARKITDOWN_OCR_API_BASE        # OCR API 地址
MARKITDOWN_OCR_MODEL           # OCR 模型
MARKITDOWN_OCR_TIMEOUT         # OCR 超时
MARKITDOWN_MAX_CONCURRENT      # 最大并发
MARKITDOWN_MAX_FILE_SIZE_MB    # 最大文件大小 (MB)
MARKITDOWN_MCP_HOST            # MCP 主机
MARKITDOWN_MCP_PORT            # MCP 端口
```

## 使用场景

### markitdown-api 适用场景

1. **传统 Web 应用集成** - 通过 REST API 调用
2. **需要认证的场景** - Bearer Token 保护
3. **跨域访问** - CORS 支持
4. **简单快速转换** - `/convert` 端点
5. **HTTP 客户端集成** - 标准 HTTP 请求

### markitdown-ocr-mcp 适用场景

1. **LLM Agent 集成** - MCP 协议原生支持
2. **Claude Desktop 等应用** - MCP 服务器配置
3. **大量 PDF OCR 处理** - 逐页处理优势
4. **需要精细进度控制** - 每页进度更新
5. **本地可信环境** - 无需认证

## 性能对比

### PDF 处理性能

**markitdown-api:**
- **2026-04-15 更新**: 支持逐页处理
- 精确进度 (每页独立进度)
- 单页失败可跳过继续处理
- 支持页码范围 (测试/抽样)
- 使用 PyMuPDF 进行页面提取

**markitdown-ocr-mcp:**
- 逐页处理
- 精确进度 (每页独立进度)
- 单页失败可跳过继续处理
- 支持页码范围 (测试/抽样)

### 内存使用

**markitdown-api:**
- Task 对象保留文件内容 (bytes)
- 适合小文件
- 大文件可能占用较多内存

**markitdown-ocr-mcp:**
- 仅存储文件路径
- 按需读取文件
- 更适合大文件处理

## 部署对比

### Docker 部署

**markitdown-api:**
```bash
docker build -f packages/markitdown-api/Dockerfile -t markitdown-api:latest .
docker run -p 8000:8000 -v /storage:/app/storage markitdown-api:latest
```

**markitdown-ocr-mcp:**
```bash
docker build -f packages/markitdown-ocr-mcp/Dockerfile -t markitdown-ocr-mcp:latest .
docker run -p 3001:3001 -v /storage:/app/storage markitdown-ocr-mcp:latest --http
```

### Claude Desktop 配置

**markitdown-api:**
```json
// 不适用 - 需通过 HTTP 调用
```

**markitdown-ocr-mcp:**
```json
{
  "mcpServers": {
    "markitdown-ocr": {
      "command": "docker",
      "args": ["run", "--rm", "-i", "markitdown-ocr-mcp:latest"]
    }
  }
}
```

## 代码质量对比

### 代码组织

**markitdown-api:**
- 模块化清晰 (server.py, task_store.py, task_processor.py, auth.py, models.py)
- Pydantic 模型定义完善
- 类型注解完整
- 符合 FastAPI 最佳实践

**markitdown-ocr-mcp:**
- 模块化清晰 (__main__.py, _task_store.py, _task_processor.py, _sse_notifications.py)
- MCP 工具定义清晰
- 类型注解完整
- 符合 MCP SDK 最佳实践

### 测试覆盖

**markitdown-api:**
- `tests/test_api.py` - API 端点测试

**markitdown-ocr-mcp:**
- `tests/test_mcp_client.py` - MCP 客户端测试
- `tests/test_api_direct.py` - API 直接调用测试
- `tests/test_real_pdf.py` - 真实 PDF 测试
- `tests/test_real_image.py` - 真实图片测试
- `tests/test_pdf_manual.py` - PDF 手动测试
- `tests/test_pdf_image_extract.py` - PDF 图片提取测试
- `tests/test_debug_convert.py` - 调试转换测试
- `tests/test_simple.py` - 简单测试
- `tests/test_task_store.py` - TaskStore 测试

## 总结

### 选择建议

**选择 markitdown-api 如果:**
- 需要标准 RESTful HTTP API
- 需要认证和 CORS 支持
- 面向传统 Web 应用
- 需要简单快速集成
- 需要 PDF 逐页 OCR 处理 (2026-04-15 新增)

**选择 markitdown-ocr-mcp 如果:**
- 需要 MCP 协议支持 (LLM Agent)
- 主要处理 PDF 文档且需要 OCR
- 需要逐页处理和精细进度
- 本地可信环境部署

### 潜在改进方向

**markitdown-api 可以改进:**
1. ✅ ~~添加 PDF 逐页处理支持~~ (已完成 2026-04-15)
2. 添加任务自动清理功能
3. 优化大文件内存使用

**markitdown-ocr-mcp 可以改进:**
1. 添加认证机制
2. 添加 CORS 支持
3. 添加直接同步转换端点
4. 完善错误处理和日志

### 共同优势

- 都使用 SQLite 持久化
- 都支持 SSE 实时通知
- 都支持 Silent 模式
- 都支持 OCR (通过 markitdown-ocr)
- 都有完善的文档
- 都支持 Docker 部署

---

*文档生成时间：2026-04-15*
