#!/usr/bin/env python3
"""
Quick test: embed 274 bytes,  measure decode without full batch validation.
"""
import sys, json, os, glob
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.embedder import embed
import subprocess

def quick_embed_test(h264_path: str, output_h264: str):
    """Quick embed test: 274 bytes (ZK blob), simple quality check."""
    
    message = b'X' * 100  # Simple test message
    secret_key = os.urandom(32)
    circuits_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'circuits')
    
    print(f"[test] embedding {len(message)} bytes into {os.path.basename(h264_path)}")
    
    try:
        result = embed(
            video_path=h264_path,
            message=message,
            output_path=output_h264,
            circuits_dir=circuits_dir,
            secret_key=secret_key,
            max_modifications_per_block=2,
            ffmpeg_validate=False
        )
        print(f"[test] embedded {result.bits_embedded} bits")
        print(f"[test] capacity: {result.capacity_bits} bits")
        
        # Simple decode check
        try:
            subprocess.run(f'ffprobe -v error -select_streams v:0 "{output_h264}"', 
                          shell=True, capture_output=True, check=True, timeout=5)
            status = "OK"
        except:
            status = "DECODE_ERROR"
        
        print(f"[test] decode status: {status}")
        return {
            'bits_embedded': result.bits_embedded,
            'capacity_bits': result.capacity_bits,
            'payload_bytes': len(message),
            'decode_status': status
        }
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    bdir = os.path.dirname(__file__)
    ddir = os.path.join(os.path.dirname(bdir), 'data')
    
    test_videos = [
        os.path.join(ddir, 'encoded', 'foreman_cif_g8.h264'),
        os.path.join(ddir, 'encoded', 'coastguard_cif_g8.h264'),
    ]
    
    results = {}
    for h264 in test_videos:
        if not os.path.exists(h264):
            print(f"[skip] {h264} not found")
            continue
        
        name = os.path.basename(h264).replace('.h264', '')
        output = os.path.join(ddir, 'output', f'_quick_test_{name}.h264')
        
        print(f"\n=== {name} ===")
        result = quick_embed_test(h264, output)
        if result:
            results[name] = result
    
    print(f"\n=== Summary ===")
    print(json.dumps(results, indent=2))

if __name__ == '__main__':
    main()
