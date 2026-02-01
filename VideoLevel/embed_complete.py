"""
Complete End-to-End Embedding Workflow
=======================================

Embed message + ZK-SNARK proof into H.264 video with full reconstruction

Workflow:
1. Extract DCT coefficients from input video
2. Generate ZK-SNARK proof for message (optional)
3. Prepare payload: [header][message][proof]
4. Embed payload using LSB steganography
5. Reconstruct video with modified coefficients
6. Save stego video and metadata

Author: ZK Video Stego Team
Date: February 2, 2026
"""

import sys
import json
import struct
import hashlib
from pathlib import Path
from typing import Tuple, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from zk_mv_stego.decoder.cavlc_extractor_simple import SimpleCAVLCExtractor
from zk_mv_stego.embedder.payload_embedder import PayloadEmbedder
from zk_mv_stego.bitstream.bitstream_reconstructor import BitstreamReconstructor


def prepare_payload(message: str, include_proof: bool = False, 
                   proof_data: Optional[bytes] = None) -> bytes:
    """
    Prepare payload with header, message, and optional proof
    
    Payload structure:
    - Header (8 bytes):
      - Magic: "ZKST" (4 bytes)
      - Message length (4 bytes, big-endian)
    - Message (variable length)
    - Proof (variable length, optional)
    
    Args:
        message: Message to embed
        include_proof: Include ZK-SNARK proof
        proof_data: Proof bytes (if include_proof=True)
    
    Returns:
        Complete payload bytes
    """
    # Encode message
    message_bytes = message.encode('utf-8')
    message_length = len(message_bytes)
    
    # Build header
    magic = b'ZKST'
    header = magic + struct.pack('>I', message_length)
    
    # Combine
    payload = header + message_bytes
    
    if include_proof and proof_data:
        payload += proof_data
    
    return payload


def embed_into_video(input_video: Path, message: str, output_video: Path,
                     max_frames: int = 100, 
                     allow_small_values: bool = False,
                     include_proof: bool = False) -> dict:
    """
    Complete embedding workflow
    
    Args:
        input_video: Input H.264 video
        message: Message to embed
        output_video: Output stego video
        max_frames: Maximum frames to use
        allow_small_values: Use |coeff|=1 for higher capacity (less stable)
        include_proof: Generate and include ZK-SNARK proof
    
    Returns:
        Statistics dictionary
    """
    print("="*80)
    print("END-TO-END EMBEDDING WORKFLOW")
    print("="*80)
    
    # Step 1: Extract DCT coefficients
    print(f"\n[1/6] Extracting DCT coefficients from video...")
    print(f"      Input: {input_video}")
    print(f"      Max frames: {max_frames}")
    
    extractor = SimpleCAVLCExtractor()
    frames = extractor.extract_from_video(str(input_video), max_frames=max_frames)
    
    if not frames:
        raise ValueError("No frames extracted from video")
    
    print(f"      Extracted {len(frames)} frames")
    
    # Step 2: Collect usable coefficients
    print(f"\n[2/6] Collecting usable coefficients...")
    print(f"      Filter: skip_dc=True, skip_zeros=True, allow_small_values={allow_small_values}")
    
    coefficients = []
    
    for frame in frames:
        for mb_data in frame.get('macroblocks', []):
            mb_idx = mb_data['mb_idx']
            coeffs_flat = mb_data['coefficients']
            
            # Split into 24 blocks (16 Y + 4 Cb + 4 Cr)
            for block_idx in range(24):
                start = block_idx * 16
                end = start + 16
                block_coeffs = coeffs_flat[start:end]
                
                coefficients.append((mb_idx, block_idx, list(block_coeffs)))
    
    print(f"      Total blocks: {len(coefficients)}")
    
    # Calculate capacity
    embedder = PayloadEmbedder(
        skip_dc=True, 
        skip_zeros=True,
        allow_small_values=allow_small_values
    )
    capacity_bits = embedder.calculate_capacity(coefficients)
    capacity_bytes = capacity_bits // 8
    
    print(f"      Capacity: {capacity_bits} bits ({capacity_bytes} bytes)")
    print(f"      Capacity per frame: {capacity_bits // len(frames)} bits/frame")
    
    # Step 3: Generate/prepare proof (optional)
    proof_data = None
    if include_proof:
        print(f"\n[3/6] Generating ZK-SNARK proof...")
        try:
            from zk_mv_stego.crypto.proof_generator import GrothProofGenerator
            
            generator = GrothProofGenerator()
            if not generator.setup_complete:
                print("      [WARN] Circuit not set up, skipping proof generation")
                include_proof = False
            else:
                secret = hashlib.sha256(message.encode()).hexdigest()[:32]
                proof_obj = generator.generate_proof(
                    payload=message.encode('utf-8'),
                    secret=secret,
                    use_binary=True
                )
                
                if 'proof_data' in proof_obj:
                    proof_data = proof_obj['proof_data']
                    print(f"      Proof generated: {len(proof_data)} bytes")
                else:
                    print("      [WARN] Proof generation failed, continuing without proof")
                    include_proof = False
        except Exception as e:
            print(f"      [WARN] Proof generation error: {e}")
            print("      Continuing without proof...")
            include_proof = False
    else:
        print(f"\n[3/6] Skipping proof generation (include_proof=False)")
    
    # Step 4: Prepare payload
    print(f"\n[4/6] Preparing payload...")
    payload = prepare_payload(message, include_proof, proof_data)
    
    print(f"      Message: '{message}' ({len(message)} chars)")
    print(f"      Payload size: {len(payload)} bytes")
    print(f"      Capacity: {capacity_bytes} bytes")
    
    if len(payload) > capacity_bytes:
        raise ValueError(
            f"Payload too large: {len(payload)} bytes > {capacity_bytes} bytes capacity. "
            f"Try: 1) Shorter message, 2) More frames (--max-frames), "
            f"3) Higher capacity mode (--allow-small-values)"
        )
    
    # Step 5: Embed payload
    print(f"\n[5/6] Embedding payload using LSB steganography...")
    modified_coefficients, bits_embedded = embedder.embed_payload(
        coefficients,
        payload
    )
    
    print(f"      Bits embedded: {bits_embedded}/{len(payload)*8}")
    print(f"      Blocks modified: {len(modified_coefficients)}")
    print(f"      Embedding rate: {bits_embedded/(len(coefficients)*16)*100:.2f}%")
    
    # Step 6: Reconstruct video
    print(f"\n[6/6] Reconstructing video with embedded payload...")
    print(f"      Output: {output_video}")
    
    reconstructor = BitstreamReconstructor()
    result = reconstructor.reconstruct_video(
        original_file=str(input_video),
        modified_coefficients=modified_coefficients,
        output_file=str(output_video),
        max_slices=max_frames
    )
    
    if not result['success']:
        raise RuntimeError("Video reconstruction failed!")
    
    print(f"\n      Slices reconstructed: {result['slices_reconstructed']}")
    print(f"      Slices modified: {result['slices_modified']}")
    print(f"      Output size: {output_video.stat().st_size:,} bytes")
    
    # Compute statistics
    stats = {
        'success': True,
        'input_video': str(input_video),
        'output_video': str(output_video),
        'message': message,
        'message_length': len(message),
        'payload_bytes': len(payload),
        'proof_included': include_proof,
        'proof_bytes': len(proof_data) if proof_data else 0,
        'frames_used': len(frames),
        'capacity_bytes': capacity_bytes,
        'capacity_bits': capacity_bits,
        'bits_embedded': bits_embedded,
        'blocks_modified': len(modified_coefficients),
        'total_blocks': len(coefficients),
        'embedding_rate': bits_embedded / (len(coefficients) * 16) * 100,
        'reconstruction': result
    }
    
    return stats


