# MarkItDown API 代码审计报告

## 审计概述

**审计日期**: 2026-04-13
**审计范围**: `packages/markitdown-api`
**审计目的**: 安全性、代码质量、最佳实践检查

---

## 1. 安全问题

### 1.1 🔴 高风险 - CORS 配置过于宽松

**文件**: [`server.py`](packages/markitdown-api/src/markitdown_api/server.py:66)

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**问题**: 
- `allow_origins=["*"]` 允许任何来源访问 API
- 与 `allow_credentials=True` 组合使用存在安全风险

**建议修复**:
```python
# 从环境变量读取允许的来源
ALLOWED_ORIGINS = os.getenv("MARKITDOWN_API_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000")
allowed_origins = ALLOWED_ORIGINS.split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,  # 或仅在需要时启用
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
```

### 1.2 🔴 高风险 - 文件上传无大小限制

**文件**: [`server.py`](packages/markitdown-api/src/markitdown_api/server.py:137)

```python
content = await file.read()  # 无大小限制
```

**问题**: 
- 没有对上传文件大小进行限制
- 可能导致内存耗尽攻击

**建议修复**:
```python
# 添加文件大小限制
MAX_FILE_SIZE = int(os.getenv("MARKITDOWN_MAX_FILE_SIZE_MB", "100")) * 1024 * 1024

@app.post("/tasks", response_model=SubmitTaskResponse)
async def submit_task(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., max_length=MAX_FILE_SIZE),  # 添加限制
    ...
):
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large")
```

### 1.3 🟡 中风险 - 文件名未验证

**文件**: [`server.py`](packages/markitdown-api/src/markitdown_api/server.py:149)

```python
task = task_store.create_task(task_id, content, file.filename or "unknown", options)
```

**问题**: 
- 用户提供的文件名直接使用，可能包含路径遍历字符
- 可能导致文件写入到意外位置

**建议修复**:
```python
import re

def sanitize_filename(filename: str) -> str:
    """清理文件名，移除危险字符"""
    # 移除路径分隔符和特殊字符
    filename = re.sub(r'[\\/*?:"<>|]', '_', filename)
    # 移除路径遍历
    filename = filename.replace('..', '_')
    # 限制长度
    return filename[:255]

safe_filename = sanitize_filename(file.filename or "unknown")
```

### 1.4 🟡 中风险 - SQL 注入风险（低）

**文件**: [`task_store.py`](packages/markitdown-api/src/markitdown_api/task_store.py:350)

```python
cursor.execute(
    f"UPDATE tasks SET {', '.join(updates)} WHERE task_id = ?",
    values
)
```

**问题**: 
- 使用 f-string 构建 SQL 查询
- 但 `updates` 内容由代码控制，非用户输入，风险较低

**建议**: 当前实现安全，但建议使用更明确的方式：
```python
# 使用参数化查询构建
update_fields = []
if status is not None:
    update_fields.append(("status", status.value))
# ... 其他字段
```

### 1.5 🟢 低风险 - Bearer Token 时效验证

**文件**: [`auth.py`](packages/markitdown-api/src/markitdown_api/auth.py:64)

```python
if token != api_key:
    raise HTTPException(...)
```

**问题**: 
- Token 无过期时间
- 无 JWT 签名验证

**建议**: 对于简单场景足够，生产环境建议使用 JWT：
```python
# 可选：使用 JWT
import jwt

def verify_jwt_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        if payload.get("exp") < time.time():
            raise HTTPException(status_code=401, detail="Token expired")
        return payload
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
```

---

## 2. 代码质量问题

### 2.1 🟡 未使用的导入

**文件**: [`server.py`](packages/markitdown-api/src/markitdown_api/server.py:10)

```python
import asyncio  # 未使用
```

**建议**: 移除未使用的导入

### 2.2 🟡 未使用的模型

**文件**: [`models.py`](packages/markitdown-api/src/markitdown_api/models.py:24)

```python
class ConversionOptions(BaseModel):  # 定义但未在 API 中使用
class SubmitTaskRequest(BaseModel):  # 定义但未使用
class ErrorResponse(BaseModel):      # 定义但未使用
```

**建议**: 移除或实际使用这些模型

### 2.3 🟡 全局状态管理

**文件**: [`task_store.py`](packages/markitdown-api/src/markitdown_api/task_store.py:444)

```python
_task_store: Optional[TaskStore] = None

def get_task_store() -> TaskStore:
    global _task_store
    if _task_store is None:
        ...
```

**问题**: 
- 使用全局单例模式
- 多进程环境下可能有问题

**建议**: 使用依赖注入：
```python
from functools import lru_cache

@lru_cache()
def get_task_store() -> TaskStore:
    return TaskStore(os.getenv("MARKITDOWN_STORAGE_DIR", "./storage"))
```

### 2.4 🟡 异步处理问题

**文件**: [`task_processor.py`](packages/markitdown-api/src/markitdown_api/task_processor.py:90)

```python
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

task = loop.create_task(process_wrapper())
self._processing_tasks[task_id] = task

threading.Thread(
    target=loop.run_forever,
    daemon=True
).start()
```

**问题**: 
- 每个任务创建新的 event loop 和线程
- 资源浪费，可能导致线程泄漏

**建议**: 使用共享的 event loop：
```python
# 使用全局 event loop 或 FastAPI 的 background tasks
class TaskProcessor:
    def __init__(self):
        self._loop = asyncio.get_event_loop() or asyncio.new_event_loop()
        self._executor = ThreadPoolExecutor(max_workers=self.max_concurrent)
    
    def start_processing(self, task_id: str):
        future = asyncio.run_coroutine_threadsafe(
            self._process_task(task_id),
            self._loop
        )
        self._processing_tasks[task_id] = future
```

