# 任务队列策略实现 - 全面代码审计报告

## 审计概览

| 项目 | 信息 |
|------|------|
| 审计日期 | 2026-05-03 |
| 审计范围 | 任务队列策略设计与实现 |
| 审计文件 | `core/task_queue.py`, `core/task_processor.py`, `core/models.py`, `api.py`, `core/auth.py`, `app.py` |
| 参考文档 | `docs/design/task-queue-strategy-design.md` |
| 审计人员 | Maria (AI Assistant) |
| 审计结论 | ⚠️ **基本符合设计，但存在关键缺陷** |

---

## 一、架构合理性评估

### 1.1 组件关系验证 ✅ 符合设计

**设计文档中的架构：**
```
API Server → TaskDispatcher → TaskQueueRouter → Strategy(Fifo/Ratio) → Scheduler → ThreadPoolExecutor
```

**实际实现架构：**
```
api.py → TaskProcessor → TaskDispatchStrategy → FifoStrategy/RatioStrategy → _scheduler_loop → ThreadPoolExecutor
```

**评估结论：**
- ✅ 策略抽象基类 `TaskDispatchStrategy` 设计正确，符合开闭原则
- ✅ `FifoStrategy` 和 `RatioStrategy` 分离清晰，各自独立维护队列
- ✅ `TaskDispatchStrategyFactory` 工厂类简化策略创建
- ⚠️ 设计中的 `TaskDispatcher` 和 `TaskQueueRouter` 被合并到 `TaskProcessor`，虽然简化了架构但耦合度增加
- ⚠️ 设计中的独立 `Scheduler` 被整合为 `_scheduler_loop()`，无法独立监控和管理

### 1.2 策略模式实现 ✅ 合理

**优点：**
- `TaskDispatchStrategy` 抽象基类定义清晰，接口完整
- 策略可通过 `set_dispatch_strategy()` 动态切换
- 工厂模式简化配置

**缺点：**
- 策略切换未实现设计文档中的「队列排空后切换」逻辑（见设计文档第 331-334 行）
- 切换时未拒绝新任务提交，可能导致队列中任务丢失

### 1.3 线程模型 ⚠️ 存在隐患

**当前实现：**
```python
# task_processor.py:136-143
def _ensure_loop(self) -> asyncio.AbstractEventLoop:
    with self._loop_lock:
        if self._loop is None or not self._loop.is_running():
            self._loop = asyncio.new_event_loop()
            self._loop_thread = threading.Thread(target=self._loop.run_forever, daemon=True)
            self._loop_thread.start()
```

**问题分析：**
- ✅ 使用独立线程运行事件循环，避免阻塞主线程
- ⚠️ `_loop_lock` 只保护 `self._loop` 的创建，不保护后续使用
- ⚠️ `daemon=True` 线程在进程退出时可能未完成任务清理
- ⚠️ 多次调用 `_ensure_loop()` 在极端场景下可能创建多个 loop

---

## 二、实现完整性审查

### 2.1 设计文档对照检查

| 设计要求 | 实现状态 | 说明 |
|----------|----------|------|
| FIFO 策略 | ✅ 已实现 | `FifoStrategy` 类，支持 `max_queue_size`, `queue_timeout` |
| Ratio 策略 | ✅ 已实现 | `RatioStrategy` 类，支持按文件大小分流 |
| 策略切换 API (`PUT /admin/queue/strategy`) | ✅ 已实现 | `api.py:320-339` |
| 比例调整 API (`PUT /admin/queue/ratios`) | ✅ 已实现 | `api.py:341-362` |
| 提升优先级 API (`POST /admin/queue/priority`) | ✅ 已实现 | `api.py:302-318` |
| 移除任务 API (`DELETE /admin/queue/task`) | ✅ 已实现 | `api.py:364-378` |
| 队列状态 API (`GET /admin/queue/stats`) | ✅ 已实现 | `api.py:297-300` |
| 队列满返回 503 + Retry-After | ❌ **未实现** | 当前返回队列为满时标记任务失败 |
| 配额弹性借用机制 | ❌ **未实现** | Ratio 策略 dequeue 固定顺序，无借用逻辑 |
| 策略切换「排空队列」逻辑 | ❌ **未实现** | 直接替换策略实例，可能丢失任务 |
| Prometheus Metrics | ❌ **未实现** | 无 metrics 暴露 |
| HTTP 指标头 (`X-Queue-Stats`) | ❌ **未实现** | 无响应头注入 |
| 操作审计日志 | ⚠️ **部分实现** | 有 logger 但无结构化审计记录 |

