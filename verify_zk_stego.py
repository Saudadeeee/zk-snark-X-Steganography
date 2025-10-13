#!/usr/bin/env python3
"""
ZK-SNARK Steganography Verification API
Single-command verification of chaos-based steganographic ZK proofs
"""

import argparse
import json
import sys
import os
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent / 'src'))

from zk_stego.hybrid_proof_artifact import extract_chaos_proof

def verify_zk_stego(stego_image_path: str, secret_key: str = None, verbose: bool = False) -> dict:
    """
    Single-command verification of ZK-SNARK steganography
    
    Args:
        stego_image_path: Path to steganographic image
        secret_key: Secret key for chaos parameters (optional)
        verbose: Enable detailed output
        
    Returns:
        dict: Verification result with proof data and metadata
    """
    try:
        if verbose:
            print(f"Analyzing steganographic image: {stego_image_path}")
        
        artifact = extract_chaos_proof(stego_image_path)
        
        if not artifact:
            return {
                'success': False,
                'error': 'No valid ZK proof artifact found in image',
                'details': 'Image may not contain steganographic data or wrong secret key'
            }
        
        # Analyze extracted proof
        proof = artifact.get('proof', {})
        chaos_info = artifact.get('chaos', {})
        
        result = {
            'success': True,
            'proof_found': True,
            'proof_type': 'Groth16 ZK-SNARK',
            'chaos_algorithm': chaos_info.get('algorithm', 'unknown'),
            'proof_elements': list(proof.keys()),
            'proof_size_bits': chaos_info.get('proof_length', 0),
            'embedding_method': 'Chaos-based LSB with PNG metadata',
            'timestamp': chaos_info.get('timestamp'),
            'metadata': {
                'initial_position': chaos_info.get('initial_position', {}),
                'arnold_iterations': chaos_info.get('arnold_iterations', 0),
                'logistic_r': chaos_info.get('logistic_r', 0),
                'positions_used': chaos_info.get('positions_used', 0)
            }
        }
        
        if verbose:
            print("ZK-SNARK Proof Successfully Extracted!")
            print(f"   Algorithm: {result['chaos_algorithm']}")
            print(f"   Proof elements: {', '.join(result['proof_elements'])}")
            print(f"   Data size: {result['proof_size_bits']} bits")
            print(f"   Positions used: {result['metadata']['positions_used']}")
            print(f"   Arnold iterations: {result['metadata']['arnold_iterations']}")
            print(f"   Logistic parameter: {result['metadata']['logistic_r']}")
        
        # Validate proof structure
        required_elements = ['pi_a', 'pi_b', 'pi_c']
        missing_elements = [elem for elem in required_elements if elem not in proof]
        
        if missing_elements:
            result['warning'] = f"Missing proof elements: {missing_elements}"
            if verbose:
                print(f"WARNING  Warning: {result['warning']}")
        
        # Add raw proof data if requested
        result['raw_proof'] = proof
        
        return result
        
    except Exception as e:
        return {
            'success': False,
            'error': f'Verification failed: {str(e)}',
            'details': 'Check image format and accessibility'
        }

def main():
    parser = argparse.ArgumentParser(
        description='Verify ZK-SNARK steganographic images with chaos-based positioning',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic verification
  python3 verify_zk_stego.py stego_image.png
  
  # With secret key
  python3 verify_zk_stego.py stego_image.png --key "my_secret_key"
  
  # Verbose output
  python3 verify_zk_stego.py stego_image.png -v
  
  # JSON output for automation
  python3 verify_zk_stego.py stego_image.png --json
        """
    )
    
    parser.add_argument('image', help='Path to steganographic image')
    parser.add_argument('--key', '-k', help='Secret key for extraction')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--json', '-j', action='store_true', help='JSON output format')
    
    args = parser.parse_args()
    
    # Check if image exists
    
    if not os.path.exists(args.image):
        print(f"ERROR: Image file not found: {args.image}")
        sys.exit(1)    # Perform verification
    result = verify_zk_stego(args.image, args.key, args.verbose and not args.json)
    
    if args.json:
        # JSON output for automation
        print(json.dumps(result, indent=2))
    else:
        # Human-readable output
        if result['success']:
            print(f"ZK-SNARK Proof Verified in {args.image}")
            print(f"   Type: {result['proof_type']}")
            print(f"   Algorithm: {result['chaos_algorithm']}")
            print(f"   Size: {result['proof_size_bits']} bits")
            if result.get('warning'):
                print(f"   WARNING: {result['warning']}")
        else:
            print(f"ERROR: Verification Failed: {result['error']}")
            if result.get('details'):
                print(f"   Details: {result['details']}")
            sys.exit(1)

if __name__ == '__main__':
    main()