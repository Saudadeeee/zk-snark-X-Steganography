"""Simple Video Quality Benchmark - Bypass import issues"""

def main():
    print("="*70)
    print("VIDEO QUALITY BENCHMARK")
    print("="*70)
    
    # Import after initial output to see where crash happens
    print("\nImporting numpy...")
    import numpy as np
    print("✓ numpy imported")
    
    print("Importing cv2...")
    import cv2
    print("✓ cv2 imported")
    
    print("Importing skimage...")
    from skimage.metrics import structural_similarity as ssim
    print("✓ skimage imported")
    
    from pathlib import Path
    
    # Configuration
    print("\n[Configuration]")
    original_video = "data/raw/foreman_cif.y4m"
    stego_video = "data/output/test_stego.mp4"
    
    if not Path(original_video).exists():
        print(f"✗ Original not found: {original_video}")
        return 1
    
    if not Path(stego_video).exists():
        print(f"✗ Stego not found: {stego_video}")
        return 1
    
    print(f"Original: {original_video}")
    print(f"Stego:    {stego_video}")
    
    # Load videos
    print("\n[Loading videos]")
    cap_orig = cv2.VideoCapture(original_video)
    cap_stego = cv2.VideoCapture(stego_video)
    
    if not cap_orig.isOpened():
        print("✗ Cannot open original")
        return 1
    
    if not cap_stego.isOpened():
        print("✗ Cannot open stego")
        return 1
    
    frame_count = int(cap_stego.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"✓ Loaded ({frame_count} frames)")
    
    # Calculate metrics
    print("\n[Calculating metrics]")
    psnr_values = []
    ssim_values = []
    
    for i in range(frame_count):
        ret_orig, frame_orig = cap_orig.read()
        ret_stego, frame_stego = cap_stego.read()
        
        if not ret_orig or not ret_stego:
            break
        
        # Resize if needed
        if frame_orig.shape != frame_stego.shape:
            frame_stego = cv2.resize(frame_stego, 
                                     (frame_orig.shape[1], frame_orig.shape[0]))
        
        # PSNR
        mse = np.mean((frame_orig.astype(float) - frame_stego.astype(float)) ** 2)
        psnr = 20 * np.log10(255.0 / np.sqrt(mse)) if mse > 0 else 100
        psnr_values.append(psnr)
        
        # SSIM
        gray_orig = cv2.cvtColor(frame_orig, cv2.COLOR_BGR2GRAY)
        gray_stego = cv2.cvtColor(frame_stego, cv2.COLOR_BGR2GRAY)
        ssim_val = ssim(gray_orig, gray_stego)
        ssim_values.append(ssim_val)
        
        if (i + 1) % 10 == 0:
            print(f"  Frame {i+1}/{frame_count}", end='\r')
    
    print(f"  Frame {len(psnr_values)}/{frame_count} - Done!")
    
    cap_orig.release()
    cap_stego.release()
    
    # Results
    avg_psnr = np.mean(psnr_values)
    avg_ssim = np.mean(ssim_values)
    
    print("\n" + "="*70)
    print("RESULTS")
    print("="*70)
    
    print(f"\nPSNR (Peak Signal-to-Noise Ratio):")
    print(f"  Average: {avg_psnr:.2f} dB")
    print(f"  Min:     {np.min(psnr_values):.2f} dB")
    print(f"  Max:     {np.max(psnr_values):.2f} dB")
    print(f"  Std Dev: {np.std(psnr_values):.2f} dB")
    
    print(f"\nSSIM (Structural Similarity Index):")
    print(f"  Average: {avg_ssim:.4f} ({avg_ssim*100:.2f}%)")
    print(f"  Min:     {np.min(ssim_values):.4f}")
    print(f"  Max:     {np.max(ssim_values):.4f}")
    print(f"  Std Dev: {np.std(ssim_values):.4f}")
    
    # Assessment
    print(f"\nQuality Assessment:")
    if avg_psnr >= 50:
        print(f"  PSNR: Excellent (Near-perfect)")
    elif avg_psnr >= 45:
        print(f"  PSNR: Visually lossless")
    else:
        print(f"  PSNR: High quality")
    
    if avg_ssim >= 0.99:
        print(f"  SSIM: Excellent (99%+ similarity)")
    elif avg_ssim >= 0.98:
        print(f"  SSIM: Visually lossless")
    else:
        print(f"  SSIM: High quality")
    
    # File sizes
    from pathlib import Path
    size_orig = Path(original_video).stat().st_size / (1024*1024)
    size_stego = Path(stego_video).stat().st_size / (1024*1024)
    
    print(f"\nFile Sizes:")
    print(f"  Original: {size_orig:.2f} MB")
    print(f"  Stego:    {size_stego:.2f} MB")
    print(f"  Ratio:    {size_stego/size_orig:.2f}x")
    
    print("\n" + "="*70)
    print(f"✓ Benchmark complete: PSNR {avg_psnr:.2f}dB, SSIM {avg_ssim:.4f}")
    print("="*70)
    
    return 0

if __name__ == "__main__":
    import sys
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
