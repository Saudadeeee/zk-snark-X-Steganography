#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Download verifier_package từ server
Sử dụng: python download_verifier_package.py
"""

import urllib.request
import os
import sys
import io
from pathlib import Path

# Fix encoding for Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

SERVER_URL = "http://192.168.1.119:8006/verifier_package"
OUTPUT_DIR = "verifier_package"

# Danh sách các file cần download
FILES = [
    "README.md",
    "requirements.txt",
    "setup.sh",
    "setup.bat",
    "src/zk_stego/__init__.py",
    "src/zk_stego/hybrid_proof_artifact.py",
    "src/zk_stego/chaos_embedding.py",
    "src/zk_stego/zk_proof_generator.py",
    "circuits/compiled/build/verification_key.json",
    "scripts/verify.py",
]

print("=" * 80)
print("DOWNLOAD VERIFIER PACKAGE")
print("=" * 80)
print(f"Server: {SERVER_URL}")
print(f"Output: {OUTPUT_DIR}")
print()

# Tạo thư mục output
Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

success = 0
failed = 0

for file_path in FILES:
    url = f"{SERVER_URL}/{file_path}"
    output_path = Path(OUTPUT_DIR) / file_path
    
    # Tạo thư mục cha nếu chưa có
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        print(f"Downloading: {file_path}...", end=" ")
        urllib.request.urlretrieve(url, str(output_path))
        size = output_path.stat().st_size
        print(f"[OK] ({size:,} bytes)")
        success += 1
    except Exception as e:
        print(f"[FAILED] Error: {e}")
        failed += 1

print()
print("=" * 80)
print(f"Download complete: {success} success, {failed} failed")
print("=" * 80)
print(f"\nPackage location: {Path(OUTPUT_DIR).absolute()}")
print("\nNext steps:")
print(f"  1. cd {OUTPUT_DIR}")
print("  2. Run setup.sh (Linux/Mac) or setup.bat (Windows)")
print("  3. python scripts/verify.py <stego_image.png>")

