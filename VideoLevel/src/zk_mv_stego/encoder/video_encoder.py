"""
Video Encoder with DCT Steganography
=====================================

Encodes video with embedded data using DCT coefficient modification.
Re-encodes with high quality (CRF 18) to achieve PSNR ≥ 45dB.
"""

import subprocess
import json
import os
from pathlib import Path
from typing import List, Dict, Optional
import numpy as np
import cv2


class VideoEncoder:
    """Encode video with DCT steganography"""
    
    def __init__(self, output_path: str, crf: int = 18, preset: str = "veryslow"):
        """
        Initialize video encoder
        
        Args:
            output_path: Output video path
            crf: Constant Rate Factor (18 = visually lossless)
            preset: Encoding preset (veryslow = best quality)
        """
        self.output_path = output_path
        self.crf = crf
        self.preset = preset
    
    def encode(self, frames: List[np.ndarray], fps: int = 30, 
               width: int = None, height: int = None) -> bool:
        """
        Encode frames to video using FFmpeg
        
        Args:
            frames: List of video frames (BGR format)
            fps: Frames per second
            width: Video width (auto-detected if None)
            height: Video height (auto-detected if None)
            
        Returns:
            True if encoding successful
        """
        if not frames:
            print("Error: No frames to encode")
            return False
        
        # Get dimensions
        if width is None or height is None:
            h, w = frames[0].shape[:2]
            width = w
            height = h
        
        print(f"\n{'='*60}")
        print(f"VIDEO ENCODING")
        print(f"{'='*60}")
        print(f"[1] Configuration:")
        print(f"    Frames: {len(frames)}")
        print(f"    Resolution: {width}x{height}")
        print(f"    FPS: {fps}")
        print(f"    CRF: {self.crf} (lower = better quality)")
        print(f"    Preset: {self.preset}")
        print(f"    Output: {self.output_path}")
        
        # Create output directory
        os.makedirs(os.path.dirname(os.path.abspath(self.output_path)), exist_ok=True)
        
        # FFmpeg command for high-quality encoding
        cmd = [
            'ffmpeg',
            '-y',  # Overwrite output
            '-f', 'rawvideo',
            '-vcodec', 'rawvideo',
            '-s', f'{width}x{height}',
            '-pix_fmt', 'bgr24',
            '-r', str(fps),
            '-i', '-',  # Input from stdin
            '-c:v', 'libx264',
            '-crf', str(self.crf),
            '-preset', self.preset,
            '-tune', 'film',  # Optimize for film content
            '-pix_fmt', 'yuv420p',
            self.output_path
        ]
        
        print(f"[2] Launching FFmpeg...")
        
        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # Write frames
            for idx, frame in enumerate(frames):
                if idx % 50 == 0:
                    print(f"    Encoding frame {idx}/{len(frames)}...", end='\r')
                process.stdin.write(frame.tobytes())
            
            process.stdin.close()
            process.wait()
            
            if process.returncode == 0:
                file_size = os.path.getsize(self.output_path) / (1024 * 1024)
                print(f"\n[3] Encoding complete!")
                print(f"    File size: {file_size:.2f} MB")
                print(f"{'='*60}\n")
                return True
            else:
                stderr = process.stderr.read().decode()
                print(f"\nFFmpeg error:\n{stderr}")
                return False
                
        except Exception as e:
            print(f"Encoding error: {e}")
            return False
    
    @staticmethod
    def decode_frames(video_path: str, max_frames: int = None) -> List[np.ndarray]:
        """
        Decode video to frames using OpenCV
        
        Args:
            video_path: Path to video file
            max_frames: Maximum frames to decode (None = all)
            
        Returns:
            List of frames in BGR format
        """
        cap = cv2.VideoCapture(str(video_path))
        
        if not cap.isOpened():
            print(f"Error: Cannot open video {video_path}")
            return []
        
        frames = []
        frame_count = 0
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            frames.append(frame)
            frame_count += 1
            
            if max_frames and frame_count >= max_frames:
                break
        
        cap.release()
        return frames
    
    @staticmethod
    def get_video_info(video_path: str) -> Dict:
        """Get video metadata using FFprobe"""
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            '-show_streams',
            str(video_path)
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            info = json.loads(result.stdout)
            
            # Extract video stream info
            for stream in info.get('streams', []):
                if stream.get('codec_type') == 'video':
                    return {
                        'width': stream.get('width'),
                        'height': stream.get('height'),
                        'fps': eval(stream.get('r_frame_rate', '30/1')),
                        'codec': stream.get('codec_name'),
                        'duration': float(stream.get('duration', 0)),
                        'frames': int(stream.get('nb_frames', 0))
                    }
            
            return {}
        except Exception as e:
            print(f"Error getting video info: {e}")
            return {}
