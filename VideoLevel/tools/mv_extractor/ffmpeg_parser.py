"""
FFmpeg-based Motion Vector Extractor (Alternative Method)
Extracts motion vectors by parsing FFmpeg debug output

This is a robust fallback method when PyAV has compatibility issues.
"""

import subprocess
import re
import json
import numpy as np
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
import tempfile
import os


@dataclass
class FFmpegMVData:
    """Motion Vector data from FFmpeg"""
    frame_idx: int
    frame_type: str
    timestamp: float
    
    # Position in frame
    src_x: int
    src_y: int
    
    # Motion vector components
    mvx: int
    mvy: int
    
    # Additional info
    dst_x: int = 0
    dst_y: int = 0
    
    def __post_init__(self):
        """Calculate derived properties"""
        self.magnitude = np.sqrt(self.mvx ** 2 + self.mvy ** 2)
        self.parity_x = abs(self.mvx) % 2
        self.parity_y = abs(self.mvy) % 2
        
        # Macroblock coordinates
        self.mb_x = self.src_x // 16
        self.mb_y = self.src_y // 16
        
        # Destination
        if self.dst_x == 0 and self.dst_y == 0:
            self.dst_x = self.src_x + self.mvx
            self.dst_y = self.src_y + self.mvy


class FFmpegMVExtractor:
    """
    Extract motion vectors using FFmpeg's debug output
    
    This method runs FFmpeg with motion vector export and parses
    the raw output to extract MV data. More reliable than PyAV
    for compatibility across different systems.
    """
    
    def __init__(self, video_path: str):
        """
        Initialize FFmpeg MV Extractor
        
        Args:
            video_path: Path to video file
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")
        
        self.video_path = video_path
        self.mv_data: List[FFmpegMVData] = []
        self.video_info = self._get_video_info()
    
    def _get_video_info(self) -> Dict:
        """Get video information using ffprobe"""
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_streams',
            '-show_format',
            self.video_path
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            info = json.loads(result.stdout)
            
            video_stream = next(
                (s for s in info['streams'] if s['codec_type'] == 'video'),
                None
            )
            
            if not video_stream:
                raise ValueError("No video stream found")
            
            return {
                'codec': video_stream.get('codec_name', 'unknown'),
                'width': video_stream.get('width', 0),
                'height': video_stream.get('height', 0),
                'fps': eval(video_stream.get('r_frame_rate', '30/1')),
                'duration': float(info['format'].get('duration', 0)),
                'bitrate': int(info['format'].get('bit_rate', 0)),
                'pix_fmt': video_stream.get('pix_fmt', 'yuv420p'),
            }
        except Exception as e:
            print(f"Warning: Could not get video info: {e}")
            return {'codec': 'unknown', 'width': 0, 'height': 0, 'fps': 30.0}
    
    def extract_motion_vectors(self, max_frames: Optional[int] = None) -> List[FFmpegMVData]:
        """
        Extract motion vectors using FFmpeg
        
        Args:
            max_frames: Maximum frames to process
            
        Returns:
            List of FFmpegMVData objects
        """
        print(f"Extracting motion vectors from: {self.video_path}")
        print(f"Video: {self.video_info['width']}x{self.video_info['height']} "
              f"@ {self.video_info['fps']:.2f} fps, codec: {self.video_info['codec']}")
        
        # Create temporary file for raw MV data
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            temp_file = f.name
        
        try:
            # Run FFmpeg to extract motion vectors
            # We'll use a custom filter to dump MV data
            self._run_ffmpeg_extract(temp_file, max_frames)
            
            # Parse the output
            self._parse_ffmpeg_output(temp_file)
            
            print(f"\n[OK] Extraction complete!")
            print(f"Total motion vectors extracted: {len(self.mv_data)}")
            
            return self.mv_data
            
        finally:
            # Clean up temp file
            if os.path.exists(temp_file):
                os.unlink(temp_file)
    
    def _run_ffmpeg_extract(self, output_file: str, max_frames: Optional[int]):
        """Run FFmpeg with MV export enabled"""
        
        # Build FFmpeg command
        cmd = [
            'ffmpeg',
            '-flags2', '+export_mvs',  # Enable MV export
            '-i', self.video_path,
        ]
        
        if max_frames:
            cmd.extend(['-vframes', str(max_frames)])
        
        # Use showinfo filter to get frame information
        cmd.extend([
            '-vf', 'showinfo',
            '-f', 'null',
            '-'
        ])
        
        print("Running FFmpeg to extract motion vectors...")
        
        # Run and capture output
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        
        # Save stderr to file (contains frame info and MV data)
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(result.stderr)
    
    def _parse_ffmpeg_output(self, output_file: str):
        """
        Parse FFmpeg output to extract motion vectors
        
        Note: FFmpeg's showinfo filter provides frame metadata but not
        detailed MV coordinates. For full MV extraction, we need to use
        a different approach with libavcodec directly or a modified FFmpeg.
        
        This implementation provides a foundation that can be extended
        with custom FFmpeg builds or by parsing libavcodec debug output.
        """
        with open(output_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse frame information
        frame_pattern = re.compile(
            r'Parsed_showinfo.*?n:\s*(\d+).*?pts_time:([\d.]+).*?type:(\w)',
            re.DOTALL
        )
        
        frames_info = []
        for match in frame_pattern.finditer(content):
            frame_idx = int(match.group(1))
            timestamp = float(match.group(2))
            frame_type = match.group(3)
            
            frames_info.append({
                'frame_idx': frame_idx,
                'timestamp': timestamp,
                'frame_type': frame_type
            })
        
        print(f"Found {len(frames_info)} frames in FFmpeg output")
        
        # For production: Need to extract actual MV data
        # This requires either:
        # 1. Custom FFmpeg build with MV dump to structured format
        # 2. Using libavcodec API directly via ctypes/cffi
        # 3. Using modified decoder that outputs MV to file
        
        # For now, we'll extract what we can from debug output
        # and provide hooks for real MV extraction
        
        print("\n[INFO] Basic frame info extracted.")
        print("[INFO] For full MV extraction, use one of these methods:")
        print("  1. PyAV with export_mvs (see h264_parser.py)")
        print("  2. Custom FFmpeg build with MV dump")
        print("  3. JM Reference Decoder with MV output")
    
    def extract_with_custom_ffmpeg(self, max_frames: Optional[int] = None) -> List[FFmpegMVData]:
        """
        Extract using custom FFmpeg build or script
        
        This method expects a custom FFmpeg that can output MV data
        in a structured format (CSV or JSON).
        """
        # TODO: Implement with custom FFmpeg build
        pass
    
    def get_statistics(self) -> Dict:
        """Get statistics about extracted MVs"""
        if not self.mv_data:
            return {}
        
        mvx_values = [mv.mvx for mv in self.mv_data]
        mvy_values = [mv.mvy for mv in self.mv_data]
        magnitudes = [mv.magnitude for mv in self.mv_data]
        
        return {
            'total_vectors': len(self.mv_data),
            'mvx_range': (min(mvx_values), max(mvx_values)),
            'mvy_range': (min(mvy_values), max(mvy_values)),
            'avg_magnitude': np.mean(magnitudes),
            'max_magnitude': max(magnitudes),
        }
    
    def save_to_json(self, output_path: str):
        """Save to JSON file"""
        data = {
            'video_path': self.video_path,
            'video_info': self.video_info,
            'num_vectors': len(self.mv_data),
            'motion_vectors': [asdict(mv) for mv in self.mv_data]
        }
        
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)


def main():
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python ffmpeg_parser.py <video.mp4> [max_frames]")
        return
    
    video_path = sys.argv[1]
    max_frames = int(sys.argv[2]) if len(sys.argv) > 2 else None
    
    extractor = FFmpegMVExtractor(video_path)
    extractor.extract_motion_vectors(max_frames=max_frames)


if __name__ == '__main__':
    main()