def main():
    """CLI interface"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Embed message + ZK-SNARK proof into H.264 video',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic embedding (message only)
  python embed_complete.py -i data/output/foreman_baseline.h264 -m "Secret message"
  
  # With ZK-SNARK proof
  python embed_complete.py -i input.h264 -m "Message" --proof
  
  # High capacity mode (less stable)
  python embed_complete.py -i input.h264 -m "Long message..." --allow-small-values
  
  # More frames for larger payload
  python embed_complete.py -i input.h264 -m "Large payload" --max-frames 200
        """
    )
    
    parser.add_argument('-i', '--input', required=True, 
                       help='Input H.264 video file')
    parser.add_argument('-o', '--output',
                       help='Output stego video (default: input_stego.h264)')
    parser.add_argument('-m', '--message', required=True,
                       help='Message to embed')
    parser.add_argument('--proof', action='store_true',
                       help='Generate and include ZK-SNARK proof')
    parser.add_argument('--max-frames', type=int, default=100,
                       help='Maximum frames to use (default: 100)')
    parser.add_argument('--allow-small-values', action='store_true',
                       help='Use |coeff|=1 for higher capacity (less stable)')
    parser.add_argument('--stats', 
                       help='Save statistics to JSON file')
    
    args = parser.parse_args()
    
    # Setup paths
    input_video = Path(args.input)
    if not input_video.exists():
        print(f"[ERROR] Input video not found: {input_video}")
        sys.exit(1)
    
    if args.output:
        output_video = Path(args.output)
    else:
        output_video = input_video.parent / f"{input_video.stem}_stego{input_video.suffix}"
    
    output_video.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        # Run embedding
        stats = embed_into_video(
            input_video=input_video,
            message=args.message,
            output_video=output_video,
            max_frames=args.max_frames,
            allow_small_values=args.allow_small_values,
            include_proof=args.proof
        )
        
        # Save statistics
        if args.stats:
            stats_file = Path(args.stats)
            with open(stats_file, 'w') as f:
                json.dump(stats, f, indent=2)
            print(f"\n[INFO] Statistics saved to: {stats_file}")
        
        # Print summary
        print(f"\n{'='*80}")
        print("EMBEDDING COMPLETE!")
        print(f"{'='*80}")
        print(f"Output: {output_video}")
        print(f"Message: '{args.message}'")
        print(f"Payload: {stats['payload_bytes']} bytes")
        print(f"Proof: {'Included' if stats['proof_included'] else 'Not included'}")
        print(f"Capacity used: {stats['bits_embedded']}/{stats['capacity_bits']} bits "
              f"({stats['embedding_rate']:.1f}%)")
        print(f"{'='*80}")
        
        # Next steps
        print(f"\nNext steps:")
        print(f"  1. Extract: python scripts/extract.py {output_video}")
        print(f"  2. Verify:  python scripts/verify.py <extracted_payload.json>")
        
    except Exception as e:
        print(f"\n[ERROR] Embedding failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