### 2.2 关键功能缺失详情

#### ❌ F-001: 队列满未返回 HTTP 503

**设计要求（设计文档第 91-92 行）：**
- 队列满时返回 HTTP 503 + `Retry-After` 头
- 客户端可重试或提交后轮询状态

**当前实现：**
```python
# task_processor.py:158-166
if not result.accepted:
    self.task_store.update_task(
        task_id,
        status=TaskStatus.FAILED,
        progress=-1,
        message="Queue full",
        error="Queue is full, try again later",
    )
```

**问题：**
- 任务被标记为 `FAILED` 而非排队等待
- 客户端收到 200 OK + task_id，需要轮询才能发现失败
- 不符合设计文档的背压控制预期

---

#### ❌ F-002: Ratio 策略缺少配额弹性借用

**设计要求（设计文档第 138-142 行）：**
```python
# 弹性：空闲通道任务可借用对方槽位
if self._small_queue.qsize() > 0 and large_slots > 0:
    return self._small_queue.get_nowait()
if self._large_queue.qsize() > 0 and small_slots > 0:
    return self._large_queue.get_nowait()
```

**当前实现：**
```python
# task_queue.py:279-296
async def dequeue(self) -> Optional[str]:
    # 优先小队列
    try:
        return await self._small_queue.get(timeout=0.05)
    except asyncio.TimeoutError:
        pass
    # 再尝试大队列
    try:
        return await self._large_queue.get(timeout=0.05)
    except asyncio.TimeoutError:
        return None
```

**问题：**
- 固定顺序 dequeue（先 small 后 large）
- 无配额管理，不检查当前各通道活跃任务数
- 可能导致小队列空时大队列任务饿死

---

#### ❌ F-003: 策略切换未排空队列

**设计要求（设计文档第 330-334 行）：**
```
切换行为：
1. 拒绝新任务提交（返回 503）
2. 等待队列中现有任务处理完成（最多等待 60 秒）
3. 切换策略实例
4. 恢复接受新任务
5. 如果 60 秒内未完成，强制清空队列（保留任务记录）
```

**当前实现：**
```python
# api.py:320-339
@app.put("/admin/queue/strategy")
async def switch_strategy(body: QueueStrategyRequest, _: str = Depends(verify_admin_token)):
    processor = get_task_processor()
    previous_strategy = processor._dispatch_strategy.strategy_name
    new_strategy = TaskDispatchStrategyFactory.create(body.strategy, **body.params)
    processor.set_dispatch_strategy(new_strategy)  # 直接替换
    return JSONResponse(content={...})
```

**问题：**
- 直接替换策略实例，旧队列中任务可能丢失
- 未实现排空逻辑，未拒绝新任务
- 未记录切换过程中的任务状态

---

### 2.3 环境变量配置审查

**设计文档要求的环境变量：**
```bash
MARKITDOWN_DISPATCH_STRATEGY=fifo  # 或 ratio
MARKITDOWN_MAX_QUEUE_SIZE=100
MARKITDOWN_QUEUE_TIMEOUT=5.0
MARKITDOWN_SMALL_RATIO=0.4
MARKITDOWN_LARGE_RATIO=0.6
MARKITDOWN_FILE_THRESHOLD_MB=5
MARKITDOWN_ADMIN_TOKEN=your-admin-token-here
```

**实际实现：**

