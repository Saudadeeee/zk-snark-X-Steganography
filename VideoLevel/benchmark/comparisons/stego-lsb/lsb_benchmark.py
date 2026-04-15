import sys
import os
import time
from pathlib import Path
import cv2
import numpy as np

def run_lsb_benchmark(video_file: str):
    """
    Simulates Naive LSB Steganography on the pixel domain.
    Reads a few frames from the video, applies LSB embedding, 
    and checks the PSNR / SSIM of the modified frame.
    """
    if not os.path.exists(video_file):
        print(f"Error: Video file {video_file} not found.")
        return

    print(f"--- Running Naive LSB Benchmark ---")
    print(f"Target Video: {video_file}")
    
    cap = cv2.VideoCapture(video_file)
    ret, frame = cap.read()
    if not ret:
        print("Could not read frame.")
        return
        
    # Convert to grayscale (Luma) as target for embedding (for fair comparison with H264 Y-channel)
    original_y = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
    h, w = original_y.shape
    capacity_bits = h * w  # 1 bit per pixel
    payload = bytes([i % 256 for i in range(274)]) # 274 bytes to match our system
    payload_bits = []
    for b in payload:
        for i in range(8):
            payload_bits.append((b >> (7 - i)) & 1)
            
    print(f"\nEmbedding {len(payload_bits)} bits into {h}x{w} frame (Capacity: {capacity_bits} bits)")
    
    # BEDDING
    t0 = time.perf_counter()
    stego_y = original_y.copy()
    flat = stego_y.flatten()
    
    # Embed
    for i, bit in enumerate(payload_bits):
        flat[i] = (flat[i] & ~1) | bit
        
    stego_y = flat.reshape((h, w))
    embed_time = (time.perf_counter() - t0) * 1000
    
    # Calculate PSNR
    mse = np.mean((original_y.astype(np.float64) - stego_y.astype(np.float64)) ** 2)
    if mse == 0:
        psnr = float('inf')
    else:
        psnr = 10 * np.log10((255 ** 2) / mse)
        
    print(f"\n--- Results ---")
    print(f"Embed Time : {embed_time:.2f} ms per frame")
    print(f"PSNR       : {psnr:.2f} dB (For highly localized LSB)")
    print("Note: In localized LSB, damage is concentrated. Distributed LSB gives ~51 dB.")
    print("-----------------------------------")
    
    cap.release()

if __name__ == "__main__":
    video = sys.argv[1] if len(sys.argv) > 1 else "../../../data/encoded/foreman_cif_300_g8.h264"
    run_lsb_benchmark(video)
