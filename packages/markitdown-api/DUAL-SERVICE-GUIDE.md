# MarkItDown API + MCP 双服务部署指南

同时启用 RESTful API 和 MCP HTTP 服务，提供统一入口。

## 架构概览

```
┌─────────────────┐     ┌──────────────────┐
│   API Client    │────▶│  markitdown-api  │
│  (HTTP/REST)    │     │   :8000          │
└─────────────────┘     └──────────────────┘

┌─────────────────┐     ┌──────────────────┐
│   LLM Client    │────▶│  markitdown-mcp  │
│ (Claude/ChatGPT)│     │   :3001 (HTTP)   │
└─────────────────┘     └──────────────────┘
```

## 快速启动

### 1. 配置环境变量

```bash
cd packages/markitdown-api
cp dual-service.env.example .env

# 编辑 .env 文件，填写实际的 API Key
vim .env
```

### 2. 启动双服务

```bash
# 使用 docker-compose
docker-compose -f docker-compose.dual.yml up -d

# 查看日志
docker-compose -f docker-compose.dual.yml logs -f

# 停止服务
docker-compose -f docker-compose.dual.yml down
```

### 3. 验证服务

```bash
# 检查 API 健康状态
curl http://localhost:8000/health

# 检查 MCP 健康状态
curl http://localhost:3001/health

# 带认证访问 API
curl -H "Authorization: Bearer your-secret-token" \
  http://localhost:8000/formats

# 带认证访问 MCP
curl -H "Authorization: Bearer your-secret-token" \
  http://localhost:3001/tasks/events
```

## 服务端点

| 服务 | 地址 | 用途 |
|------|------|------|
| RESTful API | `http://localhost:8000` | HTTP API 客户端 |
| MCP HTTP | `http://localhost:3001/mcp` | LLM 客户端 (MCP) |
| MCP SSE | `http://localhost:3001/tasks/events` | 任务进度通知 |
| API Docs | `http://localhost:8000/docs` | Swagger UI |

## 认证方式

两个服务共享同一个 `MARKITDOWN_API_KEY`：

```bash
# 环境变量配置
export MARKITDOWN_API_KEY="your-secret-token-32-chars-min"

# HTTP 请求头
Authorization: Bearer your-secret-token-32-chars-min
```

### Claude Desktop 配置示例

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
        "-p", "3001:3001",
        "markitdown-ocr-mcp:latest",
        "--http", "--host", "0.0.0.0", "--port", "3001"
      ]
    }
  }
}
```

## API vs MCP 对比

| 功能 | API (:8000) | MCP (:3001) |
|------|-------------|-------------|
| 传输方式 | HTTP REST | MCP Protocol |
| 文件上传 | Form Data / Base64 | Base64 |
| 任务管理 | ✅ | ✅ |
| SSE 通知 | ✅ | ✅ |
| 同步转换 | ✅ | ❌ |
| OCR 支持 | ✅ | ✅ |
| 最佳场景 | 普通 HTTP 客户端 | LLM 客户端 |

## 生产部署建议

### 1. 使用 Nginx 反向代理（可选）

```bash
# 启动带 Nginx 的版本
docker-compose -f docker-compose.dual.yml --profile with-nginx up -d
```

统一入口：`http://localhost/api/` 和 `http://localhost/mcp/`

### 2. HTTPS 配置

建议使用 Nginx 或 CloudFlare 处理 HTTPS 终端。

### 3. 独立认证（可选）

如果希望 API 和 MCP 使用不同 Token，修改 `docker-compose.dual.yml`：

```yaml
# API 服务
environment:
  - MARKITDOWN_API_KEY=${MARKITDOWN_API_TOKEN}

# MCP 服务  
environment:
  - MARKITDOWN_API_KEY=${MARKITDOWN_MCP_TOKEN}
```

## 故障排查

| 问题 | 排查方法 |
|------|----------|
| 服务无法启动 | 检查 `.env` 文件是否存在且 Token 长度 >= 32 |
| 401 认证失败 | 确认请求头 `Authorization: Bearer <token>` 格式正确 |
| OCR 失败 | 检查 `MARKITDOWN_OCR_API_KEY` 是否有效 |
| 存储问题 | 确认 Docker volumes 已正确挂载 |

## 查看日志

```bash
# 所有服务日志
docker-compose -f docker-compose.dual.yml logs

# 仅 API 日志
docker-compose -f docker-compose.dual.yml logs markitdown-api

# 仅 MCP 日志
docker-compose -f docker-compose.dual.yml logs markitdown-mcp
```

## 开发模式

本地源码运行（不通过 Docker）：

**Terminal 1 - API:**
```bash
cd packages/markitdown-api
export MARKITDOWN_API_KEY="your-secret-token"
markitdown-api --host 127.0.0.1 --port 8000
```

**Terminal 2 - MCP:**
```bash
cd packages/markitdown-ocr-mcp
export MARKITDOWN_API_KEY="your-secret-token"
export MARKITDOWN_OCR_API_KEY="sk-xxx"
markitdown-ocr-mcp --http --host 127.0.0.1 --port 3001
```

✌Bazinga！
