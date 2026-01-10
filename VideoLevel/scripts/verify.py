#!/usr/bin/env python3
"""
ZK-SNARK Video Steganography - Verification Script
Extract and verify secret message from stego video
"""

import sys
import argparse
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from zk_mv_stego import VideoVerifier


def main():
    parser = argparse.ArgumentParser(
        description="Extract and verify secret message from stego video",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full verification with ZK proof
  python verify.py -i stego.mp4 -k mykey123 -p metadata/proof.json
  
  # Extract only (no proof verification)
  python verify.py -i stego.mp4 -k mykey123 --no-verify
  
  # Compare with original message
  python verify.py -i stego.mp4 -k key -p proof.json --expected "Secret message"
"""
    )
    
    # Required arguments
    parser.add_argument(
        "-i", "--input",
        required=True,
        help="Input stego video file"
    )
    parser.add_argument(
        "-k", "--key",
        required=True,
        help="Chaos key used during embedding"
    )
    
    # Optional arguments
    parser.add_argument(
        "-p", "--proof",
        help="ZK proof JSON file (from embedding)"
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip ZK proof verification (extract only)"
    )
    parser.add_argument(
        "--expected",
        help="Expected message for validation"
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        help="Maximum frames to process"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )
    
    args = parser.parse_args()
    
    # Validate input
    if not Path(args.input).exists():
        print(f"❌ Error: Stego video not found: {args.input}")
        sys.exit(1)
    
    if args.proof and not Path(args.proof).exists():
        print(f"❌ Error: Proof file not found: {args.proof}")
        sys.exit(1)
    
    print("=" * 70)
    print("🔍 ZK-SNARK Video Steganography - Verification")
    print("=" * 70)
    print(f"Stego Video: {args.input}")
    print(f"Proof File:  {args.proof or 'None (extract only)'}")
    print(f"Verify ZK:   {'No' if args.no_verify else 'Yes'}")
    print("=" * 70)
    
    try:
        # Create verifier
        verifier = VideoVerifier()
        
        # Extract and verify
        result = verifier.extract_and_verify(
            stego_video_path=args.input,
            chaos_key=args.key,
            proof_path=args.proof,
            verify_zk_proof=not args.no_verify,
            max_frames=args.max_frames,
            verbose=args.verbose
        )
        
        if result["success"]:
            print("\n✅ Verification successful!")
            print(f"   Extracted message: {result['message']}")
            print(f"   Message length:    {len(result['message'])} characters")
            print(f"   ZK proof valid:    {result.get('zk_proof_valid', 'N/A')}")
            
            # Compare with expected
            if args.expected:
                if result["message"] == args.expected:
                    print(f"   ✅ Message matches expected value")
                else:
                    print(f"   ❌ Message mismatch!")
                    print(f"      Expected: {args.expected}")
                    print(f"      Got:      {result['message']}")
                    sys.exit(1)
            
            print("\n" + "=" * 70)
            sys.exit(0)
        else:
            print(f"\n❌ Verification failed: {result.get('error', 'Unknown error')}")
            sys.exit(1)
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
