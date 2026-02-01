"""
Verify Extracted Payload
=========================

Verifies extracted payload from stego video:
1. Validates message integrity (hash check)
2. Checks proof format and structure
3. Reports verification status

Note: Full ZK-SNARK proof verification requires complete 336-byte Groth16 proof.
      Current system limitation: Only ~98 bytes can be embedded due to bitstream
      reconstruction constraints. This script validates the extraction integrity.

Usage:
    python scripts/verify.py <extracted_payload.json>

Example:
    python scripts/verify.py data/output/extracted_payload.json

Author: ZK Video Stego Team  
Date: January 2026
"""

import sys
import json
import hashlib
from pathlib import Path


def verify_payload(payload_data: dict, verbose: bool = True) -> dict:
    """
    Verify extracted payload integrity
    
    Args:
        payload_data: Dictionary with extracted payload data
        verbose: Print detailed verification steps
    
    Returns:
        Dictionary with verification results
    """
    results = {
        'message_valid': False,
        'proof_valid': False,
        'extraction_valid': False,
        'errors': [],
        'warnings': []
    }
    
    if verbose:
        print("="*80)
        print("PAYLOAD VERIFICATION")
        print("="*80)
    
    # 1. Validate message
    if verbose:
        print("\n[1/3] Validating message...")
    
    try:
        message = payload_data.get('message', '')
        message_length = payload_data.get('message_length', 0)
        message_hash = payload_data.get('message_hash', '')
        
        # Check message length matches
        actual_length = len(message.encode('utf-8'))
        if actual_length != message_length:
            results['errors'].append(
                f"Message length mismatch: header={message_length}, actual={actual_length}"
            )
        else:
            if verbose:
                print(f"  [OK] Message length: {message_length} bytes")
        
        # Verify message hash
        computed_hash = hashlib.sha256(message.encode('utf-8')).hexdigest()
        if computed_hash != message_hash:
            results['errors'].append(
                f"Message hash mismatch: expected={message_hash}, computed={computed_hash}"
            )
        else:
            if verbose:
                print(f"  [OK] Message hash: {message_hash[:16]}...")
            results['message_valid'] = True
        
        if verbose:
            print(f"  [OK] Message: '{message}'")
    
    except Exception as e:
        results['errors'].append(f"Message validation failed: {e}")
    
    # 2. Validate proof
    if verbose:
        print("\n[2/3] Validating proof...")
    
    try:
        proof_bytes = payload_data.get('proof_bytes', 0)
        proof_hex = payload_data.get('proof_hex', '')
        
        # Check proof exists
        if proof_bytes == 0:
            results['warnings'].append("No proof data found")
        else:
            if verbose:
                print(f"  [OK] Proof size: {proof_bytes} bytes")
            
            # Verify hex encoding
            try:
                proof_data = bytes.fromhex(proof_hex)
                if len(proof_data) != proof_bytes:
                    results['errors'].append(
                        f"Proof hex length mismatch: expected={proof_bytes}, actual={len(proof_data)}"
                    )
                else:
                    if verbose:
                        print(f"  [OK] Proof hex: {proof_hex[:32]}...")
                    results['proof_valid'] = True
            except ValueError as e:
                results['errors'].append(f"Invalid proof hex: {e}")
            
            # Check if proof is complete
            if proof_bytes != 336:
                results['warnings'].append(
                    f"Incomplete proof: {proof_bytes}/336 bytes. "
                    "Full ZK-SNARK verification requires 336-byte Groth16 proof. "
                    "Current system limitation allows only ~98 bytes total payload."
                )
                if verbose:
                    print(f"  [WARNING] Incomplete proof ({proof_bytes}/336 bytes)")
                    print(f"            Full ZK-SNARK verification not possible")
    
    except Exception as e:
        results['errors'].append(f"Proof validation failed: {e}")
    
    # 3. Validate extraction info
    if verbose:
        print("\n[3/3] Validating extraction...")
    
    try:
        extraction_info = payload_data.get('extraction_info', {})
        
        frames_processed = extraction_info.get('frames_processed', 0)
        usable_coeffs = extraction_info.get('usable_coefficients', 0)
        capacity_bytes = extraction_info.get('capacity_bytes', 0)
        bits_extracted = extraction_info.get('bits_extracted', 0)
        
        if verbose:
            print(f"  [OK] Frames processed: {frames_processed}")
            print(f"  [OK] Usable coefficients: {usable_coeffs:,}")
            print(f"  [OK] Capacity: {capacity_bytes} bytes")
            print(f"  [OK] Bits extracted: {bits_extracted:,}")
        
        # Check capacity usage
        total_bytes = payload_data.get('total_bytes', 0)
        if total_bytes > capacity_bytes:
            results['errors'].append(
                f"Payload exceeds capacity: {total_bytes} > {capacity_bytes} bytes"
            )
        else:
            usage_pct = (total_bytes / capacity_bytes * 100) if capacity_bytes > 0 else 0
            if verbose:
                print(f"  [OK] Capacity usage: {total_bytes}/{capacity_bytes} bytes ({usage_pct:.1f}%)")
            results['extraction_valid'] = True
    
    except Exception as e:
        results['errors'].append(f"Extraction validation failed: {e}")
    
    # Overall status
    results['success'] = (
        results['message_valid'] and 
        results['proof_valid'] and 
        results['extraction_valid'] and
        len(results['errors']) == 0
    )
    
    return results


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    # Parse arguments
    payload_json = Path(sys.argv[1])
    
    if not payload_json.exists():
        print(f"[ERROR] Payload file not found: {payload_json}")
        sys.exit(1)
    
    try:
        # Load extracted payload
        with open(payload_json, 'r', encoding='utf-8') as f:
            payload_data = json.load(f)
        
        # Verify payload
        results = verify_payload(payload_data, verbose=True)
        
        # Print results
        print("\n" + "="*80)
        print("VERIFICATION RESULTS")
        print("="*80)
        print(f"Message valid: {'YES' if results['message_valid'] else 'NO'}")
        print(f"Proof valid: {'YES' if results['proof_valid'] else 'NO'}")
        print(f"Extraction valid: {'YES' if results['extraction_valid'] else 'NO'}")
        
        if results['errors']:
            print(f"\nErrors ({len(results['errors'])}):")
            for error in results['errors']:
                print(f"  - {error}")
        
        if results['warnings']:
            print(f"\nWarnings ({len(results['warnings'])}):")
            for warning in results['warnings']:
                print(f"  - {warning}")
        
        print("\n" + "="*80)
        if results['success']:
            print("STATUS: VERIFICATION SUCCESSFUL")
        else:
            print("STATUS: VERIFICATION FAILED")
        print("="*80)
        
        sys.exit(0 if results['success'] else 1)
        
    except Exception as e:
        print(f"\n[ERROR] Verification failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
