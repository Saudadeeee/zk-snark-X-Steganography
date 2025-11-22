"""
Simple Wireshark Benchmark - Chỉ sử dụng Wireshark để capture và phân tích
Không cần numpy/PIL, chỉ phân tích file size và network traffic
"""

import subprocess
import os
import sys
import time
import tempfile
import json
from pathlib import Path
from datetime import datetime

TSHARK_PATH = "D:\\Apps\\Wireshark\\tshark.exe"
INTERFACE = "\\Device\\NPF_Loopback"

def get_file_size(filepath):
    """Get file size"""
    if os.path.exists(filepath):
        return os.path.getsize(filepath)
    return 0

def capture_and_analyze(image_path, duration=3):
    """Capture và phân tích network traffic cho một ảnh"""
    print(f"\nAnalyzing: {os.path.basename(image_path)}")
    
    file_size = get_file_size(image_path)
    print(f"File size: {file_size:,} bytes ({file_size/1024:.2f} KB)")
    
    # Estimate packets (assuming ~1400 bytes per packet)
    estimated_packets = max(1, int(file_size / 1400))
    print(f"Estimated packets: {estimated_packets}")
    
    # Start HTTP server simulation
    import http.server
    import socketserver
    import threading
    
    server_port = 8000
    handler = http.server.SimpleHTTPRequestHandler
    
    # Change to directory containing image
    image_dir = os.path.dirname(os.path.abspath(image_path))
    image_name = os.path.basename(image_path)
    
    os.chdir(image_dir)
    
    server = socketserver.TCPServer(("", server_port), handler)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    
    time.sleep(0.5)
    
    # Capture traffic
    with tempfile.NamedTemporaryFile(suffix='.pcap', delete=False) as f:
        pcap_file = f.name
    
    try:
        cmd_capture = [
            TSHARK_PATH,
            "-i", INTERFACE,
            "-f", f"tcp port {server_port}",
            "-w", pcap_file,
            "-q"
        ]
        
        print("Starting Wireshark capture...")
        process = subprocess.Popen(
            cmd_capture,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        time.sleep(0.5)
        
        # Transfer file
        try:
            import urllib.request
            start_time = time.time()
            urllib.request.urlopen(f"http://localhost:{server_port}/{image_name}", timeout=5)
            transfer_time = time.time() - start_time
        except Exception as e:
            print(f"Warning: Transfer simulation: {e}")
            transfer_time = 0.1
        
        time.sleep(0.5)
        
        # Stop capture
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
        
        server.shutdown()
        server.server_close()
        
        # Analyze capture
        stats = {
            "file_size": file_size,
            "transfer_time": transfer_time,
            "packets": 0,
            "bytes": 0,
            "throughput_mbps": 0
        }
        
        if os.path.exists(pcap_file) and os.path.getsize(pcap_file) > 0:
            # Get packet stats
            cmd_stats = [
                TSHARK_PATH,
                "-r", pcap_file,
                "-T", "fields",
                "-e", "frame.number",
                "-e", "frame.len",
                "-e", "frame.time_epoch",
                "-E", "header=n",
                "-E", "separator=|"
            ]
            
            result = subprocess.run(
                cmd_stats,
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
                    if line.strip():
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
                elif transfer_time > 0:
                    stats["throughput_mbps"] = (total_bytes * 8) / (transfer_time * 1_000_000)
        
        # Cleanup
        if os.path.exists(pcap_file):
            os.unlink(pcap_file)
        
        return stats
        
    except Exception as e:
        print(f"Error: {e}")
        server.shutdown()
        server.server_close()
        if os.path.exists(pcap_file):
            os.unlink(pcap_file)
        return {
            "file_size": file_size,
            "transfer_time": transfer_time,
            "packets": estimated_packets,
            "bytes": file_size,
            "throughput_mbps": 0
        }

def main():
    """Main function"""
    if len(sys.argv) < 2:
        print("Usage: python wireshark_benchmark_simple.py <original_image> [stego_image]")
        print("\nIf only one image provided, will estimate stego image size.")
        sys.exit(1)
    
    original_image = sys.argv[1]
    
    if not os.path.exists(original_image):
        print(f"ERROR: Image not found: {original_image}")
        sys.exit(1)
    
    print("=" * 80)
    print("WIRESHARK NETWORK BENCHMARK")
    print("=" * 80)
    print(f"Using tshark: {TSHARK_PATH}")
    print(f"Interface: {INTERFACE}")
    
    # Analyze original
    print("\n" + "=" * 80)
    print("ORIGINAL IMAGE")
    print("=" * 80)
    orig_stats = capture_and_analyze(original_image)
    
    # Analyze stego (if provided) or estimate
    if len(sys.argv) >= 3:
        stego_image = sys.argv[2]
        if not os.path.exists(stego_image):
            print(f"ERROR: Stego image not found: {stego_image}")
            sys.exit(1)
        
        print("\n" + "=" * 80)
        print("STEGO IMAGE")
        print("=" * 80)
        stego_stats = capture_and_analyze(stego_image)
    else:
        # Estimate stego (assume 0.5% overhead)
        print("\n" + "=" * 80)
        print("STEGO IMAGE (ESTIMATED)")
        print("=" * 80)
        stego_size = int(orig_stats["file_size"] * 1.005)  # 0.5% overhead
        stego_stats = {
            "file_size": stego_size,
            "transfer_time": orig_stats["transfer_time"] * 1.005,
            "packets": max(1, int(stego_size / 1400)),
            "bytes": stego_size,
            "throughput_mbps": orig_stats["throughput_mbps"]
        }
        print(f"Estimated stego size: {stego_size:,} bytes ({stego_size/1024:.2f} KB)")
        print("(Assuming 0.5% overhead)")
    
    # Comparison
    print("\n" + "=" * 80)
    print("COMPARISON")
    print("=" * 80)
    print(f"{'Metric':<30} {'Original':<20} {'Stego':<20} {'Difference':<20}")
    print("-" * 80)
    
    size_diff = stego_stats["file_size"] - orig_stats["file_size"]
    size_diff_pct = (size_diff / orig_stats["file_size"] * 100) if orig_stats["file_size"] > 0 else 0
    
    packet_diff = stego_stats["packets"] - orig_stats["packets"]
    packet_diff_pct = (packet_diff / orig_stats["packets"] * 100) if orig_stats["packets"] > 0 else 0
    
    print(f"{'File Size (bytes)':<30} {orig_stats['file_size']:,<20} {stego_stats['file_size']:,<20} {size_diff:+,}")
    print(f"{'File Size (KB)':<30} {orig_stats['file_size']/1024:.2f}{'':<17} {stego_stats['file_size']/1024:.2f}{'':<17} {size_diff/1024:+.2f}")
    print(f"{'Size Difference (%)':<30} {'-':<20} {'-':<20} {size_diff_pct:+.2f}%")
    print(f"{'Packets':<30} {orig_stats['packets']:<20} {stego_stats['packets']:<20} {packet_diff:+d}")
    print(f"{'Packets Difference (%)':<30} {'-':<20} {'-':<20} {packet_diff_pct:+.2f}%")
    print(f"{'Transfer Time (s)':<30} {orig_stats['transfer_time']:.3f}{'':<17} {stego_stats['transfer_time']:.3f}{'':<17} {(stego_stats['transfer_time']-orig_stats['transfer_time']):+.3f}")
    
    if orig_stats["throughput_mbps"] > 0:
        throughput_diff = stego_stats["throughput_mbps"] - orig_stats["throughput_mbps"]
        print(f"{'Throughput (Mbps)':<30} {orig_stats['throughput_mbps']:.3f}{'':<17} {stego_stats['throughput_mbps']:.3f}{'':<17} {throughput_diff:+.3f}")
    
    print("=" * 80)
    
    # Save results
    results = {
        "timestamp": datetime.now().isoformat(),
        "original": orig_stats,
        "stego": stego_stats,
        "comparison": {
            "size_diff_bytes": size_diff,
            "size_diff_percent": size_diff_pct,
            "packet_diff": packet_diff,
            "packet_diff_percent": packet_diff_pct
        }
    }
    
    output_dir = Path("benchmark_results")
    output_dir.mkdir(exist_ok=True)
    
    json_file = output_dir / f"wireshark_benchmark_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"\nResults saved to: {json_file}")
    print("\n[SUCCESS] Benchmark completed!")

if __name__ == "__main__":
    main()