| 变量 | 设计要求 | 实现状态 | 说明 |
|------|----------|----------|------|
| `MARKITDOWN_DISPATCH_STRATEGY` | ✅ | ❌ **未实现** | 策略选择未通过环境变量配置 |
| `MARKITDOWN_MAX_QUEUE_SIZE` | ✅ | ✅ | 工厂类参数支持 |
| `MARKITDOWN_QUEUE_TIMEOUT` | ✅ | ✅ | `queue_timeout` 参数支持 |
| `MARKITDOWN_SMALL_RATIO` | ✅ | ✅ | RatioStrategy 参数 |
| `MARKITDOWN_LARGE_RATIO` | ✅ | ✅ | RatioStrategy 参数 |
| `MARKITDOWN_FILE_THRESHOLD_MB` | ✅ | ✅ | `file_threshold_bytes` 参数 |
| `MARKITDOWN_ADMIN_TOKEN` | ✅ | ✅ | `api.py:96` 读取 |

**缺失详情：**
```python
# task_processor.py:433-453 (全局实例创建)
def get_task_processor() -> TaskProcessor:
    global _task_processor
    if _task_processor is None:
        _task_processor = TaskProcessor(
            task_store=task_store,
            enable_ocr=os.getenv("MARKITDOWN_OCR_ENABLED", "false").lower() == "true",
            progress_callback=progress_callback,
            # ❌ 缺少 dispatch_strategy 参数！
            # ❌ 未读取 MARKITDOWN_DISPATCH_STRATEGY 环境变量
        )
    return _task_processor
```

**问题：**
- 全局 `TaskProcessor` 实例未通过环境变量配置策略
- 默认使用 `FifoStrategy()`，无法在启动时指定策略类型
- `.env.example` 文件中也未列出相关环境变量

---

## 三、安全性审查

### 3.1 管理员认证 ✅ 基本合理

**实现：**
```python
# api.py:95-113
def verify_admin_token(authorization: Optional[str] = Header(default=None), request: Request = None):
    admin_token = os.getenv("MARKITDOWN_ADMIN_TOKEN", "")
    if not admin_token:
        raise HTTPException(status_code=401, detail="Admin authentication not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = authorization[7:]
    if not secrets.compare_digest(token, admin_token):  # ✅ 安全比较
        raise HTTPException(status_code=401, detail="Invalid admin token")
```

**优点：**
- ✅ 使用 `secrets.compare_digest()` 防止时序攻击
- ✅ 环境变量配置，不记录日志
- ✅ 添加了速率限制（30 req/60s）

**风险：**
- ⚠️ `MARKITDOWN_ADMIN_TOKEN` 未配置时返回 401 而非禁用端点（可能导致误用）
- ⚠️ 无 token 强度验证（建议 ≥32 字符）

### 3.2 CORS 配置 ⚠️ 需关注

**实现：**
```python
# app.py:124-126
cors_origins = os.getenv("MARKITDOWN_CORS_ORIGINS", "*")
if cors_origins != "*":
    cors_origins = [origin.strip() for origin in cors_origins.split(",")]
```

**风险：**
- ⚠️ 默认允许所有来源 (`*`)，在生产环境可能不安全
- ⚠️ 管理员端点无额外 CORS 限制

### 3.3 DNS Rebinding 防护 ✅ 已实现

**实现：**
```python
# auth.py:32-61
class AuthMiddleware(BaseHTTPMiddleware):
    @staticmethod
    def _is_valid_origin(origin: str, host: str) -> bool:
        # 验证 origin 与 host 是否匹配
        ...
```

**优点：**
- ✅ 正确验证 Origin header 与 Host header 匹配
- ✅ 防止 DNS rebinding 攻击

---

## 四、代码质量问题

### 4.1 🔴 Critical 级别问题

#### C-001: RatioStrategy promote_task 数据丢失（⚠️ FifoStrategy 已修复）

**位置：** `task_queue.py:344`（仅 RatioStrategy）

**FifoStrategy 状态：** ✅ 已正确实现 — `task_queue.py:154-161` 在重建队列时保留了 `task_item[2], task_item[3], task_item[4]`（即 `source_path, filename, options`）。

