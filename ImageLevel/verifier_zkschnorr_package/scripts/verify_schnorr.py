#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZK-Schnorr Steganography Verification Script
Single-command verification of chaos-based steganographic Schnorr proofs
"""

import argparse
import json
import sys
import os
import io
import hashlib
import time
from pathlib import Path

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

project_root = Path(__file__).parent.parent
sys.path.append(str(project_root / 'src'))

import numpy as np
from PIL import Image

from zk_stego.chaos_embedding import ChaosEmbedding, generate_chaos_key_from_secret
from zk_schnorr.schnorr_proof import SchnorrProof, SchnorrProofSystem
from zk_schnorr.chaos_schnorr_pipeline import SchnorrChaosPipeline


def extract_schnorr_proof(image_path: str) -> dict:
    """
    Extract Schnorr proof metadata từ ảnh steganography
    
    Args:
        image_path: Path to stego image
        
    Returns:
        dict: Proof metadata hoặc None nếu không tìm thấy
    """
    try:
        image = Image.open(image_path)
        image_array = np.array(image)
        
        # Try to extract metadata from LSB
        # Schnorr proof được embed ở cuối ảnh dưới dạng JSON với marker
        height, width = image_array.shape[:2]
        
        # Extract metadata from bottom-right corner
        bits = []
        for y in range(height-1, max(height-100, 0), -1):
            for x in range(width-1, max(width-100, 0), -1):
                if image_array.ndim == 3:
                    pixel = image_array[y, x, 0]
                else:
                    pixel = image_array[y, x]
                bits.append(pixel & 1)
                
                if len(bits) >= 10000:  # Max metadata size
                    break
            if len(bits) >= 10000:
                break
        
        # Convert bits to bytes
        bytes_data = []
        for i in range(0, len(bits), 8):
            if i + 8 <= len(bits):
                byte = 0
                for j in range(8):
                    byte = (byte << 1) | bits[i + j]
                bytes_data.append(byte)
        
        # Try to find JSON metadata with marker
        text = bytes(bytes_data).decode('utf-8', errors='ignore')
        
        # Look for SCHNORR_PROOF marker
        marker_start = "SCHNORR_PROOF:"
        marker_end = ":END_SCHNORR"
        
        if marker_start in text:
            start_idx = text.find(marker_start) + len(marker_start)
            end_idx = text.find(marker_end, start_idx)
            
            if end_idx > start_idx:
                json_str = text[start_idx:end_idx]
                metadata = json.loads(json_str)
                return metadata
        
        return None
        
    except Exception as e:
        return None


def verify_schnorr_stego(stego_image_path: str, chaos_secret: str = None, verbose: bool = False) -> dict:
    """
    Verify Schnorr steganography proof
    
    Args:
        stego_image_path: Path to stego image
        chaos_secret: Optional chaos key for message extraction
        verbose: Enable detailed output
        
    Returns:
        dict: Verification result
    """
    try:
        if verbose:
            print(f"Analyzing steganographic image: {stego_image_path}")
        
        # Extract proof metadata
        proof_data = extract_schnorr_proof(stego_image_path)
        
        if not proof_data:
            return {
                'success': False,
                'error': 'No valid Schnorr proof artifact found in image',
                'details': 'Image may not contain steganographic data'
            }
        
        if verbose:
            print("✓ Schnorr proof metadata extracted")
            print(f"  Feature point: ({proof_data['stego_metadata']['x0']}, {proof_data['stego_metadata']['y0']})")
            print(f"  Message bits: {proof_data['stego_metadata']['bit_length']}")
            print(f"  Timestamp: {proof_data['stego_metadata']['timestamp']}")
        
        # Verify proof
        pipeline = SchnorrChaosPipeline()
        is_valid = pipeline.verify_proof(proof_data)
        
        if verbose:
            print(f"✓ Proof verification: {'VALID' if is_valid else 'INVALID'}")
        
        result = {
            'success': True,
            'proof_valid': is_valid,
            'metadata': proof_data['stego_metadata'],
            'proof_size_bytes': len(json.dumps(proof_data['schnorr_proof'])),
            'timestamp': proof_data['stego_metadata']['timestamp']
        }
        
        # Optional: Extract message if chaos secret provided
        if chaos_secret and is_valid:
            try:
                image = Image.open(stego_image_path)
                image_array = np.array(image)
                
                x0 = proof_data['stego_metadata']['x0']
                y0 = proof_data['stego_metadata']['y0']
                bit_length = proof_data['stego_metadata']['bit_length']
                
                chaos_key = generate_chaos_key_from_secret(chaos_secret)
                chaos_embed = ChaosEmbedding(image_array)
                
                # Extract bits
                extracted_bits = chaos_embed.extract_bits(bit_length, x0, y0, chaos_key)
                
                # Convert to message
                message_bytes = []
                for i in range(0, len(extracted_bits), 8):
                    if i + 8 <= len(extracted_bits):
                        byte = 0
                        for j in range(8):
                            byte = (byte << 1) | extracted_bits[i + j]
                        message_bytes.append(byte)
                
                message = bytes(message_bytes).decode('utf-8', errors='replace')
                result['extracted_message'] = message
                
                if verbose:
                    print(f"✓ Message extracted: {message}")
                    
            except Exception as e:
                if verbose:
                    print(f"⚠ Message extraction failed: {e}")
                result['extraction_error'] = str(e)
        
        return result
        
    except Exception as e:
        return {
            'success': False,
            'error': f'Verification failed: {str(e)}'
        }


def main():
    parser = argparse.ArgumentParser(
        description='Verify ZK-Schnorr steganographic proofs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic verification
  python verify_schnorr.py stego_image.png
  
  # Verbose output
  python verify_schnorr.py stego_image.png -v
  
  # JSON output
  python verify_schnorr.py stego_image.png --json
  
  # Extract message with chaos key
  python verify_schnorr.py stego_image.png --extract --chaos-key mysecret -v
        """
    )
    
    parser.add_argument('image', help='Path to steganographic image')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--extract', action='store_true', help='Extract hidden message')
    parser.add_argument('--chaos-key', help='Chaos secret key for message extraction')
    
    args = parser.parse_args()
    
    if not Path(args.image).exists():
        print(f"Error: Image file not found: {args.image}")
        sys.exit(1)
    
    # Verify
    chaos_secret = args.chaos_key if args.extract else None
    result = verify_schnorr_stego(args.image, chaos_secret, args.verbose)
    
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result['success']:
            print("\n" + "="*70)
            print("VERIFICATION RESULT")
            print("="*70)
            
            if result['proof_valid']:
                print("✅ PROOF VALID - Schnorr signature verified")
            else:
                print("❌ PROOF INVALID - Schnorr signature verification failed")
            
            print(f"\nMetadata:")
            print(f"  Feature point: ({result['metadata']['x0']}, {result['metadata']['y0']})")
            print(f"  Message length: {result['metadata']['bit_length']} bits")
            print(f"  Chaos key: {result['metadata']['chaos_key']}")
            print(f"  Proof size: {result['proof_size_bytes']} bytes")
            
            if 'extracted_message' in result:
                print(f"\nExtracted Message:")
                print(f"  {result['extracted_message']}")
            
            print("="*70)
            
            sys.exit(0 if result['proof_valid'] else 1)
        else:
            print(f"❌ Error: {result['error']}")
            if 'details' in result:
                print(f"   {result['details']}")
            sys.exit(1)


if __name__ == '__main__':
    main()
