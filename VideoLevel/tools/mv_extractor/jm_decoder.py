"""
JM Reference Decoder Wrapper for Motion Vector Extraction

This module provides a Python interface to the JM H.264/AVC Reference Decoder
for extracting real motion vectors from H.264 bitstreams.

This is the GOLD STANDARD method for MV extraction in research/production.
"""

import subprocess
import os
import tempfile
import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import json


@dataclass
class JMMVData:
    """Motion Vector data from JM decoder"""
    frame_idx: int
    frame_type: str  # I, P, B
    mb_x: int
    mb_y: int
    
    # Motion Vector (MV = MVP + MVD)
    mvx: int
    mvy: int
    
    # Motion Vector Difference (what's encoded in bitstream)
    mvd_x: int
    mvd_y: int
    
    # Motion Vector Predictor (calculated from neighbors)
    mvp_x: int = 0
    mvp_y: int = 0
    
    # Block information
    mb_type: str = ''
    partition: str = ''
    
    def __post_init__(self):
        """Calculate derived properties"""
        self.magnitude = np.sqrt(self.mvx ** 2 + self.mvy ** 2)
        self.mvd_magnitude = np.sqrt(self.mvd_x ** 2 + self.mvd_y ** 2)
        
        self.parity_x = abs(self.mvx) % 2
        self.parity_y = abs(self.mvy) % 2
        
        self.mvd_parity_x = abs(self.mvd_x) % 2
        self.mvd_parity_y = abs(self.mvd_y) % 2
        
        # Verify MV = MVP + MVD relationship
        if self.mvp_x != 0 or self.mvp_y != 0:
            assert abs(self.mvx - (self.mvp_x + self.mvd_x)) < 2, "MV != MVP + MVD"


