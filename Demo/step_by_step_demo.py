#!/usr/bin/env python3
"""
ZK-SNARK Steganography - Step by Step Demo
Hướng dẫn từng bước cơ bản về steganography với ZK-SNARK
"""

import os
import sys
import time
from datetime import datetime

# Add parent directory to path to import our modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.zk_stego.chaos_embedding import ChaosEmbedding
from src.zk_stego.metadata_message_generator import MetadataMessageGenerator

def print_step(step_num, title, description=""):
    """Print formatted step information"""
    print(f"\n{'='*60}")
    print(f"STEP {step_num}: {title}")
    print(f"{'='*60}")
    if description:
        print(f"📝 {description}")
    print()

def print_success(message):
    """Print success message"""
    print(f"✅ SUCCESS: {message}")

def print_info(message):
    """Print info message"""
    print(f"ℹ️  INFO: {message}")

def print_warning(message):
    """Print warning message"""
    print(f"⚠️  WARNING: {message}")

def main():
    """Main step-by-step demo function"""
    
    print("🎯 ZK-SNARK STEGANOGRAPHY - STEP BY STEP DEMO")
    print("=" * 60)
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Setup paths
    demo_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(demo_dir)
    test_images_dir = os.path.join(project_root, "examples", "testvectors")
    output_dir = os.path.join(demo_dir, "output")
    debug_dir = os.path.join(demo_dir, "debug")
    
    # Create output directories
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(debug_dir, exist_ok=True)
    
    print_step(1, "ENVIRONMENT SETUP", "Checking directories and test files")
    
    print_info(f"Demo directory: {demo_dir}")
    print_info(f"Project root: {project_root}")
    print_info(f"Test images: {test_images_dir}")
    print_info(f"Output directory: {output_dir}")
    
    # Check for test images
    if not os.path.exists(test_images_dir):
        print_warning("Test images directory not found!")
        return False
    
    test_images = [f for f in os.listdir(test_images_dir) 
                   if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
    
    if not test_images:
        print_warning("No test images found!")
        return False
    
    print_success(f"Found {len(test_images)} test images")
    for img in test_images[:3]:  # Show first 3
        print(f"  - {img}")
    
    print_step(2, "MESSAGE GENERATION", "Creating metadata message for embedding")
    
    # Initialize message generator
    msg_generator = MetadataMessageGenerator()
    
    # Generate a simple metadata message
    test_message = msg_generator.generate_processing_history_message(
        "Step-by-step demo test message - ZK-Stego Demo processing"
    )
    
    print_info(f"Generated message length: {len(test_message)} characters")
    print_info(f"Message preview: {test_message[:100]}...")
    print_success("Message generation completed")
    
    print_step(3, "CHAOS SYSTEM TESTING", "Testing chaos-based position generation")
    
    # Test the chaos system without image (just mathematical testing)
    from src.zk_stego.chaos_embedding import ChaosGenerator
    
    test_width, test_height = 512, 512  # Test dimensions
    chaos_gen = ChaosGenerator(test_width, test_height)
    
    print_info(f"Testing chaos system with dimensions: {test_width}x{test_height}")
    
    # Test Arnold Cat Map
    test_x, test_y = 100, 100
    iterations = 10
    
    new_x, new_y = chaos_gen.arnold_cat_map(test_x, test_y, iterations)
    print_info(f"Arnold Cat Map: ({test_x},{test_y}) -> ({new_x},{new_y}) after {iterations} iterations")
    
    # Test Logistic Map
    logistic_values = chaos_gen.logistic_map(0.5, 3.9, 20)
    print_info(f"Logistic Map sample: [{logistic_values[0]:.4f}, {logistic_values[1]:.4f}, ...]")
    print_info(f"Range: [{min(logistic_values):.4f}, {max(logistic_values):.4f}]")
    
    # Test position generation
    positions = chaos_gen.generate_positions(test_x, test_y, 12345, 10)
    print_info(f"Generated {len(positions)} chaos positions")
    print_success("Chaos system tested successfully")
    
    # Save debug info
    debug_file = os.path.join(debug_dir, f"chaos_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
    with open(debug_file, 'w') as f:
        f.write(f"Chaos Embedding Debug Info - {datetime.now()}\n")
        f.write("=" * 50 + "\n")
        f.write(f"Test dimensions: {test_width}x{test_height}\n")
        f.write(f"Arnold iterations: {iterations}\n")
        f.write(f"Logistic sample: {logistic_values[:5]}\n")
        f.write(f"Positions generated: {len(positions)}\n")
        f.write(f"Sample positions: {positions[:5]}\n")
    
    print_info(f"Debug info saved: {os.path.basename(debug_file)}")
    
    print_step(4, "IMAGE PROCESSING", "Embedding message into test image")
    
    # Select first available test image
    test_image = test_images[0]
    input_path = os.path.join(test_images_dir, test_image)
    # Use PNG format to preserve LSB data (WebP is lossy and corrupts steganography)
    output_filename = f"stego_{os.path.splitext(test_image)[0]}.png"
    output_path = os.path.join(output_dir, output_filename)
    
    print_info(f"Processing image: {test_image}")
    print_info(f"Input: {input_path}")
    print_info(f"Output: {output_path}")
    
    try:
        from PIL import Image
        import numpy as np
        
        start_time = time.time()
        
        # Load image for embedding
        image = Image.open(input_path)
        if image.mode != 'RGB':
            image = image.convert('RGB')
        image_array = np.array(image)
        
        # Initialize chaos embedder with image
        chaos_embedder = ChaosEmbedding(image_array)
        
        # Perform embedding  
        test_seed = "demo_secret_key"
        stego_image = chaos_embedder.embed_message(test_message, test_seed)
        
        # Save stego image as PNG to preserve LSB data
        stego_image.save(output_path, 'PNG')
        
        embedding_time = time.time() - start_time
        print_success(f"Message embedded successfully in {embedding_time:.4f} seconds")
        
        # Check file sizes
        original_size = os.path.getsize(input_path)
        stego_size = os.path.getsize(output_path)
        overhead = ((stego_size - original_size) / original_size) * 100
        
        print_info(f"Original size: {original_size:,} bytes")
        print_info(f"Stego size: {stego_size:,} bytes")
        print_info(f"Size overhead: {overhead:.2f}%")
            
    except Exception as e:
        print_warning(f"Error during embedding: {str(e)}")
        return False
    
    print_step(5, "MESSAGE EXTRACTION", "Retrieving embedded message")
    
    try:
        start_time = time.time()
        
        # Load stego image for extraction
        stego_image = Image.open(output_path)
        if stego_image.mode != 'RGB':
            stego_image = stego_image.convert('RGB')
        stego_array = np.array(stego_image)
        
        # Initialize chaos embedder with stego image
        chaos_extractor = ChaosEmbedding(stego_array)
        
        # Extract message
        extracted_message = chaos_extractor.extract_message(
            len(test_message), 
            test_seed
        )
        
        extraction_time = time.time() - start_time
        
        if extracted_message:
            print_success(f"Message extracted successfully in {extraction_time:.4f} seconds")
            
            # Verify message integrity
            if extracted_message == test_message:
                print_success("✨ MESSAGE INTEGRITY VERIFIED - Perfect match!")
            else:
                print_warning("Message integrity check failed")
                print_info(f"Original length: {len(test_message)}")
                print_info(f"Extracted length: {len(extracted_message)}")
                
                # Show differences if lengths match
                if len(extracted_message) == len(test_message):
                    differences = sum(1 for a, b in zip(test_message, extracted_message) if a != b)
                    print_info(f"Character differences: {differences}")
                else:
                    print_info("Length mismatch - cannot compare character by character")
                
        else:
            print_warning("Message extraction failed!")
            return False
            
    except Exception as e:
        print_warning(f"Error during extraction: {str(e)}")
        return False
    
    print_step(6, "DEMO SUMMARY", "Results and next steps")
    
    print("📊 STEP-BY-STEP DEMO RESULTS:")
    print(f"  ✅ Image processed: {test_image}")
    print(f"  ✅ Message length: {len(test_message)} characters")
    print(f"  ✅ Secret key: {test_seed}")
    print(f"  ✅ Embedding time: {embedding_time:.4f} seconds")
    print(f"  ✅ Extraction time: {extraction_time:.4f} seconds")
    print(f"  ✅ Size overhead: {overhead:.2f}%")
    print(f"  ✅ Message integrity: {'VERIFIED' if extracted_message == test_message else 'FAILED'}")
    print()
    
    print("📁 GENERATED FILES:")
    print(f"  - Stego image: {os.path.basename(output_path)}")
    print(f"  - Debug info: {os.path.basename(debug_file)}")
    print()
    
    print("🎯 NEXT STEPS:")
    print("  1. Run comprehensive_demo.py for detailed analysis")
    print("  2. Run performance_benchmark.py for thorough testing")
    print("  3. Try with your own images in examples/testvectors/")
    print("  4. Explore ZK-SNARK proof generation (advanced)")
    print()
    
    print_success("Step-by-Step Demo completed successfully!")
    print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    return True

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Demo interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ FATAL ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)