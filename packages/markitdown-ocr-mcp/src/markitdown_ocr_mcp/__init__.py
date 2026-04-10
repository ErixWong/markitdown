# SPDX-FileCopyrightText: 2025-present Contributors
#
# SPDX-License-Identifier: MIT

"""
markitdown-ocr-mcp: Enhanced MCP server for MarkItDown

Features:
- Async task management (submit, query, cancel)
- OCR support for embedded images
- SSE real-time notifications
- Progress tracking
- Docker deployment support
"""

from .__about__ import __version__

__all__ = [
    "__version__",
]