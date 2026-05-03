# 任务队列策略设计文档

## 概述

### 背景

当前 `TaskProcessor` 使用 `ThreadPoolExecutor` 作为唯一并发控制点，但存在以下问题：

- 无队列机制，任务提交即执行，无排队等待
- 无背压控制，超过并发数时线程池阻塞，客户端无感知
- 无优先级控制，大文件/OCR 任务可能阻塞小文件

### 设计目标

1. **引入任务队列**：提供 FIFO 排队和按比例分配两种策略
2. **支持管理员手动调整**：预留 API 接口，允许运行时动态调整队列优先级和配额
3. **最小化侵入性**：复用现有 `ThreadPoolExecutor` + 事件循环架构
4. **可观测性**：暴露队列状态指标，便于运维监控

---

## 架构设计

### 组件关系

```
┌─────────────────────────────────────────────────────────────────┐
│                        API Server                               │
│  POST /tasks     POST /tasks/base64     POST /convert           │
└───────────────────────┬─────────────────────────────────────────┘
                        │ task_id + Task 对象
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                    TaskDispatcher                               │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              TaskQueueRouter                              │  │
│  │                                                           │  │
│  │  策略配置: FIFO / Ratio                                   │  │
│  │  管理员干预: set_priority(), set_ratios(), promote()      │  │
│  └───────┬───────────────────────────────┬───────────────────┘  │
│          │                               │                      │
│  ┌───────▼────────┐           ┌──────────▼──────────────┐       │
│  │  FifoStrategy  │           │   RatioStrategy         │       │
│  │                │           │                         │       │
│  │  _queue: Queue │           │  _small: Queue (40%)    │       │
│  │  max_size=100  │           │  _large: Queue (60%)    │       │
│  └────────────────┘           └─────────────────────────┘       │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │               Scheduler                                   │  │
│  │  - 从队列取任务 → 提交到 ThreadPoolExecutor               │  │
│  │  - 监控空闲槽位，触发拉取                                  │  │
│  │  - 管理员干预：promote/cancel/reorder                     │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│              ThreadPoolExecutor (max_workers=N)                 │
│              现有架构，直接复用                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 策略定义

### 策略 A: 纯 FIFO

所有任务进入单一队列，按提交顺序依次处理。

```
客户端提交任务 → Queue → 按顺序出队 → 执行
```

**适用场景：**
- 任务类型混合，无需区分优先级
- 实现简单，运维成本低
- 适合中小规模部署（<50 TPS）

**配置参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `max_queue_size` | int | 100 | 队列最大容量 |
| `max_concurrent` | int | 3 | 最大并发数 |
| `queue_timeout` | float | 5.0 | 队列满时等待超时（秒） |

**队列满时行为：**
- 返回 HTTP 503 + `Retry-After` 头
- 客户端可重试或提交后轮询状态

### 策略 B: 按比例分配

按文件大小将任务分流到两个独立队列，按配置比例调度。

```
客户端提交任务
    │
    ├── < 5MB ──→ Small Queue (40% 配额) ──┐
    │                                         ├──→ Scheduler → ThreadPoolExecutor
    └── >= 5MB → Large Queue (60% 配额) ──┘
```

**适用场景：**
- 小文件（如 DOCX、XLSX）和大文件（如 PDF OCR）混合
- 需要保证小文件快速响应，不被大任务阻塞
- 适合 OCR 负载高的场景

**配置参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `file_threshold_bytes` | int | 5242880 (5MB) | 小/大文件分界阈值 |
| `small_ratio` | float | 0.4 | 小文件通道配额比例 |
| `large_ratio` | float | 0.6 | 大文件通道配额比例 |
| `max_queue_size` | int | 100 | 总队列容量 |
| `max_concurrent` | int | 3 | 最大并发数 |

**配额调度逻辑：**

```python
# 伪代码
def schedule(self):
    # 计算各通道可用槽位
    small_slots = int(self.max_concurrent * self.small_ratio)
    large_slots = int(self.max_concurrent * self.large_ratio)
    
    # 优先满足小队列（保障低延迟）
    if self._small_queue.qsize() > 0 and small_slots > 0:
        return self._small_queue.get_nowait()
    
    # 大文件通道
    if self._large_queue.qsize() > 0 and large_slots > 0:
        return self._large_queue.get_nowait()
    
    # 弹性：空闲通道任务可借用对方槽位
    if self._small_queue.qsize() > 0 and large_slots > 0:
        return self._small_queue.get_nowait()
    if self._large_queue.qsize() > 0 and small_slots > 0:
        return self._large_queue.get_nowait()
