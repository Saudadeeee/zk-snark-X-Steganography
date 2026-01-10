"""
Real H.264 Motion Vector Extractor using PyAV
Extracts actual motion vectors from H.264 bitstream

This replaces the synthetic demo mode with production-ready MV extraction.
"""

import av
import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import json


@dataclass
class RealMVData:
    """Real Motion Vector data extracted from H.264 bitstream"""
    frame_idx: int
    frame_type: str  # I, P, B
    timestamp: float
    
    # Motion vector position and value
    src_x: int  # Source block position X
    src_y: int  # Source block position Y
    dst_x: int  # Destination position X (src_x + motion[0])
    dst_y: int  # Destination position Y (src_y + motion[1])
    motion_x: int  # Motion vector X component
    motion_y: int  # Motion vector Y component
    motion_scale: int  # Motion vector scale/precision
    
    # Block information
    w: int  # Block width
    h: int  # Block height
    
    def __post_init__(self):
        """Calculate derived properties"""
        # Calculate actual motion in pixels (accounting for scale)
        if self.motion_scale > 0:
            self.mvx = self.motion_x // self.motion_scale
            self.mvy = self.motion_y // self.motion_scale
        else:
            self.mvx = self.motion_x
            self.mvy = self.motion_y
        
        self.magnitude = np.sqrt(self.mvx ** 2 + self.mvy ** 2)
        self.parity_x = abs(self.mvx) % 2
        self.parity_y = abs(self.mvy) % 2
        
        # Macroblock coordinates (assuming 16x16 macroblocks)
        self.mb_x = self.src_x // 16
        self.mb_y = self.src_y // 16


