"""
Script để tạo stego image với ZK-SNARK
Có thể chạy độc lập để tạo ảnh trước khi benchmark
"""

import os
import sys
import io
from pathlib import Path

# Fix encoding for Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

try:
    import numpy as np
    from PIL import Image
    from zk_stego.hybrid_proof_artifact import HybridProofArtifact
    from zk_stego.metadata_message_generator import MetadataMessageGenerator
except ImportError as e:
    print(f"ERROR: Missing dependencies: {e}")
    print("Please install: pip install numpy Pillow")
    print("\nOr use a Python environment with these packages.")
    sys.exit(1)

def create_stego_image(original_path: str, output_dir: str = "benchmark_results", message: str = None):
    """Tạo stego image"""
    print("=" * 60)
    print("Creating Stego Image with ZK-SNARK")
    print("=" * 60)
    
    if not os.path.exists(original_path):
        print(f"ERROR: Image not found: {original_path}")
        return None, None
    
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    print(f"Loading image: {original_path}")
    original_img = Image.open(original_path)
    original_array = np.array(original_img)
    
    print(f"Image size: {original_array.shape}")
    
    if message is None:
        print("Generating message from metadata...")
        generator = MetadataMessageGenerator()
        message = generator.auto_generate_metadata_message(
            original_path,
            message_type="comprehensive"
        )
    
    print(f"Message length: {len(message)} characters")
    
    print("\nCreating ZK-SNARK proof and embedding...")
    hybrid = HybridProofArtifact()
    result = hybrid.embed_with_proof(
        original_array,
        message,
        chaos_key="benchmark_key"
    )
    
    if result is None:
        print("ERROR: Failed to create stego image")
        return None, None
    
    stego_image, proof_package = result
    
    original_output = output_path / "original_benchmark.png"
    stego_output = output_path / "stego_benchmark.png"
    
    original_img.save(original_output, "PNG")
    stego_image.save(stego_output, "PNG")
    
    # Embed proof into PNG chunk if proof was generated
    if proof_package:
        print("\nEmbedding ZK proof into PNG chunk...")
        hybrid_artifact = HybridProofArtifact()
        # Extract chaos parameters for embedding
        from zk_stego.chaos_embedding import generate_chaos_key_from_secret
        chaos_key_int = generate_chaos_key_from_secret("benchmark_key")
        
        # Get x0, y0 from proof package or extract from image
        x0 = proof_package.get('chaos_params', {}).get('x0', original_array.shape[1] // 2)
        y0 = proof_package.get('chaos_params', {}).get('y0', original_array.shape[0] // 2)
        
        # Embed proof using hybrid method
        proof_json = proof_package.get('proof', {})
        
        # Use actual public_inputs from proof_package if available
        actual_public_inputs = proof_package.get('public_inputs')
        if actual_public_inputs:
            # Convert public inputs list to dict format for embedding
            # Format: [commitmentRoot, proofLength, timestamp]
            public_json = {
            'positions': proof_package.get('chaos_params', {}).get('positions', []),
            'proof_length': proof_package.get('chaos_params', {}).get('proof_length', 0),
            'public_inputs': actual_public_inputs  # Store actual public inputs
        }
        else:
            public_json = {
                'positions': proof_package.get('chaos_params', {}).get('positions', []),
                'proof_length': proof_package.get('chaos_params', {}).get('proof_length', 0)
            }
        
        success = hybrid_artifact.embed_hybrid_proof(
            str(original_output),
            str(stego_output),
            proof_json,
            public_json,
            "benchmark_key",
            x0=x0,
            y0=y0
        )
        
        if success:
            print("[OK] ZK proof embedded into PNG chunk successfully")
        else:
            print("WARNING: Failed to embed proof into PNG chunk, but stego image created")
    
    original_size = os.path.getsize(original_output)
    stego_size = os.path.getsize(stego_output)
    
    print("\n" + "=" * 60)
    print("Results")
    print("=" * 60)
    print(f"Original: {original_output}")
    print(f"  Size: {original_size:,} bytes ({original_size/1024:.2f} KB)")
    print(f"Stego: {stego_output}")
    print(f"  Size: {stego_size:,} bytes ({stego_size/1024:.2f} KB)")
    print(f"Difference: {stego_size - original_size:,} bytes ({((stego_size - original_size) / original_size * 100):.2f}%)")
    print(f"ZK Proof: {'Generated' if proof_package else 'Failed'}")
    print("=" * 60)
    
    return str(original_output), str(stego_output)

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Create stego image with ZK-SNARK")
    parser.add_argument("image_path", help="Path to original image")
    parser.add_argument("-o", "--output-dir", default="benchmark_results", help="Output directory")
    parser.add_argument("-m", "--message", help="Message to embed (default: auto-generated)")
    
    args = parser.parse_args()
    
    orig, stego = create_stego_image(args.image_path, args.output_dir, args.message)
    
    if orig and stego:
        print(f"\nStego images created successfully!")
        print(f"Use these files for benchmark:")
        print(f"  python scripts/wireshark_benchmark_simple.py {orig} {stego}")
        sys.exit(0)
    else:
        print("\nFailed to create stego images")
        sys.exit(1)