**RatioStrategy 问题代码：**
```python
# task_queue.py:344 - RatioStrategy.promote_task
target_queue.put_nowait((new_position, task_id, None, None, None))
#                                       ^^^^  ^^^^  ^^^^
# source_path, filename, options 全部丢失！
```

**对比 FifoStrategy 的正确实现：**
```python
# task_queue.py:161 - FifoStrategy.promote_task
self._queue.put_nowait((new_position, task_id, task_item[2], task_item[3], task_item[4]))
# ✅ 保留了原始数据
```

**问题：**
- RatioStrategy 的 `promote_task` 在第 335-341 行遍历队列时，将被提升的任务从队列中取出并丢弃
- 第 344 行重建队列项时使用 `None` 替代了 `source_path, filename, options`
- 被提升的任务重新入队后数据不完整，后续执行将失败
- FifoStrategy 无此问题（第 153-154 行正确保存了 `task_item`）

---

#### C-002: 队列满未返回 HTTP 503（问题在 API 层和 TaskProcessor 层）

**位置：** `api.py:151-171`（API 路由层）+ `task_processor.py:155-166`（enqueue 层）

**API 层问题：**
```python
# api.py:170 - 提交任务后无队列状态检查
background_tasks.add_task(processor.start_processing, task_id)
return SubmitTaskResponse(...)  # 始终返回 200 OK
```

**TaskProcessor 层问题：**
```python
# task_processor.py:158-165 - enqueue 失败时标记任务 FAILED
if not result.accepted:
    self.task_store.update_task(
        task_id,
        status=TaskStatus.FAILED,
        progress=-1,
        message="Queue full",
        error="Queue is full, try again later",
    )
```

**问题：**
- 客户端提交任务后始终收到 200 OK + task_id
- 队列满时任务被静默标记为 FAILED，客户端需轮询才能发现
- 未返回 HTTP 503 + `Retry-After` 头，客户端无法感知背压
- 修复应在 API 层（enqueue 前检查队列容量）和 TaskProcessor 层（传递拒绝状态）协同完成

---

### 4.2 🟡 High 级别问题

#### H-001: 队列索引重建效率低（影响有限）

**位置：** `task_queue.py:106-107, 194-195`

```python
# dequeue 时重建索引
for i, key in enumerate(self._task_index):
    self._task_index[key] = i  # O(n) 操作

# remove_task 时重建索引
for idx, key in enumerate(self._task_index):
    self._task_index[key] = idx  # O(n) 操作
```

**问题：**
- 每次 dequeue/remove 都遍历整个 `_task_index`
- 但 `max_queue_size` 默认 100，O(100) 操作在实际运行中几乎无感知
- 仅在 promote/remove 操作时触发全量重建，频率不高

**建议：** 可改用 `collections.OrderedDict` 或增量索引更新，但优先级可降低。

---

#### H-002: 缺少任务入队超时后的清理

**位置：** `task_queue.py:91-96`

```python
except asyncio.TimeoutError:
    self._positions.pop(task_id, None)
    return QueueResult(accepted=False, ...)
    # ❌ 未清理 _task_index
```

**问题：**
- 队列满超时后只清理 `_positions`，未清理 `_task_index`
- 可能导致索引与队列不一致

---

#### H-003: `_get_active_tasks_info` 查询开销（已有 TTL 缓存缓解）

**位置：** `task_processor.py:399-417`

```python
def _get_active_tasks_info(self) -> list[dict]:
    import time as _time
    now = _time.time()
    if self._processing_tasks and (now - self._active_tasks_cache_time > self._active_tasks_cache_ttl):
        # 仅在缓存过期（TTL=2s）时才查询
        for task_id, task in self._processing_tasks.items():
            task_data = self.task_store.get_task(task_id)
```

**实际评估：**
- ✅ 已实现 TTL=2.0 秒的缓存（`_active_tasks_cache_ttl`），高频调用不会每次查 DB
- ⚠️ 缓存过期后的首次调用仍会遍历所有活跃任务查询 task_store
- ⚠️ `task_store.get_task()` 在内存存储场景下开销极小，但如后续切换为 DB 存储，此问题会放大
- 严重性已从 High 降为 Medium

