#!/usr/bin/env python3
"""
Download the all-MiniLM-L6-v2 sentence-transformer model to D:\models
Run this script on your host machine (NOT in Docker) to pre-download the model.
The backend expects the model to be available under:
    D:\models\sentence-transformers\all-MiniLM-L6-v2
"""
import os
import sys
from pathlib import Path

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    print("Installing sentence-transformers...")
    os.system("pip install sentence-transformers torch")
    from sentence_transformers import SentenceTransformer

models_root = Path(r"D:\models")
target_dir = models_root / "sentence-transformers" / "all-MiniLM-L6-v2"
target_dir.mkdir(parents=True, exist_ok=True)

print(f"Downloading all-MiniLM-L6-v2 to {target_dir}")
print("This may take a few minutes (~100MB download)...")

try:
    model = SentenceTransformer(
        "sentence-transformers/all-MiniLM-L6-v2",
        cache_folder=str(models_root),
    )
    model.save(str(target_dir))
    print("✓ Model downloaded successfully!")
    print(f"✓ Model location: {target_dir}")
    print("✓ You can now start your Docker containers")
except Exception as e:
    print(f"✗ Download failed: {e}")
    sys.exit(1)
