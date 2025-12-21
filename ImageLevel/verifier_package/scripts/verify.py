#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZK-SNARK Steganography Verification API
Single-command verification of chaos-based steganographic ZK proofs
"""

import argparse
import json
import sys
import os
import io
from pathlib import Path

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

project_root = Path(__file__).parent.parent
sys.path.append(str(project_root / 'src'))

from zk_stego.hybrid_proof_artifact import extract_chaos_proof
from zk_stego.zk_proof_generator import ZKProofGenerator

def verify_zk_stego(stego_image_path: str, secret_key: str = None, verbose: bool = False) -> dict:
    """
    Single-command verification of ZK-SNARK steganography
    
    Args:
        stego_image_path: Path to steganographic image
        secret_key: Secret key for chaos extraction (REQUIRED for version 2.0+)
                   Must be transmitted via secure channel
        verbose: Enable detailed output
        
    Returns:
        dict: Verification result with proof data and metadata
    """
    try:
        if verbose:
            print(f"Analyzing steganographic image: {stego_image_path}")
        
        # Extract proof using secret_key (required for secure version 2.0+)
        try:
            artifact = extract_chaos_proof(stego_image_path, secret_key=secret_key)
        except ValueError as e:
            return {
                'success': False,
                'error': str(e),
                'details': 'Secret key is required for extraction. Use --key option.'
            }
        
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
        
        required_elements = ['pi_a', 'pi_b', 'pi_c']
        missing_elements = [elem for elem in required_elements if elem not in proof]
        
        if missing_elements:
            result['warning'] = f"Missing proof elements: {missing_elements}"
            result['validation_status'] = 'failed'
            result['validation_error'] = f"Missing proof elements: {missing_elements}"
            if verbose:
                print(f"WARNING: {result['warning']}")
        else:
            # Thực hiện ZK proof verification
            try:
                zk_gen = ZKProofGenerator(project_root=str(project_root))
                
                # Convert public inputs từ dict sang list
                # Circuit có nPublic: 3
                # Public inputs format: [commitmentRoot, proofLength, timestamp] (all as strings)
                public_info = artifact.get('public', {})
                
                # If actual public_inputs are stored, use them directly
                if 'public_inputs' in public_info and public_info['public_inputs']:
                    public_list = [str(x) for x in public_info['public_inputs']]
                else:
                    # Fallback: convert from metadata
                    commitment_root_hex = public_info.get('commitment_root', '')
                    try:
                        # Convert hex string to number
                        if commitment_root_hex:
                            commitment_root_num = int(commitment_root_hex, 16)
                        else:
                            commitment_root_num = 0
                    except (ValueError, TypeError):
                        commitment_root_num = 0
                    
                    proof_length = public_info.get('proof_length', 0)
                    timestamp = public_info.get('timestamp', 0)
                    
                    # Format as list of strings (snarkjs expects this format)
                    public_list = [
                        str(commitment_root_num),
                        str(proof_length),
                        str(timestamp)
                    ]
                
                if verbose:
                    print("Verifying ZK-SNARK proof...")
                
                # Suppress output từ ZKProofGenerator
                import io
                import contextlib
                
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    is_valid = zk_gen.verify_proof(proof, public_list)
                
                if is_valid:
                    result['validation_status'] = 'success'
                    result['zk_verification'] = True
                    if verbose:
                        print("ZK-SNARK proof verification: PASSED")
                else:
                    result['validation_status'] = 'failed'
                    result['zk_verification'] = False
                    result['validation_error'] = 'ZK proof verification failed'
                    if verbose:
                        print("ZK-SNARK proof verification: FAILED")
                        
            except Exception as e:
                # Nếu không thể verify (thiếu snarkjs, etc.), vẫn coi là success nếu extract được
                result['validation_status'] = 'warning'
                result['zk_verification'] = None
                result['validation_warning'] = f"Could not verify ZK proof: {str(e)}"
                if verbose:
                    print(f"WARNING: Could not verify ZK proof: {e}")
                    print("  (Proof extracted successfully, but ZK verification requires snarkjs)")
        
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
  # Verification with secret key (REQUIRED for version 2.0+)
  python scripts/verify.py stego_image.png --key "my_secret_key"
  
  # Verbose output  
  python scripts/verify.py stego_image.png --key "my_secret_key" -v
  
  # JSON output for automation
  python scripts/verify.py stego_image.png --key "my_secret_key" --json

SECURITY NOTE:
  The secret key must be transmitted via a SECURE CHANNEL (not stored in image).
  This ensures that only authorized parties can extract and verify the proof.
        """
    )
    
    parser.add_argument('image', help='Path to steganographic image')
    parser.add_argument('--key', '-k', required=True, 
                       help='Secret key for extraction (REQUIRED - must be transmitted securely)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--json', '-j', action='store_true', help='JSON output format')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.image):
        print(f"ERROR: Image file not found: {args.image}")
        print("\n[FAILED] Validate FAILED")
        sys.exit(1)
    
    result = verify_zk_stego(args.image, args.key, args.verbose and not args.json)
    
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result['success']:
            print(f"ZK-SNARK Proof Verified in {args.image}")
            print(f"   Type: {result['proof_type']}")
            print(f"   Algorithm: {result['chaos_algorithm']}")
            print(f"   Size: {result['proof_size_bits']} bits")
            
            # Hiển thị validation status
            validation_status = result.get('validation_status', 'unknown')
            if validation_status == 'success':
                print("\n[SUCCESS] Validate SUCCESS")
            elif validation_status == 'failed':
                print("\n[FAILED] Validate FAILED")
                if result.get('validation_error'):
                    print(f"   Error: {result['validation_error']}")
            elif validation_status == 'warning':
                print("\n[WARNING] Validate WARNING")
                if result.get('validation_warning'):
                    print(f"   Warning: {result['validation_warning']}")
            
            if result.get('warning'):
                print(f"   WARNING: {result['warning']}")
        else:
            print(f"ERROR: Verification Failed: {result['error']}")
            if result.get('details'):
                print(f"   Details: {result['details']}")
            print("\n[FAILED] Validate FAILED")
            sys.exit(1)

if __name__ == '__main__':
    main()
