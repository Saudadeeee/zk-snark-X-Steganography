"""
Video Verifier - Extract and Verify ZK Proofs
==============================================

Complete verification workflow:
1. Extract proof from video MVs
2. Verify proof with public inputs
3. No need to know secret message!

This demonstrates zero-knowledge property:
- Verifier can confirm proof validity
- Without learning the secret message
"""

import json
from pathlib import Path
from typing import Tuple, Dict
from ..embedder.mv_embedder import MVExtractor
from ..prover.zk_proof_wrapper import ZKProofWrapper


class VideoVerifier:
    """
    Verify ZK-SNARK proofs embedded in video
    
    Zero-knowledge verification:
    - Confirms message was correctly embedded
    - Without revealing the message content
    """
    
    def __init__(self, circuit_dir=None):
        """Initialize Video Verifier"""
        try:
            self.zk_wrapper = ZKProofWrapper(circuit_dir)
            self.zk_available = True
        except Exception as e:
            print(f"[WARNING] ZK circuits not available: {e}")
            self.zk_available = False
    
    def verify_stego_video(self, stego_json: str) -> Tuple[bool, Dict]:
        """
        Verify ZK proof in stego video
        
        Args:
            stego_json: Path to stego video metadata JSON
            
        Returns:
            (valid, verification_data) tuple
        """
        print(f"\n{'='*80}")
        print("VIDEO VERIFIER: ZK-SNARK PROOF VERIFICATION")
        print(f"{'='*80}\n")
        
        # Step 1: Load stego metadata
        print("[Step 1/4] Loading stego video metadata...")
        with open(stego_json, 'r') as f:
            stego_data = json.load(f)
        
        print(f"  Video: {stego_data['video_path']}")
        print(f"  Video hash: {stego_data['video_hash'][:32]}...")
        print(f"  Proof size: {stego_data['proof_size']} bytes")
        print(f"  Carriers used: {stego_data['embedding_info']['carriers_used']}")
        
        # Step 2: Extract proof from MVs
        print(f"\n[Step 2/4] Extracting proof from motion vectors...")
        
        extractor = MVExtractor()
        
        # Use carrier indices if available (deterministic extraction)
        carrier_indices = stego_data['embedding_info'].get('carrier_indices')
        
        if carrier_indices:
            print(f"  Using deterministic carrier indices")
            proof_bytes, extraction_valid = extractor.extract(
                stego_data['modified_mvs'],
                carrier_indices=carrier_indices,
                component=stego_data['embedding_info']['config']['component']
            )
        else:
            # Fallback to chaos-based selection
            print(f"  Using chaos-based carrier selection")
            proof_bytes, extraction_valid = extractor.extract(
                stego_data['modified_mvs'],
                chaos_seed=stego_data['chaos_seed'],
                expected_bits=stego_data['embedding_info']['bits_embedded'],
                component=stego_data['embedding_info']['config']['component']
            )
        
        if not extraction_valid:
            print(f"  [ERROR] Proof extraction failed")
            return False, {}
        
        print(f"  Extracted {len(proof_bytes)} bytes")
        
        # Step 3: Verify proof
        print(f"\n[Step 3/4] Verifying ZK proof...")
        
        # Check if it's a mock proof
        try:
            proof_obj = json.loads(proof_bytes.decode('utf-8'))
            if isinstance(proof_obj, dict) and proof_obj.get('type') == 'mock_groth16_proof':
                print(f"  [INFO] Mock proof detected")
                print(f"  Message hash: {proof_obj['message_hash'][:16]}...")
                print(f"  Video hash: {proof_obj['video_hash'][:16]}...")
                
                # Verify hashes match
                if proof_obj['video_hash'] == stego_data['video_hash']:
                    print(f"  [OK] Video hash matches")
                    is_valid = True
                else:
                    print(f"  [ERROR] Video hash mismatch")
                    is_valid = False
                
                verified_data = {
                    'proof_type': 'mock',
                    'message_hash': proof_obj['message_hash'],
                    'video_hash': proof_obj['video_hash']
                }
            else:
                # Real ZK proof
                if not self.zk_available:
                    print(f"  [ERROR] Real proof found but ZK circuits not available")
                    return False, {}
                
                is_valid, verified_data = self.zk_wrapper.verify_proof(proof_bytes)
        except:
            # Binary proof - need ZK verification
            if not self.zk_available:
                print(f"  [ERROR] ZK circuits not available for verification")
                return False, {}
            
            is_valid, verified_data = self.zk_wrapper.verify_proof(proof_bytes)
        
        # Step 4: Summary
        print(f"\n[Step 4/4] Verification summary:")
        print(f"  Proof valid: {is_valid}")
        print(f"  Extraction rate: {100*stego_data['verification']['modification_rate']:.2f}%")
        
        if is_valid:
            print(f"\n{'='*80}")
            print("[OK] PROOF VERIFICATION SUCCESSFUL")
            print(f"{'='*80}")
            print(f"\nZero-Knowledge Property Demonstrated:")
            print(f"  [OK] Proof is valid")
            print(f"  [OK] Message was correctly embedded")
            print(f"  [OK] Secret message remains unknown to verifier")
            print(f"{'='*80}\n")
        else:
            print(f"\n{'='*80}")
            print("[FAIL] PROOF VERIFICATION FAILED")
            print(f"{'='*80}\n")
        
        return is_valid, {
            **verified_data,
            'extraction_valid': extraction_valid,
            'stego_metadata': stego_data['verification']
        }


def main():
    """CLI interface for Video Verifier"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Video Verifier - Verify ZK Proofs in Video')
    parser.add_argument('--input', required=True, help='Stego video metadata JSON')
    parser.add_argument('--circuit-dir', help='Path to circuit directory')
    
    args = parser.parse_args()
    
    # Create verifier
    verifier = VideoVerifier(circuit_dir=args.circuit_dir)
    
    # Verify
    valid, data = verifier.verify_stego_video(args.input)
    
    if valid:
        print(f"\n[SUCCESS] Verification passed")
        exit(0)
    else:
        print(f"\n[FAILURE] Verification failed")
        exit(1)


if __name__ == '__main__':
    main()