```

---

## 管理员干预 API

### 设计原则

1. **实时生效**：无需重启服务
2. **操作审计**：所有调整操作记录日志
3. **幂等性**：重复请求不产生副作用
4. **回滚机制**：记录操作历史，支持回滚

### API 端点设计

所有管理员端点统一前缀 `/admin`，需要 Bearer Token 认证。

#### GET /admin/queue/stats

获取当前队列状态。

**请求：**
```http
GET /admin/queue/stats
Authorization: Bearer <admin_token>
```

**响应：**
```json
{
  "strategy": "ratio",
  "max_concurrent": 3,
  "total_queued": 12,
  "total_processing": 3,
  "total_completed": 156,
  "total_failed": 2,
  "queues": {
    "fifo": {
      "pending": 12,
      "capacity": 100,
      "utilization": 0.12
    }
  },
  "ratio": null,
  "active_tasks": [
    {
      "task_id": "task_20260503_091234_abcd1234",
      "filename": "report.pdf",
      "status": "processing",
      "progress": 45,
      "started_at": "2026-05-03T09:12:34Z",
      "duration_seconds": 23.5
    }
  ]
}
```

**策略为 FIFO 时的响应：**
```json
{
  "strategy": "fifo",
  "max_concurrent": 3,
  "queues": {
    "fifo": {
      "pending": 12,
      "capacity": 100,
      "utilization": 0.12
    }
  },
  "ratio": null
}
```

**策略为 Ratio 时的响应：**
```json
{
  "strategy": "ratio",
  "small_queue": {
    "pending": 5,
    "capacity": 40,
    "utilization": 0.125
  },
  "large_queue": {
    "pending": 7,
    "capacity": 60,
    "utilization": 0.117
  },
  "ratio": {
    "small": 0.4,
    "large": 0.6
  }
}
```

#### POST /admin/queue/priority

提升指定任务优先级（插入队列头部）。

**请求：**
```http
POST /admin/queue/priority
Authorization: Bearer <admin_token>
Content-Type: application/json

{
  "task_id": "task_20260503_091234_abcd1234"
}
```

**响应：**
```json
{
  "task_id": "task_20260503_091234_abcd1234",
  "status": "promoted",
  "message": "Task promoted to head of queue",
  "previous_position": 12,
  "new_position": 1
}
```

**错误响应：**
```json
{
  "error": "Task not found in queue",
  "detail": "Task is currently processing or already completed"
}
```

#### PUT /admin/queue/strategy

动态切换队列策略。

**请求：**
```http
PUT /admin/queue/strategy
Authorization: Bearer <admin_token>
Content-Type: application/json

{
  "strategy": "fifo",
  "params": {
    "max_concurrent": 5,
    "max_queue_size": 200
  }
}
```

**策略参数：**

FIFO 策略参数：
```json
{
  "strategy": "fifo",
  "params": {
    "max_concurrent": 5,
    "max_queue_size": 200,
    "queue_timeout": 10.0
  }
}
```

Ratio 策略参数：
```json
{
  "strategy": "ratio",
  "params": {
    "max_concurrent": 5,
    "max_queue_size": 200,
    "small_ratio": 0.3,
    "large_ratio": 0.7,
    "file_threshold_bytes": 10485760
  }
}
```

**响应：**
```json
{
  "previous_strategy": "fifo",
  "current_strategy": "ratio",
  "status": "switching",
  "message": "Strategy switch initiated. Queue draining in progress.",
  "note": "Tasks currently in queue will be processed before switch completes."
}
```

**切换行为：**
1. 拒绝新任务提交（返回 503）
2. 等待队列中现有任务处理完成（最多等待 60 秒）
3. 切换策略实例
4. 恢复接受新任务
5. 如果 60 秒内未完成，强制清空队列（保留任务记录）

#### DELETE /admin/queue/task

从队列中移除指定任务（仅对 pending 状态有效）。

**请求：**
```http
DELETE /admin/queue/task
Authorization: Bearer <admin_token>

