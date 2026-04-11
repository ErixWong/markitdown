# MarkItDown OCR MCP 工作流程文档

## 1. 整体流程图

```mermaid
flowchart TD
    subgraph Client["MCP Client (Claude Desktop)"]
        A1[调用 submit_conversion_task]
        A2[获取 task_id]
        A3[轮询 get_task_status 或 SSE 订阅]
        A4[调用 get_task_result]
    end

    subgraph Server["MCP Server (__main__.py)"]
        B1[接收 MCP 工具调用]
        B2[获取 TaskStore 实例]
        B3[获取 TaskProcessor 实例]
        B4[返回 task_id]
    end

    subgraph Store["TaskStore (_task_store.py)"]
        C1[generate_task_id<br/>生成带时间戳的 ID]
        C2[base64.b64decode<br/>解码文件内容]
        C3[create_task<br/>保存源文件 + SQLite 记录]
        C4[update_progress<br/>更新进度]
        C5[complete_task<br/>保存结果 + 更新状态]
        C6[fail_task<br/>记录错误]
    end

    subgraph Processor["TaskProcessor (_task_processor.py)"]
        D1[start_processing<br/>创建 asyncio.Task]
        D2[process_task<br/>异步处理]
        D3[读取源文件]
        D4[创建 MarkItDown 实例]
        D5[执行 convert_stream]
        D6[保存结果]
    end

    subgraph SSE["SSE Notifications"]
        E1[notify_progress]
        E2[notify_completed]
        E3[notify_failed]
        E4[notify_cancelled]
    end

    A1 --> B1
    B1 --> B2
    B2 --> C1
    C1 --> C2
    C2 --> C3
    C3 --> B3
    B3 --> D1
    D1 --> B4
    B4 --> A2
    A2 --> A3
    A3 --> E1 & E2 & E3 & E4
  
    D1 --> D2
    D2 --> D3
    D3 --> D4
    D4 --> D5
    D5 --> D6
    D6 --> C5
  
    D2 -.->|进度更新| C4
    C4 -.->|回调| E1
    C5 -.->|回调| E2
    D2 -.->|错误| C6
    C6 -.->|回调| E3
  
    A3 -->|完成后| A4
    A4 --> C5
```

## 2. 详细步骤说明

### 步骤 1：提交任务

| 操作     | 组件                   | 说明                                                     |
| -------- | ---------------------- | -------------------------------------------------------- |
| 调用工具 | MCP Client             | `submit_conversion_task(content, filename, options)`   |
| 接收请求 | `__main__.py`        | MCP 工具装饰器处理                                       |
| 生成 ID  | `_task_store.py`     | `generate_task_id()` 生成 `task_lz1m2x3y4z5a6b7c8d9` |
| 解码内容 | `_task_store.py`     | `base64.b64decode(content)`                            |
| 保存文件 | `_task_store.py`     | 写入 `storage/2026/04/10/task_xxx_source.pdf`          |
| 创建记录 | `_task_store.py`     | SQLite INSERT，状态 `pending`                          |
| 启动处理 | `_task_processor.py` | `asyncio.create_task(process_task())`                  |
| 返回 ID  | `__main__.py`        | 返回 `task_id` 给客户端                                |

### 步骤 2：异步处理

| 操作     | 组件                      | 说明                                                             |
| -------- | ------------------------- | ---------------------------------------------------------------- |
| 更新状态 | `_task_processor.py`    | `update_progress(task_id, 0, "Starting...")` → `processing` |
| 读取文件 | `_task_processor.py`    | `open(task.source_path, 'rb')`                                 |
| 创建实例 | `_task_processor.py`    | `MarkItDown(enable_plugins=enable_ocr)`                        |
| 执行转换 | `_task_processor.py`    | `mid.convert_stream(file_stream, stream_info)`                 |
| OCR 处理 | `markitdown-ocr`        | 如果 `enable_ocr=True`，调用 LLM Vision                        |
| 保存结果 | `_task_store.py`        | `complete_task(task_id, result.markdown)`                      |
| 发送通知 | `_sse_notifications.py` | `notify_completed(task_id)`                                    |

