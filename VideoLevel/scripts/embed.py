#!/usr/bin/env python3
"""
ZK-SNARK Video Steganography - Main Embedding Script
Embed secret message into H.264 video using motion vectors + ZK proofs
"""

import sys
import argparse
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from zk_mv_stego import VideoProver


def main():
    parser = argparse.ArgumentParser(
        description="Embed secret message into H.264 video with ZK-SNARK proof",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic embedding
  python embed.py -i input.mp4 -o stego.mp4 -m "Secret message" -k mykey123
  
  # With custom quality
  python embed.py -i input.mp4 -o stego.mp4 -m "Secret" -k key --crf 18
  
  # Skip ZK proof (faster, for testing)
  python embed.py -i input.mp4 -o stego.mp4 -m "Test" -k key --no-proof
"""
    )
    
    # Required arguments
    parser.add_argument(
        "-i", "--input",
        required=True,
        help="Input H.264 video file"
    )
    parser.add_argument(
        "-o", "--output",
        required=True,
        help="Output stego video file"
    )
    parser.add_argument(
        "-m", "--message",
        required=True,
        help="Secret message to embed"
    )
    parser.add_argument(
        "-k", "--key",
        required=True,
        help="Secret chaos key (SAVE THIS for extraction!)"
    )
    
    # Optional arguments
    parser.add_argument(
        "--no-proof",
        action="store_true",
        help="Skip ZK proof generation (faster, for testing)"
    )
    parser.add_argument(
        "--crf",
        type=int,
        default=23,
        help="Video quality (0-51, lower=better, default: 23)"
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        help="Maximum frames to process (for testing)"
    )
    parser.add_argument(
        "--output-dir",
        default="results",
        help="Output directory for metadata and logs"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )
    
    args = parser.parse_args()
    
    # Validate input
    if not Path(args.input).exists():
        print(f"❌ Error: Input video not found: {args.input}")
        sys.exit(1)
    
    print("=" * 70)
    print("🔐 ZK-SNARK Video Steganography - Embedding")
    print("=" * 70)
    print(f"Input:    {args.input}")
    print(f"Output:   {args.output}")
    print(f"Message:  {len(args.message)} characters")
    print(f"ZK Proof: {'No (testing mode)' if args.no_proof else 'Yes'}")
    print("=" * 70)
    
    try:
        # Create prover
        prover = VideoProver(output_dir=args.output_dir)
        
        # Embed message
        result = prover.embed_and_prove(
            video_path=args.input,
            output_path=args.output,
            message=args.message,
            chaos_key=args.key,
            generate_zk_proof=not args.no_proof,
            crf=args.crf,
            max_frames=args.max_frames,
            verbose=args.verbose
        )
        
        if result["success"]:
            print("\n✅ Embedding successful!")
            print(f"   Stego video: {result['stego_video']}")
            print(f"   Metadata:    {result.get('metadata_file', 'N/A')}")
            print(f"   MVs used:    {result.get('mvs_used', 'N/A')}")
            print(f"\n⚠️  IMPORTANT: Save your chaos key!")
            print(f"   Chaos Key: {args.key}")
            print("\n" + "=" * 70)
            sys.exit(0)
        else:
            print(f"\n❌ Embedding failed: {result.get('error', 'Unknown error')}")
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