### 2.5 🟡 错误处理不完整

**文件**: [`task_store.py`](packages/markitdown-api/src/markitdown_api/task_store.py:255)

```python
for month_dir in os.listdir(year_path):  # 可能抛出 OSError
    month_path = os.path.join(year_path, month_dir)
    for day_dir in os.listdir(month_path):  # 可能抛出 OSError
```

**建议**: 添加异常处理：
```python
try:
    for year_dir in os.listdir(self.storage_dir):
        ...
except OSError as e:
    logger.warning(f"Error listing storage directory: {e}")
    return b""
```

---

## 3. 最佳实践建议

### 3.1 添加请求速率限制

```python
from fastapi import Request
from slowapi import Limiter

limiter = Limiter(key_func=get_remote_address)

@app.post("/tasks")
@limiter.limit("10/minute")
async def submit_task(request: Request, ...):
    ...
```

### 3.2 添加输入验证

```python
from pydantic import validator

class SubmitTaskRequest(BaseModel):
    filename: str
    
    @validator('filename')
    def validate_filename(cls, v):
        if '..' in v or '/' in v or '\\' in v:
            raise ValueError('Invalid filename')
        return v
```

### 3.3 添加日志审计

```python
import logging

logger = logging.getLogger("markitdown_api.audit")

@app.post("/tasks")
async def submit_task(...):
    logger.info(f"Task submitted: {task_id}, filename={filename}, size={len(content)}")
    ...
```

### 3.4 添加健康检查详情

```python
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "version": __version__,
        "uptime": time.time() - _server_start_time,
        "storage": {
            "available": os.path.exists(os.getenv("MARKITDOWN_STORAGE_DIR", "./storage")),
            "size": get_storage_size(),
        },
        "active_tasks": get_task_processor().get_active_count(),
    }
```

### 3.5 添加 API 版本控制

```python
app = FastAPI(
    title="MarkItDown API",
    version=__version__,
    description="RESTful API for converting files to Markdown",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
)

# 所有路由添加 /api/v1 前缀
app.include_router(api_router, prefix="/api/v1")
```

---

## 4. 性能问题

### 4.1 🟡 文件内容存储在内存

**文件**: [`task_store.py`](packages/markitdown-api/src/markitdown_api/task_store.py:30)

```python
@dataclass
class Task:
    content: bytes  # 原始文件内容存储在内存
```

**问题**: 
- 大文件会占用大量内存
- 每次获取任务都会加载完整内容

**建议**: 
- 文件内容只存储在磁盘
- Task 类中只存储文件路径引用

### 4.2 🟡 SQLite 并发限制

**文件**: [`task_store.py`](packages/markitdown-api/src/markitdown_api/task_store.py:64)

```python
self._local.conn = sqlite3.connect(db_path, check_same_thread=False)
```

**问题**: 
- SQLite 写操作并发性能有限
- 高并发场景可能成为瓶颈

**建议**: 
- 使用连接池
- 或考虑使用 PostgreSQL/MySQL

---

## 5. 审计总结

| 类别 | 高风险 | 中风险 | 低风险 | 建议 |
|------|--------|--------|--------|------|
| 安全 | 2 | 2 | 1 | 立即修复 CORS 和文件大小限制 |
| 代码质量 | 0 | 5 | 0 | 清理未使用代码，改进异步处理 |
| 性能 | 0 | 2 | 0 | 优化内存使用，考虑数据库升级 |
| 最佳实践 | 0 | 0 | 0 | 添加速率限制、审计日志 |

### 优先修复项

1. **立即修复**: CORS 配置、文件大小限制
2. **短期修复**: 文件名验证、异步处理优化
3. **长期改进**: 添加速率限制、审计日志、API 版本控制

---

## 6. 修复建议代码

### 6.1 安全配置文件

创建 `packages/markitdown-api/src/markitdown_api/security.py`:

```python
"""Security utilities for API protection."""

import os
import re
from typing import List

# Maximum file size (default 100MB)
MAX_FILE_SIZE_MB = int(os.getenv("MARKITDOWN_MAX_FILE_SIZE_MB", "100"))
MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024

# Allowed CORS origins
ALLOWED_ORIGINS = os.getenv(
    "MARKITDOWN_API_ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:8000"
).split(",")


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename to prevent path traversal attacks.
    
    Args:
        filename: Original filename
        
    Returns:
        Safe filename
    """
    # Remove path separators and special characters
    filename = re.sub(r'[\\/*?:"<>|]', '_', filename)
    # Remove path traversal
    filename = filename.replace('..', '_')
    # Limit length
    return filename[:255]


def validate_file_size(content: bytes) -> bool:
    """
    Validate file size is within limits.
    
    Args:
        content: File content
        
    Returns:
        True if valid, False otherwise
    """
    return len(content) <= MAX_FILE_SIZE


def get_allowed_origins() -> List[str]:
    """Get list of allowed CORS origins."""
    return [origin.strip() for origin in ALLOWED_ORIGINS if origin.strip()]
```

### 6.2 更新 server.py 使用安全配置

```python
from .security import sanitize_filename, validate_file_size, get_allowed_origins, MAX_FILE_SIZE

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# 文件上传
@app.post("/tasks", response_model=SubmitTaskResponse)
async def submit_task(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    ...
):
    content = await file.read()
    
    # 验证文件大小
    if not validate_file_size(content):
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE_MB}MB"
        )
    
    # 清理文件名
    safe_filename = sanitize_filename(file.filename or "unknown")
    
    task = task_store.create_task(task_id, content, safe_filename, options)
    ...
```

---

**审计完成**。建议按优先级逐步修复上述问题。