"""
Prepare Test Videos
===================

Encode Y4M videos to H.264 Baseline Profile for testing
"""

import subprocess
from pathlib import Path


def encode_to_h264_baseline(input_file: Path, output_file: Path) -> bool:
    """
    Encode video to H.264 Baseline Profile
    
    Args:
        input_file: Input Y4M file
        output_file: Output H.264 file
    
    Returns:
        True if successful
    """
    print(f"\nEncoding {input_file.name} to H.264 Baseline...")
    
    cmd = [
        'ffmpeg',
        '-y',  # Overwrite output
        '-i', str(input_file),
        '-c:v', 'libx264',
        '-profile:v', 'baseline',
        '-level', '3.0',
        '-crf', '23',  # Quality
        '-preset', 'medium',
        '-frames:v', '10',  # Only 10 frames for testing
        str(output_file)
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        
        if output_file.exists():
            size = output_file.stat().st_size
            print(f"  ✓ Success: {output_file.name} ({size:,} bytes)")
            return True
        else:
            print(f"  ✗ Failed: Output file not created")
            return False
            
    except subprocess.CalledProcessError as e:
        print(f"  ✗ FFmpeg error: {e}")
        print(f"  stderr: {e.stderr}")
        return False
    except FileNotFoundError:
        print(f"  ✗ FFmpeg not found. Please install FFmpeg.")
        return False


def main():
    print("="*80)
    print("PREPARING TEST VIDEOS")
    print("="*80)
    
    # Setup paths
    raw_dir = Path("data/raw")
    output_dir = Path("data/output")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Test videos
    test_videos = [
        ("foreman_cif.y4m", "foreman_baseline.h264"),
        ("akiyo_cif.y4m", "akiyo_baseline.h264"),
        ("bus_cif.y4m", "bus_baseline.h264"),
    ]
    
    success_count = 0
    
    for input_name, output_name in test_videos:
        input_file = raw_dir / input_name
        output_file = output_dir / output_name
        
        if not input_file.exists():
            print(f"\n⚠️  Skipping {input_name} (not found)")
            continue
        
        if output_file.exists():
            print(f"\n⚠️  Skipping {output_name} (already exists)")
            success_count += 1
            continue
        
        if encode_to_h264_baseline(input_file, output_file):
            success_count += 1
    
    print("\n" + "="*80)
    print(f"COMPLETED: {success_count}/{len(test_videos)} videos ready")
    print("="*80)


if __name__ == '__main__':
    main()
