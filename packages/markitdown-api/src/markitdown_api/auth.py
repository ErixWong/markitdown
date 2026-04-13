# SPDX-FileCopyrightText: 2024-present Microsoft Corporation
#
# SPDX-License-Identifier: MIT
"""
Authentication module for Bearer Token authentication.

Provides optional Bearer Token authentication for API endpoints.
"""

import os
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# Bearer token security scheme
security = HTTPBearer(
    auto_error=False,
    description="Bearer token authentication. Set MARKITDOWN_API_KEY environment variable to enable."
)


def get_api_key() -> Optional[str]:
    """Get API key from environment variable."""
    return os.getenv("MARKITDOWN_API_KEY")


def is_auth_enabled() -> bool:
    """Check if authentication is enabled."""
    return get_api_key() is not None


async def verify_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[str]:
    """
    Verify Bearer token if authentication is enabled.
    
    Args:
        credentials: HTTP Bearer credentials from request
        
    Returns:
        Token string if valid
        
    Raises:
        HTTPException: If authentication is enabled and token is invalid
    """
    api_key = get_api_key()
    
    # If no API key configured, authentication is disabled
    if api_key is None:
        return None
    
    # If API key is configured, require valid token
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required. Authentication is enabled.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    
    if token != api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return token


async def optional_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[str]:
    """
    Optional authentication - only verify if token is provided.
    
    This is useful for endpoints that work with or without authentication,
    but may provide additional features when authenticated.
    
    Args:
        credentials: HTTP Bearer credentials from request
        
    Returns:
        Token string if valid, None if no token provided
    """
    api_key = get_api_key()
    
    # If no API key configured, no authentication
    if api_key is None:
        return None
    
    # If token provided, verify it
    if credentials is not None:
        token = credentials.credentials
        if token == api_key:
            return token
        # Invalid token - raise error
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return None