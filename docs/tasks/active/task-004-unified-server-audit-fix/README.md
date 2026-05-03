# Task-004: Unified Server Audit & Simplification

## 目标

对 API+MCP 统一服务架构进行审计、修复问题，并简化为纯 Unified 模式。

## 阶段一：审计修复

| # | 问题 | 修复方案 | 文件 |
|---|------|----------|------|
| 1 | `api.py` 重复 CORS 中间件 | 添加 `enable_cors` 参数 | `api.py`, `app.py` |
| 2 | 双重认证逻辑冲突 | 新增 `verify_token_or_passthrough` | `auth.py`, `api.py` |
| 3 | `LargeBodyMiddleware` 重复定义 | 提取到 `core/middleware.py` | 新增 |
| 4 | `options: dict = {}` 可变默认参数 | 改为 `Optional[dict] = None` | `mcp.py` |
| 5 | MCP SSE 路径不一致 | 统一使用变量 | `app.py`, `mcp.py` |

## 阶段三：任务队列策略

实现任务队列机制，支持 FIFO 和按比例分配两种策略，以及管理员干预 API。

### 变更

| 文件 | 变更内容 |
|------|---------|
| `core/task_queue.py` | **新增** - 队列策略抽象基类、FifoStrategy、RatioStrategy、工厂类 |
| `core/models.py` | 新增 QueueStatsResponse、QueuePriorityResponse、QueueStrategyResponse、QueueRatiosResponse、QueueTaskResponse |
| `core/task_processor.py` | 注入队列策略、实现调度器循环、添加队列统计 API |
| `api.py` | 新增 `/admin/queue/*` 路由（stats、priority、strategy、ratios、task） |

### 架构设计

```
客户端提交任务 → TaskProcessor.start_processing()
    │
    ├── 提交到队列 (FifoStrategy / RatioStrategy)
    ├── 队列满时返回 503
    │
    ▼
Scheduler Loop (后台循环)
    │
    ├── 从队列取任务 → 提交到 ThreadPoolExecutor
    ├── 监控空闲槽位
    └── 支持 promote/remove 操作
```

### 策略特性

**FIFO 策略：**
- 单一队列，按提交顺序处理
- 支持队列满拒绝（503）
- 支持 promote（提升优先级）
- 支持 remove（移除任务）

**Ratio 策略：**
- 双队列（small < 5MB, large >= 5MB）
- 按比例分配槽位（默认 small 40%, large 60%）
- 支持动态调整比例
- 小队列优先调度

### 管理员 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/admin/queue/stats` | GET | 获取队列状态统计 |
| `/admin/queue/priority` | POST | 提升任务到队列头部 |
| `/admin/queue/strategy` | PUT | 切换队列策略 |
| `/admin/queue/ratios` | PUT | 调整通道比例 |
| `/admin/queue/task` | DELETE | 从队列移除任务 |

### 测试结果

```
39 passed, 2 warnings
```

| 测试类别 | 状态 |
|----------|------|
| test_import (7 tests) | ✅ |
| test_task_queue (24 tests) | ✅ |
| test_unified (8 tests) | ✅ |

## 阶段二：纯 Unified 模式简化

用户需求：只保留 unified 模式，通过 `--no-api` / `--no-mcp` 控制开关。

### 变更

| 变更 | 文件 |
|------|------|
| 移除 mode 选择（unified/api/mcp） | `__main__.py` |
| 移除 `run_api_server()` | `api.py` |
| 移除 `run_mcp_server()` + `create_starlette_app()` | `mcp.py` |
| 添加 `enable_api`/`enable_mcp` 参数 | `app.py` |
| 添加 `--no-api`/`--no-mcp` CLI 参数 | `__main__.py` |
| 更新 Docker 示例 | `README.md`, `Dockerfile` |

### 测试结果

```
15 passed, 2 warnings
```

| 测试 | 状态 |
|------|------|
| test_import | ✅ |
| test_import_core | ✅ |
| test_import_api | ✅ |
| test_import_mcp | ✅ |
| test_unified_full | ✅ |
| test_unified_api_only | ✅ |
| test_unified_mcp_only | ✅ |
| test_health_unified_root | ✅ |
| test_health_api_sub | ✅ |
| test_api_formats | ✅ |
| test_api_submit_base64 | ✅ |
| test_api_list_tasks | ✅ |
| test_api_convert_direct | ✅ |
| test_mcp_tools_exist | ✅ |
| test_unified_routes | ✅ |
