# markitdown-ocr-resize 项目设计文档

## 背景

### 问题发现

在使用 markitdown-ocr 处理扫描 PDF 时，发现 OCR 结果不完整。经分析发现：

1.**markitdown-ocr 有两条图像提取路径**：

   -**主路径**：直接提取 PDF 嵌入的原始图像（`_extract_images_from_page`）

   -**Fallback 路径**：渲染整个页面到图像（`_ocr_full_pages`）

2.**DPI=150 修改只影响 Fallback 路径**：

- 主路径在图像有 `stream` 键时，直接使用原始数据，不进行 DPI 缩放
- 扫描 PDF 的图像通常是高分辨率（如 3507×2480 像素）

3.**大图像导致问题**：

- 3507×2480 像素的图像转换为 PNG base64 后约 **3.3 MB**
- 超过 nginx 默认的 `client_max_body_size 1m` 限制
- 即使增加到 2m，仍有 28/32 页超过限制
- 更重要的是：**大图像浪费 LLM Vision 算力，OCR 效果不一定更好**

### 测试数据

| 页面 | 原始图像尺寸 | PNG Base64 大小 | 超过 2MB |

|------|-------------|-----------------|----------|

| Page 1 | 3507×2480 | 860 KB | ❌ |

| Page 2 | 3507×2480 | 3270 KB | ✅ |

| Page 20 | 3507×2480 | 4550 KB | ✅ |

| Page 27 | 3507×2480 | 1349 KB | ❌ |

| Page 28 | 3507×2480 | 796 KB | ❌ |

| Page 32 | 3507×2480 | 740 KB | ❌ |

---

## 解决方案

### 核心改进

在 `_extract_images_from_page` 函数中，提取图像后添加缩放逻辑：

```python

# 在 pil_img.convert("RGB") 之后添加：


# Resize large images to reduce LLM Vision API load

max_dimension =1500  # 最大宽度/高度

if pil_img.width> max_dimension or pil_img.height> max_dimension:

    scale =min(max_dimension / pil_img.width, max_dimension / pil_img.height)

    new_size = (int(pil_img.width* scale), int(pil_img.height* scale))

    pil_img = pil_img.resize(new_size, Image.LANCZOS)

```

### 效果预估

| 原始尺寸 | 缩放后尺寸 | PNG Base64 大小 | 缩放比例 |

|----------|-----------|-----------------|----------|

| 3507×2480 | 1500×1060 | ~800 KB | ~75% 减少 |

---

## 项目创建步骤

### 1. Fork markitdown-ocr 仓库

```bash

# 在 GitHub 上 fork microsoft/markitdown

# 或直接 fork markitdown-ocr 子目录


# 克隆到本地

gitclonehttps://github.com/YOUR_USERNAME/markitdown-ocr.git

cdmarkitdown-ocr

```

### 2. 修改源码

文件：`src/markitdown_ocr/_pdf_converter_with_ocr.py`

位置：`_extract_images_from_page` 函数，约第 75 行

修改内容：

```python

# 原代码（约第 75 行）：

if pil_img.modenotin ("RGB", "L"):

    pil_img = pil_img.convert("RGB")


# 修改为：

if pil_img.modenotin ("RGB", "L"):

    pil_img = pil_img.convert("RGB")


# Resize large images to reduce LLM Vision API load

# Target: max 1500 pixels width/height (suitable for OCR)

max_dimension =1500

if pil_img.width> max_dimension or pil_img.height> max_dimension:

    scale =min(max_dimension / pil_img.width, max_dimension / pil_img.height)

    new_size = (int(pil_img.width* scale), int(pil_img.height* scale))

    pil_img = pil_img.resize(new_size, Image.LANCZOS)

```

### 3. 添加配置选项（可选）

为了更灵活，可以添加配置参数：

