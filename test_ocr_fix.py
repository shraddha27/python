#!/usr/bin/env python3
"""Test OCR parsing with numbered tasks."""

import sys
sys.path.insert(0, '/Users/shradd163152/Documents/python')

from backend_fastapi.ai import _parse_tasks_from_ocr_text
from unittest.mock import patch

# Test with the exact format from your handwritten note
ocr_text = """1. Complete the AI project feature update
Regarding project for Task Management complete it by today

2. Test the working of project
Test working and give demo tomorrow

3. Demo the project internally
Share the demo of project by 24 July"""

# Mock the LLM to fail so it uses fallback
with patch("backend_fastapi.ai.generate_response", return_value=None):
    tasks = _parse_tasks_from_ocr_text(ocr_text, "Extract tasks from handwritten note")
    
    print(f"Found {len(tasks)} tasks:\n")
    for i, task in enumerate(tasks, 1):
        print(f"Task {i}:")
        print(f"  Title: {task['title']}")
        print(f"  Description: {task['description']}")
        print()

# Also test with cleaner format
ocr_text_clean = """1. Complete the AI project feature update
Regarding project for Task Management complete it by today
2. Test the working of project
Test working and give demo tomorrow
3. Demo the project internally
Share the demo of project by 24 July"""

print("=" * 60)
print("Testing with cleaner format:\n")

with patch("backend_fastapi.ai.generate_response", return_value=None):
    tasks = _parse_tasks_from_ocr_text(ocr_text_clean, "Extract tasks")
    
    print(f"Found {len(tasks)} tasks:\n")
    for i, task in enumerate(tasks, 1):
        print(f"Task {i}:")
        print(f"  Title: {task['title']}")
        print(f"  Description: {task['description']}")
        print()