class JMDecoder:
    """
    JM H.264/AVC Reference Decoder wrapper
    
    This class provides a Python interface to the JM decoder for extracting
    motion vectors from H.264 bitstreams.
    
    Prerequisites:
    1. JM decoder must be built (ldecod or ldecod.exe)
    2. JM must be modified to export MV data (see PRODUCTION_MV_EXTRACTION.md)
    
    Usage:
        decoder = JMDecoder(jm_path='/path/to/JM/bin/ldecod')
        mvs = decoder.extract_motion_vectors('video.264')
    """
    
    def __init__(self, jm_decoder_path: str = None):
        """
        Initialize JM decoder wrapper
        
        Args:
            jm_decoder_path: Path to JM ldecod executable
                           If None, will search common locations
        """
        self.jm_decoder_path = jm_decoder_path or self._find_jm_decoder()
        
        if not self.jm_decoder_path or not os.path.exists(self.jm_decoder_path):
            raise FileNotFoundError(
                "JM decoder not found. Please:\n"
                "1. Download JM from https://vcgit.hhi.fraunhofer.de/jvet/JM\n"
                "2. Build ldecod (see PRODUCTION_MV_EXTRACTION.md)\n"
                "3. Pass path to decoder: JMDecoder('/path/to/ldecod')"
            )
        
        print(f"Using JM decoder: {self.jm_decoder_path}")
        self._verify_jm_version()
    
    def _find_jm_decoder(self) -> Optional[str]:
        """Search for JM decoder in common locations"""
        search_paths = [
            './JM/bin/ldecod.exe',
            './JM/bin/ldecod',
            '../JM/bin/ldecod.exe',
            '../JM/bin/ldecod',
            '../../external/JM/bin/ldecod.exe',
            '../../external/JM/bin/ldecod',
            '/usr/local/bin/ldecod',
            'ldecod',  # In PATH
        ]
        
        for path in search_paths:
            if os.path.exists(path):
                return os.path.abspath(path)
        
        return None
    
    def _verify_jm_version(self):
        """Verify JM decoder is working"""
        try:
            result = subprocess.run(
                [self.jm_decoder_path, '-h'],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            # Check if it's actually JM
            if 'JM' in result.stdout or 'H.264' in result.stdout:
                print("[OK] JM decoder verified")
            else:
                print("[WARN] Decoder may not be JM reference decoder")
                
        except Exception as e:
            print(f"[WARN] Could not verify JM decoder: {e}")
    
    def prepare_h264_bitstream(self, video_path: str, output_264: str = None) -> str:
        """
        Convert video to raw H.264 bitstream for JM decoder
        
        Args:
            video_path: Path to input video (MP4, MKV, etc.)
            output_264: Path for output .264 file (optional)
            
        Returns:
            Path to .264 bitstream file
        """
        if output_264 is None:
            # Create temporary file
            fd, output_264 = tempfile.mkstemp(suffix='.264')
            os.close(fd)
        
        print(f"Converting {video_path} to H.264 bitstream...")
        
        cmd = [
            'ffmpeg',
            '-i', video_path,
            '-c:v', 'copy',  # Copy video stream without re-encoding
            '-an',  # No audio
            '-f', 'h264',
            '-y',
            output_264
        ]
        
        try:
            subprocess.run(cmd, capture_output=True, check=True)
            print(f"[OK] H.264 bitstream created: {output_264}")
            return output_264
            
        except subprocess.CalledProcessError as e:
            # If copy fails, re-encode with x264
            print("[INFO] Copy failed, re-encoding with x264...")
            cmd = [
                'ffmpeg',
                '-i', video_path,
                '-c:v', 'libx264',
                '-preset', 'medium',
                '-crf', '23',
                '-an',
                '-f', 'h264',
                '-y',
                output_264
            ]
            subprocess.run(cmd, capture_output=True, check=True)
            print(f"[OK] H.264 bitstream created: {output_264}")
            return output_264
    
    def decode_with_mv_export(self, h264_file: str, mv_output: str = None) -> Tuple[str, str]:
        """
        Run JM decoder with MV export
        
        Args:
            h264_file: Path to H.264 bitstream file
            mv_output: Path for MV output CSV (optional)
            
        Returns:
            Tuple of (yuv_output_path, mv_csv_path)
        """
        if mv_output is None:
            mv_output = h264_file.replace('.264', '_mvs.csv')
        
        yuv_output = h264_file.replace('.264', '_decoded.yuv')
        
        # Set environment variable for MV export path (if JM modified to use it)
        env = os.environ.copy()
        env['JM_MV_EXPORT_FILE'] = mv_output
        
        print(f"Running JM decoder on {h264_file}...")
        
        cmd = [
            self.jm_decoder_path,
            '-i', h264_file,
            '-o', yuv_output,
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
                timeout=300  # 5 minute timeout
            )
            
            print("[OK] JM decoding complete")
            
            # Check if MV file was created
            if os.path.exists(mv_output):
                print(f"[OK] Motion vectors exported to: {mv_output}")
            else:
                print("[WARN] MV export file not created.")
                print("      JM decoder may not have MV export modification.")
                print("      See PRODUCTION_MV_EXTRACTION.md for setup instructions.")
            
            return yuv_output, mv_output
            
        except subprocess.TimeoutExpired:
            raise RuntimeError("JM decoder timed out")
        except Exception as e:
            raise RuntimeError(f"JM decoder failed: {e}")
    
    def extract_motion_vectors(self, video_path: str, cleanup: bool = True) -> List[JMMVData]:
        """
        Extract motion vectors from video using JM decoder
        
        Args:
            video_path: Path to video file
            cleanup: Whether to delete temporary files
            
        Returns:
            List of JMMVData objects
        """
        print(f"\n{'='*70}")
        print("JM-based Motion Vector Extraction")
        print(f"{'='*70}")
        
        # Step 1: Convert to H.264 bitstream
        h264_file = self.prepare_h264_bitstream(video_path)
        
        # Step 2: Run JM decoder with MV export
        yuv_file, mv_csv = self.decode_with_mv_export(h264_file)
        
        # Step 3: Parse MV CSV
        mv_data = []
        if os.path.exists(mv_csv):
            mv_data = self._parse_mv_csv(mv_csv)
        else:
            print("\n[ERROR] JM decoder did not export MV data")
            print("[INFO] You need to modify JM decoder to export MVs")
            print("[INFO] See: docs/PRODUCTION_MV_EXTRACTION.md")
            print("\n[INFO] For now, providing manual extraction instructions:")
            print("      1. Use modified JM with MV export patch")
            print("      2. Or manually inspect JM decoder output")
            
        # Cleanup
        if cleanup:
            for f in [h264_file, yuv_file]:
                if os.path.exists(f):
                    os.unlink(f)
            print("[OK] Temporary files cleaned up")
        
        return mv_data
    
    def _parse_mv_csv(self, csv_path: str) -> List[JMMVData]:
        """Parse MV CSV exported by modified JM decoder"""
        try:
            df = pd.read_csv(csv_path)
            
            mv_data = []
            for _, row in df.iterrows():
                mv = JMMVData(
                    frame_idx=int(row.get('frame', 0)),
                    frame_type=str(row.get('frame_type', 'P')),
                    mb_x=int(row.get('mb_x', 0)),
                    mb_y=int(row.get('mb_y', 0)),
                    mvx=int(row.get('mvx', 0)),
                    mvy=int(row.get('mvy', 0)),
                    mvd_x=int(row.get('mvd_x', 0)),
                    mvd_y=int(row.get('mvd_y', 0)),
                    mvp_x=int(row.get('mvp_x', 0)) if 'mvp_x' in row else 0,
                    mvp_y=int(row.get('mvp_y', 0)) if 'mvp_y' in row else 0,
                    mb_type=str(row.get('mb_type', '')),
                    partition=str(row.get('partition', '')),
                )
                mv_data.append(mv)
            
            print(f"[OK] Parsed {len(mv_data)} motion vectors from CSV")
            return mv_data
            
        except Exception as e:
            print(f"[ERROR] Failed to parse MV CSV: {e}")
            return []
    
    def get_statistics(self, mv_data: List[JMMVData]) -> Dict:
        """Calculate statistics from extracted MVs"""
        if not mv_data:
            return {}
        
        p_mvs = [mv for mv in mv_data if mv.frame_type == 'P']
        
        mvd_x_values = [mv.mvd_x for mv in p_mvs]
        mvd_y_values = [mv.mvd_y for mv in p_mvs]
        
        return {
            'total_vectors': len(mv_data),
            'p_frame_vectors': len(p_mvs),
            'mvd_x_range': (min(mvd_x_values), max(mvd_x_values)) if mvd_x_values else (0, 0),
            'mvd_y_range': (min(mvd_y_values), max(mvd_y_values)) if mvd_y_values else (0, 0),
            'avg_mvd_magnitude': np.mean([mv.mvd_magnitude for mv in p_mvs]) if p_mvs else 0,
            'zero_mvds': sum(1 for mv in p_mvs if mv.mvd_x == 0 and mv.mvd_y == 0),
        }
    
    def save_to_json(self, mv_data: List[JMMVData], output_path: str):
        """Save extracted MVs to JSON"""
        data = {
            'source': 'JM Reference Decoder',
            'num_vectors': len(mv_data),
            'motion_vectors': [
                {
                    'frame_idx': mv.frame_idx,
                    'frame_type': mv.frame_type,
                    'mb_x': mv.mb_x,
                    'mb_y': mv.mb_y,
                    'mvx': mv.mvx,
                    'mvy': mv.mvy,
                    'mvd_x': mv.mvd_x,
                    'mvd_y': mv.mvd_y,
                    'mvp_x': mv.mvp_x,
                    'mvp_y': mv.mvp_y,
                    'magnitude': mv.magnitude,
                    'mvd_magnitude': mv.mvd_magnitude,
                }
                for mv in mv_data
            ]
        }
        
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"[OK] Saved to: {output_path}")


def main():
    """Test JM decoder wrapper"""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python jm_decoder.py <video.mp4> [jm_decoder_path]")
        print("\nExample:")
        print("  python jm_decoder.py input.mp4")
        print("  python jm_decoder.py input.mp4 /path/to/ldecod")
        return
    
    video_path = sys.argv[1]
    jm_path = sys.argv[2] if len(sys.argv) > 2 else None
    
    try:
        decoder = JMDecoder(jm_path)
        
        # Extract MVs
        mv_data = decoder.extract_motion_vectors(video_path, cleanup=False)
        
        if mv_data:
            # Print statistics
            stats = decoder.get_statistics(mv_data)
            print("\n=== Statistics ===")
            for key, value in stats.items():
                print(f"{key}: {value}")
            
            # Save to JSON
            output_json = video_path.replace('.mp4', '_jm_mvs.json')
            decoder.save_to_json(mv_data, output_json)
        else:
            print("\n[INFO] No MV data extracted")
            print("[INFO] Next steps:")
            print("  1. Build JM decoder (see docs/PRODUCTION_MV_EXTRACTION.md)")
            print("  2. Modify JM to export MVs")
            print("  3. Run this script again")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
