"""
Verify ZK-SNARK Proof from Video DCT Steganography
===================================================

Usage:
    python scripts/verify.py --video data/output/stego.mp4 --metadata data/output/stego.json
"""

import argparse
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.zk_mv_stego.verifier.video_verifier import VideoVerifier


def main():
    parser = argparse.ArgumentParser(
        description="Verify ZK-SNARK proof from video DCT steganography"
    )
    
    parser.add_argument(
        '--video', '-v',
        required=True,
        help='Stego video file path'
    )
    
    parser.add_argument(
        '--metadata', '-m',
        required=True,
        help='Metadata JSON file path'
    )
    
    parser.add_argument(
        '--expected-message',
        help='Expected message (optional validation)'
    )
    
    parser.add_argument(
        '--circuit-dir',
        help='Path to ZK circuit directory'
    )
    
    args = parser.parse_args()
    
    # Create verifier
    verifier = VideoVerifier(circuit_dir=args.circuit_dir)
    
    # Run verification
    valid, details = verifier.extract_and_verify(
        stego_video=args.video,
        metadata_path=args.metadata,
        expected_message=args.expected_message
    )
    
    if valid:
        print(f"\n✓ VERIFICATION SUCCESS")
        print(f"Message: '{details['message']}'")
        return 0
    else:
        print(f"\n✗ VERIFICATION FAILED")
        if 'error' in details:
            print(f"Error: {details['error']}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
