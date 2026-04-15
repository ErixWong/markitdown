# MarkItDown 双服务部署配置

同时启用 **RESTful API** 和 **MCP HTTP** 服务的完整配置方案。

## 架构说明

```
                    ┌─────────────────┐
   HTTP Clients ───▶│  markitdown-api │──┐
   (curl, apps)     │    Port: 8000   │  │
                    └─────────────────┘  │  ┌──────────────┐
                                         ├──▶│  LLM OCR     │
                    ┌─────────────────┐  │  │  Service     │
   LLM Clients ─────▶│ markitdown-mcp │──┘  └──────────────┘
   (Claude, etc.)   │   Port: 3001    │
                    └─────────────────┘
```

## 默认端口配置

| 服务 | 内部端口 | 外部映射 | 用途 |
|------|---------|---------|------|
| API | 8000 | 8000 | RESTful HTTP API |
| MCP | 3001 | 3001 | MCP HTTP/SSE |

## 快速启动

### 1. 环境准备

```bash
# 创建工作目录
mkdir -p ~/markitdown-deployment
cd ~/markitdown-deployment

# 下载配置
curl -O https://raw.githubusercontent.com/ErixWong/markitdown/main/packages/markitdown-api/docker-compose.dual.yml
curl -O https://raw.githubusercontent.com/ErixWong/markitdown/main/packages/markitdown-api/dual-service.env.example

# 重命名环境文件
mv dual-service.env.example .env
```

### 2. 配置环境变量

编辑 `.env` 文件：

```bash
# 认证配置（两个服务共享）
MARKITDOWN_API_KEY=your-secret-token-32-chars-min-with-mixed-123

# OCR 配置（仅 MCP 需要）
MARKITDOWN_OCR_API_KEY=sk-your-openai-api-key
MARKITDOWN_OCR_MODEL=gpt-4o
```

### 3. 启动服务

```bash
# 一键启动双服务
docker-compose -f docker-compose.dual.yml up -d

# 查看状态
docker-compose -f docker-compose.dual.yml ps

# 查看日志
docker-compose -f docker-compose.dual.yml logs -f
```

### 4. 验证服务

```bash
# API 健康检查
curl http://localhost:8000/health

# MCP 健康检查
curl http://localhost:3001/health

# 带认证访问 API
curl -H "Authorization: Bearer your-secret-token-32-chars-min" \
  http://localhost:8000/formats

# 带认证访问 MCP SSE
curl -H "Authorization: Bearer your-secret-token-32-chars-min" \
  http://localhost:3001/tasks/events
```

## 端口自定义

如果默认端口被占用，修改 `docker-compose.dual.yml`：

```yaml
services:
  markitdown-api:
    ports:
      - "8080:8000"    # 外部8080 → 内部8000
    
  markitdown-mcp:
    ports:
      - "3002:3001"    # 外部3002 → 内部3001
```

或创建 `.env` 覆盖：

```bash
API_EXTERNAL_PORT=8080
MCP_EXTERNAL_PORT=3002
```

然后修改 docker-compose 使用变量：

```yaml
ports:
  - "${API_EXTERNAL_PORT:-8000}:8000"
  - "${MCP_EXTERNAL_PORT:-3001}:3001"
```

## 服务对比

| 特性 | API (8000) | MCP (3001) |
|------|-----------|-----------|
| 协议 | RESTful HTTP | MCP Protocol |
| 文件传输 | Form Data / Base64 | Base64 |
| 同步转换 | ✅ 支持 | ❌ 不支持 |
| 异步任务 | ✅ 支持 | ✅ 支持 |
| SSE 通知 | ✅ 支持 | ✅ 支持 |
| OCR 支持 | ✅ 支持 | ✅ 支持 |
| 逐页处理 | ✅ 支持 | ✅ 支持 |
| 最佳场景 | HTTP 客户端 | LLM 客户端 |

## 认证配置

两个服务**共享相同的 Bearer Token**，通过 `MARKITDOWN_API_KEY` 设置。

### Token 要求

- 最少 32 个字符
- 必须包含字母和数字
- 弱 Token 会被拒绝

### 请求示例

```bash
# API 请求
curl -X POST http://localhost:8000/tasks \
  -H "Authorization: Bearer your-token-32-chars-min" \
  -F "file=@document.pdf"

# MCP SSE 连接
curl -N http://localhost:3001/tasks/events \
  -H "Authorization: Bearer your-token-32-chars-min"
```

## Claude Desktop 配置

当 MCP 启用认证时，配置方式：

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

## 独立认证（高级）

如果需要 API 和 MCP 使用不同 Token：

1. 修改 `docker-compose.dual.yml`：

```yaml
services:
  markitdown-api:
    environment:
      - MARKITDOWN_API_KEY=${API_TOKEN}
    
  markitdown-mcp:
    environment:
      - MARKITDOWN_API_KEY=${MCP_TOKEN}
```

2. 更新 `.env`：

```bash
API_TOKEN=api-secret-token-32-chars-here
MCP_TOKEN=mcp-secret-token-32-chars-here
```

## 常见问题

### 端口冲突

```bash
# 检查端口占用
lsof -i :8000
lsof -i :3001

# 或修改 docker-compose 使用其他端口
```

### 认证失败

```bash
# 确认 Token 长度 >= 32
echo -n "your-token" | wc -c

# 检查请求头格式
curl -v -H "Authorization: Bearer your-token" http://localhost:8000/health
```

### 存储权限

```bash
# 确保 Docker 可以写入存储目录
mkdir -p storage-api storage-mcp
chmod 755 storage-*
```

## 生产部署建议

### 1. 使用反向代理

```yaml
# 添加 nginx 服务
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
```

### 2. HTTPS 配置

建议使用 Let's Encrypt + Nginx 或 CloudFlare 处理 HTTPS。

### 3. 监控

```yaml
# 健康检查
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
  interval: 30s
  timeout: 10s
  retries: 3
```

## 本地开发模式

不使用 Docker，直接运行源码：

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

## 参考文档

- [MarkItDown API README](../../packages/markitdown-api/README.md)
- [MarkItDown MCP README](../../packages/markitdown-ocr-mcp/README.md)
- [MCP Protocol Specification](https://spec.modelcontextprotocol.io/)

---

**维护信息**
- 创建时间: 2026-04-15
- 适用版本: markitdown-api >= 0.1.0, markitdown-ocr-mcp >= 0.1.0
- 最后更新: 2026-04-15
