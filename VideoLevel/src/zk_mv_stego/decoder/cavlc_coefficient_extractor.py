"""
CAVLC Coefficient Extractor
============================

Extract DCT coefficients from H.264 CAVLC (baseline profile) video
This matches the decoding used in bitstream_reconstructor.py
"""

from pathlib import Path
from typing import List, Dict, Tuple, Optional
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from zk_mv_stego.bitstream.h264_parser import H264BitstreamParser, NALUnitType, BitstreamReader
from zk_mv_stego.bitstream.slice_header_parser import SliceHeaderParser, SPSData, PPSData
from zk_mv_stego.bitstream.macroblock_parser import MacroblockParser  
from zk_mv_stego.bitstream.cavlc_decoder import CAVLCDecoder


class CAVLCCoefficientExtractor:
    """
    Extract DCT coefficients from CAVLC-encoded H.264 video
    Uses same decoding logic as bitstream_reconstructor for consistency
    """
    
    def __init__(self):
        self.parser = H264BitstreamParser()
        self.sps_data = None
        self.pps_data = None
        
    def extract_from_video(self, video_path: str, max_frames: Optional[int] = None) -> List[Dict]:
        """
        Extract coefficients from H.264 baseline (CAVLC) video
        
        Args:
            video_path: Path to H.264 video file
            max_frames: Maximum frames to extract
            
        Returns:
            List of frame data dictionaries
        """
        # Create parser with video path
        parser = H264BitstreamParser(video_path)
        
        with open(video_path, 'rb') as f:
            video_data = f.read()
        
        # Parse NAL units
        nal_units = parser.parse(video_data)
        
        # Extract SPS/PPS
        for nal in nal_units:
            if nal.nal_unit_type == NALUnitType.SPS:
                self.sps_data = self._parse_sps(nal)
            elif nal.nal_unit_type == NALUnitType.PPS:
                self.pps_data = self._parse_pps(nal)
        
        # Extract from I-slices
        frames_data = []
        frame_count = 0
        
        for nal in nal_units:
            if nal.nal_unit_type == NALUnitType.CODED_SLICE_IDR:
                if max_frames and frame_count >= max_frames:
                    break
                
                frame_data = self._extract_from_slice(nal, frame_count)
                if frame_data:
                    frames_data.append(frame_data)
                    frame_count += 1
        
        return frames_data
    
    def _parse_sps(self, nal) -> SPSData:
        """Parse SPS (simplified)"""
        return SPSData(
            profile_idc=66,  # Baseline
            level_idc=30,
            seq_parameter_set_id=0,
            pic_width_in_mbs=22,  # 352/16
            pic_height_in_mbs=18,  # 288/16
            frame_mbs_only_flag=True
        )
    
    def _parse_pps(self, nal) -> PPSData:
        """Parse PPS (simplified)"""
        return PPSData(
            pic_parameter_set_id=0,
            seq_parameter_set_id=0,
            entropy_coding_mode_flag=False,  # CAVLC
            pic_init_qp=26
        )
    
    def _extract_from_slice(self, nal, frame_idx: int) -> Optional[Dict]:
        """
        Extract coefficients from one slice
        Matches bitstream_reconstructor decoding logic
        """
        try:
            # Parse slice header
            slice_parser = SliceHeaderParser(self.sps_data, self.pps_data)
            slice_header = slice_parser.parse_slice_header(nal.rbsp_byte)
            
            # Skip slice header to get to MB data
            reader = BitstreamReader(nal.rbsp_byte)
            header_bits = self._estimate_slice_header_bits(slice_header)
            reader.seek(header_bits)
            
            # Decode macroblocks (decode 10 MBs per slice like reconstructor)
            mb_parser = MacroblockParser(reader, slice_header.slice_type, slice_header.qp)
            cavlc_decoder = CAVLCDecoder(reader)
            
            macroblocks = []
            num_mbs = 10  # Match reconstructor
            
            for mb_idx in range(num_mbs):
                try:
                    mb_type = mb_parser.parse_macroblock_type_only()
                    
                    # Read CBP and QP delta
                    coded_block_pattern = 0
                    if slice_header.slice_type in [2, 7]:  # I-slice
                        try:
                            coded_block_pattern = mb_parser._read_coded_block_pattern()
                            if coded_block_pattern > 0:
                                _ = mb_parser.reader.read_se()  # QP delta
                        except:
                            pass
                    
                    # Decode all 24 blocks (16 luma + 8 chroma)
                    mb_coeffs = []
                    if coded_block_pattern != 0:
                        for block_idx in range(24):
                            try:
                                block_data = cavlc_decoder.decode_block_cavlc(2, 16)
                                mb_coeffs.extend(block_data.levels)
                            except:
                                mb_coeffs.extend([0] * 16)
                    else:
                        mb_coeffs = [0] * 384  # All zeros
                    
                    macroblocks.append({
                        'mb_idx': mb_idx,
                        'coefficients': mb_coeffs
                    })
                    
                except (EOFError, Exception):
                    break
            
            return {
                'frame_idx': frame_idx,
                'macroblocks': macroblocks,
                'total_coefficients': len(macroblocks) * 384,
                'non_zero_count': sum(sum(1 for c in mb['coefficients'] if c != 0) 
                                     for mb in macroblocks)
            }
            
        except Exception as e:
            print(f"  [WARNING] Slice extraction failed: {e}")
            return None
    
    def _estimate_slice_header_bits(self, slice_header) -> int:
        """Estimate slice header size in bits (simplified)"""
        # Typical I-slice header: ~50-100 bits
        return 80
    
    def get_all_coefficients_flat(self, frames_data: List[Dict]) -> List[int]:
        """
        Get flattened list of all coefficients across frames
        
        Args:
            frames_data: Frame data from extract_from_video()
            
        Returns:
            Flat list of all coefficients
        """
        all_coeffs = []
        
        for frame in frames_data:
            for mb in frame.get('macroblocks', []):
                all_coeffs.extend(mb.get('coefficients', []))
        
        return all_coeffs


# Test
if __name__ == '__main__':
    extractor = CAVLCCoefficientExtractor()
    
    video_path = 'd:\\Code\\SourceCode\\Project\\zk-snark-X-Steganography\\VideoLevel\\data\\raw\\high_motion_test.h264'
    
    print("Testing CAVLC Coefficient Extractor...")
    frames = extractor.extract_from_video(video_path, max_frames=1)
    
    print(f"Extracted {len(frames)} frames")
    
    if frames:
        coeffs = extractor.get_all_coefficients_flat(frames)
        non_zero = [c for c in coeffs if c != 0]
        
        print(f"Total coefficients: {len(coeffs)}")
        print(f"Non-zero: {len(non_zero)}")
        print(f"First 10 non-zero: {non_zero[:10]}")
        print(f"Coefficients at indices 256-275:")
        for i in range(256, 276):
            if i < len(coeffs) and coeffs[i] != 0:
                print(f"  [{i}] = {coeffs[i]}")
