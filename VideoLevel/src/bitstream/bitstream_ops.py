"""
Bitstream Operations: Patcher and Reconstructor
================================================

Merged module combining:
  - BitArray / BitstreamPatcher: Direct bit-level patching at tracked offsets
  - BitstreamReconstructor: Full CAVLC re-encoding of H.264 slices

H.264 steganography embedding via smart bitstream patching.
"""

from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass

from .h264 import (
    NALUnit, NALUnitType, SliceHeaderParser, SPSData, PPSData,
    H264BitstreamParser, TraceableCAVLCParser,
)
from .cavlc import CAVLCEncoder, CAVLCDecoder
from .bitstream_io import BitstreamWriter, BitstreamReader


# =============================================================================
# BITSTREAM PATCHER  (formerly bitstream_patcher.py)
# =============================================================================



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

        # Build reverse lookup: end_bit → (key, offset_data) for retroactive boundary check.
        # When patching block B, we verify that the immediately preceding block A (whose
        # end_bit == B.start_bit) is not extended by the modified bits.  A H.264 decoder
        # reads block A's encoding in a streaming fashion; if B's new bits happen to form
        # the tail of a longer valid CAVLC codeword starting at A, the decoder overruns A
        # and misaligns all subsequent blocks — cascade desync.
        end_to_block = {}
        for blk_key, blk_offset in global_block_offsets.items():
            eb = blk_offset.get('end_bit')
            if eb is not None:
                end_to_block[eb] = (blk_key, blk_offset)

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

            # Use TraceableCAVLCParser's pre-computed nC exclusively when available.
            # This nC matches FFmpeg's H.264 spec computation from running neighbor TC values.
            #
            # CRITICAL: Never fall back to other nC values when tracer_nC is known.
            # Fallback scanning produces false-positive nC matches: e.g. nC=2 may
            # coincidentally round-trip for a block originally encoded with nC=4. The
            # forward check with nC=2 also passes (zero-padded gives the right bit count),
            # but FFmpeg computes nC=4 from context and reads 19 bits instead of 11,
            # causing cascade desync in the rest of the slice.
            tracer_nC = offset_info.get('nC', None) if isinstance(offset_info, dict) else None
            if tracer_nC is not None:
                nC_scan_order = [tracer_nC]  # ONLY use tracer_nC — fallbacks cause false positives
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

            # NOTE: T1 Position Safety Check was previously here but was removed once
            # CAVLCEncoder/Decoder sufLen progression was fixed to follow H.264 spec
            # (two separate if-statements instead of if/elif).  The round-trip forward
            # check (Step 6a) and retroactive boundary check (Step 6b) below are now
            # sufficient to catch any modifications that would produce invalid bitstreams.

            # Re-encode modified coefficients with trailing_ones override only.
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

            # Step 6a: Forward round-trip check — verify decode(new_bits, nC) consumes
            # EXACTLY original_length bits.  Length equality alone is insufficient:
            # for FLC6 (nC≥8) a T1 change (e.g. T1=2→0) can produce new_bits with the
            # same *count* of bits but a structurally-incomplete encoding that the
            # decoder overruns by 9+ bits into the next block, causing cascade desync.
            try:
                fwd_raw = self._bits_to_bytes(new_bits + [0] * 64)
                fwd_reader = BitstreamReader(fwd_raw)
                fwd_dec = CAVLCDecoder(fwd_reader)
                fwd_dec.decode_block_cavlc(nC, max_num_coeff=16)
                if fwd_reader.pos != original_length:
                    if patched_count < 2:
                        print(f"[PATCHER] SKIP {key}: new_bits decode consumes "
                              f"{fwd_reader.pos}b != {original_length}b (incomplete encoding)")
                    skipped_count += 1
                    continue
            except Exception:
                skipped_count += 1
                continue

            # Step 6b: Retroactive boundary corruption check.
            # Verify that placing new_bits at [start_bit, end_bit) does NOT extend the
            # CAVLC decoding of any ancestor block reachable by walking the directly-
            # connected chain backwards up to CHAIN_LOOKBACK_PATCH steps.
            # Short intermediate blocks (e.g. 1-bit) can be "transparent" gaps that
            # a mis-decoding ancestor overruns through, so a single-step check is not
            # sufficient.
            CHAIN_LOOKBACK_PATCH = 8
            chain_boundary_patch = start_bit
            retro_skip = False
            for _hop in range(CHAIN_LOOKBACK_PATCH):
                anc_entry = end_to_block.get(chain_boundary_patch)
                if anc_entry is None:
                    break
                anc_key_p, anc_offset_p = anc_entry
                anc_nC_p = anc_offset_p.get('nC')
                anc_start_p = anc_offset_p.get('start_bit')
                anc_len_p = anc_offset_p.get('bit_length')
                if anc_nC_p is None or anc_start_p is None or anc_len_p is None or anc_len_p <= 0:
                    break
                # ancestor A's own bits + unchanged intermediate bits between A's end and B
                anc_bits_p = list(rbsp_bits[anc_start_p:chain_boundary_patch])
                intermediate_p = list(rbsp_bits[chain_boundary_patch:start_bit])
                combined = self._bits_to_bytes(anc_bits_p + intermediate_p + new_bits + [0] * 64)
                try:
                    retro_reader = BitstreamReader(combined)
                    retro_dec = CAVLCDecoder(retro_reader)
                    retro_dec.decode_block_cavlc(anc_nC_p, max_num_coeff=16)
                    if retro_reader.pos != anc_len_p:
                        retro_skip = True
                        break
                except Exception:
                    retro_skip = True
                    break
                chain_boundary_patch = anc_start_p

            if retro_skip:
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

        # Build end_to_block reverse lookup for retroactive boundary check (second pass).
        end_to_block_retro = {}
        for blk_key, blk_offset in block_offsets.items():
            eb = blk_offset.get('end_bit')
            if eb is not None:
                end_to_block_retro[eb] = (blk_key, blk_offset)

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
            # CRITICAL: Only use tracer_nC when available — fallbacks cause false positives.
            tracer_nC = offset_data.get('nC', None) if isinstance(offset_data, dict) else None
            if tracer_nC is not None:
                nC_scan_order = [tracer_nC]  # ONLY use tracer_nC — fallbacks cause false positives
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

        # Second pass: retroactive boundary corruption check.
        # For each patchable block B, verify that NO single-bit flip of B's encoding
        # extends the CAVLC decoding of any ancestor block reachable by walking the
        # directly-connected block chain backwards up to CHAIN_LOOKBACK steps.
        #
        # Why multi-hop? Short intermediate blocks (e.g. 1-bit) can act as transparent
        # "gaps" that a mis-decoding ancestor overruns through.  A single-step check
        # would miss these transitive corruptions.
        CHAIN_LOOKBACK = 8  # Walk up to 8 blocks back; covers worst-case short chains
        for key in list(matched_info.keys()):
            offset_data = block_offsets.get(key, {})
            start_bit_b = offset_data.get('start_bit')
            end_bit_b = offset_data.get('end_bit')
            bit_length_b = offset_data.get('bit_length')
            if start_bit_b is None or bit_length_b is None or bit_length_b <= 0:
                continue

            b_orig_bits = list(rbsp_bits[start_bit_b:end_bit_b])

            retroactively_constrained = False

            # Walk the chain of directly-connected predecessors backward
            chain_boundary = start_bit_b  # The bit where B (or current chain head) starts
            for _hop in range(CHAIN_LOOKBACK):
                anc_entry = end_to_block_retro.get(chain_boundary)
                if anc_entry is None:
                    break  # Chain ends; no more predecessors

                anc_key, anc_offset = anc_entry
                anc_nC = anc_offset.get('nC')
                anc_start = anc_offset.get('start_bit')
                anc_len = anc_offset.get('bit_length')
                if anc_nC is None or anc_start is None or anc_len is None or anc_len <= 0:
                    break

                # ancestor A's own bits + intermediate bits between A's end and B's start
                anc_bits = list(rbsp_bits[anc_start:chain_boundary])         # A's encoding
                intermediate = list(rbsp_bits[chain_boundary:start_bit_b])   # gap bits (0 when direct)

                # Test each single-bit flip of B against ancestor A
                for p in range(bit_length_b):
                    b_flipped = b_orig_bits[:]
                    b_flipped[p] ^= 1
                    combined = self._bits_to_bytes(anc_bits + intermediate + b_flipped + [0] * 64)
                    try:
                        rr = BitstreamReader(combined)
                        rd = CAVLCDecoder(rr)
                        rd.decode_block_cavlc(anc_nC, max_num_coeff=16)
                        if rr.pos != anc_len:
                            retroactively_constrained = True
                            break
                    except Exception:
                        retroactively_constrained = True
                        break

                if retroactively_constrained:
                    break

                # Step one block further back
                chain_boundary = anc_start

            if retroactively_constrained:
                unpatchable.add(key)
                del matched_info[key]

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


