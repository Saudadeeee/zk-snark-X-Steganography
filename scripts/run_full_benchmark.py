"""
Helper script để chạy full benchmark
Tự động kiểm tra và cài đặt dependencies nếu cần
"""

import subprocess
import sys
import os

def check_and_install_dependencies():
    """Kiểm tra và cài đặt dependencies"""
    required = ['numpy', 'PIL', 'matplotlib', 'pandas']
    missing = []
    
    for module in required:
        try:
            if module == 'PIL':
                __import__('PIL')
            else:
                __import__(module)
        except ImportError:
            missing.append(module)
    
    if missing:
        print("Missing dependencies:", ', '.join(missing))
        print("Attempting to install...")
        
        # Try different Python executables
        python_cmds = [
            ['python', '-m', 'pip', 'install', '--user'] + missing,
            ['python3', '-m', 'pip', 'install', '--user'] + missing,
            ['py', '-m', 'pip', 'install', '--user'] + missing,
        ]
        
        for cmd in python_cmds:
            try:
                result = subprocess.run(cmd + ['numpy', 'Pillow', 'matplotlib', 'pandas'], 
                                      capture_output=True, timeout=60)
                if result.returncode == 0:
                    print("Dependencies installed successfully!")
                    return True
            except:
                continue
        
        print("\nERROR: Could not install dependencies automatically.")
        print("Please install manually:")
        print("  pip install numpy Pillow matplotlib pandas")
        print("\nOr use a Python environment with these packages already installed.")
        return False
    
    return True

if __name__ == "__main__":
    print("=" * 60)
    print("Full Wireshark Benchmark Runner")
    print("=" * 60)
    
    if not check_and_install_dependencies():
        print("\nYou can still run the benchmark if you have dependencies installed.")
        print("Please install: pip install numpy Pillow matplotlib pandas")
        sys.exit(1)
    
    # Import and run
    try:
        from full_wireshark_benchmark import main
        sys.exit(main())
    except ImportError as e:
        print(f"ERROR: Could not import benchmark module: {e}")
        print("Make sure full_wireshark_benchmark.py is in the same directory.")
        sys.exit(1)

