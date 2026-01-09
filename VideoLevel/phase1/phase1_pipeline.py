"""
Phase 1 Main Pipeline
=====================

End-to-end embedding and extraction pipeline.

Usage:
    # Embed payload into video
    python phase1_pipeline.py embed \
        --video data/encoded/foreman_cif_h264.mp4 \
        --payload "Secret message" \
        --output results/stego_video.json \
        --seed 12345
    
    # Extract payload from video
    python phase1_pipeline.py extract \
        --video data/encoded/foreman_cif_h264.mp4 \
        --input results/stego_video.json \
        --seed 12345
"""

import argparse
import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.mv_extractor import H264MVExtractor
from phase1.payload_encoder import EmbeddingConfig
from phase1.mv_embedder import MVEmbedder, MVExtractor


class Phase1Pipeline:
    """Main pipeline for Phase 1"""
    
    def __init__(self):
        """Initialize pipeline"""
        self.config = EmbeddingConfig(
            method='lsb_parity',
            component='mvx',
            min_magnitude=2.0,  # Stable filter
            max_magnitude=50.0,
            embedding_rate=0.2,
            ecc_enabled=True,
            ecc_redundancy=0.3
        )
    
    def embed_payload(self,
                     video_path: str,
                     payload: bytes,
                     chaos_seed: int,
                     output_path: str) -> dict:
        """
        Embed payload into video
        
        Args:
            video_path: Path to input H.264 video
            payload: Payload bytes to embed
            chaos_seed: Seed for carrier selection
            output_path: Path to save modified MV data
            
        Returns:
            Embedding info dictionary
        """
        print(f"\n{'='*80}")
        print("PHASE 1: PAYLOAD EMBEDDING")
        print(f"{'='*80}\n")
        
        # Step 1: Extract MVs from video
        print("[Step 1/4] Extracting motion vectors...")
        extractor = H264MVExtractor(video_path)
        extractor.extract_motion_vectors()
        mv_data = extractor.mv_data
        
        print(f"  Extracted {len(mv_data)} motion vectors")
        
        # Convert to dict format
        mv_dicts = []
        for mv in mv_data:
            mv_dicts.append({
                'frame_idx': mv.frame_idx,
                'frame_type': mv.frame_type,
                'timestamp': mv.timestamp,
                'mb_x': mv.src_x // 16,  # Convert to macroblock coords
                'mb_y': mv.src_y // 16,
                'mvx': mv.motion_x,
                'mvy': mv.motion_y,
                'block_type': f"{mv.w}x{mv.h}"
            })
        
        # Step 2: Embed payload
        print(f"\n[Step 2/4] Embedding payload...")
        print(f"  Payload size: {len(payload)} bytes")
        print(f"  Chaos seed: {chaos_seed}")
        
        embedder = MVEmbedder(self.config)
        modified_mv_data, embedding_info = embedder.embed(
            mv_dicts,
            payload,
            chaos_seed
        )
        
        # Step 3: Save modified MV data
        print(f"\n[Step 3/4] Saving modified MV data...")
        
        output_data = {
            'video_path': video_path,
            'chaos_seed': chaos_seed,
            'embedding_info': embedding_info,
            'modified_mvs': modified_mv_data,
            'original_mv_count': len(mv_dicts)
        }
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(output_data, f, indent=2)
        
        print(f"  Saved to: {output_path}")
        
        # Step 4: Summary
        print(f"\n[Step 4/4] Embedding summary:")
        print(f"  Original MVs:      {len(mv_dicts)}")
        print(f"  Modified MVs:      {embedding_info['carriers_used']}")
        print(f"  Modification rate: {100*embedding_info['carriers_used']/len(mv_dicts):.1f}%")
        print(f"  Payload embedded:  {embedding_info['payload_size']} bytes")
        print(f"  Total bits:        {embedding_info['bits_embedded']} bits")
        print(f"  Avg modification:  {embedding_info['avg_modification']:.2f} pixels")
        
        print(f"\n{'='*80}")
        print("[OK] EMBEDDING COMPLETED SUCCESSFULLY")
        print(f"{'='*80}\n")
        
        return embedding_info
    
    def extract_payload(self,
                       video_path: str,
                       stego_data_path: str,
                       chaos_seed: int) -> tuple:
        """
        Extract payload from video
        
        Args:
            video_path: Path to H.264 video
            stego_data_path: Path to modified MV data JSON
            chaos_seed: Seed for carrier selection (must match embedding)
            
        Returns:
            (payload, valid) tuple
        """
        print(f"\n{'='*80}")
        print("PHASE 1: PAYLOAD EXTRACTION")
        print(f"{'='*80}\n")
        
        # Step 1: Load stego data
        print("[Step 1/4] Loading stego data...")
        with open(stego_data_path, 'r') as f:
            stego_data = json.load(f)
        
        modified_mv_data = stego_data['modified_mvs']
        embedding_info = stego_data['embedding_info']
        
        print(f"  Loaded {len(modified_mv_data)} MVs")
        print(f"  Expected bits: {embedding_info['bits_embedded']}")
        
        # Step 2: Extract payload
        print(f"\n[Step 2/4] Extracting payload...")
        
        extractor = MVExtractor()
        payload, valid = extractor.extract(
            modified_mv_data,
            chaos_seed=chaos_seed,
            expected_bits=embedding_info['bits_embedded'],
            component=embedding_info['config']['component']
        )
        
        # Step 3: Verify
        print(f"\n[Step 3/4] Verification:")
        print(f"  Extraction valid: {valid}")
        if valid and payload:
            print(f"  Payload size: {len(payload)} bytes")
            print(f"  Expected size: {embedding_info['payload_size']} bytes")
            print(f"  Size match: {len(payload) == embedding_info['payload_size']}")
        
        # Step 4: Summary
        if valid:
            print(f"\n{'='*80}")
            print("[OK] EXTRACTION COMPLETED SUCCESSFULLY")
            print(f"{'='*80}\n")
        else:
            print(f"\n{'='*80}")
            print("[FAIL] EXTRACTION FAILED")
            print(f"{'='*80}\n")
        
        return payload, valid


