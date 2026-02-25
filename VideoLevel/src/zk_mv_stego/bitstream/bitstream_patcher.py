"""
Bitstream Patcher for Smart Patching

Directly overwrites coefficient bits at tracked offsets without re-encoding entire slices.
Leverages Safety Filter's bit-length invariance guarantee.
"""

from typing import List, Tuple, Dict
from .traceable_cavlc_parser import TraceableCAVLCParser
from .cavlc_encoder import CAVLCEncoder
from .bitstream_io import BitstreamWriter  # Use actual BitstreamWriter
from .nal_handler import SPSData, PPSData


class BitArray:
    """Simple bit array for bit-level operations"""
    
    def __init__(self, data: bytes):
        """Initialize from bytes"""
        self.bits = []
        for byte in data:
            for i in range(7, -1, -1):
                self.bits.append((byte >> i) & 1)
    
    def __len__(self):
        return len(self.bits)
    
    def __getitem__(self, key):
        if isinstance(key, slice):
            return self.bits[key]
        return self.bits[key]
    
    def __setitem__(self, key, value):
        if isinstance(key, slice):
            # Slice assignment
            start, stop, step = key.indices(len(self.bits))
            if step != 1:
                raise ValueError("Only contiguous slices supported")
            
            # Replace bits
            if isinstance(value, list):
                self.bits[start:stop] = value
            else:
                raise ValueError("Value must be list of bits")
        else:
            self.bits[key] = value
    
    def to_bytes(self) -> bytes:
        """Convert bit array back to bytes"""
        # Pad to byte boundary if needed
        if len(self.bits) % 8 != 0:
            padding_needed = 8 - (len(self.bits) % 8)
            padded_bits = self.bits + [0] * padding_needed
        else:
            padded_bits = self.bits
        
        result = bytearray()
        for i in range(0, len(padded_bits), 8):
            byte = 0
            for j in range(8):
                byte |= (padded_bits[i + j] << (7 - j))
            result.append(byte)
        
        return bytes(result)


