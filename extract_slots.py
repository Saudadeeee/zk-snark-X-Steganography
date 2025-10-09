#!/usr/bin/env python3

import sys
import json
import time
import logging
from PIL import Image

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def extract_all_slots(image_path, max_slots=256):
    logging.info("🔍 Starting LSB slot extraction")
    start_time = time.time()
    
    # Load image
    logging.info(f"📂 Loading stego image: {image_path}")
    img_load_start = time.time()
    img = Image.open(image_path).convert('RGB')
    pixels = list(img.getdata())
    width, height = img.size
    img_load_time = time.time() - img_load_start
    
    logging.info(f"✅ Image loaded in {img_load_time:.4f}s")
    logging.info(f"   Image dimensions: {width}x{height}")
    logging.info(f"   Total pixels: {len(pixels)}")
    logging.info(f"   Total RGB slots: {len(pixels) * 3}")
    
    # Flatten pixels
    logging.info("🔄 Flattening pixel data")
    flatten_start = time.time()
    flat_pixels = []
    for r, g, b in pixels:
        flat_pixels.extend([r, g, b])
    flatten_time = time.time() - flatten_start
    logging.info(f"✅ Pixel flattening completed in {flatten_time:.4f}s")
    
    # Extract LSBs
    logging.info(f"🎯 Extracting LSBs from first {max_slots} slots")
    extract_start = time.time()
    slots = []
    for i in range(min(max_slots, len(flat_pixels))):
        lsb = flat_pixels[i] & 1
        slots.append(lsb)
    
    # Pad with zeros if needed
    original_length = len(slots)
    while len(slots) < max_slots:
        slots.append(0)
    
    extract_time = time.time() - extract_start
    total_time = time.time() - start_time
    
    logging.info(f"✅ LSB extraction completed in {extract_time:.4f}s")
    logging.info(f"   Extracted {original_length} actual LSBs")
    logging.info(f"   Padded with {max_slots - original_length} zeros")
    logging.info(f"   Final slot array length: {len(slots)}")
    logging.info(f"🎉 Total extraction time: {total_time:.4f}s")
    
    print(f"Extracted {len(slots)} slots from image {width}x{height}", file=sys.stderr)
    return slots

def main():
    logging.info("🚀 Starting ZK-SNARK Steganography Slot Extraction Tool")
    logging.info("=" * 60)
    
    if len(sys.argv) < 2:
        logging.error("❌ Invalid arguments")
        print("Usage: python3 extract_slots.py stego.png [secret_bits] [message_bits]", file=sys.stderr)
        print("If secret and message are provided, they will be included in the output", file=sys.stderr)
        sys.exit(1)
    
    image_path = sys.argv[1]
    logging.info(f"📄 Input parameters:")
    logging.info(f"   Stego image: {image_path}")
    
    # Extract LSB slots
    slots = extract_all_slots(image_path)
    
    # Prepare circuit input
    logging.info("🔧 Preparing circuit input JSON")
    input_start = time.time()
    
    circuit_input = {
        "slots": slots
    }
    
    # Add secret and message if provided
    if len(sys.argv) >= 4:
        secret_str = sys.argv[2]
        message_str = sys.argv[3]
        
        logging.info(f"🔐 Adding private inputs:")
        logging.info(f"   Secret: {secret_str}")
        logging.info(f"   Message: {message_str}")
        
        secret_bits = [int(b) for b in secret_str]
        message_bits = [int(b) for b in message_str]
        
        # Validate inputs
        if len(secret_bits) != 16:
            logging.error(f"❌ Invalid secret length: {len(secret_bits)} (expected 16)")
            sys.exit(1)
            
        if len(message_bits) != 8:
            logging.error(f"❌ Invalid message length: {len(message_bits)} (expected 8)")
            sys.exit(1)
        
        circuit_input["secret"] = secret_bits
        circuit_input["message"] = message_bits
        
        print(f"Including secret: {secret_str}", file=sys.stderr)
        print(f"Including message: {message_str}", file=sys.stderr)
    else:
        logging.info("ℹ️ No private inputs provided (public extraction only)")
    
    input_time = time.time() - input_start
    logging.info(f"✅ Circuit input prepared in {input_time:.4f}s")
    
    # Output JSON
    json_start = time.time()
    json_output = json.dumps(circuit_input, indent=2)
    json_time = time.time() - json_start
    
    logging.info(f"📄 JSON serialization completed in {json_time:.4f}s")
    logging.info(f"💾 Output JSON size: {len(json_output)} bytes")
    logging.info("🎉 SLOT EXTRACTION COMPLETED SUCCESSFULLY!")
    logging.info("=" * 60)
    
    print(json_output)

if __name__ == "__main__":
    main()