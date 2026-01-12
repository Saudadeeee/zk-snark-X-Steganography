"""
Video Prover - Embed ZK Proofs into Video
==========================================

Complete workflow:
1. Generate ZK proof for message
2. Serialize proof (~256 bytes)
3. Embed proof into video MVs
4. Save stego video metadata

This combines:
- Phase 2: ZK proof generation
- Phase 1: MV embedding
"""

import json
import hashlib
from pathlib import Path
from typing import Dict, Optional
from ..extractor.h264_parser import H264MVExtractor
from ..embedder.payload_encoder import EmbeddingConfig
from ..embedder.mv_embedder import MVEmbedder
from .zk_proof_wrapper import ZKProofWrapper


class VideoProver:
    """
    Embed ZK-SNARK proofs into video motion vectors
    
    Complete steganography workflow with cryptographic proof
    """
    
    def __init__(self, circuit_dir: Optional[str] = None):
        """
        Initialize Video Prover
        
        Args:
            circuit_dir: Path to ZK circuit files
        """
        # Try to initialize ZK proof wrapper
        try:
            self.zk_wrapper = ZKProofWrapper(circuit_dir)
            self.zk_available = True
        except Exception as e:
            print(f"[WARNING] ZK circuits not available: {e}")
            print("[INFO] Will use mock proofs for testing")
            self.zk_available = False
        
        # Embedding configuration
        self.config = EmbeddingConfig(
            method='lsb_parity',
            component='mvx',
            min_magnitude=2.0,  # Stable under ±1 modification
            max_magnitude=50.0,
            embedding_rate=0.2,
            ecc_enabled=True
        )
    
    def embed_with_proof(self,
                        video_path: str,
                        message: str,
                        chaos_key: str,
                        output_json: str,
                        output_video: Optional[str] = None,
                        generate_real_proof: bool = True) -> bool:
        """
        Complete workflow: Generate ZK proof + Embed into video
        
        Args:
            video_path: Path to input H.264 video
            message: Secret message (private input)
            chaos_key: Chaos key for embedding (private input)
            output_json: Path to save stego video metadata
            output_video: Optional path to save stego video file (requires ffmpeg)
            generate_real_proof: If True, generate real ZK proof
                                If False, use mock proof for testing
            
        Returns:
            Embedding metadata dictionary
        """
        print(f"\n{'='*80}")
        print("VIDEO PROVER: ZK-SNARK VIDEO STEGANOGRAPHY")
        print(f"{'='*80}\n")
        
        # Step 1: Compute video hash (public input)
        print("[Step 1/5] Computing video hash...")
        video_hash = self._compute_video_hash(video_path)
        print(f"  Video hash: {video_hash[:32]}...")
        
        # Step 2: Generate ZK proof
        print(f"\n[Step 2/5] Generating ZK proof...")
        if generate_real_proof and self.zk_available:
            proof_data = self.zk_wrapper.generate_proof(
                message=message,
                chaos_key=chaos_key,
                video_hash=video_hash
            )
            proof_bytes = proof_data['proof_bytes']
            print(f"  Real ZK proof generated: {len(proof_bytes)} bytes")
        else:
            # Mock proof for testing
            proof_bytes = self._generate_mock_proof(message, chaos_key, video_hash)
            print(f"  Mock proof generated: {len(proof_bytes)} bytes")
            print(f"  [INFO] To use real proofs, set generate_real_proof=True")
        
        # Step 3: Extract MVs from video
        print(f"\n[Step 3/5] Extracting motion vectors...")
        extractor = H264MVExtractor(video_path)
        extractor.extract_motion_vectors()
        
        print(f"  Extracted {len(extractor.mv_data)} motion vectors")
        
        # Convert to dict format
        mv_dicts = []
        for mv in extractor.mv_data:
            mv_dicts.append({
                'frame_idx': mv.frame_idx,
                'frame_type': mv.frame_type,
                'timestamp': mv.timestamp,
                'mb_x': mv.src_x // 16,
                'mb_y': mv.src_y // 16,
                'mvx': mv.motion_x,
                'mvy': mv.motion_y,
                'block_type': f"{mv.w}x{mv.h}"
            })
        
        # Step 4: Embed proof into MVs
        print(f"\n[Step 4/5] Embedding proof into motion vectors...")
        
        # Use chaos_key hash as seed for carrier selection
        chaos_seed = int(hashlib.sha256(chaos_key.encode()).hexdigest()[:8], 16)
        
        embedder = MVEmbedder(self.config)
        modified_mv_data, embedding_info = embedder.embed(
            mv_dicts,
            proof_bytes,
            chaos_seed
        )
        
        # Step 5: Save stego video metadata
        print(f"\n[Step 5/5] Saving stego video metadata...")
        
        stego_metadata = {
            'video_path': video_path,
            'video_hash': video_hash,
            'message_length': len(message),
            'chaos_seed': chaos_seed,
            'proof_size': len(proof_bytes),
            'embedding_info': embedding_info,
            'original_mvs': mv_dicts,  # Original MVs for extraction
            'modified_mvs': modified_mv_data,
            'verification': {
                'public_video_hash': video_hash,
                'carriers_used': embedding_info['carriers_used'],
                'modification_rate': embedding_info['carriers_used'] / len(mv_dicts)
            }
        }
        
        Path(output_json).parent.mkdir(parents=True, exist_ok=True)
        with open(output_json, 'w') as f:
            json.dump(stego_metadata, f, indent=2)
        
        print(f"  Saved to: {output_json}")
        
        # Step 6: Create stego video file (optional)
        if output_video:
            print(f"\n[Step 6/6] Creating stego video file...")
            try:
                from ..encoder import H264VideoEncoder
                
                encoder = H264VideoEncoder(
                    input_video=video_path,
                    output_video=output_video
                )
                
                # Pass embedding_info to encoder for sidecar metadata
                encoding_result = encoder.write_stego_video(
                    modified_mvs=modified_mv_data,
                    method='enhanced',  # Use enhanced encoding
                    embedding_info=embedding_info  # Pass embedding info
                )
                
                print(f"  Stego video created: {output_video}")
                print(f"  Size: {encoding_result['output_size']:,} bytes")
                print(f"  Method: {encoding_result['method']}")
                if 'note' in encoding_result:
                    print(f"  Note: {encoding_result['note']}")
                
                stego_metadata['stego_video'] = output_video
                stego_metadata['encoding_result'] = encoding_result
                
                # Update JSON with video path
                with open(output_json, 'w') as f:
                    json.dump(stego_metadata, f, indent=2)
                    
            except ImportError as e:
                print(f"  [WARNING] Video encoder not available: {e}")
                print(f"  [INFO] Metadata saved without video file")
            except Exception as e:
                print(f"  [ERROR] Video encoding failed: {e}")
                print(f"  [INFO] Metadata saved without video file")
                import traceback
                traceback.print_exc()
        
        # Summary
        print(f"\n{'='*80}")
        print("EMBEDDING SUMMARY")
        print(f"{'='*80}")
        print(f"Message:           {len(message)} chars (secret)")
        print(f"Proof size:        {len(proof_bytes)} bytes")
        print(f"Total MVs:         {len(mv_dicts)}")
        print(f"Carriers used:     {embedding_info['carriers_used']}")
        print(f"Embedding rate:    {100*stego_metadata['verification']['modification_rate']:.2f}%")
        print(f"Avg modification:  {embedding_info['avg_modification']:.2f} pixels")
        if output_video:
            print(f"Stego video:       {output_video}")
        print(f"\n{'='*80}")
        print("[OK] PROOF SUCCESSFULLY EMBEDDED INTO VIDEO")
        print(f"{'='*80}\n")
        
        return stego_metadata
    
    def _compute_video_hash(self, video_path: str) -> str:
        """Compute SHA256 hash of video file"""
        sha256 = hashlib.sha256()
        with open(video_path, 'rb') as f:
            while True:
                data = f.read(65536)  # 64KB chunks
                if not data:
                    break
                sha256.update(data)
        return sha256.hexdigest()
    
    def _generate_mock_proof(self, message: str, chaos_key: str, video_hash: str) -> bytes:
        """
        Generate mock proof for testing
        
        Mock proof structure (JSON):
        {
            "type": "mock_groth16",
            "message_hash": "...",
            "video_hash": "...",
            "timestamp": ...,
            "version": 1
        }
        """
        message_hash = hashlib.sha256(message.encode()).hexdigest()
        
        mock_proof = {
            "type": "mock_groth16_proof",
            "message_hash": message_hash,
            "video_hash": video_hash,
            "chaos_key_hash": hashlib.sha256(chaos_key.encode()).hexdigest(),
            "proof_version": 1,
            "note": "This is a mock proof for testing. Use generate_real_proof=True for production."
        }
        
        return json.dumps(mock_proof).encode('utf-8')


