"""
Traceable CAVLC Parser with Bit Offset Tracking

Extends SimpleCAVLCExtractor to track bit positions of each coefficient block.
This enables Smart Patching: direct bit overwrite without re-encoding.
"""

from typing import Dict, Tuple, Optional
from ..decoder.cavlc_extractor_simple import SimpleCAVLCExtractor
from .h264_parser import BitstreamReader
from .nal_handler import SliceHeaderParser, SPSData, PPSData
from .macroblock_parser import MacroblockParser
from .cavlc_decoder import CAVLCDecoder


class TraceableCAVLCParser(SimpleCAVLCExtractor):
    """
    Parser that tracks bit positions while extracting coefficients.
    
    Returns both:
    - blocks: {(mb_idx, block_idx): [coeffs]}
    - offsets: {(mb_idx, block_idx): {'start_bit': int, 'end_bit': int, 'bit_length': int}}
    """
    
    def __init__(self):
        super().__init__()
        self.block_offsets = {}  # Track bit offsets
    
    def extract_with_offsets(self, nal, sps: SPSData, pps: PPSData, global_mb_idx: int = 0) -> Dict:
        """
        Extract coefficients AND track bit offsets for each block.
        
        Args:
            nal: NAL unit to parse
            sps: SPS data
            pps: PPS data
            global_mb_idx: Starting macroblock index
            
        Returns:
            {
                'blocks': {(mb_idx, block_idx): [16 coeffs]},
                'offsets': {(mb_idx, block_idx): {'start_bit': int, 'end_bit': int, 'bit_length': int}},
                'mb_metadata': {mb_idx: {'mb_type': ..., 'cbp': ...}}
            }
        """
        # Reset tracking
        self.block_offsets = {}
        self.neighbor_coeffs = {}
        
        try:
            # CRITICAL: Check if video uses CABAC (not supported)
            if hasattr(pps, 'entropy_coding_mode_flag') and pps.entropy_coding_mode_flag:
                print(f"[TraceableParser] ERROR: Video uses CABAC encoding, not CAVLC!")
                print(f"[TraceableParser] This system only supports Baseline Profile with CAVLC.")
                print(f"[TraceableParser] Please re-encode video with: ffmpeg -i input.mp4 -profile:v baseline -level 3.0 output.h264")
                return {
                    'blocks': {},
                    'offsets': {},
                    'mb_metadata': {},
                    'error': 'CABAC_NOT_SUPPORTED'
                }
            
            # Create reader from NAL data
            reader = BitstreamReader(nal.rbsp_byte)
            
            # Parse slice header
            slice_parser = SliceHeaderParser(reader, nal, sps, pps)
            slice_header = slice_parser.parse()
            
            # Position after slice header
            header_end_pos = reader.position
            
            # Calculate QP
            slice_qp = 26 + pps.pic_init_qp_minus26 + slice_header.slice_qp_delta
            
            mb_parser = MacroblockParser(reader, slice_header.slice_type)
            cavlc_decoder = CAVLCDecoder(reader)
            
            blocks = {}  # {(mb_idx, block_idx): [coeffs]}
            mb_metadata = {}  # {mb_idx: {'mb_type': ..., 'cbp': ...}}
            
            # Calculate max MBs in frame
            max_mbs_in_frame = (sps.pic_width_in_mbs_minus1 + 1) * (sps.pic_height_in_map_units_minus1 + 1)
            mb_width = sps.pic_width_in_mbs_minus1 + 1
            
            print(f"[TraceableParser] Max MBs in frame: {max_mbs_in_frame}, MB width: {mb_width}")
            
            slice_mb_idx_counter = 0
            current_mb_addr = slice_header.first_mb_in_slice
            
            total_bits = len(reader.data) * 8
            
            # Parse all MBs in slice (FIXED: use proper termination condition)
            while slice_mb_idx_counter < max_mbs_in_frame:
                # Check if we have enough bits left
                if total_bits - reader.pos <= 8:
                    break
                
                mb_idx = current_mb_addr
                
                try:
                    # Handle mb_skip_run for P/B slices
                    if not mb_parser.is_i_slice:
                        mb_skip_run = reader.read_ue()
                        if mb_skip_run > 0:
                            # Skip MBs - all zero coefficients
                            for skip_i in range(mb_skip_run):
                                skip_mb_idx = current_mb_addr + skip_i
                                
                                # Record all blocks as zero with NO offset (not coded)
                                for block_idx in range(24):
                                    blocks[(skip_mb_idx, block_idx)] = [0] * 16
                                    # Skip blocks don't have offsets (not in bitstream)
                                
                                mb_metadata[skip_mb_idx] = {
                                    'mb_type': None,
                                    'cbp': 0,
                                    'is_skip_mb': True
                                }
                                slice_mb_idx_counter += 1
                            
                            current_mb_addr += mb_skip_run
                            mb_idx = current_mb_addr
                    
                    # Parse MB header
                    pos_before_mb = reader.position
                    try:
                        mb_data = mb_parser.parse_macroblock()
                    except Exception as header_err:
                        if mb_idx < 10:
                            print(f"    [MB_HDR_ERR] MB={mb_idx}: {header_err}")
                        # Skip this MB and continue
                        current_mb_addr += 1
                        slice_mb_idx_counter += 1
                        continue
                    
                    # Determine MB type and decoding order
                    is_i16x16 = mb_data.mb_type >= 1 and mb_data.mb_type <= 24
                    luma_blocks = mb_parser.get_luma_blocks_to_decode(mb_data)
                    
                    # Debug for first few MBs (EXTENDED TO MB 5 FOR DEBUGGING)
                    if mb_idx <= 5:
                        print(f"    [MB{mb_idx}] type={mb_data.mb_type}, CBP={mb_data.coded_block_pattern}, is_i16x16={is_i16x16}, luma_blocks={len(luma_blocks)}")
                    
                    # Store MB metadata
                    mb_metadata[mb_idx] = {
                        'mb_type': mb_data.mb_type,
                        'cbp': mb_data.coded_block_pattern,
                        'is_skip_mb': mb_data.coded_block_pattern == 0,
                        'is_i16x16': is_i16x16
                    }
                    
                    # CRITICAL FIX: Parse I_16x16 DC block first (H.264 spec 8.5.6)
                    if is_i16x16:
                        # Parse Intra16x16DCLevel (4x4 DC coefficients)
                        try:
                            luma_dc_block = cavlc_decoder.decode_block_cavlc(nC=-1, max_num_coeff=16)
                            if mb_idx <= 5:
                                pos_after = reader.position
                                print(f"    [I16DC] MB={mb_idx}: TC={luma_dc_block.total_coeffs}")
                        except Exception as e:
                            pass  # Skip on error
                    
                    # Parse luma AC blocks (0-15) for all MB types
                    luma_parsed_count = 0
                    for block_idx in range(16):
                        should_decode = (block_idx in luma_blocks)
                        
                        if should_decode:
                            # Calculate nC from neighbors
                            mb_x = mb_idx % mb_width
                            mb_y = mb_idx // mb_width
                            
                            cache_key = (mb_idx, block_idx)
                            
                            # CRITICAL: calculate_nC expects (mb_global, blk) format in dict
                            # We're using cache_key = (mb_idx, block_idx) which IS mb_global format
                            # Pass mb_width to signal we're using global addressing
                            nC = mb_parser.calculate_nC(mb_x, mb_y, block_idx, self.neighbor_coeffs, mb_width=mb_width)
                            
                            # 🔑 KEY: Track bit position BEFORE decoding
                            block_start_bit = reader.position
                            
                            try:
                                # Decode block (use 15 coeffs for I_16x16 AC, 16 for others)
                                max_coeffs = 15 if is_i16x16 else 16
                                block = cavlc_decoder.decode_block_cavlc(nC, max_coeffs)
                                
                                # 🔑 KEY: Track bit position AFTER decoding
                                block_end_bit = reader.position
                                
                                # SANITY CHECK: TC must be in [0, max_coeffs] — reject desync'd blocks
                                if block.total_coeffs < 0 or block.total_coeffs > max_coeffs:
                                    raise ValueError(f"TC={block.total_coeffs} out of valid range [0,{max_coeffs}] — parser desync!")
                                
                                # CRITICAL FIX: Always store 16 coefficients (pad if I_16x16 AC)
                                # Encoder expects 16-element arrays for 4x4 blocks
                                coeffs_16 = block.levels[:16] + [0] * (16 - len(block.levels))
                                
                                # Store coefficients
                                blocks[cache_key] = coeffs_16
                                
                                # 🎯 CRITICAL: Store bit offset ONLY if block has actual bits
                                # If bit_length=0, it means decode_vlc failed and rewound the reader.
                                # That signals a VLC decode failure — no real bitstream data here.
                                # Storing bit_length=0 offsets causes patcher to try patching 0-bit
                                # regions (always fails with our_enc=N vs NAL=0 mismatch).
                                if block_end_bit > block_start_bit:
                                    self.block_offsets[cache_key] = {
                                        'start_bit': block_start_bit,
                                        'end_bit': block_end_bit,
                                        'bit_length': block_end_bit - block_start_bit,
                                        'nC': nC  # CRITICAL: Store nC for BitstreamPatcher
                                    }
                                # else: bit_length==0 → VLC decode failure (reader rewound) — no valid offset
                                
                                # Update neighbor cache WITH SAME KEY FORMAT
                                # CRITICAL: Clamp to valid range [0,16] to prevent nC corruption
                                self.neighbor_coeffs[cache_key] = min(max(block.total_coeffs, 0), 16)
                                
                                luma_parsed_count += 1
                                
                            except Exception as decode_err:
                                # Decoder failed - use zeros
                                blocks[cache_key] = [0] * 16
                                self.neighbor_coeffs[cache_key] = 0
                                
                                # Log decode failures for debugging
                                if mb_idx < 3:
                                    err_msg = str(decode_err)[:60]
                                    print(f"        [DECODE_ERR] MB={mb_idx}, Blk={block_idx}: {err_msg}")
                                
                                # No offset stored for failed blocks
                        else:
                            # Block not coded - all zeros
                            cache_key = (mb_idx, block_idx)
                            blocks[cache_key] = [0] * 16
                            self.neighbor_coeffs[cache_key] = 0
                            # No offset (block not in bitstream)
                    
                    # Debug luma parsing summary
                    if mb_idx <= 5:
                        print(f"    [LUMA] MB={mb_idx}: Parsed {luma_parsed_count}/{len(luma_blocks)} blocks")
                    
                    # CRITICAL FIX: Parse ChromaDC and ChromaAC blocks (H.264 spec Table 7-11)
                    # cbp_chroma = bits 5:4 of CBP (together, not independently)
                    #   0 = no chroma residual
                    #   1 = chroma DC only
                    #   2 = chroma DC + chroma AC
                    cbp = mb_data.coded_block_pattern
                    cbp_chroma = (cbp >> 4) & 3  # 2-bit field: bits 5 and 4
                    chroma_dc_present = cbp_chroma >= 1
                    chroma_ac_present = cbp_chroma >= 2
                    
                    if chroma_dc_present:
                        pos_before_cdc = reader.position
                        # Parse 2 ChromaDC blocks (Cb and Cr, each 2x2)
                        for chroma_idx in range(2):  # 0=Cb, 1=Cr
                            try:
                                # nC for ChromaDC = -1 (Table 9-4)
                                chroma_dc_block = cavlc_decoder.decode_block_cavlc(nC=-1, max_num_coeff=4)
                                # Parse to advance bitstream
                            except:
                                pass  # Skip on error
                        pos_after_cdc = reader.position
                        if mb_idx <= 5:
                            print(f"    [CDC] MB={mb_idx}: 2 blocks, bits={pos_after_cdc - pos_before_cdc}, pos={pos_before_cdc}->{pos_after_cdc}")
                    
                    if chroma_ac_present:
                        pos_before_cac = reader.position
                        # Parse 8 ChromaAC blocks (4 Cb + 4 Cr, each 4x4 minus DC)
                        for chroma_block_idx in range(8):  # blocks 16-23
                            try:
                                # nC for ChromaAC = 0 (simplified, full calc is complex)
                                chroma_ac_block = cavlc_decoder.decode_block_cavlc(nC=0, max_num_coeff=15)
                                # Parse to advance bitstream
                            except:
                                pass  # Skip on error
                        pos_after_cac = reader.position
                        if mb_idx <= 5:
                            print(f"    [CAC] MB={mb_idx}: 8 blocks, bits={pos_after_cac - pos_before_cac}, pos={pos_before_cac}->{pos_after_cac}")
                    
                    # Debug: Show MB summary for first few MBs
                    if mb_idx <= 5:
                        pos_after_mb = reader.position
                        print(f"    [MB_END] MB={mb_idx}: Total bits={pos_after_mb - pos_before_mb}, pos={pos_before_mb}->{pos_after_mb}\n")
                    
                    current_mb_addr += 1
                    slice_mb_idx_counter += 1
                    
                except Exception as mb_err:
                    print(f"[TraceableParser] MB {slice_mb_idx_counter} error: {mb_err}")
                    break
            
            print(f"[TraceableParser] Extracted {len(blocks)} blocks with {len(self.block_offsets)} offsets")
            
            return {
                'blocks': blocks,
                'offsets': self.block_offsets,
                'mb_metadata': mb_metadata,
                'num_mbs': slice_mb_idx_counter  # CRITICAL: actual MB count including SKIP MBs
            }
            
        except Exception as e:
            print(f"[TraceableParser] Extraction error: {e}")
            import traceback
            traceback.print_exc()
            return {
                'blocks': {},
                'offsets': {},
                'mb_metadata': {}
            }