class BitstreamPatcher:
    """
    Patches H.264 bitstream by overwriting coefficient bits at specific offsets.
    
    Key property: Safety Filter guarantees bit length invariance
    -> Old and new coefficients encode to SAME bit length
    -> Safe to overwrite without alignment issues
    """
    
    def __init__(self):
        self.parser = TraceableCAVLCParser()
    
    def patch_slice(self, original_nal, modifications: List[Tuple[int, int, List[int]]], 
                    sps: SPSData, pps: PPSData, global_mb_offset: int = 0,
                    pre_computed_offsets: Dict = None, pre_computed_blocks: Dict = None):
        """
        Patch a slice with modified coefficients using direct bit overwrite.
        
        Args:
            original_nal: Original NAL unit
            modifications: List of (mb_idx_GLOBAL, block_idx, new_coeffs)  <- GLOBAL MB indices!
            sps: SPS data
            pps: PPS data
            global_mb_offset: Global MB offset for this slice (to convert local->global MB indices)
            pre_computed_offsets: Optional pre-computed block offsets {(mb_local, blk): offset_data}
                                  If provided, skip internal re-parse to avoid divergence.
            pre_computed_blocks: Optional pre-computed blocks {(mb_local, blk): [coeffs]}
            
        Returns:
            Patched NAL unit with same structure
        """
        print(f"[PATCHER] Patching {len(modifications)} blocks (global_mb_offset={global_mb_offset})...")
        
        # Step 1: Get bit offsets (use pre-computed if available, otherwise re-parse)
        if pre_computed_offsets is not None and pre_computed_blocks is not None:
            # Use pre-computed data from the reconstructor's parse — avoids double-parse divergence
            block_offsets = pre_computed_offsets
            original_blocks = pre_computed_blocks
            print(f"[PATCHER] Using pre-computed offsets ({len(block_offsets)} offsets) — skipping re-parse")
        else:
            # Fallback: re-parse the NAL internally
            # ⚠️ WARNING: Re-parsing can diverge from embedder's parse due to parser state!
            result = self.parser.extract_with_offsets(original_nal, sps, pps)
            block_offsets = result['offsets']  # Keys are (mb_idx_LOCAL, block_idx)
            original_blocks = result['blocks']
        
        if not block_offsets:
            print(f"[PATCHER] Warning: No offsets extracted!")
            return original_nal
        
        # ==================================================================================
        # CRITICAL FIX: Convert slice-local MB indices to global MB indices
        # ==================================================================================
        # Parser returns (mb_local, blk_idx) -> Convert to (mb_global, blk_idx)
        # mb_global = mb_local + global_mb_offset
        global_block_offsets = {}
        global_original_blocks = {}  # CRITICAL: Also convert blocks dict!
        
        for (mb_local, blk_idx), offset_data in block_offsets.items():
            mb_global = mb_local + global_mb_offset
            global_block_offsets[(mb_global, blk_idx)] = offset_data
        
        for (mb_local, blk_idx), coeffs in original_blocks.items():
            mb_global = mb_local + global_mb_offset
            global_original_blocks[(mb_global, blk_idx)] = coeffs
        
        # DEBUG: Show first 10 entries in both dicts
        print(f"[PATCHER_DEBUG] Sample block_offsets (local): {list(block_offsets.keys())[:10]}")
        print(f"[PATCHER_DEBUG] Sample original_blocks (local): {list(original_blocks.keys())[:10]}")
        print(f"[PATCHER_DEBUG] Sample global_block_offsets: {list(global_block_offsets.keys())[:10]}")
        print(f"[PATCHER_DEBUG] Sample global_original_blocks: {list(global_original_blocks.keys())[:10]}")
        if global_mb_offset == 309:  # Frame 1
            # Check if block (0, 6) exists in original_blocks
            test_key_local = (0, 6)
            test_key_global = (309, 6)
            if test_key_local in original_blocks:
                test_coeffs_local = original_blocks[test_key_local]
                nz_local = [c for c in test_coeffs_local if c != 0]
                print(f"[PATCHER_DEBUG] original_blocks[(0,6)]: {len(nz_local)} non-zero coeffs: {nz_local}")
            else:
                print(f"[PATCHER_DEBUG] original_blocks[(0,6)]: NOT FOUND")
                
            if test_key_global in global_original_blocks:
                test_coeffs_global = global_original_blocks[test_key_global]
                nz_global = [c for c in test_coeffs_global if c != 0]
                print(f"[PATCHER_DEBUG] global_original_blocks[(309,6)]: {len(nz_global)} non-zero coeffs: {nz_global}")
            else:
                print(f"[PATCHER_DEBUG] global_original_blocks[(309,6)]: NOT FOUND")
        
        # Step 2: Convert RBSP bytes to BitArray (mutable bit-level structure)
        rbsp_bits = BitArray(original_nal.rbsp_byte)
        
        print(f"[PATCHER] Original RBSP: {len(rbsp_bits)} bits")
        print(f"[PATCHER] Tracked offsets: {len(block_offsets)} blocks (slice-local) -> {len(global_block_offsets)} blocks (global)")
        
        # Debug: Show modification targets vs available offsets
        mod_keys = set((mb, blk) for mb, blk, _ in modifications)
        offset_keys = set(global_block_offsets.keys())  # Use global offsets!
        overlap = mod_keys & offset_keys
        
        print(f"[PATCHER_DEBUG] Modifications target: {len(mod_keys)} blocks")
        print(f"[PATCHER_DEBUG] First 5 modification keys: {sorted(list(mod_keys))[:5]}")
        print(f"[PATCHER_DEBUG] First 5 offset keys: {sorted(list(offset_keys))[:5]}")
        print(f"[PATCHER_DEBUG] Overlap: {len(overlap)} blocks can be patched")
        # NEW: Show actual overlap or mismatch
        if overlap:
            print(f"[PATCHER_DEBUG] Overlapping keys (first 10): {sorted(list(overlap))[:10]}")
        elif mod_keys and offset_keys:
            # Show the gap
            print(f"[PATCHER_DEBUG] [WARN] NO OVERLAP!")
            print(f"[PATCHER_DEBUG]   Mod keys range: {min(mb for mb,_ in mod_keys)} to {max(mb for mb,_ in mod_keys)}")
            print(f"[PATCHER_DEBUG]   Offset keys range: {min(mb for mb,_ in offset_keys)} to {max(mb for mb,_ in offset_keys)}")
            # Show if it's an offset mismatch
            mod_mbs = sorted(set(mb for mb,_ in mod_keys))
            offset_mbs = sorted(set(mb for mb,_ in offset_keys))
            print(f"[PATCHER_DEBUG]   Mod MBs: {mod_mbs[:10]}")
            print(f"[PATCHER_DEBUG]   Offset MBs: {offset_mbs[:10]}")
        
        
        # Step 3: Patch each modified block
        patched_count = 0
        skipped_count = 0
        
        for mb_idx, block_idx, new_coeffs in modifications:
            key = (mb_idx, block_idx)  # Already global from embedder!
            
            if key not in global_block_offsets:  # Use global offsets!
                print(f"[PATCHER] Warning: Block {key} not in global offset map (skip MB or not coded)")
                skipped_count += 1
                continue
            
            offset_info = global_block_offsets[key]  # Use global offsets!
            start_bit = offset_info['start_bit']
            end_bit = offset_info['end_bit']
            original_length = offset_info['bit_length']
            
            # ==================================================================================
            # CRITICAL FIX: Only patch blocks that have bitstream offsets
            # ==================================================================================
            # Step 4: Verify block has offset data (was actually coded in NAL)
            # We need offset data to know WHERE to patch in the bitstream
            if key not in global_block_offsets:
                if patched_count == 0:  # Show debug for first occurrence only
                    print(f"[PATCHER] SKIP {key}: Block has no bitstream offset (wasn't coded in NAL)")
                skipped_count += 1
                continue
            
            # Get original coefficients from blocks dict (GLOBAL keys!)
            # CRITICAL FIX: Use global_original_blocks, not original_blocks
            # original_blocks hasLOCAL keys (0,1,2...), we need GLOBAL keys (94,95,96...)
            original_coeffs = global_original_blocks.get(key, None)
            
            # CRITICAL: If block not found in extracted coeffs, SKIP IT!
            # This means the block wasn't actually coded in the NAL
            if original_coeffs is None:
                if patched_count == 0:  # Show debug for first occurrence only
                    print(f"[PATCHER] SKIP {key}: Block not found in extracted coeffs (wasn't coded in NAL)")
                skipped_count += 1
                continue
            
            # PARSER CONSISTENCY CHECK: Verify total_coeffs match between parser and embedder
            parser_total = sum(1 for c in original_coeffs if c != 0)
            modified_total = sum(1 for c in new_coeffs if c != 0)
            if parser_total != modified_total and patched_count < 5:
                print(f"[PATCHER_WARN] {key}: Parser extracted {parser_total} coeffs, embedder has {modified_total} coeffs")
                print(f"  This indicates parser extraction inconsistency!")
            
            # Apply modifications to ORIGINAL coefficients (not FFmpeg approximations!)
            # modified_coeffs = copy of original + apply same bit flips
            # For now, we'll use new_coeffs but this needs investigation
            
            # [WARN] TODO: This is still using FFmpeg-modified coefficients which may not be encodable!
            # Need to: 1) Extract mod positions from new_coeffs
            #          2) Apply same mods to original_coeffs
            #          3) Encode the modified-original coefficients
            
            # For debugging: try to encode ORIGINAL coefficients first
            if patched_count == 0:
                print(f"[PATCHER_DEBUG] Testing encodability of ORIGINAL coefficients for {key}")
                print(f"  Original coeffs (non-zero): {[c for c in original_coeffs if c != 0][:10]}")
                print(f"  Modified coeffs (non-zero): {[c for c in new_coeffs if c != 0][:10]}")
            
            # CRITICAL: Use actual nC from offset tracking!
            # Must match the nC used by Safety Filter validation
            nC = offset_info.get('nC', 0)
            
            # DEBUG: Show nC value and coefficient details for first few blocks in frame 0 and frame 1
            if patched_count < 4 or (key[0] >= 309 and key[0] < 312):  # Frame 0 first 4, or Frame 1 first few MBs
                print(f"[PATCHER_DEBUG] Block {key}: using nC={nC} for encoding")
                print(f"  Original coeffs (from NAL): {[c for c in original_coeffs if c != 0][:10]}")
                print(f"  Modified coeffs (from embedder): {[c for c in new_coeffs if c != 0][:10]}")
                # Show which coefficients changed
                changes = [(i, o, n) for i, (o, n) in enumerate(zip(original_coeffs, new_coeffs)) if o != n]
                if changes:
                    print(f"  Changes at indices: {changes}")
                
                # CRITICAL TEST: Check if extraction is correct
                # Extract actual bits from NAL
                actual_nal_bits = rbsp_bits[start_bit:end_bit]
                print(f"  Actual NAL bits: {len(actual_nal_bits)} bits")
                if len(actual_nal_bits) <= 30:
                    print(f"    Bits: {actual_nal_bits}")
            
            # LENGTH-ONLY pre-check: verify our encoder produces the same BIT COUNT
            # as the original NAL (even if the exact VLC bits differ — both are valid H.264).
            # If lengths differ, we cannot patch in-place without shifting subsequent bits.
            orig_bits = self._encode_coefficients_to_bits(original_coeffs, nC, max_num_coeff=16)
            if len(orig_bits) != original_length:
                if patched_count < 5:
                    print(f"[PATCHER] SKIP {key}: Length mismatch (our_enc={len(orig_bits)}, NAL={original_length})")
                    print(f"  Our encoder produces different-length encoding than FFmpeg (both valid H.264)")
                    print(f"  Cannot patch in-place. nC={nC}, coeffs={[c for c in original_coeffs if c != 0][:6]}")
                skipped_count += 1
                continue
            
            if patched_count == 0:
                print(f"[PATCHER] Patching block {key} (nC={nC}, length={original_length}bits matched)")
                nz_orig = [c for c in original_coeffs if c != 0]
                nz_mod = [c for c in new_coeffs if c != 0]
                print(f"  Original non-zero: {nz_orig[:6]}")
                print(f"  Modified non-zero: {nz_mod[:6]}")
            
            # CRITICAL: Extract original total_coeffs to preserve suffixLength when re-encoding
            # Count non-zero coefficients in original block
            original_total_coeffs = sum(1 for c in original_coeffs if c != 0)
            
            # CRITICAL FIX: Skip blocks where original is all-zeros but modified has non-zeros
            # This is impossible to patch because:
            # - All-zero block encodes as 1-2 bits (coeff_token only)
            # - Non-zero block encodes as 20+ bits (coeff_token + levels + total_zeros + runs)
            # No override_total_coeffs can fix this fundamental difference
            modified_total_coeffs = sum(1 for c in new_coeffs if c != 0)
            
            if original_total_coeffs == 0 and modified_total_coeffs > 0:
                if patched_count ==0:  # Show detailed debug for first occurrence only
                    print(f"[PATCHER] SKIP {key}: Original is all-zeros ({original_total_coeffs} coeffs) "
                          f"but modified has {modified_total_coeffs} non-zero coeffs - impossible to patch!")
                    print(f"  Original: {original_coeffs}")
                    print(f"  Modified: {new_coeffs}")
                skipped_count += 1
                continue
            
            # CRITICAL DEBUG: Analyze why bit lengths differ
            # Check if total_coeffs changed (should be caught above for 0->n, but what about n->m?)
            if original_total_coeffs != modified_total_coeffs:
                if patched_count < 2:  # Show for first 2 cases
                    print(f"[PATCHER_DEBUG] {key}: total_coeffs changed {original_total_coeffs}->{modified_total_coeffs}")
                    print(f"  Original non-zero positions: {[i for i, c in enumerate(original_coeffs) if c != 0]}")
                    print(f"  Modified non-zero positions: {[i for i, c in enumerate(new_coeffs) if c != 0]}")
                    print(f"  WARNING override_total_coeffs={original_total_coeffs} should preserve suffixLength")
                    # Check for zero->non-zero violations
                    zero_to_nonzero = [(i, original_coeffs[i], new_coeffs[i]) 
                                      for i in range(len(original_coeffs)) 
                                      if original_coeffs[i] == 0 and new_coeffs[i] != 0]
                    if zero_to_nonzero:
                        print(f"  [!] ZERO->NON-ZERO violations: {zero_to_nonzero[:5]}")
                    # Check for non-zero->zero violations
                    nonzero_to_zero = [(i, original_coeffs[i], new_coeffs[i]) 
                                      for i in range(len(original_coeffs)) 
                                      if original_coeffs[i] != 0 and new_coeffs[i] == 0]
                    if nonzero_to_zero:
                        print(f"  [!] NON-ZERO->ZERO violations: {nonzero_to_zero[:5]}")
            
            # Re-encode modified coefficients WITH original total_coeffs override
            # This ensures suffixLength remains the same, maintaining bit length
            new_bits = self._encode_coefficients_to_bits(new_coeffs, nC, max_num_coeff=16, 
                                                         override_total_coeffs=original_total_coeffs,
                                                         debug_key=key)
            
            if patched_count < 4 or (key[0] >= 309 and key[0] < 312):
                print(f"  Re-encoded original: {len(orig_bits)} bits")
                if len(orig_bits) <= 30:
                    print(f"    Bits: {orig_bits}")
                print(f"  Re-encoded modified: {len(new_bits)} bits")
                
                # Check match
                actual_nal_bits = rbsp_bits[start_bit:end_bit]
                if orig_bits == actual_nal_bits:
                    print(f"  [OK] Re-encoded MATCHES actual NAL!")
                else:
                    print(f"  ❌ Re-encoded DOES NOT MATCH NAL!")
                    if len(orig_bits) == len(actual_nal_bits):
                        # Count bit differences
                        diff_count = sum(1 for a, b in zip(orig_bits, actual_nal_bits) if a != b)
                        print(f"     Bit differences: {diff_count}/{len(orig_bits)}")
                    else:
                        print(f"     Length mismatch prevents comparison")

            
            # Step 5: CRITICAL - Verify bit length (Safety Filter guarantee)
            if len(new_bits) != original_length:
                if patched_count < 2:  # Show first few errors
                    print(f"[PATCHER] SKIP {key}: Modified coefficients encode to different length!")
                    print(f"  Original NAL: {original_length} bits")
                    print(f"  Re-encoded:   {len(new_bits)} bits")
                    print(f"  [SAFETY VIOLATION] This should never happen if Safety Filter worked correctly")
                
                skipped_count += 1
                continue
            
            # Step 6: Overwrite bits at specific position
            try:
                rbsp_bits[start_bit:end_bit] = new_bits
                patched_count += 1
                
                # Debug first patch
                if patched_count == 1:
                    print(f"[PATCHER] First patch at {key}:")
                    print(f"  Bit offset: {start_bit}-{end_bit} ({original_length} bits)")
                    non_zero_orig = [c for c in original_coeffs if c != 0]
                    non_zero_new = [c for c in new_coeffs if c != 0]
                    print(f"  Original coeffs: {non_zero_orig[:5] if non_zero_orig else [0]}")
                    print(f"  New coeffs:      {non_zero_new[:5] if non_zero_new else [0]}")
            
            except Exception as e:
                print(f"[PATCHER] Error patching block {key}: {e}")
                skipped_count += 1
                continue
        
        print(f"[PATCHER] Successfully patched: {patched_count}/{len(modifications)}", flush=True)
        if skipped_count > 0:
            print(f"[PATCHER] Skipped: {skipped_count} blocks (not coded or length mismatch)", flush=True)
        
        # FORCE OUTPUT TO STDOUT
        import sys
        sys.stdout.flush()
        sys.stderr.flush()
        
        # Step 7: Convert BitArray back to bytes
        patched_rbsp = rbsp_bits.to_bytes()
        
        # Step 8: Create new NAL unit with patched RBSP
        # Create a simple NAL-like object (match original structure)
        class PatchedNAL:
            def __init__(self, original_nal, new_rbsp):
                self.forbidden_zero_bit = original_nal.forbidden_zero_bit
                self.nal_ref_idc = original_nal.nal_ref_idc
                self.nal_unit_type = original_nal.nal_unit_type
                self.rbsp_byte = new_rbsp
                self.start_pos = original_nal.start_pos
                self.size = len(new_rbsp) + 1  # +1 for NAL header
        
        return PatchedNAL(original_nal, patched_rbsp)
    
    def _encode_coefficients_to_bits(self, coeffs: List[int], nC: int, max_num_coeff: int, 
                                     override_total_coeffs: int = None, debug_key=None) -> List[int]:
        """
        Encode coefficient block to bit sequence.
        
        CRITICAL: Uses SAME CAVLCEncoder as Safety Filter to ensure consistency.
        
        Args:
            coeffs: Coefficient values  
            nC: Neighbor context (for VLC table selection)
            max_num_coeff: Maximum coefficients (16 for 4x4 blocks)
            override_total_coeffs: Optional override for total_coeffs (for re-encoding modified blocks)
            debug_key: Optional (mb_idx, block_idx) for debugging
            
        Returns:
            List of bits [0, 1, 1, 0, ...]
        """
        # Create temporary writer
        temp_writer = BitstreamWriter()
        encoder = CAVLCEncoder(temp_writer)
        
        # Encode block (same call as Safety Filter)
        encoder.encode_block_cavlc(coeffs, nC=nC, max_num_coeff=max_num_coeff, 
                                   override_total_coeffs=override_total_coeffs,
                                   debug_key=debug_key)
        
        # Extract bits as list
        bits = temp_writer.get_bits_as_list()
        
        return bits
