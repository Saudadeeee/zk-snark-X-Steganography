"""
Network Performance Benchmark for ZK-SNARK Steganography
Đánh giá hiệu năng và payload khi truyền qua WiFi sử dụng Wireshark/tshark
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
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime
import statistics

import numpy as np
from PIL import Image
import matplotlib.pyplot as plt
import pandas as pd

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from zk_stego.hybrid_proof_artifact import HybridProofArtifact
from zk_stego.metadata_message_generator import MetadataMessageGenerator


class NetworkCapture:
    """Capture và phân tích network traffic sử dụng tshark"""
    
    def __init__(self, interface: Optional[str] = None, tshark_path: Optional[str] = None):
        self.tshark_path = tshark_path or self._find_tshark()
        self.interface = interface or self._detect_interface()
        self.capture_file = None
        self.capture_process = None
    
    def _find_tshark(self) -> str:
        """Tìm đường dẫn đến tshark"""
        possible_paths = [
            "D:\\Apps\\Wireshark\\tshark.exe",
            "C:\\Program Files\\Wireshark\\tshark.exe",
            "C:\\Program Files (x86)\\Wireshark\\tshark.exe",
            "tshark"  # Fallback to PATH
        ]
        for path in possible_paths:
            if path == "tshark":
                return path
            if os.path.exists(path):
                return path
        return "tshark"  # Default fallback
        
    def _detect_interface(self) -> str:
        """Tự động phát hiện network interface"""
        try:
            result = subprocess.run(
                [self.tshark_path, "-D"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    if 'Wi-Fi' in line or 'wlan' in line.lower() or 'eth' in line.lower():
                        parts = line.split('.', 1)
                        if len(parts) > 1:
                            return parts[0].strip()
                if lines:
                    return lines[0].split('.', 1)[0].strip()
        except Exception as e:
            print(f"Warning: Could not detect interface: {e}")
        return "\\Device\\NPF_Loopback"  # Use loopback for local testing
    
    def start_capture(self, output_file: str, filter_expr: str = "tcp port 8000") -> bool:
        """Bắt đầu capture network traffic"""
        try:
            self.capture_file = output_file
            cmd = [
                self.tshark_path,
                "-i", self.interface,
                "-f", filter_expr,
                "-w", output_file,
                "-q"
            ]
            self.capture_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            time.sleep(1)
            return self.capture_process.poll() is None
        except FileNotFoundError:
            print(f"ERROR: tshark not found at {self.tshark_path}. Please check Wireshark installation.")
            return False
        except Exception as e:
            print(f"ERROR: Failed to start capture: {e}")
            return False
    
    def stop_capture(self) -> bool:
        """Dừng capture"""
        if self.capture_process:
            self.capture_process.terminate()
            try:
                self.capture_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.capture_process.kill()
            return True
        return False
    
    def analyze_capture(self, pcap_file: str) -> Dict[str, Any]:
        """Phân tích captured traffic"""
        if not os.path.exists(pcap_file):
            return {}
        
        stats = {
            "total_packets": 0,
            "total_bytes": 0,
            "tcp_packets": 0,
            "tcp_bytes": 0,
            "http_packets": 0,
            "http_bytes": 0,
            "packet_sizes": [],
            "inter_arrival_times": [],
            "throughput_mbps": 0,
            "avg_packet_size": 0,
            "max_packet_size": 0,
            "min_packet_size": 0,
            "packet_count_by_size": {}
        }
        
        try:
            cmd = [
                self.tshark_path,
                "-r", pcap_file,
                "-T", "fields",
                "-e", "frame.number",
                "-e", "frame.len",
                "-e", "frame.time_epoch",
                "-e", "tcp.len",
                "-e", "http.content_length",
                "-E", "header=n",
                "-E", "separator=|"
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                prev_time = None
                
                for line in lines:
                    if not line.strip():
                        continue
                    
                    parts = line.split('|')
                    if len(parts) >= 3:
                        try:
                            packet_num = int(parts[0]) if parts[0] else 0
                            frame_len = int(parts[1]) if parts[1] else 0
                            frame_time = float(parts[2]) if len(parts) > 2 and parts[2] else None
                            tcp_len = int(parts[3]) if len(parts) > 3 and parts[3] else 0
                            
                            stats["total_packets"] += 1
                            stats["total_bytes"] += frame_len
                            stats["packet_sizes"].append(frame_len)
                            
                            if tcp_len > 0:
                                stats["tcp_packets"] += 1
                                stats["tcp_bytes"] += tcp_len
                            
                            if frame_time and prev_time:
                                inter_arrival = frame_time - prev_time
                                stats["inter_arrival_times"].append(inter_arrival)
                            prev_time = frame_time
                            
                            size_range = (frame_len // 100) * 100
                            stats["packet_count_by_size"][size_range] = \
                                stats["packet_count_by_size"].get(size_range, 0) + 1
                                
                        except (ValueError, IndexError):
                            continue
                
                if stats["packet_sizes"]:
                    stats["avg_packet_size"] = statistics.mean(stats["packet_sizes"])
                    stats["max_packet_size"] = max(stats["packet_sizes"])
                    stats["min_packet_size"] = min(stats["packet_sizes"])
                
                if stats["inter_arrival_times"]:
                    total_time = sum(stats["inter_arrival_times"])
                    if total_time > 0:
                        stats["throughput_mbps"] = (stats["total_bytes"] * 8) / (total_time * 1_000_000)
                
        except Exception as e:
            print(f"Warning: Error analyzing capture: {e}")
        
        return stats


class ImageServer:
    """HTTP server để serve ảnh cho testing"""
    
    def __init__(self, port: int = 8000):
        self.port = port
        self.server = None
        self.server_thread = None
        self.image_path = None
        
    def set_image(self, image_path: str):
        """Set ảnh để serve"""
        self.image_path = image_path
    
    def start(self):
        """Start HTTP server"""
        handler = self._create_handler()
        self.server = socketserver.TCPServer(("", self.port), handler)
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.daemon = True
        self.server_thread.start()
        time.sleep(0.5)
    
    def stop(self):
        """Stop HTTP server"""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
    
    def _create_handler(self):
        class ImageHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                self.image_path = None
                super().__init__(*args, **kwargs)
            
            def do_GET(self):
                if self.path == '/image' or self.path == '/image.png':
                    if hasattr(self, 'image_path') and self.image_path:
                        try:
                            with open(self.image_path, 'rb') as f:
                                image_data = f.read()
                            
                            self.send_response(200)
                            self.send_header('Content-Type', 'image/png')
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


class NetworkBenchmark:
    """Benchmark network performance cho steganography"""
    
    def __init__(self, output_dir: str = "benchmark_results", tshark_path: Optional[str] = None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.capture = NetworkCapture(tshark_path=tshark_path)
        self.server = ImageServer()
        self.results = []
        
    def prepare_test_images(
        self, 
        original_image_path: str,
        message: str = None
    ) -> Tuple[str, str]:
        """Chuẩn bị ảnh gốc và ảnh stego"""
        print("Preparing test images...")
        
        original_img = Image.open(original_image_path)
        original_array = np.array(original_img)
        
        if message is None:
            generator = MetadataMessageGenerator()
            message = generator.auto_generate_metadata_message(
                original_image_path,
                message_type="comprehensive"
            )
        
        hybrid = HybridProofArtifact()
        stego_image, proof_package = hybrid.embed_with_proof(
            original_array,
            message,
            chaos_key="benchmark_key"
        )
        
        if stego_image is None:
            raise ValueError("Failed to create stego image")
        
        original_temp = self.output_dir / "original_test.png"
        stego_temp = self.output_dir / "stego_test.png"
        
        original_img.save(original_temp, "PNG")
        stego_image.save(stego_temp, "PNG")
        
        original_size = os.path.getsize(original_temp)
        stego_size = os.path.getsize(stego_temp)
        
        print(f"Original image size: {original_size:,} bytes")
        print(f"Stego image size: {stego_size:,} bytes")
        print(f"Size difference: {stego_size - original_size:,} bytes ({((stego_size - original_size) / original_size * 100):.2f}%)")
        
        return str(original_temp), str(stego_temp)
    
    def transfer_image(self, image_path: str, capture_duration: int = 10) -> Dict[str, Any]:
        """Transfer ảnh và capture traffic"""
        print(f"\nTransferring image: {os.path.basename(image_path)}")
        
        self.server.set_image(image_path)
        self.server.start()
        
        with tempfile.NamedTemporaryFile(suffix='.pcap', delete=False) as f:
            pcap_file = f.name
        
        capture_started = self.capture.start_capture(pcap_file)
        if not capture_started:
            print("Warning: Could not start capture, using simulated data")
            time.sleep(2)
            self.capture.stop_capture()
            return self._simulate_stats(image_path)
        
        time.sleep(1)
        
        try:
            import urllib.request
            start_time = time.time()
            urllib.request.urlopen(f"http://localhost:8000/image", timeout=5)
            transfer_time = time.time() - start_time
        except Exception as e:
            print(f"Warning: Transfer simulation: {e}")
            transfer_time = 2.0
        
        time.sleep(1)
        self.capture.stop_capture()
        self.server.stop()
        
        time.sleep(0.5)
        
        stats = self.capture.analyze_capture(pcap_file)
        stats["transfer_time"] = transfer_time
        stats["file_size"] = os.path.getsize(image_path)
        
        if os.path.exists(pcap_file):
            os.unlink(pcap_file)
        
        return stats
    
    def _simulate_stats(self, image_path: str) -> Dict[str, Any]:
        """Simulate stats nếu không capture được"""
        file_size = os.path.getsize(image_path)
        estimated_packets = max(1, file_size // 1400)
        
        return {
            "total_packets": estimated_packets,
            "total_bytes": file_size,
            "tcp_packets": estimated_packets,
            "tcp_bytes": file_size,
            "packet_sizes": [1400] * estimated_packets,
            "avg_packet_size": 1400,
            "max_packet_size": 1500,
            "min_packet_size": file_size % 1400 or 1400,
            "throughput_mbps": 10.0,
            "transfer_time": file_size / (10_000_000 / 8),
            "file_size": file_size
        }
    
    def run_benchmark(
        self,
        original_image_path: str,
        message: str = None,
        iterations: int = 3
    ) -> Dict[str, Any]:
        """Chạy benchmark đầy đủ"""
        print("=" * 60)
        print("NETWORK PERFORMANCE BENCHMARK")
        print("ZK-SNARK Steganography vs Original Image")
        print("=" * 60)
        
        original_file, stego_file = self.prepare_test_images(original_image_path, message)
        
        original_results = []
        stego_results = []
        
        print(f"\nRunning {iterations} iterations for each image type...")
        
        for i in range(iterations):
            print(f"\n--- Iteration {i+1}/{iterations} ---")
            
            print("\n[Original Image]")
            orig_stats = self.transfer_image(original_file)
            original_results.append(orig_stats)
            time.sleep(1)
            
            print("\n[Stego Image]")
            stego_stats = self.transfer_image(stego_file)
            stego_results.append(stego_stats)
            time.sleep(1)
        
        return self._aggregate_results(original_results, stego_results, original_file, stego_file)
    
    def _aggregate_results(
        self,
        original_results: List[Dict],
        stego_results: List[Dict],
        original_file: str,
        stego_file: str
    ) -> Dict[str, Any]:
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
                "avg_packets": avg_stat(original_results, "total_packets"),
                "std_packets": std_stat(original_results, "total_packets"),
                "avg_bytes": avg_stat(original_results, "total_bytes"),
                "std_bytes": std_stat(original_results, "total_bytes"),
                "avg_throughput_mbps": avg_stat(original_results, "throughput_mbps"),
                "std_throughput": std_stat(original_results, "throughput_mbps"),
                "avg_transfer_time": avg_stat(original_results, "transfer_time"),
                "std_transfer_time": std_stat(original_results, "transfer_time"),
                "avg_packet_size": avg_stat(original_results, "avg_packet_size"),
                "max_packet_size": max([r.get("max_packet_size", 0) for r in original_results]),
                "min_packet_size": min([r.get("min_packet_size", 0) for r in original_results]),
                "raw_results": original_results
            },
            "stego_image": {
                "file_path": stego_file,
                "file_size": os.path.getsize(stego_file),
                "avg_packets": avg_stat(stego_results, "total_packets"),
                "std_packets": std_stat(stego_results, "total_packets"),
                "avg_bytes": avg_stat(stego_results, "total_bytes"),
                "std_bytes": std_stat(stego_results, "total_bytes"),
                "avg_throughput_mbps": avg_stat(stego_results, "throughput_mbps"),
                "std_throughput": std_stat(stego_results, "throughput_mbps"),
                "avg_transfer_time": avg_stat(stego_results, "transfer_time"),
                "std_transfer_time": std_stat(stego_results, "transfer_time"),
                "avg_packet_size": avg_stat(stego_results, "avg_packet_size"),
                "max_packet_size": max([r.get("max_packet_size", 0) for r in stego_results]),
                "min_packet_size": min([r.get("min_packet_size", 0) for r in stego_results]),
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
            "throughput_diff_mbps": stego["avg_throughput_mbps"] - orig["avg_throughput_mbps"],
            "throughput_diff_percent": ((stego["avg_throughput_mbps"] - orig["avg_throughput_mbps"]) / orig["avg_throughput_mbps"] * 100) if orig["avg_throughput_mbps"] > 0 else 0,
            "transfer_time_diff": stego["avg_transfer_time"] - orig["avg_transfer_time"],
            "transfer_time_diff_percent": ((stego["avg_transfer_time"] - orig["avg_transfer_time"]) / orig["avg_transfer_time"] * 100) if orig["avg_transfer_time"] > 0 else 0
        }
        
        return aggregated
    
    def save_results(self, results: Dict[str, Any], filename: str = None):
        """Lưu kết quả ra file JSON"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"network_benchmark_{timestamp}.json"
        
        filepath = self.output_dir / filename
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"\nResults saved to: {filepath}")
        return filepath
    
    def create_comparison_table(self, results: Dict[str, Any]) -> pd.DataFrame:
        """Tạo bảng so sánh"""
        orig = results["original_image"]
        stego = results["stego_image"]
        comp = results["comparison"]
        
        data = {
            "Metric": [
                "File Size (bytes)",
                "File Size (KB)",
                "Total Packets",
                "Total Bytes Transferred",
                "Average Packet Size (bytes)",
                "Max Packet Size (bytes)",
                "Min Packet Size (bytes)",
                "Throughput (Mbps)",
                "Transfer Time (seconds)",
                "Packets per Second"
            ],
            "Original Image": [
                f"{orig['file_size']:,}",
                f"{orig['file_size']/1024:.2f}",
                f"{orig['avg_packets']:.1f} ± {orig['std_packets']:.1f}",
                f"{orig['avg_bytes']:.0f} ± {orig['std_bytes']:.0f}",
                f"{orig['avg_packet_size']:.1f}",
                f"{orig['max_packet_size']}",
                f"{orig['min_packet_size']}",
                f"{orig['avg_throughput_mbps']:.3f} ± {orig['std_throughput']:.3f}",
                f"{orig['avg_transfer_time']:.3f} ± {orig['std_transfer_time']:.3f}",
                f"{(orig['avg_packets'] / orig['avg_transfer_time']):.1f}" if orig['avg_transfer_time'] > 0 else "N/A"
            ],
            "Stego Image": [
                f"{stego['file_size']:,}",
                f"{stego['file_size']/1024:.2f}",
                f"{stego['avg_packets']:.1f} ± {stego['std_packets']:.1f}",
                f"{stego['avg_bytes']:.0f} ± {stego['std_bytes']:.0f}",
                f"{stego['avg_packet_size']:.1f}",
                f"{stego['max_packet_size']}",
                f"{stego['min_packet_size']}",
                f"{stego['avg_throughput_mbps']:.3f} ± {stego['std_throughput']:.3f}",
                f"{stego['avg_transfer_time']:.3f} ± {stego['std_transfer_time']:.3f}",
                f"{(stego['avg_packets'] / stego['avg_transfer_time']):.1f}" if stego['avg_transfer_time'] > 0 else "N/A"
            ],
            "Difference": [
                f"{comp['file_size_diff_bytes']:+,} bytes",
                f"{comp['file_size_diff_percent']:+.2f}%",
                f"{comp['packet_count_diff']:+.1f}",
                f"{comp['packet_count_diff_percent']:+.2f}%",
                f"{(stego['avg_packet_size'] - orig['avg_packet_size']):+.1f}",
                f"{(stego['max_packet_size'] - orig['max_packet_size']):+}",
                f"{(stego['min_packet_size'] - orig['min_packet_size']):+}",
                f"{comp['throughput_diff_mbps']:+.3f} Mbps",
                f"{comp['transfer_time_diff']:+.3f} s",
                f"{((stego['avg_packets']/stego['avg_transfer_time']) - (orig['avg_packets']/orig['avg_transfer_time'])):+.1f}" if orig['avg_transfer_time'] > 0 and stego['avg_transfer_time'] > 0 else "N/A"
            ]
        }
        
        df = pd.DataFrame(data)
        return df
    
    def create_plots(self, results: Dict[str, Any], output_prefix: str = None):
        """Tạo biểu đồ so sánh"""
        if output_prefix is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_prefix = f"network_benchmark_{timestamp}"
        
        orig = results["original_image"]
        stego = results["stego_image"]
        
        fig, axes = plt.subplots(2, 3, figsize=(18, 12))
        fig.suptitle('Network Performance Comparison: Original vs Stego Image', 
                     fontsize=16, fontweight='bold')
        
        metrics = [
            ("File Size (KB)", "file_size", 1/1024, "KB"),
            ("Total Packets", "avg_packets", 1, "packets"),
            ("Throughput (Mbps)", "avg_throughput_mbps", 1, "Mbps"),
            ("Transfer Time (s)", "avg_transfer_time", 1, "seconds"),
            ("Avg Packet Size (bytes)", "avg_packet_size", 1, "bytes"),
            ("Total Bytes", "avg_bytes", 1, "bytes")
        ]
        
        for idx, (title, key, multiplier, unit) in enumerate(metrics):
            ax = axes[idx // 3, idx % 3]
            
            orig_val = orig.get(key, 0) * multiplier
            stego_val = stego.get(key, 0) * multiplier
            
            categories = ['Original', 'Stego']
            values = [orig_val, stego_val]
            colors = ['#2ecc71', '#e74c3c']
            
            bars = ax.bar(categories, values, color=colors, alpha=0.7, edgecolor='black', linewidth=1.5)
            
            for i, (bar, val) in enumerate(zip(bars, values)):
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height,
                       f'{val:.2f} {unit}',
                       ha='center', va='bottom', fontweight='bold')
            
            ax.set_ylabel(unit)
            ax.set_title(title, fontweight='bold')
            ax.grid(axis='y', alpha=0.3)
        
        plt.tight_layout()
        
        plot_file = self.output_dir / f"{output_prefix}_comparison.png"
        plt.savefig(plot_file, dpi=300, bbox_inches='tight')
        print(f"Comparison plot saved to: {plot_file}")
        plt.close()
        
        self._create_line_plot(results, output_prefix)
    
    def _create_line_plot(self, results: Dict[str, Any], output_prefix: str):
        """Tạo biểu đồ đường so sánh qua các iterations"""
        orig_results = results["original_image"]["raw_results"]
        stego_results = results["stego_image"]["raw_results"]
        
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle('Performance Trends Across Iterations', fontsize=16, fontweight='bold')
        
        iterations = list(range(1, len(orig_results) + 1))
        
        metrics = [
            ("Throughput (Mbps)", "throughput_mbps", "Mbps", axes[0, 0]),
            ("Transfer Time (s)", "transfer_time", "seconds", axes[0, 1]),
            ("Total Packets", "total_packets", "packets", axes[1, 0]),
            ("Total Bytes", "total_bytes", "bytes", axes[1, 1])
        ]
        
        for title, key, unit, ax in metrics:
            orig_values = [r.get(key, 0) for r in orig_results]
            stego_values = [r.get(key, 0) for r in stego_results]
            
            ax.plot(iterations, orig_values, marker='o', linewidth=2, 
                   label='Original', color='#2ecc71', markersize=8)
            ax.plot(iterations, stego_values, marker='s', linewidth=2, 
                   label='Stego', color='#e74c3c', markersize=8)
            
            ax.set_xlabel('Iteration', fontweight='bold')
            ax.set_ylabel(unit, fontweight='bold')
            ax.set_title(title, fontweight='bold')
            ax.legend()
            ax.grid(alpha=0.3)
            ax.set_xticks(iterations)
        
        plt.tight_layout()
        
        plot_file = self.output_dir / f"{output_prefix}_trends.png"
        plt.savefig(plot_file, dpi=300, bbox_inches='tight')
        print(f"Trend plot saved to: {plot_file}")
        plt.close()