{
  "task_id": "task_20260503_091234_abcd1234"
}
```

**响应：**
```json
{
  "task_id": "task_20260503_091234_abcd1234",
  "status": "removed",
  "message": "Task removed from queue"
}
```

#### PUT /admin/queue/ratios

调整按比例分配策略中的通道配额比例。

**请求：**
```http
PUT /admin/queue/ratios
Authorization: Bearer <admin_token>
Content-Type: application/json

{
  "small_ratio": 0.5,
  "large_ratio": 0.5
}
```

**响应：**
```json
{
  "previous_ratios": {
    "small": 0.4,
    "large": 0.6
  },
  "current_ratios": {
    "small": 0.5,
    "large": 0.5
  },
  "status": "updated",
  "message": "Ratios updated. New allocation will take effect immediately."
}
```

**验证规则：**
- `small_ratio + large_ratio == 1.0`，否则返回 400
- `0 < ratio < 1.0`，否则返回 400

---

## 数据模型

### QueueStats

```python
@dataclass
class QueueStats:
    """队列状态统计"""
    strategy: str                              # "fifo" | "ratio"
    max_concurrent: int                        # 最大并发数
    total_queued: int                          # 当前排队总数
    total_processing: int                      # 当前处理中
    total_completed: int                       # 历史完成数
    total_failed: int                          # 历史失败数
    
    # FIFO 专用
    fifo_pending: int = 0
    fifo_capacity: int = 100
    
    # Ratio 专用
    small_pending: int = 0
    large_pending: int = 0
    small_capacity: int = 40
    large_capacity: int = 60
    
    # 通用
    small_ratio: float = 0.4
    large_ratio: float = 0.6


@dataclass
class ActiveTaskInfo:
    """活跃任务信息"""
    task_id: str
    filename: str
    status: str                                # "processing"
    progress: int
    started_at: str                            # ISO 8601
    duration_seconds: float


@dataclass
class QueueOperationLog:
    """队列操作日志"""
    timestamp: str                             # ISO 8601
    operator: str                              # 操作者（IP 或用户名）
    action: str                                # "promote" | "switch_strategy" | "update_ratios" | "remove"
    task_id: Optional[str] = None
    previous_state: Optional[dict] = None
    new_state: Optional[dict] = None
    success: bool = True
    error: Optional[str] = None
```

---

## 实现方案

### 文件变更

| 文件 | 变更内容 |
|------|---------|
| `core/task_queue.py` | **新增** - 队列策略抽象 + FIFO + Ratio 实现 |
| `core/task_processor.py` | 修改 - 注入队列策略，替换直接提交逻辑 |
| `core/models.py` | 修改 - 新增 `QueueStats`、`ActiveTaskInfo` 数据模型 |
| `api.py` | 修改 - 新增 `/admin` 路由 |
| `auth.py` | 修改 - 新增 admin token 验证中间件 |

### 核心接口

```python
# core/task_queue.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class QueueResult:
    """提交结果"""
    accepted: bool
    task_id: str
    position: int = 0
    message: str = ""


class TaskDispatchStrategy(ABC):
    """任务分发策略抽象基类"""
    
    @property
    @abstractmethod
    def strategy_name(self) -> str:
        ...
    
    @abstractmethod
    async def enqueue(self, task_id: str, task: Task) -> QueueResult:
        """提交任务到队列"""
        ...
    
    @abstractmethod
    async def dequeue(self) -> Optional[str]:
        """从队列取出下一个任务 ID"""
        ...
    
    @abstractmethod
    def get_stats(self) -> dict:
        """获取队列统计"""
        ...
    
    @abstractmethod
    async def promote_task(self, task_id: str) -> dict:
        """提升任务到队列头部"""
        ...
    
    @abstractmethod
    async def remove_task(self, task_id: str) -> bool:
        """从队列移除任务"""
        ...
    
    @abstractmethod
    async def set_ratios(self, small_ratio: float, large_ratio: float) -> dict:
        """设置通道比例（仅 Ratio 策略）"""
        ...


