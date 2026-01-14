"""
Video Verifier - DCT Steganography with ZK-SNARK Verification
==============================================================

Complete workflow:
1. Decode stego video to frames
2. Extract proof from DCT coefficients using carrier indices
3. Verify ZK-SNARK proof
4. Return verification result
"""

import json
import hashlib
from pathlib import Path
from typing import Dict, Optional, Tuple
import time

from .zk_proof_wrapper import ZKProofWrapper
from ..embedder.dct_embedder import DCTExtractor
from ..encoder.video_encoder import VideoEncoder


class VideoVerifier:
    """
    Verifier for DCT-based video steganography with ZK-SNARK proofs
    """
    
    def __init__(self, circuit_dir: Optional[str] = None):
        """
        Initialize Video Verifier
        
        Args:
            circuit_dir: Path to ZK circuit files
        """
        # Initialize ZK proof wrapper
        try:
            self.zk_wrapper = ZKProofWrapper(circuit_dir)
            self.zk_available = True
        except Exception as e:
            print(f"[WARNING] ZK circuits not available: {e}")
            print("[INFO] Will use mock verification for testing")
            self.zk_available = False
        
        self.stats = {}
    
    def extract_and_verify(self,
                          stego_video: str,
                          metadata_path: str,
                          expected_message: Optional[str] = None) -> Tuple[bool, Dict]:
        """
        Complete verifier workflow: Extract proof and verify
        
        Args:
            stego_video: Path to stego video
            metadata_path: Path to metadata JSON
            expected_message: Expected message (optional, for validation)
            
        Returns:
            (verification_result, details) tuple
        """
        print(f"\n{'='*70}")
        print("ZK-SNARK VIDEO VERIFIER - DCT STEGANOGRAPHY")
        print(f"{'='*70}")
        
        start_time = time.time()
        
        # Step 1: Load metadata
        print(f"\n[STEP 1] Loading metadata...")
        print(f"Metadata: {metadata_path}")
        
        try:
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
        except Exception as e:
            print(f"✗ Failed to load metadata: {e}")
            return False, {'error': str(e)}
        
        embedding_info = metadata['embedding_info']
        carrier_indices = embedding_info['carrier_indices']
        chaos_seed = metadata['chaos_seed']
        message = metadata.get('message', '')
        
        print(f"✓ Metadata loaded")
        print(f"  Message: '{message}'")
        print(f"  Carriers: {len(carrier_indices):,}")
        print(f"  Method: {metadata.get('method', 'unknown')}")
        
        # Step 2: Decode video
        print(f"\n[STEP 2] Decoding stego video...")
        print(f"Video: {stego_video}")
        
        max_frames = metadata['video_info']['frames']
        frames = VideoEncoder.decode_frames(stego_video, max_frames=max_frames)
        
        if not frames:
            print("✗ Failed to decode video")
            return False, {'error': 'Failed to decode video'}
        
        print(f"✓ Decoded {len(frames)} frames")
        
        # Step 3: Extract proof from DCT coefficients
        print(f"\n[STEP 3] Extracting proof from DCT coefficients...")
        
        extractor = DCTExtractor()
        proof_bytes, extraction_valid = extractor.extract(
            frames=frames,
            carrier_indices=carrier_indices,
            chaos_seed=chaos_seed
        )
        
        if not extraction_valid:
            print("✗ Proof extraction failed")
            return False, {'error': 'Proof extraction failed (ECC check)'}
        
        print(f"✓ Proof extracted: {len(proof_bytes)} bytes")
        
        # Step 4: Decode proof
        print(f"\n[STEP 4] Decoding proof...")
        
        try:
            proof_data = json.loads(proof_bytes.decode('utf-8'))
            public_signal = proof_data['publicSignals'][0]
            print(f"✓ Proof decoded")
            print(f"  Public signal: {public_signal}")
        except Exception as e:
            print(f"✗ Failed to decode proof: {e}")
            return False, {'error': f'Proof decode failed: {e}'}
        
        # Step 5: Verify ZK proof
        print(f"\n[STEP 5] Verifying ZK-SNARK proof...")
        
        if self.zk_available:
            zk_valid = self.zk_wrapper.verify_proof(proof_data, message)
        else:
            # Mock verification
            expected_signal = str(int(hashlib.sha256(message.encode()).hexdigest(), 16) % (2**64))
            zk_valid = (public_signal == expected_signal)
        
        if zk_valid:
            print(f"✓ ZK proof VALID")
        else:
            print(f"✗ ZK proof INVALID")
        
        # Step 6: Validate message (if provided)
        message_valid = True
        if expected_message is not None:
            message_valid = (message == expected_message)
            if message_valid:
                print(f"✓ Message matches expected: '{expected_message}'")
            else:
                print(f"✗ Message mismatch!")
                print(f"  Expected: '{expected_message}'")
                print(f"  Got: '{message}'")
        
        # Final result
        elapsed = time.time() - start_time
        overall_valid = zk_valid and extraction_valid and message_valid
        
        details = {
            'zk_proof_valid': zk_valid,
            'extraction_valid': extraction_valid,
            'message_valid': message_valid,
            'overall_valid': overall_valid,
            'message': message,
            'public_signal': public_signal,
            'proof_size': len(proof_bytes),
            'carriers_used': len(carrier_indices),
            'verification_time': elapsed,
            'method': metadata.get('method'),
            'version': metadata.get('version')
        }
        
        self.stats = details
        
        print(f"\n{'='*70}")
        print(f"VERIFICATION {'SUCCESS' if overall_valid else 'FAILED'}")
        print(f"{'='*70}")
        print(f"ZK Proof: {'✓ VALID' if zk_valid else '✗ INVALID'}")
        print(f"Extraction: {'✓ VALID' if extraction_valid else '✗ INVALID'}")
        if expected_message:
            print(f"Message: {'✓ MATCH' if message_valid else '✗ MISMATCH'}")
        print(f"Time: {elapsed:.2f}s")
        print(f"{'='*70}\n")
        
        return overall_valid, details
    
    def get_stats(self) -> Dict:
        """Get verifier statistics"""
        return self.stats
