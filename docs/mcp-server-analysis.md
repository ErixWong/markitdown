# MarkItDown MCP 服务器分析与可行性研究

## 执行摘要

本文档分析在 MarkItDown 项目中构建 MCP（模型上下文协议）服务器的可行性，研究官方 MCP 服务器实现，并提出可提供的潜在工具。

---

## 1. 项目结构概述

MarkItDown 项目采用 monorepo 结构，包含以下包：

| 包名 | 用途 | 状态 |
|------|------|------|
| [`packages/markitdown`](packages/markitdown) | 核心转换库 | 生产环境 |
| [`packages/markitdown-mcp`](packages/markitdown-mcp) | 官方 MCP 服务器 | 生产环境 |
| [`packages/markitdown-ocr`](packages/markitdown-ocr) | OCR 插件（图像文字提取） | 开发中 |
| [`packages/markitdown-sample-plugin`](packages/markitdown-sample-plugin) | 示例插件模板 | 示例代码 |

### 核心库功能

[`MarkItDown`](packages/markitdown/src/markitdown/_markitdown.py:93) 类提供以下功能：

- **文件格式支持**：PDF、DOCX、XLSX、PPTX、HTML、EPUB、IPYNB、CSV、图片、音频等
- **URI 支持**：`file://`、`http://`、`https://`、`data://` URI
- **插件系统**：基于入口点的插件发现机制（`markitdown.plugin`）
- **转换器优先级系统**：基于优先级的转换器选择机制

---

## 2. 官方 MCP 服务器分析

### 2.1 实现细节

官方 MCP 服务器位于 [`packages/markitdown-mcp`](packages/markitdown-mcp)。

**核心组件：**

```python
# 来自 __main__.py
from mcp.server.fastmcp import FastMCP
from markitdown import MarkItDown

mcp = FastMCP("markitdown")

@mcp.tool()
async def convert_to_markdown(uri: str) -> str:
    """将 http:, https:, file: 或 data: URI 描述的资源转换为 markdown"""
    return MarkItDown(enable_plugins=check_plugins_enabled()).convert_uri(uri).markdown
```

### 2.2 传输协议支持

| 传输方式 | 模式 | 默认端口 | 使用场景 |
|----------|------|----------|----------|
| STDIO | 默认 | 无 | 本地 CLI 集成 |
| Streamable HTTP | `--http` | 3001 | 远程/Web 集成 |
| SSE | `/sse` 端点 | 3001 | 传统 HTTP 客户端 |

### 2.3 依赖项

来自 [`pyproject.toml`](packages/markitdown-mcp/pyproject.toml:26-29)：

```toml
dependencies = [
  "mcp~=1.8.0",
  "markitdown[all]>=0.1.1,<0.2.0",
]
```

### 2.4 安全考虑

- **无身份认证**：服务器以用户权限运行
- **本地绑定**：HTTP/SSE 模式默认绑定 localhost
- **文件访问**：可读取用户可访问的任何文件
- **网络访问**：可获取任何网络资源

---

## 3. OCR 插件分析

### 3.1 插件架构

[`markitdown-ocr`](packages/markitdown-ocr) 插件提供基于 LLM Vision 的 OCR 功能：

**入口点注册：**
```toml
[project.entry-points."markitdown.plugin"]
ocr = "markitdown_ocr"
```

**提供的转换器：**
- [`PdfConverterWithOCR`](packages/markitdown-ocr/src/markitdown_ocr/_pdf_converter_with_ocr.py) - PDF OCR 转换器
- [`DocxConverterWithOCR`](packages/markitdown-ocr/src/markitdown_ocr/_docx_converter_with_ocr.py) - DOCX OCR 转换器
- [`PptxConverterWithOCR`](packages/markitdown-ocr/src/markitdown_ocr/_pptx_converter_with_ocr.py) - PPTX OCR 转换器
- [`XlsxConverterWithOCR`](packages/markitdown-ocr/src/markitdown_ocr/_xlsx_converter_with_ocr.py) - XLSX OCR 转换器

**优先级系统：**
```python
PRIORITY_OCR_ENHANCED = -1.0  # 在内置转换器（优先级 0.0）之前运行
```

### 3.2 OCR 服务配置

**环境变量：**
| 变量名 | 用途 |
|--------|------|
| `MARKITDOWN_OCR_API_KEY` | LLM 服务 API 密钥 |
| `MARKITDOWN_OCR_API_BASE` | API 基础 URL（可选） |
| `MARKITDOWN_OCR_MODEL` | 模型名称（如 `gpt-4o`） |

**服务类：**
```python
class LLMVisionOCRService:
    def extract_text(self, image_stream, prompt, stream_info) -> OCRResult
```

---

## 4. 可行性评估

### 4.1 构建增强版 MCP 服务器