---

### 4.3 🟢 Medium 级别问题

#### M-001: 未使用的 import

**位置：** `task_queue.py:6`

```python
from .models import TaskStatus  # ❌ 未使用
```

---

#### M-002: 测试未覆盖策略切换

**位置：** `tests/test_task_queue.py`

**问题：**
- 无策略切换 API 的测试
- 无 `set_dispatch_strategy()` 的测试
- 无管理员端点集成测试

---

#### M-003: 响应格式与设计文档不一致

**设计文档（第 186-198 行）：**
```json
{
  "strategy": "ratio",
  "queues": {
    "fifo": {...},
    "ratio": null
  },
  "active_tasks": [...]
}
```

**实际实现：**
```json
{
  "strategy": "fifo",
  "fifo_queue": {...},    // 字段名变了
  "small_queue": {...},
  "large_queue": {...},
  "ratio_config": {...}   // 字段名变了
}
```

---

### 4.4 🔴 审计遗漏补充（二次核查发现）

> 以下问题在初次审计中未被发现，经代码逐行复核后补充。

#### N-001: `RatioStrategy.enqueue` 中 `os` 未导入导致潜在 NameError 🔴 Critical

**位置：** `task_queue.py:263`

```python
async def enqueue(self, task_id: str, task_content: bytes, filename: str, options: dict) -> QueueResult:
    source_path = None
    if isinstance(task_content, str):
        source_path = task_content
        task_content = None
    
    queue, positions, counter_name = self._get_queue_for_task(task_content, source_path)
    
    # ... put 成功后:
    file_size = len(task_content) if task_content else (os.path.getsize(source_path) if source_path else 0)
    #                                                                      ^^
    #                                            os 仅在 _get_queue_for_task 内部 import！
```

**触发条件：**
- `task_content` 为 None（即传入的是 `source_path` 字符串）
- `source_path` 不为 None
- 第 263 行尝试调用 `os.path.getsize()`，但 `os` 未在模块顶层导入，仅在第 238 行 `_get_queue_for_task` 方法内部 `import os`

**影响：** 生产环境必定触发 `NameError: name 'os' is not defined`，导致任务入队后返回 500 错误。

**建议修复：** 在 `task_queue.py` 顶部添加 `import os`，或将第 263 行的文件大小计算逻辑移入 `_get_queue_for_task`。

---

#### N-002: `_process_task` 忽略队列中的数据，依赖 task_store 重新获取 🟡 High

**位置：** `task_processor.py:194-201`

```python
async def _process_task(self, task_id: str):
    task = self.task_store.get_task(task_id)  # 从 task_store 重新获取
    if task is None:
        logger.error(f"Task {task_id} not found")
        return
    content = task.content
    filename = task.filename
    options = task.options or {}
```

**问题：**
- `_scheduler_loop` 调用 `dequeue()` 仅取回 `task_id`，丢弃了队列中存储的 `(source_path, filename, options)` 元组
- `_process_task` 必须从 `task_store` 重新获取所有任务数据
- 如果 `task_store` 使用外部存储（如 Redis/SQLite）且在服务重启后丢失，队列中积压的任务将全部因 "not found" 而失败
- 队列中存储完整数据的设计初衷（应对 task_store 不可用）被完全架空

**建议：** 修改 `dequeue()` 返回完整元组，或让 `_scheduler_loop` 将队列数据传递给 `_process_task`。

---

#### N-003: `start_processing` 参数类型语义不清 🟡 High

**位置：** `task_processor.py:155-156`

```python
result = await self._dispatch_strategy.enqueue(
    task_id, task.source_path, task.filename, task.options or {}
)
```

**`enqueue` 方法签名：**
```python
async def enqueue(self, task_id: str, task_content: bytes, filename: str, options: dict) -> QueueResult:
```