def main():
    """CLI interface for Video Prover"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Video Prover - Embed ZK Proofs into Video')
    parser.add_argument('--video', required=True, help='Input H.264 video')
    parser.add_argument('--message', required=True, help='Secret message')
    parser.add_argument('--key', required=True, help='Chaos key')
    parser.add_argument('--output', required=True, help='Output metadata JSON')
    parser.add_argument('--output-video', help='Output stego video file (optional)')
    parser.add_argument('--mock-proof', action='store_true', 
                       help='Use mock proof (testing only, NOT SECURE)')
    parser.add_argument('--circuit-dir', 
                       default='../../ImageLevel/circuits/compiled/build',
                       help='Path to circuit directory')
    
    args = parser.parse_args()
    
    # Create prover
    prover = VideoProver(circuit_dir=args.circuit_dir)
    
    # Embed proof (default: real proofs)
    result = prover.embed_with_proof(
        video_path=args.video,
        message=args.message,
        chaos_key=args.key,
        output_json=args.output,
        output_video=args.output_video,
        generate_real_proof=not args.mock_proof  # Real by default
    )
    
    print(f"\n[SUCCESS] Stego video metadata saved to: {args.output}")
    if args.output_video:
        print(f"[SUCCESS] Stego video file saved to: {args.output_video}")


if __name__ == '__main__':
    main()