**可行性：高** ✅

项目已有可工作的 MCP 服务器实现。构建带有 OCR 功能的增强版本非常直接：

**方案 1：扩展现有 MCP 服务器**

修改 [`packages/markitdown-mcp`](packages/markitdown-mcp) 以包含 OCR 工具：

```python
@mcp.tool()
async def convert_to_markdown_with_ocr(uri: str, ocr_enabled: bool = True) -> str:
    """转换文档并对嵌入图像进行 OCR 提取"""
    mid = MarkItDown(enable_plugins=True)  # 启用 OCR 插件
    return mid.convert_uri(uri).markdown
```

**方案 2：创建独立的 OCR MCP 包**

创建 `packages/markitdown-ocr-mcp` 作为独立包：

```
packages/markitdown-ocr-mcp/
├── pyproject.toml
├── README.md
└── src/markitdown_ocr_mcp/
    ├── __init__.py
    ├── __main__.py  # MCP 服务器实现
    └── _tools.py    # 工具定义
```

### 4.2 技术要求

| 要求 | 状态 | 备注 |
|------|------|------|
| MCP SDK | 可用 | `mcp~=1.8.0` |
| FastMCP | 可用 | 简化 MCP 服务器创建 |
| HTTP 服务器 | 可用 | Starlette + Uvicorn |
| 插件集成 | 可用 | 入口点系统 |
| OCR 依赖 | 可选 | `openai>=1.0.0` |

### 4.3 实现复杂度

| 方面 | 复杂度 | 原因 |
|------|--------|------|
| 基础 MCP 服务器 | 低 | 已有实现 |
| OCR 集成 | 中 | 需要 LLM 客户端配置 |
| 多工具支持 | 低 | FastMCP 装饰器模式 |
| 错误处理 | 中 | OCR 服务失败处理 |
| 配置管理 | 中 | 环境变量处理 |

---

## 5. 建议提供的工具

基于异步任务架构设计，工具分为三类：**任务管理工具**、**同步转换工具**、**辅助工具**。

### 5.1 任务管理工具（核心）

#### 工具 1：`submit_conversion_task`

```python
@mcp.tool()
async def submit_conversion_task(
    content: str,       # Base64 编码的文件内容
    filename: str,      # 文件名（用于推断格式）
    options: dict = {}  # 可选配置
) -> str:
    """
    提交文件转换任务，返回任务 ID。
    
    参数：
        content: Base64 编码的文件内容
        filename: 文件名（如 "document.pdf"）
        options: 可选配置，支持：
            - ocr_enabled: 是否启用 OCR（默认 false）
            - ocr_prompt: 自定义 OCR 提示词
            - ocr_model: OCR 模型名称
    
    返回：
        task_id: 任务唯一标识符
    """
```

**使用场景**：上传文件进行异步转换，适合大文件和 OCR 处理

#### 工具 2：`get_task_status`

```python
@mcp.tool()
async def get_task_status(task_id: str) -> dict:
    """
    查询任务状态和进度。
    
    参数：
        task_id: 任务 ID
    
    返回：
        {
            "task_id": "task_abc123",
            "status": "processing",  # pending/processing/completed/failed
            "progress": 45,          # 0-100
            "message": "OCR processing page 5/10",
            "created_at": "2026-04-10T09:30:00Z",
            "updated_at": "2026-04-10T09:32:15Z"
        }
    """
```

**使用场景**：轮询查询任务进度，或配合 SSE 通知使用

#### 工具 3：`get_task_result`

```python
@mcp.tool()
async def get_task_result(task_id: str) -> str:
    """
    获取转换结果（Markdown 文本）。
    
    参数：
        task_id: 任务 ID
    
    返回：
        Markdown 格式的转换结果
    
    错误：
        - 任务未完成时返回错误信息
        - 任务失败时返回错误原因
    """
```

**使用场景**：任务完成后获取转换结果

#### 工具 4：`cancel_task`

```python
@mcp.tool()
async def cancel_task(task_id: str) -> bool:
    """
    取消待处理或处理中的任务。
    
    参数：
        task_id: 任务 ID
    
    返回：
        True: 取消成功
        False: 任务已完成或不存在
    """
```

**使用场景**：取消不需要的转换任务

#### 工具 5：`list_tasks`

```python
@mcp.tool()
async def list_tasks(
    status: str = "",   # 过滤状态：pending/processing/completed/failed
    limit: int = 10     # 返回数量限制
) -> list[dict]:
    """
    列出任务列表。
    
    参数：
        status: 可选状态过滤
        limit: 返回数量限制（默认 10）
    
    返回：
        任务信息列表
    """
```

**使用场景**：查看历史任务或管理多个任务

### 5.2 同步转换工具（便捷）

#### 工具 6：`convert_to_markdown`