**问题：**
- 第二个参数名为 `task_content: bytes`，但实际传入 `task.source_path`（str 类型）
- `enqueue` 内部通过 `isinstance(task_content, str)` 检查来区分路径和内容（`task_queue.py:74-76, 247-249`），但这种隐式类型重载极易引发误解
- 类型注解 `bytes` 与实际传入 `str` 不匹配，静态类型检查工具（mypy/pyright）会报错

**建议：** 将 `enqueue` 签名改为 `task_content: Union[bytes, str]` 或拆分为两个参数 `content: Optional[bytes]` + `source_path: Optional[str]`。

---

#### N-004: `dequeue` 返回后队列数据被丢弃 🟡 High

**位置：** `task_queue.py:99-110` (FifoStrategy), `task_queue.py:279-296` (RatioStrategy)

```python
async def dequeue(self) -> Optional[str]:
    position, task_id, source_path, filename, options = await asyncio.wait_for(
        self._queue.get(), timeout=0.1
    )
    self._positions.pop(task_id, None)
    return task_id  # source_path, filename, options 全部丢弃！
```

**问题：**
- `dequeue` 从队列取出完整元组 `(position, task_id, source_path, filename, options)`
- 但只返回 `task_id`，`source_path`, `filename`, `options` 被丢弃
- 配合 N-002，这导致队列数据完全无法被下游使用
- 如果 task_store 中的任务在 dequeue 之后、_process_task 之前被清理，任务数据将永久丢失

**建议：** 修改 `dequeue` 返回类型为 `Optional[tuple]` 或 `Optional[QueueItem]`，携带完整数据。

---

#### N-005: `_task_index` 索引值偏移 🟢 Medium

**位置：** `task_queue.py:78`

```python
self._task_index[task_id] = self._queue.qsize()
# qsize() 在 put 之前获取，索引值比实际位置大 1
```

**问题：**
- `_task_index[task_id]` 记录的是 put 前的 `qsize()`，而非 put 后的实际位置
- 这导致 `get_task()` 方法（第 125 行 `items[target_idx]`）可能取到错误的队列项
- 当前 `_task_index` 主要用于 `promote_task` 和 `remove_task` 判断存在性，索引值的准确性未直接影响功能

**建议：** 改为 `self._task_index[task_id] = self._queue.qsize() - 1` 或在 put 之后赋值。

---

#### N-006: `.env.example` 缺少 `MARKITDOWN_ADMIN_TOKEN` 配置 🟢 Medium

**位置：** `.env.example`

**问题：**
- `.env.example` 中未列出 `MARKITDOWN_ADMIN_TOKEN` 环境变量
- 生产部署时容易遗漏配置，导致管理员 API 返回 401
- 应添加示例配置项并注明最低强度要求

---

## 五、测试覆盖评估

### 5.1 测试文件分析

**文件：** `tests/test_task_queue.py` (283 行)

| 测试类型 | 数量 | 覆盖范围 |
|----------|------|----------|
| FifoStrategy enqueue/dequeue | 3 | ✅ |
| FifoStrategy queue full | 1 | ✅ |
| FifoStrategy promote | 2 | ✅ |
| FifoStrategy remove | 2 | ✅ |
| FifoStrategy stats | 1 | ✅ |
| RatioStrategy enqueue | 2 | ✅ |
| RatioStrategy dequeue priority | 1 | ✅ |
| RatioStrategy set_ratios | 3 | ✅ |
| RatioStrategy stats | 1 | ✅ |
| RatioStrategy promote/remove | 2 | ✅ |
| Factory tests | 3 | ✅ |
| **API 端点测试** | 0 | ❌ **缺失** |
| **策略切换测试** | 0 | ❌ **缺失** |
| **并发场景测试** | 0 | ❌ **缺失** |

### 5.2 缺失的测试场景

- ❌ 管理员 API 认证测试
- ❌ 速率限制测试
- ❌ 策略切换过程中的任务处理测试
- ❌ 队列满时的 503 返回测试
- ❌ 并发 enqueue/dequeue 竞态测试
- ❌ `get_task_processor()` 全局实例测试
- ❌ **RatioStrategy.promote_task 数据完整性测试**（N-001 相关）
- ❌ **enqueue 传入 source_path(str) 时的 NameError 测试**（N-001 相关）
- ❌ **dequeue 后数据完整性测试**（N-004 相关）

