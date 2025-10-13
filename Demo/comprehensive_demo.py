#!/usr/bin/env python3
"""
ZK-SNARK Steganography - Comprehensive Demo
Demo tổng hợp với logging chi tiết và phân tích đầy đủ
"""

import os
import sys
import time
import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

# Add parent directory to path to import our modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.zk_stego.chaos_embedding import ChaosEmbedding
from src.zk_stego.metadata_message_generator import MetadataMessageGenerator

class ComprehensiveDemo:
    """Comprehensive ZK-SNARK Steganography demonstration with detailed logging"""
    
    def __init__(self):
        self.demo_dir = os.path.dirname(os.path.abspath(__file__))
        self.project_root = os.path.dirname(self.demo_dir)
        self.test_images_dir = os.path.join(self.project_root, "examples", "testvectors")
        self.output_dir = os.path.join(self.demo_dir, "output")
        self.debug_dir = os.path.join(self.demo_dir, "debug")
        self.doc_dir = os.path.join(self.demo_dir, "doc")
        
        # Create directories
        for dir_path in [self.output_dir, self.debug_dir, self.doc_dir]:
            os.makedirs(dir_path, exist_ok=True)
        
        # Setup logging
        self.timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.log_file = os.path.join(self.debug_dir, f"comprehensive_demo_{self.timestamp}.log")
        self.setup_logging()
        
        # Initialize components
        self.msg_generator = MetadataMessageGenerator()
        # Note: chaos_embedder will be initialized per image
        
        # Results storage
        self.results = {
            'timestamp': self.timestamp,
            'tests': [],
            'summary': {},
            'errors': []
        }
    
    def setup_logging(self):
        """Setup detailed logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def log_section(self, title: str, description: str = ""):
        """Log section header"""
        separator = "=" * 60
        self.logger.info(separator)
        self.logger.info(f"SECTION: {title}")
        self.logger.info(separator)
        if description:
            self.logger.info(f"📝 {description}")
    
    def analyze_test_images(self) -> List[str]:
        """Analyze available test images"""
        self.log_section("TEST IMAGES ANALYSIS", "Scanning and analyzing available test images")
        
        if not os.path.exists(self.test_images_dir):
            self.logger.error(f"Test images directory not found: {self.test_images_dir}")
            return []
        
        # Find all image files
        image_extensions = ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff')
        images = []
        
        for file in os.listdir(self.test_images_dir):
            if file.lower().endswith(image_extensions):
                file_path = os.path.join(self.test_images_dir, file)
                file_size = os.path.getsize(file_path)
                
                images.append(file)
                self.logger.info(f"Found image: {file} ({file_size:,} bytes)")
        
        self.logger.info(f"Total images found: {len(images)}")
        return images
    
    def generate_test_messages(self) -> List[Dict[str, Any]]:
        """Generate various test messages"""
        self.log_section("MESSAGE GENERATION", "Creating different types of metadata messages")
        
        messages = []
        
        # 1. Simple file properties
        simple_msg = self.msg_generator.generate_file_properties_message(
            os.path.join(self.test_images_dir, "Lenna_test_image.webp")
        )
        messages.append({
            'type': 'File Properties',
            'content': simple_msg,
            'length': len(simple_msg),
            'description': 'Basic file properties metadata'
        })
        
        # 2. Processing history
        extended_msg = self.msg_generator.generate_processing_history_message(
            "Comprehensive demo steganography test with chaos embedding algorithm"
        )
        messages.append({
            'type': 'Processing History',
            'content': extended_msg,
            'length': len(extended_msg),
            'description': 'Detailed processing information'
        })
        
        # 3. JSON structured data
        json_data = {
            "demo_info": {
                "version": "1.0.0",
                "timestamp": datetime.now().isoformat(),
                "test_type": "comprehensive"
            },
            "parameters": {
                "chaos_seed": 0.5,
                "embedding_strength": 0.1,
                "verification_enabled": True
            },
            "metadata": {
                "author": "ZK-Stego Framework",
                "purpose": "Comprehensive testing",
                "expected_results": "Full verification"
            }
        }
        json_msg = json.dumps(json_data, separators=(',', ':'))
        messages.append({
            'type': 'JSON Structured',
            'content': json_msg,
            'length': len(json_msg),
            'description': 'Structured JSON data'
        })
        
        # 4. Comprehensive metadata
        long_msg = self.msg_generator.auto_generate_metadata_message(
            os.path.join(self.test_images_dir, "Lenna_test_image.webp"),
            message_type="comprehensive"
        )
        messages.append({
            'type': 'Comprehensive Metadata',
            'content': long_msg,
            'length': len(long_msg),
            'description': 'Comprehensive combined information'
        })
        
        # Log message details
        for msg in messages:
            self.logger.info(f"Generated {msg['type']}: {msg['length']} chars - {msg['description']}")
        
        return messages
    
    def test_chaos_system(self) -> Dict[str, Any]:
        """Test and analyze chaos system behavior"""
        self.log_section("CHAOS SYSTEM ANALYSIS", "Testing chaos map behavior and properties")
        
        from src.zk_stego.chaos_embedding import ChaosGenerator
        
        test_results = {
            'seeds_tested': [],
            'statistics': {},
            'position_tests': {}
        }
        
        # Test with different image dimensions
        test_dimensions = [(256, 256), (512, 512), (1024, 1024)]
        test_keys = [12345, 54321, 98765]
        
        for width, height in test_dimensions:
            self.logger.info(f"Testing chaos system with dimensions: {width}x{height}")
            chaos_gen = ChaosGenerator(width, height)
            
            for chaos_key in test_keys:
                # Test position generation
                positions = chaos_gen.generate_positions(width//2, height//2, chaos_key, 100)
                
                # Calculate position statistics
                x_coords = [p[0] for p in positions]
                y_coords = [p[1] for p in positions]
                
                stats = {
                    'dimensions': f"{width}x{height}",
                    'chaos_key': chaos_key,
                    'positions_generated': len(positions),
                    'x_range': [min(x_coords), max(x_coords)],
                    'y_range': [min(y_coords), max(y_coords)],
                    'unique_positions': len(set(positions))
                }
                
                test_results['seeds_tested'].append(stats)
                self.logger.info(f"  Key {chaos_key}: Generated {len(positions)} unique positions")
                
        # Test logistic map directly
        chaos_gen = ChaosGenerator(512, 512)
        logistic_seq = chaos_gen.logistic_map(0.5, 3.9, 1000)
        
        test_results['statistics'] = {
            'logistic_min': min(logistic_seq),
            'logistic_max': max(logistic_seq),
            'logistic_mean': sum(logistic_seq) / len(logistic_seq),
            'chaos_quality': 'Good' if max(logistic_seq) > 0.8 and min(logistic_seq) < 0.2 else 'Needs improvement'
        }
        
        self.logger.info(f"Logistic Map - Range: [{test_results['statistics']['logistic_min']:.4f}, {test_results['statistics']['logistic_max']:.4f}]")
        self.logger.info(f"Chaos system quality: {test_results['statistics']['chaos_quality']}")
        
        return test_results
    
    def perform_embedding_tests(self, images: List[str], messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Perform comprehensive embedding tests"""
        self.log_section("EMBEDDING TESTS", "Testing steganography with different image-message combinations")
        
        test_results = []
        test_count = 0
        total_tests = len(images) * len(messages)
        
        for image_filename in images:
            for message_info in messages:
                test_count += 1
                self.logger.info(f"[{test_count}/{total_tests}] Testing {image_filename} with {message_info['type']}")
                
                # Setup paths
                input_path = os.path.join(self.test_images_dir, image_filename)
                # Use PNG format to preserve LSB data (WebP is lossy)
                base_filename = os.path.splitext(image_filename)[0]
                output_filename = f"stego_{message_info['type'].lower().replace(' ', '_')}_{base_filename}.png"
                output_path = os.path.join(self.output_dir, output_filename)
                
                test_result = {
                    'test_id': test_count,
                    'image': image_filename,
                    'message_type': message_info['type'],
                    'message_length': message_info['length'],
                    'input_path': input_path,
                    'output_path': output_path,
                    'timestamp': datetime.now().isoformat()
                }
                
                try:
                    from PIL import Image
                    import numpy as np
                    from src.zk_stego.chaos_embedding import ChaosEmbedding
                    
                    # Get original file info
                    original_size = os.path.getsize(input_path)
                    test_result['original_size'] = original_size
                    
                    # Perform embedding
                    self.logger.info(f"  Embedding message ({message_info['length']} chars)...")
                    start_time = time.time()
                    
                    # Load and prepare image
                    image = Image.open(input_path)
                    if image.mode != 'RGB':
                        image = image.convert('RGB')
                    image_array = np.array(image)
                    
                    # Initialize chaos embedder for this specific image
                    chaos_embedder = ChaosEmbedding(image_array)
                    
                    # Perform embedding
                    stego_image = chaos_embedder.embed_message(message_info['content'], "test_secret_key")
                    
                    # Save stego image as PNG to preserve LSB data
                    stego_image.save(output_path, 'PNG')
                    
                    embedding_time = time.time() - start_time
                    test_result['embedding_time'] = embedding_time
                    test_result['embedding_success'] = True
                    
                    if os.path.exists(output_path):
                        # Analyze stego image
                        stego_size = os.path.getsize(output_path)
                        size_overhead = ((stego_size - original_size) / original_size) * 100
                        
                        test_result['stego_size'] = stego_size
                        test_result['size_overhead'] = size_overhead
                        
                        self.logger.info(f"  ✅ Embedding successful: {embedding_time:.4f}s, overhead: {size_overhead:.2f}%")
                        
                        # Test extraction
                        self.logger.info(f"  Testing message extraction...")
                        extract_start = time.time()
                        
                        # Load stego image for extraction
                        stego_loaded = Image.open(output_path)
                        if stego_loaded.mode != 'RGB':
                            stego_loaded = stego_loaded.convert('RGB')
                        stego_array = np.array(stego_loaded)
                        
                        # Initialize extractor
                        chaos_extractor = ChaosEmbedding(stego_array)
                        
                        # Extract message
                        extracted_message = chaos_extractor.extract_message(
                            message_info['length'],
                            "test_secret_key"
                        )
                        
                        extraction_time = time.time() - extract_start
                        test_result['extraction_time'] = extraction_time
                        
                        if extracted_message:
                            # Verify message integrity
                            integrity_check = extracted_message == message_info['content']
                            test_result['extraction_success'] = True
                            test_result['message_integrity'] = integrity_check
                            
                            if integrity_check:
                                self.logger.info(f"  ✅ Extraction successful: {extraction_time:.4f}s, integrity: VERIFIED")
                            else:
                                if len(extracted_message) == len(message_info['content']):
                                    differences = sum(1 for a, b in zip(message_info['content'], extracted_message) if a != b)
                                    test_result['message_differences'] = differences
                                    self.logger.warning(f"  ⚠️ Message integrity failed: {differences} differences")
                                else:
                                    test_result['message_differences'] = abs(len(extracted_message) - len(message_info['content']))
                                    self.logger.warning(f"  ⚠️ Length mismatch: expected {len(message_info['content'])}, got {len(extracted_message)}")
                        else:
                            test_result['extraction_success'] = False
                            test_result['message_integrity'] = False
                            self.logger.error(f"  ❌ Message extraction failed")
                    else:
                        test_result['embedding_success'] = False
                        self.logger.error(f"  ❌ Stego image not created")
                
                except Exception as e:
                    test_result['error'] = str(e)
                    self.logger.error(f"  ❌ Test failed with error: {str(e)}")
                    self.results['errors'].append({
                        'test_id': test_count,
                        'error': str(e),
                        'timestamp': datetime.now().isoformat()
                    })
                
                test_results.append(test_result)
        
        return test_results
    
    def generate_comprehensive_report(self, test_results: List[Dict[str, Any]], chaos_results: Dict[str, Any]):
        """Generate comprehensive analysis report"""
        self.log_section("REPORT GENERATION", "Creating detailed analysis report")
        
        # Calculate summary statistics
        successful_tests = [t for t in test_results if t.get('embedding_success', False) and t.get('extraction_success', False)]
        failed_tests = [t for t in test_results if not (t.get('embedding_success', False) and t.get('extraction_success', False))]
        
        summary = {
            'total_tests': len(test_results),
            'successful_tests': len(successful_tests),
            'failed_tests': len(failed_tests),
            'success_rate': len(successful_tests) / len(test_results) * 100 if test_results else 0
        }
        
        if successful_tests:
            embedding_times = [t['embedding_time'] for t in successful_tests if 'embedding_time' in t]
            extraction_times = [t['extraction_time'] for t in successful_tests if 'extraction_time' in t]
            size_overheads = [t['size_overhead'] for t in successful_tests if 'size_overhead' in t]
            
            summary.update({
                'avg_embedding_time': sum(embedding_times) / len(embedding_times) if embedding_times else 0,
                'avg_extraction_time': sum(extraction_times) / len(extraction_times) if extraction_times else 0,
                'avg_size_overhead': sum(size_overheads) / len(size_overheads) if size_overheads else 0,
                'min_embedding_time': min(embedding_times) if embedding_times else 0,
                'max_embedding_time': max(embedding_times) if embedding_times else 0
            })
        
        # Create comprehensive report
        report = {
            'comprehensive_demo_report': {
                'metadata': {
                    'timestamp': self.timestamp,
                    'demo_version': '1.0.0',
                    'framework': 'ZK-SNARK Steganography',
                    'log_file': os.path.basename(self.log_file)
                },
                'summary': summary,
                'chaos_analysis': chaos_results,
                'detailed_results': test_results,
                'performance_metrics': {
                    'throughput_bytes_per_second': self.calculate_throughput(successful_tests),
                    'reliability_score': len(successful_tests) / len(test_results) if test_results else 0,
                    'efficiency_score': self.calculate_efficiency_score(successful_tests)
                }
            }
        }
        
        # Save JSON report
        report_file = os.path.join(self.doc_dir, f"comprehensive_report_{self.timestamp}.json")
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        self.logger.info(f"📄 Comprehensive report saved: {os.path.basename(report_file)}")
        
        # Save CSV summary
        csv_file = os.path.join(self.doc_dir, f"comprehensive_summary_{self.timestamp}.csv")
        self.save_csv_summary(test_results, csv_file)
        
        return report
    
    def calculate_throughput(self, successful_tests: List[Dict[str, Any]]) -> float:
        """Calculate average throughput in bytes per second"""
        if not successful_tests:
            return 0.0
        
        total_bytes = sum(t.get('original_size', 0) for t in successful_tests)
        total_time = sum(t.get('embedding_time', 0) for t in successful_tests)
        
        return total_bytes / total_time if total_time > 0 else 0.0
    
    def calculate_efficiency_score(self, successful_tests: List[Dict[str, Any]]) -> float:
        """Calculate efficiency score based on time and size overhead"""
        if not successful_tests:
            return 0.0
        
        # Normalize factors (lower is better)
        avg_time = sum(t.get('embedding_time', 0) for t in successful_tests) / len(successful_tests)
        avg_overhead = sum(t.get('size_overhead', 0) for t in successful_tests) / len(successful_tests)
        
        # Simple efficiency score (0-1, higher is better)
        time_score = max(0, 1 - (avg_time / 1.0))  # Assume 1 second is maximum acceptable
        overhead_score = max(0, 1 - (avg_overhead / 20.0))  # Assume 20% is maximum acceptable
        
        return (time_score + overhead_score) / 2
    
    def save_csv_summary(self, test_results: List[Dict[str, Any]], csv_file: str):
        """Save test results summary as CSV"""
        import csv
        
        fieldnames = [
            'test_id', 'image', 'message_type', 'message_length',
            'embedding_time', 'extraction_time', 'size_overhead',
            'embedding_success', 'extraction_success', 'message_integrity'
        ]
        
        with open(csv_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for result in test_results:
                row = {field: result.get(field, '') for field in fieldnames}
                writer.writerow(row)
        
        self.logger.info(f"📊 CSV summary saved: {os.path.basename(csv_file)}")
    
    def run_comprehensive_demo(self):
        """Run the complete comprehensive demo"""
        self.logger.info("🚀 STARTING COMPREHENSIVE ZK-SNARK STEGANOGRAPHY DEMO")
        self.logger.info(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            # 1. Analyze test images
            images = self.analyze_test_images()
            if not images:
                self.logger.error("No test images found. Cannot proceed.")
                return False
            
            # 2. Generate test messages
            messages = self.generate_test_messages()
            
            # 3. Test chaos system
            chaos_results = self.test_chaos_system()
            
            # 4. Perform embedding tests
            test_results = self.perform_embedding_tests(images, messages)
            
            # 5. Generate comprehensive report
            report = self.generate_comprehensive_report(test_results, chaos_results)
            
            # 6. Final summary
            self.log_section("DEMO COMPLETED", "Comprehensive demo finished successfully")
            
            summary = report['comprehensive_demo_report']['summary']
            self.logger.info("📊 FINAL SUMMARY:")
            self.logger.info(f"  Total tests: {summary['total_tests']}")
            self.logger.info(f"  Successful tests: {summary['successful_tests']}")
            self.logger.info(f"  Success rate: {summary['success_rate']:.1f}%")
            
            if 'avg_embedding_time' in summary:
                self.logger.info(f"  Average embedding time: {summary['avg_embedding_time']:.4f}s")
                self.logger.info(f"  Average size overhead: {summary['avg_size_overhead']:.2f}%")
            
            self.logger.info("📁 Generated files:")
            for file in os.listdir(self.doc_dir):
                if file.startswith(f"comprehensive"):
                    self.logger.info(f"  - doc/{file}")
            
            for file in os.listdir(self.output_dir):
                if file.startswith("stego_"):
                    self.logger.info(f"  - output/{file}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Comprehensive demo failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

def main():
    """Main function"""
    demo = ComprehensiveDemo()
    success = demo.run_comprehensive_demo()
    return success

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