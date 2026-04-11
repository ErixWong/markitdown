#!/usr/bin/env python3
"""
MCP Client Test Script for markitdown-ocr-mcp server.

Tests all MCP tools via HTTP transport.
"""

import asyncio
import base64
import httpx
import sys
from pathlib import Path

# Server URL (needs trailing slash for MCP)
MCP_URL = "http://127.0.0.1:3000/mcp/"

# MCP required headers
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


async def call_tool(client: httpx.AsyncClient, tool_name: str, arguments: dict) -> dict:
    """Call an MCP tool and return the result."""
    response = await client.post(
        MCP_URL,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        },
        headers=MCP_HEADERS
    )
    
    if response.status_code != 200:
        return {"error": f"HTTP {response.status_code}", "body": response.text}
    
    result = response.json()
    if "error" in result:
        return {"error": result["error"]}
    
    content = result.get("result", {}).get("content", [])
    if content:
        text = content[0].get("text", "")
        return {"text": text}
    
    return {"error": "No content returned"}


async def test_mcp_tools():
    """Test all MCP tools."""
    
    print("=" * 60)
    print("MCP Client Test Script")
    print("=" * 60)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        
        # Test 1: get_supported_formats
        print("\n[Test 1] get_supported_formats")
        print("-" * 40)
        
        result = await call_tool(client, "get_supported_formats", {})
        
        if "error" in result:
            print(f"  ERROR: {result['error']}")
            if "body" in result:
                print(f"  Body: {result['body'][:200]}")
        else:
            print(f"  Response:\n{result['text']}")
        
        # Test 2: submit_conversion_task
        print("\n[Test 2] submit_conversion_task")
        print("-" * 40)
        
        # Create a simple test file content
        test_content = b"# Test Document\n\nThis is a test document for MCP conversion.\n\n## Section 1\n\nSome content here."
        test_content_b64 = base64.b64encode(test_content).decode()
        
        result = await call_tool(client, "submit_conversion_task", {
            "content": test_content_b64,
            "filename": "test.md",
            "options": {"enable_ocr": False}
        })
        
        if "error" in result:
            print(f"  ERROR: {result['error']}")
            return
        
        task_id = result["text"].strip()
        print(f"  Task ID: {task_id}")
        
        # Test 3: get_task_status
        print("\n[Test 3] get_task_status")
        print("-" * 40)
        
        # Wait a bit for processing
        await asyncio.sleep(1)
        
        result = await call_tool(client, "get_task_status", {"task_id": task_id})
        
        if "error" in result:
            print(f"  ERROR: {result['error']}")
        else:
            print(f"  Response:\n{result['text']}")
        
        # Test 4: get_task_result
        print("\n[Test 4] get_task_result")
        print("-" * 40)
        
        # Wait for completion
        await asyncio.sleep(2)
        
        result = await call_tool(client, "get_task_result", {"task_id": task_id})
        
        if "error" in result:
            print(f"  ERROR: {result['error']}")
        else:
            result_text = result["text"]
            if result_text.startswith("Error"):
                print(f"  Result: {result_text}")
            else:
                print(f"  Result length: {len(result_text)} chars")
                print(f"  Preview: {result_text[:200]}...")
        
        # Test 5: list_tasks
        print("\n[Test 5] list_tasks")
        print("-" * 40)
        
        result = await call_tool(client, "list_tasks", {"limit": 5})
        
        if "error" in result:
            print(f"  ERROR: {result['error']}")
        else:
            print(f"  Response:\n{result['text']}")
        
        # Test 6: SSE endpoint
        print("\n[Test 6] SSE endpoint check")
        print("-" * 40)
        
        try:
            sse_response = await client.get(
                "http://127.0.0.1:3002/tasks/events",
                timeout=3.0,
                headers={"Accept": "text/event-stream"}
            )
            print(f"  SSE Status: {sse_response.status_code}")
            print(f"  Content-Type: {sse_response.headers.get('content-type')}")
        except httpx.TimeoutException:
            print("  SSE Status: OK (timeout expected for long-running stream)")
        except Exception as e:
            print(f"  SSE Status: ERROR ({e})")
    
    print("\n" + "=" * 60)
    print("Test completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_mcp_tools())