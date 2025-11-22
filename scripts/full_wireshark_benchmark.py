"""
Full Wireshark Benchmark với ZK-SNARK Steganography
Tạo stego image thực tế và chạy benchmark với nhiều iterations
"""

import os
import sys
import time
import json
import subprocess
import tempfile
import threading
import http.server
import socketserver
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import statistics

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

try:
    import numpy as np
    from PIL import Image
    import matplotlib.pyplot as plt
    import pandas as pd
    from zk_stego.hybrid_proof_artifact import HybridProofArtifact
    from zk_stego.metadata_message_generator import MetadataMessageGenerator
except ImportError as e:
    print(f"ERROR: Missing dependencies: {e}")
    print("Please install: pip install numpy Pillow matplotlib pandas")
    sys.exit(1)

TSHARK_PATH = "D:\\Apps\\Wireshark\\tshark.exe"
INTERFACE = "\\Device\\NPF_Loopback"


class WiresharkCapture:
    """Capture network traffic với Wireshark"""
    
    def __init__(self, tshark_path: str = TSHARK_PATH):
        self.tshark_path = tshark_path
        self.capture_process = None
    
    def start_capture(self, output_file: str, filter_expr: str = "tcp port 8000") -> bool:
        """Bắt đầu capture"""
        try:
            cmd = [
                self.tshark_path,
                "-i", INTERFACE,
                "-f", filter_expr,
                "-w", output_file,
                "-q"
            ]
            self.capture_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            time.sleep(0.5)
            return self.capture_process.poll() is None
        except Exception as e:
            print(f"Warning: Could not start capture: {e}")
            return False
    
    def stop_capture(self):
        """Dừng capture"""
        if self.capture_process:
            self.capture_process.terminate()
            try:
                self.capture_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.capture_process.kill()
    
    def analyze_capture(self, pcap_file: str) -> Dict:
        """Phân tích captured traffic"""
        stats = {
            "packets": 0,
            "bytes": 0,
            "throughput_mbps": 0,
            "transfer_time": 0
        }
        
        if not os.path.exists(pcap_file) or os.path.getsize(pcap_file) == 0:
            return stats
        
        try:
            cmd = [
                self.tshark_path,
                "-r", pcap_file,
                "-T", "fields",
                "-e", "frame.number",
                "-e", "frame.len",
                "-e", "frame.time_epoch",
                "-E", "header=n",
                "-E", "separator=|"
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
                stats["packets"] = len(lines)
                
                total_bytes = 0
                times = []
                for line in lines:
                    parts = line.split('|')
                    if len(parts) >= 2:
                        try:
                            packet_bytes = int(parts[1]) if parts[1] else 0
                            total_bytes += packet_bytes
                            if len(parts) >= 3 and parts[2]:
                                times.append(float(parts[2]))
                        except (ValueError, IndexError):
                            pass
                
                stats["bytes"] = total_bytes
                
                if times and len(times) > 1:
                    total_time = max(times) - min(times)
                    if total_time > 0:
                        stats["throughput_mbps"] = (total_bytes * 8) / (total_time * 1_000_000)
                        stats["transfer_time"] = total_time
                elif total_bytes > 0:
                    # Estimate from file size
                    stats["transfer_time"] = (total_bytes * 8) / (10_000_000)  # Assume 10 Mbps
                    stats["throughput_mbps"] = (total_bytes * 8) / (stats["transfer_time"] * 1_000_000)
        except Exception as e:
            print(f"Warning: Error analyzing capture: {e}")
        
        return stats


class ImageServer:
    """HTTP server để serve ảnh"""
    
    def __init__(self, port: int = 8000):
        self.port = port
        self.server = None
        self.server_thread = None
        self.image_path = None
    
    def set_image(self, image_path: str):
        self.image_path = image_path
    
    def start(self):
        handler = self._create_handler()
        self.server = socketserver.TCPServer(("", self.port), handler)
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.daemon = True
        self.server_thread.start()
        time.sleep(0.5)
    
    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
    
    def _create_handler(self):
        class ImageHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                self.image_path = None
                super().__init__(*args, **kwargs)
            
            def do_GET(self):
                if self.path == '/image' or self.path.endswith('.png') or self.path.endswith('.webp'):
                    if hasattr(self, 'image_path') and self.image_path:
                        try:
                            with open(self.image_path, 'rb') as f:
                                image_data = f.read()
                            
                            self.send_response(200)
                            content_type = 'image/png' if self.image_path.endswith('.png') else 'image/webp'
                            self.send_header('Content-Type', content_type)
                            self.send_header('Content-Length', str(len(image_data)))
                            self.end_headers()
                            self.wfile.write(image_data)
                        except Exception as e:
                            self.send_error(500, f"Error: {e}")
                    else:
                        self.send_error(404, "Image not set")
                else:
                    self.send_error(404)
            
            def log_message(self, format, *args):
                pass
        
        handler_class = type('ImageHandler', (ImageHandler,), {})
        handler_class.image_path = self.image_path
        return handler_class


class FullBenchmark:
    """Full benchmark với ZK-SNARK steganography"""
    
    def __init__(self, output_dir: str = "benchmark_results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.capture = WiresharkCapture()
        self.server = ImageServer()
    
    def create_stego_image(self, original_image_path: str, message: str = None) -> Tuple[str, str]:
        """Tạo stego image với ZK-SNARK"""
        print("Creating stego image with ZK-SNARK...")
        
        original_img = Image.open(original_image_path)
        original_array = np.array(original_img)
        
        if message is None:
            generator = MetadataMessageGenerator()
            message = generator.auto_generate_metadata_message(
                original_image_path,
                message_type="comprehensive"
            )
        
        print(f"Message length: {len(message)} characters")
        
        hybrid = HybridProofArtifact()
        stego_image, proof_package = hybrid.embed_with_proof(
            original_array,
            message,
            chaos_key="benchmark_key"
        )
        
        if stego_image is None:
            raise ValueError("Failed to create stego image")
        
        original_temp = self.output_dir / "original_benchmark.png"
        stego_temp = self.output_dir / "stego_benchmark.png"
        
        original_img.save(original_temp, "PNG")
        stego_image.save(stego_temp, "PNG")
        
        original_size = os.path.getsize(original_temp)
        stego_size = os.path.getsize(stego_temp)
        
        print(f"Original: {original_size:,} bytes ({original_size/1024:.2f} KB)")
        print(f"Stego: {stego_size:,} bytes ({stego_size/1024:.2f} KB)")
        print(f"Difference: {stego_size - original_size:,} bytes ({((stego_size - original_size) / original_size * 100):.2f}%)")
        print(f"ZK Proof generated: {proof_package is not None}")
        
        return str(original_temp), str(stego_temp)
    
    def transfer_and_capture(self, image_path: str) -> Dict:
        """Transfer ảnh và capture traffic"""
        file_size = os.path.getsize(image_path)
        image_name = os.path.basename(image_path)
        
        self.server.set_image(image_path)
        self.server.start()
        
        with tempfile.NamedTemporaryFile(suffix='.pcap', delete=False) as f:
            pcap_file = f.name
        
        capture_started = self.capture.start_capture(pcap_file)
        
        time.sleep(0.5)
        
        try:
            import urllib.request
            start_time = time.time()
            urllib.request.urlopen(f"http://localhost:8000/{image_name}", timeout=10)
            transfer_time = time.time() - start_time
        except Exception as e:
            print(f"Warning: Transfer error: {e}")
            transfer_time = 0.1
        
        time.sleep(0.5)
        self.capture.stop_capture()
        self.server.stop()
        
        time.sleep(0.3)
        
        stats = self.capture.analyze_capture(pcap_file)
        stats["file_size"] = file_size
        stats["transfer_time"] = transfer_time
        
        if os.path.exists(pcap_file):
            os.unlink(pcap_file)
        
        return stats
    
    def run_benchmark(self, original_image_path: str, iterations: int = 5, message: str = None) -> Dict:
        """Chạy benchmark đầy đủ"""
        print("=" * 80)
        print("FULL WIRESHARK BENCHMARK WITH ZK-SNARK STEGANOGRAPHY")
        print("=" * 80)
        
        original_file, stego_file = self.create_stego_image(original_image_path, message)
        
        print(f"\nRunning {iterations} iterations for each image type...")
        
        original_results = []
        stego_results = []
        
        for i in range(iterations):
            print(f"\n--- Iteration {i+1}/{iterations} ---")
            
            print("\n[Original Image]")
            orig_stats = self.transfer_and_capture(original_file)
            original_results.append(orig_stats)
            print(f"  Packets: {orig_stats['packets']}, Bytes: {orig_stats['bytes']:,}, Time: {orig_stats['transfer_time']:.3f}s")
            
            time.sleep(1)
            
            print("\n[Stego Image]")
            stego_stats = self.transfer_and_capture(stego_file)
            stego_results.append(stego_stats)
            print(f"  Packets: {stego_stats['packets']}, Bytes: {stego_stats['bytes']:,}, Time: {stego_stats['transfer_time']:.3f}s")
            
            time.sleep(1)
        
        return self._aggregate_results(original_results, stego_results, original_file, stego_file)
    
    def _aggregate_results(self, original_results: List[Dict], stego_results: List[Dict], 
                          original_file: str, stego_file: str) -> Dict:
        """Tổng hợp kết quả"""
        
        def avg_stat(results: List[Dict], key: str) -> float:
            values = [r.get(key, 0) for r in results if key in r]
            return statistics.mean(values) if values else 0
        
        def std_stat(results: List[Dict], key: str) -> float:
            values = [r.get(key, 0) for r in results if key in r]
            return statistics.stdev(values) if len(values) > 1 else 0
        
        aggregated = {
            "timestamp": datetime.now().isoformat(),
            "original_image": {
                "file_path": original_file,
                "file_size": os.path.getsize(original_file),
                "avg_packets": avg_stat(original_results, "packets"),
                "std_packets": std_stat(original_results, "packets"),
                "avg_bytes": avg_stat(original_results, "bytes"),
                "std_bytes": std_stat(original_results, "bytes"),
                "avg_throughput": avg_stat(original_results, "throughput_mbps"),
                "std_throughput": std_stat(original_results, "throughput_mbps"),
                "avg_transfer_time": avg_stat(original_results, "transfer_time"),
                "std_transfer_time": std_stat(original_results, "transfer_time"),
                "raw_results": original_results
            },
            "stego_image": {
                "file_path": stego_file,
                "file_size": os.path.getsize(stego_file),
                "avg_packets": avg_stat(stego_results, "packets"),
                "std_packets": std_stat(stego_results, "packets"),
                "avg_bytes": avg_stat(stego_results, "bytes"),
                "std_bytes": std_stat(stego_results, "bytes"),
                "avg_throughput": avg_stat(stego_results, "throughput_mbps"),
                "std_throughput": std_stat(stego_results, "throughput_mbps"),
                "avg_transfer_time": avg_stat(stego_results, "transfer_time"),
                "std_transfer_time": std_stat(stego_results, "transfer_time"),
                "raw_results": stego_results
            }
        }
        
        orig = aggregated["original_image"]
        stego = aggregated["stego_image"]
        
        aggregated["comparison"] = {
            "file_size_diff_bytes": stego["file_size"] - orig["file_size"],
            "file_size_diff_percent": ((stego["file_size"] - orig["file_size"]) / orig["file_size"] * 100) if orig["file_size"] > 0 else 0,
            "packet_count_diff": stego["avg_packets"] - orig["avg_packets"],
            "packet_count_diff_percent": ((stego["avg_packets"] - orig["avg_packets"]) / orig["avg_packets"] * 100) if orig["avg_packets"] > 0 else 0,
            "throughput_diff": stego["avg_throughput"] - orig["avg_throughput"],
            "throughput_diff_percent": ((stego["avg_throughput"] - orig["avg_throughput"]) / orig["avg_throughput"] * 100) if orig["avg_throughput"] > 0 else 0,
            "transfer_time_diff": stego["avg_transfer_time"] - orig["avg_transfer_time"],
            "transfer_time_diff_percent": ((stego["avg_transfer_time"] - orig["avg_transfer_time"]) / orig["avg_transfer_time"] * 100) if orig["avg_transfer_time"] > 0 else 0
        }
        
        return aggregated
    
    def create_comparison_table(self, results: Dict) -> pd.DataFrame:
        """Tạo bảng so sánh"""
        orig = results["original_image"]
        stego = results["stego_image"]
        comp = results["comparison"]
        
        data = {
            "Metric": [
                "File Size (bytes)",
                "File Size (KB)",
                "Total Packets",
                "Total Bytes",
                "Throughput (Mbps)",
                "Transfer Time (seconds)"
            ],
            "Original Image": [
                f"{orig['file_size']:,}",
                f"{orig['file_size']/1024:.2f}",
                f"{orig['avg_packets']:.1f} ± {orig['std_packets']:.1f}",
                f"{orig['avg_bytes']:.0f} ± {orig['std_bytes']:.0f}",
                f"{orig['avg_throughput']:.3f} ± {orig['std_throughput']:.3f}",
                f"{orig['avg_transfer_time']:.3f} ± {orig['std_transfer_time']:.3f}"
            ],
            "Stego Image": [
                f"{stego['file_size']:,}",
                f"{stego['file_size']/1024:.2f}",
                f"{stego['avg_packets']:.1f} ± {stego['std_packets']:.1f}",
                f"{stego['avg_bytes']:.0f} ± {stego['std_bytes']:.0f}",
                f"{stego['avg_throughput']:.3f} ± {stego['std_throughput']:.3f}",
                f"{stego['avg_transfer_time']:.3f} ± {stego['std_transfer_time']:.3f}"
            ],
            "Difference": [
                f"{comp['file_size_diff_bytes']:+,} bytes",
                f"{comp['file_size_diff_percent']:+.2f}%",
                f"{comp['packet_count_diff']:+.1f} ({comp['packet_count_diff_percent']:+.2f}%)",
                f"{comp['throughput_diff']:+.3f} Mbps",
                f"{comp['throughput_diff_percent']:+.2f}%",
                f"{comp['transfer_time_diff']:+.3f} s ({comp['transfer_time_diff_percent']:+.2f}%)"
            ]
        }
        
        return pd.DataFrame(data)
    
    def create_line_plots(self, results: Dict, output_prefix: str = None):
        """Tạo biểu đồ đường"""
        if output_prefix is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_prefix = f"benchmark_{timestamp}"
        
        orig_results = results["original_image"]["raw_results"]
        stego_results = results["stego_image"]["raw_results"]
        
        iterations = list(range(1, len(orig_results) + 1))
        
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle('Network Performance Trends: Original vs Stego Image', 
                     fontsize=16, fontweight='bold')
        
        metrics = [
            ("Throughput (Mbps)", "throughput_mbps", "Mbps", axes[0, 0]),
            ("Transfer Time (s)", "transfer_time", "seconds", axes[0, 1]),
            ("Total Packets", "packets", "packets", axes[1, 0]),
            ("Total Bytes", "bytes", "bytes", axes[1, 1])
        ]
        
        for title, key, unit, ax in metrics:
            orig_values = [r.get(key, 0) for r in orig_results]
            stego_values = [r.get(key, 0) for r in stego_results]
            
            ax.plot(iterations, orig_values, marker='o', linewidth=2.5, 
                   label='Original', color='#2ecc71', markersize=10, alpha=0.8)
            ax.plot(iterations, stego_values, marker='s', linewidth=2.5, 
                   label='Stego', color='#e74c3c', markersize=10, alpha=0.8)
            
            ax.set_xlabel('Iteration', fontweight='bold', fontsize=11)
            ax.set_ylabel(unit, fontweight='bold', fontsize=11)
            ax.set_title(title, fontweight='bold', fontsize=12)
            ax.legend(fontsize=10)
            ax.grid(alpha=0.3, linestyle='--')
            ax.set_xticks(iterations)
            
            # Add value labels
            for i, (ov, sv) in enumerate(zip(orig_values, stego_values)):
                if i == 0 or i == len(iterations) - 1:  # Label first and last
                    ax.annotate(f'{ov:.2f}', (iterations[i], ov), 
                              textcoords="offset points", xytext=(0,10), 
                              ha='center', fontsize=8, color='#2ecc71')
                    ax.annotate(f'{sv:.2f}', (iterations[i], sv), 
                              textcoords="offset points", xytext=(0,-15), 
                              ha='center', fontsize=8, color='#e74c3c')
        
        plt.tight_layout()
        
        plot_file = self.output_dir / f"{output_prefix}_line_chart.png"
        plt.savefig(plot_file, dpi=300, bbox_inches='tight')
        print(f"\nLine chart saved to: {plot_file}")
        plt.close()
    
    def save_results(self, results: Dict, filename: str = None):
        """Lưu kết quả"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"full_benchmark_{timestamp}.json"
        
        filepath = self.output_dir / filename
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        return filepath


def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Full Wireshark Benchmark with ZK-SNARK Steganography"
    )
    parser.add_argument(
        "image_path",
        help="Path to original image file"
    )
    parser.add_argument(
        "-i", "--iterations",
        type=int,
        default=5,
        help="Number of test iterations (default: 5)"
    )
    parser.add_argument(
        "-m", "--message",
        help="Message to embed (default: auto-generated from metadata)",
        default=None
    )
    parser.add_argument(
        "-o", "--output-dir",
        default="benchmark_results",
        help="Output directory (default: benchmark_results)"
    )
    
    args = parser.parse_args()
    
    if not os.path.exists(args.image_path):
        print(f"ERROR: Image file not found: {args.image_path}")
        return 1
    
    benchmark = FullBenchmark(output_dir=args.output_dir)
    
    try:
        results = benchmark.run_benchmark(
            args.image_path,
            iterations=args.iterations,
            message=args.message
        )
        
        json_file = benchmark.save_results(results)
        
        print("\n" + "=" * 80)
        print("COMPARISON TABLE")
        print("=" * 80)
        df = benchmark.create_comparison_table(results)
        print(df.to_string(index=False))
        
        benchmark.create_line_plots(results)
        
        print("\n" + "=" * 80)
        print("BENCHMARK COMPLETED")
        print("=" * 80)
        print(f"Results JSON: {json_file}")
        print(f"Plots saved in: {benchmark.output_dir}")
        
    except KeyboardInterrupt:
        print("\nBenchmark interrupted by user")
        return 1
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

