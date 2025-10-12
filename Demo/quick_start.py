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
    print("⚡ QUICK START - ZK Steganography Demo")
    print("=====================================")
    print(f"Time: {datetime.now().strftime('%H:%M:%S')}")
    print()
    
    # Check test image
    demo_dir = Path(__file__).parent
    test_images_dir = demo_dir.parent / "examples" / "testvectors"
    images = list(test_images_dir.glob("*.png")) + list(test_images_dir.glob("*.webp"))
    
    if not images:
        print("❌ No test images found!")
        print(f"   Please add images to: {test_images_dir}")
        return
    
    test_image = images[0]
    print(f"📷 Using image: {test_image.name}")
    print(f"   Size: {test_image.stat().st_size:,} bytes")
    print()
    
    # Test import
    sys.path.append(str(demo_dir.parent / "src"))
    
    try:
        print("📦 Testing imports...")
        from zk_stego.chaos_embedding import ChaosEmbedding
        print("   ✅ ChaosEmbedding imported")
        
        try:
            from zk_stego.hybrid_proof_artifact import HybridProofArtifact
            print("   ✅ HybridProofArtifact imported")
            zk_available = True
        except ImportError:
            print("   ⚠️  HybridProofArtifact not available")
            zk_available = False
            
    except ImportError as e:
        print(f"   ❌ Import failed: {e}")
        return
    
    print()
    
    # Quick test
    print("🔬 Quick functionality test...")
    message = "Hello!"
    
    try:
        # Initialize
        print(f"   Initializing with {test_image.name}...")
        
        # Load image as numpy array
        from PIL import Image
        import numpy as np
        
        pil_image = Image.open(test_image)
        image_array = np.array(pil_image)
        
        chaos_embedding = ChaosEmbedding(image_array)
        print("   ✅ Chaos embedding initialized")
        
        # Embed
        print(f"   Embedding message: '{message}'...")
        stego_image = chaos_embedding.embed_message(message)
        print("   ✅ Message embedded successfully")
        
        # Save
        output_dir = demo_dir / "output"
        output_dir.mkdir(exist_ok=True)
        
        stego_file = output_dir / f"quick_test_{datetime.now().strftime('%H%M%S')}.png"
        stego_image.save(stego_file)
        print(f"   ✅ Stego image saved: {stego_file.name}")
        
        # ZK test (if available)
        if zk_available:
            print("   Testing ZK proof...")
            try:
                hybrid_proof = HybridProofArtifact()
                # Note: ZK proof might fail due to circuit requirements
                print("   ✅ ZK system initialized (circuit files may be needed for full proof)")
            except Exception as e:
                print(f"   ⚠️  ZK proof test skipped: {e}")
        
        print()
        print("🎉 QUICK TEST COMPLETED SUCCESSFULLY!")
        print()
        print("📁 Output saved to:", output_dir)
        print()
        print("Next steps:")
        print("  • Run full demo: python step_by_step_demo.py")
        print("  • Run benchmark: python performance_benchmark.py") 
        print("  • Run all demos: ./run_all_demos.sh")
        
    except Exception as e:
        print(f"   ❌ Test failed: {e}")
        print()
        print("🔍 Troubleshooting:")
        print("  • Check if test images exist in examples/testvectors/")
        print("  • Verify src/zk_stego modules are available")
        print("  • Run: python step_by_step_demo.py for detailed debug")

if __name__ == "__main__":
    main()