#!/usr/bin/env python3
"""
Manual test script for PDF conversion.
Usage: python tests/test_pdf_manual.py <pdf_path>
"""

import asyncio
import base64
import sys
import os
from pathlib import Path

# Load .env file before other imports
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Debug: Print OCR configuration
print("OCR Configuration:")
print(f"  MARKITDOWN_OCR_API_KEY: {'***' + os.environ.get('MARKITDOWN_OCR_API_KEY', '')[-8:] if os.environ.get('MARKITDOWN_OCR_API_KEY') else 'NOT SET'}")
print(f"  MARKITDOWN_OCR_MODEL: {os.environ.get('MARKITDOWN_OCR_MODEL', 'NOT SET')}")
print(f"  MARKITDOWN_OCR_API_BASE: {os.environ.get('MARKITDOWN_OCR_API_BASE', 'NOT SET')}")
print()

from markitdown_ocr_mcp._task_store import TaskStore
from markitdown_ocr_mcp._task_processor import TaskProcessor


async def test_direct_conversion(pdf_path: str):
    """Test direct conversion using MarkItDown without MCP."""
    from markitdown import MarkItDown
    
    print(f"\n{'='*60}")
    print("Testing Direct Conversion (No OCR)")
    print(f"{'='*60}")
    
    md = MarkItDown()
    result = md.convert(pdf_path)
    
    print(f"\nFile: {pdf_path}")
    print(f"Text Preview (first 500 chars):\n")
    print(result.text_content[:500])
    print(f"\n... Total length: {len(result.text_content)} characters")


async def test_direct_conversion_with_ocr(pdf_path: str):
    """Test direct conversion using MarkItDown with OCR plugin."""
    from markitdown import MarkItDown
    from markitdown_ocr import register_converters, LLMVisionOCRService, PdfConverterWithOCR
    
    print(f"\n{'='*60}")
    print("Testing Direct Conversion (With OCR)")
    print(f"{'='*60}")
    
    # Create OCR service explicitly
    print("\nCreating OCR service from environment...")
    try:
        ocr_service = LLMVisionOCRService.from_env()
        print(f"OCR service created successfully!")
        print(f"  Model: {ocr_service.model}")
    except Exception as e:
        print(f"Failed to create OCR service: {e}")
        import traceback
        traceback.print_exc()
        ocr_service = None
    
    # Create custom converter with debug output
    print("\nCreating DebugPdfConverterWithOCR...")
    class DebugPdfConverterWithOCR(PdfConverterWithOCR):
        def convert(self, file_stream, stream_info, **kwargs):
            """Override convert to add debug output."""
            print("\n[DEBUG] convert() called!")
            print(f"[DEBUG] stream_info: {stream_info}")
            return super().convert(file_stream, stream_info, **kwargs)
        
        def _ocr_full_pages(self, pdf_bytes, ocr_service):
            """Override to add debug output."""
            import io
            import pdfplumber
            from PIL import Image
            
            print("\n[DEBUG] _ocr_full_pages() called!")
            print(f"Max image dimension: {self.max_image_dimension}")
            
            markdown_parts = []
            pdf_bytes.seek(0)
            with pdfplumber.open(pdf_bytes) as pdf:
                total_pages = len(pdf.pages)
                print(f"Total pages: {total_pages}")
                
                for page_num, page in enumerate(pdf.pages, 1):
                    print(f"\nProcessing page {page_num}/{total_pages}...")
                    
                    # Render page to image at 150 DPI
                    page_img = page.to_image(resolution=150)
                    pil_img = page_img.original
                    print(f"  Original size: {pil_img.width}x{pil_img.height}")
                    
                    # Resize if needed
                    if pil_img.width > self.max_image_dimension or pil_img.height > self.max_image_dimension:
                        scale = min(self.max_image_dimension / pil_img.width, self.max_image_dimension / pil_img.height)
                        new_size = (int(pil_img.width * scale), int(pil_img.height * scale))
                        print(f"  Resizing to: {new_size[0]}x{new_size[1]} (scale: {scale:.2f})")
                        pil_img = pil_img.resize(new_size, Image.LANCZOS)
                    
                    # Calculate base64 size
                    img_stream = io.BytesIO()
                    pil_img.save(img_stream, format="PNG")
                    b64_size = len(img_stream.getvalue())
                    print(f"  PNG size: {b64_size / 1024:.1f} KB")
                    
                    img_stream.seek(0)
                    print(f"  Calling OCR API...")
                    ocr_result = ocr_service.extract_text(img_stream)
                    
                    if ocr_result.text.strip():
                        text_preview = ocr_result.text.strip()[:100]
                        print(f"  OCR result: {len(ocr_result.text)} chars - '{text_preview}...'")
                        markdown_parts.append(f"\n## Page {page_num}\n\n*[Image OCR]\n{ocr_result.text.strip()}\n[End OCR]*")
                    else:
                        print(f"  OCR result: No text extracted")
                        markdown_parts.append(f"\n## Page {page_num}\n\n*[No text could be extracted]*")
            
            return "\n\n".join(markdown_parts)
    
    print("\nCreating MarkItDown instance...")
    md = MarkItDown()
    
    # Register debug converter
    print("\nRegistering debug converter...")
    md.register_converter(DebugPdfConverterWithOCR(ocr_service=ocr_service), priority=-1.0)
    print("Converter registered!")
    
    print(f"\nCalling md.convert({pdf_path})...")
    result = md.convert(pdf_path)
    print("convert() returned!")
    
    print(f"\n{'='*60}")
    print("FINAL RESULT")
    print(f"{'='*60}")
    print(f"\nFile: {pdf_path}")
    print(f"Text Preview (first 500 chars):\n")
    print(result.text_content[:500])
    print(f"\n... Total length: {len(result.text_content)} characters")


