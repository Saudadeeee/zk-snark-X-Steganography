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
    
    def extract_from_video(self, video_path: str, max_frames: Optional[int] = None) -> List[Dict]:
        parser = H264BitstreamParser(video_path)
        nal_units = parser.parse()  # No argument needed
        
        # Track nC values for each block: {(mb_idx, block_idx): nC}
        self.nC_map = {}
        
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
            # Parse SPS fields per H.264 spec
            profile_idc = reader.read_bits(8)
            constraint_flags = reader.read_bits(8)
            level_idc = reader.read_bits(8)
            seq_parameter_set_id = reader.read_ue()
            
            # High Profile extensions (profile 100, 110, 122, 244, 44, etc.)
            high_profiles = [100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135]
            if profile_idc in high_profiles:
                chroma_format_idc = reader.read_ue()
                if chroma_format_idc == 3:
                    separate_colour_plane_flag = reader.read_bits(1)
                
                bit_depth_luma_minus8 = reader.read_ue()
                bit_depth_chroma_minus8 = reader.read_ue()
                qpprime_y_zero_transform_bypass_flag = reader.read_bits(1)
                seq_scaling_matrix_present_flag = reader.read_bits(1)
                
                if seq_scaling_matrix_present_flag:
                    # Skip scaling lists (complex, 8 lists for 4:2:0)
                    num_lists = 12 if chroma_format_idc != 3 else 8
                    for i in range(num_lists):
                        seq_scaling_list_present_flag = reader.read_bits(1)
                        if seq_scaling_list_present_flag:
                            # Skip actual scaling list data
                            size = 16 if i < 6 else 64
                            last_scale = 8
                            next_scale = 8
                            for j in range(size):
                                if next_scale != 0:
                                    delta_scale = reader.read_se()
                                    next_scale = (last_scale + delta_scale + 256) % 256
                                last_scale = next_scale if next_scale != 0 else last_scale
            
            sps.log2_max_frame_num_minus4 = reader.read_ue()
            sps.pic_order_cnt_type = reader.read_ue()
            
            if sps.pic_order_cnt_type == 0:
                sps.log2_max_pic_order_cnt_lsb_minus4 = reader.read_ue()
            elif sps.pic_order_cnt_type == 1:
                # Additional fields for POC type 1
                delta_pic_order_always_zero_flag = reader.read_bits(1)
                offset_for_non_ref_pic = reader.read_se()
                offset_for_top_to_bottom_field = reader.read_se()
                num_ref_frames_in_pic_order_cnt_cycle = reader.read_ue()
                for i in range(num_ref_frames_in_pic_order_cnt_cycle):
                    offset_for_ref_frame = reader.read_se()
            
            num_ref_frames = reader.read_ue()
            gaps_in_frame_num_value_allowed_flag = reader.read_bits(1)
            
            # Store dimensions!
            sps.pic_width_in_mbs_minus1 = reader.read_ue()
            sps.pic_height_in_map_units_minus1 = reader.read_ue()
            sps.frame_mbs_only_flag = reader.read_bits(1) == 1
            
            print(f"[SPS] Profile={profile_idc}, Dimensions={sps.pic_width_in_mbs_minus1+1}x{sps.pic_height_in_map_units_minus1+1} MBs")
            
        except Exception as e:
            print(f"[CAVLC Extractor] SPS parsing error: {e}")
            import traceback
            traceback.print_exc()

    def _parse_pps(self, nal, pps):
        """Parse PPS NAL unit to update PPSData object"""
        try:
            reader = BitstreamReader(nal.rbsp_byte)
            pic_parameter_set_id = reader.read_ue()
            seq_parameter_set_id = reader.read_ue()
            entropy_coding_mode_flag = reader.read_bits(1)
            bottom_field_pic_order_in_frame_present_flag = reader.read_bits(1)
            num_slice_groups_minus1 = reader.read_ue()
            
            pps.num_ref_idx_l0_default_active_minus1 = reader.read_ue()
            pps.num_ref_idx_l1_default_active_minus1 = reader.read_ue()
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
        self.chroma_neighbor_coeffs = {}  # {(mb_addr, comp, blk_in_comp): total_coeffs} for AC chroma
        
        # Create reader from NAL data
        reader = BitstreamReader(nal.rbsp_byte)
        
        # Parse slice header using same method as reconstructor
        slice_parser = SliceHeaderParser(reader, nal, sps, pps)
        slice_header = slice_parser.parse()
        
        # Calculate QP from PPS init QP + slice QP delta
        slice_qp = 26 + pps.pic_init_qp_minus26 + slice_header.slice_qp_delta
        
        # Current position is after slice header
        header_bits_end = reader.position
        
        # PRIORITY 1: Log slice type for debugging
        slice_type_names = {0: 'P', 1: 'B', 2: 'I', 3: 'SP', 4: 'SI', 5: 'P', 6: 'B', 7: 'I', 8: 'SP', 9: 'SI'}
        slice_type_name = slice_type_names.get(slice_header.slice_type, f'UNKNOWN({slice_header.slice_type})')
        print(f"  Slice header: Type={slice_type_name} (code={slice_header.slice_type}), QP={slice_qp}, reader at bit {header_bits_end}")
        
        # Determine effective num_ref_idx_l0_active_minus1 for motion vector parsing in P-frames
        # Use the slice header override if present, otherwise fall back to PPS default
        if slice_header.num_ref_idx_active_override_flag:
            num_ref_idx_l0 = slice_header.num_ref_idx_l0_active_minus1
        else:
            num_ref_idx_l0 = pps.num_ref_idx_l0_default_active_minus1

        mb_parser = MacroblockParser(reader, slice_header.slice_type,
                                     num_ref_idx_l0_active_minus1=num_ref_idx_l0)
        cavlc_decoder = CAVLCDecoder(reader)

        mbs = []
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
                # H.264 Section 7.3.4: For P/B slices, MUST read mb_skip_run before mb_data
                # This indicates number of consecutive skip MBs (no residuals)
                if not mb_parser.is_i_slice:
                    mb_skip_run = reader.read_ue()
                    if mb_skip_run > 0:
                        # Skip these MBs - they have no coded residuals
                        for skip_i in range(mb_skip_run):
                            skip_mb_idx = current_mb_addr + skip_i
                            skip_coeffs = [0] * 384  # All zero coefficients
                            mbs.append({
                                'mb_idx': skip_mb_idx,
                                'coefficients': skip_coeffs,
                                'cbp': 0,
                                'mb_type': None,
                                'is_skip_mb': True
                            })
                            slice_mb_idx_counter += 1
                        # Advance address past skip MBs
                        current_mb_addr += mb_skip_run
                        mb_idx = current_mb_addr
                
                # Log reader position before parsing (for debugging if needed)
                pos_before_mb = reader.position
                
                # CRITICAL FIX: Use try-except to recover from MB parsing errors
                try:
                    # Use robust parsing from MacroblockParser
                    mb_data = mb_parser.parse_macroblock()
                    
                    # Additional validation: Check if mb_data looks reasonable
                    if mb_data.mb_type > 100:  # Sanity check
                        raise ValueError(f"Unreasonable mb_type={mb_data.mb_type}, likely corrupted")
                    if mb_data.coded_block_pattern > 47:
                        # Already clamped in parser, but check anyway
                        print(f"[WARN] MB {mb_idx}: CBP was out of range and was clamped")
                    
                except Exception as mb_parse_error:
                    # RECOVERY: Skip this corrupted MB and continue
                    print(f"[ERROR] MB {mb_idx} parsing failed: {mb_parse_error}")
                    print(f"[RECOVERY] Skipping corrupted MB {mb_idx}, inserting zeros")
                    
                    # Create zero MB as placeholder
                    zero_coeffs = [0] * 384
                    mbs.append({
                        'mb_idx': mb_idx,
                        'coefficients': zero_coeffs,
                        'cbp': 0,
                        'mb_type': 'CORRUPTED',
                        'is_skip_mb': False
                    })
                    
                    # Advance to next MB - try to resync by advancing some bits
                    # This is heuristic - advance by average MB size (~200-500 bits)
                    try:
                        reader.read_bits(min(300, total_bits - reader.pos - 16))  # Skip ~300 bits
                    except:
                        pass  # If we can't skip, we're near end anyway
                    
                    current_mb_addr += 1
                    slice_mb_idx_counter += 1
                    continue  # Skip to next MB
                
                # pos_after = reader.position
                # bits_consumed = pos_after - pos_before
                
                # Coefficients are NOT parsed by parse_macroblock (it only does header/prediction)
                # But wait, does parse_macroblock parse residuals?
                # Looking at MacroblockParser outline (Step 613), it calculates luma_blocks_to_decode.
                # It does NOT seem to contain a loop calling cavlc_decoder.
                # So we must parse residuals here.
                
                # Determine blocks to decode
                luma_blocks = mb_parser.get_luma_blocks_to_decode(mb_data)

                # Parse them
                coeffs = [0] * 384

                mb_global_addr = current_mb_addr
                mb_width = sps.pic_width_in_mbs_minus1 + 1
                mb_x = mb_global_addr % mb_width
                mb_y = mb_global_addr // mb_width
                if not hasattr(self, 'neighbor_coeffs'): self.neighbor_coeffs = {}

                # CRITICAL FIX: For I_16x16 MBs, the luma DC block (4x4, 16 coeffs)
                # ALWAYS precedes the luma AC blocks in the bitstream.
                # If we don't consume it, all subsequent block reads are desynchronized.
                # Block index -1 is used as a virtual key for the I_16x16 DC block.
                if mb_parser._is_i16x16(mb_data.mb_type_enum):
                    # nC for I_16x16 luma DC: per H.264 spec Section 9.2.1, nC is
                    # derived ONLY from adjacent I_16x16 DC neighbors (key -1).
                    # If a neighbor is NOT I_16x16 (e.g. I_4x4), it does NOT contribute
                    # (nA/nB = 0, not available). Using regular 4x4 block TCs as fallback
                    # is WRONG: it gives nC=13 when nC=0 is correct, causing 5+ bit
                    # over-consumption via FLC6 table instead of 1-bit VLC → desync.
                    left_mb_dc_tc = None
                    top_mb_dc_tc = None
                    if mb_x > 0:
                        left_mb_addr = mb_y * mb_width + (mb_x - 1)
                        left_mb_dc_tc = self.neighbor_coeffs.get((left_mb_addr, -1))
                        # NOTE: Do NOT fall back to regular 4x4 block TC here
                    if mb_y > 0:
                        top_mb_addr = (mb_y - 1) * mb_width + mb_x
                        top_mb_dc_tc = self.neighbor_coeffs.get((top_mb_addr, -1))
                        # NOTE: Do NOT fall back to regular 4x4 block TC here
                    if left_mb_dc_tc is not None and top_mb_dc_tc is not None:
                        nC_dc = (left_mb_dc_tc + top_mb_dc_tc + 1) >> 1
                    elif left_mb_dc_tc is not None:
                        nC_dc = left_mb_dc_tc
                    elif top_mb_dc_tc is not None:
                        nC_dc = top_mb_dc_tc
                    else:
                        nC_dc = 0  # No I_16x16 DC neighbors → encoder uses nC=0
                    try:
                        dc_block = cavlc_decoder.decode_block_cavlc(nC_dc, 16)
                        self.neighbor_coeffs[(mb_global_addr, -1)] = dc_block.total_coeffs
                    except Exception:
                        self.neighbor_coeffs[(mb_global_addr, -1)] = 0

                # We need all 24 blocks ordered 0..23
                # luma_blocks contains indices 0..15.
                # chroma blocks? parse_macroblock handles cbp decoding.
                # We need to trust cbp from mb_data.

                # Iterate all 24 potential blocks
                cavlc_block_failed = False
                for b in range(24):
                    should_decode = False
                    if b < 16:
                        should_decode = (b in luma_blocks)
                    elif b < 20: # Chroma DC (blocks 16-19)
                         # SKIP Chroma DC - use special 2x2 Hadamard transform (not implemented)
                         # For now, leave as zeros to avoid decoder errors
                         should_decode = False  # Was: mb_data.chroma_dc_present
                    elif b < 24: # Chroma AC (blocks 20-23)
                         # SKIP Chroma AC for now - often causes decode errors
                         # Only embed in luma blocks (0-15) which decode reliably
                         should_decode = False  # Was: mb_data.chroma_ac_present
                    
                    if should_decode:
                         # PRIORITY 3 FIX: Use GLOBAL MB address for neighbor cache
                         # Global MB address = first_mb_in_slice + current offset within slice
                         mb_global_addr = current_mb_addr  # This is already global!
                         mb_width = sps.pic_width_in_mbs_minus1 + 1
                         mb_x = mb_global_addr % mb_width
                         mb_y = mb_global_addr // mb_width
                         
                         if not hasattr(self, 'neighbor_coeffs'): self.neighbor_coeffs = {}
                         
                         # Use global MB address as cache key (NOT local mb_x, mb_y which reset per slice)
                         cache_key = (mb_global_addr, b)
                         nC = mb_parser.calculate_nC(mb_x, mb_y, b, self.neighbor_coeffs, mb_width=mb_width)
                         
                         # Store nC for Safety Filter (CRITICAL FIX)
                         self.nC_map[cache_key] = nC
                         
                         # Track reader position for error debugging
                         pos_before_block = reader.position
                         
                         # 🔴 TWIN LOGGING: Decoder side (log for first MB only)
                         if mb_global_addr == 0 and b < 16:
                             # Peek next 16 bits without consuming
                             peek_bits = reader.peek_bits(16) if hasattr(reader, 'peek_bits') else "N/A"
                             
                             # CORRECT neighbor key calculation using H.264 block scan order
                             # H.264 scan: 0 1 | 4 5
                             #             2 3 | 6 7
                             #             ----+----
                             #             8 9 |12 13
                             #            10 11|14 15
                             # Map to (x,y): (0..3, 0..3)
                             BLOCK_XY = [
                                 (0,0), (1,0), (0,1), (1,1),
                                 (2,0), (3,0), (2,1), (3,1),
                                 (0,2), (1,2), (0,3), (1,3),
                                 (2,2), (3,2), (2,3), (3,3)
                             ]
                             blk_x, blk_y = BLOCK_XY[b]
                             
                             # Left neighbor
                             if blk_x > 0:
                                 left_idx = next((i for i, (x,y) in enumerate(BLOCK_XY) if x==blk_x-1 and y==blk_y), None)
                                 left_key = (mb_global_addr, left_idx) if left_idx is not None else None
                             else:
                                 left_key = None  # Edge (for now, ignore cross-MB)
                             
                             # Top neighbor
                             if blk_y > 0:
                                 top_idx = next((i for i, (x,y) in enumerate(BLOCK_XY) if x==blk_x and y==blk_y-1), None)
                                 top_key = (mb_global_addr, top_idx) if top_idx is not None else None
                             else:
                                 top_key = None  # Edge
                             
                             nA = self.neighbor_coeffs.get(left_key, "edge") if left_key else "edge"
                             nB = self.neighbor_coeffs.get(top_key, "edge") if top_key else "edge"
                             print(f"[DEC] MB:{mb_global_addr} Blk:{b}({blk_x},{blk_y}) nC:{nC} (nA={nA}, nB={nB}) Pos:{pos_before_block} Peek:{peek_bits}")
                         
                         pos_decode_start = reader.position  # Save position BEFORE decode
                         debug_key = (mb_global_addr, b) if mb_global_addr == 0 and b < 16 else None
                         
                         # CRITICAL FIX: Wrap CAVLC decode in try-except for error recovery
                         try:
                             block = cavlc_decoder.decode_block_cavlc(nC, 16, debug_key=debug_key)
                         except Exception as cavlc_error:
                             # CAVLC decode failed - reader position is now unreliable.
                             # Stop decoding remaining blocks to prevent cascade desync.
                             print(f"[ERROR] CAVLC decode failed for MB {mb_global_addr} block {b}: {cavlc_error}")
                             print(f"[RECOVERY] Aborting remaining blocks for this MB to prevent cascade desync")
                             from ..bitstream.cavlc_decoder import CoefficientBlock
                             block = CoefficientBlock(
                                 levels=[0] * 16,
                                 total_coeffs=0,
                                 trailing_ones=0,
                                 total_zeros=0
                             )
                             cavlc_block_failed = True
                         
                         pos_decode_end = reader.position
                         bits_consumed = pos_decode_end - pos_decode_start
                         
                         if mb_global_addr == 0 and b < 16:
                             non_zero = [c for c in block.levels if c != 0]
                             print(f"  -> Consumed {bits_consumed} bits, TC={block.total_coeffs}, Coeffs={non_zero[:3] if non_zero else []}")
                         
                         # Copy into correct position in flattened list
                         # flatten coeffs: blocks 0..23
                         start_idx = b * 16
                         coeffs[start_idx:start_idx+16] = block.levels
                        
                         self.neighbor_coeffs[cache_key] = block.total_coeffs if hasattr(block, 'total_coeffs') else 0
                         if cavlc_block_failed:
                             break  # Stop decoding remaining blocks - reader position is unreliable
                    else:
                         # Update neighbors 0 for skipped blocks
                         mb_global_addr = current_mb_addr
                         if not hasattr(self, 'neighbor_coeffs'): self.neighbor_coeffs = {}
                         # PRIORITY 3: Use global MB address
                         cache_key = (mb_global_addr, b)
                         self.neighbor_coeffs[cache_key] = 0
                
                # Consume chroma residuals to keep reader aligned for next MB.
                # The for-b loop above only decodes luma (b<16). If we don't consume
                # chroma bytes here, the reader stays at chroma data and the next
                # MB's parse_macroblock() reads chroma bytes as MB header → garbage.
                # Skip chroma if luma decode already failed (reader position unreliable).
                # H.264 cbp_chroma = bits[5:4] as a 2-bit field (NOT individual bits).
                cbp_val = mb_data.coded_block_pattern
                cbp_chroma = (cbp_val >> 4) & 3  # 0=no chroma, 1=DC only, 2=DC+AC
                if not cavlc_block_failed and cbp_chroma >= 1:  # Chroma DC present (Cb DC + Cr DC)
                    for _ in range(2):  # nC=-1, 2x2 block → max 4 coeffs
                        try:
                            cavlc_decoder.decode_block_cavlc(-1, 4)
                        except Exception:
                            pass
                if not cavlc_block_failed and cbp_chroma >= 2:  # Chroma AC present (4 Cb AC + 4 Cr AC)
                    # Chroma 2x2 block layout within MB:
                    #   blk=0: (bx=0,by=0)  blk=1: (bx=1,by=0)
                    #   blk=2: (bx=0,by=1)  blk=3: (bx=1,by=1)
                    # CRITICAL: Use only CROSS-MB neighbors (not same-MB chroma blocks).
                    # x264 encodes chroma AC VLC using only neighbors from adjacent MBs.
                    # Using same-MB decoded blocks as neighbors produces incorrect nC values.
                    # Cross-MB left neighbors: only bx=0 blocks (blk0, blk2) touch left MB
                    #   blk0(bx=0,by=0) → left_MB.blk1(bx=1,by=0)
                    #   blk2(bx=0,by=1) → left_MB.blk3(bx=1,by=1)
                    # Cross-MB top neighbors: only by=0 blocks (blk0, blk1) touch top MB
                    #   blk0(bx=0,by=0) → top_MB.blk2(bx=0,by=1)
                    #   blk1(bx=1,by=0) → top_MB.blk3(bx=1,by=1)
                    CHROMA_LEFT_X = [1, None, 3, None]  # cross-MB left blk index (None=interior)
                    CHROMA_TOP_X  = [2, 3, None, None]  # cross-MB top blk index (None=interior)
                    if not hasattr(self, 'chroma_neighbor_coeffs'):
                        self.chroma_neighbor_coeffs = {}
                    for comp in range(2):   # 0=Cb, 1=Cr
                        for blk_in_comp in range(4):
                            # Left neighbor nC (cross-MB only)
                            cross_left = CHROMA_LEFT_X[blk_in_comp]
                            if mb_x > 0 and cross_left is not None:
                                nA = self.chroma_neighbor_coeffs.get((mb_global_addr - 1, comp, cross_left))
                            else:
                                nA = None
                            # Top neighbor nC (cross-MB only)
                            cross_top = CHROMA_TOP_X[blk_in_comp]
                            if mb_y > 0 and cross_top is not None:
                                nB = self.chroma_neighbor_coeffs.get((mb_global_addr - mb_width, comp, cross_top))
                            else:
                                nB = None
                            # Compute nC
                            if nA is not None and nB is not None:
                                nC_chroma = (nA + nB + 1) >> 1
                            elif nA is not None:
                                nC_chroma = nA
                            elif nB is not None:
                                nC_chroma = nB
                            else:
                                nC_chroma = 0
                            try:
                                blk = cavlc_decoder.decode_block_cavlc(nC_chroma, 15)
                                self.chroma_neighbor_coeffs[(mb_global_addr, comp, blk_in_comp)] = blk.total_coeffs
                            except Exception:
                                self.chroma_neighbor_coeffs[(mb_global_addr, comp, blk_in_comp)] = 0

                # CRITICAL: Include CBP metadata to prevent embedding in skip MBs
                mbs.append({
                    'mb_idx': mb_idx, 
                    'coefficients': coeffs,
                    'cbp': mb_data.coded_block_pattern,
                    'mb_type': mb_data.mb_type,
                    'is_skip_mb': mb_data.coded_block_pattern == 0
                })
                
                current_mb_addr += 1
                slice_mb_idx_counter += 1
                
            except Exception as e:
                print(f"[CAVLC Extract] MB {slice_mb_idx_counter} error: {type(e).__name__}: {e}")
                import traceback
                traceback.print_exc()
                break

        
        return {
            'frame_idx': idx,
            'slice_header': slice_header,  # Store parsed slice header for reconstruction
            'macroblocks': mbs,
            'total_coefficients': len(mbs) * 384,
            'non_zero_count': sum(sum(1 for c in mb['coefficients'] if c != 0) for mb in mbs),
            'nC_map': self.nC_map  # CRITICAL: Pass nC values to Safety Filter
        }
    
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
            slice_parser = SliceHeaderParser(reader, nal, sps, pps)  # ← FIX: Pass nal object, not nal.nal_unit_type
            slice_header = slice_parser.parse()
            
            # Calculate QP
            slice_qp = 26 + pps.pic_init_qp_minus26 + slice_header.slice_qp_delta
            
            mb_parser = MacroblockParser(reader, slice_header.slice_type)
            cavlc_decoder = CAVLCDecoder(reader)
            
            blocks = {}  # {(mb_idx, block_idx): [16 coeffs]}
            mb_metadata = {}  # {mb_idx: {'mb_type': ..., 'cbp': ...}}
            
            # Extract ALL macroblocks in the slice (not just 10)
            # CIF format is 352x288 = 22x18 macroblocks = 396 total MBs per frame
            for mb_idx in range(396):  # Extract all MBs
                try:
                    mb_type = mb_parser.parse_macroblock_type_only()
                    
                    cbp = 0
                    # Only process I-slices (types 2 and 7)
                    # P-slices have different MB types and CBP encoding
                    if slice_header.slice_type in [2, 7]:
                        try:
                            cbp = mb_parser._read_coded_block_pattern()
                            if cbp > 0:
                                mb_parser.reader.read_se()
                        except:
                            pass
                    
                    # Store MB metadata (including skip MB flag)
                    mb_metadata[mb_idx] = {
                        'mb_type': mb_type, 
                        'cbp': cbp,
                        'is_skip_mb': cbp == 0
                    }
                    
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
