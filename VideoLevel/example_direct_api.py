#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Simple Example - Direct API Usage
==================================

Ví dụ nhúng ZK-SNARK proof trực tiếp qua API (không qua CLI)
"""

import warnings
warnings.filterwarnings('ignore')

import sys
from pathlib import Path

# Add to path
sys.path.insert(0, str(Path(__file__).parent))

def main():
    print("="*70)
    print("SIMPLE EXAMPLE - Direct API Usage")
    print("="*70)
    
    # Import modules
    print("\n[1] Importing modules...")
    try:
        from src.zk_mv_stego.prover.video_prover import VideoProver
        from src.zk_mv_stego.verifier.video_verifier import VideoVerifier
        print("    ✓ Modules imported")
    except Exception as e:
        print(f"    ✗ Import failed: {e}")
        return 1
    
    # Configuration
    print("\n[2] Configuration...")
    input_video = "data/raw/foreman_cif.y4m"
    output_video = "data/output/example_stego.mp4"
    metadata_file = "data/output/example_stego.json"
    message = "Hello from ZK-SNARK DCT Steganography!"
    max_frames = 50  # Test với 50 frames
    
    if not Path(input_video).exists():
        print(f"    ✗ Input video not found: {input_video}")
        return 1
    
    print(f"    Input:  {input_video}")
    print(f"    Output: {output_video}")
    print(f"    Message: '{message}'")
    print(f"    Frames: {max_frames}")
    
    # Create prover
    print("\n[3] Creating prover...")
    try:
        prover = VideoProver(crf=18)
        print("    ✓ Prover created")
    except Exception as e:
        print(f"    ✗ Prover creation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Embed proof
    print("\n[4] Embedding proof...")
    try:
        success = prover.prove_and_embed(
            input_video=input_video,
            output_video=output_video,
            output_metadata=metadata_file,
            message=message,
            max_frames=max_frames
        )
        
        if success:
            print("    ✓ Embedding successful!")
        else:
            print("    ✗ Embedding failed")
            return 1
            
    except Exception as e:
        print(f"    ✗ Error during embedding: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Verify proof
    print("\n[5] Verifying proof...")
    try:
        verifier = VideoVerifier()
        
        valid, details = verifier.extract_and_verify(
            stego_video=output_video,
            metadata_path=metadata_file,
            expected_message=message
        )
        
        if valid:
            print("    ✓ Verification successful!")
            print(f"    ✓ ZK proof: {'VALID' if details['zk_proof_valid'] else 'INVALID'}")
            print(f"    ✓ Extraction: {'VALID' if details['extraction_valid'] else 'INVALID'}")
            print(f"    ✓ Message: {'MATCH' if details['message_valid'] else 'MISMATCH'}")
        else:
            print("    ✗ Verification failed")
            if 'error' in details:
                print(f"    Error: {details['error']}")
            return 1
            
    except Exception as e:
        print(f"    ✗ Error during verification: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Summary
    print("\n" + "="*70)
    print("SUCCESS!")
    print("="*70)
    print(f"\nOutput files:")
    print(f"  - Video: {output_video}")
    print(f"  - Metadata: {metadata_file}")
    print(f"\nMessage embedded: '{message}'")
    print(f"Verification: PASSED ✓")
    print("="*70)
    
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
