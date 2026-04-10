#!/usr/bin/env python3
"""
Test OCR with a real image file.
"""

import sys
import os
import time
import base64
import io
from pathlib import Path

# Load .env file
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from PIL import Image
from openai import OpenAI

# Get image path
image_path = sys.argv[1] if len(sys.argv) > 1 else "D:\\tmp\\screen-book.png"
print(f"Testing with image: {image_path}")

# Check file
if not Path(image_path).exists():
    print(f"Error: File not found: {image_path}")
    sys.exit(1)

file_size = Path(image_path).stat().st_size
print(f"File size: {file_size / 1024:.1f} KB")

# Load and show image info
img = Image.open(image_path)
print(f"Image: {img.width}x{img.height}, format={img.format}, mode={img.mode}")

# Resize if too large
max_dim = 1500
if img.width > max_dim or img.height > max_dim:
    scale = min(max_dim / img.width, max_dim / img.height)
    new_size = (int(img.width * scale), int(img.height * scale))
    print(f"Resizing to: {new_size[0]}x{new_size[1]}")
    img = img.resize(new_size, Image.LANCZOS)

# Convert to RGB if needed
if img.mode not in ("RGB", "L"):
    print(f"Converting mode {img.mode} to RGB")
    img = img.convert("RGB")

# Save to stream
img_stream = io.BytesIO()
img.save(img_stream, format="PNG")
img_stream.seek(0)
base64_image = base64.b64encode(img_stream.read()).decode('utf-8')
data_uri = f"data:image/png;base64,{base64_image}"
print(f"Base64 size: {len(base64_image) / 1024:.1f} KB")

# Get config
api_key = os.environ.get("MARKITDOWN_OCR_API_KEY")
api_base = os.environ.get("MARKITDOWN_OCR_API_BASE")
model = os.environ.get("MARKITDOWN_OCR_MODEL")
timeout = float(os.environ.get("MARKITDOWN_OCR_TIMEOUT", "120"))

print(f"\nAPI config: model={model}, timeout={timeout}s")

# Create client
client = OpenAI(api_key=api_key, base_url=api_base, timeout=timeout)

# Send OCR request
print("\nSending OCR request...")
start_time = time.time()

try:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extract all text from this image. Return ONLY the extracted text, maintaining the original layout and order. Do not add any commentary or description."},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ],
    )
    elapsed = time.time() - start_time
    print(f"\nResponse received in {elapsed:.2f}s!")
    print(f"\nOCR Result:")
    print("-" * 60)
    print(response.choices[0].message.content)
    print("-" * 60)
    
except Exception as e:
    elapsed = time.time() - start_time
    print(f"\nError after {elapsed:.2f}s: {e}")
    import traceback
    traceback.print_exc()