```python
@mcp.tool()
async def convert_to_markdown(uri: str) -> str:
    """
    将 URI 转换为 Markdown（同步，无 OCR）。
    
    参数：
        uri: 文档 URI（file:, http:, https:, data:）
    
    返回：
        Markdown 文本
    
    注意：
        - 适合小文件快速转换
        - 不支持 OCR
        - 可能因大文件超时
    """
```

**使用场景**：快速转换小文件，与官方 MCP 兼容

#### 工具 7：`convert_file_content`

```python
@mcp.tool()
async def convert_file_content(
    content: str,       # Base64 编码的文件内容
    filename: str,      # 文件名
    options: dict = {}  # 可选配置
) -> str:
    """
    直接转换文件内容（同步，适合小文件）。
    
    参数：
        content: Base64 编码的文件内容
        filename: 文件名
        options: 可选配置（支持 OCR）
    
    返回：
        Markdown 文本
    
    注意：
        - 适合小文件（<5MB）
        - 支持 OCR 但可能超时
    """
```

**使用场景**：小文件直接转换，无需任务管理

### 5.3 辅助工具

#### 工具 8：`get_supported_formats`

```python
@mcp.tool()
async def get_supported_formats() -> list[dict]:
    """
    获取支持的文件格式列表。
    
    返回：
        [
            {
                "extension": ".pdf",
                "mimetype": "application/pdf",
                "converter": "PdfConverterWithOCR",
                "ocr_support": true
            },
            ...
        ]
    """
```

**使用场景**：AI 代理发现支持的格式

#### 工具 9：`ocr_image`

```python
@mcp.tool()
async def ocr_image(
    content: str,       # Base64 编码的图像内容
    prompt: str = ""    # 可选 OCR 提示词
) -> str:
    """
    对单个图像执行 OCR。
    
    参数：
        content: Base64 编码的图像内容
        prompt: 自定义提取提示词
    
    返回：
        从图像提取的文字
    """
```

**使用场景**：直接对图像进行 OCR，不涉及文档转换

#### 工具 10：`get_document_metadata`

```python
@mcp.tool()
async def get_document_metadata(
    content: str,       # Base64 编码的文件内容
    filename: str       # 文件名
) -> dict:
    """
    提取文档元数据，无需完整转换。
    
    参数：
        content: Base64 编码的文件内容
        filename: 文件名
    
    返回：
        {
            "title": "文档标题",
            "author": "作者",
            "page_count": 10,
            "image_count": 5,
            "word_count": 5000
        }
    """
```

**使用场景**：快速分析文档基本信息

### 5.4 工具分类总结

| 类别 | 工具 | 用途 |
|------|------|------|
| **任务管理** | `submit_conversion_task` | 提交异步任务 |
| | `get_task_status` | 查询进度 |
| | `get_task_result` | 获取结果 |
| | `cancel_task` | 取消任务 |
| | `list_tasks` | 任务列表 |
| **同步转换** | `convert_to_markdown` | URI 快速转换 |
| | `convert_file_content` | 文件内容快速转换 |
| **辅助工具** | `get_supported_formats` | 格式发现 |
| | `ocr_image` | 图像 OCR |
| | `get_document_metadata` | 元数据提取 |

### 5.5 推荐使用场景

| 场景 | 推荐工具 | 原因 |
|------|----------|------|
| 小文件（<5MB）无 OCR | `convert_to_markdown` 或 `convert_file_content` | 快速、简单 |
| 大文件或 OCR 处理 | `submit_conversion_task` + `get_task_status` | 异步、可追踪 |
| 批量处理 | `submit_conversion_task`（多次） | 并行处理 |
| 图像 OCR | `ocr_image` | 专用工具 |
| 格式查询 | `get_supported_formats` | 发现工具 |

---

## 6. 实现路线图

### 第一阶段：基础增强（第 1 周）

1. 向现有 MCP 服务器添加 OCR 配置支持
2. 实现 `convert_to_markdown_with_ocr` 工具
3. 添加 OCR 设置的环境变量处理

### 第二阶段：扩展工具（第 2 周）

1. 实现 `convert_batch` 多文件处理
2. 添加 `get_supported_formats` 发现工具
3. 实现 `ocr_image` 直接图像 OCR

### 第三阶段：高级功能（第 3 周）

1. 实现 `extract_images` 工具
2. 添加 `get_document_metadata` 工具
3. 创建全面的错误处理机制

### 第四阶段：文档与测试（第 4 周）

1. 编写全面的 README
2. 创建使用示例
3. 添加集成测试
4. 发布到 PyPI

---

## 7. 配置方案

### 7.1 环境变量

