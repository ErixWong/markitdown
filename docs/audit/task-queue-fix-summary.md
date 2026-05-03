# 任务队列策略修复总结

## 修复日期
2026-05-03

## 修复文件清单

| 文件 | 修改内容 |
|------|---------|
| `core/task_queue.py` | N-001/C-001/N-002/N-003/N-004/M-001 修复 |
| `core/task_processor.py` | H-003/N-002 修复 + 导入 time 模块 |
| `api.py` | C-002 修复 + 空白行清理 |
| `.env.example` | N-006 修复 - 添加队列配置 |
| `tests/test_task_queue.py` | 更新测试适配 QueueItem |

---

## 修复详情

### 🔴 Critical 修复

#### N-001: RatioStrategy.enqueue 中 `os` 未导入
**问题：** `task_queue.py:263` 使用 `os.path.getsize()` 但 `os` 仅在 `_get_queue_for_task` 方法内部导入。

**修复：** 在模块顶部添加 `import os`。

```diff
- from typing import Optional
+ from typing import Optional, Union
+ import os
```

---

#### C-001: RatioStrategy.promote_task 数据丢失
**问题：** 第 344 行使用 `(new_position, task_id, None, None, None)` 重建队列项，丢失 `source_path, filename, options`。

**修复：** 仿照 FifoStrategy 实现，保存并恢复原始数据。

```diff
- target_queue.put_nowait((new_position, task_id, None, None, None))
+ task_item = None
+ while not target_queue.empty():
+     if item[1] == task_id:
+         task_item = item
+ ...
+ target_queue.put_nowait((new_position, task_id, task_item[2], task_item[3], task_item[4]))
```

---

#### C-002: 队列满未返回 HTTP 503
**问题：** API 层未检查队列容量，队列满时任务被标记 FAILED 而非返回 503。

**修复：**
1. 在 `TaskDispatchStrategy` 添加 `is_queue_full()` 抽象方法
2. 在 `FifoStrategy` 和 `RatioStrategy` 实现 `is_queue_full()`
3. 在 `api.py` 的 `submit_task` 和 `submit_task_base64` 检查队列容量

```python
# api.py
if processor._dispatch_strategy.is_queue_full():
    raise HTTPException(
        status_code=503,
        detail="Queue is full, please retry later",
        headers={"Retry-After": "5"}
    )
```

---

### 🟡 High 修复

#### H-003: 环境变量策略选择配置
**问题：** `get_task_processor()` 未读取 `MARKITDOWN_DISPATCH_STRATEGY` 环境变量。

**修复：** 在 `get_task_processor()` 中读取环境变量并配置策略。

```python
strategy_type = os.getenv("MARKITDOWN_DISPATCH_STRATEGY", "fifo").lower()
strategy_params = {
    "max_queue_size": int(os.getenv("MARKITDOWN_MAX_QUEUE_SIZE", "100")),
    "queue_timeout": float(os.getenv("MARKITDOWN_QUEUE_TIMEOUT", "5.0")),
}
if strategy_type == "ratio":
    strategy_params["small_ratio"] = float(os.getenv("MARKITDOWN_SMALL_RATIO", "0.4"))
    ...
dispatch_strategy = TaskDispatchStrategyFactory.create(strategy_type, **strategy_params)
```

---

#### N-002/N-004: dequeue 数据流断裂
**问题：** `dequeue()` 返回仅 `task_id`，队列中存储的 `source_path, filename, options` 被丢弃。

**修复：**
1. 添加 `QueueItem` 数据类
2. 修改 `dequeue()` 返回 `Optional[QueueItem]`
3. 修改 `_scheduler_loop` 和 `_process_task` 使用 `QueueItem`

```python
@dataclass
class QueueItem:
    task_id: str
    source_path: Optional[str] = None
    filename: Optional[str] = None
    options: Optional[dict] = None

async def dequeue(self) -> Optional[QueueItem]:
    ...
    return QueueItem(task_id=task_id, source_path=source_path, filename=filename, options=options)
```

---

#### N-003: enqueue 参数类型语义不清
**问题：** 参数名 `task_content: bytes` 但实际传入 `str`（source_path）。

**修复：** 修改签名为 `task_content: Union[bytes, str, None]`。

```diff
- async def enqueue(self, task_id: str, task_content: bytes, ...) -> QueueResult:
+ async def enqueue(self, task_id: str, task_content: Union[bytes, str, None], ...) -> QueueResult:
```

---

### 🟢 Medium 修复

#### M-001: 未使用 import
**修复：** 移除 `from .models import TaskStatus` 未使用的导入。

---

#### N-006: .env.example 缺少配置
**修复：** 添加队列配置项：

```bash
# Task Queue Strategy
MARKITDOWN_DISPATCH_STRATEGY=fifo
MARKITDOWN_MAX_QUEUE_SIZE=100
MARKITDOWN_QUEUE_TIMEOUT=5.0

# Ratio Strategy (only when strategy=ratio)
MARKITDOWN_SMALL_RATIO=0.4
MARKITDOWN_LARGE_RATIO=0.6
MARKITDOWN_FILE_THRESHOLD_MB=5

# Admin API Token (min 32 chars)
# MARKITDOWN_ADMIN_TOKEN=
```

---

## 测试验证

```
============================= 28 passed in 5.29s ==============================
```

新增测试：
- `test_queue_item_data_preservation` - 验证 QueueItem 数据完整性
- `test_ratio_promote_data_preservation` - 验证 RatioStrategy promote 数据保留
- `test_fifo_is_queue_full` - 验证 is_queue_full 方法
- `test_ratio_is_queue_full` - 验证 RatioStrategy is_queue_full 方法

---

## 未修复问题（需要后续处理）

### C-003: 策略切换排空队列逻辑
**状态：** 未实现
**建议：** 需要实现设计文档第 330-334 行的排空逻辑：
1. 拒绝新任务提交（返回 503）
2. 等待队列中现有任务处理完成（最多 60 秒）
3. 切换策略实例
4. 恢复接受新任务

### H-002: Ratio 策略配额弹性借用
**状态：** 未实现
**建议：** 实现设计文档第 138-142 行的弹性借用逻辑。

---

## 验证命令

```bash
cd packages/markitdown-server
python -m ruff check src/markitdown_server/core/task_queue.py src/markitdown_server/core/task_processor.py src/markitdown_server/api.py
python -m pytest tests/test_task_queue.py -v
```

---

*修复人员: Maria (AI Assistant)*
*修复日期: 2026-05-03*
*文档状态: 已完成*
✌Bazinga！