### 步骤 3：获取结果

| 操作     | 组件               | 说明                             |
| -------- | ------------------ | -------------------------------- |
| 查询状态 | MCP Client         | `get_task_status(task_id)`     |
| 获取结果 | MCP Client         | `get_task_result(task_id)`     |
| 返回内容 | `_task_store.py` | 读取 `task_xxx_result.md` 文件 |

## 3. SSE 通知消息格式

### 3.1 事件类型列表

| 事件类型           | 触发时机 | 必需字段                               |
| ------------------ | -------- | -------------------------------------- |
| `task_progress`  | 进度更新 | `task_id`, `progress`, `message` |
| `task_completed` | 任务完成 | `task_id`, `status`, `progress`  |
| `task_failed`    | 任务失败 | `task_id`, `status`, `error`     |
| `task_cancelled` | 任务取消 | `task_id`, `status`                |

### 3.2 消息格式详解

#### task_progress（进度更新）

```json
{
  "event": "task_progress",
  "data": {
    "task_id": "task_lz1m2x3y4z5a6b7c8d9",
    "progress": 45,
    "message": "OCR processing page 5/10"
  }
}
```

**SSE 格式：**

```
event: task_progress
data: {"task_id":"task_lz1m2x3y4z5a6b7c8d9","progress":45,"message":"OCR processing page 5/10"}
```

#### task_completed（任务完成）

```json
{
  "event": "task_completed",
  "data": {
    "task_id": "task_lz1m2x3y4z5a6b7c8d9",
    "status": "completed",
    "progress": 100
  }
}
```

**SSE 格式：**

```
event: task_completed
data: {"task_id":"task_lz1m2x3y4z5a6b7c8d9","status":"completed","progress":100}
```

#### task_failed（任务失败）

```json
{
  "event": "task_failed",
  "data": {
    "task_id": "task_lz1m2x3y4z5a6b7c8d9",
    "status": "failed",
    "error": "OCR API timeout after 30 seconds"
  }
}
```

**SSE 格式：**

```
event: task_failed
data: {"task_id":"task_lz1m2x3y4z5a6b7c8d9","status":"failed","error":"OCR API timeout after 30 seconds"}
```

#### task_cancelled（任务取消）

```json
{
  "event": "task_cancelled",
  "data": {
    "task_id": "task_lz1m2x3y4z5a6b7c8d9",
    "status": "cancelled"
  }
}
```

**SSE 格式：**

```
event: task_cancelled
data: {"task_id":"task_lz1m2x3y4z5a6b7c8d9","status":"cancelled"}
```

### 3.3 SSE 订阅方式

**订阅特定任务：**

```
GET /tasks/events?task_id=task_lz1m2x3y4z5a6b7c8d9
```

**订阅所有任务：**

```
GET /tasks/events
```

**客户端示例（JavaScript）：**

```javascript
const eventSource = new EventSource('/tasks/events?task_id=task_xxx');

eventSource.addEventListener('task_progress', (e) => {
  const data = JSON.parse(e.data);
  console.log(`Progress: ${data.progress}% - ${data.message}`);
});

eventSource.addEventListener('task_completed', (e) => {
  const data = JSON.parse(e.data);
  console.log(`Task ${data.task_id} completed!`);
  eventSource.close();  // 完成后关闭连接
});

eventSource.addEventListener('task_failed', (e) => {
  const data = JSON.parse(e.data);
  console.error(`Task failed: ${data.error}`);
  eventSource.close();
});
```

## 4. 任务状态流转

```mermaid
stateDiagram-v2
    [*] --> pending: 任务创建
    pending --> processing: 开始处理
    processing --> completed: 转换成功
    processing --> failed: 转换失败
    pending --> cancelled: 用户取消
    processing --> cancelled: 用户取消
    completed --> [*]
    failed --> [*]
    cancelled --> [*]
```

### 状态说明