```bash
# 核心 MarkItDown
MARKITDOWN_ENABLE_PLUGINS=false  # 启用插件系统

# OCR 配置
MARKITDOWN_OCR_API_KEY=sk-xxx    # OCR 必需
MARKITDOWN_OCR_API_BASE=https://api.openai.com/v1  # 可选
MARKITDOWN_OCR_MODEL=gpt-4o      # OCR 必需
```

### 7.2 MCP 客户端配置

**Claude Desktop（STDIO）：**
```json
{
  "mcpServers": {
    "markitdown-ocr": {
      "command": "markitdown-ocr-mcp",
      "env": {
        "MARKITDOWN_OCR_API_KEY": "sk-xxx",
        "MARKITDOWN_OCR_MODEL": "gpt-4o"
      }
    }
  }
}
```

**Claude Desktop（Docker）：**
```json
{
  "mcpServers": {
    "markitdown-ocr": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "MARKITDOWN_OCR_API_KEY=sk-xxx",
        "-e", "MARKITDOWN_OCR_MODEL=gpt-4o",
        "markitdown-ocr-mcp:latest"
      ]
    }
  }
}
```

---

## 8. 与官方 MCP 服务器对比

| 功能 | 官方 MCP | 建议增强版 MCP |
|------|----------|----------------|
| 基础转换 | ✅ | ✅ |
| OCR 支持 | ❌ | ✅ |
| 批量处理 | ❌ | ✅ |
| 格式发现 | ❌ | ✅ |
| 图像提取 | ❌ | ✅ |
| 元数据提取 | ❌ | ✅ |
| 插件系统 | 可选 | 必需 |
| LLM 依赖 | 无 | OpenAI 兼容 |

---

## 9. 安全考虑

### 9.1 OCR 带来的额外风险

| 风险 | 缓解措施 |
|------|----------|
| API 密钥泄露 | 使用环境变量，禁止日志记录 |
| LLM API 成本 | 速率限制，用量监控 |
| 图像数据传输 | 本地处理选项 |
| 提示词注入 | 清理用户输入 |

### 9.2 建议

1. **禁止在日志或响应中暴露 API 密钥**
2. **为 OCR 调用实施速率限制**
3. **提供本地 OCR 替代方案（如 Tesseract）**
4. **处理前验证 URI 方案**
5. **清理提示词以防止注入攻击**

---

## 10. 结论

### 可行性总结

构建带有 OCR 功能的增强版 MCP 服务器**可行性很高**：

- ✅ 现有 MCP 基础设施提供坚实基础
- ✅ 插件系统已支持 OCR 集成
- ✅ FastMCP 简化工具实现
- ✅ 包之间职责分离清晰

### 推荐方案

**方案 A：扩展官方 MCP 服务器**

优点：
- 单一包维护
- 与官方实现一致
- 部署简单

缺点：
- 添加可选依赖
- 可能使官方包复杂化

**方案 B：创建独立包（推荐）**

优点：
- 职责分离清晰
- 可选安装
- 独立版本控制
- 可独立演进

缺点：
- 需维护额外包
- 可能存在重复

### 下一步行动

1. 创建 `packages/markitdown-ocr-mcp` 包结构
2. 使用 FastMCP 实现核心工具
3. 添加全面的配置处理
4. 编写文档和示例
5. 使用 Claude Desktop 和 MCP Inspector 测试
6. 发布到 PyPI

---

## 11. 异步任务架构设计

### 11.1 为什么需要异步任务？

| 场景 | 同步处理问题 | 异步任务优势 |
|------|-------------|-------------|
| 大文件（>10MB） | 超时、内存压力 | 后台处理，不阻塞 |
| OCR 转换 | LLM API 响应慢 | 进度可追踪 |
| 批量转换 | 长时间等待 | 并行处理 |
| 网络不稳定 | 连接中断丢失 | 任务持久化 |

### 11.2 异步任务工具设计

```python
# 工具 1: 提交转换任务
@mcp.tool()
async def submit_conversion_task(
    content: str,       # Base64 文件内容
    filename: str,
    options: dict = {}  # OCR、格式等选项
) -> str:
    """提交转换任务，返回 task_id"""
    return "task_abc123"

# 工具 2: 查询任务状态
@mcp.tool()
async def get_task_status(task_id: str) -> dict:
    """获取任务进度和状态"""
    return {
        "status": "processing",  # pending/processing/completed/failed
        "progress": 45,          # 0-100
        "message": "Processing page 3/10"
    }

# 工具 3: 获取转换结果
@mcp.tool()
async def get_task_result(task_id: str) -> str:
    """获取转换结果（Markdown）"""
    return "# Document Content..."

# 工具 4: 取消任务
@mcp.tool()
async def cancel_task(task_id: str) -> bool:
    """取消待处理/处理中的任务"""
    return True
```

### 11.3 SSE 通知机制

MCP 协议已支持 SSE，可实现服务端推送：

