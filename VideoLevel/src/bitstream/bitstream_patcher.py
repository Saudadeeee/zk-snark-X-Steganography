"""
Bitstream Patcher for Smart Patching

Directly overwrites coefficient bits at tracked offsets without re-encoding entire slices.
Leverages Safety Filter's bit-length invariance guarantee.
"""

from typing import List, Tuple, Dict
from .traceable_cavlc_parser import TraceableCAVLCParser
from .cavlc_encoder import CAVLCEncoder
from .bitstream_io import BitstreamWriter, BitstreamReader
from .cavlc_decoder import CAVLCDecoder
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
        # Step 1: Get bit offsets (use pre-computed if available, otherwise re-parse)
        if pre_computed_offsets is not None and pre_computed_blocks is not None:
            # Use pre-computed data from the reconstructor's parse — avoids double-parse divergence
            block_offsets = pre_computed_offsets
            original_blocks = pre_computed_blocks
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

        # Step 2: Convert RBSP bytes to BitArray (mutable bit-level structure)
        rbsp_bits = BitArray(original_nal.rbsp_byte)

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
            
            # ==================================================================================
            # BIT-EXACT nC SCANNING VIA RE-DECODE
            # ==================================================================================
            # Problem: SimpleCAVLCExtractor may compute nC differently from FFmpeg, giving
            # wrong coefficients. Even with the correct nC, encode(wrong_coeffs) != NAL bits.
            #
            # Solution: Re-decode the raw NAL bits at the stored offset with each nC and
            # verify the round-trip: encode(decode(bits, nC)) == bits.
            # This finds both the correct nC AND the true coefficient sequence, independent
            # of any discrepancy between our extractor and FFmpeg.
            #
            # nC regions: 0-1 -> Table NC_0_1, 2-3 -> NC_2_3, 4-7 -> NC_4_7, 8+ -> NC_8
            # ==================================================================================

            actual_nal_bits = list(rbsp_bits[start_bit:end_bit])
            # Use a 64-bit lookahead buffer to avoid padding-zero artifacts:
            # when the block is not byte-aligned the decoder would otherwise
            # read padding zeros that look like valid CAVLC data, shifting the
            # consumed-bit count and failing the original_length check.
            lookahead_end = min(end_bit + 64, len(rbsp_bits))
            raw_nal_bytes = self._bits_to_bytes(list(rbsp_bits[start_bit:lookahead_end]))

            matched_nC = None
            matched_nal_coeffs = None  # Coefficients decoded directly from the NAL
            orig_bits = None
            matched_trailing_ones = None  # T1 override that produced the correct round-trip

            # Prefer TraceableCAVLCParser's pre-computed nC (matches FFmpeg's H.264 spec nC
            # computation from neighbor total_coeffs).  Scanning from nC=0 first causes ~43%
            # of blocks to pick the wrong nC table by coincidence, which makes re-encoded bits
            # undecodable by FFmpeg → CAVLC sync loss → catastrophic PSNR.
            tracer_nC = offset_info.get('nC', None) if isinstance(offset_info, dict) else None
            if tracer_nC is not None:
                nC_scan_order = [tracer_nC] + [nc for nc in [0, 2, 4, 6, 8] if nc != tracer_nC]
            else:
                nC_scan_order = [0, 2, 4, 6, 8]

            for nC_try in nC_scan_order:
                try:
                    reader = BitstreamReader(raw_nal_bytes)
                    dec = CAVLCDecoder(reader)
                    block = dec.decode_block_cavlc(nC_try, max_num_coeff=16)
                    consumed = reader.pos
                    if consumed != original_length:
                        continue  # Wrong nC: decoder consumed wrong number of bits
                    # Verify round-trip: encode(decode(bits)) == bits
                    nal_coeffs = list(block.levels)
                    # First try without T1 override (encoder chooses max T1)
                    candidate = self._encode_coefficients_to_bits(nal_coeffs, nC_try, max_num_coeff=16)
                    if len(candidate) == original_length and list(candidate) == actual_nal_bits:
                        matched_nC = nC_try
                        matched_nal_coeffs = nal_coeffs
                        orig_bits = candidate
                        matched_trailing_ones = None  # No override needed
                        break
                    # If standard encode fails, try with T1 override = decoded trailing_ones.
                    # Some original encoders choose a smaller T1 than the maximum possible.
                    t1_decoded = block.trailing_ones
                    candidate_t1 = self._encode_coefficients_to_bits(
                        nal_coeffs, nC_try, max_num_coeff=16,
                        override_trailing_ones=t1_decoded
                    )
                    if len(candidate_t1) == original_length and list(candidate_t1) == actual_nal_bits:
                        matched_nC = nC_try
                        matched_nal_coeffs = nal_coeffs
                        orig_bits = candidate_t1
                        matched_trailing_ones = t1_decoded
                        break
                except Exception:
                    continue

            if matched_nC is None:
                if patched_count < 5:
                    lens = {}
                    for nC_try in [0, 2, 4, 6, 8]:
                        try:
                            reader = BitstreamReader(raw_nal_bytes)
                            dec = CAVLCDecoder(reader)
                            dec.decode_block_cavlc(nC_try, max_num_coeff=16)
                            lens[nC_try] = reader.pos
                        except Exception:
                            lens[nC_try] = None
                    print(f"[PATCHER] SKIP {key}: No nC round-trips exactly "
                          f"(NAL={original_length}b). nC->consumed={lens}")
                skipped_count += 1
                continue

            nC = matched_nC  # Confirmed correct nC via round-trip decode-encode
            # Use matched_nal_coeffs as the ground-truth original coefficients
            # from NAL, not the extractor's (potentially wrong) version.

            # ──────────────────────────────────────────────────────────────────
            # Apply the embedder's LSB intent to the NAL-decoded coeffs.
            # Instead of a delta (which assumes identical parsing between the
            # embedder's TraceableCAVLCParser and the patcher's BitstreamDecoder),
            # we use the INTENDED LSB from the embedder's result.
            #
            # For each position where the embedder changed original_coeffs[i]:
            #   intended_lsb = abs(new_coeffs[i]) % 2
            # We set matched_nal_coeffs[i]'s LSB to intended_lsb.
            # If the current LSB already matches, no modification is needed.
            #
            # This is robust to parsing inconsistencies (root cause of safe_pos
            # divergence): the stego coefficient's LSB always equals the embedded
            # bit regardless of the patcher's decoded base value.
            # ──────────────────────────────────────────────────────────────────
            original_total_coeffs = sum(1 for c in matched_nal_coeffs if c != 0)

            # Build modified NAL coefficients using intended-LSB / intended-sign approach
            modified_nal_coeffs = list(matched_nal_coeffs)
            for i in range(min(len(original_coeffs), len(modified_nal_coeffs))):
                if original_coeffs[i] != new_coeffs[i] and original_coeffs[i] != 0:
                    if abs(original_coeffs[i]) == abs(new_coeffs[i]):
                        # Sign-bit change: absolute values are equal but signs differ.
                        # Applies to trailing ±1 coefficients encoded via sign-bit embedding.
                        intended_positive = new_coeffs[i] > 0
                        nal_positive = matched_nal_coeffs[i] > 0
                        if intended_positive != nal_positive:
                            modified_nal_coeffs[i] = -matched_nal_coeffs[i]
                        # else: sign already matches — no change needed
                    else:
                        # Standard LSB modification
                        intended_lsb = abs(new_coeffs[i]) % 2
                        matched_abs = abs(matched_nal_coeffs[i])
                        current_lsb = matched_abs % 2
                        if current_lsb != intended_lsb:
                            sign = 1 if matched_nal_coeffs[i] >= 0 else -1
                            new_abs = (matched_abs & ~1) | intended_lsb
                            if new_abs == 0:
                                new_abs = matched_abs  # Safety: cannot create zero
                            modified_nal_coeffs[i] = sign * new_abs
                        # else: current LSB already matches intended — no change needed

            modified_total_coeffs = sum(1 for c in modified_nal_coeffs if c != 0)

            # Skip if modification would introduce zero→non-zero or total_coeffs change
            # (these cannot be patched safely)
            if original_total_coeffs == 0 and modified_total_coeffs > 0:
                skipped_count += 1
                continue
            if original_total_coeffs != modified_total_coeffs:
                # Safety filter should have prevented this — skip as a safeguard
                skipped_count += 1
                continue

            # Re-encode modified coefficients with trailing_ones override only.
            # Note: override_total_coeffs is intentionally OMITTED — the intended-LSB
            # approach never changes zero/non-zero status, so the encoder computes the
            # correct total_coeffs from actual values.  Omitting the override keeps the
            # stego encoding reproducible by get_unpatchable_blocks (which doesn't try
            # override_total_coeffs variations), ensuring consistent nal_length_map
            # between original and stego extraction passes.
            new_bits = self._encode_coefficients_to_bits(
                modified_nal_coeffs, nC, max_num_coeff=16,
                override_trailing_ones=matched_trailing_ones)

            # Bit-exact match already confirmed for original in nC scanning above.

            # Step 5: Verify bit length (Safety Filter guarantee)
            if len(new_bits) != original_length:
                if patched_count < 2:
                    print(f"[PATCHER] SKIP {key}: Modified coefficients encode to different length!")
                    print(f"  Original NAL: {original_length} bits")
                    print(f"  Re-encoded:   {len(new_bits)} bits")
                skipped_count += 1
                continue

            # Step 6: Overwrite bits at specific position
            try:
                rbsp_bits[start_bit:end_bit] = new_bits
                patched_count += 1
            except Exception as e:
                print(f"[PATCHER] Error patching block {key}: {e}")
                skipped_count += 1
                continue
        
        print(f"[PATCHER] Successfully patched: {patched_count}/{len(modifications)}")
        if skipped_count > 0:
            print(f"[PATCHER] Skipped: {skipped_count} blocks (not coded or length mismatch)")

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
                self.start_code_size = getattr(original_nal, 'start_code_size', 4)
        
        return PatchedNAL(original_nal, patched_rbsp)
    
    def _bits_to_bytes(self, bits: List[int]) -> bytes:
        """Pack list of 0/1 ints into bytes (MSB first), padding to byte boundary."""
        padded = bits + [0] * ((8 - len(bits) % 8) % 8)
        result = bytearray()
        for i in range(0, len(padded), 8):
            byte = sum(padded[i + j] << (7 - j) for j in range(8))
            result.append(byte)
        return bytes(result)

    def get_unpatchable_blocks(self, rbsp_bytes: bytes, block_offsets: Dict):
        """
        Return the set of (mb_local, blk_idx) keys that CANNOT be successfully
        round-tripped (decode → re-encode produces different bits from the NAL).

        These blocks must be excluded from embedding: the patcher would silently
        skip them at patch-time, leaving original coefficients in the stego and
        breaking embedding/extraction sync.

        Also returns verified nC and coefficient values for patchable blocks.
        These are the CORRECT decoded values (using the nC that bit-exactly
        reproduces the NAL encoding), which avoids nC table mismatches between
        TraceableCAVLCParser and the patcher's BitstreamDecoder.

        Args:
            rbsp_bytes:    Raw RBSP bytes of the slice NAL (original_nal.rbsp_byte).
            block_offsets: Dict {(mb_local, blk_idx): {'start_bit':…,'end_bit':…,'bit_length':…}}
                           (LOCAL indices, as returned by TraceableCAVLCParser).

        Returns:
            (unpatchable, matched_info)
            - unpatchable: Set of (mb_local, blk_idx) keys that are NOT safely patchable.
            - matched_info: Dict {(mb_local, blk_idx): (matched_nC, coefficients)}
                            for patchable blocks — the bit-exact-verified nC and coefficients.
        """
        rbsp_bits = BitArray(rbsp_bytes)
        unpatchable = set()
        matched_info = {}

        for key, offset_data in block_offsets.items():
            start_bit = offset_data.get('start_bit')
            end_bit = offset_data.get('end_bit')
            original_length = offset_data.get('bit_length')

            if start_bit is None or end_bit is None or original_length is None or original_length <= 0:
                continue

            actual_nal_bits = list(rbsp_bits[start_bit:end_bit])
            lookahead_end = min(end_bit + 64, len(rbsp_bits))
            raw_nal_bytes = self._bits_to_bytes(list(rbsp_bits[start_bit:lookahead_end]))

            # Prefer TraceableCAVLCParser's pre-computed nC (matches FFmpeg's H.264 spec nC)
            tracer_nC = offset_data.get('nC', None) if isinstance(offset_data, dict) else None
            if tracer_nC is not None:
                nC_scan_order = [tracer_nC] + [nc for nc in [0, 2, 4, 6, 8] if nc != tracer_nC]
            else:
                nC_scan_order = [0, 2, 4, 6, 8]

            found = False
            for nC_try in nC_scan_order:
                try:
                    reader = BitstreamReader(raw_nal_bytes)
                    dec = CAVLCDecoder(reader)
                    block = dec.decode_block_cavlc(nC_try, max_num_coeff=16)
                    consumed = reader.pos
                    if consumed != original_length:
                        continue
                    nal_coeffs = list(block.levels)
                    # Standard encode (encoder picks max trailing-ones)
                    candidate = self._encode_coefficients_to_bits(
                        nal_coeffs, nC_try, max_num_coeff=16)
                    if len(candidate) == original_length and list(candidate) == actual_nal_bits:
                        found = True
                        matched_info[key] = (nC_try, nal_coeffs, None)  # no T1 override needed
                        break
                    # Retry with the decoded trailing_ones override
                    t1_decoded = block.trailing_ones
                    candidate_t1 = self._encode_coefficients_to_bits(
                        nal_coeffs, nC_try, max_num_coeff=16,
                        override_trailing_ones=t1_decoded)
                    if len(candidate_t1) == original_length and list(candidate_t1) == actual_nal_bits:
                        found = True
                        matched_info[key] = (nC_try, nal_coeffs, t1_decoded)  # T1 override required
                        break
                except Exception:
                    continue

            if not found:
                unpatchable.add(key)

        return unpatchable, matched_info

    def _encode_coefficients_to_bits(self, coeffs: List[int], nC: int, max_num_coeff: int,
                                     override_total_coeffs: int = None, debug_key=None,
                                     override_trailing_ones: int = None) -> List[int]:
        """
        Encode coefficient block to bit sequence.

        CRITICAL: Uses SAME CAVLCEncoder as Safety Filter to ensure consistency.

        Args:
            coeffs: Coefficient values
            nC: Neighbor context (for VLC table selection)
            max_num_coeff: Maximum coefficients (16 for 4x4 blocks)
            override_total_coeffs: Optional override for total_coeffs (for re-encoding modified blocks)
            debug_key: Optional (mb_idx, block_idx) for debugging
            override_trailing_ones: Optional T1 count override to match original encoder's choice

        Returns:
            List of bits [0, 1, 1, 0, ...]
        """
        # Create temporary writer
        temp_writer = BitstreamWriter()
        encoder = CAVLCEncoder(temp_writer)

        # Encode block (same call as Safety Filter)
        encoder.encode_block_cavlc(coeffs, nC=nC, max_num_coeff=max_num_coeff,
                                   override_total_coeffs=override_total_coeffs,
                                   override_trailing_ones=override_trailing_ones,
                                   debug_key=debug_key)

        # Extract bits as list
        bits = temp_writer.get_bits_as_list()

        return bits
