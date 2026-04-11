#!/usr/bin/env python3
"""
Diagnostic script for Section 1 benchmark.
Deletes old files, runs benchmark, validates output against theory.
"""

import os
import sys
import json
import subprocess
from pathlib import Path
import numpy as np

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from benchmark._common import RESULTS_DIR, OUTPUT_DIR, SEQUENCES
from benchmark.sec1_quality import run, QUALITY_SEQUENCES, STEGO_OUTPUTS


def diagnose_environment():
    """Check environment for required tools and files."""
    print("\n" + "="*70)
    print(" ENVIRONMENT DIAGNOSTICS")
    print("="*70)
    
    # 1. Check ffmpeg
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=5
        )
        if result.returncode == 0:
            version_line = result.stdout.decode().split('\n')[0]
            print(f"✓ ffmpeg: {version_line}")
        else:
            print(f"✗ ffmpeg: command failed with code {result.returncode}")
            return False
    except FileNotFoundError:
        print("✗ ffmpeg: not found in PATH")
        return False
    except Exception as e:
        print(f"✗ ffmpeg: error - {e}")
        return False
    
    # 2. Check source videos exist
    print("\nSource videos:")
    for seq, path in QUALITY_SEQUENCES.items():
        if path.exists():
            size_mb = path.stat().st_size / (1024*1024)
            print(f"  ✓ {seq}: {path.name} ({size_mb:.1f} MB)")
        else:
            print(f"  ✗ {seq}: NOT FOUND - {path}")
            return False
    
    # 3. Check output directory is writable
    print(f"\nOutput directory: {OUTPUT_DIR}")
    if OUTPUT_DIR.exists():
        print(f"  ✓ Exists")
        try:
            test_file = OUTPUT_DIR / ".write_test"
            test_file.write_text("test")
            test_file.unlink()
            print(f"  ✓ Writable")
        except Exception as e:
            print(f"  ✗ Not writable: {e}")
            return False
    else:
        print(f"  ✗ Does not exist")
        return False
    
    return True


def cleanup_old_data():
    """Delete old cached data and generated files."""
    print("\n" + "="*70)
    print(" CLEANING UP OLD DATA")
    print("="*70)
    
    files_to_delete = [
        RESULTS_DIR / "sec1_quality_data.json",
        RESULTS_DIR / "sec1_psnr_per_frame.png",
        RESULTS_DIR / "sec1_ssim_per_frame.png",
        RESULTS_DIR / "sec1_avg_quality_bar.png",
    ]
    
    # Also delete stego videos
    for seq in QUALITY_SEQUENCES.keys():
        stego_path = OUTPUT_DIR / f"sec1_stego_{seq}.h264"
        if stego_path.exists():
            files_to_delete.append(stego_path)
    
    for fpath in files_to_delete:
        if fpath.exists():
            try:
                fpath.unlink()
                print(f"  ✓ Deleted {fpath.name}")
            except Exception as e:
                print(f"  ✗ Failed to delete {fpath.name}: {e}")
                return False
        else:
            print(f"  - {fpath.name} (not found, OK)")
    
    return True