async def test_task_processor(pdf_path: str):
    """Test the TaskProcessor with a real PDF file."""
    
    print(f"\n{'='*60}")
    print("Testing TaskProcessor (MCP Backend)")
    print(f"{'='*60}")
    
    # Initialize storage
    storage_dir = Path(__file__).parent.parent / "storage"
    task_store = TaskStore(storage_dir=storage_dir)
    task_processor = TaskProcessor(task_store=task_store, max_concurrent=1)
    
    # Read PDF file
    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        print(f"Error: File not found: {pdf_path}")
        return
    
    file_content = pdf_file.read_bytes()
    file_base64 = base64.b64encode(file_content).decode('utf-8')
    
    # Create task
    task = task_store.create_task(
        file_content_base64=file_base64,
        file_name=pdf_file.name,
        enable_ocr=True,
        metadata={"test": True}
    )
    
    print(f"\nCreated task: {task.task_id}")
    print(f"File name: {task.file_name}")
    print(f"Enable OCR: {task.enable_ocr}")
    print(f"Status: {task.status}")
    
    # Process task
    print("\nProcessing task...")
    
    def progress_callback(tid, progress, message):
        print(f"  Progress: {progress}% - {message}")
    
    try:
        result = await task_processor.process_task(task.task_id, progress_callback)
        print(f"\nTask completed!")
        print(f"Status: {result.status}")
        print(f"Progress: {result.progress}")
        
        if result.result_text:
            print(f"\nResult Preview (first 500 chars):\n")
            print(result.result_text[:500])
            print(f"\n... Total length: {len(result.result_text)} characters")
        
        if result.error:
            print(f"\nError: {result.error}")
            
    except Exception as e:
        print(f"\nError processing task: {e}")
        import traceback
        traceback.print_exc()


async def main():
    if len(sys.argv) < 2:
        print("Usage: python tests/test_pdf_manual.py <pdf_path>")
        print("\nOptions:")
        print("  --direct    Test direct conversion without OCR")
        print("  --ocr       Test direct conversion with OCR")
        print("  --mcp       Test TaskProcessor (MCP backend)")
        print("  --all       Run all tests")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "--all"
    
    # Verify file exists
    if not Path(pdf_path).exists():
        print(f"Error: File not found: {pdf_path}")
        sys.exit(1)
    
    if mode == "--direct":
        await test_direct_conversion(pdf_path)
    elif mode == "--ocr":
        await test_direct_conversion_with_ocr(pdf_path)
    elif mode == "--mcp":
        await test_task_processor(pdf_path)
    else:
        # Run all tests
        try:
            await test_direct_conversion(pdf_path)
        except Exception as e:
            print(f"Direct conversion failed: {e}")
        
        try:
            await test_direct_conversion_with_ocr(pdf_path)
        except Exception as e:
            print(f"OCR conversion failed: {e}")
        
        try:
            await test_task_processor(pdf_path)
        except Exception as e:
            print(f"TaskProcessor test failed: {e}")


if __name__ == "__main__":
    asyncio.run(main())