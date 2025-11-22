"""
Test script để kiểm tra Wireshark có hoạt động không
"""

import subprocess
import os
import sys

def test_tshark():
    """Test tshark"""
    tshark_path = "D:\\Apps\\Wireshark\\tshark.exe"
    
    if not os.path.exists(tshark_path):
        print(f"ERROR: tshark not found at {tshark_path}")
        return False
    
    print(f"Found tshark at: {tshark_path}")
    
    # Test version
    try:
        result = subprocess.run(
            [tshark_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print("\nTshark version:")
            print(result.stdout.split('\n')[0])
            return True
    except Exception as e:
        print(f"ERROR: {e}")
        return False
    
    return False

def test_interfaces():
    """Test list interfaces"""
    tshark_path = "D:\\Apps\\Wireshark\\tshark.exe"
    
    try:
        result = subprocess.run(
            [tshark_path, "-D"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            print("\nAvailable interfaces:")
            print(result.stdout)
            return True
    except Exception as e:
        print(f"ERROR: {e}")
        return False
    
    return False

if __name__ == "__main__":
    print("=" * 60)
    print("WIRESHARK TEST")
    print("=" * 60)
    
    if test_tshark():
        print("\n[OK] Tshark is working!")
        test_interfaces()
    else:
        print("\n[FAIL] Tshark test failed!")
        sys.exit(1)

