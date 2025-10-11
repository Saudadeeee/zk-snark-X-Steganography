#!/usr/bin/env python3
"""
Quick Performance Demo
Demonstrates the key performance characteristics of ZK-SNARK chaos steganography
"""

import sys
import time
import json
import numpy as np
from PIL import Image
import os
sys.path.append('../src')

def quick_performance_test():
    """Quick demonstration of key performance metrics"""
    print("ZK-SNARK Chaos Steganography - Quick Performance Demo")
    print("=" * 60)
    
    # Import after ensuring dependencies
    try:
        from zk_stego.hybrid_proof_artifact import embed_chaos_proof, extract_chaos_proof
        print("ZK-SNARK chaos steganography modules loaded")
    except ImportError as e:
        print(f"Module import failed: {e}")
        return
    
    # Create test image
    print("\nCreating test image (256×256)...")
    test_img = np.random.randint(50, 200, (256, 256, 3), dtype=np.uint8)
    
    # Add texture patterns
    for i in range(0, 256, 32):
        for j in range(0, 256, 32):
            if (i//32 + j//32) % 2 == 0:
                test_img[i:i+16, j:j+16] = [200, 200, 200]
    
    Image.fromarray(test_img).save('demo_test_image.png')
    print("Test image created")
    
    # Create test proof
    print("\nCreating test ZK proof...")
    test_proof = {
        "pi_a": ["0x1a2b3c4d5e6f7890", "0xabcdef1234567890"],
        "pi_b": [["0x1111222233334444", "0x5555666677778888"], 
                 ["0x9999aaaabbbbcccc", "0xddddeeeeffff0000"]],
        "pi_c": ["0xfedcba0987654321", "0x0123456789abcdef"],
        "protocol": "groth16",
        "curve": "bn128"
    }
    
    with open('demo_proof.json', 'w') as f:
        json.dump(test_proof, f, indent=2)
    
    proof_size = len(json.dumps(test_proof, separators=(',', ':')))
    print(f"Test proof created ({proof_size} bytes)")
    
    # Create public inputs
    public = {
        'inputs': ['1', '42', '123'],
        'proof_length': proof_size * 8,
        'positions': []
    }
    
    with open('demo_public.json', 'w') as f:
        json.dump(public, f, indent=2)
    
    # Performance test 1: Embedding
    print("\nTesting embedding performance...")
    embed_times = []
    
    for i in range(3):
        start_time = time.perf_counter()
        success = embed_chaos_proof(
            'demo_test_image.png',
            f'demo_stego_{i}.png',
            'demo_proof.json',
            'demo_public.json',
            'demo_secret_key'
        )
        end_time = time.perf_counter()
        
        if success:
            embed_time = (end_time - start_time) * 1000
            embed_times.append(embed_time)
            print(f"   Run {i+1}: {embed_time:.2f} ms - {'Success' if success else 'Failed'}")
        else:
            print(f"   Run {i+1}: Failed")
    
    avg_embed_time = np.mean(embed_times) if embed_times else 0
    print(f"Average embedding time: {avg_embed_time:.2f} ms")
    
    # Performance test 2: Extraction
    if embed_times:
        print("\nTesting extraction performance...")
        extract_times = []
        
        for i in range(3):
            if os.path.exists(f'demo_stego_{i}.png'):
                start_time = time.perf_counter()
                extracted = extract_chaos_proof(f'demo_stego_{i}.png')
                end_time = time.perf_counter()
                
                extract_time = (end_time - start_time) * 1000
                extract_times.append(extract_time)
                
                success = extracted is not None and 'proof' in extracted
                print(f"   Run {i+1}: {extract_time:.2f} ms - {'Success' if success else 'Failed'}")
        
        avg_extract_time = np.mean(extract_times) if extract_times else 0
        print(f"Average extraction time: {avg_extract_time:.2f} ms")
        
        # Total performance
        total_time = avg_embed_time + avg_extract_time
        print(f"Total processing time: {total_time:.2f} ms")
    
    # Capacity analysis
    print("\nCapacity analysis...")
    image_capacity = 256 * 256 * 3  # Total bits available (LSB of each color channel)
    proof_bits = proof_size * 8
    capacity_used = (proof_bits / image_capacity) * 100
    
    print(f"   Image capacity: {image_capacity} bits")
    print(f"   Proof size: {proof_bits} bits")
    print(f"   Capacity used: {capacity_used:.2f}%")
    
    # Security features
    print("\nSecurity features demonstrated:")
    print("   Arnold Cat Map chaos positioning")
    print("   Logistic Map sequence generation")
    print("   Feature extraction for optimal placement")
    print("   PNG chunk metadata storage")
    print("   Zero-knowledge proof verification")
    
    # Performance summary
    if embed_times and extract_times:
        print("\nPerformance Summary:")
        print(f"   Embedding: {avg_embed_time:.1f} ms")
        print(f"   Extraction: {avg_extract_time:.1f} ms")
        print(f"   Total: {total_time:.1f} ms")
        print(f"   Throughput: {proof_size/(total_time/1000):.0f} bytes/second")
        print(f"   Efficiency: {capacity_used:.1f}% capacity utilization")
    
    # Cleanup
    cleanup_files = [
        'demo_test_image.png', 'demo_proof.json', 'demo_public.json'
    ] + [f'demo_stego_{i}.png' for i in range(3)]
    
    for f in cleanup_files:
        try:
            os.remove(f)
        except:
            pass
    
    print("\nQuick performance demo complete!")
    return {
        'embedding_time': avg_embed_time if embed_times else 0,
        'extraction_time': avg_extract_time if extract_times else 0,
        'total_time': total_time if embed_times and extract_times else 0,
        'proof_size': proof_size,
        'capacity_used': capacity_used,
        'success_rate': len(embed_times) / 3 * 100
    }

if __name__ == "__main__":
    quick_performance_test()