class H264MVExtractor:
    """
    Production-ready H.264 Motion Vector Extractor using PyAV
    
    Extracts real motion vectors from H.264 encoded videos by accessing
    the decoded frame side data.
    """
    
    def __init__(self, video_path: str):
        """
        Initialize H.264 MV Extractor
        
        Args:
            video_path: Path to H.264 video file
        """
        self.video_path = video_path
        self.mv_data: List[RealMVData] = []
        self.video_info = {}
        
    def extract_motion_vectors(self, max_frames: Optional[int] = None) -> List[RealMVData]:
        """
        Extract motion vectors from H.264 video
        
        Args:
            max_frames: Maximum number of frames to process (None = all frames)
            
        Returns:
            List of RealMVData objects
        """
        print(f"Extracting motion vectors from: {self.video_path}")
        
        try:
            container = av.open(self.video_path)
            
            # Get video stream
            video_stream = container.streams.video[0]
            
            # Store video info
            self.video_info = {
                'codec': video_stream.codec_context.name,
                'width': video_stream.codec_context.width,
                'height': video_stream.codec_context.height,
                'fps': float(video_stream.average_rate),
                'duration': float(video_stream.duration * video_stream.time_base) if video_stream.duration else 0,
                'pix_fmt': video_stream.codec_context.pix_fmt,
                'profile': video_stream.codec_context.profile,
            }
            
            print(f"Video info: {self.video_info['width']}x{self.video_info['height']} "
                  f"@ {self.video_info['fps']:.2f} fps, codec: {self.video_info['codec']}")
            
            # Enable motion vector export
            codec_context = video_stream.codec_context
            codec_context.options = {'flags2': '+export_mvs'}
            
            frame_idx = 0
            
            # Decode frames and extract MVs
            for frame in container.decode(video=0):
                if max_frames and frame_idx >= max_frames:
                    break
                
                # Extract motion vectors from frame
                self._extract_frame_mvs(frame, frame_idx)
                
                frame_idx += 1
                
                if frame_idx % 10 == 0:
                    print(f"Processed {frame_idx} frames, extracted {len(self.mv_data)} MVs...")
            
            container.close()
            
            print(f"\n[OK] Extraction complete!")
            print(f"Total frames processed: {frame_idx}")
            print(f"Total motion vectors extracted: {len(self.mv_data)}")
            
            return self.mv_data
            
        except Exception as e:
            print(f"[ERROR] Failed to extract motion vectors: {e}")
            raise
    
    def _extract_frame_mvs(self, frame, frame_idx: int):
        """
        Extract motion vectors from a single frame
        
        Args:
            frame: PyAV VideoFrame object
            frame_idx: Frame index
        """
        # Determine frame type
        frame_type = self._get_frame_type(frame)
        timestamp = float(frame.time) if frame.time is not None else frame_idx / self.video_info.get('fps', 30.0)
        
        # Only extract MVs from P and B frames
        if frame_type == 'I':
            return
        
        # PyAV 16+ uses MotionVectors class in side_data
        try:
            if hasattr(frame, 'side_data'):
                # Iterate over side_data items
                for side_data_item in frame.side_data:
                    # Check if this is MotionVectors type
                    item_type = str(type(side_data_item))
                    if 'MotionVector' in item_type:
                        # This is a MotionVectors container, iterate over MVs
                        mv_count = 0
                        for mv in side_data_item:
                            self._add_motion_vector(mv, frame_idx, frame_type, timestamp)
                            mv_count += 1
                        if mv_count == 0:
                            print(f"[DEBUG] Frame {frame_idx}: Found MotionVectors but count=0")
                        return
        except Exception as e:
            print(f"[DEBUG] Frame {frame_idx} MV extraction error: {e}")
            import traceback
            traceback.print_exc()
        
        # Fallback: Try older PyAV access patterns
        if hasattr(frame, 'side_data_motion_vectors'):
            mvs = frame.side_data_motion_vectors
            if mvs:
                for mv in mvs:
                    self._add_motion_vector(mv, frame_idx, frame_type, timestamp)
    
    def _parse_side_data_mvs(self, data, frame_idx: int, frame_type: str, timestamp: float):
        """
        Parse motion vector data from side_data dictionary
        
        PyAV 10+ exposes MVs as structured data
        """
        try:
            # Data might be a list of motion vectors
            if hasattr(data, '__iter__'):
                for mv in data:
                    self._add_motion_vector(mv, frame_idx, frame_type, timestamp)
        except Exception as e:
            print(f"[WARN] Could not parse side_data MVs: {e}")
    
    def _parse_side_data_buffer(self, buffer, frame_idx: int, frame_type: str, timestamp: float):
        """
        Parse motion vector data from raw buffer
        
        Format: struct AVMotionVector from libavutil/motion_vector.h
        Size: 32 bytes per MV
        """
        import struct
        
        try:
            # AVMotionVector structure (32 bytes):
            # int32_t source (4 bytes)
            # uint8_t w, h (2 bytes)
            # int16_t src_x, src_y (4 bytes)
            # int16_t dst_x, dst_y (4 bytes)
            # uint64_t flags (8 bytes)
            # int32_t motion_x, motion_y (8 bytes)
            # uint16_t motion_scale (2 bytes)
            
            mv_size = 32
            num_mvs = len(buffer) // mv_size
            
            for i in range(num_mvs):
                offset = i * mv_size
                mv_bytes = buffer[offset:offset + mv_size]
                
                # Unpack structure
                source = struct.unpack_from('i', mv_bytes, 0)[0]
                w, h = struct.unpack_from('BB', mv_bytes, 4)
                src_x, src_y = struct.unpack_from('hh', mv_bytes, 6)
                dst_x, dst_y = struct.unpack_from('hh', mv_bytes, 10)
                motion_x, motion_y = struct.unpack_from('ii', mv_bytes, 18)
                motion_scale = struct.unpack_from('H', mv_bytes, 26)[0]
                
                # Create MV object
                class MVStruct:
                    pass
                
                mv = MVStruct()
                mv.source = (src_x, src_y)
                mv.dst = (dst_x, dst_y)
                mv.motion = (motion_x, motion_y)
                mv.w = w
                mv.h = h
                mv.motion_scale = motion_scale
                
                self._add_motion_vector(mv, frame_idx, frame_type, timestamp)
                
        except Exception as e:
            print(f"[WARN] Could not parse MV buffer: {e}")
            
        except Exception as e:
            # Skip invalid MVs but log for debugging
            # print(f"[DEBUG] Skipped MV: {e}")on_y = struct.unpack_from('ii', mv_bytes, 18)
                motion_scale = struct.unpack_from('H', mv_bytes, 26)[0]
                
                # Create MV object
                class MVStruct:
                    pass
                
                mv = MVStruct()
                mv.source = (src_x, src_y)
                mv.dst = (dst_x, dst_y)
                mv.motion = (motion_x, motion_y)
                mv.w = w
                mv.h = h
                mv.motion_scale = motion_scale
                
                self._add_motion_vector(mv, frame_idx, frame_type, timestamp)
                
        except Exception as e:
            print(f"[WARN] Could not parse MV buffer: {e}")
    
    def _add_motion_vector(self, mv, frame_idx: int, frame_type: str, timestamp: float):
        """
        Add a motion vector to the collection
        
        Args:
            mv: Motion vector object from PyAV
            frame_idx: Frame index
            frame_type: Frame type (I/P/B)
            timestamp: Frame timestamp
        """
        try:
            # PyAV 16+ has direct attributes
            src_x = getattr(mv, 'src_x', 0)
            src_y = getattr(mv, 'src_y', 0)
            dst_x = getattr(mv, 'dst_x', 0)
            dst_y = getattr(mv, 'dst_y', 0)
            motion_x = getattr(mv, 'motion_x', 0)
            motion_y = getattr(mv, 'motion_y', 0)
            motion_scale = getattr(mv, 'motion_scale', 4)
            w = getattr(mv, 'w', 16)
            h = getattr(mv, 'h', 16)
            
            mv_obj = RealMVData(
                frame_idx=frame_idx,
                frame_type=frame_type,
                timestamp=timestamp,
                src_x=src_x,
                src_y=src_y,
                dst_x=dst_x,
                dst_y=dst_y,
                motion_x=motion_x,
                motion_y=motion_y,
                motion_scale=motion_scale,
                w=w,
                h=h,
            )
            
            self.mv_data.append(mv_obj)
            
        except Exception as e:
            # Log error for debugging
            print(f"[ERROR] Failed to add MV: {e}")
            import traceback
            traceback.print_exc()
    
    def _get_frame_type(self, frame) -> str:
        """Determine frame type (I, P, or B)"""
        if hasattr(frame, 'pict_type'):
            pict_type = frame.pict_type
            if pict_type == av.video.frame.PictureType.I:
                return 'I'
            elif pict_type == av.video.frame.PictureType.P:
                return 'P'
            elif pict_type == av.video.frame.PictureType.B:
                return 'B'
        
        # Fallback: assume P-frame for non-I frames
        if hasattr(frame, 'key_frame') and frame.key_frame:
            return 'I'
        
        return 'P'  # Default
    
    def get_statistics(self) -> Dict:
        """Get basic statistics about extracted MVs"""
        if not self.mv_data:
            return {}
        
        mvx_values = [mv.mvx for mv in self.mv_data]
        mvy_values = [mv.mvy for mv in self.mv_data]
        magnitudes = [mv.magnitude for mv in self.mv_data]
        
        p_frames = [mv for mv in self.mv_data if mv.frame_type == 'P']
        b_frames = [mv for mv in self.mv_data if mv.frame_type == 'B']
        
        return {
            'total_vectors': len(self.mv_data),
            'p_frame_vectors': len(p_frames),
            'b_frame_vectors': len(b_frames),
            'mvx_range': (min(mvx_values), max(mvx_values)) if mvx_values else (0, 0),
            'mvy_range': (min(mvy_values), max(mvy_values)) if mvy_values else (0, 0),
            'avg_magnitude': np.mean(magnitudes) if magnitudes else 0,
            'max_magnitude': max(magnitudes) if magnitudes else 0,
            'zero_mvs': sum(1 for mv in self.mv_data if mv.mvx == 0 and mv.mvy == 0)
        }
    
    def save_to_json(self, output_path: str):
        """Save extracted MVs to JSON"""
        data = {
            'video_path': self.video_path,
            'video_info': self.video_info,
            'num_vectors': len(self.mv_data),
            'motion_vectors': [
                {
                    'frame_idx': mv.frame_idx,
                    'frame_type': mv.frame_type,
                    'timestamp': mv.timestamp,
                    'mb_x': mv.mb_x,
                    'mb_y': mv.mb_y,
                    'mvx': mv.mvx,
                    'mvy': mv.mvy,
                    'magnitude': mv.magnitude,
                    'parity_x': mv.parity_x,
                    'parity_y': mv.parity_y,
                    'block_w': mv.w,
                    'block_h': mv.h,
                }
                for mv in self.mv_data
            ]
        }
        
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"[OK] Saved to: {output_path}")


def main():
    """Test the H.264 MV extractor"""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python h264_parser.py <video.mp4> [max_frames]")
        print("\nExample:")
        print("  python h264_parser.py input.mp4 100")
        return
    
    video_path = sys.argv[1]
    max_frames = int(sys.argv[2]) if len(sys.argv) > 2 else None
    
    try:
        extractor = H264MVExtractor(video_path)
        mv_data = extractor.extract_motion_vectors(max_frames=max_frames)
        
        # Print statistics
        stats = extractor.get_statistics()
        print("\n=== Statistics ===")
        for key, value in stats.items():
            print(f"{key}: {value}")
        
        # Save to JSON
        output_json = video_path.replace('.mp4', '_mvs_real.json')
        extractor.save_to_json(output_json)
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
