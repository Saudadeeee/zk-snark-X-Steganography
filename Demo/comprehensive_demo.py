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

from zk_stego.chaos_embedding import ChaosEmbedding
from zk_stego.hybrid_proof_artifact import HybridProofArtifact

class ZKStegoDemo:
    def __init__(self):
        self.demo_dir = Path(__file__).parent
        self.doc_dir = self.demo_dir / "doc"
        self.logs_dir = self.demo_dir / "logs"
        self.output_dir = self.demo_dir / "output"
        self.debug_dir = self.demo_dir / "debug"
        
        # Setup logging
        self.setup_logging()
        
        # Performance metrics
        self.metrics = {
            "start_time": time.time(),
            "steps": {},
            "memory_usage": [],
            "file_sizes": {}
        }
        
        self.logger.info("=" * 80)
        self.logger.info("ZK-SNARK STEGANOGRAPHY COMPREHENSIVE DEMO")
        self.logger.info("=" * 80)
        self.logger.info(f"Demo started at: {datetime.now()}")
        
    def setup_logging(self):
        """Setup comprehensive logging system"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.logs_dir / f"demo_log_{timestamp}.log"
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        )
        
        # Setup file handler
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        
        # Setup console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.INFO)
        
        # Setup logger
        self.logger = logging.getLogger('ZKStegoDemo')
        self.logger.setLevel(logging.DEBUG)
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        self.logger.info(f"Logging initialized. Log file: {log_file}")
        
    def step_timer(self, step_name):
        """Decorator for timing steps"""
        def decorator(func):
            def wrapper(*args, **kwargs):
                self.logger.info(f"\n{'='*20} STEP: {step_name} {'='*20}")
                start_time = time.time()
                
                try:
                    result = func(*args, **kwargs)
                    end_time = time.time()
                    duration = end_time - start_time
                    
                    self.metrics["steps"][step_name] = {
                        "duration": duration,
                        "status": "success",
                        "timestamp": datetime.now().isoformat()
                    }
                    
                    self.logger.info(f"✅ {step_name} completed in {duration:.4f} seconds")
                    return result
                    
                except Exception as e:
                    end_time = time.time()
                    duration = end_time - start_time
                    
                    self.metrics["steps"][step_name] = {
                        "duration": duration,
                        "status": "failed",
                        "error": str(e),
                        "timestamp": datetime.now().isoformat()
                    }
                    
                    self.logger.error(f"❌ {step_name} failed after {duration:.4f} seconds: {e}")
                    raise
                    
            return wrapper
        return decorator
    
    def setup_environment(self):
        """Setup and verify environment"""
        self.logger.info("Checking environment setup...")
        
        # Check required directories
        required_dirs = [
            "../examples/testvectors",
            "../circuits/compiled",
            "../artifacts/keys"
        ]
        
        for dir_path in required_dirs:
            full_path = self.demo_dir / dir_path
            if full_path.exists():
                self.logger.debug(f"✅ Directory exists: {full_path}")
            else:
                self.logger.error(f"❌ Missing directory: {full_path}")
                
        # Check for test images
        test_images_dir = self.demo_dir.parent / "examples" / "testvectors"
        images = list(test_images_dir.glob("*.png")) + list(test_images_dir.glob("*.webp"))
        
        self.logger.info(f"Found {len(images)} test images:")
        for img in images:
            size = img.stat().st_size
            self.logger.info(f"  - {img.name}: {size} bytes")
            self.metrics["file_sizes"][img.name] = size
            
        return images
        """Setup and verify environment"""
        self.logger.info("Checking environment setup...")
        
        # Check required directories
        required_dirs = [
            "../examples/testvectors",
            "../circuits/compiled",
            "../artifacts/keys"
        ]
        
        for dir_path in required_dirs:
            full_path = self.demo_dir / dir_path
            if full_path.exists():
                self.logger.debug(f"✅ Directory exists: {full_path}")
            else:
                self.logger.error(f"❌ Missing directory: {full_path}")
                
        # Check for test images
        test_images_dir = self.demo_dir.parent / "examples" / "testvectors"
        images = list(test_images_dir.glob("*.png")) + list(test_images_dir.glob("*.webp"))
        
        self.logger.info(f"Found {len(images)} test images:")
        for img in images:
            size = img.stat().st_size
            self.logger.info(f"  - {img.name}: {size} bytes")
            self.metrics["file_sizes"][img.name] = size
            
        return images
    
    def initialize_chaos_embedding(self, image_path):
        """Initialize chaos embedding system"""
        self.logger.info(f"Initializing chaos embedding for: {image_path}")
        
        # Debug: Print image details
        self.logger.debug(f"Image path: {image_path}")
        self.logger.debug(f"Image exists: {image_path.exists()}")
        self.logger.debug(f"Image size: {image_path.stat().st_size} bytes")
        
        # Load image as numpy array
        from PIL import Image
        import numpy as np
        
        pil_image = Image.open(image_path)
        image_array = np.array(pil_image)
        
        # Initialize chaos embedding
        chaos_embedding = ChaosEmbedding(image_array)
        
        # Debug: Print chaos parameters
        self.logger.debug("Chaos parameters:")
        self.logger.debug(f"  - Image dimensions: {chaos_embedding.width}x{chaos_embedding.height}")
        
        # Save debug info
        debug_info = {
            "image_path": str(image_path),
            "image_size_bytes": image_path.stat().st_size,
            "initialization_time": datetime.now().isoformat()
        }
        
        debug_file = self.debug_dir / f"chaos_init_{image_path.stem}.json"
        with open(debug_file, 'w') as f:
            json.dump(debug_info, f, indent=2)
            
        self.logger.info(f"Debug info saved to: {debug_file}")
        return chaos_embedding
    
    @step_timer("Generate Secret Message")
    def generate_secret_message(self):
        """Generate a secret message for embedding"""
        messages = [
            "Hello ZK-SNARK World!",
            "This is a secret message hidden using zero-knowledge proofs",
            "Chaos theory meets cryptography",
            "Privacy-preserving steganography demo"
        ]
        
        message = messages[0]  # Use first message for demo
        self.logger.info(f"Generated secret message: '{message}'")
        self.logger.debug(f"Message length: {len(message)} characters")
        self.logger.debug(f"Message bytes: {message.encode('utf-8')}")
        
        return message
    
    @step_timer("Embed Message")
    def embed_message(self, chaos_embedding, message):
        """Embed message using chaos-based steganography"""
        self.logger.info("Starting message embedding process...")
        
        # Convert message to binary
        binary_message = ''.join(format(ord(char), '08b') for char in message)
        self.logger.debug(f"Binary message: {binary_message}")
        self.logger.debug(f"Binary length: {len(binary_message)} bits")
        
        # Perform embedding
        stego_image = chaos_embedding.embed_message(message)
        
        # Save stego image
        output_file = self.output_dir / f"stego_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        stego_image.save(output_file)
        
        self.logger.info(f"Stego image saved to: {output_file}")
        self.metrics["file_sizes"][output_file.name] = output_file.stat().st_size
        
        # Debug: Compare original vs stego
        original_size = chaos_embedding.image_path
        stego_size = output_file.stat().st_size
        
        self.logger.debug(f"Size comparison:")
        self.logger.debug(f"  - Stego image size: {stego_size} bytes")
        self.logger.debug(f"  - Size difference: {stego_size - self.metrics['file_sizes'].get('original', 0)} bytes")
        
        return stego_image, output_file
    
    @step_timer("Initialize ZK Proof System")
    def initialize_zk_proof(self):
        """Initialize ZK proof artifact system"""
        self.logger.info("Initializing ZK proof system...")
        
        # Check for required circuit files
        circuit_dir = self.demo_dir.parent / "circuits" / "compiled"
        required_files = ["stego_check_v2.r1cs", "stego_check_v2.wasm"]
        
        for file_name in required_files:
            file_path = circuit_dir / "build" / "stego_check_v2_js" / file_name
            if not file_path.exists():
                file_path = circuit_dir / "build" / file_name
                
            if file_path.exists():
                self.logger.debug(f"✅ Found circuit file: {file_path}")
                self.metrics["file_sizes"][file_name] = file_path.stat().st_size
            else:
                self.logger.warning(f"⚠️  Circuit file not found: {file_name}")
        
        # Initialize hybrid proof artifact
        try:
            hybrid_proof = HybridProofArtifact()
            self.logger.info("✅ ZK proof system initialized successfully")
            return hybrid_proof
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize ZK proof system: {e}")
            raise
    
    @step_timer("Generate ZK Proof")
    def generate_zk_proof(self, hybrid_proof, stego_image_path, message):
        """Generate zero-knowledge proof"""
        self.logger.info("Generating zero-knowledge proof...")
        
        try:
            # Generate proof
            proof_data = hybrid_proof.generate_proof(str(stego_image_path), message)
            
            # Save proof
            proof_file = self.output_dir / f"proof_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(proof_file, 'w') as f:
                json.dump(proof_data, f, indent=2)
                
            self.logger.info(f"✅ ZK proof generated and saved to: {proof_file}")
            self.metrics["file_sizes"][proof_file.name] = proof_file.stat().st_size
            
            # Debug: Proof details
            self.logger.debug(f"Proof data keys: {list(proof_data.keys())}")
            
            return proof_data, proof_file
            
        except Exception as e:
            self.logger.error(f"❌ Failed to generate ZK proof: {e}")
            # Continue demo even if proof generation fails
            return None, None
    
    @step_timer("Verify ZK Proof")
    def verify_zk_proof(self, hybrid_proof, proof_data):
        """Verify the generated zero-knowledge proof"""
        if proof_data is None:
            self.logger.warning("⚠️  Skipping proof verification (no proof data)")
            return False
            
        self.logger.info("Verifying zero-knowledge proof...")
        
        try:
            verification_result = hybrid_proof.verify_proof(proof_data)
            
            if verification_result:
                self.logger.info("✅ ZK proof verification successful!")
            else:
                self.logger.error("❌ ZK proof verification failed!")
                
            return verification_result
            
        except Exception as e:
            self.logger.error(f"❌ Error during proof verification: {e}")
            return False
    
    @step_timer("Generate Performance Report")
    def generate_performance_report(self):
        """Generate comprehensive performance report"""
        self.logger.info("Generating performance report...")
        
        # Calculate total runtime
        total_runtime = time.time() - self.metrics["start_time"]
        self.metrics["total_runtime"] = total_runtime
        
        # Create performance report
        report = {
            "demo_metadata": {
                "timestamp": datetime.now().isoformat(),
                "total_runtime_seconds": total_runtime,
                "python_version": sys.version,
                "platform": sys.platform
            },
            "step_performance": self.metrics["steps"],
            "file_sizes": self.metrics["file_sizes"],
            "summary": {
                "total_steps": len(self.metrics["steps"]),
                "successful_steps": len([s for s in self.metrics["steps"].values() if s["status"] == "success"]),
                "failed_steps": len([s for s in self.metrics["steps"].values() if s["status"] == "failed"]),
                "avg_step_duration": sum(s["duration"] for s in self.metrics["steps"].values()) / len(self.metrics["steps"]) if self.metrics["steps"] else 0
            }
        }
        
        # Save performance report
        report_file = self.doc_dir / f"performance_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
            
        self.logger.info(f"📊 Performance report saved to: {report_file}")
        
        # Generate summary
        self.logger.info("\n" + "="*60)
        self.logger.info("DEMO PERFORMANCE SUMMARY")
        self.logger.info("="*60)
        self.logger.info(f"Total Runtime: {total_runtime:.4f} seconds")
        self.logger.info(f"Steps Completed: {report['summary']['successful_steps']}/{report['summary']['total_steps']}")
        self.logger.info(f"Average Step Duration: {report['summary']['avg_step_duration']:.4f} seconds")
        
        return report_file
    
    def run_demo(self):
        """Run the complete demo"""
        try:
            # Setup environment
            images = self.setup_environment()
            
            if not images:
                self.logger.error("No test images found. Demo cannot continue.")
                return
                
            # Use first available image
            test_image = images[0]
            self.logger.info(f"Using test image: {test_image}")
            
            # Initialize chaos embedding
            chaos_embedding = self.initialize_chaos_embedding(test_image)
            
            # Generate secret message
            message = self.generate_secret_message()
            
            # Embed message
            stego_image, stego_file = self.embed_message(chaos_embedding, message)
            
            # Initialize ZK proof system
            hybrid_proof = self.initialize_zk_proof()
            
            # Generate ZK proof
            proof_data, proof_file = self.generate_zk_proof(hybrid_proof, stego_file, message)
            
            # Verify ZK proof
            verification_result = self.verify_zk_proof(hybrid_proof, proof_data)
            
            # Generate performance report
            report_file = self.generate_performance_report()
            
            # Final summary
            self.logger.info("\n" + "="*80)
            self.logger.info("DEMO COMPLETED SUCCESSFULLY!")
            self.logger.info("="*80)
            self.logger.info("Generated files:")
            self.logger.info(f"  - Stego image: {stego_file if stego_file else 'N/A'}")
            self.logger.info(f"  - ZK proof: {proof_file if proof_file else 'N/A'}")
            self.logger.info(f"  - Performance report: {report_file}")
            self.logger.info(f"  - Debug logs: {self.logs_dir}")
            
        except Exception as e:
            self.logger.error(f"Demo failed with error: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            raise

if __name__ == "__main__":
    demo = ZKStegoDemo()
    demo.run_demo()