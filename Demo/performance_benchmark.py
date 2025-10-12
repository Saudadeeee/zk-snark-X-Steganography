#!/usr/bin/env python3
"""
Performance Benchmark Script for ZK Steganography
Measures performance across different image sizes and message lengths
"""

import os
import sys
import time
import json
import traceback
from datetime import datetime
from pathlib import Path
import matplotlib.pyplot as plt

# Add src directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

class PerformanceBenchmark:
    def __init__(self):
        self.demo_dir = Path(__file__).parent
        self.doc_dir = self.demo_dir / "doc"
        self.output_dir = self.demo_dir / "output"
        self.debug_dir = self.demo_dir / "debug"
        
        self.results = {
            "benchmark_info": {
                "timestamp": datetime.now().isoformat(),
                "python_version": sys.version,
                "platform": sys.platform
            },
            "test_cases": [],
            "summary": {}
        }
        
    def benchmark_embedding(self, image_path, message):
        """Benchmark message embedding process"""
        print(f"\n🔬 Benchmarking: {image_path.name} with message length {len(message)}")
        
        try:
            from zk_stego.chaos_embedding import ChaosEmbedding
            from PIL import Image
            import numpy as np
            
            # Load image as numpy array
            pil_image = Image.open(image_path)
            image_array = np.array(pil_image)
            
            # Initialize
            init_start = time.time()
            chaos_embedding = ChaosEmbedding(image_array)
            init_time = time.time() - init_start
            
            # Embed message
            embed_start = time.time()
            stego_image = chaos_embedding.embed_message(message)
            embed_time = time.time() - embed_start
            
            # Save stego image
            save_start = time.time()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            stego_file = self.output_dir / f"benchmark_stego_{image_path.stem}_{len(message)}_{timestamp}.png"
            stego_image.save(stego_file)
            save_time = time.time() - save_start
            
            # Calculate metrics
            original_size = image_path.stat().st_size
            stego_size = stego_file.stat().st_size
            size_overhead = stego_size - original_size
            size_overhead_percent = (size_overhead / original_size) * 100
            
            result = {
                "image_name": image_path.name,
                "image_size_bytes": original_size,
                "message_length": len(message),
                "message_bits": len(message) * 8,
                "times": {
                    "initialization": init_time,
                    "embedding": embed_time,
                    "saving": save_time,
                    "total": init_time + embed_time + save_time
                },
                "file_sizes": {
                    "original": original_size,
                    "stego": stego_size,
                    "overhead_bytes": size_overhead,
                    "overhead_percent": size_overhead_percent
                },
                "throughput": {
                    "bytes_per_second": original_size / (init_time + embed_time) if (init_time + embed_time) > 0 else 0,
                    "bits_per_second": (len(message) * 8) / embed_time if embed_time > 0 else 0
                },
                "status": "success",
                "timestamp": datetime.now().isoformat()
            }
            
            print(f"  ✅ Success - Total time: {result['times']['total']:.4f}s")
            print(f"     Embedding: {embed_time:.4f}s, Size overhead: {size_overhead_percent:.2f}%")
            
            return result
            
        except Exception as e:
            print(f"  ❌ Failed: {e}")
            
            result = {
                "image_name": image_path.name,
                "message_length": len(message),
                "status": "failed",
                "error": str(e),
                "traceback": traceback.format_exc(),
                "timestamp": datetime.now().isoformat()
            }
            
            return result
    
    def run_benchmark_suite(self):
        """Run comprehensive benchmark suite"""
        print("🚀 STARTING PERFORMANCE BENCHMARK SUITE")
        print(f"Timestamp: {datetime.now()}")
        
        # Find test images
        test_images_dir = self.demo_dir.parent / "examples" / "testvectors"
        images = list(test_images_dir.glob("*.png")) + list(test_images_dir.glob("*.webp"))
        
        if not images:
            print("❌ No test images found!")
            return
        
        print(f"Found {len(images)} test images: {[img.name for img in images]}")
        
        # Test messages of different lengths
        test_messages = [
            "Hi",  # 2 chars
            "Hello World!",  # 12 chars
            "This is a secret message for ZK steganography testing.",  # 56 chars
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 2,  # ~114 chars
            "A" * 200,  # 200 chars
        ]
        
        print(f"Testing {len(test_messages)} different message lengths")
        
        # Run benchmarks
        total_tests = len(images) * len(test_messages)
        current_test = 0
        
        for image in images:
            for i, message in enumerate(test_messages):
                current_test += 1
                print(f"\n[{current_test}/{total_tests}] Testing {image.name} with message #{i+1} ({len(message)} chars)")
                
                result = self.benchmark_embedding(image, message)
                self.results["test_cases"].append(result)
                
                # Small delay to prevent resource exhaustion
                time.sleep(0.1)
        
        # Generate summary statistics
        self.generate_summary()
        
        # Save results
        self.save_results()
        
        # Generate visualizations
        self.generate_visualizations()
        
        print(f"\n🎉 BENCHMARK COMPLETED!")
        print(f"Total tests: {total_tests}")
        print(f"Successful: {len([r for r in self.results['test_cases'] if r['status'] == 'success'])}")
        print(f"Failed: {len([r for r in self.results['test_cases'] if r['status'] == 'failed'])}")
    
    def generate_summary(self):
        """Generate summary statistics"""
        successful_tests = [r for r in self.results["test_cases"] if r["status"] == "success"]
        
        if not successful_tests:
            self.results["summary"] = {"error": "No successful tests to summarize"}
            return
        
        # Calculate averages
        avg_init_time = sum(r["times"]["initialization"] for r in successful_tests) / len(successful_tests)
        avg_embed_time = sum(r["times"]["embedding"] for r in successful_tests) / len(successful_tests)
        avg_total_time = sum(r["times"]["total"] for r in successful_tests) / len(successful_tests)
        avg_overhead_percent = sum(r["file_sizes"]["overhead_percent"] for r in successful_tests) / len(successful_tests)
        
        # Find min/max times
        min_total_time = min(r["times"]["total"] for r in successful_tests)
        max_total_time = max(r["times"]["total"] for r in successful_tests)
        
        # Calculate throughput
        avg_throughput_bps = sum(r["throughput"]["bytes_per_second"] for r in successful_tests) / len(successful_tests)
        avg_bit_rate = sum(r["throughput"]["bits_per_second"] for r in successful_tests) / len(successful_tests)
        
        self.results["summary"] = {
            "total_tests": len(self.results["test_cases"]),
            "successful_tests": len(successful_tests),
            "failed_tests": len(self.results["test_cases"]) - len(successful_tests),
            "average_times": {
                "initialization": avg_init_time,
                "embedding": avg_embed_time,
                "total": avg_total_time
            },
            "time_range": {
                "min_total": min_total_time,
                "max_total": max_total_time
            },
            "average_overhead_percent": avg_overhead_percent,
            "average_throughput": {
                "bytes_per_second": avg_throughput_bps,
                "bits_per_second": avg_bit_rate
            }
        }
        
        print(f"\n📊 BENCHMARK SUMMARY:")
        print(f"  Average embedding time: {avg_embed_time:.4f}s")
        print(f"  Average size overhead: {avg_overhead_percent:.2f}%")
        print(f"  Average throughput: {avg_throughput_bps:.0f} bytes/s")
    
    def save_results(self):
        """Save benchmark results to file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_file = self.doc_dir / f"performance_benchmark_{timestamp}.json"
        
        with open(results_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        
        print(f"📁 Results saved to: {results_file}")
        
        # Also save a CSV summary for easy analysis
        csv_file = self.doc_dir / f"performance_summary_{timestamp}.csv"
        
        with open(csv_file, 'w') as f:
            f.write("Image,Message_Length,Init_Time,Embed_Time,Total_Time,Size_Overhead_Percent,Status\n")
            
            for result in self.results["test_cases"]:
                if result["status"] == "success":
                    f.write(f"{result['image_name']},{result['message_length']},"
                           f"{result['times']['initialization']:.4f},"
                           f"{result['times']['embedding']:.4f},"
                           f"{result['times']['total']:.4f},"
                           f"{result['file_sizes']['overhead_percent']:.2f},"
                           f"{result['status']}\n")
                else:
                    f.write(f"{result['image_name']},{result['message_length']},"
                           f",,,,{result['status']}\n")
        
        print(f"📊 CSV summary saved to: {csv_file}")
    
    def generate_visualizations(self):
        """Generate performance visualization charts"""
        successful_tests = [r for r in self.results["test_cases"] if r["status"] == "success"]
        
        if not successful_tests:
            print("⚠️  No successful tests for visualization")
            return
        
        try:
            # Create performance charts
            fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 10))
            
            # Chart 1: Embedding time vs message length
            msg_lengths = [r["message_length"] for r in successful_tests]
            embed_times = [r["times"]["embedding"] for r in successful_tests]
            
            ax1.scatter(msg_lengths, embed_times, alpha=0.7)
            ax1.set_xlabel("Message Length (characters)")
            ax1.set_ylabel("Embedding Time (seconds)")
            ax1.set_title("Embedding Time vs Message Length")
            ax1.grid(True, alpha=0.3)
            
            # Chart 2: Size overhead vs message length
            size_overheads = [r["file_sizes"]["overhead_percent"] for r in successful_tests]
            
            ax2.scatter(msg_lengths, size_overheads, alpha=0.7, color='orange')
            ax2.set_xlabel("Message Length (characters)")
            ax2.set_ylabel("Size Overhead (%)")
            ax2.set_title("Size Overhead vs Message Length")
            ax2.grid(True, alpha=0.3)
            
            # Chart 3: Throughput vs image size
            image_sizes = [r["image_size_bytes"] for r in successful_tests]
            throughputs = [r["throughput"]["bytes_per_second"] for r in successful_tests]
            
            ax3.scatter(image_sizes, throughputs, alpha=0.7, color='green')
            ax3.set_xlabel("Image Size (bytes)")
            ax3.set_ylabel("Throughput (bytes/second)")
            ax3.set_title("Throughput vs Image Size")
            ax3.grid(True, alpha=0.3)
            
            # Chart 4: Total time breakdown
            images_tested = list(set(r["image_name"] for r in successful_tests))
            
            if len(images_tested) > 1:
                avg_times_by_image = {}
                for img in images_tested:
                    img_results = [r for r in successful_tests if r["image_name"] == img]
                    avg_times_by_image[img] = {
                        "init": sum(r["times"]["initialization"] for r in img_results) / len(img_results),
                        "embed": sum(r["times"]["embedding"] for r in img_results) / len(img_results),
                        "save": sum(r["times"]["saving"] for r in img_results) / len(img_results)
                    }
                
                images = list(avg_times_by_image.keys())
                init_times = [avg_times_by_image[img]["init"] for img in images]
                embed_times = [avg_times_by_image[img]["embed"] for img in images]
                save_times = [avg_times_by_image[img]["save"] for img in images]
                
                x = range(len(images))
                width = 0.25
                
                ax4.bar([i - width for i in x], init_times, width, label='Initialization', alpha=0.8)
                ax4.bar(x, embed_times, width, label='Embedding', alpha=0.8)
                ax4.bar([i + width for i in x], save_times, width, label='Saving', alpha=0.8)
                
                ax4.set_xlabel("Images")
                ax4.set_ylabel("Time (seconds)")
                ax4.set_title("Average Time Breakdown by Image")
                ax4.set_xticks(x)
                ax4.set_xticklabels([img[:10] + "..." if len(img) > 10 else img for img in images])
                ax4.legend()
                ax4.grid(True, alpha=0.3)
            else:
                ax4.text(0.5, 0.5, "Not enough data\nfor comparison", 
                        horizontalalignment='center', verticalalignment='center',
                        transform=ax4.transAxes, fontsize=12)
                ax4.set_title("Time Breakdown (Insufficient Data)")
            
            plt.tight_layout()
            
            # Save chart
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            chart_file = self.doc_dir / f"performance_charts_{timestamp}.png"
            plt.savefig(chart_file, dpi=300, bbox_inches='tight')
            plt.close()
            
            print(f"📈 Performance charts saved to: {chart_file}")
            
        except ImportError:
            print("⚠️  matplotlib not available - skipping visualization")
        except Exception as e:
            print(f"⚠️  Error generating visualization: {e}")

if __name__ == "__main__":
    benchmark = PerformanceBenchmark()
    benchmark.run_benchmark_suite()