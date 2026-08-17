#!/usr/bin/env python3
"""Test EasyOCR with handwritten notes."""

import easyocr
from PIL import Image
import sys

# Initialize EasyOCR (better Docker support, no GUI dependencies)
reader = easyocr.Reader(['en'], gpu=False)

# Your image path
image_path = r"c:\Users\shradd163152\Documents\python\handwritten_tasks.jpg"

try:
    # Run OCR
    result = reader.readtext(image_path)
    
    # Extract text
    extracted_text = "\n".join([line[1] for line in result if line and len(line) > 1])
    
    print("=" * 60)
    print("EASYOCR RESULT:")
    print("=" * 60)
    print(extracted_text)
    print("=" * 60)
    
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
