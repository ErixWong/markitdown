#!/usr/bin/env python3
"""
Test script for converting a real PDF file using the MCP server.

Usage:
    1. Start the MCP server: python -m markitdown_ocr_mcp --http --port 3000
    2. Run this test: python test_real_pdf.py
"""

import json
import time
import httpx
import threading

# Configuration
MCP_SERVER_URL = "http://127.0.0.1:3000/mcp/"
SSE_URL = "http://127.0.0.1:3000/tasks/events"
TEST_PDF_PATH = r"D:\tmp\奇瑞质量协议签章版.pdf"
OUTPUT_DIR = r"D:\tmp"

# Global state for SSE events
sse_events = []
sse_running = True
task_completed = False
task_failed = False
last_event_time = None


def listen_sse(task_id: str):
    """Listen to SSE events for a task in a background thread."""
    global sse_events, sse_running, task_completed, task_failed, last_event_time
    url = f"{SSE_URL}?task_id={task_id}"
    
    try:
        with httpx.stream("GET", url, timeout=None) as response:  # No timeout - wait for events
            print(f"  [SSE] Connected to {url}")
            for line in response.iter_lines():
                if not sse_running:
                    break
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data = json.loads(line[5:].strip())
                    sse_events.append({"event": event_type, "data": data})
                    last_event_time = time.time()
                    
                    # Handle different event types (unified structure)
                    # All events have: task_id, status, progress, message
                    status = data.get("status", "")
                    progress = data.get("progress", 0)
                    message = data.get("message", "")
                    
                    if event_type == "task_progress":
                        print(f"  [SSE] Progress: {progress}% - {message}")
                    elif event_type == "task_completed":
                        task_completed = True
                        print(f"  [SSE] Task completed! Fetching result via API...")
                    elif event_type == "task_failed":
                        task_failed = True
                        print(f"  [SSE] Task failed: {message}")
                elif line.startswith(":"):
                    # Heartbeat - update last_event_time
                    last_event_time = time.time()
    except Exception as e:
        print(f"  [SSE] Error: {e}")


def start_sse_listener(task_id: str) -> threading.Thread:
    """Start SSE listener in a background thread."""
    thread = threading.Thread(target=listen_sse, args=(task_id,))
    thread.daemon = True
    thread.start()
    return thread


def call_mcp_tool(tool_name: str, arguments: dict) -> dict:
    """Call an MCP tool via HTTP."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        }
    }
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"
    }
    
    response = httpx.post(MCP_SERVER_URL, json=payload, headers=headers, timeout=30.0)
    response.raise_for_status()
    
    result = response.json()
    if "error" in result:
        raise Exception(f"MCP Error: {result['error']}")
    
    # Extract content from MCP response
    content = result.get("result", {}).get("content", [])
    if content and len(content) > 0:
        text = content[0].get("text", "{}")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": text}
    return {}


def main():
    global sse_running, task_completed, task_failed, last_event_time
    
    print("=" * 60)
    print("MCP PDF Conversion Test (using file_path)")
    print("=" * 60)
    print(f"\nTest file: {TEST_PDF_PATH}")
    print(f"Output directory: {OUTPUT_DIR}")
    print()
    
    # Step 1: Submit conversion task using file_path
    print("[Step 1] Submitting conversion task using file_path...")
    
    # Optional: process only specific pages (useful for testing)
    # Set to "" to process all pages, or "1-3" to process first 3 pages
    PAGE_RANGE = ""  # Process all pages (set to "1-3" for faster testing)
    
    try:
        result = call_mcp_tool("submit_conversion_task", {
            "file_path": TEST_PDF_PATH,
            "options": {
                "enable_ocr": True,
                "page_range": PAGE_RANGE  # Add page_range option
            }
        })
        task_id = result.get("task_id") or result.get("raw", "")
        if not task_id or task_id.startswith("Error"):
            print(f"  ERROR: {result}")
            return
        print(f"  Task ID: {task_id}")
    except Exception as e:
        print(f"  ERROR submitting task: {e}")
        return
    
    # Start SSE listener for real-time notifications
    print("\n[SSE] Starting SSE listener...")
    last_event_time = time.time()
    sse_thread = start_sse_listener(task_id)
    
    # Step 2: Wait for task completion via SSE events
    print("\n[Step 2] Waiting for conversion to complete (via SSE)...")
    idle_timeout = 60  # If no events for 60 seconds, consider it stalled
    
    while not task_completed and not task_failed:
        current_time = time.time()
        
        # Check if we've been idle too long (no events)
        if current_time - last_event_time > idle_timeout:
            print(f"  ERROR: No SSE events for {idle_timeout}s - task may be stalled")
            # Try to get status via API as fallback
            try:
                status = call_mcp_tool("get_task_status", {"task_id": task_id})
                print(f"  [Fallback] Status: {status}")
                if status.get("status") == "completed":
                    task_completed = True
                    break
                elif status.get("status") == "failed":
                    task_failed = True
                    break
                # Reset timer if we got a valid status
                last_event_time = current_time
            except Exception as e:
                print(f"  [Fallback] Error getting status: {e}")
                break
        
        time.sleep(0.5)  # Check frequently
    
    if task_failed:
        print("\n  ERROR: Task failed")
        sse_running = False
        return
    
    # Step 3: Get the result via API
    print("\n[Step 3] Getting conversion result via API...")
    try:
        result = call_mcp_tool("get_task_result", {"task_id": task_id})
        markdown_content = result.get("raw", "")
    except Exception as e:
        print(f"  ERROR getting result: {e}")
        sse_running = False
        return
    
    if not markdown_content or markdown_content.startswith("Error"):
        print(f"  ERROR: No result available")
        sse_running = False
        return
    
    print(f"  Result length: {len(markdown_content):,} characters")
    
    # Step 4: Save the result
    print("\n[Step 4] Saving result...")
    output_path = f"{OUTPUT_DIR}\\奇瑞质量协议签章版.md"
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        print(f"  Saved to: {output_path}")
    except Exception as e:
        print(f"  ERROR saving result: {e}")
        sse_running = False
        return
    
    # Show a preview
    print("\n[Preview] First 500 characters of result:")
    print("-" * 40)
    print(markdown_content[:500])
    if len(markdown_content) > 500:
        print("...")
    print("-" * 40)
    
    print("\n" + "=" * 60)
    print("Test completed successfully!")
    print("=" * 60)
    
    # Stop SSE listener
    sse_running = False
    
    # Print SSE events summary
    if sse_events:
        print("\n[SSE Events Summary]")
        for event in sse_events:
            print(f"  {event['event']}: {event['data']}")


if __name__ == "__main__":
    main()