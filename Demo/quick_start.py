#!/usr/bin/env python3
"""
Quick Start Demo - Minimal ZK Steganography Demo
Chạy nhanh để test cơ bản
"""

import os
import sys
from pathlib import Path
from datetime import datetime

def main():
    print("QUICK QUICK START - ZK Steganography Demo")
    print("=====================================")
    print(f"Time: {datetime.now().strftime('%H:%M:%S')}")
    print()
    
    # Check test image
    demo_dir = Path(__file__).parent
    test_images_dir = demo_dir.parent / "examples" / "testvectors"
    images = list(test_images_dir.glob("*.png")) + list(test_images_dir.glob("*.webp"))
    
    if not images:
        print("ERROR: No test images found!")
        print(f"   Please add images to: {test_images_dir}")
        return
    
    test_image = images[0]
    print(f"Using image: {test_image.name}")
    print(f"   Size: {test_image.stat().st_size:,} bytes")
    print()
    
    # Test import
    sys.path.append(str(demo_dir.parent / "src"))
    
    try:
        print("Testing imports...")
        from zk_stego.chaos_embedding import ChaosEmbedding
        print("   ChaosEmbedding imported")
        
        try:
            from zk_stego.hybrid_proof_artifact import HybridProofArtifact
            print("   HybridProofArtifact imported")
            zk_available = True
        except ImportError:
            print("   HybridProofArtifact not available")
            zk_available = False
            
    except ImportError as e:
        print(f"   ERROR: Import failed: {e}")
        return
    
    print()
    
    # Quick test with metadata message
    print("TESTING Quick functionality test...")
    
    try:
        # Initialize
        print(f"   Initializing with {test_image.name}...")
        
        from PIL import Image
        import numpy as np
        from zk_stego.metadata_message_generator import MetadataMessageGenerator
        
        pil_image = Image.open(test_image)
        cover_array = np.array(pil_image)
        
        # Generate metadata message instead of custom text
        metadata_gen = MetadataMessageGenerator()
        message = metadata_gen.generate_file_properties_message(str(test_image))
        print(f"   Generated metadata message: {len(message)} chars")
        
        chaos = ChaosEmbedding(cover_array)
        print("   Chaos embedding initialized")
        
        stego_image = chaos.embed_message(message, secret_key="file_integrity_key")
        print("   Metadata message embedded successfully")
        
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as stego_file:
            stego_image.save(stego_file.name, 'PNG')
            print(f"   Stego image saved: {stego_file.name}")
            
            if zk_available:
                try:
                    hybrid = HybridProofArtifact()
                    print("   ZK system initialized (circuit files may be needed for full proof)")
                except Exception as e:
                    print(f"   ZK initialization note: {e}")
        
        print("QUICK TEST COMPLETED SUCCESSFULLY!")
        print(f"Image dimensions: {cover_array.shape}")
        print(f"Metadata message type: File properties")
        print(f"Message length: {len(message)} characters")
        print(f"Message content: {message[:50]}..." if len(message) > 50 else f"Message content: {message}")
        print(f"Steganography: Metadata-based chaos embedding works")
        print(f"ZK Support: {'Available' if zk_available else 'Limited (circuit files needed)'}")
        
    except Exception as e:
        print()
        print(f"   ERROR: Test failed: {e}")
        print()
        print("Troubleshooting:")
        print("  • Check if test images exist in examples/testvectors/")
        print("  • Verify src/zk_stego modules are available")
        print("  • Run: python step_by_step_demo.py for detailed debug")

if __name__ == "__main__":
    main()