---

## 六、与设计文档偏离汇总

| 设计要求 | 实现状态 | 偏离程度 |
|----------|----------|----------|
| 独立 Scheduler 组件 | 合并到 TaskProcessor | ⚠️ 中度偏离 |
| 队列满返回 503 | 标记任务失败 | 🔴 **重度偏离** |
| 配额弹性借用 | 未实现 | 🔴 **重度偏离** |
| 策略切换排空逻辑 | 未实现 | 🔴 **重度偏离** |
| Prometheus Metrics | 未实现 | 🟡 中度偏离 |
| 环境变量策略选择 | 未实现 | 🟡 中度偏离 |
| 操作审计日志 | 有基础日志 | 🟡 中度偏离 |

---

## 七、修复建议与优先级

### 🔴 Critical (必须修复)

| 编号 | 问题 | 建议修复 | 预估工时 |
|------|------|----------|----------|
| C-001 | RatioStrategy promote_task 数据丢失 | 仿照 FifoStrategy 保留原队列项数据 | 30min |
| C-002 | 队列满未返回 503 | API 层检查队列容量 + 返回 HTTP 503 | 1h |
| C-003 | 策略切换任务丢失 | 实现排空逻辑 + 新任务拒绝 | 3h |
| N-001 | RatioStrategy.enqueue 中 `os` 未导入 | 在模块顶部 `import os` | 5min |

### 🟡 High (建议修复)

| 编号 | 问题 | 建议修复 | 预估工时 |
|------|------|----------|----------|
| H-001 | 队列索引重建效率（影响有限） | 使用增量更新而非全量重建 | 1h |
| H-002 | Ratio dequeue 配额借用 | 实现设计文档的弹性借用逻辑 | 2h |
| H-003 | 环境变量策略选择 | 在 `get_task_processor()` 中读取配置 | 30min |
| H-004 | `_scheduler_loop` 变量覆盖 | 使用不同变量名避免覆盖 | 15min |
| N-002 | _process_task 忽略队列数据 | dequeue 返回完整元组 | 1h |
| N-003 | enqueue 参数类型语义不清 | 修改签名为 `Union[bytes, str]` | 30min |
| N-004 | dequeue 返回后数据丢弃 | 返回完整数据而非仅 task_id | 1h |

### 🟢 Medium (可选优化)

| 编号 | 问题 | 建议修复 | 预估工时 |
|------|------|----------|----------|
| M-001 | 未使用 import | 清理 `TaskStatus` import | 5min |
| M-002 | 测试覆盖缺失 | 添加 API 端点和并发测试 | 2h |
| M-003 | 响应格式不一致 | 调整字段名匹配设计文档 | 30min |
| M-004 | `_get_active_tasks_info` 查 DB（已有 TTL 缓存） | 延长 TTL 或事件驱动更新 | 30min |
| N-005 | `_task_index` 索引值偏移 | 修正赋值时机 | 10min |
| N-006 | `.env.example` 缺少 ADMIN_TOKEN | 添加配置项 | 5min |

---

## 八、总体评估结论

### 8.1 实现完整度评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 架构设计 | 80/100 | 基本符合策略模式，但简化了部分组件 |
| 功能完整性 | 60/100 | 核心功能已实现，关键特性缺失（503、弹性借用、排空切换）+ N-001 运行时错误 |
| 安全性 | 85/100 | 认证、速率限制合理，CORS 需关注 |
| 代码质量 | 65/100 | RatioStrategy 存在运行时 NameError + dequeue 数据流断裂 |
| 测试覆盖 | 55/100 | 单元测试覆盖核心路径，缺失 API/并发/数据完整性测试 |

**综合评分：69/100**（初次审计 72/100，二次核查下调 3 分）

### 8.2 最终结论

⚠️ **实现基本符合设计文档，但存在以下关键缺陷：**