| 状态           | 说明                 | 可转换到                                 |
| -------------- | -------------------- | ---------------------------------------- |
| `pending`    | 任务已创建，等待处理 | `processing`, `cancelled`            |
| `processing` | 正在转换中           | `completed`, `failed`, `cancelled` |
| `completed`  | 转换完成，结果可获取 | 终态                                     |
| `failed`     | 转换失败，有错误信息 | 终态                                     |
| `cancelled`  | 用户取消             | 终态                                     |

## 5. 文件存储结构

```
storage/
├── tasks.db                      # SQLite 数据库
└── 2026/                          # 年份
    └── 04/                        # 月份
        └── 10/                    # 日期
            ├── task_lz1m2x_source_document.pdf    # 源文件
            ├── task_lz1m2x_result.md              # 结果文件
            ├── task_abc123_source_report.docx
            ├── task_abc123_result.md
            └── ...
```

### 文件命名规则

| 文件类型 | 格式                                     | 示例                                |
| -------- | ---------------------------------------- | ----------------------------------- |
| 源文件   | `{task_id}_source_{original_filename}` | `task_lz1m2x_source_document.pdf` |
| 结果文件 | `{task_id}_result.md`                  | `task_lz1m2x_result.md`           |

## 6. 数据库表结构

```sql
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,           -- 任务 ID
    status TEXT DEFAULT 'pending',      -- 状态
    progress INTEGER DEFAULT 0,         -- 进度 0-100
    message TEXT,                       -- 进度消息
    created_at TIMESTAMP,               -- 创建时间
    updated_at TIMESTAMP,               -- 更新时间
    source_path TEXT,                   -- 源文件路径
    result_path TEXT,                   -- 结果文件路径
    options_json TEXT,                  -- 选项 JSON
    error_message TEXT                  -- 错误消息
);

CREATE INDEX idx_status ON tasks(status);
CREATE INDEX idx_created ON tasks(created_at);
```

## 7. MCP 工具参数格式

### submit_conversion_task

```json
{
  "content": "base64_encoded_file_content...",
  "filename": "document.pdf",
  "options": {
    "enable_ocr": true,
    "ocr_prompt": "Extract all text from this image",
    "ocr_model": "gpt-4o"
  }
}
```

**返回：**

```json
"task_lz1m2x3y4z5a6b7c8d9"
```

### get_task_status

```json
{
  "task_id": "task_lz1m2x3y4z5a6b7c8d9"
}
```

**返回：**

```json
{
  "task_id": "task_lz1m2x3y4z5a6b7c8d9",
  "status": "processing",
  "progress": 45,
  "message": "OCR processing page 5/10",
  "created_at": "2026-04-10T09:30:00",
  "updated_at": "2026-04-10T09:32:15"
}
```

### get_task_result

```json
{
  "task_id": "task_lz1m2x3y4z5a6b7c8d9"
}
```

**返回：**

```markdown
# Document Title

Content extracted from the document...
```

### cancel_task

```json
{
  "task_id": "task_lz1m2x3y4z5a6b7c8d9"
}
```

**返回：**

```json
true  // 或 false（如果任务已完成或不存在）
```

### list_tasks

```json
{
  "status": "processing",
  "limit": 10
}
```

**返回：**

```json
[
  {
    "task_id": "task_lz1m2x3y4z5a6b7c8d9",
    "status": "processing",
    "progress": 45,
    "message": "OCR processing page 5/10",
    "created_at": "2026-04-10T09:30:00",
    "updated_at": "2026-04-10T09:32:15"
  },
  ...
]
```

### get_supported_formats

**参数：** 无

**返回：**

```json
[
  {"extension": ".pdf", "mimetype": "application/pdf", "ocr_support": true},
  {"extension": ".docx", "mimetype": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "ocr_support": true},
  {"extension": ".xlsx", "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "ocr_support": true},
  {"extension": ".pptx", "mimetype": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "ocr_support": true},
  {"extension": ".jpg", "mimetype": "image/jpeg", "ocr_support": true},
  {"extension": ".png", "mimetype": "image/png", "ocr_support": true},
  ...
]
```

## 8. 错误处理

### 任务未找到

```json
{
  "error": "Task not found"
}
```

### 任务未完成

```json
{
  "error": "Task status is 'processing', not 'completed'"
}
```

### Base64 解码失败

