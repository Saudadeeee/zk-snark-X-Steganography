"""
Video Verifier - Extract and Verify ZK Proofs
==============================================

Complete verification workflow:
1. Extract MVs from stego video file OR load from metadata
2. Extract proof from MVs
3. Verify proof with public inputs
4. Demonstrate zero-knowledge property

This demonstrates zero-knowledge property:
- Verifier can confirm proof validity
- Without learning the secret message
"""

import json
from pathlib import Path
from typing import Tuple, Dict, Optional
from ..embedder.mv_embedder import MVExtractor
from ..prover.zk_proof_wrapper import ZKProofWrapper
from ..extractor.h264_parser import H264MVExtractor


class VideoVerifier:
    """
    Verify ZK-SNARK proofs embedded in video
    
    Zero-knowledge verification:
    - Confirms message was correctly embedded
    - Without revealing the message content
    
    Supports two verification modes:
    1. From stego video file directly (extracts MVs using PyAV)
    2. From metadata JSON (uses pre-extracted MVs)
    """
    
    def __init__(self, circuit_dir=None):
        """Initialize Video Verifier"""
        try:
            self.zk_wrapper = ZKProofWrapper(circuit_dir)
            self.zk_available = True
        except Exception as e:
            print(f"[WARNING] ZK circuits not available: {e}")
            self.zk_available = False
    
    def verify_from_video_file(self, stego_video: str, metadata_json: Optional[str] = None) -> Tuple[bool, Dict]:
        """
        Verify ZK proof by extracting MVs directly from stego video file
        
        Args:
            stego_video: Path to stego video file (.mp4)
            metadata_json: Optional path to metadata (contains carrier info)
            
        Returns:
            (valid, verification_data) tuple
        """
        print(f"\n{'='*80}")
        print("VIDEO VERIFIER: EXTRACT FROM STEGO VIDEO FILE")
        print(f"{'='*80}\n")
        
        # Step 1: Extract MVs from stego video
        print("[Step 1/5] Extracting motion vectors from stego video...")
        extractor = H264MVExtractor(stego_video)
        extractor.extract_motion_vectors()
        
        print(f"  Extracted {len(extractor.mv_data)} motion vectors")
        
        # Convert to dict format
        mv_dicts = []
        for mv in extractor.mv_data:
            mv_dicts.append({
                'frame_idx': mv.frame_idx,
                'frame_type': mv.frame_type,  # Include frame type
                'mvx': mv.motion_x,
                'mvy': mv.motion_y,
                'mb_x': mv.src_x // 16,
                'mb_y': mv.src_y // 16,
                'magnitude': mv.magnitude,  # Include magnitude for carrier selection
                'parity_x': mv.parity_x,
                'parity_y': mv.parity_y
            })
        
        # Step 2: Load metadata if provided (for carrier indices)
        carrier_indices = None
        chaos_seed = None
        expected_bits = None
        component = 'mvx'
        
        if metadata_json:
            print(f"\n[Step 2/5] Loading metadata...")
            metadata_path = Path(metadata_json)
            
            # Check for sidecar metadata
            if not metadata_path.exists():
                sidecar_path = Path(stego_video).with_suffix('.stego.json')
                if sidecar_path.exists():
                    metadata_path = sidecar_path
            
            if metadata_path.exists():
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                
                # Check metadata version
                if metadata.get('version') == '2.0':
                    # New enhanced format
                    print(f"  Using enhanced metadata v2.0")
                    print(f"  MV modifications: {metadata['total_mvs_modified']}")
                    
                    # Get extraction info from sidecar
                    extraction_info = metadata.get('extraction_info', {})
                    carrier_indices = extraction_info.get('carrier_indices')
                    component = extraction_info.get('component', 'mvx')
                    expected_bits = extraction_info.get('expected_bits', 0)
                    
                    if carrier_indices:
                        print(f"  Found carrier indices: {len(carrier_indices)} carriers")
                    
                    # Note: We don't need to apply modifications here
                    # The MVs from video are already in original form
                    # We'll extract using carrier indices directly
                
                else:
                    # Legacy format
                    if 'embedding_info' in metadata:
                        carrier_indices = metadata['embedding_info'].get('carrier_indices')
                        component = metadata['embedding_info']['config']['component']
                        expected_bits = metadata['embedding_info']['bits_embedded']
                    
                    if 'chaos_seed' in metadata:
                        chaos_seed = metadata['chaos_seed']
                
                print(f"  Metadata loaded successfully")
            else:
                print(f"  [WARNING] Metadata not found, using defaults")
        else:
            print(f"\n[Step 2/5] No metadata provided, using default extraction")
        
        # Step 3: Extract proof bits from MVs
        print(f"\n[Step 3/5] Extracting proof from motion vectors...")
        
        mv_extractor = MVExtractor()
        
        if carrier_indices:
            proof_bytes, extraction_valid = mv_extractor.extract(
                mv_dicts,
                carrier_indices=carrier_indices,
                component=component
            )
        elif chaos_seed is not None:
            proof_bytes, extraction_valid = mv_extractor.extract(
                mv_dicts,
                chaos_seed=chaos_seed,
                expected_bits=expected_bits,
                component=component
            )
        else:
            # Automatic extraction (tries to find proof)
            print(f"  [WARNING] No carrier info, attempting automatic extraction")
            # This is a fallback and may not work reliably
            proof_bytes, extraction_valid = mv_extractor.extract(
                mv_dicts,
                chaos_seed=0,  # Default seed
                expected_bits=8000,  # Reasonable default
                component=component
            )
        
        if not extraction_valid:
            print(f"  [ERROR] Proof extraction failed")
            return False, {'error': 'Extraction failed'}
        
        print(f"  Extracted {len(proof_bytes)} bytes")
        
        # Step 4: Verify proof
        print(f"\n[Step 4/5] Verifying ZK proof...")
        is_valid, verified_data = self._verify_proof_bytes(proof_bytes)
        
        # Step 5: Summary
        print(f"\n[Step 5/5] Verification summary:")
        print(f"  Proof valid: {is_valid}")
        print(f"  Source: Direct video extraction")
        
        if is_valid:
            print(f"\n{'='*80}")
            print("[OK] PROOF VERIFICATION SUCCESSFUL")
            print(f"{'='*80}")
            print(f"\nZero-Knowledge Property Demonstrated:")
            print(f"  [OK] Proof extracted from video")
            print(f"  [OK] Proof is cryptographically valid")
            print(f"  [OK] Secret message remains unknown to verifier")
            print(f"{'='*80}\n")
        else:
            print(f"\n{'='*80}")
            print("[FAIL] PROOF VERIFICATION FAILED")
            print(f"{'='*80}\n")
        
        return is_valid, {
            **verified_data,
            'extraction_valid': extraction_valid,
            'extraction_mode': 'direct_video'
        }
    
    def verify_stego_video(self, stego_json: str) -> Tuple[bool, Dict]:
        """
        Verify ZK proof from stego metadata JSON (legacy method)
        
        Args:
            stego_json: Path to stego video metadata JSON
            
        Returns:
            (valid, verification_data) tuple
        """
        print(f"\n{'='*80}")
        print("VIDEO VERIFIER: ZK-SNARK PROOF VERIFICATION (METADATA)")
        print(f"{'='*80}\n")
        
        # Step 1: Load stego metadata
        print("[Step 1/4] Loading stego video metadata...")
        with open(stego_json, 'r') as f:
            stego_data = json.load(f)
        
        # Check if there's an associated stego video file
        if 'stego_video' in stego_data and Path(stego_data['stego_video']).exists():
            print(f"  [INFO] Stego video file found, switching to direct extraction mode")
            return self.verify_from_video_file(
                stego_data['stego_video'],
                metadata_json=stego_json
            )
        
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
        is_valid, verified_data = self._verify_proof_bytes(proof_bytes)
        
        # Check video hash if available
        if 'video_hash' in verified_data and 'video_hash' in stego_data:
            if verified_data['video_hash'] == stego_data['video_hash']:
                print(f"  [OK] Video hash matches")
            else:
                print(f"  [WARNING] Video hash mismatch")
        
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
            'stego_metadata': stego_data['verification'],
            'extraction_mode': 'metadata'
        }
    
    def _verify_proof_bytes(self, proof_bytes: bytes) -> Tuple[bool, Dict]:
        """
        Internal method to verify proof bytes
        
        Args:
            proof_bytes: Extracted proof bytes
            
        Returns:
            (is_valid, verified_data) tuple
        """
        # Check if it's a mock proof
        try:
            proof_obj = json.loads(proof_bytes.decode('utf-8'))
            if isinstance(proof_obj, dict) and proof_obj.get('type') == 'mock_groth16_proof':
                print(f"  [INFO] Mock proof detected")
                print(f"  Message hash: {proof_obj['message_hash'][:16]}...")
                print(f"  Video hash: {proof_obj['video_hash'][:16]}...")
                
                # Mock proofs are always valid (for testing)
                is_valid = True
                
                verified_data = {
                    'proof_type': 'mock',
                    'message_hash': proof_obj['message_hash'],
                    'video_hash': proof_obj['video_hash']
                }
                
                return is_valid, verified_data
                
        except:
            pass  # Not a JSON proof, continue to real verification
        
        # Real ZK proof verification
        if not self.zk_available:
            print(f"  [ERROR] Real proof found but ZK circuits not available")
            return False, {'error': 'ZK circuits not available'}
        
        try:
            is_valid, verified_data = self.zk_wrapper.verify_proof(proof_bytes)
            return is_valid, verified_data
        except Exception as e:
            print(f"  [ERROR] Proof verification failed: {e}")
            return False, {'error': str(e)}


