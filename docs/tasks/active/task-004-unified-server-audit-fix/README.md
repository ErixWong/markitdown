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