```python
# 在任务完成时发送通知
await send_sse_event({
    "event": "task_completed",
    "data": {
        "task_id": "task_abc123",
        "status": "completed",
        "result_available": True
    }
})
```

### 11.4 文件上传方式对比

| 方面 | Base64（推荐） | Form/Multipart |
|------|---------------|----------------|
| MCP 协议兼容性 | ✅ 完全兼容 JSON-RPC | ❌ 需要额外 HTTP 端点 |
| 实现复杂度 | 低 - 标准工具参数 | 高 - 需要单独 HTTP 服务 |
| 传输效率 | ~33% 增加（编码开销） | 原始二进制传输 |
| 客户端支持 | 所有 MCP 客户端 | 仅 HTTP 客户端 |
| 调试便利性 | ✅ JSON 可读 | ❌ 二进制不可读 |

**推荐使用 Base64 方式**，因为它保持了 MCP 协议的一致性和简洁性。

---

## 12. 存储架构设计

### 12.1 目录结构

按年/月/日组织文件，防止单目录文件过多：

```
storage/
├── 2026/
│   ├── 04/
│   │   ├── 10/
│   │   │   ├── task_abc123_source.pdf
│   │   │   ├── task_abc123_result.md
│   │   │   ├── task_def456_source.docx
│   │   │   └── ...
│   │   └── 11/
│   │       └── ...
│   └── 05/
│       └── ...
├── tasks.db  # SQLite 数据库
```

### 12.2 SQLite 表结构

```sql
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    status TEXT DEFAULT 'pending',      -- pending/processing/completed/failed
    progress INTEGER DEFAULT 0,         -- 0-100
    message TEXT,                       -- "Processing page 3/10"
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    source_path TEXT,                   -- storage/2026/04/10/task_abc123_source.pdf
    result_path TEXT,                   -- storage/2026/04/10/task_abc123_result.md
    options_json TEXT,                  -- {"ocr": true, "model": "gpt-4o"}
    error_message TEXT
);

CREATE INDEX idx_status ON tasks(status);
CREATE INDEX idx_created ON tasks(created_at);
```

### 12.3 存储方案对比

| 特性 | 纯文件系统 | SQLite + 文件系统（推荐） |
|------|-----------|-------------------------|
| 单任务查询 | O(n) 遍历 | O(1) 索引 |
| 状态过滤 | 需解析所有 JSON | SQL WHERE |
| 并发安全 | 需手动加锁 | 内置事务 |
| 进度更新 | 重写整个文件 | 单字段更新 |
| 部署复杂度 | 无依赖 | 单文件数据库 |

### 12.4 任务存储实现

```python
import sqlite3
import json
from datetime import datetime
from pathlib import Path

class TaskStore:
    def __init__(self, storage_dir: str):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(f"{storage_dir}/tasks.db")
        self._init_db()
    
    def _init_db(self):
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                status TEXT DEFAULT 'pending',
                progress INTEGER DEFAULT 0,
                message TEXT,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                source_path TEXT,
                result_path TEXT,
                options_json TEXT,
                error_message TEXT
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_status ON tasks(status)")
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_created ON tasks(created_at)")
    
    def _get_date_path(self) -> Path:
        """获取按日期组织的存储路径"""
        now = datetime.now()
        path = self.storage_dir / str(now.year) / f"{now.month:02d}" / f"{now.day:02d}"
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def create_task(self, task_id: str, source_content: bytes, filename: str, options: dict) -> str:
        """创建任务并保存源文件"""
        date_path = self._get_date_path()
        source_path = str(date_path / f"{task_id}_source_{filename}")
        
        # 保存源文件
        with open(source_path, 'wb') as f:
            f.write(source_content)
        
        # 创建数据库记录
        self.db.execute("""
            INSERT INTO tasks (task_id, source_path, options_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (task_id, source_path, json.dumps(options), datetime.now(), datetime.now()))
        self.db.commit()
        
        return source_path
    
    def update_progress(self, task_id: str, progress: int, message: str):
        """更新任务进度"""
        self.db.execute("""
            UPDATE tasks SET progress=?, message=?, updated_at=?, status='processing'
            WHERE task_id=?
        """, (progress, message, datetime.now(), task_id))
        self.db.commit()
    
    def complete_task(self, task_id: str, result_content: str):
        """完成任务并保存结果"""
        date_path = self._get_date_path()
        result_path = str(date_path / f"{task_id}_result.md")
        
        # 保存结果文件
        with open(result_path, 'w', encoding='utf-8') as f:
            f.write(result_content)
        
        # 更新数据库记录
        self.db.execute("""
            UPDATE tasks SET status='completed', progress=100, result_path=?, updated_at=?
            WHERE task_id=?
        """, (result_path, datetime.now(), task_id))
        self.db.commit()
    
    def fail_task(self, task_id: str, error_message: str):
        """标记任务失败"""
        self.db.execute("""
            UPDATE tasks SET status='failed', error_message=?, updated_at=?
            WHERE task_id=?
        """, (error_message, datetime.now(), task_id))
        self.db.commit()
    
    def get_task(self, task_id: str) -> dict | None:
        """获取任务信息"""
        row = self.db.execute(
            "SELECT * FROM tasks WHERE task_id=?", (task_id,)
        ).fetchone()
        if row:
            columns = ["task_id", "status", "progress", "message", "created_at", 
                       "updated_at", "source_path", "result_path", "options_json", "error_message"]
            return dict(zip(columns, row))
        return None
    
    def get_result(self, task_id: str) -> str | None:
        """获取转换结果"""
        task = self.get_task(task_id)
        if task and task["status"] == "completed" and task["result_path"]:
            with open(task["result_path"], 'r', encoding='utf-8') as f:
                return f.read()
        return None
```

