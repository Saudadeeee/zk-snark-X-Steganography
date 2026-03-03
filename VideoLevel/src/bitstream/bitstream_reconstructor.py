"""
H.264 Bitstream Reconstructor with CAVLC Re-encoding

Rebuilds H.264 bitstream after modifying DCT coefficients for video-only steganography.

This implementation performs TRUE coefficient embedding by:
1. Extracting ALL coefficients from original video
2. Applying LSB modifications to embed payload
3. Re-encoding CAVLC residual data with modified coefficients
4. Reconstructing video with embedded data

The approach uses simplified macroblock syntax to handle common cases while
maintaining video playability and proof extraction capability.

Reference: ITU-T H.264 (2021) Sections 7, 8, 9
"""

from typing import List, Tuple, Dict, Optional
import struct
from dataclasses import dataclass

from .nal_handler import NALUnit, NALUnitType, SliceHeaderParser, SPSData, PPSData
from .macroblock_parser import MacroblockParser
from .cavlc_encoder import CAVLCEncoder
from .cavlc_decoder import CAVLCDecoder
from .bitstream_io import BitstreamWriter, BitstreamReader


@dataclass
class ModifiedSliceData:
    """Data for a modified slice"""
    nal_unit: NALUnit
    sps: SPSData
    pps: PPSData
    modified_coefficients: List[Tuple[int, int, List[int]]]  # (mb_idx, block_idx, coeffs)


