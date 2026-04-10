#!/usr/bin/env python3
"""
Simple step-by-step test to find where the hang occurs.
"""

import sys
import os
from pathlib import Path

# Load .env file before other imports
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

print("Step 1: Starting imports...")

print("  1.1: Importing os, sys, Path... done")

print("  1.2: Importing OpenAI...")
try:
    from openai import OpenAI
    print("  1.2: OpenAI imported successfully")
except ImportError as e:
    print(f"  1.2: Failed to import OpenAI: {e}")
    sys.exit(1)

print("  1.3: Creating OpenAI client...")
api_key = os.environ.get("MARKITDOWN_OCR_API_KEY")
api_base = os.environ.get("MARKITDOWN_OCR_API_BASE")
model = os.environ.get("MARKITDOWN_OCR_MODEL")
print(f"       API Key: {'***' + api_key[-8:] if api_key else 'NOT SET'}")
print(f"       API Base: {api_base}")
print(f"       Model: {model}")

if api_key and api_base:
    client = OpenAI(api_key=api_key, base_url=api_base)
    print("  1.3: OpenAI client created successfully")
else:
    print("  1.3: Skipping client creation - missing env vars")
    client = None

print("  1.4: Importing MarkItDown...")
from markitdown import MarkItDown
print("  1.4: MarkItDown imported successfully")

print("  1.5: Importing markitdown_ocr...")
from markitdown_ocr import LLMVisionOCRService, PdfConverterWithOCR
print("  1.5: markitdown_ocr imported successfully")

print("\nStep 2: Creating OCR service...")
try:
    ocr_service = LLMVisionOCRService.from_env()
    print(f"  OCR service created: model={ocr_service.model}")
except Exception as e:
    print(f"  Failed to create OCR service: {e}")
    import traceback
    traceback.print_exc()
    ocr_service = None

print("\nStep 3: Creating MarkItDown instance...")
md = MarkItDown()
print("  MarkItDown instance created")

print("\nStep 4: Registering PDF converter with OCR...")
if ocr_service:
    converter = PdfConverterWithOCR(ocr_service=ocr_service)
    md.register_converter(converter, priority=-1.0)
    print("  PDF converter registered")
else:
    print("  Skipping converter registration - no OCR service")

print("\nStep 5: Opening PDF file...")
pdf_path = sys.argv[1] if len(sys.argv) > 1 else None
if not pdf_path:
    print("  No PDF path provided, skipping file test")
    sys.exit(0)

if not Path(pdf_path).exists():
    print(f"  File not found: {pdf_path}")
    sys.exit(1)

print(f"  Opening: {pdf_path}")
file_size = Path(pdf_path).stat().st_size
print(f"  File size: {file_size / 1024:.1f} KB")

print("\nStep 6: Calling md.convert()...")
print("  This may take a while for large PDFs...")

# Add timeout handling
import signal

def timeout_handler(signum, frame):
    print("\n  TIMEOUT: convert() took too long!")
    raise TimeoutError("convert() timeout")

# Set timeout to 60 seconds (Windows doesn't support signal.alarm, so we use a different approach)
print("  Starting conversion (no timeout on Windows)...")

try:
    result = md.convert(pdf_path)
    print("  convert() returned successfully!")
    print(f"\nStep 7: Result")
    print(f"  Text length: {len(result.text_content)} characters")
    print(f"  Preview (first 200 chars):\n")
    print(result.text_content[:200])
except Exception as e:
    print(f"  Error during conversion: {e}")
    import traceback
    traceback.print_exc()