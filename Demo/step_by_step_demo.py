#!/usr/bin/env python3
"""
Step-by-step ZK Steganography Demo
Simple demo with detailed debug output for each step
"""

import os
import sys
import time
import json
from datetime import datetime
from pathlib import Path

# Add src directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

def print_step(step_num, title):
    """Print formatted step header"""
    print(f"\n{'='*60}")
    print(f"STEP {step_num}: {title}")
    print(f"{'='*60}")
    print(f"Time: {datetime.now().strftime('%H:%M:%S')}")

def print_debug(label, value):
    """Print debug information"""
    print(f"🔍 DEBUG - {label}: {value}")

def print_result(success, message):
    """Print step result"""
    symbol = "✅" if success else "❌"
    print(f"{symbol} RESULT: {message}")

def save_debug_info(filename, data):
    """Save debug information to file"""
    debug_dir = Path(__file__).parent / "debug"
    debug_file = debug_dir / filename
    
    with open(debug_file, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"📝 Debug info saved to: {debug_file}")

def main():
    print("🚀 ZK-SNARK STEGANOGRAPHY STEP-BY-STEP DEMO")
    print(f"Started at: {datetime.now()}")
    
    # Step 1: Check Environment
    print_step(1, "Environment Check")
    
    demo_dir = Path(__file__).parent
    project_root = demo_dir.parent
    
    print_debug("Demo directory", demo_dir)
    print_debug("Project root", project_root)
    
    # Check test images
    test_images_dir = project_root / "examples" / "testvectors"
    images = list(test_images_dir.glob("*.png")) + list(test_images_dir.glob("*.webp"))
    
    print_debug("Test images directory", test_images_dir)
    print_debug("Found images", [img.name for img in images])
    
    if images:
        print_result(True, f"Found {len(images)} test images")
        test_image = images[0]
        print_debug("Selected image", test_image.name)
        print_debug("Image size", f"{test_image.stat().st_size} bytes")
    else:
        print_result(False, "No test images found!")
        return
    
    # Step 2: Import and Test Modules
    print_step(2, "Module Import Test")
    
    try:
        from zk_stego.chaos_embedding import ChaosEmbedding
        print_result(True, "ChaosEmbedding imported successfully")
    except ImportError as e:
        print_result(False, f"Failed to import ChaosEmbedding: {e}")
        return
    
    try:
        from zk_stego.hybrid_proof_artifact import HybridProofArtifact
        print_result(True, "HybridProofArtifact imported successfully")
    except ImportError as e:
        print_result(False, f"Failed to import HybridProofArtifact: {e}")
        # Continue without ZK proof for now
        HybridProofArtifact = None
    
    # Step 3: Initialize Chaos Embedding
    print_step(3, "Initialize Chaos Embedding")
    
    start_time = time.time()
    
    try:
        # Load image first
        from PIL import Image
        import numpy as np
        
        pil_image = Image.open(test_image)
        image_array = np.array(pil_image)
        
        print_debug("PIL image mode", pil_image.mode)
        print_debug("Image array shape", image_array.shape)
        
        chaos_embedding = ChaosEmbedding(image_array)
        init_time = time.time() - start_time
        
        print_debug("Initialization time", f"{init_time:.4f} seconds")
        print_debug("Image path", test_image)
        
        # Get image properties
        print_debug("Image dimensions", f"{chaos_embedding.width}x{chaos_embedding.height}")
        
        print_result(True, "Chaos embedding initialized")
        
        # Save debug info
        debug_data = {
            "image_path": str(test_image),
            "image_size": test_image.stat().st_size,
            "initialization_time": init_time,
            "timestamp": datetime.now().isoformat()
        }
        save_debug_info("chaos_embedding_init.json", debug_data)
        
    except Exception as e:
        print_result(False, f"Chaos embedding initialization failed: {e}")
        return
    
    # Step 4: Prepare Secret Message
    print_step(4, "Prepare Secret Message")
    
    message = "Hello ZK World!"
    binary_message = ''.join(format(ord(char), '08b') for char in message)
    
    print_debug("Original message", f"'{message}'")
    print_debug("Message length", f"{len(message)} characters")
    print_debug("Binary representation", binary_message[:50] + "..." if len(binary_message) > 50 else binary_message)
    print_debug("Binary length", f"{len(binary_message)} bits")
    
    print_result(True, "Secret message prepared")
    
    # Step 5: Embed Message
    print_step(5, "Message Embedding")
    
    start_time = time.time()
    
    try:
        stego_image = chaos_embedding.embed_message(message)
        embed_time = time.time() - start_time
        
        print_debug("Embedding time", f"{embed_time:.4f} seconds")
        
        # Save stego image
        output_dir = demo_dir / "output"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        stego_file = output_dir / f"stego_image_{timestamp}.png"
        
        stego_image.save(stego_file)
        stego_size = stego_file.stat().st_size
        
        print_debug("Stego image saved to", stego_file.name)
        print_debug("Stego image size", f"{stego_size} bytes")
        print_debug("Size difference", f"{stego_size - test_image.stat().st_size} bytes")
        
        print_result(True, "Message embedded successfully")
        
        # Save debug info
        debug_data = {
            "original_image": str(test_image),
            "stego_image": str(stego_file),
            "message": message,
            "embedding_time": embed_time,
            "original_size": test_image.stat().st_size,
            "stego_size": stego_size,
            "size_difference": stego_size - test_image.stat().st_size,
            "timestamp": datetime.now().isoformat()
        }
        save_debug_info("message_embedding.json", debug_data)
        
    except Exception as e:
        print_result(False, f"Message embedding failed: {e}")
        return
    
    # Step 6: ZK Proof Generation (if available)
    if HybridProofArtifact:
        print_step(6, "ZK Proof Generation")
        
        try:
            hybrid_proof = HybridProofArtifact()
            print_debug("ZK proof system", "Initialized")
            
            start_time = time.time()
            proof_data = hybrid_proof.generate_proof(str(stego_file), message)
            proof_time = time.time() - start_time
            
            print_debug("Proof generation time", f"{proof_time:.4f} seconds")
            
            # Save proof
            proof_file = output_dir / f"zk_proof_{timestamp}.json"
            with open(proof_file, 'w') as f:
                json.dump(proof_data, f, indent=2)
            
            print_debug("Proof saved to", proof_file.name)
            print_debug("Proof file size", f"{proof_file.stat().st_size} bytes")
            
            print_result(True, "ZK proof generated successfully")
            
            # Step 7: Proof Verification
            print_step(7, "ZK Proof Verification")
            
            start_time = time.time()
            verification_result = hybrid_proof.verify_proof(proof_data)
            verify_time = time.time() - start_time
            
            print_debug("Verification time", f"{verify_time:.4f} seconds")
            print_debug("Verification result", verification_result)
            
            if verification_result:
                print_result(True, "ZK proof verification successful!")
            else:
                print_result(False, "ZK proof verification failed!")
            
            # Save verification debug info
            debug_data = {
                "proof_file": str(proof_file),
                "verification_result": verification_result,
                "proof_generation_time": proof_time,
                "verification_time": verify_time,
                "timestamp": datetime.now().isoformat()
            }
            save_debug_info("zk_proof_verification.json", debug_data)
            
        except Exception as e:
            print_result(False, f"ZK proof process failed: {e}")
    else:
        print_step(6, "ZK Proof Generation")
        print_result(False, "ZK proof system not available - skipping")
    
    # Final Summary
    print(f"\n{'='*60}")
    print("🎉 DEMO COMPLETED!")
    print(f"{'='*60}")
    print(f"Completed at: {datetime.now()}")
    print(f"\nGenerated files:")
    print(f"  📁 Output: {output_dir}")
    print(f"  📁 Debug: {demo_dir / 'debug'}")
    print(f"  📁 Logs: {demo_dir / 'logs'}")
    print(f"  📁 Documentation: {demo_dir / 'doc'}")

if __name__ == "__main__":
    main()