```json
{
  "error": "Invalid Base64 content"
}
```

### OCR API 错误

```json
{
  "event": "task_failed",
  "data": {
    "task_id": "task_xxx",
    "status": "failed",
    "error": "OCR API error: Rate limit exceeded"
  }
}
```

## 9. 时序图

```mermaid
sequenceDiagram
    participant C as MCP Client
    participant M as __main__.py
    participant S as TaskStore
    participant P as TaskProcessor
    participant N as SSE Service
    participant F as File System
    participant D as SQLite

    C->>M: submit_conversion_task(content, filename, options)
    M->>S: create_task_from_base64()
    S->>S: generate_task_id()
    S->>F: save source file
    S->>D: INSERT task (pending)
    S-->>M: task_id
    M->>P: start_processing(task_id)
    P-->>M: asyncio.Task
    M-->>C: task_id

    Note over P: Async processing starts

    P->>S: update_progress(0, "Starting...")
    S->>D: UPDATE (processing)
    S->>N: notify_progress()
    N-->>C: SSE: task_progress

    P->>F: read source file
    P->>P: MarkItDown.convert_stream()
  
    loop Each page (OCR)
        P->>S: update_progress(n, "Page x/y")
        S->>N: notify_progress()
        N-->>C: SSE: task_progress
    end

    P->>S: complete_task(result)
    S->>F: save result.md
    S->>D: UPDATE (completed)
    S->>N: notify_completed()
    N-->>C: SSE: task_completed

    C->>M: get_task_result(task_id)
    M->>S: get_result(task_id)
    S->>F: read result.md
    S-->>M: markdown content
    M-->>C: markdown content
```

## 10. OCR 处理详细流程

```mermaid
flowchart TD
    subgraph PDF["PDF OCR 处理"]
        A1[读取 PDF 文件]
        A2[pdfplumber.open]
        A3[遍历每页]
        A4[提取页面图像]
        A5[调整图像尺寸]
        A6[调用 LLM Vision API]
        A7[合并所有页面文本]
    end

    subgraph LLM["LLM Vision API"]
        B1[构建请求<br/>image_url + prompt]
        B2[发送到 OpenAI/其他 API]
        B3[接收响应<br/>提取的文字]
    end

    A1 --> A2
    A2 --> A3
    A3 --> A4
    A4 --> A5
    A5 --> A6
    A6 --> B1
    B1 --> B2
    B2 --> B3
    B3 --> A7
    A7 --> A3
  
    A3 -.->|进度更新| C1[update_progress]
    C1 -.->|SSE 通知| C2[notify_progress]
```

### OCR 进度计算

| 阶段     | 进度范围 | 说明                 |
| -------- | -------- | -------------------- |
| 初始化   | 0-5%     | 读取 PDF，检测页数   |
| 页面提取 | 5-10%    | 提取每页图像         |
| OCR 处理 | 10-95%   | 每页 OCR（主要时间） |
| 合并结果 | 95-100%  | 合并所有页面文本     |

**进度公式：**

```python
# OCR 部分占 85% 的进度
ocr_progress = 10 + int(page_num / total_pages * 85)
message = f"OCR processing page {page_num}/{total_pages}"
```

---

## 附录：相关文件

| 文件     | 路径                                                                         | 说明              |
| -------- | ---------------------------------------------------------------------------- | ----------------- |
| MCP 入口 | `packages/markitdown-ocr-mcp/src/markitdown_ocr_mcp/__main__.py`           | MCP 工具定义      |
| 任务存储 | `packages/markitdown-ocr-mcp/src/markitdown_ocr_mcp/_task_store.py`        | SQLite + 文件管理 |
| 任务处理 | `packages/markitdown-ocr-mcp/src/markitdown_ocr_mcp/_task_processor.py`    | 异步转换处理      |
| SSE 通知 | `packages/markitdown-ocr-mcp/src/markitdown_ocr_mcp/_sse_notifications.py` | 实时通知服务      |
| OCR 插件 | `packages/markitdown-ocr/src/markitdown_ocr/_pdf_converter_with_ocr.py`    | PDF OCR 转换器    |
