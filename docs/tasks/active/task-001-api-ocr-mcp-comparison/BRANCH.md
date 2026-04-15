# Git 分支映射

## 关联分支

- **主分支**: main
- **任务分支**: 无 (分析任务，不涉及代码修改)

## 提交记录

本次任务包含代码修改和文档更新：

### 代码修改
- `packages/markitdown-api/src/markitdown_api/task_processor.py`
  - 添加 `parse_page_range()` 函数
  - 添加 `extract_pdf_page()` 函数
  - 添加 `get_pdf_page_count()` 函数
  - 添加 `_process_pdf_page_by_page()` 方法
  - 添加 `_process_whole_file()` 方法
  - 添加 `_report_progress()` 方法
  - 修改 `_process_task()` 方法

- `packages/markitdown-api/pyproject.toml`
  - 添加 `PyMuPDF` 依赖到 `[ocr]` 可选依赖
  - 新增 `[pdf]` 可选依赖组

### 文档更新
- `docs/api-vs-ocr-mcp-comparison.md` - 更新对比信息
- `docs/pdf-page-by-page-implementation.md` - 新增实施说明文档
- `docs/tasks/active/task-001-api-ocr-mcp-comparison/README.md` - 任务说明
- `docs/tasks/active/task-001-api-ocr-mcp-comparison/BRANCH.md` - 本文件

## 合并策略

所有修改已提交到 main 分支。

---

**创建时间**: 2026-04-15
**最后更新**: 2026-04-15
