"""
Extract Payload from Stego Video
=================================

Extracts embedded payload (message + ZK-SNARK proof) from H.264 stego video.

Process:
1. Parse H.264 bitstream and extract DCT coefficients from I-frames
2. Filter usable coefficients (non-DC, non-zero, not ±1)
3. Extract LSB bits from coefficients to reconstruct payload
4. Parse payload structure: [4-byte header] [message] [proof]
5. Save extracted message and proof to JSON

Usage:
    python scripts/extract.py <stego_video.h264> [output.json]

Example:
    python scripts/extract.py data/output/foreman_stego_groth16.h264 data/output/extracted_payload.json

Author: ZK Video Stego Team
Date: January 2026
"""

import sys
import json
import struct
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.zk_mv_stego.decoder.cavlc_extractor_simple import SimpleCAVLCExtractor


def extract_payload(stego_video: Path, max_frames: int = 100, 
                   allow_small_values: bool = False,
                   use_sign_bit: bool = False) -> dict:  # Changed default to LSB
    """
    Extract embedded payload from stego video
    
    Args:
        stego_video: Path to stego H.264 video
        max_frames: Maximum number of I-frames to process
        allow_small_values: Extract from |coeff|==1 (must match embedding setting)
        use_sign_bit: Use SIGN BIT extraction (True) or LSB extraction (False - default)
    
    Returns:
        Dictionary with extracted message and proof
    """
    print(f"\n[*] Extracting from: {stego_video}")
    print(f"    Max frames: {max_frames}, allow_small_values: {allow_small_values}")
    print(f"    Extraction method: {'SIGN BIT' if use_sign_bit else 'LSB'}")
    
    print("\n[1/3] Extracting DCT coefficients from I-frames...")
    extractor = SimpleCAVLCExtractor()
    frames = extractor.extract_from_video(str(stego_video), max_frames=max_frames)
    
    if not frames:
        raise ValueError("No I-frames found in video")
    
    print(f"  [OK] Extracted {len(frames)} I-frames")
    
    print("\n[2/3] Collecting usable coefficients...")
    coefficients = []
    
    for frame in frames:
        if 'macroblocks' in frame:
            for mb_data in frame['macroblocks']:
                coeffs_flat = mb_data['coefficients']
                
                for block_idx in range(24):  # 16 Y + 4 Cb + 4 Cr
                    start = block_idx * 16
                    end = start + 16
                    block_coeffs = coeffs_flat[start:end]
                    
                    for coeff_idx, coeff in enumerate(block_coeffs):
                        # AC-INDEX-1 MODE: ONLY extract from index 1 (first AC after DC)
                        if coeff_idx != 1:
                            continue
                        if coeff == 0:  # Skip zeros
                            continue
                        # Magnitude threshold: only use coefficients >= 3
                        if abs(coeff) < 3:
                            continue
                        # MUST match embedding: allow_small_values controls ±1 usage
                        if not allow_small_values and abs(coeff) == 1:
                            continue
                        coefficients.append(coeff)
    
    print(f"  [OK] Found {len(coefficients)} usable coefficients")
    print(f"       Capacity: {len(coefficients) // 8} bytes")
    
    print(f"\n[3/3] Extracting bits using {'SIGN BIT' if use_sign_bit else 'LSB'} method...")
    bits = []
    
    if use_sign_bit:
        # Bit 0 = Positive, Bit 1 = Negative (matches DirectBitstreamPatcher)
        for coeff in coefficients:
            bit = 1 if coeff < 0 else 0
            bits.append(bit)
    else:
        for coeff in coefficients:
            lsb = abs(coeff) & 1  # Extract LSB from absolute value
            bits.append(lsb)
    
    payload_bytes = bytearray()
    for i in range(0, len(bits), 8):
        if i + 8 <= len(bits):
            byte_bits = bits[i:i+8]
            byte_val = sum(bit << (7-idx) for idx, bit in enumerate(byte_bits))
            payload_bytes.append(byte_val)
    
    print(f"  [OK] Extracted {len(payload_bytes)} bytes ({len(bits)} bits)")
    
    if len(payload_bytes) < 8:
        raise ValueError(f"Payload too small: {len(payload_bytes)} bytes (need at least 8 for header)")
    
    magic = payload_bytes[0:4]  # 4 bytes magic + 4 bytes message length (BIG-ENDIAN)
    if magic != b'ZKST':
        raise ValueError(f"Invalid magic header: {magic} (expected b'ZKST')")
    
    message_length = struct.unpack('>I', payload_bytes[4:8])[0]
    
    print(f"\n[*] Payload structure:")
    print(f"    Magic: {magic.decode('ascii')}")
    print(f"    Message length: {message_length} bytes")
    
    if len(payload_bytes) < 8 + message_length:
        raise ValueError(f"Payload too small for message: {len(payload_bytes)} bytes (need {8 + message_length})")
    
    message_bytes = payload_bytes[8:8+message_length]
    message = message_bytes.decode('utf-8', errors='replace')
    
    proof_bytes = payload_bytes[8+message_length:]
    
    print(f"    Message: {len(message_bytes)} bytes = '{message}'")
    print(f"    Proof: {len(proof_bytes)} bytes")
    
    # Calculate hash of message (for verification)
    import hashlib
    message_hash = hashlib.sha256(message.encode('utf-8')).hexdigest()
    
    return {
        'message': message,
        'message_length': message_length,
        'message_hash': message_hash,
        'proof_bytes': len(proof_bytes),
        'proof_hex': proof_bytes.hex(),
        'total_bytes': len(payload_bytes),
        'extraction_info': {
            'video': str(stego_video),
            'frames_processed': len(frames),
            'usable_coefficients': len(coefficients),
            'capacity_bytes': len(coefficients) // 8,
            'bits_extracted': len(bits)
        }
    }


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    # Parse arguments
    stego_video = Path(sys.argv[1])
    output_json = Path(sys.argv[2]) if len(sys.argv) >= 3 and not sys.argv[2].startswith('--') else Path("data/output/extracted_payload.json")
    
    # Parse flags
    allow_small_values = '--allow-small-values' in sys.argv
    use_sign_bit = '--sign-bit' in sys.argv or '--use-sign-bit' in sys.argv
    
    # Default to SIGN BIT if not explicitly set to LSB
    if '--lsb' not in sys.argv:
        use_sign_bit = True
    
    if not stego_video.exists():
        print(f"[ERROR] Video not found: {stego_video}")
        sys.exit(1)
    
    try:
        # Extract payload (with matching embedding settings)
        result = extract_payload(stego_video, max_frames=100, 
                                allow_small_values=allow_small_values,
                                use_sign_bit=use_sign_bit)
        
        # Save to JSON
        output_json.parent.mkdir(parents=True, exist_ok=True)
        with open(output_json, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        
        print(f"\n[SUCCESS] Extraction complete!")
        print(f"[*] Output saved to: {output_json}")
        print(f"\n{'='*80}")
        print("EXTRACTION SUMMARY")
        print('='*80)
        print(f"Message: '{result['message']}'")
        print(f"Message hash: {result['message_hash']}")
        print(f"Proof bytes: {result['proof_bytes']}")
        print(f"Total payload: {result['total_bytes']} bytes")
        print(f"Capacity used: {result['total_bytes']}/{result['extraction_info']['capacity_bytes']} bytes")
        print('='*80)
        
    except Exception as e:
        print(f"\n[ERROR] Extraction failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
