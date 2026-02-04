"""
Simple CAVLC Coefficient Extractor
Uses IDENTICAL decoding logic as bitstream_reconstructor
"""

from typing import List, Dict, Optional
from ..bitstream.h264_parser import H264BitstreamParser, NALUnitType, BitstreamReader
from ..bitstream.nal_handler import SliceHeaderParser, SPSData, PPSData
from ..bitstream.macroblock_parser import MacroblockParser  
from ..bitstream.cavlc_decoder import CAVLCDecoder


class SimpleCAVLCExtractor:
    """Extract coefficients using exact same logic as reconstructor"""
    
    def __init__(self, skip_constraint_fixing=False, track_positions=False):
        self.skip_constraint_fixing = skip_constraint_fixing
        self.track_positions = track_positions
        if skip_constraint_fixing:
            print("[CAVLC Extractor] Constraint fixing DISABLED - raw coefficients preserved")
        if track_positions:
            print("[CAVLC Extractor] Bit position tracking ENABLED for DirectBitstreamPatcher")
    
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
        global_mb_offset = 0  # Track global MB index across all slices
        
        sps = SPSData()
        pps = PPSData()
        
        for nal in nal_units:
            # Handle SPS/PPS to get dimensions and parameters
            if nal.nal_unit_type == NALUnitType.SPS:
                self._parse_sps(nal, sps)
                print(f"[CAVLC Extractor] Parsed SPS: width={sps.pic_width_in_mbs_minus1+1} MBs")
            elif nal.nal_unit_type == NALUnitType.PPS:
                self._parse_pps(nal, pps)
            
            # Extract from both I-frames (IDR) and P-frames (NON_IDR)
            elif nal.nal_unit_type in [NALUnitType.SLICE_IDR, NALUnitType.SLICE_NON_IDR]:
                if max_frames and count >= max_frames:
                    break
                
                print(f"[CAVLC Extractor] Processing frame {count}...")
                try:
                    frame = self._extract_slice(nal, sps, pps, count, global_mb_offset)
                    if frame:
                        print(f"[CAVLC Extractor] Frame {count}: {frame['total_coefficients']} coeffs, {frame['non_zero_count']} non-zero")
                        frames.append(frame)
                        count += 1
                        
                        # Update global MB offset based on actual MBs in frame
                        # Use SPS dimensions if available, else assume we parsed all?
                        # Since we now use max_mbs_in_frame to limit, we should count actual MBs.
                        # Simple calculation for now:
                        mbs_in_pic = (sps.pic_width_in_mbs_minus1 + 1) * (sps.pic_height_in_map_units_minus1 + 1)
                        if mbs_in_pic > 1:
                            global_mb_offset += mbs_in_pic
                        else:
                            global_mb_offset += len(frame['macroblocks']) # Fallback
                    else:
                        print(f"[CAVLC Extractor] Frame {count}: extraction returned None")
                except Exception as e:
                    print(f"[CAVLC Extractor] Frame {count} error: {type(e).__name__}: {e}")
                    import traceback
                    traceback.print_exc()
                    break
        
        print(f"[CAVLC Extractor] Successfully extracted {len(frames)} frames")
        return frames
    
    
    def _parse_sps(self, nal, sps):
        """Parse SPS NAL unit to update SPSData object"""
        # Logic copied from BitstreamReconstructor
        try:
            reader = BitstreamReader(nal.rbsp_byte)
            # Parse SPS fields
            profile_idc = reader.read_bits(8)
            constraint_flags = reader.read_bits(8)
            level_idc = reader.read_bits(8)
            seq_parameter_set_id = reader.read_ue()
            
            sps.log2_max_frame_num_minus4 = reader.read_ue()
            sps.pic_order_cnt_type = reader.read_ue()
            
            if sps.pic_order_cnt_type == 0:
                sps.log2_max_pic_order_cnt_lsb_minus4 = reader.read_ue()
            
            num_ref_frames = reader.read_ue()
            gaps_in_frame_num_value_allowed_flag = reader.read_bits(1)
            
            # Store dimensions!
            sps.pic_width_in_mbs_minus1 = reader.read_ue()
            sps.pic_height_in_map_units_minus1 = reader.read_ue()
            sps.frame_mbs_only_flag = reader.read_bits(1) == 1
            
        except Exception as e:
            print(f"[CAVLC Extractor] SPS parsing error: {e}")

    def _parse_pps(self, nal, pps):
        """Parse PPS NAL unit to update PPSData object"""
        try:
            reader = BitstreamReader(nal.rbsp_byte)
            pic_parameter_set_id = reader.read_ue()
            seq_parameter_set_id = reader.read_ue()
            entropy_coding_mode_flag = reader.read_bits(1)
            bottom_field_pic_order_in_frame_present_flag = reader.read_bits(1)
            num_slice_groups_minus1 = reader.read_ue()
            
            num_ref_idx_l0_default_active_minus1 = reader.read_ue()
            num_ref_idx_l1_default_active_minus1 = reader.read_ue()
            weighted_pred_flag = reader.read_bits(1)
            weighted_bipred_idc = reader.read_bits(2)
            
            pps.pic_init_qp_minus26 = reader.read_se()
            pic_init_qs_minus26 = reader.read_se()
            chroma_qp_index_offset = reader.read_se()
            
            pps.deblocking_filter_control_present_flag = reader.read_bits(1) == 1
            constrained_intra_pred_flag = reader.read_bits(1)
            pps.redundant_pic_cnt_present_flag = reader.read_bits(1) == 1
        except Exception as e:
            print(f"[CAVLC Extractor] PPS parsing error: {e}")

    def _extract_slice(self, nal, sps, pps, idx, global_mb_offset=0):
        # Reset neighbor context for this slice
        self.neighbor_coeffs = {}
        
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
        cavlc_decoder = CAVLCDecoder(reader, skip_constraint_fixing=self.skip_constraint_fixing)
        
        mbs = []
        
        # For DirectBitstreamPatcher: store original bitstream data
        if self.track_positions:
            original_bitstream = nal.rbsp_byte
        
        # Calculate theoretical max MBs to prevent infinite loops
        max_mbs_in_frame = (sps.pic_width_in_mbs_minus1 + 1) * (sps.pic_height_in_map_units_minus1 + 1)
        slice_mb_idx_counter = 0 # Counter for MBs processed within this slice
        current_mb_addr = slice_header.first_mb_in_slice # Global MB address
        
        # Loop while there are enough bits for at least one more MB and we haven't exceeded frame's MB count
        # A typical MB syntax element (like mb_type) is at least 1 bit.
        # The 8-bit check is a heuristic to ensure we don't try to read from an empty buffer.
        total_bits = len(reader.data) * 8
        while (total_bits - reader.pos) > 8 and slice_mb_idx_counter < max_mbs_in_frame:
            mb_idx = current_mb_addr
            try:
                # Use robust parsing from MacroblockParser
                mb_data = mb_parser.parse_macroblock()
                
                # Coefficients are NOT parsed by parse_macroblock (it only does header/prediction)
                # But wait, does parse_macroblock parse residuals?
                # Looking at MacroblockParser outline (Step 613), it calculates luma_blocks_to_decode.
                # It does NOT seem to contain a loop calling cavlc_decoder.
                # So we must parse residuals here.
                
                # Determine blocks to decode
                luma_blocks = mb_parser.get_luma_blocks_to_decode(mb_data)
                # Parse them
                coeffs = [0] * 384
                
                # We need all 24 blocks ordered 0..23
                # luma_blocks contains indices 0..15.
                # chroma blocks? parse_macroblock handles cbp decoding.
                # We need to trust cbp from mb_data.
                
                # Iterate all 24 potential blocks
                # Track coefficient positions if requested
                if self.track_positions and not hasattr(mb_data, 'coeff_positions'):
                    mb_data.coeff_positions = {}
                
                for b in range(24):
                    should_decode = False
                    if b < 16:
                        should_decode = (b in luma_blocks)
                    elif b < 20: # Chroma DC
                         should_decode = mb_data.chroma_dc_present
                    elif b < 24: # Chroma AC
                         should_decode = mb_data.chroma_ac_present
                    
                    if should_decode:
                         # Calculate nC
                         mb_x = mb_idx % (sps.pic_width_in_mbs_minus1 + 1)
                         mb_y = mb_idx // (sps.pic_width_in_mbs_minus1 + 1)
                         
                         if not hasattr(self, 'neighbor_coeffs'): self.neighbor_coeffs = {}
                         nC = mb_parser.calculate_nC(mb_x, mb_y, b, self.neighbor_coeffs)
                         
                         # Decode with position tracking if enabled
                         block = cavlc_decoder.decode_block_cavlc(nC, 16, track_positions=self.track_positions)
                         
                         # Copy into correct position in flattened list
                         # flatten coeffs: blocks 0..23
                         start_idx = b * 16
                         coeffs[start_idx:start_idx+16] = block.levels
                         
                         # Store bit positions if tracking
                         if self.track_positions and hasattr(block, 'coeff_bit_positions'):
                             mb_data.coeff_positions[(mb_idx, b)] = block.coeff_bit_positions
                         
                         self.neighbor_coeffs[(mb_x, mb_y, b)] = block.total_coeffs
                    else:
                         # Update neighbors 0
                         mb_x = mb_idx % (sps.pic_width_in_mbs_minus1 + 1)
                         mb_y = mb_idx // (sps.pic_width_in_mbs_minus1 + 1)
                         if not hasattr(self, 'neighbor_coeffs'): self.neighbor_coeffs = {}
                         self.neighbor_coeffs[(mb_x, mb_y, b)] = 0
                
                mb_entry = {'mb_idx': mb_idx, 'coefficients': coeffs}
                
                # Add bit positions if tracking
                if self.track_positions and hasattr(mb_data, 'coeff_positions'):
                    mb_entry['coeff_positions'] = mb_data.coeff_positions
                
                mbs.append(mb_entry)
                
                current_mb_addr += 1
                slice_mb_idx_counter += 1
                
            except Exception as e:
                print(f"[EXTRACT_ERROR] MB {slice_mb_idx_counter}: {type(e).__name__}: {str(e)[:200]}")
                break

        
        result = {
            'frame_idx': idx,
            'macroblocks': mbs,
            'total_coefficients': len(mbs) * 384,
            'non_zero_count': sum(sum(1 for c in mb['coefficients'] if c != 0) for mb in mbs)
        }
        
        # Add bitstream data if tracking positions
        if self.track_positions:
            result['bitstream_data'] = original_bitstream
        
        return result
    
    def extract_coefficients_from_nal(self, nal, global_mb_idx: int = 0, sps=None, pps=None) -> Optional[Dict]:
        """
        Extract coefficients from a single NAL unit for BitstreamReconstructor.
        
        Args:
            nal: NAL unit to extract from
            global_mb_idx: Starting macroblock index (unused, for compatibility)
            sps: SPS data from video (optional, uses defaults if None)
            pps: PPS data from video (optional, uses defaults if None)
            
        Returns:
            Dict with 'blocks' key containing {(mb_idx, block_idx): [coeffs]} mapping
        """
        # Simple SPS/PPS with defaults if not provided
        if sps is None:
            sps = SPSData()
        if pps is None:
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
            cavlc_decoder = CAVLCDecoder(reader, skip_constraint_fixing=self.skip_constraint_fixing)
            
            blocks = {}  # {(mb_idx, block_idx): [16 coeffs]}
            mb_metadata = {}  # {mb_idx: {'mb_type': ..., 'cbp': ...}}
            
            # Reset neighbor context (CRITICAL for proper nC calculation)
            self.neighbor_coeffs = {}
            
            # Use same robust extraction as _extract_slice
            max_mbs_in_frame = (sps.pic_width_in_mbs_minus1 + 1) * (sps.pic_height_in_map_units_minus1 + 1)
            total_bits = len(reader.data) * 8
            slice_mb_idx = 0
            current_mb_addr = slice_header.first_mb_in_slice
            
            # Loop while there are enough bits for at least one more MB
            while (total_bits - reader.position) > 8 and slice_mb_idx < max_mbs_in_frame:
                mb_idx = current_mb_addr
                try:
                    # Use FULL macroblock parsing (same as _extract_slice)
                    mb_data = mb_parser.parse_macroblock()
                    
                    # Store MB metadata - use correct attribute names from MacroblockData
                    mb_metadata[mb_idx] = {
                        'mb_type': mb_data.mb_type if hasattr(mb_data, 'mb_type') else 0,
                        'cbp': mb_data.coded_block_pattern if hasattr(mb_data, 'coded_block_pattern') else 0
                    }
                    
                    # Determine blocks to decode (use MacroblockParser's logic)
                    luma_blocks = mb_parser.get_luma_blocks_to_decode(mb_data)
                    
                    # Decode all 24 blocks
                    for block_idx in range(24):
                        should_decode = False
                        
                        if block_idx < 16:  # Luma
                            should_decode = (block_idx in luma_blocks)
                        elif block_idx < 20:  # Chroma DC
                            should_decode = mb_data.chroma_dc_present if hasattr(mb_data, 'chroma_dc_present') else False
                        elif block_idx < 24:  # Chroma AC
                            should_decode = mb_data.chroma_ac_present if hasattr(mb_data, 'chroma_ac_present') else False
                        
                        if should_decode:
                            # Calculate nC with neighbor context (CRITICAL)
                            mb_x = mb_idx % (sps.pic_width_in_mbs_minus1 + 1)
                            mb_y = mb_idx // (sps.pic_width_in_mbs_minus1 + 1)
                            nC = mb_parser.calculate_nC(mb_x, mb_y, block_idx, self.neighbor_coeffs)
                            
                            # Decode block with proper nC
                            debug_key = (mb_idx, block_idx) if (mb_idx == 0 and block_idx == 2) else None
                            block = cavlc_decoder.decode_block_cavlc(nC, 16, debug_key=debug_key)
                            
                            # DEBUG: Log first few blocks
                            if mb_idx == 0 and block_idx == 2:
                                print(f"[EXTRACT_DEBUG] MB0 Block2: total_coeffs={block.total_coeffs}, levels={block.levels}")
                            
                            # CRITICAL: Only store if block has non-zero coefficients
                            # This prevents BitstreamReconstructor from getting spurious zero blocks
                            if block.total_coeffs > 0:
                                blocks[(mb_idx, block_idx)] = block.levels
                            
                            # Update neighbor context (CRITICAL for next MB)
                            self.neighbor_coeffs[(mb_x, mb_y, block_idx)] = block.total_coeffs
                        else:
                            # Block not coded (CBP=0 for this block) - update neighbor context only
                            # Don't add to blocks dict - BitstreamReconstructor will use zeros
                            mb_x = mb_idx % (sps.pic_width_in_mbs_minus1 + 1)
                            mb_y = mb_idx // (sps.pic_width_in_mbs_minus1 + 1)
                            self.neighbor_coeffs[(mb_x, mb_y, block_idx)] = 0
                    
                    current_mb_addr += 1
                    slice_mb_idx += 1
                    
                except Exception as e:
                    # Only log if it's not expected end-of-stream
                    if (total_bits - reader.position) > 8:
                        print(f"[extract_coefficients_from_nal] MB {mb_idx} error: {type(e).__name__}")
                    break
            
            return {'blocks': blocks, 'mb_metadata': mb_metadata}
            
        except Exception as e:
            print(f"[SimpleCAVLCExtractor] extract_coefficients_from_nal error: {e}")
            return None
    
    def get_all_coefficients_flat(self, frames: List[Dict]) -> List[int]:
        result = []
        for frame in frames:
            for mb in frame.get('macroblocks', []):
                result.extend(mb.get('coefficients', []))
        return result