---

## 13. 进度跟踪实现

### 13.1 当前状态分析

当前转换器**不支持进度回调**。查看 [`PdfConverterWithOCR`](packages/markitdown-ocr/src/markitdown_ocr/_pdf_converter_with_ocr.py:180-333)：

```python
def convert(self, file_stream, stream_info, **kwargs):
    # 遍历 PDF 页面 - 无进度通知
    for page_num, page in enumerate(pdf.pages, 1):
        # 提取图像
        # OCR 处理
        # 合并结果
```

### 13.2 进度回调改造方案

**方案 1：添加进度回调参数**

```python
from typing import Callable

class PdfConverterWithOCR(DocumentConverter):
    def convert(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        **kwargs: Any,
    ) -> DocumentConverterResult:
        
        with pdfplumber.open(pdf_bytes) as pdf:
            total_pages = len(pdf.pages)
            for page_num, page in enumerate(pdf.pages, 1):
                # 处理页面...
                
                # 调用进度回调
                if progress_callback:
                    progress_callback(
                        current=page_num,
                        total=total_pages,
                        message=f"Processing page {page_num}/{total_pages}"
                    )
```

**方案 2：异步任务处理器**

```python
class ConversionTaskProcessor:
    def __init__(self, task_store: TaskStore, ocr_service: LLMVisionOCRService):
        self.task_store = task_store
        self.ocr_service = ocr_service
    
    async def process_task(self, task_id: str):
        """异步处理转换任务"""
        # 更新状态为处理中
        self.task_store.update_progress(task_id, 0, "Starting conversion...")
        
        # 获取任务信息
        task = self.task_store.get_task(task_id)
        if not task:
            return
        
        # 读取源文件
        with open(task["source_path"], 'rb') as f:
            file_stream = io.BytesIO(f.read())
        
        # 创建进度回调
        def on_progress(current: int, total: int, message: str):
            progress = int(current / total * 100)
            self.task_store.update_progress(task_id, progress, message)
            # 发送 SSE 事件通知
            self._send_sse_notification(task_id, progress, message)
        
        # 执行转换
        try:
            converter = PdfConverterWithOCR(ocr_service=self.ocr_service)
            result = converter.convert(
                file_stream,
                StreamInfo(filename=task["source_path"]),
                progress_callback=on_progress
            )
            
            # 保存结果
            self.task_store.complete_task(task_id, result.markdown)
            self._send_sse_notification(task_id, 100, "Conversion completed")
            
        except Exception as e:
            self.task_store.fail_task(task_id, str(e))
            self._send_sse_notification(task_id, -1, f"Error: {str(e)}")
    
    def _send_sse_notification(self, task_id: str, progress: int, message: str):
        """发送 SSE 事件通知"""
        # SSE 推送实现
        pass
```

### 13.3 需要修改的文件

| 文件 | 改动内容 |
|------|----------|
| [`_pdf_converter_with_ocr.py`](packages/markitdown-ocr/src/markitdown_ocr/_pdf_converter_with_ocr.py) | 添加 `progress_callback` 参数 |
| [`_docx_converter_with_ocr.py`](packages/markitdown-ocr/src/markitdown_ocr/_docx_converter_with_ocr.py) | 添加进度回调支持 |
| [`_pptx_converter_with_ocr.py`](packages/markitdown-ocr/src/markitdown_ocr/_pptx_converter_with_ocr.py) | 添加进度回调支持 |
| [`_xlsx_converter_with_ocr.py`](packages/markitdown-ocr/src/markitdown_ocr/_xlsx_converter_with_ocr.py) | 添加进度回调支持 |

### 13.4 进度信息示例

```json
{
  "task_id": "task_abc123",
  "status": "processing",
  "progress": 45,
  "message": "OCR processing page 5/10",
  "created_at": "2026-04-10T09:30:00Z",
  "updated_at": "2026-04-10T09:32:15Z"
}
```

