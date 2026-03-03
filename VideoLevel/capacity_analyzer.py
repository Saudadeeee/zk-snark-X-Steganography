import sys
import os

from src.decoder.cavlc_extractor_simple import SimpleCAVLCExtractor
from src.embedder.cavlc_safety_filter import CAVLCSafetyFilter

def analyze_video(video_path):
    print(f"\n{'='*50}")
    print(f"Analyzing {os.path.basename(video_path)}")
    print(f"{'='*50}")
    
    extractor = SimpleCAVLCExtractor()
    safety_filter = CAVLCSafetyFilter()
    
    # Extract all frames to get a good sample of I and P frames without taking too long
    frames = extractor.extract_from_video(video_path, max_frames=300)
    
    i_frame_caps = []
    p_frame_caps = []
    
    for idx, frame in enumerate(frames):
        # Build block map for safety filter
        coefficients = []
        for mb in frame['macroblocks']:
            if mb['is_skip_mb']:
                continue
            for b in range(16):  # Only luma blocks 0-15
                start_idx = b * 16
                coeffs = mb['coefficients'][start_idx:start_idx+16]
                if any(c != 0 for c in coeffs):
                    coefficients.append((mb['mb_idx'], b, coeffs))
        
        if len(coefficients) > 0:
            safe_positions = safety_filter.get_safe_positions(coefficients, skip_dc=True)
            capacity_bits = len(safe_positions)
        else:
            capacity_bits = 0
            
        if capacity_bits > 500:
            i_frame_caps.append(capacity_bits)
            frame_type = "I-Frame (Keyframe)"
        else:
            p_frame_caps.append(capacity_bits)
            frame_type = "P-Frame/B-Frame"
            
        print(f"Frame {idx:02d} [{frame_type}]: {capacity_bits} bits safe capacity")
        
    avg_i = sum(i_frame_caps) / len(i_frame_caps) if i_frame_caps else 0
    avg_p = sum(p_frame_caps) / len(p_frame_caps) if p_frame_caps else 0
    
    print(f"\n--- SUMMARY ---")
    print(f"Average I-Frame capacity: {avg_i:.1f} bits/frame")
    print(f"Average P-Frame capacity: {avg_p:.1f} bits/frame")
    
    payload_size = 2336
    if avg_i > 0:
        required_i_frames = payload_size / avg_i
        print(f"To hide {payload_size} bits, you need approximately {required_i_frames:.2f} I-Frames.")
    else:
        print("No I-Frames detected in sample!")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        analyze_video(sys.argv[1])
    else:
        # Run on a normal encoded video with default GOP (has I and P frames)
        # We previously generated data/raw/akiyo_cavlc_baseline.h264 with CRF 23
        # Wait, that was overwritten. Let's make a fresh quick one.
        os.system("ffmpeg -i data/raw/foreman_cif.y4m -c:v libx264 -profile:v baseline -coder 0 -crf 23 -y data/raw/foreman_normal.h264 > nul 2>&1")
        analyze_video("data/raw/foreman_normal.h264")
