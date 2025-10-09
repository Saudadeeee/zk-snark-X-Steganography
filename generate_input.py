#!/usr/bin/env python3

import sys
import json

def generate_input(slots, secret_bits, message_bits):
    if isinstance(secret_bits, str):
        secret_bits = [int(b) for b in secret_bits]
    if isinstance(message_bits, str):
        message_bits = [int(b) for b in message_bits]
    
    input_data = {
        "slots": slots,
        "message": message_bits,
        "secret": secret_bits
    }
    
    return input_data

def main():
    if len(sys.argv) != 4:
        print("Usage: python3 generate_input.py 'slots_json_array' secret_bits message_bits")
        print("Example: python3 generate_input.py '[0,1,0,1,...]' 1010110011010101 10110011")
        sys.exit(1)
    
    slots_str = sys.argv[1]
    secret_str = sys.argv[2]
    message_str = sys.argv[3]
    
    try:
        slots = json.loads(slots_str)
        
        secret_bits = [int(b) for b in secret_str]
        message_bits = [int(b) for b in message_str]
        
        if len(secret_bits) != 16:
            print("Error: Secret must be exactly 16 bits")
            sys.exit(1)
        
        if len(message_bits) != 8:
            print("Error: Message must be exactly 8 bits")
            sys.exit(1)
        
        if len(slots) != 256:
            print("Error: Slots array must have exactly 256 elements")
            sys.exit(1)
        
        input_data = generate_input(slots, secret_bits, message_bits)
        
        print(json.dumps(input_data, indent=2))
        
    except json.JSONDecodeError as e:
        print(f"Error parsing slots JSON: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()