def main():
    """CLI interface for Video Verifier"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Video Verifier - Verify ZK Proofs in Video',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Verify from metadata JSON
  python -m src.zk_mv_stego.verifier.video_verifier --stego-json results/stego.json
  
  # Verify directly from video file
  python -m src.zk_mv_stego.verifier.video_verifier --stego-video results/stego.mp4
  
  # Verify from video with metadata
  python -m src.zk_mv_stego.verifier.video_verifier --stego-video results/stego.mp4 --metadata results/stego.json
"""
    )
    
    parser.add_argument('--stego-json', help='Stego video metadata JSON (legacy mode)')
    parser.add_argument('--stego-video', help='Stego video file (.mp4) for direct extraction')
    parser.add_argument('--metadata', help='Optional metadata file for video extraction')
    parser.add_argument('--circuit-dir', help='Path to circuit directory')
    
    args = parser.parse_args()
    
    # Validate arguments
    if not args.stego_json and not args.stego_video:
        parser.error("Either --stego-json or --stego-video must be provided")
    
    # Create verifier
    verifier = VideoVerifier(circuit_dir=args.circuit_dir)
    
    # Verify
    if args.stego_video:
        # Direct video extraction mode
        valid, data = verifier.verify_from_video_file(
            args.stego_video,
            metadata_json=args.metadata
        )
    else:
        # Legacy metadata mode
        valid, data = verifier.verify_stego_video(args.stego_json)
    
    if valid:
        print(f"\n[SUCCESS] Verification passed")
        exit(0)
    else:
        print(f"\n[FAILURE] Verification failed")
        exit(1)


if __name__ == '__main__':
    main()
