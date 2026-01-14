#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Quick Start - ZK-SNARK DCT Video Steganography
===============================================

Hướng dẫn nhanh để nhúng và verify ZK-SNARK proof trong video.
"""

import sys
import os
from pathlib import Path

# Suppress warnings
import warnings
warnings.filterwarnings('ignore')

print("="*70)
print("QUICK START - ZK-SNARK DCT STEGANOGRAPHY")
print("="*70)

print("""
BAT DAU NHANH:

1. EMBEDDING (Nhúng proof vào video)
   ===================================
   
   Cú pháp cơ bản:
   ---------------
   python scripts/embed.py \\
       --input <video_input> \\
       --output <video_output> \\
       --message "Your message here"
   
   Ví dụ:
   ------
   python scripts/embed.py \\
       --input data/raw/foreman_cif.y4m \\
       --output data/output/stego.mp4 \\
       --message "Secret message from Alice" \\
       --crf 18 \\
       --max-frames 100
   
   Tham số:
   --------
   --input      : Video nguồn (required)
   --output     : Video đầu ra với proof nhúng (required)
   --message    : Message để tạo ZK proof (required)
   --metadata   : File metadata JSON (default: <output>.json)
   --crf        : Quality (18=visually lossless, default: 18)
   --max-frames : Giới hạn số frames (optional, để test nhanh)
   
   Output:
   -------
   - <output>.mp4  : Video với proof đã nhúng
   - <output>.json : Metadata (carrier indices, chaos seed)

2. VERIFICATION (Xác thực proof)
   ================================
   
   Cú pháp cơ bản:
   ---------------
   python scripts/verify.py \\
       --video <stego_video> \\
       --metadata <metadata_json>
   
   Ví dụ:
   ------
   python scripts/verify.py \\
       --video data/output/stego.mp4 \\
       --metadata data/output/stego.json \\
       --expected-message "Secret message from Alice"
   
   Tham số:
   --------
   --video            : Stego video (required)
   --metadata         : Metadata JSON (required)
   --expected-message : Message để kiểm tra (optional)
   
   Kết quả:
   --------
   ✓ ZK proof VALID       - Proof hợp lệ
   ✓ Extraction VALID     - Giải mã thành công
   ✓ Message MATCH        - Message khớp (nếu có --expected-message)

3. VIDEO INPUT
   ============
   
   Có sẵn 3 video test:
   --------------------
""")

# List available videos
data_path = Path("data/raw")
if data_path.exists():
    videos = list(data_path.glob("*.y4m")) + list(data_path.glob("*.mp4"))
    for v in videos:
        size_mb = v.stat().st_size / (1024*1024)
        print(f"   ✓ {v.name:20s} ({size_mb:6.2f} MB)")
else:
    print("   [!] data/raw/ not found")

print("""
4. QUALITY SETTINGS
   =================
   
   CRF (Constant Rate Factor):
   ---------------------------
   --crf 18  : Visually lossless (recommended, ~48dB PSNR)
   --crf 23  : High quality (~43dB PSNR)
   --crf 28  : Medium quality (~38dB PSNR)
   
   Lower CRF = Better quality + Larger file

5. CAPACITY
   =========
   
   Embedding capacity:
   -------------------
   - Per frame (CIF 352x288): ~22 KB
   - Per second (30fps):      ~660 KB
   - 100 frames:              ~2.2 MB
   - 300 frames:              ~6.6 MB
   
   ZK-SNARK proof size: ~800 bytes
   → Có thể embed nhiều proofs hoặc data lớn

6. WORKFLOW EXAMPLE
   =================
   
   Step 1: Embed proof
   -------------------
   $ python scripts/embed.py \\
         --input data/raw/foreman_cif.y4m \\
         --output data/output/my_stego.mp4 \\
         --message "Alice sent 100 BTC to Bob" \\
         --max-frames 50
   
   Output:
     ✓ Proof generated: 800 bytes
     ✓ Decoded 50 frames
     ✓ Embedding complete (3,500 carriers)
     ✓ Video encoded (CRF 18)
     ✓ Metadata saved
   
   Step 2: Send video to verifier
   -------------------------------
   Send 2 files:
   - my_stego.mp4   (video with embedded proof)
   - my_stego.json  (metadata with carrier indices)
   
   Step 3: Verify proof
   --------------------
   $ python scripts/verify.py \\
         --video data/output/my_stego.mp4 \\
         --metadata data/output/my_stego.json \\
         --expected-message "Alice sent 100 BTC to Bob"
   
   Result:
     ✓ ZK proof VALID
     ✓ Extraction VALID
     ✓ Message MATCH
     
   → Proof verified successfully!

7. TROUBLESHOOTING
   ================
   
   Issue: Numpy warning
   --------------------
   Warning: "Numpy built with MINGW-W64 is experimental"
   
   Solution: Ignore warning (cosmetic only) hoặc:
   $ pip uninstall numpy opencv-python -y
   $ pip install numpy opencv-python --force-reinstall
   
   Issue: FFmpeg not found
   -----------------------
   Error: "ffmpeg command not found"
   
   Solution: Install FFmpeg
   - Windows: Download từ https://ffmpeg.org/download.html
   - Linux: sudo apt install ffmpeg
   - macOS: brew install ffmpeg
   
   Issue: Import error
   -------------------
   Error: "ModuleNotFoundError: No module named 'scipy'"
   
   Solution: Install dependencies
   $ pip install -r requirements.txt

8. ADVANCED USAGE
   ===============
   
   Custom chaos seed:
   ------------------
   # Modify trong code để dùng seed riêng
   chaos_seed = int(hashlib.sha256(message.encode()).hexdigest(), 16) % (2**32)
   
   Multiple proofs:
   ----------------
   # Concat nhiều proofs thành 1 payload
   payload = proof1 + proof2 + proof3
   
   Custom encoding:
   ----------------
   # Modify video_encoder.py để tune parameters
   encoder = VideoEncoder(output, crf=18, preset="veryslow")

9. DOCUMENTATION
   ==============
   
   Đầy đủ:
   -------
   - README.md              : Comprehensive guide
   - MIGRATION_SUMMARY.md   : Technical details
   - DCT_MIGRATION_COMPLETE.md : Quick summary
   - SYSTEM_EVALUATION.md   : Evaluation report

10. NEXT STEPS
    ===========
    
    ✓ Read README.md for detailed documentation
    ✓ Run validate_structure.py to check system
    ✓ Start with small video (50-100 frames) for testing
    ✓ Increase frames after successful test
    ✓ Measure quality with PSNR/SSIM if needed
""")

print("="*70)
print("READY TO START!")
print("="*70)
print()
print("Run embedding now:")
print('  python scripts/embed.py --input data/raw/foreman_cif.y4m \\')
print('         --output data/output/stego.mp4 \\')
print('         --message "Your secret message" \\')
print('         --max-frames 50')
print()
