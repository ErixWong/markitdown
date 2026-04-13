# SPDX-FileCopyrightText: 2024-present Microsoft Corporation
#
# SPDX-License-Identifier: MIT
"""
MarkItDown RESTful API Server

Provides HTTP REST API endpoints for file conversion to Markdown.
"""

from .__about__ import __version__
from .server import create_app, run_server

__all__ = ["__version__", "create_app", "run_server"]


def main():
    """Main entry point for the API server."""
    run_server()


if __name__ == "__main__":
    main()