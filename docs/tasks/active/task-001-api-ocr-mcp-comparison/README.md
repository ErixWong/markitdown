# Task-001: markitdown-api vs markitdown-ocr-mcp 对比分析

## 任务信息

- **任务编号**: task-001
- **任务名称**: API 与 OCR-MCP 实现对比分析
- **创建时间**: 2026-04-15
- **完成时间**: 2026-04-15
- **状态**: completed
- **优先级**: medium

## 目标

分析并比较 `markitdown-api` 和 `markitdown-ocr-mcp` 两个包的实现差异，包括:
- 架构设计
- 功能特性
- 代码实现
- API 接口
- 使用场景

### 扩展目标 (2026-04-15)

将 `markitdown-ocr-mcp` 的 PDF 逐页处理功能移植到 `markitdown-api`:
- 实现 PDF 页面提取
- 实现逐页 OCR 处理
- 实现精确进度更新
- 支持页码范围选择

## 工作内容

### 1. 项目结构分析
- ✅ 分析两个包的文件组织
- ✅ 对比依赖关系 (pyproject.toml)
- ✅ 识别核心模块

### 2. 核心实现对比
- ✅ TaskStore 实现对比
  - markitdown-api: 保留文件内容在内存
  - markitdown-ocr-mcp: 仅存储文件路径
  
- ✅ TaskProcessor 实现对比
  - markitdown-api: 整文件处理 → **已更新为支持逐页处理**
  - markitdown-ocr-mcp: 支持 PDF 逐页处理
  
- ✅ SSE 通知实现对比
  - 两者实现几乎相同
  - 统一的事件格式

### 3. API 接口对比
- ✅ markitdown-api: RESTful HTTP API (FastAPI)
- ✅ markitdown-ocr-mcp: MCP 协议工具 + HTTP/SSE

### 4. 功能特性对比
- ✅ 认证机制 (Bearer Token vs 无认证)
- ✅ CORS 支持 (有 vs 无)
- ✅ OCR 支持 (基础 vs 逐页)
- ✅ Silent 模式 (都支持)
- ✅ 直接转换 (有 vs 无)

### 5. 使用场景分析
- ✅ markitdown-api: 传统 Web 应用、需要认证
- ✅ markitdown-ocr-mcp: LLM Agent、PDF OCR 处理

### 6. PDF 逐页处理功能移植 (2026-04-15)
- ✅ 添加 `parse_page_range()` 函数
- ✅ 添加 `extract_pdf_page()` 函数 (使用 PyMuPDF)
- ✅ 添加 `get_pdf_page_count()` 函数
- ✅ 实现 `_process_pdf_page_by_page()` 方法
- ✅ 实现 `_process_whole_file()` 方法
- ✅ 更新 `_process_task()` 方法，自动检测 PDF 并选择处理方式
- ✅ 添加 `PyMuPDF` 和 `pdfplumber` 依赖
- ✅ 更新对比文档

## 输出物

1. **对比分析文档**: `docs/api-vs-ocr-mcp-comparison.md`
   - 架构对比
   - 功能对比表
   - 代码实现差异
   - API 接口对比
   - 使用场景建议

2. **任务记录**: `docs/tasks/active/task-001-api-ocr-mcp-comparison/README.md`

## 关键发现

### 架构差异
- **markitdown-api**: FastAPI + RESTful HTTP，面向传统 Web 集成
- **markitdown-ocr-mcp**: MCP SDK + Starlette，面向 LLM Agent 集成

### 核心功能差异
1. **PDF 处理**:
   - markitdown-api: **已支持逐页处理** (2026-04-15)
   - markitdown-ocr-mcp: 逐页处理，精确进度，支持页码范围

2. **认证安全**:
   - markitdown-api: Bearer Token 认证，CORS 配置
   - markitdown-ocr-mcp: 无认证，设计用于本地可信环境

3. **内存使用**:
   - markitdown-api: Task 对象保留文件内容
   - markitdown-ocr-mcp: 仅存储路径，按需读取

### 代码复用
- SSE 通知实现几乎完全相同
- TaskStore 都使用 SQLite + 文件系统
- 都使用 markitdown-ocr 插件
- **PDF 逐页处理代码已移植到 markitdown-api**

## 建议

### markitdown-api 改进方向
1. ✅ ~~添加 PDF 逐页处理支持~~ (已完成 2026-04-15)
2. 添加任务自动清理功能
3. 优化大文件内存使用

### markitdown-ocr-mcp 改进方向
1. 添加认证机制
2. 添加 CORS 支持
3. 添加直接同步转换端点

## 审查清单

- [x] 代码风格一致
- [x] 功能分析完整
- [x] 无明显问题
- [x] 文档清晰准确
- [x] PDF 逐页处理功能已移植
- [x] 依赖已更新 (PyMuPDF, pdfplumber)

## 归档

完成审查后，此任务应移动到 `docs/tasks/archived/` 目录。

---

**完成时间**: 2026-04-15
**审查状态**: 待审查