def run_benchmark():
    """Execute the benchmark with error catching."""
    print("\n" + "="*70)
    print(" RUNNING BENCHMARK")
    print("="*70)
    
    try:
        data = run(force=True)
        return data
    except Exception as e:
        print(f"\n✗ BENCHMARK FAILED WITH EXCEPTION:")
        print(f"  {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return None


def validate_output_data(data):
    """Validate that output data makes sense."""
    print("\n" + "="*70)
    print(" VALIDATING OUTPUT DATA")
    print("="*70)
    
    if not data:
        print("✗ No data returned from benchmark")
        return False
    
    has_errors = False
    
    for seq_name, metrics in data.items():
        print(f"\n{seq_name}:")
        
        # Check required keys
        required_keys = ["psnr", "ssim", "avg_psnr", "avg_idr_psnr", 
                        "avg_pframe_psnr", "psnr_full_video", "avg_ssim"]
        for key in required_keys:
            if key not in metrics:
                print(f"  ✗ Missing key: {key}")
                has_errors = True
        
        # Validate PSNR values
        if "avg_idr_psnr" in metrics:
            psnr = metrics["avg_idr_psnr"]
            if np.isinf(psnr):
                print(f"  ✗ avg_idr_psnr is INF (embedded zero bits?)")
                has_errors = True
            elif np.isnan(psnr):
                print(f"  ✗ avg_idr_psnr is NaN")
                has_errors = True
            elif psnr < 0 or psnr > 100:
                print(f"  ✗ avg_idr_psnr out of range: {psnr:.2f} dB")
                has_errors = True
            else:
                print(f"  ✓ avg_idr_psnr = {psnr:.2f} dB")
        
        # Validate SSIM values
        if "avg_ssim" in metrics:
            ssim = metrics["avg_ssim"]
            if np.isinf(ssim) or np.isnan(ssim):
                print(f"  ✗ avg_ssim is INF/NaN: {ssim}")
                has_errors = True
            elif ssim < 0 or ssim > 1:
                print(f"  ✗ avg_ssim out of range: {ssim:.4f}")
                has_errors = True
            else:
                print(f"  ✓ avg_ssim = {ssim:.4f}")
        
        # Validate per-frame data exists and is not empty
        if "psnr" in metrics:
            psnr_list = metrics["psnr"]
            if not psnr_list:
                print(f"  ✗ psnr list is empty (frames not decoded)")
                has_errors = True
            else:
                finite_psnr = [p for p in psnr_list if np.isfinite(p)]
                print(f"  ✓ psnr: {len(psnr_list)} frames, {len(finite_psnr)} finite")
    
    return not has_errors


def check_stego_videos_exist():
    """Verify stego videos were created."""
    print("\n" + "="*70)
    print(" CHECKING STEGO VIDEO GENERATION")
    print("="*70)
    
    all_exist = True
    for seq_name in QUALITY_SEQUENCES.keys():
        stego_path = STEGO_OUTPUTS[seq_name]
        if stego_path.exists():
            size_mb = stego_path.stat().st_size / (1024*1024)
            print(f"  ✓ {seq_name}: {stego_path.name} ({size_mb:.1f} MB)")
        else:
            print(f"  ✗ {seq_name}: NOT CREATED - {stego_path}")
            all_exist = False
    
    return all_exist


def compare_to_theoretical():
    """Compare measured data to theoretical model."""
    print("\n" + "="*70)
    print(" THEORETICAL MODEL COMPARISON")
    print("="*70)
    
    # Load the data
    cache_path = RESULTS_DIR / "sec1_quality_data.json"
    if not cache_path.exists():
        print("✗ Cache file not found, cannot compare")
        return
    
    with open(cache_path) as f:
        data = json.load(f)
    
    print("\nTheory: Embedding 274 bytes (2192 bits) via LSB of CAVLC T1 signs")
    print("Expected PSNR per embedded frame: ~37-40 dB (imperceptible)")
    print("Expected SSIM per embedded frame: >0.98 (excellent)\n")
    
    for seq_name, metrics in data.items():
        print(f"{seq_name}:")
        idr_psnr = metrics["avg_idr_psnr"]
        full_psnr = metrics["psnr_full_video"]
        ssim = metrics["avg_ssim"]
        
        # Compare to theory
        if idr_psnr > 50 or idr_psnr < 25:
            print(f"  ⚠ IDR PSNR {idr_psnr:.1f} dB - outside expected 25-50 dB range")
        else:
            print(f"  ✓ IDR PSNR {idr_psnr:.1f} dB - in range [25, 50]")
        
        if full_psnr > 50:
            print(f"  ⚠ Full-video PSNR {full_psnr:.1f} dB - higher than typical ~30-40 dB")
            print(f"     (Suggests P-frames have low degradation, check motion compensation)")
        
        if ssim < 0.98:
            print(f"  ⚠ SSIM {ssim:.4f} - below ideal >0.98")
        else:
            print(f"  ✓ SSIM {ssim:.4f} - excellent")


def main():
    """Main diagnostic flow."""
    
    # Step 1: Check environment
    if not diagnose_environment():
        print("\n✗ Environment check failed. Cannot proceed.")
        sys.exit(1)
    
    # Step 2: Clean up
    if not cleanup_old_data():
        print("\n✗ Cleanup failed.")
        sys.exit(1)
    
    # Step 3: Run benchmark
    data = run_benchmark()
    
    if data is None:
        print("\n✗ Benchmark failed")
    else:
        # Step 4: Validate output
        if validate_output_data(data):
            print("\n✓ Output data looks valid")
        else:
            print("\n⚠ Output data has issues")
        
        # Step 5: Check stego videos
        if check_stego_videos_exist():
            print("\n✓ All stego videos created")
        else:
            print("\n✗ Some stego videos missing")
        
        # Step 6: Compare to theory
        compare_to_theoretical()
    
    print("\n" + "="*70)
    print(" DIAGNOSIS COMPLETE")
    print("="*70)


if __name__ == "__main__":
    main()