class FifoStrategy(TaskDispatchStrategy):
    """纯 FIFO 策略"""
    
    def __init__(self, max_queue_size: int = 100):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._positions: dict[str, int] = {}  # task_id → queue position
        self._counter: int = 0
        self.max_queue_size = max_queue_size
    
    @property
    def strategy_name(self) -> str:
        return "fifo"
    
    async def enqueue(self, task_id: str, task: Task) -> QueueResult:
        self._counter += 1
        position = self._counter
        self._positions[task_id] = position
        
        try:
            await asyncio.wait_for(
                self._queue.put((position, task_id, task)),
                timeout=5.0
            )
            return QueueResult(
                accepted=True,
                task_id=task_id,
                position=self._queue.qsize(),
                message=f"Task queued at position {self._queue.qsize()}"
            )
        except asyncio.TimeoutError:
            del self._positions[task_id]
            return QueueResult(
                accepted=False,
                task_id=task_id,
                message="Queue is full, try again later"
            )
    
    async def dequeue(self) -> Optional[str]:
        try:
            position, task_id, task = await asyncio.wait_for(
                self._queue.get(), timeout=0.1
            )
            self._positions.pop(task_id, None)
            return task_id
        except asyncio.TimeoutError:
            return None
    
    async def promote_task(self, task_id: str) -> dict:
        if task_id not in self._positions:
            return {"success": False, "error": "Task not found in queue"}
        
        # 从队列中移除（需要重建队列）
        items = []
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                if item[1] != task_id:
                    items.append(item)
            except asyncio.QueueEmpty:
                break
        
        # 重新插入队首
        new_position = 0
        self._queue.put_nowait((new_position, task_id, None))
        
        for item in items:
            self._queue.put_nowait(item)
        
        self._positions[task_id] = new_position
        return {"success": True, "position": new_position}
    
    async def remove_task(self, task_id: str) -> bool:
        if task_id not in self._positions:
            return False
        
        items = []
        found = False
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                if item[1] == task_id:
                    found = True
                else:
                    items.append(item)
            except asyncio.QueueEmpty:
                break
        
        for item in items:
            self._queue.put_nowait(item)
        
        self._positions.pop(task_id, None)
        return found


class RatioStrategy(TaskDispatchStrategy):
    """按比例分配策略"""
    
    def __init__(
        self,
        small_ratio: float = 0.4,
        large_ratio: float = 0.6,
        file_threshold_bytes: int = 5 * 1024 * 1024,
        max_queue_size: int = 100
    ):
        small_capacity = int(max_queue_size * small_ratio)
        large_capacity = int(max_queue_size * large_ratio)
        
        self._small_queue: asyncio.Queue = asyncio.Queue(maxsize=small_capacity)
        self._large_queue: asyncio.Queue = asyncio.Queue(maxsize=large_capacity)
        
        self._small_counter = 0
        self._large_counter = 0
        
        self._small_positions: dict[str, int] = {}
        self._large_positions: dict[str, int] = {}
        
        self.small_ratio = small_ratio
        self.large_ratio = large_ratio
        self.file_threshold_bytes = file_threshold_bytes
        self.max_queue_size = max_queue_size
    
    @property
    def strategy_name(self) -> str:
        return "ratio"
    
    async def enqueue(self, task_id: str, task: Task) -> QueueResult:
        # 按文件大小分流
        if len(task.content) < self.file_threshold_bytes:
            queue = self._small_queue
            positions = self._small_positions
            counter_name = "_small_counter"
        else:
            queue = self._large_queue
            positions = self._large_positions
            counter_name = "_large_counter"
        
        # 使用计数器维护优先级
        global_counter = getattr(self, counter_name) + 1
        setattr(self, counter_name, global_counter)
        position = global_counter
        positions[task_id] = position
        
        try:
            await asyncio.wait_for(
                queue.put((position, task_id, task)),
                timeout=5.0
            )
            return QueueResult(
                accepted=True,
                task_id=task_id,
                position=queue.qsize(),
                message=f"Task queued in {'small' if len(task.content) < self.file_threshold_bytes else 'large'} queue"
            )
        except asyncio.TimeoutError:
            positions.pop(task_id, None)
            return QueueResult(
                accepted=False,
                task_id=task_id,
                message="Queue is full, try again later"
            )
    
    async def dequeue(self) -> Optional[str]:
        # 优先小队列
        try:
            position, task_id, task = await asyncio.wait_for(
                self._small_queue.get(), timeout=0.05
            )
            self._small_positions.pop(task_id, None)
            return task_id
        except asyncio.TimeoutError:
            pass
        
        # 再尝试队列
        try:
            position, task_id, task = await asyncio.wait_for(
                self._large_queue.get(), timeout=0.05
            )
            self._large_positions.pop(task_id, None)
            return task_id
        except asyncio.TimeoutError:
            return None
    
    async def set_ratios(self, small_ratio: float, large_ratio: float) -> dict:
        if abs(small_ratio + large_ratio - 1.0) > 0.001:
            return {"success": False, "error": "Ratios must sum to 1.0"}
        if not (0 < small_ratio < 1.0 and 0 < large_ratio < 1.0):
            return {"success": False, "error": "Ratios must be between 0 and 1"}
        
        old_small = self.small_ratio
        old_large = self.large_ratio
        self.small_ratio = small_ratio
        self.large_ratio = large_ratio
        
        return {
            "success": True,
            "previous_ratios": {"small": old_small, "large": old_large},
            "current_ratios": {"small": small_ratio, "large": large_ratio}
        }
