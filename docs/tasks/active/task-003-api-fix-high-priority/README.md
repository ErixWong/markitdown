# Task-003: markitdown-api PDF 处理器高优先级问题修复

## 任务信息

- **任务编号**: task-003
- **任务名称**: PDF 处理器高优先级问题修复
- **创建时间**: 2026-04-15
- **完成时间**: 2026-04-15
- **状态**: completed
- **优先级**: high

## 目标

修复代码审计中发现的高优先级问题：
1. 资源泄漏风险 (extract_pdf_page 函数)
2. Lambda 闭包变量捕获问题

## 修复清单

- [x] 修复 `extract_pdf_page()` 资源泄漏 (try-finally)
- [x] 修复 `_process_pdf_page_by_page()` Lambda 闭包问题 (使用 partial)
- [x] 添加输入验证到 `parse_page_range()` (ValueError)
- [x] 提取进度常量为模块级常量
- [x] 运行测试验证修复
- [x] 更新审计报告

## 修复详情

### 1. 资源泄漏修复

**文件**: `task_processor.py:82-121`

**修复前**:
```python
def extract_pdf_page(pdf_bytes: io.BytesIO, page_num: int) -> io.BytesIO:
    try:
        doc = fitz.open(...)
        new_doc = fitz.open()
        # ... 操作
        new_doc.close()  # 如果 tobytes() 失败，不会执行
        return single_page_bytes
    except Exception as e:
        raise
```

**修复后**:
```python
def extract_pdf_page(pdf_bytes: io.BytesIO, page_num: int) -> io.BytesIO:
    doc = None
    new_doc = None
    try:
        doc = fitz.open(...)
        new_doc = fitz.open()
        # ... 操作
        return single_page_bytes
    finally:
        if doc:
            doc.close()
        if new_doc:
            new_doc.close()
```

### 2. Lambda 闭包修复

**文件**: `task_processor.py:489`

**修复前**:
```python
result = await asyncio.get_event_loop().run_in_executor(
    self._executor,
    lambda: md.convert_stream(single_page_bytes, stream_info=stream_info)
)
```

**修复后**:
```python
from functools import partial

result = await asyncio.get_event_loop().run_in_executor(
    self._executor,
    partial(md.convert_stream, single_page_bytes, stream_info=stream_info)
)
```

### 3. 输入验证

**文件**: `task_processor.py:57-62`

**新增**:
```python
if total_pages <= 0:
    raise ValueError(f"total_pages must be positive, got {total_pages}")
```

### 4. 常量提取

**文件**: `task_processor.py:30-37`

**新增**:
```python
# Progress allocation constants
PROGRESS_INITIAL_SETUP = 10
PROGRESS_PAGE_PROCESSING = 85
PROGRESS_FINAL_COMBINE = 5

# Page processing sub-stages ratio
PAGE_EXTRACT_RATIO = 0.05
PAGE_CONVERT_RATIO = 0.85
```

### 5. 测试验证

```
✓ 导入测试通过
✓ 常量定义验证：10, 85, 5
✓ 输入验证测试：
  - total_pages=0 → ValueError
  - total_pages=-5 → ValueError
✓ 正常功能测试：
  - Empty range: 100 pages
  - Range 1-5: [1, 2, 3, 4, 5]
```

## 相关文件

- `packages/markitdown-api/src/markitdown_api/task_processor.py` - 主要修复文件
- `docs/tracking/api-pdf-processor-audit.md` - 审计报告参考

---

**创建时间**: 2026-04-15
**状态**: 进行中