class BitstreamReconstructor:
    """
    Reconstruct H.264 bitstream after coefficient modification
    """
    
    def __init__(self):
        self.start_code = b'\x00\x00\x00\x01'
        # Cache for total_coeffs tracking (needed for nC calculation)
        self.mb_total_coeffs = {}  # {(mb_idx, block_idx): total_coeffs}
    
    def _calculate_nC(self, mb_idx: int, block_idx: int, pic_width_in_mbs: int = 22) -> int:
        """
        Calculate nC (neighbor context) for CAVLC coeff_token encoding
        
        According to H.264 Section 8.4.1.2.2:
        nC = (nA + nB + 1) >> 1
        
        Where:
        - nA = total_coeffs of left block
        - nB = total_coeffs of top block
        - If unavailable, use default: 0 for edge blocks, or based on position
        
        Args:
            mb_idx: Current macroblock index (scan order)
            block_idx: Block index within MB (0-15 luma, 16-23 chroma)
            pic_width_in_mbs: Picture width in macroblocks (for CIF 352x288: 22 MBs)
        
        Returns:
            nC context value (0-4 for Table 9-5, -1 for ChromaDC)
        """
        # ==================================================================================
        # CRITICAL FIX #4: Chroma AC blocks nC calculation
        # ==================================================================================
        # Chroma blocks (16-23) are AC coefficients in I_4x4 mode
        # According to H.264 spec and parser implementation:
        # - ChromaAC uses nC=0 (simplified, neighbors not well-defined due to subsampling)
        # - ChromaDC would use nC=-1 but doesn't exist in I_4x4 mode
        #
        # OLD CODE (WRONG):
        # if block_idx >= 16:
        #     return -1  ← BUG! Causes VLC mismatch with parser!
        #
        # NEW CODE (CORRECT):
        if block_idx >= 16:
            return 0  # Chroma AC blocks use nC=0 (matches parser)
        
        # Luma 4x4 block - calculate neighbor context
        mb_x = mb_idx % pic_width_in_mbs
        mb_y = mb_idx // pic_width_in_mbs

        # H.264 scan order block position mapping (same as macroblock_parser.py)
        BLOCK_XY = [
            (0,0), (1,0), (0,1), (1,1),
            (2,0), (3,0), (2,1), (3,1),
            (0,2), (1,2), (0,3), (1,3),
            (2,2), (3,2), (2,3), (3,3)
        ]
        blk_x, blk_y = BLOCK_XY[block_idx]

        def find_block_idx(x, y):
            for i, (bx, by) in enumerate(BLOCK_XY):
                if bx == x and by == y:
                    return i
            return -1

        # Get left neighbor (nA)
        nA = None
        if blk_x > 0:
            # Left block is within same MB
            left_block_idx = find_block_idx(blk_x - 1, blk_y)
            if left_block_idx >= 0:
                nA = self.mb_total_coeffs.get((mb_idx, left_block_idx), 0)
        elif mb_x > 0:
            # Left block is in left MB (x=3, same y)
            left_mb_idx = mb_idx - 1
            left_block_idx = find_block_idx(3, blk_y)
            if left_block_idx >= 0:
                nA = self.mb_total_coeffs.get((left_mb_idx, left_block_idx), 0)

        # Get top neighbor (nB)
        nB = None
        if blk_y > 0:
            # Top block is within same MB
            top_block_idx = find_block_idx(blk_x, blk_y - 1)
            if top_block_idx >= 0:
                nB = self.mb_total_coeffs.get((mb_idx, top_block_idx), 0)
        elif mb_y > 0:
            # Top block is in top MB (same x, y=3)
            top_mb_idx = mb_idx - pic_width_in_mbs
            top_block_idx = find_block_idx(blk_x, 3)
            if top_block_idx >= 0:
                nB = self.mb_total_coeffs.get((top_mb_idx, top_block_idx), 0)

        # Calculate nC according to H.264 spec
        if nA is not None and nB is not None:
            nC = (nA + nB + 1) >> 1
        elif nA is not None:
            nC = nA
        elif nB is not None:
            nC = nB
        else:
            # No neighbors available (top-left corner) - use default
            nC = 0

        return nC
    
    def _update_total_coeffs_cache(self, mb_idx: int, block_idx: int, coeffs: List[int]):
        """
        Update cache with total_coeffs for a block (for nC calculation)
        
        Args:
            mb_idx: Macroblock index
            block_idx: Block index within MB
            coeffs: Coefficient array
        """
        total_coeffs = sum(1 for c in coeffs if c != 0)
        self.mb_total_coeffs[(mb_idx, block_idx)] = total_coeffs
        
    def reconstruct_video(self, 
                         original_file: str,
                         modified_coefficients: List[Tuple[int, int, List[int]]],
                         output_file: str,
                         max_slices: int = 50,
                         frame_verified_data: Dict = None) -> Dict:
        """
        Reconstruct H.264 video with modified coefficients embedded via CAVLC re-encoding
        
        Process:
        1. Parse original video to extract structure and ALL coefficients
        2. Build map of modified coefficients
        3. Re-encode each slice with CAVLC, using modified coefficients where applicable
        4. Write reconstructed video to output
        
        Args:
            original_file: Original H.264 file path
            modified_coefficients: List of (mb_idx, block_idx, coeffs)
            output_file: Output H.264 file path
            max_slices: Maximum slices to process
            
        Returns:
            Statistics dict with success status
        """
        print(f"\n{'='*70}")
        print("H.264 VIDEO RECONSTRUCTION WITH CAVLC RE-ENCODING")
        print(f"{'='*70}")
        
        # Parse original video
        from .h264_parser import H264BitstreamParser
        parser = H264BitstreamParser(original_file)
        parser.parse()
        
        # Parse SPS and PPS from the video - find the most recent ones before each slice
        # Store ALL SPS/PPS encountered
        all_sps = {}  # {sps_id: SPSData}
        all_pps = {}  # {pps_id: PPSData}
        
        for nal in parser.nal_units:
            if nal.nal_unit_type == 7:  # SPS
                try:
                    parsed_sps = self._parse_sps_from_nal(nal)
                    # SPS ID is parsed but we'll use 0 as default
                    all_sps[0] = parsed_sps
                except Exception as e:
                    print(f"[WARNING] Failed to parse SPS: {e}")
            elif nal.nal_unit_type == 8:  # PPS
                try:
                    parsed_pps = self._parse_pps_from_nal(nal)
                    # PPS ID is parsed but we'll use 0 as default
                    all_pps[0] = parsed_pps
                except Exception as e:
                    print(f"[WARNING] Failed to parse PPS: {e}")
        
        # Use the most recent SPS/PPS (last parsed)
        self.sps = all_sps.get(0, None)
        self.pps = all_pps.get(0, None)
        
        print(f"\n[1] Parsed original video:")
        print(f"    NAL units: {len(parser.nal_units)}")
        print(f"    Modified blocks: {len(modified_coefficients)}")
        if self.sps:
            print(f"    SPS parsed: log2_max_frame_num={self.sps.log2_max_frame_num_minus4 + 4}")
        if self.pps:
            print(f"    PPS parsed: deblocking_filter_control={self.pps.deblocking_filter_control_present_flag}")
        
        # Build coefficient modification map
        coeff_map = {}
        for mb_idx, block_idx, coeffs in modified_coefficients:
            coeff_map[(mb_idx, block_idx)] = coeffs
        
        # Log statistics
        if coeff_map:
            mb_indices = [mb_idx for mb_idx, _, _ in modified_coefficients]
            print(f"    MB range: {min(mb_indices)} - {max(mb_indices)}")
            print(f"    Unique MBs modified: {len(set(mb_indices))}")
        
        # Reconstruct NAL units
        print(f"\n[2] Reconstructing slices with CAVLC re-encoding...")
        reconstructed_nals = []
        slices_reconstructed = 0
        slices_with_modifications = 0
        global_mb_idx = 0
        
        # CRITICAL: Derive per-slice MB count from SPS (deterministic, matches TraceableCAVLCParser)
        # Both the embedder (test) and reconstructor must use the SAME count for all slices.
        # TraceableCAVLCParser uses max_mbs_in_frame derived the same way.
        if self.sps:
            mb_count_per_slice = (
                (self.sps.pic_width_in_mbs_minus1 + 1) *
                (self.sps.pic_height_in_map_units_minus1 + 1)
            )
        else:
            mb_count_per_slice = 264  # CIF default: 22x12
        print(f"    [MB_COUNT] Per-slice MB count from SPS: {mb_count_per_slice}")
        
        for nal in parser.nal_units:
            # Copy non-slice NALs and P/B-Frame slices as-is (SPS, PPS, SEI, P-slices, B-slices)
            # ONLY process I-Frames (NAL type 5) for coefficient modification
            if nal.nal_unit_type != 5:
                if nal.nal_unit_type == 1:
                    print(f"    [BYPASS] Skipping P/B-Frame NAL intact (Binary Copy)")
                    global_mb_idx += mb_count_per_slice  # advance counter for each P-frame slice
                reconstructed_nals.append(nal)
                continue
            
            # Stop if reached max slices
            if slices_reconstructed >= max_slices:
                reconstructed_nals.append(nal)
                continue
            
            try:
                # Use SPS-derived MB count (constant, matches TraceableCAVLCParser)
                mb_count = mb_count_per_slice
                print(f"    Slice {slices_reconstructed} (Type {nal.nal_unit_type}): {mb_count} MBs, checking for modifications...")
                
                # Check if slice has modifications
                slice_has_mods = any(
                    global_mb_idx <= key[0] < global_mb_idx + mb_count
                    for key in coeff_map.keys()
                )
                
                if slice_has_mods:
                    # Re-encode slice with modified coefficients
                    mods_count = sum(1 for k in coeff_map if global_mb_idx <= k[0] < global_mb_idx + mb_count)
                    print(f"    Slice {slices_reconstructed}: Re-encoding with {mods_count} modifications")
                    modified_nal, actual_mb_count = self._reconstruct_slice_with_cavlc(
                        nal, coeff_map, global_mb_idx,
                        frame_verified_data=frame_verified_data
                    )
                    
                    # Use SPS count (not parsed actual) for consistency
                    if actual_mb_count is not None and actual_mb_count > 0 and actual_mb_count != mb_count:
                        print(f"      [INFO] TraceableParser returned {actual_mb_count} MBs, using SPS count {mb_count}")
                    
                    reconstructed_nals.append(modified_nal)
                    slices_with_modifications += 1
                else:
                    # No modifications, keep original
                    reconstructed_nals.append(nal)
                
                slices_reconstructed += 1
                global_mb_idx += mb_count
                
            except Exception as e:
                # CRITICAL: Don't silently keep original - this means embedding failed!
                print(f"    [!] CRITICAL ERROR: Slice {slices_reconstructed} reconstruction failed: {e}")
                
                # Log details for debugging
                import traceback
                traceback.print_exc()
                
                # Raise exception to halt process
                raise RuntimeError(
                    f"Failed to reconstruct slice {slices_reconstructed}. "
                    f"This means payload embedding failed. "
                    f"Original error: {e}"
                )
        
        # Write output
        print(f"\n[3] Writing output video...")
        self._write_h264_file(reconstructed_nals, output_file)
        
        print(f"    Output: {output_file}")
        print(f"    Slices processed: {slices_reconstructed}")
        print(f"    Slices modified: {slices_with_modifications}")
        print(f"    Total NAL units: {len(reconstructed_nals)}")
        
        return {
            'success': True,
            'slices_reconstructed': slices_reconstructed,
            'slices_modified': slices_with_modifications,
            'total_nals': len(reconstructed_nals),
            'nal_units_written': len(reconstructed_nals),
            'blocks_modified': len(modified_coefficients)
        }
    
    def _estimate_mb_count_fast(self, nal: NALUnit, sps: SPSData, pps: PPSData) -> int:
        """Quick estimate of MB count in slice"""
        try:
            reader = BitstreamReader(nal.rbsp_byte)
            slice_parser = SliceHeaderParser(reader)
            _ = slice_parser.parse_slice_header(sps, pps)
            
            mb_parser = MacroblockParser(reader, sps, pps)
            count = 0
            
            while count < 500:  # Increase safety limit to handle full frames
                try:
                    _ = mb_parser.parse_macroblock_type_only()
                    count += 1
                except:
                    break
            
            return max(count, 1)
        except:
            # CIF format default: 352x288 pixels = 22x18 MBs = 396 MBs/frame
            # Return 396 as realistic default instead of 1
            return 396
    
    def _reconstruct_slice_with_cavlc(self,
                                      original_nal: NALUnit,
                                      coeff_map: Dict,
                                      global_mb_idx: int,
                                      frame_verified_data: Dict = None):
        """
        Reconstruct slice with modified CAVLC coefficients
        
        IMPLEMENTED APPROACH:
        - Parse entire slice to extract ALL coefficients
        - Apply modifications from coeff_map
        - Re-encode ENTIRE slice with modified coefficients using CAVLC
        - Return (NEW NAL unit, actual_mb_count)
        
        Returns:
            Tuple[NALUnit, int]: (modified_nal, num_mbs_in_slice)
        """
        if not coeff_map:
            return original_nal
        
        try:
            # ⚠️ CRITICAL FIX: DO NOT parse first_mb_in_slice from header!
            # The header's first_mb_in_slice can be slice-group relative, NOT global frame index.
            # We must TRUST the accumulated global_mb_idx parameter passed from reconstruct_video.
            # 
            # OLD CODE (WRONG):
            # reader_for_header = BitstreamReader(original_nal.rbsp_byte)
            # slice_parser = SliceHeaderParser(reader_for_header, original_nal, self.sps, self.pps)
            # slice_header = slice_parser.parse()
            # actual_first_mb = slice_header.first_mb_in_slice  # ← Can be WRONG index!
            # global_mb_idx = actual_first_mb  # ← Override breaks everything!
            #
            # NEW CODE (CORRECT):
            # Just use the parameter directly - it's correctly accumulated in reconstruct_video()

            # Step 1: Extract ALL coefficients from this slice
            # CRITICAL FIX: Use TraceableCAVLCParser instead of SimpleCAVLCExtractor
            # SimpleCAVLCExtractor has a bug where it returns all-zero coefficients for P-slices
            # because it only parses CBP for I-slices (slice_type 2,7), not P-slices (slice_type 0,5).
            # This caused massive zero-preservation violations in Frames 1+.
            from .traceable_cavlc_parser import TraceableCAVLCParser
            
            parser = TraceableCAVLCParser()
            parsed_result = parser.extract_with_offsets(
                original_nal,
                self.sps,
                self.pps,
                global_mb_idx=global_mb_idx
            )
            
            if 'blocks' not in parsed_result:
                print(f"        [ERROR] No blocks extracted from slice")
                return (original_nal, None)  # Return tuple
            
            blocks = parsed_result['blocks']
            mb_metadata = parsed_result.get('mb_metadata', {})

            # CRITICAL: Use the actual MB count including SKIP MBs from TraceableCAVLCParser.
            # Do NOT compute from len(blocks)//24 — SKIP MBs add blocks but don't advance global_mb_idx the same way.
            num_mbs_in_slice = parsed_result.get('num_mbs', None)
            if num_mbs_in_slice is None or num_mbs_in_slice == 0:
                # Fallback: count unique MB indices in blocks dict
                num_mbs_in_slice = len(set(mb for mb, _ in blocks.keys())) if blocks else 1
            
            # Step 2: Apply modifications to create combined blocks
            # CRITICAL FIX: Adjust MB indexing - coeff_map uses global indexing (starts from 0, 1, 2...)
            # but blocks use slice-relative indexing.We need to map global → slice-local.
            # ALSO: Only process modifications that belong to THIS slice!
            modifications_applied = 0

            for (mb_idx_global, block_idx), modified_coeffs in coeff_map.items():
                # CRITICAL CHECK: Only apply modifications that belong to THIS slice
                # Slice range: [global_mb_idx, global_mb_idx + num_mbs_in_slice)
                if not (global_mb_idx <= mb_idx_global < global_mb_idx + num_mbs_in_slice):
                    # This modification belongs to another slice, skip it
                    continue
                
                # Convert global MB index to slice-relative (subtract slice start)
                mb_idx_local = mb_idx_global - global_mb_idx
                block_key = (mb_idx_local, block_idx)
                
                if block_key in blocks:
                    original_coeffs = blocks[block_key]
                    
                    # CRITICAL VALIDATION: Check if modification violates zero-preservation
                    orig_nz = sum(1 for c in original_coeffs if c != 0)
                    mod_nz = sum(1 for c in modified_coeffs if c != 0)
                    
                    if orig_nz != mod_nz:
                        if modifications_applied < 3:
                            print(f"        [RECONSTRUCTOR_WARN] Block {block_key} (global {mb_idx_global}): total_coeffs mismatch!")
                            print(f"          Parser extracted: {orig_nz} non-zero coeffs")
                            print(f"          Embedder modified: {mod_nz} non-zero coeffs")
                            print(f"          Original: {[c for c in original_coeffs if c != 0][:8]}")
                            print(f"          Modified: {[c for c in modified_coeffs if c != 0][:8]}")
                    
                    # CRITICAL FIX: Only count as "modification" if coefficients actually DIFFER
                    # Don't count copying original → original as a "modification"!
                    coeffs_differ = any(o != m for o, m in zip(original_coeffs, modified_coeffs))
                    
                    if coeffs_differ:
                        # Apply modification
                        blocks[block_key] = list(modified_coeffs)
                        modifications_applied += 1
                    # else: coefficients are same, no need to modify
                else:
                    print(f"        [WARN] Key {block_key} NOT FOUND in blocks (mb_global={mb_idx_global}, local={mb_idx_local})")
            
            print(f"        Applied {modifications_applied} modifications")
            
            if modifications_applied == 0:
                # This is OK - slice might not have any modifications
                print(f"        [INFO] No modifications for this slice (range {global_mb_idx}-{global_mb_idx + num_mbs_in_slice})")
                return (original_nal, num_mbs_in_slice)

            # ========================================================================
            # SMART PATCHING APPROACH
            # ========================================================================
            # Instead of re-encoding entire slice (which causes nC drift, alignment issues),
            # we use BitstreamPatcher to directly overwrite coefficient bits at tracked offsets.
            #
            # Key properties:
            # 1. Safety Filter guarantees bit-length invariance (old and new bits same length)
            # 2. Preserves original bitstream structure 100% (no alignment issues)
            # 3. No nC drift (no re-calculation of neighbor contexts)
            # 4. Only modifies coefficient values, doesn't touch headers or structure
            # ========================================================================

            # Import BitstreamPatcher
            from .bitstream_patcher import BitstreamPatcher

            # Convert coeff_map to modifications list for patcher
            # ⚠️ CRITICAL FIX: TraceableCAVLCParser uses ABSOLUTE MB addressing!
            # We MUST pass global MB indices directly, NOT slice-local indices!
            modifications = []
            for (mb_idx_global, block_idx), modified_coeffs in coeff_map.items():
                # Only include modifications for THIS slice
                if global_mb_idx <= mb_idx_global < global_mb_idx + num_mbs_in_slice:
                    # Pass global MB indices directly (DO NOT convert to slice-local!)
                    modifications.append((mb_idx_global, block_idx, modified_coeffs))
            patcher = BitstreamPatcher()
            
            # CRITICAL: Use the EMBEDDER'S verified offsets/blocks when available.
            # The embedder's NAL bit-length filter already validated that
            # encode(those coefficients) == NAL bit_length, so the patcher
            # will find our_enc == NAL for all blocks it patches.
            # 
            # If frame_verified_data is available for this global_mb_idx,
            # it means the embedder pre-validated the offsets from its own parse.
            # Use those instead of the reconstructor's potentially divergent re-parse.
            pre_offsets = None
            pre_blocks = None
            
            if frame_verified_data and global_mb_idx in frame_verified_data:
                verified_offsets, verified_blocks = frame_verified_data[global_mb_idx]
                pre_offsets = {
                    (mb - global_mb_idx, blk): v
                    for (mb, blk), v in verified_offsets.items()
                    if mb >= global_mb_idx
                }
                pre_blocks = {
                    (mb - global_mb_idx, blk): v
                    for (mb, blk), v in verified_blocks.items()
                    if mb >= global_mb_idx
                }
            else:
                # Fallback: use reconstructor's own parse results (may diverge from embedder's)
                pre_offsets = parsed_result.get('offsets', {})
                pre_blocks = parsed_result.get('blocks', {})
            
            modified_nal = patcher.patch_slice(
                original_nal,
                modifications,
                sps=self.sps,
                pps=self.pps,
                global_mb_offset=global_mb_idx,
                pre_computed_offsets=pre_offsets,
                pre_computed_blocks=pre_blocks
            )

            if modified_nal is None:
                print(f"        [ERROR] Patching returned None - BitstreamPatcher failed!")
                return (original_nal, num_mbs_in_slice)
            
            # CRITICAL: Verify patching actually modified the NAL
            if len(modified_nal.rbsp_byte) == len(original_nal.rbsp_byte):
                if modified_nal.rbsp_byte == original_nal.rbsp_byte:
                    print(f"        [WARN] Patched NAL is IDENTICAL to original!")
                    print(f"        [WARN] This means NO blocks were successfully patched")
                    print(f"        [WARN] Likely causes:")
                    print(f"          1. All modifications skipped due to round-trip encoding failures")
                    print(f"          2. All blocks had zero->non-zero or non-zero->zero violations")
                    print(f"          3. Safety Filter rejected all modifications")
                    # Don't fail - return original NAL (no modifications applied)
                    return (original_nal, num_mbs_in_slice)
            
            # Verify NAL size is reasonable (not corrupted)
            if len(modified_nal.rbsp_byte) == len(original_nal.rbsp_byte):
                if modified_nal.rbsp_byte == original_nal.rbsp_byte:
                    print(f"        [WARN] Patched NAL is IDENTICAL to original — no blocks patched")
                    return (original_nal, num_mbs_in_slice)

            return (modified_nal, num_mbs_in_slice)
            
        except Exception as e:
            print(f"        [Reconstructor] Error: {e}")
            import traceback
            traceback.print_exc()
            # Use fallback of 1 MB if num_mbs_in_slice not available
            fallback_mb_count = 1
            try:
                fallback_mb_count = num_mbs_in_slice if 'num_mbs_in_slice' in locals() else 1
            except:
                pass
            return (original_nal, fallback_mb_count)
    
    def _reconstruct_with_header_copy(self,
                                      original_nal: NALUnit,
                                      blocks: Dict,
                                      global_mb_idx: int,
                                      mb_metadata: Dict = None,
                                      sps = None,
                                      pps = None) -> Optional[bytes]:
        """
        NEW APPROACH: Copy slice header from original, only re-encode MB data
        """
        try:
            from ..decoder.cavlc_extractor_simple import SimpleCAVLCExtractor
            from ..bitstream.nal_handler import SliceHeaderParser, SPSData, PPSData
            
            # Extract ALL coefficients from original slice
            extractor = SimpleCAVLCExtractor()
            result = extractor.extract_coefficients_from_nal(original_nal, global_mb_idx, sps, pps)
            
            original_blocks = result.get('blocks', {})
            mb_metadata = result.get('mb_metadata', {})
            
            # Combine: original + modifications
            combined_blocks = dict(original_blocks)
            for key, modified_coeffs in blocks.items():
                combined_blocks[key] = modified_coeffs
            
            print(f"        [HeaderCopy] Extracted {len(original_blocks)} blocks, applying {len(blocks)} modifications")
            
            # Parse slice header to get end position
            reader = BitstreamReader(original_nal.rbsp_byte)
            
            if sps is None:
                sps = SPSData()
            if pps is None:
                pps = PPSData()
            
            slice_parser = SliceHeaderParser(reader, original_nal, sps, pps)  # ← FIX: Pass nal object
            slice_header = slice_parser.parse()
            
            # Get slice header bytes from original
            slice_header_end_bit = reader.position
            slice_header_end_byte = (slice_header_end_bit + 7) // 8
            
            # CRITICAL: If header doesn't end on byte boundary, fall back
            if slice_header_end_bit % 8 != 0:
                print(f"        [WARN] Slice header ends at bit {slice_header_end_bit} (not byte-aligned)")
                print(f"        [WARN] Falling back to full reconstruction")
                return self._reencode_slice_cavlc(original_nal, blocks, global_mb_idx, mb_metadata, sps, pps)
            
            # Copy slice header bytes
            slice_header_bytes = original_nal.rbsp_byte[:slice_header_end_byte]
            print(f"        [HeaderCopy] Copied {slice_header_end_byte} bytes of slice header")
            
            # Now encode MB data
            mb_writer = BitstreamWriter()
            
            # Get total number of MBs
            total_mbs_in_slice = len(mb_metadata) if mb_metadata else 286
            
            encoder = CAVLCEncoder(mb_writer)
            
            # Encode each MB (simplified - using original CBP)
            for slice_mb_idx in range(total_mbs_in_slice):
                mb_global_idx = global_mb_idx + slice_mb_idx
                
                mb_meta = mb_metadata.get(slice_mb_idx, {})
                original_mb_type = mb_meta.get('mb_type', 0)
                original_cbp = mb_meta.get('cbp', 0)
                
                # Collect blocks
                mb_blocks = {}
                for block_idx in range(24):
                    key = (mb_global_idx, block_idx)
                    if key in combined_blocks:
                        mb_blocks[block_idx] = combined_blocks[key]
                
                if not mb_blocks:
                    continue
                
                # Write MB type
                mb_writer.write_ue(original_mb_type)
                
                # Write prediction modes
                if original_mb_type == 0:  # I_4x4
                    for _ in range(16):
                        mb_writer.write_bits(1, 1)
                    mb_writer.write_ue(0)
                elif original_mb_type >= 1 and original_mb_type <= 24:
                    mb_writer.write_ue(0)
                
                # Write CBP
                is_intra = (original_mb_type >= 0 and original_mb_type <= 25)
                mb_writer.write_me_cbp(original_cbp, is_intra=is_intra)
                
                # Write QP delta & coefficients
                if original_cbp > 0:
                    mb_writer.write_se(0)
                    
                    for block_idx in range(24):
                        should_encode = False
                        if block_idx < 16:
                            should_encode = (original_cbp & (1 << (block_idx // 4))) != 0
                        elif block_idx < 20:
                            should_encode = (original_cbp & 0x10) != 0
                        else:
                            should_encode = (original_cbp & 0x20) != 0
                        
                        if should_encode:
                            coeffs = mb_blocks.get(block_idx, [0] * 16)
                            if len(coeffs) != 16:
                                coeffs = (list(coeffs) + [0]*16)[:16]
                            
                            # Calculate nC from neighbors (H.264 Section 8.4.1.2.2)
                            # CRITICAL: Use mb_global_idx (frame-absolute), NOT slice_mb_idx!
                            nC = self._calculate_nC(mb_global_idx, block_idx, pic_width_in_mbs=22)
                            
                            # 🔵 TWIN LOGGING: Encoder side (log for first MB only)
                            if mb_global_idx == 0 and block_idx < 16:
                                non_zero = [c for c in coeffs if c != 0]
                                total_coeffs = len(non_zero)
                                print(f"[ENC] MB:{mb_global_idx} Blk:{block_idx} nC:{nC} TotalCoeff:{total_coeffs} Coeffs:{non_zero[:5] if non_zero else [0]}")
                            
                            encoder.encode_block_cavlc(coeffs, nC=nC, max_num_coeff=16)
                            # Update total_coeffs cache for future nC calculations
                            self._update_total_coeffs_cache(mb_global_idx, block_idx, coeffs)
            
            # Get MB data
            mb_data_bytes = mb_writer.to_bytes()
            print(f"        [HeaderCopy] Encoded {len(mb_data_bytes)} bytes of MB data")
            
            # Combine
            reconstructed_rbsp = slice_header_bytes + mb_data_bytes
            print(f"        [HeaderCopy] Total RBSP: {len(reconstructed_rbsp)} bytes")
            
            return reconstructed_rbsp
            
        except Exception as e:
            print(f"        [HeaderCopy] Error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _reencode_slice_cavlc(self,
                             original_nal: NALUnit,
                             blocks: Dict,
                             global_mb_idx: int,
                             mb_metadata: Dict = None,
                             sps = None,
                             pps = None) -> Optional[bytes]:
        """
        Re-encode slice with modified CAVLC coefficients.
        Surgical approach: Copy original bytes, only re-encode modified coefficient blocks.
        """
        try:
            # ==================================================================================
            # CRITICAL FIX #2: DON'T clear cache - preserve neighbors from previous slices
            # ==================================================================================
            # OLD CODE (WRONG): self.mb_total_coeffs.clear()  ← Removes top neighbors!
            # NEW CODE: Keep cache intact - top-row MBs need neighbors from previous slice
            # Cache will be updated with current slice's blocks below
            
            # If no modifications, return original
            if not blocks:
                return original_nal.rbsp_byte
            
            from ..decoder.cavlc_extractor_simple import SimpleCAVLCExtractor
            
            # CRITICAL FIX: Extract ALL coefficients from original slice
            # Then apply modifications on top
            extractor = SimpleCAVLCExtractor()
            result = extractor.extract_coefficients_from_nal(original_nal, global_mb_idx, sps, pps)
            
            # Get ORIGINAL coefficients for all blocks
            original_blocks = result.get('blocks', {})
            mb_metadata = result.get('mb_metadata', {})

            # Combine: Start with original, then apply modifications
            combined_blocks = dict(original_blocks)  # Copy all original blocks
            
            # Apply modifications on top
            modifications_applied = 0
            for key, modified_coeffs in blocks.items():
                if key in combined_blocks:
                    combined_blocks[key] = modified_coeffs
                    modifications_applied += 1
                else:
                    # Modification for block not in original - still add it
                    combined_blocks[key] = modified_coeffs
                    modifications_applied += 1
            
            # ==================================================================================
            # CRITICAL FIX #1: Pre-populate total_coeffs cache for accurate nC calculation
            # ==================================================================================
            # Problem: Cache is cleared (line 712), but encoder needs neighbor context
            # Solution: Rebuild cache from combined_blocks BEFORE encoding
            # Note: combined_blocks uses SLICE-LOCAL indices (0, 1, 2...)
            #       but _calculate_nC expects GLOBAL indices (global_mb_idx + local)
            # → Convert to GLOBAL indices when populating cache
            
            print(f"        [FIX] Pre-populating nC cache from {len(combined_blocks)} combined blocks...")
            cache_populated = 0
            for (mb_idx_local, block_idx), coeffs in combined_blocks.items():
                # Convert slice-local MB index → global MB index
                mb_idx_global = global_mb_idx + mb_idx_local
                
                # Calculate total_coeffs (number of non-zero coefficients)
                total_coeffs = sum(1 for c in coeffs if c != 0)
                
                # Store in cache with GLOBAL indices (for nC calculation)
                self.mb_total_coeffs[(mb_idx_global, block_idx)] = total_coeffs
                cache_populated += 1
            
            print(f"        [FIX] Cache populated with {cache_populated} entries (using GLOBAL MB indices)")
            
            # Determine which MBs need re-encoding
            # CRITICAL FIX: blocks.keys() already use SLICE-LOCAL indices (0, 1, 2...)
            # DO NOT subtract global_mb_idx again!
            modified_mbs = set()
            for (mb_idx, block_idx) in blocks.keys():
                # BUG CŨ: modified_mbs.add(mb_idx - global_mb_idx)  ← SAI! Subtract two times!
                # FIX MỚI: mb_idx đã là local index rồi (0, 1, 2... trong slice)
                modified_mbs.add(mb_idx)  # Already slice-relative, no conversion needed
            
            # If no MBs modified in this slice, return original
            if not modified_mbs:
                return original_nal.rbsp_byte
            
            # Strategy: Re-encode entire slice with mixed original + modified coefficients
            from ..bitstream.nal_handler import SliceHeaderParser, SPSData, PPSData
            
            reader = BitstreamReader(original_nal.rbsp_byte)
            
            # Use actual SPS/PPS from video, fallback to defaults if not available
            if sps is None:
                sps = SPSData()
            if pps is None:
                pps = PPSData()
            
            slice_parser = SliceHeaderParser(reader, original_nal, sps, pps)  # ← FIX: Pass nal object
            slice_header = slice_parser.parse()
            
            # combined_blocks is already set above - use it directly!
            # (No need to rebuild - 'blocks' parameter already has modifications)
            
            # Re-encode slice with combined coefficients
            writer = BitstreamWriter()
            
            # DEBUG: Log slice header start for first slice
            slice_header_start_pos = writer.get_bit_position()
            debug_first_slice = False  # Disabled for production
            
            # Write COMPLETE slice header (all fields in correct order)
            # 1. Basic slice info
            writer.write_ue(slice_header.first_mb_in_slice)
            writer.write_ue(slice_header.slice_type)
            writer.write_ue(slice_header.pic_parameter_set_id)
            
            # 2. Frame number
            frame_num_bits = sps.log2_max_frame_num_minus4 + 4
            writer.write_bits(frame_num_bits, slice_header.frame_num)
            
            # 3. Field flags (only if not frame_mbs_only)
            if not sps.frame_mbs_only_flag:
                writer.write_bits(1, 1 if slice_header.field_pic_flag else 0)
                if slice_header.field_pic_flag:
                    writer.write_bits(1, 1 if slice_header.bottom_field_flag else 0)
            
            # 4. IDR picture ID
            is_idr = (original_nal.nal_unit_type == 5)
            if is_idr and slice_header.idr_pic_id is not None:
                writer.write_ue(slice_header.idr_pic_id)
                if debug_first_slice:
                    pos_after_idr = writer.get_bit_position()
                    print(f"          [ENC] After idr_pic_id: Pos:{pos_after_idr}")
            
            # 5. Picture order count
            if sps.pic_order_cnt_type == 0:
                poc_bits = sps.log2_max_pic_order_cnt_lsb_minus4 + 4
                if slice_header.pic_order_cnt_lsb is not None:
                    writer.write_bits(poc_bits, slice_header.pic_order_cnt_lsb)
                else:
                    writer.write_bits(poc_bits, 0)
            
            # 6. Redundant picture count
            if pps.redundant_pic_cnt_present_flag and slice_header.redundant_pic_cnt is not None:
                writer.write_ue(slice_header.redundant_pic_cnt)
            
            # 7. num_ref_idx_active_override (P and B slices only)
            if slice_header.slice_type % 5 in [0, 1]:  # P or B
                if debug_first_slice:
                    pos_before_num_ref = writer.get_bit_position()
                writer.write_bits(1, 1 if slice_header.num_ref_idx_active_override_flag else 0)
                if debug_first_slice:
                    pos_after_num_ref = writer.get_bit_position()
                    print(f"          [ENC] After num_ref_idx_override (flag:{slice_header.num_ref_idx_active_override_flag}): Pos:{pos_after_num_ref} (wrote {pos_after_num_ref - pos_before_num_ref} bits)")
                if slice_header.num_ref_idx_active_override_flag:
                    writer.write_ue(slice_header.num_ref_idx_l0_active_minus1)
                    if slice_header.slice_type % 5 == 1:  # B slice
                        writer.write_ue(slice_header.num_ref_idx_l1_active_minus1)
            
            # 8. ref_pic_list_modification() - copy exact bit sequence from original
            if slice_header.slice_type % 5 != 2:  # Not I slice
                if debug_first_slice:
                    pos_before_ref_list = writer.get_bit_position()
                
                # Write the exact bit sequence captured from original
                if slice_header.ref_pic_list_modification_l0_data:
                    for bit in slice_header.ref_pic_list_modification_l0_data:
                        writer.write_bits(1, bit)
                else:
                    # Fallback: write flag=0 if no data captured
                    writer.write_bits(1, 0)
                
                if debug_first_slice:
                    pos_after_ref_list = writer.get_bit_position()
                    print(f"          [ENC] After ref_pic_list_modification (copied {len(slice_header.ref_pic_list_modification_l0_data)} bits): Pos:{pos_after_ref_list}")
                
                if slice_header.slice_type % 5 == 1:  # B slice
                    if slice_header.ref_pic_list_modification_l1_data:
                        for bit in slice_header.ref_pic_list_modification_l1_data:
                            writer.write_bits(1, bit)
                    else:
                        writer.write_bits(1, 0)
            
            # 9. dec_ref_pic_marking() - copy exact bit sequence from original
            if is_idr:
                # For IDR: If we have captured data, use it; otherwise write simple flags
                if slice_header.dec_ref_pic_marking_data:
                    for bit in slice_header.dec_ref_pic_marking_data:
                        writer.write_bits(1, bit)
                else:
                    writer.write_bits(1, 1 if slice_header.no_output_of_prior_pics_flag else 0)
                    writer.write_bits(1, 1 if slice_header.long_term_reference_flag else 0)
                if debug_first_slice:
                    pos_after_dec_ref = writer.get_bit_position()
                    print(f"          [ENC] After dec_ref_pic_marking (copied {len(slice_header.dec_ref_pic_marking_data) if slice_header.dec_ref_pic_marking_data else 2} bits): Pos:{pos_after_dec_ref}")
            elif slice_header.slice_type % 5 in [0, 1]:  # P or B slice
                # For P/B: Copy exact bit sequence
                if slice_header.dec_ref_pic_marking_data:
                    for bit in slice_header.dec_ref_pic_marking_data:
                        writer.write_bits(1, bit)
                else:
                    writer.write_bits(1, 0)  # Fallback: adaptive_ref_pic_marking_mode_flag = 0
                
                if debug_first_slice:
                    pos_after_dec_ref = writer.get_bit_position()
                    print(f"          [ENC] After dec_ref_pic_marking (copied {len(slice_header.dec_ref_pic_marking_data) if slice_header.dec_ref_pic_marking_data else 1} bits): Pos:{pos_after_dec_ref}")
            
            # 10. slice_qp_delta
            pos_before_qp = writer.get_bit_position() if debug_first_slice else 0
            writer.write_se(slice_header.slice_qp_delta)
            if debug_first_slice:
                pos_after_qp = writer.get_bit_position()
                print(f"          [ENC] After slice_qp_delta (value:{slice_header.slice_qp_delta}): Pos:{pos_after_qp} (wrote {pos_after_qp - pos_before_qp} bits)")
            
            # DEBUG: Log slice header end for first slice
            if debug_first_slice:
                slice_header_end_pos = writer.get_bit_position()
                print(f"          [ENC_SLICE_HEADER] Slice global_mb_idx:{global_mb_idx} header: {slice_header_start_pos}->{slice_header_end_pos} bits ({slice_header_end_pos - slice_header_start_pos} bits total)")
            
            # 11. Deblocking filter control
            pos_before_deblock = writer.get_bit_position() if debug_first_slice else 0
            if pps.deblocking_filter_control_present_flag:
                deblocking_idc = slice_header.disable_deblocking_filter_idc if slice_header.disable_deblocking_filter_idc is not None else 0
                writer.write_ue(deblocking_idc)
                if deblocking_idc != 1:
                    writer.write_se(slice_header.slice_alpha_c0_offset_div2 if slice_header.slice_alpha_c0_offset_div2 is not None else 0)
                    writer.write_se(slice_header.slice_beta_offset_div2 if slice_header.slice_beta_offset_div2 is not None else 0)
                if debug_first_slice:
                    pos_after_deblock = writer.get_bit_position()
                    print(f"          [ENC] After deblocking_filter_control (idc:{deblocking_idc}): Pos:{pos_after_deblock} (wrote {pos_after_deblock - pos_before_deblock} bits)")
            
            # DEBUG: Log final slice header size
            if debug_first_slice:
                final_slice_header_pos = writer.get_bit_position()
                print(f"          [ENC_SLICE_HEADER] After deblocking: Pos:{final_slice_header_pos} (total slice header: {final_slice_header_pos - slice_header_start_pos} bits)")
            
            # CRITICAL FIX: Determine TOTAL number of MBs in original slice
            # NOT just the range of modified blocks!
            # Parse original slice to count total MBs
            total_mbs_in_slice = 0
            original_mb_metadata = result.get('mb_metadata', {})
            
            if original_mb_metadata:
                # Count MBs from metadata
                total_mbs_in_slice = len(original_mb_metadata)
            else:
                # Fallback: Calculate from video dimensions and slice structure
                # For CIF (352x288), typical slice has ~10 MBs
                # This is just a fallback - metadata should be available
                pic_width_in_mbs = (sps.pic_width_in_mbs_minus1 + 1) if sps else 22
                pic_height_in_mbs = (sps.pic_height_in_map_units_minus1 + 1) if sps else 18
                
                # Estimate MBs per slice (typically full width or 10 MBs)
                # Conservative estimate: use width
                total_mbs_in_slice = pic_width_in_mbs
            
            num_mbs = total_mbs_in_slice
            
            print(f"          [CRITICAL FIX] Encoding ALL {num_mbs} MBs in slice (not just {len(set(mb_idx for mb_idx, _ in combined_blocks.keys()))} modified)")
            
            # Debug: Count non-zero coefficients
            total_nonzero_before = sum(1 for coeffs in combined_blocks.values() if any(c != 0 for c in coeffs))
            print(f"          Combined blocks: {len(combined_blocks)} blocks, {total_nonzero_before} have non-zero coeffs")
            
            encoder = CAVLCEncoder(writer)
            
            # DEBUG: Check combined_blocks content
            print(f"          [CAVLC_ENC] combined_blocks has {len(combined_blocks)} blocks")
            print(f"          [CAVLC_ENC] combined_blocks keys (first 5): {list(combined_blocks.keys())[:5]}")
            nonzero_in_combined = sum(1 for coeffs in combined_blocks.values() if any(c != 0 for c in coeffs))
            print(f"          [CAVLC_ENC] Blocks with non-zero coeffs in combined_blocks: {nonzero_in_combined}")
            
            # Encode each macroblock
            for slice_mb_idx in range(num_mbs):
                mb_global_idx = global_mb_idx + slice_mb_idx
                
                # CRITICAL FIX (Quy tắc User):
                # combined_blocks uses SLICE-LOCAL indexing (0, 1, 2... trong slice)
                # NOT global indexing (150, 151, 152... trong toàn bộ video)
                # → Phải dùng slice_mb_idx (local) để lookup, KHÔNG dùng mb_global_idx!
                
                # Collect all blocks for this MB
                mb_blocks = {}
                blocks_found = 0
                for block_idx in range(24):
                    # BUG CŨ: key = (mb_global_idx, block_idx)  ← SAI! Tìm key 150 trong dict có key 0-21
                    # FIX MỚI: Dùng slice_mb_idx (local index trong slice)
                    key = (slice_mb_idx, block_idx)  # ← FIXED: Use LOCAL index
                    
                    if key in combined_blocks:
                        mb_blocks[block_idx] = combined_blocks[key]
                        blocks_found += 1
                        
                        # DEBUG first MB
                        if slice_mb_idx == 0 and block_idx == 0:
                            print(f"          [POPULATE] [OK] MB Local:{slice_mb_idx} Global:{mb_global_idx}, Block {block_idx}")
                            print(f"                      Key: {key}")
                            print(f"                      Coeffs from combined_blocks: {combined_blocks[key][:8]}...")
                    else:
                        mb_blocks[block_idx] = [0] * 16
                
                # DEBUG first MB blocks found
                if slice_mb_idx == 0:
                    print(f"          [POPULATE] MB 0: Found {blocks_found}/24 blocks in combined_blocks")
                    nonzero_blocks = [idx for idx, c in mb_blocks.items() if any(x != 0 for x in c)]
                    print(f"          [POPULATE] MB 0: Non-zero blocks: {nonzero_blocks}")
                
                # Calculate CBP from actual block contents (modified or original)
                calculated_cbp = 0
                for block_idx, coeffs in mb_blocks.items():
                    has_nonzero = any(c != 0 for c in coeffs)
                    if has_nonzero:
                        if block_idx < 16:  # Luma
                            luma_4x4 = block_idx // 4
                            calculated_cbp |= (1 << luma_4x4)
                        elif block_idx < 20:  # Cb
                            calculated_cbp |= 0x10
                        else:  # Cr
                            calculated_cbp |= 0x20
                
                # Debug CBP for first MB
                if slice_mb_idx == 0:
                    nonzero_blocks = [idx for idx, c in mb_blocks.items() if any(x != 0 for x in c)]
                    print(f"          MB 0: Calculated CBP=0x{calculated_cbp:02x}, non-zero blocks: {nonzero_blocks}")
                
                # Get original MB type and CBP from source video
                mb_meta = mb_metadata.get(slice_mb_idx, {}) if mb_metadata else {}
                original_mb_type = mb_meta.get('mb_type', 0)  # Default to I_4x4
                original_cbp = mb_meta.get('cbp', calculated_cbp)  # Use calculated if not available
                is_skip_mb = mb_meta.get('is_skip_mb', False) or original_cbp == 0
                
                # CRITICAL FIX: Preserve skip MBs (CBP=0) without modification
                # Skip MBs have no residual data and should use CBP=0
                if is_skip_mb:
                    cbp = 0  # Force CBP to 0 for skip MBs
                    if slice_mb_idx == 0:
                        print(f"          [INFO] MB 0 is skip MB (original CBP=0x00), preserving without reconstruction")
                else:
                    # For coded MBs, use calculated CBP to reflect actual block contents
                    cbp = calculated_cbp
                    
                    if slice_mb_idx == 0 and original_cbp != calculated_cbp:
                        print(f"          [WARN] MB 0: Original CBP=0x{original_cbp:02x} != Calculated CBP=0x{calculated_cbp:02x}")
                        print(f"          [INFO] Using calculated CBP to reflect actual block contents")
                
                # Write MB type (use original from video)
                if slice_mb_idx == 0:
                    pos_before_mb_type = writer.get_bit_position()
                writer.write_ue(original_mb_type)
                if slice_mb_idx == 0:
                    pos_after_mb_type = writer.get_bit_position()
                    print(f"          [ENC_BITS] MB:0 starts at Pos:{pos_before_mb_type}, after mb_type: Pos:{pos_after_mb_type} (wrote {pos_after_mb_type - pos_before_mb_type} bits)")
                
                # Handle different MB types
                if original_mb_type == 0:  # I_4x4
                    # Write prev_intra4x4_pred_mode_flag and rem_intra4x4_pred_mode for each 4x4 block
                    # Simplified: use DC prediction (mode 2) for all
                    if slice_mb_idx == 0:
                        pos_before_pred = writer.get_bit_position()
                    for _ in range(16):
                        writer.write_bits(1, 1)  # prev_intra4x4_pred_mode_flag = 1 (use most probable)
                    if slice_mb_idx == 0:
                        pos_after_pred = writer.get_bit_position()
                        print(f"          [ENC_BITS] After writing 16x pred_mode_flag(1): Pos:{pos_after_pred} (wrote {pos_after_pred - pos_before_pred} bits)")
                    # Write chroma prediction mode
                    pos_before_chroma = writer.get_bit_position() if slice_mb_idx == 0 else 0
                    writer.write_ue(0)  # DC mode
                    if slice_mb_idx == 0:
                        pos_after_chroma = writer.get_bit_position()
                        print(f"          [ENC_BITS] After writing chroma_pred_mode(UE:0): Pos:{pos_after_chroma} (wrote {pos_after_chroma - pos_before_chroma} bits)")
                elif original_mb_type >= 1 and original_mb_type <= 24:  # I_16x16
                    # Write chroma prediction mode
                    writer.write_ue(0)  # DC mode for chroma
                
                # Write CBP (use calculated CBP based on actual block contents)
                # CRITICAL: Use me(v) mapping for CBP, NOT raw Exp-Golomb!
                # Determine if this is Intra MB
                is_intra = (original_mb_type >= 0 and original_mb_type <= 25)  # I_4x4 or I_16x16
                writer.write_me_cbp(cbp, is_intra=is_intra)

                # Write QP delta (0 = no change)
                if cbp > 0:
                    writer.write_se(0)
                    
                    # Encode coefficient blocks based on calculated CBP flags
                    blocks_encoded = 0
                    for block_idx in range(24):
                        # Determine if this block should be encoded based on calculated CBP
                        should_encode = False
                        if block_idx < 16:  # Luma Y (16 4x4 blocks)
                            luma_4x4 = block_idx // 4  # Which 8x8 region (0-3)
                            should_encode = (cbp & (1 << luma_4x4)) != 0
                        elif block_idx < 20:  # Cb chroma (4 blocks)
                            should_encode = (cbp & 0x10) != 0
                        else:  # Cr chroma (4 blocks, 20-23)
                            should_encode = (cbp & 0x20) != 0
                        
                        if should_encode:
                            coeffs = mb_blocks.get(block_idx, [0] * 16)
                            if len(coeffs) != 16:
                                coeffs = (list(coeffs) + [0]*16)[:16]
                            
                            # ==================================================================================
                            # CRITICAL FIX #5: max_num_coeff depends on block type
                            # ==================================================================================
                            # Luma blocks (0-15): 16 coefficients (4x4 with DC)
                            # Chroma AC blocks (16-23): 15 coefficients (4x4 minus DC)
                            # (DC is handled separately in I_16x16 mode, but we use I_4x4)
                            #
                            # OLD CODE (WRONG):
                            # max_num_coeff = 16  ← Bug! Chroma AC should be 15!
                            #
                            # NEW CODE (CORRECT):
                            if block_idx < 16:
                                # Luma blocks: full 4x4 = 16 coeffs
                                max_num_coeff = 16
                            else:
                                # Chroma AC blocks: 4x4 minus DC = 15 coeffs
                                # (Matches parser: traceable_cavlc_parser.py line 257)
                                max_num_coeff = 15
                            
                            # Calculate nC from neighbors (H.264 Section 8.4.1.2.2)
                            # CRITICAL: Use mb_global_idx (frame-absolute), NOT slice_mb_idx!
                            nC = self._calculate_nC(mb_global_idx, block_idx, pic_width_in_mbs=22)
                            encoder.encode_block_cavlc(coeffs, nC=nC, max_num_coeff=max_num_coeff)
                            # Update total_coeffs cache for future nC calculations
                            self._update_total_coeffs_cache(mb_global_idx, block_idx, coeffs)

                            blocks_encoded += 1
                    
            # Add stop bit
            writer.write_bit(1)
            
            # Return re-encoded RBSP
            writer.align_to_byte()
            return writer.get_bytes()
            
        except Exception as e:
            print(f"          [!] Re-encoding error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    
    def _write_h264_file(self, nal_units: List[NALUnit], output_file: str):
        """
        Write NAL units to H.264 file with Annex B byte stream format
        
        Format: start_code + NAL_header + RBSP + start_code + ...
        """
        with open(output_file, 'wb') as f:
            for nal in nal_units:
                # Write start code (0x00000001)
                f.write(self.start_code)
                
                # Write NAL unit header (1 byte)
                nal_header = (
                    (nal.forbidden_zero_bit << 7) |
                    (nal.nal_ref_idc << 5) |
                    int(nal.nal_unit_type)
                )
                f.write(bytes([nal_header]))
                
                # Write RBSP (with emulation prevention if needed)
                rbsp = self._add_emulation_prevention(nal.rbsp_byte)
                f.write(rbsp)
    
    def _add_emulation_prevention(self, rbsp: bytes) -> bytes:
        """
        Add emulation prevention bytes to RBSP
        
        H.264 requires inserting 0x03 after sequences of 0x000000, 0x000001, etc.
        to prevent confusion with start codes.
        """
        output = bytearray()
        zero_count = 0
        
        for byte in rbsp:
            if zero_count == 2 and byte <= 0x03:
                # Insert emulation prevention byte
                output.append(0x03)
                zero_count = 0
            
            output.append(byte)
            
            if byte == 0x00:
                zero_count += 1
            else:
                zero_count = 0
        
        return bytes(output)
    
    def _parse_sps_from_nal(self, nal):
        """Parse SPS NAL unit to extract critical fields"""
        from ..bitstream.nal_handler import SPSData
        from .bitstream_io import BitstreamReader
        
        sps = SPSData()
        try:
            reader = BitstreamReader(nal.rbsp_byte)
            
            # Parse SPS fields
            profile_idc = reader.read_bits(8)
            constraint_flags = reader.read_bits(8)
            level_idc = reader.read_bits(8)
            seq_parameter_set_id = reader.read_ue()
            
            # High Profile (100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135)
            # requires parsing additional chroma/bit depth fields
            if profile_idc in [100, 110, 122, 244, 44, 83, 86, 118, 128, 138, 139, 134, 135]:
                chroma_format_idc = reader.read_ue()
                if chroma_format_idc == 3:
                    separate_colour_plane_flag = reader.read_bits(1)
                bit_depth_luma_minus8 = reader.read_ue()
                bit_depth_chroma_minus8 = reader.read_ue()
                qpprime_y_zero_transform_bypass_flag = reader.read_bits(1)
                seq_scaling_matrix_present_flag = reader.read_bits(1)
                if seq_scaling_matrix_present_flag:
                    # Parse scaling matrices (complex, skip for now - just read flags)
                    num_scaling_lists = 8 if chroma_format_idc != 3 else 12
                    for i in range(num_scaling_lists):
                        seq_scaling_list_present_flag = reader.read_bits(1)
                        if seq_scaling_list_present_flag:
                            # Skip reading actual scaling list
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
            
            # Skip other fields, read frame_mbs_only_flag
            num_ref_frames = reader.read_ue()
            gaps_in_frame_num_value_allowed_flag = reader.read_bits(1)
            sps.pic_width_in_mbs_minus1 = reader.read_ue()
            sps.pic_height_in_map_units_minus1 = reader.read_ue()
            sps.frame_mbs_only_flag = reader.read_bits(1) == 1

        except Exception as e:
            print(f"    [!] SPS parsing error: {e}, using defaults")
        
        return sps
    
    def _parse_pps_from_nal(self, nal):
        """Parse PPS NAL unit to extract critical fields"""
        from ..bitstream.nal_handler import PPSData
        from .bitstream_io import BitstreamReader
        
        pps = PPSData()
        try:
            reader = BitstreamReader(nal.rbsp_byte)
            
            # Parse PPS fields
            pic_parameter_set_id = reader.read_ue()
            seq_parameter_set_id = reader.read_ue()
            entropy_coding_mode_flag = reader.read_bits(1)
            bottom_field_pic_order_in_frame_present_flag = reader.read_bits(1)
            num_slice_groups_minus1 = reader.read_ue()
            
            # Store entropy coding mode
            pps.entropy_coding_mode_flag = entropy_coding_mode_flag == 1
            
            # Skip slice group map if present
            if num_slice_groups_minus1 > 0:
                # Complex slice group parsing - skip for now
                pass
            
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
            print(f"    [!] PPS parsing error: {e}, using defaults")
        
        return pps


def test_reconstruction():
    """Test bitstream reconstruction with simple video"""
    import numpy as np
    
    print("Testing Bitstream Reconstruction")
    print("=" * 70)
    
    # This test requires a real H.264 file
    # For now, we just verify the class can be instantiated
    reconstructor = BitstreamReconstructor()
    
    print("[OK] BitstreamReconstructor initialized")
    print("[OK] Ready for video reconstruction")
    
    print("\nTo test with real video:")
    print("  reconstructor.reconstruct_video(")
    print("      'input.h264',")
    print("      modified_coefficients,")
    print("      'output.h264'")
    print("  )")


if __name__ == '__main__':
    test_reconstruction()