```

### TaskProcessor 集成

```python
# core/task_processor.py 修改点

class TaskProcessor:
    def __init__(
        self,
        task_store: TaskStore,
        enable_ocr: bool = False,
        progress_callback: Optional[Callable] = None,
        max_concurrent: int = 3,
        dispatch_strategy: TaskDispatchStrategy = None,
    ):
        self.dispatch_strategy = dispatch_strategy or FifoStrategy()
        # ... 其余不变
        
    async def _scheduler_loop(self):
        """调度器循环：从队列取任务并提交执行"""
        while True:
            active = len(self._processing_tasks)
            if active < self.max_concurrent:
                task_id = await self.dispatch_strategy.dequeue()
                if task_id:
                    self._processing_tasks[task_id] = asyncio.create_task(
                        self._process_task(task_id)
                    )
            await asyncio.sleep(0.1)
    
    def start_processing(self, task_id: str):
        """重写：提交到队列而非直接执行"""
        task = self.task_store.get_task(task_id)
        loop = asyncio.get_event_loop()
        
        async def _enqueue():
            result = await self.dispatch_strategy.enqueue(task_id, task)
            if not result.accepted:
                # 队列满，标记任务失败
                self.task_store.update_task(
                    task_id,
                    status=TaskStatus.FAILED,
                    message="Queue full"
                )
        
        loop.create_task(_enqueue())
```

---

## 配置方式

### 环境变量

```bash
# 队列策略选择
MARKITDOWN_DISPATCH_STRATEGY=fifo                    # 或 ratio

# FIFO 策略参数
MARKITDOWN_MAX_QUEUE_SIZE=100
MARKITDOWN_QUEUE_TIMEOUT=5.0

# Ratio 策略参数
MARKITDOWN_SMALL_RATIO=0.4
MARKITDOWN_LARGE_RATIO=0.6
MARKITDOWN_FILE_THRESHOLD_MB=5

# 管理员 API 密钥
MARKITDOWN_ADMIN_TOKEN=your-admin-token-here
```

### pyproject.toml

```toml
[project.scripts]
markitdown-server = "markitdown_server.__main__:main"

[tool.poetry.dependencies]
# 新增
python-dateutil = "^2.8.2"
```

---

## 安全性

### 管理员 API 认证

```python
# api.py

async def admin_auth_middleware(request: Request, call_next):
    if request.url.path.startswith("/admin/"):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        expected = os.getenv("MARKITDOWN_ADMIN_TOKEN")
        if not expected or token != expected:
            return JSONResponse(
                status_code=401,
                content={"error": "Unauthorized"}
            )
    
    response = await call_next(request)
    return response
```

### 操作审计日志

```python
import logging

admin_logger = logging.getLogger("markitdown.admin")

async def log_admin_operation(action: str, **kwargs):
    admin_logger.info(
        f"ADMIN_ACTION: action={action} | "
        f"ip={request.client.host} | "
        f"{json.dumps(kwargs)}"
    )
```

---

## 可观测性

### Prometheus Metrics

```python
from prometheus_client import Counter, Histogram, Gauge

# 队列指标
queue_size_gauge = Gauge(
    "markitdown_queue_size",
    "Current number of tasks in queue"
)