1. **N-001: RatioStrategy.enqueue 运行时 NameError** — `os` 模块未在顶层导入，source_path 模式下必定崩溃
2. **C-001: RatioStrategy promote_task 数据丢失** — FifoStrategy 已修复，但 RatioStrategy 仍未保留数据
3. **C-002: 队列满未返回 HTTP 503** — 违背设计核心目标，客户端无法感知背压
4. **C-003: 策略切换可能导致任务丢失** — 未实现排空逻辑
5. **N-002/N-004: dequeue 数据流断裂** — 队列存储了完整数据但 dequeue 后丢弃，完全依赖 task_store
6. **Ratio 策略无配额弹性借用** — 可能导致队列饿死
7. **环境变量配置缺失** — 无法在启动时选择策略

### 8.3 建议行动

1. **立即修复 N-001**（`os` 未导入 — 5 分钟即可修复，影响生产环境）
2. **立即修复 C-001**（RatioStrategy `promote_task` 数据丢失）
3. **优先修复 C-002、C-003** (503 返回、策略切换)
4. **修复 N-002/N-003/N-004**（dequeue 数据流断裂，涉及接口重构）
5. **补充环境变量配置** (H-003)
6. **完善测试覆盖** (管理员 API + 并发 + 数据完整性场景)
7. **更新 `.env.example`** 添加队列相关配置项（N-006）

---

## 附录 A: 问题定位索引

| 问题编号 | 文件 | 行号 | 问题描述 |
|----------|------|------|----------|
| C-001 | task_queue.py | 344 | RatioStrategy promote_task 数据丢失（FifoStrategy 已修复） |
| C-002 | api.py + task_processor.py | 170, 158-165 | 队列满未返回 503 |
| C-003 | api.py | 320-339 | 策略切换未排空 |
| N-001 | task_queue.py | 263 | RatioStrategy.enqueue 中 `os` 未导入导致 NameError |
| H-001 | task_queue.py | 106-107, 194-195 | 索引重建效率（影响有限） |
| H-002 | task_queue.py | 279-296 | dequeue 无配额借用 |
| H-003 | task_processor.py | 449-453 | 环境变量未读取 |
| H-004 | task_processor.py | 345-350 | 变量覆盖 bug |
| N-002 | task_processor.py | 194-201 | _process_task 忽略队列数据 |
| N-003 | task_processor.py | 155-156 | enqueue 参数类型语义不清 |
| N-004 | task_queue.py | 99-110, 279-296 | dequeue 返回后数据丢弃 |
| M-001 | task_queue.py | 6 | 未使用 import |
| M-002 | tests/test_task_queue.py | - | 测试缺失 |
| M-003 | task_processor.py | 381-388 | 响应格式不一致 |
| M-004 | task_processor.py | 399-417 | stats 查 DB（已有 TTL 缓存） |
| N-005 | task_queue.py | 78 | _task_index 索引值偏移 |
| N-006 | .env.example | - | 缺少 ADMIN_TOKEN 配置 |

---

## 附录 B: 环境变量配置建议

建议在 `.env.example` 中添加：

```bash
# Task Queue Strategy
MARKITDOWN_DISPATCH_STRATEGY=fifo    # fifo | ratio
MARKITDOWN_MAX_QUEUE_SIZE=100
MARKITDOWN_QUEUE_TIMEOUT=5.0

# Ratio Strategy (only when strategy=ratio)
MARKITDOWN_SMALL_RATIO=0.4
MARKITDOWN_LARGE_RATIO=0.6
MARKITDOWN_FILE_THRESHOLD_MB=5

# Admin API
MARKITDOWN_ADMIN_TOKEN=your-strong-admin-token-here-min-32-characters
```

---

*初次审计时间: 2026-05-03*
*二次核查时间: 2026-05-03*
*审计人员: Maria (AI Assistant)*
*文档状态: 待评审修复*
*修订说明: v2 — 修正 C-001 仅影响 RatioStrategy、补充 N-001~N-006 遗漏问题、调整 H-003/M-004 严重性*