---

## 附录 A：代码示例

### A.1 带 OCR 的基础 MCP 服务器

```python
# src/markitdown_ocr_mcp/__main__.py
import os
from mcp.server.fastmcp import FastMCP
from markitdown import MarkItDown

mcp = FastMCP("markitdown-ocr")

def get_ocr_enabled() -> bool:
    return os.getenv("MARKITDOWN_OCR_ENABLED", "false").lower() == "true"

@mcp.tool()
async def convert_to_markdown(uri: str) -> str:
    """将文档 URI 转换为 Markdown"""
    return MarkItDown(enable_plugins=get_ocr_enabled()).convert_uri(uri).markdown

@mcp.tool()
async def convert_to_markdown_with_ocr(uri: str, ocr_prompt: str = None) -> str:
    """将文档转换为 Markdown，并对嵌入图像进行 OCR"""
    kwargs = {}
    if ocr_prompt:
        kwargs["llm_prompt"] = ocr_prompt
    return MarkItDown(enable_plugins=True).convert_uri(uri, **kwargs).markdown

if __name__ == "__main__":
    mcp.run()
```

### A.2 PyProject 配置

```toml
[project]
name = "markitdown-ocr-mcp"
version = "0.1.0"
description = "带 OCR 支持的 MarkItDown MCP 服务器"
dependencies = [
  "mcp~=1.8.0",
  "markitdown[all]>=0.1.0",
  "markitdown-ocr>=0.1.0",
]

[project.optional-dependencies]
llm = ["openai>=1.0.0"]

[project.scripts]
markitdown-ocr-mcp = "markitdown_ocr_mcp.__main__:main"

[project.entry-points."markitdown.plugin"]
ocr-mcp = "markitdown_ocr_mcp"
```

---

## 14. Docker 部署方案

### 14.1 Dockerfile 设计

在 `packages/markitdown-ocr-mcp/` 创建 Dockerfile：

```dockerfile
# packages/markitdown-ocr-mcp/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖（OCR 可能需要）
RUN apt-get update && apt-get install -y \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 包（从本地 monorepo）
COPY packages/markitdown /tmp/markitdown
COPY packages/markitdown-ocr /tmp/markitdown-ocr
COPY packages/markitdown-ocr-mcp /tmp/markitdown-ocr-mcp

RUN pip install /tmp/markitdown[all] \
    && pip install /tmp/markitdown-ocr \
    && pip install /tmp/markitdown-ocr-mcp \
    && rm -rf /tmp/*

# 创建存储目录
RUN mkdir -p /app/storage

# 设置环境变量
ENV MARKITDOWN_STORAGE_DIR=/app/storage

# 入口点
ENTRYPOINT ["markitdown-ocr-mcp"]
CMD ["--http", "--host", "0.0.0.0", "--port", "3001"]
```

### 14.2 多阶段构建（优化镜像大小）

```dockerfile
# 构建阶段
FROM python:3.11-slim AS builder
WORKDIR /build
COPY packages/markitdown ./markitdown
COPY packages/markitdown-ocr ./markitdown-ocr
COPY packages/markitdown-ocr-mcp ./markitdown-ocr-mcp
RUN pip wheel --wheel-dir=/wheels \
    ./markitdown[all] \
    ./markitdown-ocr \
    ./markitdown-ocr-mcp

# 运行阶段
FROM python:3.11-slim
WORKDIR /app

# 安装运行依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 包
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

# 创建存储目录
RUN mkdir -p /app/storage

# 设置环境变量
ENV MARKITDOWN_STORAGE_DIR=/app/storage

# 入口点
ENTRYPOINT ["markitdown-ocr-mcp"]
CMD ["--http", "--host", "0.0.0.0", "--port", "3001"]
```

### 14.3 构建和推送镜像

```bash
# 在 monorepo 根目录构建
docker build -f packages/markitdown-ocr-mcp/Dockerfile -t markitdown-ocr-mcp:latest .

# 标记为 Docker Hub 仓库
docker tag markitdown-ocr-mcp:latest your-username/markitdown-ocr-mcp:latest
docker tag markitdown-ocr-mcp:latest your-username/markitdown-ocr-mcp:v0.1.0

# 登录 Docker Hub
docker login

# 推送镜像
docker push your-username/markitdown-ocr-mcp:latest
docker push your-username/markitdown-ocr-mcp:v0.1.0
```

### 14.4 GitHub Actions 自动构建

