#!/usr/bin/env python3
"""
Direct API test to verify the OpenAI client works.
"""

import sys
import os
import time
from pathlib import Path

# Load .env file
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

print("=" * 60)
print("Direct API Test")
print("=" * 60)

# Get config
api_key = os.environ.get("MARKITDOWN_OCR_API_KEY")
api_base = os.environ.get("MARKITDOWN_OCR_API_BASE")
model = os.environ.get("MARKITDOWN_OCR_MODEL")
timeout = float(os.environ.get("MARKITDOWN_OCR_TIMEOUT", "60"))

print(f"\nConfiguration:")
print(f"  API Key: {'***' + api_key[-8:] if api_key else 'NOT SET'}")
print(f"  API Base: {api_base}")
print(f"  Model: {model}")
print(f"  Timeout: {timeout}s")

# Test 1: Simple text request (no image)
print("\n" + "=" * 60)
print("Test 1: Simple text request (no image)")
print("=" * 60)

from openai import OpenAI

print("\nCreating OpenAI client...")
client = OpenAI(api_key=api_key, base_url=api_base, timeout=timeout)
print(f"Client created: base_url={client.base_url}")

print("\nSending simple text request...")
start_time = time.time()
try:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "user", "content": "Say 'hello' in one word."}
        ],
    )
    elapsed = time.time() - start_time
    print(f"Response received in {elapsed:.2f}s!")
    print(f"  Content: {response.choices[0].message.content}")
except Exception as e:
    elapsed = time.time() - start_time
    print(f"Error after {elapsed:.2f}s: {e}")
    import traceback
    traceback.print_exc()

# Test 2: Vision request with small image
print("\n" + "=" * 60)
print("Test 2: Vision request with small test image")
print("=" * 60)

import base64
import io
from PIL import Image

# Create a small test image (100x50 red rectangle with text "TEST")
print("\nCreating test image...")
img = Image.new('RGB', (100, 50), color='red')
img_stream = io.BytesIO()
img.save(img_stream, format='PNG')
img_stream.seek(0)
base64_image = base64.b64encode(img_stream.read()).decode('utf-8')
data_uri = f"data:image/png;base64,{base64_image}"
print(f"  Image size: {len(base64_image) / 1024:.2f} KB (base64)")

print("\nSending vision request...")
start_time = time.time()
try:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What color is this image?"},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ],
    )
    elapsed = time.time() - start_time
    print(f"Response received in {elapsed:.2f}s!")
    print(f"  Content: {response.choices[0].message.content}")
except Exception as e:
    elapsed = time.time() - start_time
    print(f"Error after {elapsed:.2f}s: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("Test completed!")
print("=" * 60)