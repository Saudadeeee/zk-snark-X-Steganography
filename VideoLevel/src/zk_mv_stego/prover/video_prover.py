"""
Video Prover - DCT Steganography with ZK-SNARK Proofs
======================================================

Complete workflow:
1. Generate ZK proof for message
2. Decode input video to frames
3. Embed proof into DCT coefficients
4. Re-encode video with modified frames (CRF 18, PSNR ≥ 45dB)
5. Save metadata with carrier indices
"""

import json
import hashlib
from pathlib import Path
from typing import Dict, Optional, List
import numpy as np
import time

from .zk_proof_wrapper import ZKProofWrapper
from ..embedder.dct_embedder import DCTEmbedder
from ..embedder.payload_encoder import EmbeddingConfig
from ..encoder.video_encoder import VideoEncoder


class VideoProver:
    """
    Prover for DCT-based video steganography with ZK-SNARK proofs
    """
    
    def __init__(self, circuit_dir: Optional[str] = None, crf: int = 18):
        """
        Initialize Video Prover
        
        Args:
            circuit_dir: Path to ZK circuit files
            crf: Video encoding quality (18 = visually lossless)
        """
        # Initialize ZK proof wrapper
        try:
            self.zk_wrapper = ZKProofWrapper(circuit_dir)
            self.zk_available = True
        except Exception as e:
            print(f"[WARNING] ZK circuits not available: {e}")
            print("[INFO] Will use mock proofs for testing")
            self.zk_available = False
        
        # Embedding configuration
        self.config = EmbeddingConfig(
            ecc_enabled=True,
            min_magnitude=10,  # Min DCT coefficient magnitude
            max_modifications=100000,
            chaos_r=3.9
        )
        
        self.crf = crf
        self.stats = {}
    
    def prove_and_embed(self,
                       input_video: str,
                       output_video: str,
                       output_metadata: str,
                       message: str,
                       max_frames: int = None) -> bool:
        """
        Complete prover workflow: Generate proof and embed in video
        
        Args:
            input_video: Path to input video
            output_video: Path to output video with embedded proof
            output_metadata: Path to metadata JSON file
            message: Message to prove
            max_frames: Max frames to process (None = all)
            
        Returns:
            True if successful
        """
        print(f"\n{'='*70}")
        print("ZK-SNARK VIDEO PROVER - DCT STEGANOGRAPHY")
        print(f"{'='*70}")
        
        start_time = time.time()
        
        # Step 1: Generate ZK proof
        print(f"\n[STEP 1] Generating ZK-SNARK proof...")
        print(f"Message: '{message}'")
        
        if self.zk_available:
            proof_data = self.zk_wrapper.generate_proof(message)
        else:
            # Mock proof for testing
            proof_data = {
                'proof': {
                    'pi_a': ['0x1234', '0x5678'],
                    'pi_b': [['0xabcd', '0xef01'], ['0x2345', '0x6789']],
                    'pi_c': ['0x9abc', '0xdef0']
                },
                'publicSignals': [str(int(hashlib.sha256(message.encode()).hexdigest(), 16) % (2**64))]
            }
        
        proof_bytes = json.dumps(proof_data, separators=(',', ':')).encode('utf-8')
        print(f"✓ Proof generated: {len(proof_bytes)} bytes")
        print(f"  Public signal: {proof_data['publicSignals'][0]}")
        
        # Step 2: Decode video to frames
        print(f"\n[STEP 2] Decoding input video...")
        print(f"Input: {input_video}")
        
        frames = VideoEncoder.decode_frames(input_video, max_frames=max_frames)
        
        if not frames:
            print("✗ Failed to decode video")
            return False
        
        video_info = VideoEncoder.get_video_info(input_video)
        fps = int(video_info.get('fps', 30))
        
        print(f"✓ Decoded {len(frames)} frames")
        print(f"  Resolution: {frames[0].shape[1]}x{frames[0].shape[0]}")
        print(f"  FPS: {fps}")
        
        # Step 3: Embed proof in DCT coefficients
        print(f"\n[STEP 3] Embedding proof into DCT coefficients...")
        
        chaos_seed = int(hashlib.sha256(message.encode()).hexdigest(), 16) % (2**32)
        
        embedder = DCTEmbedder(self.config)
        modified_frames, embedding_info = embedder.embed(
            frames=frames,
            payload=proof_bytes,
            chaos_seed=chaos_seed
        )
        
        print(f"✓ Embedding complete")
        print(f"  Carriers used: {embedding_info['carriers_used']:,}")
        print(f"  Avg modification: {embedding_info['avg_modification']:.2f}")
        
        # Step 4: Encode video with modified frames
        print(f"\n[STEP 4] Encoding stego video...")
        print(f"Output: {output_video}")
        
        encoder = VideoEncoder(output_video, crf=self.crf, preset="veryslow")
        success = encoder.encode(
            frames=modified_frames,
            fps=fps,
            width=frames[0].shape[1],
            height=frames[0].shape[0]
        )
        
        if not success:
            print("✗ Video encoding failed")
            return False
        
        print(f"✓ Video encoded (CRF {self.crf}, target PSNR ≥ 45dB)")
        
        # Step 5: Save metadata
        print(f"\n[STEP 5] Saving metadata...")
        
        metadata = {
            'version': '2.0-DCT',
            'method': 'dct_lsb_steganography',
            'input_video': str(Path(input_video).name),
            'output_video': str(Path(output_video).name),
            'message': message,
            'proof': proof_data,
            'proof_size': len(proof_bytes),
            'embedding_info': embedding_info,
            'chaos_seed': chaos_seed,
            'video_info': {
                'frames': len(frames),
                'fps': fps,
                'resolution': f"{frames[0].shape[1]}x{frames[0].shape[0]}"
            },
            'encoding': {
                'crf': self.crf,
                'preset': 'veryslow',
                'target_psnr': '≥ 45dB'
            }
        }
        
        Path(output_metadata).parent.mkdir(parents=True, exist_ok=True)
        with open(output_metadata, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        print(f"✓ Metadata saved: {output_metadata}")
        
        # Statistics
        elapsed = time.time() - start_time
        
        self.stats = {
            'proof_size': len(proof_bytes),
            'frames_processed': len(frames),
            'carriers_used': embedding_info['carriers_used'],
            'avg_modification': embedding_info['avg_modification'],
            'encoding_time': elapsed
        }
        
        print(f"\n{'='*70}")
        print(f"PROVER COMPLETE")
        print(f"{'='*70}")
        print(f"Total time: {elapsed:.2f}s")
        print(f"Output video: {output_video}")
        print(f"Metadata: {output_metadata}")
        print(f"{'='*70}\n")
        
        return True
    
    def get_stats(self) -> Dict:
        """Get prover statistics"""
        return self.stats
