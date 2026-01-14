"""
Embed ZK-SNARK Proof into Video using DCT Steganography
========================================================

Usage:
    python scripts/embed.py --input data/raw/foreman_cif.y4m --output data/output/stego.mp4 --message "Secret message"
"""

import argparse
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.zk_mv_stego.prover.video_prover import VideoProver


def main():
    parser = argparse.ArgumentParser(
        description="Embed ZK-SNARK proof into video using DCT steganography"
    )
    
    parser.add_argument(
        '--input', '-i',
        required=True,
        help='Input video file path'
    )
    
    parser.add_argument(
        '--output', '-o',
        required=True,
        help='Output stego video file path'
    )
    
    parser.add_argument(
        '--metadata', '-m',
        help='Output metadata JSON file (default: <output>.json)'
    )
    
    parser.add_argument(
        '--message', '-msg',
        required=True,
        help='Message to embed'
    )
    
    parser.add_argument(
        '--crf',
        type=int,
        default=18,
        help='Video encoding quality (18 = visually lossless, lower = better quality)'
    )
    
    parser.add_argument(
        '--max-frames',
        type=int,
        help='Maximum frames to process (for testing)'
    )
    
    parser.add_argument(
        '--circuit-dir',
        help='Path to ZK circuit directory'
    )
    
    args = parser.parse_args()
    
    # Set default metadata path
    if args.metadata is None:
        args.metadata = str(Path(args.output).with_suffix('.json'))
    
    # Create prover
    prover = VideoProver(circuit_dir=args.circuit_dir, crf=args.crf)
    
    # Run embedding
    success = prover.prove_and_embed(
        input_video=args.input,
        output_video=args.output,
        output_metadata=args.metadata,
        message=args.message,
        max_frames=args.max_frames
    )
    
    if success:
        print(f"\n✓ SUCCESS")
        print(f"Stego video: {args.output}")
        print(f"Metadata: {args.metadata}")
        return 0
    else:
        print(f"\n✗ FAILED")
        return 1


if __name__ == '__main__':
    sys.exit(main())
