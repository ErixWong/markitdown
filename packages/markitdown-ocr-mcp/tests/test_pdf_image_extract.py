#!/usr/bin/env python3
"""
Test PDF image extraction and OCR directly.
"""

import sys
import os
import io
import base64
import time
from pathlib import Path

# Load .env file
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import pdfplumber
from PIL import Image
from openai import OpenAI

# Get PDF path
pdf_path = sys.argv[1] if len(sys.argv) > 1 else None
if not pdf_path:
    print("Usage: python test_pdf_image_extract.py <pdf_path>")
    sys.exit(1)

print(f"Testing PDF: {pdf_path}")
print(f"File size: {Path(pdf_path).stat().st_size / 1024:.1f} KB")

# Get config
api_key = os.environ.get("MARKITDOWN_OCR_API_KEY")
api_base = os.environ.get("MARKITDOWN_OCR_API_BASE")
model = os.environ.get("MARKITDOWN_OCR_MODEL")
timeout = float(os.environ.get("MARKITDOWN_OCR_TIMEOUT", "120"))

print(f"\nAPI config: model={model}, timeout={timeout}s")
client = OpenAI(api_key=api_key, base_url=api_base, timeout=timeout)

# Open PDF and extract images
print("\nOpening PDF with pdfplumber...")
with pdfplumber.open(pdf_path) as pdf:
    total_pages = len(pdf.pages)
    print(f"Total pages: {total_pages}")
    
    # Process first page only for testing
    page_num = 1
    page = pdf.pages[page_num - 1]
    print(f"\nProcessing page {page_num}...")
    
    # Check for images
    print(f"  Checking page.images...")
    if hasattr(page, "images") and page.images:
        print(f"  Found {len(page.images)} images in page.images")
        images = page.images
    else:
        print(f"  No images in page.images")
        images = []
    
    # Check objects
    print(f"  Checking page.objects...")
    if hasattr(page, "objects"):
        for obj_type in page.objects.keys():
            count = len(page.objects.get(obj_type, []))
            if count > 0:
                print(f"    {obj_type}: {count} objects")
    
    # Try to extract first image
    if images:
        print(f"\n  Extracting first image...")
        img_dict = images[0]
        print(f"    Image dict keys: {img_dict.keys()}")
        print(f"    x0={img_dict.get('x0')}, y0={img_dict.get('top')}, x1={img_dict.get('x1')}, y1={img_dict.get('bottom')}")
        
        # Try Method A: stream.get_data()
        if "stream" in img_dict and hasattr(img_dict["stream"], "get_data"):
            print(f"    Trying stream.get_data()...")
            try:
                img_bytes = img_dict["stream"].get_data()
                print(f"    Got {len(img_bytes)} bytes from stream")
                
                pil_img = Image.open(io.BytesIO(img_bytes))
                print(f"    PIL Image: {pil_img.width}x{pil_img.height}, format={pil_img.format}, mode={pil_img.mode}")
                
                # Convert to RGB if needed
                if pil_img.mode not in ("RGB", "L"):
                    pil_img = pil_img.convert("RGB")
                
                # Resize if too large
                max_dim = 1500
                if pil_img.width > max_dim or pil_img.height > max_dim:
                    scale = min(max_dim / pil_img.width, max_dim / pil_img.height)
                    new_size = (int(pil_img.width * scale), int(pil_img.height * scale))
                    print(f"    Resizing to: {new_size[0]}x{new_size[1]}")
                    pil_img = pil_img.resize(new_size, Image.LANCZOS)
                
                # Save to PNG
                img_stream = io.BytesIO()
                pil_img.save(img_stream, format="PNG")
                img_stream.seek(0)
                
                # Base64 encode
                base64_image = base64.b64encode(img_stream.read()).decode('utf-8')
                print(f"    Base64 size: {len(base64_image) / 1024:.1f} KB")
                
                # Send OCR request
                data_uri = f"data:image/png;base64,{base64_image}"
                print(f"\n  Sending OCR request...")
                start_time = time.time()
                
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "Extract all text from this image. Return ONLY the extracted text."},
                                {"type": "image_url", "image_url": {"url": data_uri}},
                            ],
                        }
                    ],
                )
                elapsed = time.time() - start_time
                print(f"  OCR response received in {elapsed:.2f}s!")
                print(f"  OCR result: {len(response.choices[0].message.content)} chars")
                print(f"\n  OCR Content:")
                print("-" * 60)
                print(response.choices[0].message.content[:500])
                print("-" * 60)
                
            except Exception as e:
                print(f"    Error: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"    No stream in image dict, trying page region rendering...")
            # Method B: render page region
            x0 = img_dict.get("x0", 0)
            y0 = img_dict.get("top", 0)
            x1 = img_dict.get("x1", 0)
            y1 = img_dict.get("bottom", 0)
            
            if x1 > x0 and y1 > y0:
                bbox = (x0, y0, x1, y1)
                print(f"    Bounding box: {bbox}")
                
                cropped_page = page.within_bbox(bbox)
                page_img = cropped_page.to_image(resolution=150)
                pil_img = page_img.original
                print(f"    Rendered image: {pil_img.width}x{pil_img.height}")
                
                # Resize if too large
                max_dim = 1500
                if pil_img.width > max_dim or pil_img.height > max_dim:
                    scale = min(max_dim / pil_img.width, max_dim / pil_img.height)
                    new_size = (int(pil_img.width * scale), int(pil_img.height * scale))
                    print(f"    Resizing to: {new_size[0]}x{new_size[1]}")
                    pil_img = pil_img.resize(new_size, Image.LANCZOS)
                
                # Save to PNG
                img_stream = io.BytesIO()
                pil_img.save(img_stream, format="PNG")
                img_stream.seek(0)
                
                # Base64 encode
                base64_image = base64.b64encode(img_stream.read()).decode('utf-8')
                print(f"    Base64 size: {len(base64_image) / 1024:.1f} KB")
                
                # Send OCR request
                data_uri = f"data:image/png;base64,{base64_image}"
                print(f"\n  Sending OCR request...")
                start_time = time.time()
                
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "Extract all text from this image. Return ONLY the extracted text."},
                                {"type": "image_url", "image_url": {"url": data_uri}},
                            ],
                        }
                    ],
                )
                elapsed = time.time() - start_time
                print(f"  OCR response received in {elapsed:.2f}s!")
                print(f"  OCR result: {len(response.choices[0].message.content)} chars")
                print(f"\n  OCR Content:")
                print("-" * 60)
                print(response.choices[0].message.content[:500])
                print("-" * 60)
    else:
        print(f"\n  No images found on page {page_num}")
        
        # Try full page OCR
        print(f"\n  Trying full page OCR...")
        page_img = page.to_image(resolution=150)
        pil_img = page_img.original
        print(f"    Page image: {pil_img.width}x{pil_img.height}")
        
        # Resize if too large
        max_dim = 1500
        if pil_img.width > max_dim or pil_img.height > max_dim:
            scale = min(max_dim / pil_img.width, max_dim / pil_img.height)
            new_size = (int(pil_img.width * scale), int(pil_img.height * scale))
            print(f"    Resizing to: {new_size[0]}x{new_size[1]}")
            pil_img = pil_img.resize(new_size, Image.LANCZOS)
        
        # Save to PNG
        img_stream = io.BytesIO()
        pil_img.save(img_stream, format="PNG")
        img_stream.seek(0)
        
        # Base64 encode
        base64_image = base64.b64encode(img_stream.read()).decode('utf-8')
        print(f"    Base64 size: {len(base64_image) / 1024:.1f} KB")
        
        # Send OCR request
        data_uri = f"data:image/png;base64,{base64_image}"
        print(f"\n  Sending OCR request...")
        start_time = time.time()
        
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract all text from this image. Return ONLY the extracted text."},
                        {"type": "image_url", "image_url": {"url": data_uri}},
                    ],
                }
            ],
        )
        elapsed = time.time() - start_time
        print(f"  OCR response received in {elapsed:.2f}s!")
        print(f"  OCR result: {len(response.choices[0].message.content)} chars")
        print(f"\n  OCR Content:")
        print("-" * 60)
        print(response.choices[0].message.content[:500])
        print("-" * 60)

print("\nTest completed!")