```yaml
# .github/workflows/docker.yml
name: Build and Push Docker Image

on:
  push:
    tags:
      - 'v*'
  workflow_dispatch:  # 手动触发

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      
      - name: Login to Docker Hub
        uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}
      
      - name: Extract version
        id: version
        run: echo "VERSION=${GITHUB_REF#refs/tags/}" >> $GITHUB_OUTPUT
      
      - name: Build and Push
        uses: docker/build-push-action@v5
        with:
          context: .
          file: packages/markitdown-ocr-mcp/Dockerfile
          push: true
          tags: |
            ${{ secrets.DOCKERHUB_USERNAME }}/markitdown-ocr-mcp:latest
            ${{ secrets.DOCKERHUB_USERNAME }}/markitdown-ocr-mcp:${{ steps.version.outputs.VERSION }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

### 14.5 使用 Docker 镜像

**Claude Desktop 配置（STDIO 模式）：**
```json
{
  "mcpServers": {
    "markitdown-ocr": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "MARKITDOWN_OCR_API_KEY=sk-xxx",
        "-e", "MARKITDOWN_OCR_MODEL=gpt-4o",
        "your-username/markitdown-ocr-mcp:latest"
      ]
    }
  }
}
```

**Claude Desktop 配置（HTTP 模式 + 持久化存储）：**
```json
{
  "mcpServers": {
    "markitdown-ocr": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-e", "MARKITDOWN_OCR_API_KEY=sk-xxx",
        "-e", "MARKITDOWN_OCR_MODEL=gpt-4o",
        "-v", "/home/user/markitdown-storage:/app/storage",
        "-p", "3001:3001",
        "your-username/markitdown-ocr-mcp:latest",
        "--http", "--host", "0.0.0.0", "--port", "3001"
      ]
    }
  }
}
```

### 14.6 Docker Compose 配置

```yaml
# docker-compose.yml
version: '3.8'

services:
  markitdown-ocr-mcp:
    image: your-username/markitdown-ocr-mcp:latest
    build:
      context: .
      dockerfile: packages/markitdown-ocr-mcp/Dockerfile
    ports:
      - "3001:3001"
    volumes:
      - ./storage:/app/storage
    environment:
      - MARKITDOWN_OCR_API_KEY=${MARKITDOWN_OCR_API_KEY}
      - MARKITDOWN_OCR_MODEL=${MARKITDOWN_OCR_MODEL:-gpt-4o}
      - MARKITDOWN_OCR_API_BASE=${MARKITDOWN_OCR_API_BASE:-https://api.openai.com/v1}
    command: ["--http", "--host", "0.0.0.0", "--port", "3001"]
    restart: unless-stopped
```

### 14.7 部署架构图

```
┌─────────────────────────────────────────────────────────────┐
│                     Docker Hub                               │
│  your-username/markitdown-ocr-mcp:latest                    │
│  your-username/markitdown-ocr-mcp:v0.1.0                    │
└─────────────────────────────────────────────────────────────┘
                           │
                           │ docker pull
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     用户环境                                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Docker 容器                              │   │
│  │  ┌─────────────────────────────────────────────┐    │   │
│  │  │         markitdown-ocr-mcp                   │    │   │
│  │  │  ┌─────────────────────────────────────┐    │    │   │
│  │  │  │  MCP Server (FastMCP)               │    │    │   │
│  │  │  │  - STDIO / HTTP / SSE               │    │    │   │
│  │  │  └─────────────────────────────────────┘    │    │   │
│  │  │  ┌─────────────────────────────────────┐    │    │   │
│  │  │  │  Task Store (SQLite)                │    │    │   │
│  │  │  │  /app/storage/tasks.db              │    │    │   │
│  │  │  └─────────────────────────────────────┘    │    │   │
│  │  │  ┌─────────────────────────────────────┐    │    │   │
│  │  │  │  MarkItDown + OCR Plugin            │    │    │   │
│  │  │  │  (内置 Python 库)                   │    │    │   │
│  │  │  └─────────────────────────────────────┘    │    │   │
│  │  └─────────────────────────────────────────────┘    │   │
│  │                      │                              │   │
│  │                      │ LLM API 调用                 │   │
│  │                      ▼                              │   │
│  │  ┌─────────────────────────────────────────────┐    │   │
│  │  │         OpenAI / 其他 LLM API               │    │   │
│  │  │         (外部服务)                          │    │   │
│  │  └─────────────────────────────────────────────┘    │   │
│  └─────────────────────────────────────────────────────┘   │
│                      │                                      │
│                      │ MCP 协议                             │
│                      ▼                                      │
│  ┌─────────────────────────────────────────────────────┐   │
│  │         Claude Desktop / MCP Client                 │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 附录 B：参考资料

- [MCP 规范](https://modelcontextprotocol.io/)
- [FastMCP 文档](https://github.com/modelcontextprotocol/python-sdk)
- [MarkItDown 仓库](https://github.com/microsoft/markitdown)
- [MarkItDown MCP 服务器](https://github.com/microsoft/markitdown/tree/main/packages/markitdown-mcp)