# =============================================================================
# BITSTREAM RECONSTRUCTOR  (formerly bitstream_reconstructor.py)
# =============================================================================



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
                modified_mbs.add(mb_idx)  # Already slice-relative, no conversion needed
            
            # If no MBs modified in this slice, return original
            if not modified_mbs:
                return original_nal.rbsp_byte
            
            # Strategy: Re-encode entire slice with mixed original + modified coefficients
            
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
                # Preserve original start code size (3 or 4 bytes) to avoid byte shifts
                sc_size = getattr(nal, 'start_code_size', 4)
                if sc_size == 3:
                    f.write(b'\x00\x00\x01')
                else:
                    f.write(b'\x00\x00\x00\x01')

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

    def make_ffmpeg_position_validator(self, original_file: str, coefficients, frame_verified_data=None):
        """
        Build an FFmpeg-backed position validator.

        Parses the original file once, then returns a closure that tests each
        candidate embedding position by applying the modification to a temp file
        and running ``ffmpeg -v error``.

        Returns
        -------
        (validator, cleanup)
            validator(mb_idx, block_idx, coeff_idx) -> bool  (True = CLEAN)
            cleanup()  removes the temp file
        """
        import io as _io, contextlib as _ctx, subprocess as _sp, os as _os

        _parser = H264BitstreamParser(original_file)
        with _ctx.redirect_stdout(_io.StringIO()):
            _parser.parse()

        _sps = _pps = None
        for nal in _parser.nal_units:
            t = int(nal.nal_unit_type)
            if t == 7:
                _sps = self._parse_sps_from_nal(nal)
            elif t == 8:
                _pps = self._parse_pps_from_nal(nal)

        if not _sps:
            return (lambda mb, blk, cidx: True), (lambda: None)

        self.sps = _sps
        self.pps = _pps
        _mb_count = (_sps.pic_width_in_mbs_minus1 + 1) * (_sps.pic_height_in_map_units_minus1 + 1)

        _idr_nals = []
        _gmb = 0
        for nal in _parser.nal_units:
            t = int(nal.nal_unit_type)
            if t == 5:
                _idr_nals.append((_gmb, nal))
                _gmb += _mb_count
            elif t == 1:
                _gmb += _mb_count

        _coeff_lu = {(mb, blk): list(c) for mb, blk, c in coefficients}
        _tmp = _os.path.join(
            _os.path.dirname(_os.path.abspath(original_file)),
            "_ffmpeg_pos_validate.h264"
        )
        # Stateful: track committed mods per IDR so each new candidate is
        # tested CUMULATIVELY with all previously accepted modifications.
        # This catches cascade failures where N combined mods cause errors
        # even though each individual mod passes alone.
        _committed: Dict[int, list] = {}  # idr_idx -> [(mb, blk, mod_coeffs)]
        _fail_cache: set = set()          # (mb, blk, cidx) that are known-bad

        def _apply_mod(coeffs, coeff_idx):
            mod = list(coeffs)
            if coeff_idx >= 0:
                val = mod[coeff_idx]
                sign = 1 if val > 0 else -1
                ab = abs(val)
                mod[coeff_idx] = sign * ((ab & ~1) | ((ab & 1) ^ 1))
            else:
                mod[~coeff_idx] = -mod[~coeff_idx]
            return mod

        def _get_pre(idr_off):
            if not frame_verified_data or idr_off not in frame_verified_data:
                return None, None
            g_off, g_blk = frame_verified_data[idr_off]
            pre_off = {(mb - idr_off, blk): v
                       for (mb, blk), v in g_off.items() if mb >= idr_off}
            pre_blk = {(mb - idr_off, blk): v
                       for (mb, blk), v in g_blk.items() if mb >= idr_off}
            return pre_off, pre_blk

        def validator(mb_idx, block_idx, coeff_idx):
            key = (mb_idx, block_idx, coeff_idx)
            if key in _fail_cache:
                return False

            orig = _coeff_lu.get((mb_idx, block_idx))
            if orig is None:
                return True

            mod_coeffs = _apply_mod(orig, coeff_idx)
            if mod_coeffs == orig:
                return True  # No actual change – trivially safe, nothing to commit

            # Find which IDR NAL this macroblock belongs to
            idr_idx = idr_off = None
            for i, (off, _) in enumerate(_idr_nals):
                if off <= mb_idx < off + _mb_count:
                    idr_idx, idr_off = i, off
                    break
            if idr_idx is None:
                return True

            idr_nal = _idr_nals[idr_idx][1]
            pre_off, pre_blk = _get_pre(idr_off)

            # Cumulative test: all previously committed mods for this IDR + new candidate
            committed_this = _committed.get(idr_idx, [])
            all_mods = committed_this + [(mb_idx, block_idx, mod_coeffs)]

            patcher = BitstreamPatcher()
            _buf = _io.StringIO()
            with _ctx.redirect_stdout(_buf):
                modified_nal = patcher.patch_slice(
                    idr_nal, all_mods,
                    sps=_sps, pps=_pps, global_mb_offset=idr_off,
                    pre_computed_offsets=pre_off, pre_computed_blocks=pre_blk)

            if modified_nal is None or modified_nal.rbsp_byte == idr_nal.rbsp_byte:
                _fail_cache.add(key)
                return False

            # Write test H.264 file with patched IDR
            out_nals = []
            idr_seen = 0
            for nal in _parser.nal_units:
                if int(nal.nal_unit_type) == 5:
                    out_nals.append(modified_nal if idr_seen == idr_idx else nal)
                    idr_seen += 1
                else:
                    out_nals.append(nal)
            self._write_h264_file(out_nals, _tmp)

            r = _sp.run(
                ["ffmpeg", "-v", "error", "-i", _tmp, "-f", "null", "-"],
                capture_output=True, text=True
            )
            # With -v error, any [h264 @...] line is a genuine decode error.
            errors = [l for l in r.stderr.splitlines()
                      if l.strip() and "[h264" in l]
            is_clean = len(errors) == 0

            if is_clean:
                # Commit this modification so future candidates are tested against
                # the cumulative set of modifications actually applied in this IDR.
                if idr_idx not in _committed:
                    _committed[idr_idx] = []
                _committed[idr_idx].append((mb_idx, block_idx, mod_coeffs))
            else:
                _fail_cache.add(key)
            return is_clean

        def cleanup():
            if _os.path.exists(_tmp):
                _os.remove(_tmp)

        return validator, cleanup

    def batch_psnr_validate(
        self,
        original_file: str,
        coefficients: list,
        safe_positions: list,
        frame_verified_data: dict = None,
        psnr_threshold_db: float = 40.0,
        max_bisect_iters: int = 12,
        max_greedy_per_idr: int = 100,
    ) -> list:
        """
        Batch PSNR-based position validator.

        Tests all CAVLC-safe positions for each IDR in one shot, then
        binary-searches to find the maximum prefix that keeps decoded
        Y-PSNR >= psnr_threshold_db.

        Unlike make_ffmpeg_position_validator (which catches HARD decode
        errors per position), this catches SOFT pixel degradation from
        intra-prediction cascade by measuring actual decoded PSNR.

        Parameters
        ----------
        original_file      : path to the original (un-modified) H.264 file
        coefficients       : list[(mb, blk, coeffs)] — same as embed_payload input
        safe_positions     : output of get_safe_positions(), descending order
        frame_verified_data: same fvd dict used for reconstruction
        psnr_threshold_db  : minimum acceptable Y-PSNR on each modified IDR frame
        max_bisect_iters   : upper bound on binary-search iterations per IDR
        max_greedy_per_idr : after binary-search, try adding this many more
                             positions one-by-one (greedy extension).  Each
                             passing position is kept; conflicting ones are
                             skipped.  Finds non-contiguous safe positions that
                             the prefix-only binary search misses.

        Returns
        -------
        Filtered list of positions (subset of safe_positions) whose combined
        pixel impact keeps PSNR >= threshold.  Preserves descending order.
        """
        import io as _io, contextlib as _ctx, subprocess as _sp, os as _os
        import numpy as _np

        # ------------------------------------------------------------------ #
        # A — Parse SPS/PPS and build IDR NAL list (same pattern as           #
        #     make_ffmpeg_position_validator)                                  #
        # ------------------------------------------------------------------ #
        _parser = H264BitstreamParser(original_file)
        with _ctx.redirect_stdout(_io.StringIO()):
            _parser.parse()

        _sps = _pps = None
        _sps_nal = _pps_nal = None
        for nal in _parser.nal_units:
            t = int(nal.nal_unit_type)
            if t == 7:
                _sps = self._parse_sps_from_nal(nal)
                _sps_nal = nal
            elif t == 8:
                _pps = self._parse_pps_from_nal(nal)
                _pps_nal = nal

        if not _sps:
            return list(safe_positions)   # can't validate → accept all

        _mb_count = (
            (_sps.pic_width_in_mbs_minus1 + 1) *
            (_sps.pic_height_in_map_units_minus1 + 1)
        )
        w_px = (_sps.pic_width_in_mbs_minus1 + 1) * 16
        h_px = (_sps.pic_height_in_map_units_minus1 + 1) * 16
        _frame_y_bytes    = w_px * h_px
        _frame_yuv_bytes  = _frame_y_bytes * 3 // 2   # YUV420p

        _idr_nals: List[Tuple[int, object]] = []
        _gmb = 0
        for nal in _parser.nal_units:
            t = int(nal.nal_unit_type)
            if t == 5:
                _idr_nals.append((_gmb, nal))
                _gmb += _mb_count
            elif t == 1:
                _gmb += _mb_count

        _coeff_lu = {(mb, blk): list(c) for mb, blk, c in coefficients}
        _bdir = _os.path.dirname(_os.path.abspath(original_file))
        _f_orig_yuv  = _os.path.join(_bdir, "_batch_orig.yuv")
        _f_test_h264 = _os.path.join(_bdir, "_batch_test.h264")
        _f_stego_yuv = _os.path.join(_bdir, "_batch_stego.yuv")

        # ------------------------------------------------------------------ #
        # Helpers                                                              #
        # ------------------------------------------------------------------ #
        def _apply_mod(coeffs, coeff_idx):
            mod = list(coeffs)
            if coeff_idx >= 0:
                val  = mod[coeff_idx]
                sign = 1 if val > 0 else -1
                ab   = abs(val)
                mod[coeff_idx] = sign * ((ab & ~1) | ((ab & 1) ^ 1))
            else:
                mod[~coeff_idx] = -mod[~coeff_idx]
            return mod

        def _get_pre(idr_off):
            if not frame_verified_data or idr_off not in frame_verified_data:
                return None, None
            g_off, g_blk = frame_verified_data[idr_off]
            pre_off = {(mb - idr_off, blk): v
                       for (mb, blk), v in g_off.items() if mb >= idr_off}
            pre_blk = {(mb - idr_off, blk): v
                       for (mb, blk), v in g_blk.items() if mb >= idr_off}
            return pre_off, pre_blk

        def _read_y_frame(yuv_path, frame_idx):
            offset = frame_idx * _frame_yuv_bytes
            try:
                with open(yuv_path, 'rb') as fh:
                    fh.seek(offset)
                    data = fh.read(_frame_y_bytes)
            except OSError:
                return None
            if len(data) < _frame_y_bytes:
                return None
            return _np.frombuffer(data, dtype=_np.uint8).astype(_np.float32)

        def _psnr(a, b):
            mse = float(_np.mean((a - b) ** 2))
            return float('inf') if mse == 0 else 20.0 * float(_np.log10(255.0 / _np.sqrt(mse)))

        def _test_positions(idr_idx, idr_off, idr_nal, positions, orig_y):
            """Patch IDR with positions, decode, return Y-PSNR (float).

            Writes a minimal single-IDR file (SPS + PPS + patched IDR) so
            FFmpeg only decodes 1 frame — ~50x faster than decoding the
            whole video.  An IDR frame is intra-only, so its decoded pixels
            are identical to what a full-video decode would produce.
            """
            all_mods = []
            for mb, blk, cidx in positions:
                orig = _coeff_lu.get((mb, blk))
                if orig is None:
                    continue
                mod = _apply_mod(orig, cidx)
                if mod != orig:
                    all_mods.append((mb, blk, mod))

            if not all_mods:
                return float('inf')   # no real changes → perfect

            pre_off, pre_blk = _get_pre(idr_off)
            patcher = BitstreamPatcher()
            with _ctx.redirect_stdout(_io.StringIO()):
                modified_nal = patcher.patch_slice(
                    idr_nal, all_mods,
                    sps=_sps, pps=_pps, global_mb_offset=idr_off,
                    pre_computed_offsets=pre_off, pre_computed_blocks=pre_blk)

            if modified_nal is None:
                return 0.0   # patch failure → reject

            # Write MINIMAL file: SPS + PPS + single patched IDR frame.
            # IDR frames are intra-only and decode independently of all other
            # frames, making this ~50x faster than encoding the full video.
            minimal_nals = []
            if _sps_nal is not None:
                minimal_nals.append(_sps_nal)
            if _pps_nal is not None:
                minimal_nals.append(_pps_nal)
            minimal_nals.append(modified_nal)
            self._write_h264_file(minimal_nals, _f_test_h264)

            r = _sp.run(
                ["ffmpeg", "-y", "-v", "error",
                 "-i", _f_test_h264,
                 "-f", "rawvideo", "-pix_fmt", "yuv420p", _f_stego_yuv],
                capture_output=True,
            )
            if r.returncode != 0:
                return 0.0   # decode failure → reject

            # Only 1 frame in the minimal file → always frame index 0
            stego_y = _read_y_frame(_f_stego_yuv, 0)
            if stego_y is None:
                return 0.0
            return _psnr(orig_y, stego_y)

        # ------------------------------------------------------------------ #
        # B — Decode original to raw YUV once                                 #
        # ------------------------------------------------------------------ #
        try:
            _sp.run(
                ["ffmpeg", "-y", "-v", "error",
                 "-i", original_file,
                 "-f", "rawvideo", "-pix_fmt", "yuv420p", _f_orig_yuv],
                capture_output=True, check=True,
            )
        except (_sp.CalledProcessError, FileNotFoundError, OSError):
            return list(safe_positions)   # FFmpeg unavailable → accept all

        # ------------------------------------------------------------------ #
        # C — Group positions by IDR index                                    #
        # ------------------------------------------------------------------ #
        groups: Dict[int, list] = {}
        for pos in safe_positions:
            mb = pos[0]
            for i, (off, _) in enumerate(_idr_nals):
                if off <= mb < off + _mb_count:
                    groups.setdefault(i, []).append(pos)
                    break

        # ------------------------------------------------------------------ #
        # D — Per-IDR: fast path → binary search → greedy extension          #
        # ------------------------------------------------------------------ #
        validated: list = []
        ffmpeg_calls = 0
        try:
            for idr_idx, (idr_off, idr_nal) in enumerate(_idr_nals):
                positions = groups.get(idr_idx, [])
                if not positions:
                    continue

                frame_idx = idr_off // _mb_count
                orig_y = _read_y_frame(_f_orig_yuv, frame_idx)
                if orig_y is None:
                    # Could not read this frame → accept all positions for safety
                    validated.extend(positions)
                    continue

                # Fast path: test ALL positions for this IDR at once
                psnr = _test_positions(idr_idx, idr_off, idr_nal, positions, orig_y)
                ffmpeg_calls += 1

                if psnr >= psnr_threshold_db:
                    validated.extend(positions)
                    continue

                # Slow path: binary search for maximum safe prefix
                # positions is in DESCENDING mb order; adding more = more cascade
                lo, hi = 0, len(positions)
                for _ in range(max_bisect_iters):
                    if hi - lo <= 1:
                        break
                    mid = (lo + hi) // 2
                    p = _test_positions(idr_idx, idr_off, idr_nal, positions[:mid], orig_y)
                    ffmpeg_calls += 1
                    if p >= psnr_threshold_db:
                        lo = mid
                    else:
                        hi = mid

                # Greedy extension: test remaining positions one-by-one and
                # add each that keeps PSNR >= threshold when accumulated with
                # the already-accepted set.  This finds non-contiguous safe
                # positions that the prefix-only binary search would miss
                # (e.g. two adj MBs conflict but each is fine with distant MBs).
                accumulated = list(positions[:lo])
                greedy_attempts = 0
                for pos in positions[lo:]:
                    if greedy_attempts >= max_greedy_per_idr:
                        break
                    p = _test_positions(idr_idx, idr_off, idr_nal,
                                        accumulated + [pos], orig_y)
                    ffmpeg_calls += 1
                    greedy_attempts += 1
                    if p >= psnr_threshold_db:
                        accumulated.append(pos)
                validated.extend(accumulated)

        finally:
            for f in (_f_orig_yuv, _f_test_h264, _f_stego_yuv):
                try:
                    if _os.path.exists(f):
                        _os.remove(f)
                except OSError:
                    pass

        return validated