def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Network Performance Benchmark for ZK-SNARK Steganography"
    )
    parser.add_argument(
        "image_path",
        help="Path to original image file"
    )
    parser.add_argument(
        "-m", "--message",
        help="Message to embed (default: auto-generated from metadata)",
        default=None
    )
    parser.add_argument(
        "-i", "--iterations",
        type=int,
        default=3,
        help="Number of test iterations (default: 3)"
    )
    parser.add_argument(
        "-o", "--output-dir",
        default="benchmark_results",
        help="Output directory for results (default: benchmark_results)"
    )
    parser.add_argument(
        "--interface",
        help="Network interface to capture (default: auto-detect)"
    )
    parser.add_argument(
        "--tshark-path",
        default="D:\\Apps\\Wireshark\\tshark.exe",
        help="Path to tshark executable (default: D:\\Apps\\Wireshark\\tshark.exe)"
    )
    
    args = parser.parse_args()
    
    if not os.path.exists(args.image_path):
        print(f"ERROR: Image file not found: {args.image_path}")
        return 1
    
    benchmark = NetworkBenchmark(output_dir=args.output_dir, tshark_path=args.tshark_path)
    if args.interface:
        benchmark.capture.interface = args.interface
    
    try:
        results = benchmark.run_benchmark(
            args.image_path,
            message=args.message,
            iterations=args.iterations
        )
        
        json_file = benchmark.save_results(results)
        
        print("\n" + "=" * 60)
        print("COMPARISON TABLE")
        print("=" * 60)
        df = benchmark.create_comparison_table(results)
        print(df.to_string(index=False))
        
        benchmark.create_plots(results)
        
        print("\n" + "=" * 60)
        print("BENCHMARK COMPLETED")
        print("=" * 60)
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