queue_depth_by_channel_gauge = Gauge(
    "markitdown_queue_depth_by_channel",
    "Queue depth by channel",
    ["channel"]  # "fifo" | "small" | "large"
)

active_tasks_gauge = Gauge(
    "markitdown_active_tasks",
    "Number of tasks currently processing"
)

# 延迟指标
task_enqueue_latency = Histogram(
    "markitdown_task_enqueue_latency_seconds",
    "Time from submission to dequeued"
)

# 计数指标
total_tasks_enqueued_counter = Counter(
    "markitdown_tasks_enqueued_total",
    "Total tasks enqueued",
    ["strategy"]  # "fifo" | "ratio"
)

total_tasks_rejected_counter = Counter(
    "markitdown_tasks_rejected_total",
    "Total tasks rejected (queue full)"
)
```

### HTTP 指标头

```http
HTTP/1.1 200 OK
X-Queue-Stats: queued=12,processing=3,completed=156
X-Strategy: ratio
```

---

## 实施计划

### 阶段一：FIFO 队列基础

| 任务 | 预估工时 | 依赖 |
|------|---------|------|
| 实现 `FifoStrategy` | 2h | 无 |
| 修改 `TaskProcessor` 注入队列 | 1h | `FifoStrategy` |
| 修改 `start_processing` 提交到队列 | 1h | 上一步 |
| 单元测试 | 2h | 上一步 |
| `/admin/queue/stats` 端点 | 1h | 上一步 |
| **小计** | **7h** | |

### 阶段二：按比例分配策略

| 任务 | 预估工时 | 依赖 |
|------|---------|------|
| 实现 `RatioStrategy` | 3h | 无 |
| 策略切换 API (`PUT /admin/queue/strategy`) | 2h | 上一步 |
| 比例调整 API (`PUT /admin/queue/ratios`) | 1h | 上一步 |
| 集成测试 | 2h | 上一步 |
| **小计** | **8h** | |

### 阶段三：管理员干预 API

| 任务 | 预估工时 | 依赖 |
|------|---------|------|
| `POST /admin/queue/priority` (提升任务) | 2h | 阶段一或二 |
| `DELETE /admin/queue/task` (移除任务) | 1h | 阶段一或二 |
| 操作审计日志 | 1h | 无 |
| Prometheus metrics | 2h | 无 |
| **小计** | **6h** | |

**总计：约 21h（3 个工作日）**

---

## 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 策略切换时队列中任务丢失 | 高 | 切换前拒绝新任务，等待现有任务完成或强制超时 |
| `asyncio.Queue` 内存占用 | 中 | 限制 `max_queue_size`，任务只存路径不存 content |
| promote 操作需要重建队列 | 低 | 当前实现需要遍历队列，影响小（异步非阻塞） |
| 管理员 token 泄露 | 高 | token 通过环境变量配置，不记录日志 |
| 策略热切换后旧策略对象泄漏 | 中 | 切换时引用计数归零，GC 自动回收 |

---

## 附录

### 参考：现有并发控制问题

当前实现 (`task_processor.py:78-140`)：

```python
def start_processing(self, task_id: str):
    # 无队列检查，直接创建 task
    loop = self._ensure_loop()
    def _create_and_track():
        task = loop.create_task(self._process_task(task_id))
        self._processing_tasks[task_id] = task
    loop.call_soon_threadsafe(_create_and_track)
```

问题：
1. 无队列排队，任务立即执行
2. 无背压，超过并发数时客户端无感知
3. `ThreadPoolExecutor` 在任务满时阻塞，导致死锁风险

### 相关文件索引

| 文件 | 说明 |
|------|------|
| `packages/markitdown-server/src/markitdown_server/core/task_processor.py` | 任务处理器（需修改） |
| `packages/markitdown-server/src/markitdown_server/core/task_store.py` | 任务存储（无需修改） |
| `packages/markitdown-server/src/markitdown_server/api.py` | API 路由（需新增 admin 端点） |
| `packages/markitdown-server/src/markitdown_server/core/models.py` | 数据模型（需新增 QueueStats） |
| `packages/markitdown-server/src/markitdown_server/app.py` | 应用初始化（需注入策略配置） |

---

*文档创建时间：2026-05-03*
*作者：Maria (AI Assistant)*
*状态：待评审*