```python

# 在 PdfConverterWithOCR 类中添加：

def__init__(

    self,

    ocr_service: Optional[LLMVisionOCRService] =None,

    max_image_dimension: int=1500,  # 新增参数

):

    super().__init__()

    self.ocr_service= ocr_service

    self.max_image_dimension= max_image_dimension

```

然后在 `_extract_images_from_page` 中使用 `self.max_image_dimension`。

### 4. 更新版本号

文件：`pyproject.toml` 或 `setup.py`

```python

# 版本号格式建议：

version ="0.1.6b2-resize"  # 或 "0.1.7"

```

### 5. 发布到 PyPI（可选）

```bash

# 构建

python-mbuild


# 发布

twineuploaddist/*

```

### 6. 创建 Docker 镜像

Dockerfile：

```dockerfile

FROM python:3.13-slim


# 安装依赖

RUN pip install markitdown-ocr-resize openai pdfplumber pymupdf pillow


# 设置工作目录

WORKDIR /workdir


# 设置入口点

ENTRYPOINT ["markitdown"]

```

构建：

```bash

dockerbuild-tYOUR_USERNAME/markitdown-ocr:resize.

dockerpushYOUR_USERNAME/markitdown-ocr:resize

```

---

## 测试验证

### 测试脚本

```python

#!/usr/bin/env python3

"""Test image resize effect"""


import pdfplumber

import io

import base64

fromPILimport Image


doc = pdfplumber.open('/workdir/chery_quality.pdf')


for page_num, page inenumerate(doc.pages, 1):

    images = page.images

    if images:

        for img in images:

            # 提取原始图像

            data = img['stream'].get_data()

            pil_img = Image.open(io.BytesIO(data))

          

            # 转换为 RGB

            if pil_img.modenotin ("RGB", "L"):

                pil_img = pil_img.convert("RGB")

          

            # 缩放前大小

            original_size = pil_img.size

          

            # 缩放

            max_dimension =1500

            if pil_img.width> max_dimension or pil_img.height> max_dimension:

                scale =min(max_dimension / pil_img.width, max_dimension / pil_img.height)

                new_size = (int(pil_img.width* scale), int(pil_img.height* scale))

                pil_img = pil_img.resize(new_size, Image.LANCZOS)

          

            # 计算 PNG base64 大小

            png_stream = io.BytesIO()

            pil_img.save(png_stream, format="PNG")

            b64_size =len(base64.b64encode(png_stream.getvalue()).decode())

          

            print(f'Page {page_num}: {original_size} -> {pil_img.size}, {b64_size/1024:.1f} KB')

```

### 预期结果

所有页面的 PNG base64 大小应小于 1 MB，远低于 nginx 2m 限制。

---

## 配置建议

### nginx 配置

```nginx

# 仍然建议增加 client_max_body_size，作为安全余量

client_max_body_size 2m;

```

### LLM Vision 配置

缩放后的图像（1500×1060）对 LLM Vision 来说：

-**足够清晰**：OCR 文字识别无影响

-**节省算力**：图像 token 数量减少约 75%

-**响应更快**：处理时间缩短

---

## 项目结构建议

```

markitdown-ocr-resize/

├── src/

│   └── markitdown_ocr/

│       ├── __init__.py

│       ├── _pdf_converter_with_ocr.py  # 主要修改文件

│       └── _ocr_service.py

├── tests/

│   └── test_resize.py

├── pyproject.toml

├── README.md

└── CHANGELOG.md

```

---

## 后续优化方向

1.**智能缩放**：根据图像内容类型自动选择最佳尺寸

2.**JPEG 格式**：对于照片类图像，使用 JPEG 格式更小

3.**批量处理**：支持多页并行 OCR

4.**进度回调**：添加进度显示支持

---

## 参考链接

- markitdown-ocr 源码：https://github.com/microsoft/markitdown/tree/main/packages/markitdown-ocr
- PIL Image.resize 文档：https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.resize
- LLM Vision 最佳实践：https://platform.openai.com/docs/guides/vision

---

*文档创建时间: 2026-04-10*