def main():
    """Main CLI interface"""
    parser = argparse.ArgumentParser(
        description='Phase 1: MV-based Steganography Pipeline'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Embed command
    embed_parser = subparsers.add_parser('embed', help='Embed payload into video')
    embed_parser.add_argument('--video', required=True, help='Input H.264 video path')
    embed_parser.add_argument('--payload', required=True, help='Payload string or file path')
    embed_parser.add_argument('--output', required=True, help='Output JSON path')
    embed_parser.add_argument('--seed', type=int, default=12345, help='Chaos seed')
    
    # Extract command
    extract_parser = subparsers.add_parser('extract', help='Extract payload from video')
    extract_parser.add_argument('--video', required=True, help='Input H.264 video path')
    extract_parser.add_argument('--input', required=True, help='Stego data JSON path')
    extract_parser.add_argument('--seed', type=int, required=True, help='Chaos seed')
    
    # Test command
    test_parser = subparsers.add_parser('test', help='Run end-to-end test')
    test_parser.add_argument('--video', required=True, help='Input H.264 video path')
    
    args = parser.parse_args()
    
    if args.command == 'embed':
        # Load payload
        if Path(args.payload).exists():
            with open(args.payload, 'rb') as f:
                payload = f.read()
        else:
            payload = args.payload.encode('utf-8')
        
        # Embed
        pipeline = Phase1Pipeline()
        pipeline.embed_payload(
            args.video,
            payload,
            args.seed,
            args.output
        )
    
    elif args.command == 'extract':
        # Extract
        pipeline = Phase1Pipeline()
        payload, valid = pipeline.extract_payload(
            args.video,
            args.input,
            args.seed
        )
        
        if valid:
            print("\nRecovered payload:")
            print("-" * 80)
            try:
                print(payload.decode('utf-8'))
            except:
                print(f"<binary data: {len(payload)} bytes>")
            print("-" * 80)
    
    elif args.command == 'test':
        # Run end-to-end test
        print("Running end-to-end test...")
        
        test_payload = b"Hello ZK-SNARK Steganography! This is a test message for Phase 1."
        seed = 12345
        output_path = "results/phase1_test_stego.json"
        
        pipeline = Phase1Pipeline()
        
        # Embed
        pipeline.embed_payload(args.video, test_payload, seed, output_path)
        
        # Extract
        payload, valid = pipeline.extract_payload(args.video, output_path, seed)
        
        # Verify
        print("\n" + "="*80)
        print("END-TO-END TEST RESULT")
        print("="*80)
        print(f"Extraction valid: {valid}")
        print(f"Payload match: {payload == test_payload}")
        if payload:
            print(f"Original:  {test_payload}")
            print(f"Recovered: {payload}")
    
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
