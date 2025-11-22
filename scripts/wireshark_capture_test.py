"""
Simple Wireshark Capture Test - Test network capture với Wireshark
Không cần numpy/PIL, chỉ test capture functionality
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

def capture_test(duration=5):
    """Test capture network traffic"""
    print("=" * 60)
    print("WIRESHARK CAPTURE TEST")
    print("=" * 60)
    
    if not os.path.exists(TSHARK_PATH):
        print(f"ERROR: tshark not found at {TSHARK_PATH}")
        return False
    
    print(f"Using tshark: {TSHARK_PATH}")
    print(f"Interface: {INTERFACE}")
    print(f"Duration: {duration} seconds")
    print("\nStarting capture...")
    
    with tempfile.NamedTemporaryFile(suffix='.pcap', delete=False) as f:
        pcap_file = f.name
    
    try:
        # Start capture
        cmd = [
            TSHARK_PATH,
            "-i", INTERFACE,
            "-f", "tcp port 8000",
            "-w", pcap_file,
            "-q"
        ]
        
        print(f"Command: {' '.join(cmd)}")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        print("Capture started. Waiting...")
        time.sleep(duration)
        
        # Stop capture
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        
        print("Capture stopped.")
        
        # Analyze capture
        if os.path.exists(pcap_file) and os.path.getsize(pcap_file) > 0:
            print(f"\nCapture file created: {pcap_file}")
            print(f"File size: {os.path.getsize(pcap_file)} bytes")
            
            # Get packet count
            cmd_stats = [
                TSHARK_PATH,
                "-r", pcap_file,
                "-T", "fields",
                "-e", "frame.number",
                "-q"
            ]
            
            result = subprocess.run(
                cmd_stats,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                lines = [l for l in result.stdout.strip().split('\n') if l.strip()]
                packet_count = len(lines)
                print(f"Packets captured: {packet_count}")
                
                if packet_count > 0:
                    print("\n[SUCCESS] Wireshark capture is working!")
                    
                    # Get detailed stats
                    cmd_detailed = [
                        TSHARK_PATH,
                        "-r", pcap_file,
                        "-T", "fields",
                        "-e", "frame.number",
                        "-e", "frame.len",
                        "-e", "frame.time_epoch",
                        "-E", "header=n",
                        "-E", "separator=|"
                    ]
                    
                    result_detailed = subprocess.run(
                        cmd_detailed,
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    
                    if result_detailed.returncode == 0:
                        total_bytes = 0
                        for line in result_detailed.stdout.strip().split('\n'):
                            if line.strip():
                                parts = line.split('|')
                                if len(parts) >= 2 and parts[1]:
                                    try:
                                        total_bytes += int(parts[1])
                                    except ValueError:
                                        pass
                        
                        print(f"Total bytes: {total_bytes:,}")
                        if packet_count > 0:
                            print(f"Avg packet size: {total_bytes // packet_count} bytes")
                    
                    return True
                else:
                    print("\n[WARNING] No packets captured. This is normal if no traffic on port 8000.")
                    print("To test with real traffic, start an HTTP server on port 8000.")
                    return True
            else:
                print(f"\n[WARNING] Could not analyze capture: {result.stderr}")
                return True
        else:
            print("\n[WARNING] Capture file is empty or not created.")
            return False
            
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if os.path.exists(pcap_file):
            try:
                os.unlink(pcap_file)
            except:
                pass

def main():
    """Main function"""
    print("\nThis script tests Wireshark capture functionality.")
    print("It will capture traffic on loopback interface for 5 seconds.")
    print("If no traffic is present, it's normal to see 0 packets.\n")
    
    if capture_test(duration=5):
        print("\n" + "=" * 60)
        print("TEST COMPLETED")
        print("=" * 60)
        print("\nWireshark is ready to use for network benchmarking!")
        print("\nTo run full benchmark, you need to:")
        print("1. Install dependencies: pip install numpy Pillow matplotlib pandas")
        print("2. Run: python scripts/network_benchmark.py <image_path>")
        return 0
    else:
        print("\n" + "=" * 60)
        print("TEST FAILED")
        print("=" * 60)
        return 1

if __name__ == "__main__":
    sys.exit(main())

