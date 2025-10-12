#!/usr/bin/env python3
"""
Comprehensive Demo Script for ZK-SNARK Steganography
Demonstrates step-by-step process with detailed logging and performance metrics
"""

import os
import sys
import time
import json
import logging
from datetime import datetime
from pathlib import Path

# Add src directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

def main():
    """Run comprehensive demo with logging"""
    
    # Setup directories
    demo_dir = Path(__file__).parent
    doc_dir = demo_dir / "doc"
    logs_dir = demo_dir / "logs"
    output_dir = demo_dir / "output"
    debug_dir = demo_dir / "debug"
    
    # Setup logging
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir / f"comprehensive_demo_{timestamp}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    
    logger = logging.getLogger('ComprehensiveDemo')
    
    # Performance metrics
    metrics = {
        "start_time": time.time(),
        "steps": [],
        "file_sizes": {}
    }
    
    logger.info("=" * 80)
    logger.info("ZK-SNARK STEGANOGRAPHY COMPREHENSIVE DEMO")
    logger.info("=" * 80)
    logger.info(f"Demo started at: {datetime.now()}")
    logger.info(f"Log file: {log_file}")
    
    try:
        # Step 1: Environment Check
        step_start = time.time()
        logger.info("\n" + "="*20 + " STEP 1: Environment Check " + "="*20)
        
        test_images_dir = demo_dir.parent / "examples" / "testvectors"
        images = list(test_images_dir.glob("*.png")) + list(test_images_dir.glob("*.webp"))
        
        if not images:
            logger.error("No test images found!")
            return
            
        test_image = images[0]
        logger.info(f"Using test image: {test_image.name}")
        logger.info(f"Image size: {test_image.stat().st_size:,} bytes")
        
        metrics["file_sizes"][test_image.name] = test_image.stat().st_size
        metrics["steps"].append({
            "name": "Environment Check",
            "duration": time.time() - step_start,
            "status": "success"
        })
        
        # Step 2: Import modules
        step_start = time.time()
        logger.info("\n" + "="*20 + " STEP 2: Import Modules " + "="*20)
        
        from zk_stego.chaos_embedding import ChaosEmbedding
        from PIL import Image
        import numpy as np
        
        logger.info("✅ All modules imported successfully")
        metrics["steps"].append({
            "name": "Import Modules", 
            "duration": time.time() - step_start,
            "status": "success"
        })
        
        # Step 3: Initialize Chaos Embedding
        step_start = time.time()
        logger.info("\n" + "="*20 + " STEP 3: Initialize Chaos Embedding " + "="*20)
        
        # Load image
        pil_image = Image.open(test_image)
        image_array = np.array(pil_image)
        logger.info(f"Image loaded: {pil_image.mode}, Shape: {image_array.shape}")
        
        # Initialize chaos embedding
        chaos_embedding = ChaosEmbedding(image_array)
        logger.info(f"Chaos embedding initialized: {chaos_embedding.width}x{chaos_embedding.height}")
        
        init_time = time.time() - step_start
        metrics["steps"].append({
            "name": "Initialize Chaos Embedding",
            "duration": init_time,
            "status": "success"
        })
        
        # Step 4: Prepare Message
        step_start = time.time()
        logger.info("\n" + "="*20 + " STEP 4: Prepare Message " + "="*20)
        
        message = "Hello ZK-SNARK Steganography! This is a comprehensive demo."
        logger.info(f"Message: '{message}'")
        logger.info(f"Message length: {len(message)} characters")
        logger.info(f"Message bits: {len(message) * 8} bits")
        
        metrics["steps"].append({
            "name": "Prepare Message",
            "duration": time.time() - step_start,
            "status": "success"
        })
        
        # Step 5: Embed Message
        step_start = time.time()
        logger.info("\n" + "="*20 + " STEP 5: Embed Message " + "="*20)
        
        stego_image = chaos_embedding.embed_message(message)
        embed_time = time.time() - step_start
        
        # Save stego image
        stego_file = output_dir / f"comprehensive_stego_{timestamp}.png"
        stego_image.save(stego_file)
        stego_size = stego_file.stat().st_size
        
        logger.info(f"✅ Message embedded in {embed_time:.4f} seconds")
        logger.info(f"Stego image saved: {stego_file.name}")
        logger.info(f"Stego size: {stego_size:,} bytes")
        
        size_overhead = stego_size - test_image.stat().st_size
        overhead_percent = (size_overhead / test_image.stat().st_size) * 100
        logger.info(f"Size overhead: {size_overhead:,} bytes ({overhead_percent:.2f}%)")
        
        metrics["file_sizes"][stego_file.name] = stego_size
        metrics["steps"].append({
            "name": "Embed Message",
            "duration": embed_time,
            "status": "success",
            "details": {
                "message_length": len(message),
                "size_overhead_bytes": size_overhead,
                "size_overhead_percent": overhead_percent
            }
        })
        
        # Step 6: Test Message Extraction
        step_start = time.time()
        logger.info("\n" + "="*20 + " STEP 6: Test Message Extraction " + "="*20)
        
        try:
            # Load stego image for extraction
            stego_pil = Image.open(stego_file)
            stego_array = np.array(stego_pil)
            
            # Initialize extractor
            extractor = ChaosEmbedding(stego_array)
            
            # Extract message
            extracted_message = extractor.extract_message(len(message))
            extract_time = time.time() - step_start
            
            logger.info(f"✅ Message extracted in {extract_time:.4f} seconds")
            logger.info(f"Original:  '{message}'")
            logger.info(f"Extracted: '{extracted_message}'")
            
            # Check if extraction was successful
            if extracted_message.strip() == message:
                logger.info("🎉 Message extraction successful!")
                extraction_status = "success"
            else:
                logger.warning("⚠️  Message extraction partial - some characters may differ")
                extraction_status = "partial"
                
            metrics["steps"].append({
                "name": "Extract Message",
                "duration": extract_time,
                "status": extraction_status,
                "details": {
                    "original_length": len(message),
                    "extracted_length": len(extracted_message),
                    "match": extracted_message.strip() == message
                }
            })
            
        except Exception as e:
            logger.error(f"❌ Message extraction failed: {e}")
            metrics["steps"].append({
                "name": "Extract Message",
                "duration": time.time() - step_start,
                "status": "failed",
                "error": str(e)
            })
        
        # Step 7: Generate Performance Report
        step_start = time.time()
        logger.info("\n" + "="*20 + " STEP 7: Generate Performance Report " + "="*20)
        
        total_runtime = time.time() - metrics["start_time"]
        
        # Create performance report
        report = {
            "demo_metadata": {
                "timestamp": datetime.now().isoformat(),
                "total_runtime_seconds": total_runtime,
                "python_version": sys.version,
                "test_image": test_image.name
            },
            "step_performance": metrics["steps"],
            "file_sizes": metrics["file_sizes"],
            "summary": {
                "total_steps": len(metrics["steps"]),
                "successful_steps": len([s for s in metrics["steps"] if s["status"] == "success"]),
                "failed_steps": len([s for s in metrics["steps"] if s["status"] == "failed"]),
                "avg_step_duration": sum(s["duration"] for s in metrics["steps"]) / len(metrics["steps"])
            }
        }
        
        # Save performance report
        report_file = doc_dir / f"comprehensive_report_{timestamp}.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
            
        logger.info(f"📊 Performance report saved: {report_file.name}")
        
        metrics["steps"].append({
            "name": "Generate Performance Report",
            "duration": time.time() - step_start,
            "status": "success"
        })
        
        # Final Summary
        logger.info("\n" + "="*60)
        logger.info("🎉 COMPREHENSIVE DEMO COMPLETED SUCCESSFULLY!")
        logger.info("="*60)
        logger.info(f"Total Runtime: {total_runtime:.4f} seconds")
        logger.info(f"Steps Completed: {report['summary']['successful_steps']}/{report['summary']['total_steps']}")
        logger.info(f"Average Step Duration: {report['summary']['avg_step_duration']:.4f} seconds")
        logger.info("")
        logger.info("Generated files:")
        logger.info(f"  📊 Performance report: {report_file.name}")
        logger.info(f"  🖼️  Stego image: {stego_file.name}")
        logger.info(f"  📝 Log file: {log_file.name}")
        
    except Exception as e:
        logger.error(f"Demo failed with error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise

if __name__ == "__main__":
    main()