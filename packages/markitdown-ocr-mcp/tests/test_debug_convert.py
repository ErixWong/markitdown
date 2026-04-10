#!/usr/bin/env python3
"""
Debug test to find where convert() hangs.
"""

import sys
import os
import io
from pathlib import Path

# Load .env file before other imports
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

print("Step 1: Imports...")

from markitdown import MarkItDown
from markitdown_ocr import LLMVisionOCRService, PdfConverterWithOCR
import pdfplumber

print("Step 1: Done")

print("\nStep 2: Create OCR service...")
ocr_service = LLMVisionOCRService.from_env()
print(f"  Model: {ocr_service.model}")

print("\nStep 3: Create custom converter with debug output...")

class DebugPdfConverterWithOCR(PdfConverterWithOCR):
    def convert(self, file_stream, stream_info, **kwargs):
        print("\n[DEBUG] convert() called!")
        
        # Get OCR service
        ocr_service = kwargs.get("ocr_service") or self.ocr_service
        print(f"[DEBUG] OCR service: {ocr_service is not None}")
        
        # Read PDF into BytesIO
        file_stream.seek(0)
        pdf_bytes = io.BytesIO(file_stream.read())
        print(f"[DEBUG] PDF bytes read: {len(pdf_bytes.getvalue())} bytes")
        
        markdown_content = []
        
        print("[DEBUG] Opening PDF with pdfplumber...")
        with pdfplumber.open(pdf_bytes) as pdf:
            total_pages = len(pdf.pages)
            print(f"[DEBUG] Total pages: {total_pages}")
            
            for page_num, page in enumerate(pdf.pages, 1):
                print(f"[DEBUG] Processing page {page_num}/{total_pages}...")
                
                markdown_content.append(f"\n## Page {page_num}\n")
                
                if ocr_service:
                    print(f"[DEBUG]   Extracting images...")
                    images_on_page = self._extract_page_images(pdf_bytes, page_num)
                    print(f"[DEBUG]   Found {len(images_on_page)} images")
                    
                    if images_on_page:
                        print(f"[DEBUG]   OCR processing {len(images_on_page)} images...")
                        for i, img_info in enumerate(images_on_page):
                            print(f"[DEBUG]     OCR image {i+1}...")
                            ocr_result = ocr_service.extract_text(img_info["stream"])
                            print(f"[DEBUG]     OCR result: {len(ocr_result.text)} chars")
                            if ocr_result.text.strip():
                                markdown_content.append(f"*[Image OCR]\n{ocr_result.text.strip()}\n[End OCR]*")
                    else:
                        print(f"[DEBUG]   No images, extracting text...")
                        text_content = page.extract_text() or ""
                        print(f"[DEBUG]   Text: {len(text_content)} chars")
                        if text_content.strip():
                            markdown_content.append(text_content.strip())
                else:
                    text_content = page.extract_text() or ""
                    if text_content.strip():
                        markdown_content.append(text_content.strip())
                
                print(f"[DEBUG]   Page {page_num} done")
        
        markdown = "\n\n".join(markdown_content).strip()
        print(f"[DEBUG] convert() done! Total: {len(markdown)} chars")
        
        from markitdown import DocumentConverterResult
        return DocumentConverterResult(markdown=markdown)

print("\nStep 4: Create MarkItDown and register converter...")
md = MarkItDown()
md.register_converter(DebugPdfConverterWithOCR(ocr_service=ocr_service), priority=-1.0)
print("  Converter registered")

print("\nStep 5: Get PDF path...")
pdf_path = sys.argv[1] if len(sys.argv) > 1 else None
if not pdf_path:
    print("  No PDF path provided")
    sys.exit(0)

if not Path(pdf_path).exists():
    print(f"  File not found: {pdf_path}")
    sys.exit(1)

print(f"  PDF: {pdf_path}")
print(f"  Size: {Path(pdf_path).stat().st_size / 1024:.1f} KB")

print("\nStep 6: Call md.convert()...")
result = md.convert(pdf_path)

print("\nStep 7: Result!")
print(f"  Total length: {len(result.text_content)} chars")
print(f"  Preview (first 300 chars):\n")
print(result.text_content[:300])

# Save result to txt file in the same directory as input file
print("\nStep 8: Saving result...")
pdf_path_obj = Path(pdf_path)
output_path = pdf_path_obj.parent / f"{pdf_path_obj.stem}.txt"
output_path.write_text(result.text_content, encoding="utf-8")
print(f"  Saved to: {output_path}")
print(f"  File size: {output_path.stat().st_size / 1024:.1f} KB")