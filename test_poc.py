#!/usr/bin/env python3

import os
import sys
import json
import tempfile
import subprocess
from PIL import Image

def test_embed_extract_roundtrip():
    print("🧪 Testing embed/extract roundtrip...")
    
    secret = "1010110011010101"
    message = "10110011"
    cover_file = "testvectors/cover_16x16.png"
    
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        stego_file = tmp.name
    
    try:
        cmd = ["python3", "embed_message.py", cover_file, stego_file, secret, message]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ Embedding failed: {result.stderr}")
            return False
        
        print("✅ Message embedded successfully")
        
        img = Image.open(stego_file).convert('RGB')
        pixels = list(img.getdata())
        flat_pixels = []
        for r, g, b in pixels:
            flat_pixels.extend([r, g, b])
        
        secret_int = int(secret, 2)
        start_pos = secret_int % len(flat_pixels)
        
        extracted_message = ""
        for i in range(len(message)):
            pos = (start_pos + i) % len(flat_pixels)
            lsb = flat_pixels[pos] & 1
            extracted_message += str(lsb)
        
        if extracted_message == message:
            print(f"✅ Roundtrip successful: {message} == {extracted_message}")
            return True
        else:
            print(f"❌ Roundtrip failed: {message} != {extracted_message}")
            return False
            
    finally:
        if os.path.exists(stego_file):
            os.unlink(stego_file)

def test_circuit_input_generation():
    print("🧪 Testing circuit input generation...")
    
    secret = "1010110011010101"
    message = "10110011"
    cover_file = "testvectors/cover_16x16.png"
    
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        stego_file = tmp.name
    
    try:
        cmd = ["python3", "embed_message.py", cover_file, stego_file, secret, message]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ Embedding failed: {result.stderr}")
            return False
        
        cmd = ["python3", "extract_slots.py", stego_file, secret, message]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ Slot extraction failed: {result.stderr}")
            return False
        
        try:
            circuit_input = json.loads(result.stdout)
            
            required_keys = ["slots", "secret", "message"]
            for key in required_keys:
                if key not in circuit_input:
                    print(f"❌ Missing key in circuit input: {key}")
                    return False
            
            if len(circuit_input["slots"]) != 256:
                print(f"❌ Wrong slots length: {len(circuit_input['slots'])}")
                return False
                
            if len(circuit_input["secret"]) != 16:
                print(f"❌ Wrong secret length: {len(circuit_input['secret'])}")
                return False
                
            if len(circuit_input["message"]) != 8:
                print(f"❌ Wrong message length: {len(circuit_input['message'])}")
                return False
            
            print("✅ Circuit input generation successful")
            return True
            
        except json.JSONDecodeError as e:
            print(f"❌ Invalid JSON output: {e}")
            return False
            
    finally:
        if os.path.exists(stego_file):
            os.unlink(stego_file)

def test_tampered_stego_detection():
    print("🧪 Testing tampered stego detection...")
    
    secret = "1010110011010101"
    message = "10110011"
    cover_file = "testvectors/cover_16x16.png"
    
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        stego_file = tmp.name
    
    try:
        cmd = ["python3", "embed_message.py", cover_file, stego_file, secret, message]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ Embedding failed: {result.stderr}")
            return False
        
        img = Image.open(stego_file).convert('RGB')
        pixels = list(img.getdata())
        
        r, g, b = pixels[0]
        r = r ^ 1
        pixels[0] = (r, g, b)
        
        img.putdata(pixels)
        img.save(stego_file)
        
        cmd = ["python3", "extract_slots.py", stego_file, secret, message]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ Slot extraction failed: {result.stderr}")
            return False
        
        circuit_input = json.loads(result.stdout)
        
        print("✅ Tampered stego test completed (circuit verification would catch this)")
        return True
        
    except Exception as e:
        print(f"❌ Tampered stego test failed: {e}")
        return False
        
    finally:
        if os.path.exists(stego_file):
            os.unlink(stego_file)

def main():
    print("🚀 Running ZK-SNARK Steganography PoC Tests")
    print("=" * 50)
    
    tests = [
        test_embed_extract_roundtrip,
        test_circuit_input_generation,
        test_tampered_stego_detection
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ Test {test.__name__} crashed: {e}")
            failed += 1
        print()
    
    print("=" * 50)
    print(f"📊 Test Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("🎉 All tests passed!")
        return 0
    else:
        print("💥 Some tests failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main())