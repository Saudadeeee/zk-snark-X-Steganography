"""
Simple CAVLC Coefficient Extractor
Uses IDENTICAL decoding logic as bitstream_reconstructor
"""

from typing import List, Dict, Optional
from ..bitstream.h264_parser import H264BitstreamParser, NALUnitType, BitstreamReader
from ..bitstream.slice_header_parser import SliceHeaderParser, SPSData, PPSData
from ..bitstream.macroblock_parser import MacroblockParser  
from ..bitstream.cavlc_decoder import CAVLCDecoder


class SimpleCAVLCExtractor:
    """Extract coefficients using exact same logic as reconstructor"""
    
    def extract_from_video(self, video_path: str, max_frames: Optional[int] = None) -> List[Dict]:
        parser = H264BitstreamParser(video_path)
        nal_units = parser.parse()  # No argument needed
        
        # Count NAL types
        slice_count = sum(1 for nal in nal_units if nal.nal_unit_type == NALUnitType.SLICE_IDR)
        print(f"[CAVLC Extractor] Found {len(nal_units)} total NAL units")
        print(f"[CAVLC Extractor] Found {slice_count} SLICE_IDR units")
        
        # Simple SPS/PPS with defaults
        sps = SPSData()
        pps = PPSData()
        
        frames = []
        count = 0
        
        for nal in nal_units:
            if nal.nal_unit_type == NALUnitType.SLICE_IDR:
                if max_frames and count >= max_frames:
                    break
                
                print(f"[CAVLC Extractor] Processing frame {count}...")
                try:
                    frame = self._extract_slice(nal, sps, pps, count)
                    if frame:
                        print(f"[CAVLC Extractor] Frame {count}: {frame['total_coefficients']} coeffs, {frame['non_zero_count']} non-zero")
                        frames.append(frame)
                        count += 1
                    else:
                        print(f"[CAVLC Extractor] Frame {count}: extraction returned None")
                except Exception as e:
                    print(f"[CAVLC Extractor] Frame {count} error: {type(e).__name__}: {e}")
                    import traceback
                    traceback.print_exc()
                    break
        
        print(f"[CAVLC Extractor] Successfully extracted {len(frames)} frames")
        return frames
    
    def _extract_slice(self, nal, sps, pps, idx):
        # Create reader from NAL data
        reader = BitstreamReader(nal.rbsp_byte)
        
        # Parse slice header using same method as reconstructor
        slice_parser = SliceHeaderParser(reader, nal.nal_unit_type, sps, pps)
        slice_header = slice_parser.parse()
        
        # Calculate QP from PPS init QP + slice QP delta
        slice_qp = 26 + pps.pic_init_qp_minus26 + slice_header.slice_qp_delta
        
        # Current position is after slice header
        header_bits_end = reader.position
        print(f"  Slice header parsed, reader at bit {header_bits_end}, QP={slice_qp}")
        
        mb_parser = MacroblockParser(reader, slice_header.slice_type)
        cavlc_decoder = CAVLCDecoder(reader)
        
        mbs = []
        
        for mb_idx in range(10):  # 10 MBs like reconstructor
            try:
                mb_type = mb_parser.parse_macroblock_type_only()
                
                cbp = 0
                if slice_header.slice_type in [2, 7]:
                    try:
                        cbp = mb_parser._read_coded_block_pattern()
                        if cbp > 0:
                            mb_parser.reader.read_se()
                    except:
                        pass
                
                coeffs = []
                if cbp != 0:
                    for b in range(24):  # 24 blocks
                        try:
                            block = cavlc_decoder.decode_block_cavlc(2, 16)
                            coeffs.extend(block.levels)
                        except:
                            coeffs.extend([0] * 16)
                else:
                    coeffs = [0] * 384
                
                mbs.append({'mb_idx': mb_idx, 'coefficients': coeffs})
            except:
                break
        
        return {
            'frame_idx': idx,
            'macroblocks': mbs,
            'total_coefficients': len(mbs) * 384,
            'non_zero_count': sum(sum(1 for c in mb['coefficients'] if c != 0) for mb in mbs)
        }
    
    def extract_coefficients_from_nal(self, nal, global_mb_idx: int = 0) -> Optional[Dict]:
        """
        Extract coefficients from a single NAL unit for BitstreamReconstructor.
        
        Args:
            nal: NAL unit to extract from
            global_mb_idx: Starting macroblock index (unused, for compatibility)
            
        Returns:
            Dict with 'blocks' key containing {(mb_idx, block_idx): [coeffs]} mapping
        """
        # Simple SPS/PPS with defaults
        sps = SPSData()
        pps = PPSData()
        
        try:
            # Create reader from NAL data
            reader = BitstreamReader(nal.rbsp_byte)
            
            # Parse slice header
            slice_parser = SliceHeaderParser(reader, nal.nal_unit_type, sps, pps)
            slice_header = slice_parser.parse()
            
            # Calculate QP
            slice_qp = 26 + pps.pic_init_qp_minus26 + slice_header.slice_qp_delta
            
            mb_parser = MacroblockParser(reader, slice_header.slice_type)
            cavlc_decoder = CAVLCDecoder(reader)
            
            blocks = {}  # {(mb_idx, block_idx): [16 coeffs]}
            
            for mb_idx in range(10):  # Extract from first 10 MBs
                try:
                    mb_type = mb_parser.parse_macroblock_type_only()
                    
                    cbp = 0
                    if slice_header.slice_type in [2, 7]:
                        try:
                            cbp = mb_parser._read_coded_block_pattern()
                            if cbp > 0:
                                mb_parser.reader.read_se()
                        except:
                            pass
                    
                    if cbp != 0:
                        for block_idx in range(24):  # 24 blocks per MB
                            try:
                                block = cavlc_decoder.decode_block_cavlc(2, 16)
                                blocks[(mb_idx, block_idx)] = block.levels
                            except:
                                blocks[(mb_idx, block_idx)] = [0] * 16
                    else:
                        # All zero blocks
                        for block_idx in range(24):
                            blocks[(mb_idx, block_idx)] = [0] * 16
                except:
                    break
            
            return {'blocks': blocks}
            
        except Exception as e:
            print(f"[SimpleCAVLCExtractor] extract_coefficients_from_nal error: {e}")
            return None
    
    def get_all_coefficients_flat(self, frames: List[Dict]) -> List[int]:
        result = []
        for frame in frames:
            for mb in frame.get('macroblocks', []):
                result.extend(mb.get('coefficients', []))
        return result
