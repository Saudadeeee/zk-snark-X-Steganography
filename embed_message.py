#!/usr/bin/env python3

import sys
import time
import logging
from PIL import Image

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def secret_to_positions(secret_bits, message_length, total_slots):
    logging.info("🔢 Computing embedding positions from secret")
    start_time = time.time()
    
    secret_int = int(''.join(map(str, secret_bits)), 2)
    start_pos = secret_int % total_slots
    
    positions = []
    for i in range(message_length):
        pos = (start_pos + i) % total_slots
        positions.append(pos)
    
    end_time = time.time()
    logging.info(f"✅ Position calculation completed in {end_time - start_time:.4f}s")
    logging.info(f"   Secret decimal value: {secret_int}")
    logging.info(f"   Start position: {start_pos}")
    logging.info(f"   Generated {len(positions)} positions")
    
    return positions

def embed_message(cover_path, stego_path, secret_bits, message_bits):
    logging.info("🖼️ Starting message embedding process")
    start_time = time.time()
    
    # Load image
    logging.info(f"📂 Loading cover image: {cover_path}")
    img_load_start = time.time()
    img = Image.open(cover_path).convert('RGB')
    pixels = list(img.getdata())
    width, height = img.size
    img_load_time = time.time() - img_load_start
    
    total_slots = width * height * 3
    
    logging.info(f"✅ Image loaded in {img_load_time:.4f}s")
    logging.info(f"   Image dimensions: {width}x{height}")
    logging.info(f"   Total RGB slots: {total_slots}")
    logging.info(f"   Message length: {len(message_bits)} bits")
    logging.info(f"   Secret bits: {''.join(map(str, secret_bits))}")
    logging.info(f"   Message bits: {''.join(map(str, message_bits))}")
    
    positions = secret_to_positions(secret_bits, len(message_bits), total_slots)
    logging.info(f"📍 Embedding at positions: {positions}")
    
    # Flatten pixels for easier manipulation
    logging.info("🔄 Converting image to flat pixel array")
    flatten_start = time.time()
    flat_pixels = []
    for r, g, b in pixels:
        flat_pixels.extend([r, g, b])
    flatten_time = time.time() - flatten_start
    logging.info(f"✅ Pixel flattening completed in {flatten_time:.4f}s")
    
    # Embed message bits
    logging.info("💾 Embedding message bits into LSBs")
    embed_start = time.time()
    for i, bit in enumerate(message_bits):
        pos = positions[i]
        if pos >= len(flat_pixels):
            raise ValueError(f"Position {pos} exceeds image capacity {len(flat_pixels)}")
        
        old_value = flat_pixels[pos]
        flat_pixels[pos] = (flat_pixels[pos] & 0xFE) | bit
        new_value = flat_pixels[pos]
        
        logging.info(f"   Bit {i}: value={bit} at pos {pos} (pixel {pos//3}, ch {pos%3}) [{old_value}→{new_value}]")
    
    embed_time = time.time() - embed_start
    logging.info(f"✅ Message embedding completed in {embed_time:.4f}s")
    
    # Reconstruct image
    logging.info("🔧 Reconstructing stego image")
    reconstruct_start = time.time()
    new_pixels = []
    for i in range(0, len(flat_pixels), 3):
        new_pixels.append((flat_pixels[i], flat_pixels[i+1], flat_pixels[i+2]))
    
    stego_img = Image.new('RGB', (width, height))
    stego_img.putdata(new_pixels)
    stego_img.save(stego_path)
    reconstruct_time = time.time() - reconstruct_start
    logging.info(f"✅ Stego image reconstructed and saved in {reconstruct_time:.4f}s")
    
    total_time = time.time() - start_time
    logging.info(f"🎉 Message embedding process completed in {total_time:.4f}s")
    logging.info(f"💾 Stego image saved to: {stego_path}")
    
    return positions

def main():
    logging.info("🚀 Starting ZK-SNARK Steganography Embedding Tool")
    logging.info("=" * 60)
    
    if len(sys.argv) != 5:
        logging.error("❌ Invalid arguments")
        print("Usage: python3 embed_message.py cover.png stego.png SECRET_BITS MESSAGE_BITS")
        print("Example: python3 embed_message.py cover.png stego.png 1010110011010101 10110011")
        sys.exit(1)
    
    cover_path = sys.argv[1]
    stego_path = sys.argv[2]
    secret_str = sys.argv[3]
    message_str = sys.argv[4]
    
    logging.info(f"📄 Input parameters:")
    logging.info(f"   Cover image: {cover_path}")
    logging.info(f"   Output image: {stego_path}")
    logging.info(f"   Secret: {secret_str}")
    logging.info(f"   Message: {message_str}")
    
    # Validate inputs
    logging.info("🔍 Validating input parameters")
    secret_bits = [int(b) for b in secret_str]
    message_bits = [int(b) for b in message_str]
    
    if len(secret_bits) != 16:
        logging.error(f"❌ Invalid secret length: {len(secret_bits)} (expected 16)")
        print("Error: Secret must be exactly 16 bits")
        sys.exit(1)
    
    if len(message_bits) != 8:
        logging.error(f"❌ Invalid message length: {len(message_bits)} (expected 8)")
        print("Error: Message must be exactly 8 bits")
        sys.exit(1)
    
    logging.info("✅ Input validation passed")
    
    try:
        positions = embed_message(cover_path, stego_path, secret_bits, message_bits)
        logging.info("🎉 EMBEDDING PROCESS COMPLETED SUCCESSFULLY!")
        logging.info(f"📍 Final embedding positions: {positions}")
        logging.info("=" * 60)
        
        # Legacy output for compatibility
        print(f"\nEmbedding completed successfully!")
        print(f"Used positions: {positions}")
        
    except Exception as e:
        logging.error(f"💥 Embedding failed: {str(e)}")
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()