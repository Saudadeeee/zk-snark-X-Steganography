#!/usr/bin/env python3
"""
Quick benchmark with detailed debugging for anomaly detection
"""

import sys
import time
import json
import psutil
import numpy as np
from pathlib import Path
from PIL import Image

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.append(str(PROJECT_ROOT / "src"))

from zk_stego.chaos_embedding import ChaosEmbedding

print("🔍 Debugging Benchmark - Checking for Anomalies")
print("="*80)

# Test configuration
image_sizes = [128, 256, 384, 512, 640, 768, 896, 1024]  # 8 sizes
message_length = 50

results = []
process = psutil.Process()

for test_id, size in enumerate(image_sizes, 1):
    print(f"\n{'='*80}")
    print(f"🧪 Test {test_id}: {size}×{size} = {size*size:,} pixels")
    print(f"{'='*80}")
    
    # Create image
    img = Image.new('RGB', (size, size), color=(100, 100, 100))
    message = "x" * message_length
    
    # Memory before
    ram_before = process.memory_info().rss / 1024 / 1024
    print(f"📊 RAM before: {ram_before:.1f} MB")
    
    try:
        # Embed
        print("⏱️  Embedding...")
        start = time.perf_counter()
        img_arr = np.array(img)
        embedder = ChaosEmbedding(image_array=img_arr)
        stego = embedder.embed_message(message)
        embed_time = (time.perf_counter() - start) * 1000
        
        ram_after_embed = process.memory_info().rss / 1024 / 1024
        print(f"   ✅ Done in {embed_time:.2f}ms")
        print(f"   📊 RAM after embed: {ram_after_embed:.1f} MB (+{ram_after_embed-ram_before:.1f} MB)")
        
        # Extract
        print("⏱️  Extracting...")
        start = time.perf_counter()
        stego_arr = np.array(stego)
        extractor = ChaosEmbedding(image_array=stego_arr)
        extracted = extractor.extract_message(message_length)
        extract_time = (time.perf_counter() - start) * 1000
        
        ram_after = process.memory_info().rss / 1024 / 1024
        print(f"   ✅ Done in {extract_time:.2f}ms")
        print(f"   📊 RAM after extract: {ram_after:.1f} MB")
        
        # Verify
        success = (extracted == message)
        print(f"   ✔️  Verification: {'✅ PASS' if success else '❌ FAIL'}")
        
        # Calculate metrics
        total_time = embed_time + extract_time
        ram_used = ram_after - ram_before
        time_per_pixel = total_time / (size * size) * 1000  # μs
        throughput = (message_length * 8 / total_time) * 1000 / 1024 / 8  # KB/s
        
        result = {
            'test_id': test_id,
            'size': size,
            'pixels': size * size,
            'embed_time_ms': round(embed_time, 3),
            'extract_time_ms': round(extract_time, 3),
            'total_time_ms': round(total_time, 3),
            'ram_before_mb': round(ram_before, 2),
            'ram_after_mb': round(ram_after, 2),
            'ram_used_mb': round(ram_used, 2),
            'time_per_pixel_us': round(time_per_pixel, 4),
            'throughput_kbps': round(throughput, 2),
            'success': success
        }
        
        results.append(result)
        
        # Summary
        print(f"\n📈 Metrics:")
        print(f"   Total Time: {total_time:.2f} ms")
        print(f"   RAM Used: {ram_used:.2f} MB")
        print(f"   Time/Pixel: {time_per_pixel:.4f} μs")
        print(f"   Throughput: {throughput:.2f} KB/s")
        
        # Check for anomalies
        if test_id > 1:
            prev = results[-2]
            time_ratio = total_time / prev['total_time_ms']
            pixel_ratio = (size * size) / prev['pixels']
            ram_ratio = ram_used / prev['ram_used_mb'] if prev['ram_used_mb'] > 0 else 0
            
            print(f"\n🔍 Anomaly Check:")
            print(f"   Pixel increase: {pixel_ratio:.2f}×")
            print(f"   Time increase: {time_ratio:.2f}×")
            print(f"   RAM increase: {ram_ratio:.2f}×")
            
            # Flag anomalies
            if time_ratio > pixel_ratio * 1.5:
                print(f"   ⚠️  WARNING: Time increased more than expected!")
                print(f"      Expected: ~{pixel_ratio:.2f}×, Got: {time_ratio:.2f}×")
            
            if ram_ratio > pixel_ratio * 1.5:
                print(f"   ⚠️  WARNING: RAM increased more than expected!")
                print(f"      Expected: ~{pixel_ratio:.2f}×, Got: {ram_ratio:.2f}×")
        
    except Exception as e:
        print(f"   ❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        
        results.append({
            'test_id': test_id,
            'size': size,
            'pixels': size * size,
            'error': str(e),
            'success': False
        })

# Save results
print("\n" + "="*80)
print("💾 Saving results...")
output_dir = Path("detailed_benchmark_results")
output_dir.mkdir(exist_ok=True)

output_file = output_dir / "debug_results.json"
with open(output_file, 'w') as f:
    json.dump({
        'test_config': {
            'image_sizes': image_sizes,
            'message_length': message_length,
            'total_tests': len(results)
        },
        'results': results
    }, f, indent=2)

print(f"✅ Saved: {output_file}")

# Analysis
print("\n" + "="*80)
print("📊 ANALYSIS SUMMARY")
print("="*80)

successful = [r for r in results if r.get('success', False)]
print(f"\nSuccess Rate: {len(successful)}/{len(results)} ({len(successful)/len(results)*100:.1f}%)")

if successful:
    times = [r['total_time_ms'] for r in successful]
    rams = [r['ram_used_mb'] for r in successful]
    time_per_pixels = [r['time_per_pixel_us'] for r in successful]
    
    print(f"\nTime (ms):")
    print(f"  Min: {min(times):.2f}, Max: {max(times):.2f}, Avg: {np.mean(times):.2f}")
    
    print(f"\nRAM (MB):")
    print(f"  Min: {min(rams):.2f}, Max: {max(rams):.2f}, Avg: {np.mean(rams):.2f}")
    
    print(f"\nTime/Pixel (μs):")
    print(f"  Min: {min(time_per_pixels):.4f}, Max: {max(time_per_pixels):.4f}, Avg: {np.mean(time_per_pixels):.4f}")
    
    # Check for anomalies in data
    print(f"\n🔍 Anomaly Detection:")
    
    # Check time progression
    for i in range(1, len(successful)):
        curr = successful[i]
        prev = successful[i-1]
        
        pixel_ratio = curr['pixels'] / prev['pixels']
        time_ratio = curr['total_time_ms'] / prev['total_time_ms']
        
        if abs(time_ratio / pixel_ratio - 1.0) > 0.5:  # >50% deviation
            print(f"  ⚠️  Anomaly at size {curr['size']}:")
            print(f"     Pixels: {pixel_ratio:.2f}×, but Time: {time_ratio:.2f}×")
            print(f"     Deviation: {abs(time_ratio/pixel_ratio - 1.0)*100:.1f}%")

print("\n" + "="*80)
print("✅ Debug benchmark complete!")
print("="*80)
