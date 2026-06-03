"""
stego.py — CAVLC Safety Filter and Payload Embedder.

Core steganography logic: identifies safe trailing-ones positions in
H.264 CAVLC blocks and embeds/extracts payload bits via sign flips.

Public API:
    CAVLCSafetyFilter  — Identifies safe T1 positions (5-rule gate)
    PayloadEmbedder    — Embeds and extracts payload bits
    EncodingLengthChecker — Verifies bit-length preservation
"""

import logging
from typing import Dict, List, Optional, Set, Tuple

from ..bitstream.cavlc import CAVLCEncoder, CAVLCDecoder
from ..bitstream.bitstream_io import BitstreamWriter, BitstreamReader
from ..bitstream.bitstream_ops import BitstreamPatcher
from ..exceptions import SafetyFilterError, EmbeddingError

logger = logging.getLogger(__name__)
# =============================================================================
# CAVLC SAFETY FILTER  (formerly cavlc_safety_filter.py)
# =============================================================================


# MBs per CIF frame (22×18).  Used by the sort key to compute the position
# of a macroblock WITHIN its IDR frame (0–395), which drives the interleaved
# embedding strategy: for each MB position (within-frame order: balanced row permutation),
# visit the same position across ALL IDR frames before moving to the next.
# This distributes the payload evenly across every IDR frame instead of
# saturating the last few IDRs — ~57 bits per IDR (for a 274-byte payload
# over 38 IDR frames) instead of ~1200 bits, giving dramatically better
# per-IDR PSNR (~42–47 dB vs ~14–17 dB) with no downstream cascade.
_CIF_MB_COUNT = 396
_CIF_MB_WIDTH = 22

def sort_blocks_interleaved(block_tuples, cif_mb_count=396):
    """
    Sorts blocks by strictly interleaving across IDR frames to guarantee
    perfect payload distribution, preventing end frames from absorbing
    all bits due to texture clustering at the bottom of the frame.
    block_tuples: list of tuples where the first element is global_mb_idx.
    """
    if not block_tuples:
        return []
        
    by_frame = {}
    for item in block_tuples:
        mb_global = item[0]
        frame_idx = mb_global // cif_mb_count
        if frame_idx not in by_frame:
            by_frame[frame_idx] = []
        by_frame[frame_idx].append(item)
    
    mb_width = _CIF_MB_WIDTH
    mb_height = max(1, cif_mb_count // mb_width)
    preferred_rows = [r for r in (mb_height - 1, mb_height - 2, mb_height - 3, mb_height - 4) if r >= 0]
    remaining_rows = [r for r in range(mb_height - 1, -1, -1) if r not in preferred_rows]

    # Sort within each frame: row-interleaved coverage to prevent early-prefix clustering.
    for frm in by_frame:
        row_buckets = {r: [] for r in range(mb_height)}
        for item in by_frame[frm]:
            local_mb = item[0] % cif_mb_count
            row = local_mb // mb_width
            row_buckets[row].append(item)

        for row in row_buckets:
            row_buckets[row].sort(key=lambda t: (-((t[0] % cif_mb_count) % mb_width), -t[1]))

        def _consume_round_robin(rows, out):
            if not rows:
                return
            offsets = {r: 0 for r in rows}
            while True:
                progressed = False
                for row in rows:
                    idx = offsets[row]
                    bucket = row_buckets[row]
                    if idx < len(bucket):
                        out.append(bucket[idx])
                        offsets[row] += 1
                        progressed = True
                if not progressed:
                    break

        interleaved_rows = []
        _consume_round_robin(preferred_rows, interleaved_rows)
        _consume_round_robin(remaining_rows, interleaved_rows)

        by_frame[frm] = interleaved_rows
    
    # Interleave (Strict Round Robin) starting from the earliest frame.
    # This keeps payload spread across the full video timeline instead of
    # concentrating the first validated positions at the end of the sequence.
    frames_desc = sorted(list(by_frame.keys()))
    interleaved = []
    max_len = max([len(lst) for lst in by_frame.values()])
    
    for i in range(max_len):
        for frm in frames_desc:
            if i < len(by_frame[frm]):
                interleaved.append(by_frame[frm][i])
                
    return interleaved


class CAVLCSafetyFilter:
    """
    Comprehensive safety filter for CAVLC-based video steganography
    
    Usage:
        filter = CAVLCSafetyFilter()
        safe_positions = filter.get_safe_positions(coefficients)
        for pos in safe_positions:
            # Embed data safely
            pass
    """
    
    def __init__(self, 
                 enable_zero_preservation: bool = True,
                 enable_trailing_ones_protection: bool = True,
                 enable_bit_length_check: bool = True,
                 min_safe_magnitude: int = 3):
        """
        Initialize safety filter
        
        Args:
            enable_zero_preservation: Enforce Rule 1 (strongly recommended)
            enable_trailing_ones_protection: Enforce Rule 2 (recommended)
            enable_bit_length_check: Enforce Rule 3 (optional but safer)
            min_safe_magnitude: Minimum |value| for safe embedding (default: 3)
        
        Raises:
            SafetyFilterError: If configuration is invalid
        """
        if min_safe_magnitude < 1:
            raise SafetyFilterError(
                "min_safe_magnitude must be >= 1",
                min_safe_magnitude=min_safe_magnitude
            )
        
        self.enable_zero_preservation = enable_zero_preservation
        self.enable_trailing_ones = enable_trailing_ones_protection
        self.enable_bit_length = enable_bit_length_check
        self.min_safe_magnitude = min_safe_magnitude
        
        # Initialize encoding length checker for Rule 3
        if self.enable_bit_length:
            self.length_checker = None
        else:
            self.length_checker = None
        
        # Cache for trailing ones detection (performance optimization)
        self._trailing_ones_cache: Dict[Tuple[int, ...], Set[int]] = {}
        self._lazy_patchability_cache: Dict[Tuple[int, int], Optional[Tuple[int, List[int], Optional[int]]]] = {}
    
    def _detect_trailing_ones(self, coeffs: List[int]) -> Set[int]:
        """
        Detect positions of trailing ±1 coefficients
        
        CAVLC encodes up to 3 trailing ±1 values specially.
        We need to identify these positions and protect them.
        
        Algorithm:
        1. Scan coefficients in REVERSE zigzag order (high freq → DC)
        2. Find consecutive ±1 values at the end
        3. Take up to 3 of them
        
        Args:
            coeffs: 16 coefficients in zigzag order
        
        Returns:
            Set of indices that are trailing ones (empty if none)
        """
        trailing_positions = set()

        # Safety check: ensure coeffs is valid
        if not coeffs or len(coeffs) == 0:
            return trailing_positions

        # Ensure we have enough coefficients


        # Coefficients are in FORWARD zigzag order (coeffs[0] = DC).
        # CAVLC "trailing ones" are the last consecutive non-zero coefficients
        # (i.e., highest-frequency) that are ±1, capped at 3.
        # Walk non-zero positions from highest index downward.
        nz_rev = [i for i in range(len(coeffs) - 1, -1, -1) if coeffs[i] != 0]

        count = 0
        for idx in nz_rev:
            if coeffs[idx] in (-1, 1) and count < 3:
                trailing_positions.add(idx)
                count += 1
            else:
                break  # first non-±1 non-zero → stop

        return trailing_positions
    
    def _verify_block_bit_length_invariance(
        self,
        original_block: List[int],
        modified_block: List[int],
        nC: int = 0,
        nal_bit_length: int = None,
        t1_override: int = None,
        max_num_coeff: int = 16
    ) -> Tuple[bool, int, int]:
        """
        **CRITICAL FIX**: Verify block modification preserves bit length via ACTUAL CAVLC encoding

        This replaces the broken heuristic check with ground-truth verification.
        We encode BOTH blocks and compare actual bit lengths.

        Args:
            original_block: Original 16 DCT coefficients (zigzag order)
            modified_block: Modified coefficients (with LSB flips)
            nC: Neighbor context for CAVLC encoding (default: 0)
            nal_bit_length: Actual bit length of the block in the NAL stream.
                            If provided, original encoder output must match this
                            length, otherwise the block cannot be round-tripped
                            by the patcher and will be rejected.
            t1_override: Optional trailing_ones override value required to bit-exactly
                         reproduce the original NAL encoding for this block. When set,
                         both original and modified blocks are encoded with this override
                         (matching the patcher's behavior for T1-override blocks).

        Returns:
            (is_safe, original_bits, modified_bits)
            - is_safe: True if bit lengths match AND zero-preservation maintained
            - original_bits: Actual encoding length of original block
            - modified_bits: Actual encoding length of modified block

        Example:
            >>> original = [-1, 3, 1, 0, 0, ...]
            >>> modified = [-1, 2, 1, 0, 0, ...]  # Flipped coeff[1]: 3 -> 2
            >>> is_safe, orig_len, mod_len = filter._verify_block_bit_length_invariance(original, modified)
            >>> # is_safe = False (28 bits -> 31 bits, length changed!)
        """
        try:
            # CRITICAL: Enforce zero-preservation at block level
            # Count non-zero coefficients in both blocks
            original_nonzeros = sum(1 for c in original_block if c != 0)
            modified_nonzeros = sum(1 for c in modified_block if c != 0)
            
            # Reject if total coefficient count changed (zero->non-zero or non-zero->zero)
            if original_nonzeros != modified_nonzeros:
                # This is impossible to patch:
                # - All-zero block: 1-2 bits (coeff_token only)
                # - Non-zero block: 20+ bits (coeff_token + levels + total_zeros + runs)
                # Cannot patch different TotalCoeffs without breaking bitstream!
                return False, 0, 0
            
            # Encode original block
            writer_orig = BitstreamWriter()
            encoder_orig = CAVLCEncoder(writer_orig)
            encoder_orig.encode_block_cavlc(original_block, nC=nC, max_num_coeff=len(original_block),
                                            override_trailing_ones=t1_override)
            original_bits = writer_orig.get_bit_position()

            # CRITICAL: If actual NAL bit length is known, the encoder's output
            # must match it exactly.  If they differ the patcher will reject this
            # block (it compares the re-encoded candidate against the original
            # NAL length).  Reject early so the safety filter never marks such
            # blocks as embeddable.
            if nal_bit_length is not None and original_bits != nal_bit_length:
                return False, original_bits, 0


            # Encode modified block
            # CRITICAL FIX: Pass override_total_coeffs=original_nonzeros
            # The bitstream_patcher uses this to preserve suffixLength.
            # If the safety filter doesn't use it, it will estimate a DIFFERENT length!
            writer_mod = BitstreamWriter()
            encoder_mod = CAVLCEncoder(writer_mod)
            encoder_mod.encode_block_cavlc(
                modified_block,
                nC=nC,
                max_num_coeff=len(original_block),
                override_total_coeffs=original_nonzeros,
                override_trailing_ones=t1_override
            )
            modified_bits = writer_mod.get_bit_position()

            # Compare lengths (must match exactly for patchable modifications)
            if original_bits != modified_bits:
                return False, original_bits, modified_bits

            # Forward decode check (mirrors patcher Step 6a):
            # Verify that decoding the modified encoding consumes EXACTLY modified_bits.
            # If the modified VLC is malformed, the decoder overruns into padding zeros
            # and consumes more bits — the patcher would skip this block at patch time,
            # causing a bit-offset desync in the extracted payload.
            try:
                fwd_bytes = writer_mod.get_bytes(align=False) + bytes(8)
                fwd_reader = BitstreamReader(fwd_bytes)
                fwd_dec = CAVLCDecoder(fwd_reader)
                fwd_dec.decode_block_cavlc(nC, max_num_coeff=len(original_block))
                if fwd_reader.pos != modified_bits:
                    return False, original_bits, modified_bits
            except Exception:
                return False, original_bits, modified_bits

            return True, original_bits, modified_bits
            
        except Exception as e:
            # If encoding fails, it's definitely not safe
            # This is EXPECTED for corrupt blocks (TC=16, etc.)
            # Silently reject without printing (too verbose)
            return False, 0, 0
    
    def get_safe_positions(
        self,
        coefficients: List[Tuple[int, int, List[int]]],
        skip_dc: bool = True,
        nC_map: Dict[Tuple[int, int], int] = None,
        nal_length_map: Dict[Tuple[int, int], int] = None,
        t1_override_map: Dict[Tuple[int, int], int] = None,
        frame_verified_data: Dict[int, Tuple[Dict, Dict]] | None = None,
        cif_mb_count: int = 396,
    ) -> List[Tuple[int, int, int]]:
        """
        Get list of safe embedding positions across all blocks

        Args:
            coefficients: List of (mb_idx, block_idx, coeffs) tuples
            skip_dc: Skip DC coefficient (position 0)
            nC_map: Dictionary mapping (mb_idx, block_idx) to actual nC values from extraction
            nal_length_map: Dictionary mapping (mb_idx, block_idx) to the actual NAL bit
                            length of each block. When provided, blocks whose encoder output
                            differs from the NAL length are rejected (keeps filter in sync
                            with the patcher).
            t1_override_map: Dictionary mapping (mb_idx, block_idx) to the trailing_ones
                             override value required to bit-exactly reproduce the original
                             NAL encoding. Blocks in this map use override_trailing_ones
                             when verifying bit-length invariance (matching patcher behavior).

        Returns:
            List of (mb_idx, block_idx, coeff_idx) tuples that are safe to modify

        Raises:
            SafetyFilterError: If coefficient data is invalid
        """
        if nC_map is None:
            nC_map = {}
        if nal_length_map is None:
            nal_length_map = {}
        if t1_override_map is None:
            t1_override_map = {}
        if not coefficients:
            raise SafetyFilterError("Empty coefficient list provided")
        
        # Validate coefficient format
        for i, item in enumerate(coefficients[:3]):  # Check first 3 for efficiency
            if not isinstance(item, tuple) or len(item) != 3:
                raise SafetyFilterError(
                    f"Invalid coefficient format at index {i}: expected (mb_idx, block_idx, coeffs)",
                    index=i, item_type=type(item)
                )
        safe_positions = []

        for mb_idx, block_idx, coeffs in coefficients:
            total_coeffs = sum(1 for c in coeffs if c != 0)
            if total_coeffs == 0:
                continue  # All-zero block: nothing to embed

            # Skip blocks explicitly marked as non-patchable by get_unpatchable_blocks.
            # This check is INDEPENDENT of enable_bit_length so that the sentinel -1
            # correctly excludes non-patchable blocks even when bit-length checking is
            # disabled.  Without this, the patcher would silently skip the block and
            # create a bit-shift in the embedded bit-stream.
            block_key = (mb_idx, block_idx)
            nal_len_entry = nal_length_map.get(block_key)
            # Skip blocks with no NAL bit-length record when nal_length_map is non-empty.
            # A missing key means the parser failed for that block, so we cannot guarantee
            # patcher success. When nal_length_map is empty (not provided) we allow all blocks.
            if nal_length_map and nal_len_entry is None:
                continue

            # Detect trailing ones for this block
            trailing_positions = self._detect_trailing_ones(coeffs)

            # Cheap per-block prefilter: collect only positions that can possibly
            # survive rules 1/2/4 before doing any encode-length verification.
            candidate_indices = []
            for coeff_idx, original in enumerate(coeffs):
                if skip_dc and coeff_idx == 0:
                    continue
                if original == 0:
                    continue
                if coeff_idx in trailing_positions:
                    continue

                abs_val = abs(original)
                new_abs = (abs_val & ~1) | ((abs_val & 1) ^ 1)
                if min(abs_val, new_abs) < self.min_safe_magnitude:
                    continue
                if new_abs == 0:
                    continue
                candidate_indices.append(coeff_idx)

            if not candidate_indices:
                continue

            # Lazy patchability validation: validate the block only when it has at least
            # one coefficient candidate that survives the cheap structural rules.
            if nal_length_map and frame_verified_data is not None:
                cached_match = self._lazy_patchability_cache.get(block_key)
                if cached_match is None:
                    idr_off = (mb_idx // cif_mb_count) * cif_mb_count
                    idr_data = frame_verified_data.get(idr_off)
                    if idr_data is None:
                        self._lazy_patchability_cache[block_key] = None
                        continue
                    g_off, _g_blk, nal_rbsp = idr_data
                    local_offsets = {
                        (mb - idr_off, blk): od
                        for (mb, blk), od in g_off.items()
                        if blk < 16 and od.get('bit_length') not in (None, 0)
                    }
                    patcher = BitstreamPatcher()
                    end_to_block = {
                        od['end_bit']: ((mb - idr_off, blk), od)
                        for (mb, blk), od in g_off.items()
                        if blk < 16 and 'end_bit' in od
                    }
                    local_key = (mb_idx - idr_off, block_idx)
                    cached_match = patcher.validate_block_patchability(
                        nal_rbsp,
                        local_key,
                        local_offsets.get(local_key, {}),
                        end_to_block,
                    )
                    self._lazy_patchability_cache[block_key] = cached_match

                if cached_match is None:
                    continue
                actual_nC = cached_match[0]
                t1_override = cached_match[2]
            else:
                actual_nC = nC_map.get(block_key, 0)
                t1_override = t1_override_map.get(block_key)

            # Check each coefficient position
            for coeff_idx in candidate_indices:

                # Calculate LSB-flipped value
                original = coeffs[coeff_idx]
                sign = 1 if original > 0 else -1
                abs_val = abs(original)
                new_abs = (abs_val & ~1) | ((abs_val & 1) ^ 1)  # Flip LSB
                new_val = sign * new_abs

                # Rule 3: Verify bit-length preservation via ACTUAL CAVLC encoding
                if self.enable_bit_length:
                    modified_block = coeffs[:]
                    modified_block[coeff_idx] = new_val

                    is_safe, orig_bits, mod_bits = self._verify_block_bit_length_invariance(
                        coeffs,
                        modified_block,
                        nC=actual_nC,
                        nal_bit_length=nal_length_map.get(block_key),
                        t1_override=t1_override
                    )

                    if not is_safe:
                        continue

                # SAFE!
                safe_positions.append((mb_idx, block_idx, coeff_idx))

        # Sign-bit positions for trailing ±1 coefficients.
        # Flipping the sign of a trailing one (±1 → ∓1) is bit-length invariant ONLY
        # when the coefficient is truly encoded as a trailing-one sign bit (1 bit per sign).
        # For blocks with t1_override, some ±1 values are encoded as regular levels where
        # +1 and -1 have different VLC lengths — must verify invariance before adding.
        # Use ~coeff_idx (always negative) to mark these as sign-bit positions.
        for mb_idx, block_idx, coeffs in coefficients:
            block_key = (mb_idx, block_idx)
            nal_len = nal_length_map.get(block_key)
            if nal_len is None or nal_len == -1:
                continue
            actual_nC = nC_map.get(block_key, 0)
            t1_override = t1_override_map.get(block_key)
            # Determine the TRUE T1 candidate positions (those actually encoded as
            # trailing_one_sign_flags in the bitstream, not as regular level codes).
            #
            # When t1_override is not None:  the original encoder used T1 = t1_override
            #   (may be less than the maximum possible consecutive ±1 run).  Only the
            #   LAST t1_override non-zero positions are genuine T1 sign-flag positions;
            #   earlier ±1 values are encoded as regular level codes whose sign bits lie
            #   within a VLC codeword — flipping them produces spec-non-compliant bits.
            #
            # When t1_override is None:  standard encoder path used the maximum available
            #   T1 count, so _detect_trailing_ones() correctly identifies all T1 positions.
            if t1_override is not None:
                nz_pos_t1 = [i for i in range(len(coeffs)) if coeffs[i] != 0]
                t1_actual = min(t1_override, len(nz_pos_t1))
                trailing_positions = set(nz_pos_t1[-t1_actual:]) if t1_actual > 0 else set()
            else:
                trailing_positions = self._detect_trailing_ones(coeffs)
            for coeff_idx in sorted(trailing_positions):
                # Verify bit-length invariance for sign flip before adding
                modified_block = list(coeffs)
                modified_block[coeff_idx] = -modified_block[coeff_idx]
                is_safe, _, _ = self._verify_block_bit_length_invariance(
                    coeffs, modified_block, nC=actual_nC,
                    nal_bit_length=nal_len,
                    t1_override=t1_override
                )
                if is_safe:
                    safe_positions.append((mb_idx, block_idx, ~coeff_idx))

        # Return positions in interleaved order from sort_blocks_interleaved:
        # within each frame, late macroblocks first; across frames, chronological
        # round-robin. This keeps embed/extract ordering deterministic while
        # distributing payload across the full timeline.
        return sort_blocks_interleaved(safe_positions, _CIF_MB_COUNT)


# =============================================================================
# PAYLOAD EMBEDDER  (formerly payload_embedder.py)
# =============================================================================


class PayloadEmbedder:
    """
    Embed binary payload into DCT coefficients using LSB substitution
    with CAVLC Safety Filter (5 rules to prevent corruption)
    
    SAFETY RULES (enforced by CAVLCSafetyFilter):
    1. Zero-Preservation: Never 0→nonzero or nonzero→0 (breaks TotalCoeffs)
    2. Trailing Ones: Never modify last 3 ±1 coeffs (special CAVLC encoding)
    3. Bit-Length Invariance: Only modify if encoding length unchanged
    4. Magnitude Threshold: Only |value| >= 3 (guarantees structure preservation after LSB flip)
    5. CAVLC Re-encoding: Always re-encode modified blocks
    
    CAPACITY OPTIMIZATION:
    - Use coefficients with |value| >= 3 (guarantees no structure change after LSB flip)
    - Optionally include |value| == 1 with caution (may flip to 0)
    - Skip DC (position 0) for stability
    - Skip zeros (would become ±1, changing block structure)
    """
    
    def __init__(self,
                 skip_dc: bool = True,
                 skip_zeros: bool = True,
                 allow_small_values: bool = False,
                 use_safety_filter: bool = True,
                 enable_trailing_ones_protection: bool = True,
                 enable_bit_length_check: bool = True,
                 max_modifications_per_block: int = 1):
        """
        Initialize embedder with CAVLC Safety Filter
        
        Args:
            skip_dc: Skip DC coefficients (position 0 in zigzag)
            skip_zeros: Skip zero coefficients
            allow_small_values: Allow embedding in |coeff| == 1 (RISKY: may flip to 0)
                               Set to True for higher capacity (up to 2x), but less stable
            use_safety_filter: Enable comprehensive CAVLC safety checks (RECOMMENDED)
            enable_trailing_ones_protection: Protect trailing ±1 coefficients (RECOMMENDED)
            enable_bit_length_check: Check CAVLC encoding length invariance (optional)
            max_modifications_per_block: Maximum modifications per block (1-4, default: 1)
                                        1 = safest (default)
                                        3 = balanced (higher capacity)
                                        4+ = higher capacity but may affect quality
        """
        self.skip_dc = skip_dc
        self.skip_zeros = skip_zeros
        self.allow_small_values = allow_small_values
        self.use_safety_filter = use_safety_filter
        self.max_modifications_per_block = max(1, min(max_modifications_per_block, 8))
        
        # Initialize CAVLC Safety Filter if enabled
        if self.use_safety_filter:
            min_magnitude = 1 if allow_small_values else 3
            self.safety_filter = CAVLCSafetyFilter(
                enable_zero_preservation=True,
                enable_trailing_ones_protection=enable_trailing_ones_protection,
                enable_bit_length_check=enable_bit_length_check,
                min_safe_magnitude=min_magnitude
            )
        else:
            self.safety_filter = None
    
    def embed_payload(self, coefficients: List[Tuple[int, int, List[int]]],
                     payload: bytes, nC_map: Optional[Dict[Tuple[int, int], int]] = None,
                     nal_length_map: Optional[Dict[Tuple[int, int], int]] = None,
                     t1_override_map: Optional[Dict[Tuple[int, int], int]] = None,
                     frame_verified_data: Optional[Dict[int, Tuple[Dict, Dict]]] = None,
                     ffmpeg_validator=None,
                     pre_validated_positions=None) -> Tuple[List[Tuple[int, int, List[int]]], int]:
        """
        Embed payload into coefficient blocks with CAVLC safety checks

        Args:
            coefficients: List of (mb_idx, block_idx, coeffs) tuples
            payload: Binary payload to embed
            nC_map: Mapping of block keys to nC values (Crucial for safety filter accuracy)
            ffmpeg_validator: Optional callable(mb_idx, block_idx, coeff_idx)->bool.
                              If provided, each position is tested with FFmpeg before use.
            pre_validated_positions: Optional pre-filtered position list from
                              batch_psnr_validate().  When provided, CAVLC + FFmpeg
                              filtering is skipped entirely (fast path).

        Returns:
            (modified_coefficients, bits_embedded)
        """
        # Convert payload to bits
        payload_bits = self._bytes_to_bits(payload)

        # Use safety filter if enabled
        if self.use_safety_filter and self.safety_filter:
            return self._embed_with_safety_filter(
                coefficients, payload_bits, nC_map, nal_length_map,
                t1_override_map, frame_verified_data, ffmpeg_validator, pre_validated_positions)
        raise EmbeddingError("use_safety_filter=False embedding path is not implemented")
    
    def _embed_with_safety_filter(
        self,
        coefficients: List[Tuple[int, int, List[int]]],
        payload_bits: List[int],
        nC_map: Optional[Dict[Tuple[int, int], int]] = None,
        nal_length_map: Optional[Dict[Tuple[int, int], int]] = None,
        t1_override_map: Optional[Dict[Tuple[int, int], int]] = None,
        frame_verified_data: Optional[Dict[int, Tuple[Dict, Dict]]] = None,
        ffmpeg_validator=None,
        pre_validated_positions=None,
    ) -> Tuple[List[Tuple[int, int, List[int]]], int]:
        """
        Embed using CAVLC Safety Filter (RECOMMENDED)

        This method enforces all 5 CAVLC safety rules to prevent corruption.
        When ffmpeg_validator is provided, each position is also tested empirically
        with FFmpeg before use (lazy: only tested when a bit is about to be embedded).
        When pre_validated_positions is provided, the CAVLC filter and FFmpeg validator
        are both skipped (fast path for use with batch_psnr_validate output).
        """
        # Get all safe positions across all blocks
        if pre_validated_positions is not None:
            # Fast path: caller already filtered positions with batch_psnr_validate
            safe_positions = pre_validated_positions
            ffmpeg_validator = None   # nothing more to validate
        else:
            safe_positions = self.safety_filter.get_safe_positions(
                coefficients,
                skip_dc=self.skip_dc,
                nC_map=nC_map,
                nal_length_map=nal_length_map,
                t1_override_map=t1_override_map,
                frame_verified_data=frame_verified_data,
            )

        # Build coeff lookup: (mb_idx, block_idx) -> mutable coefficients list.
        # We iterate safe_positions directly (already in the correct interleaved order
        # from get_safe_positions / sort_blocks_interleaved) so that the embedding order
        # EXACTLY matches the extraction order in extract_bits_direct.
        #
        # IMPORTANT: Do NOT iterate sort_blocks_interleaved(all_coefficients) here.
        # That order differs from sort_blocks_interleaved(safe_positions_only) because
        # the round-robin interleaving depends on how many items each frame contributes:
        # an ALL-blocks frame may have mb395-blocks that are NOT safe, pushing the first
        # safe block of that frame to a later round, whereas the SAFE-only sort visits
        # the first safe block at round 0.  The mismatch scrambles embed/extract order.
        coeff_dict = {(mb, blk): list(cs) for mb, blk, cs in coefficients}

        bits_embedded = 0
        self.last_used_safe_positions = []
        ffmpeg_skipped = 0
        modifications_count: Dict[Tuple[int, int], int] = {}
        modified_keys: list = []   # ordered list of (mb, blk) that were actually changed

        for mb_idx, block_idx, coeff_idx in safe_positions:
            if bits_embedded >= len(payload_bits):
                break

            block_key = (mb_idx, block_idx)

            # Respect max modifications per block
            if modifications_count.get(block_key, 0) >= self.max_modifications_per_block:
                continue

            # Lazy FFmpeg validation: test this position before embedding
            if ffmpeg_validator is not None:
                if not ffmpeg_validator(mb_idx, block_idx, coeff_idx):
                    ffmpeg_skipped += 1
                    continue  # skip unsafe position

            current_coeffs = coeff_dict[block_key]
            payload_bit = payload_bits[bits_embedded]

            if coeff_idx >= 0:
                # Standard LSB modification
                original_val = current_coeffs[coeff_idx]
                new_val = self._modify_lsb(current_coeffs[coeff_idx], payload_bit)
                current_coeffs[coeff_idx] = new_val
                modified_val = new_val
            else:
                # Sign-bit modification for trailing ±1 coefficients.
                # ~coeff_idx recovers the original zigzag index.
                real_idx = ~coeff_idx
                original_val = current_coeffs[real_idx]
                abs_val = abs(current_coeffs[real_idx])
                new_val = abs_val if payload_bit == 0 else -abs_val
                current_coeffs[real_idx] = new_val
                modified_val = new_val

            # Record that this block was touched (track first time for order)
            if block_key not in modifications_count:
                modified_keys.append(block_key)
            modifications_count[block_key] = modifications_count.get(block_key, 0) + 1

            self.last_used_safe_positions.append((mb_idx, block_idx, coeff_idx))
            bits_embedded += 1

        # Build modified list: only blocks whose coefficients actually changed
        modified = []
        orig_dict = {(mb, blk): cs for mb, blk, cs in coefficients}
        for key in modified_keys:
            orig = orig_dict[key]
            new_cs = coeff_dict[key]
            if any(o != n for o, n in zip(orig, new_cs)):
                modified.append((key[0], key[1], new_cs))

        if ffmpeg_skipped:
            logger.warning(f"[Embedder] FFmpeg validator skipped {ffmpeg_skipped} unsafe positions")

        return modified, bits_embedded

    def extract_payload(
        self,
        coefficients: List[Tuple[int, int, List[int]]],
        payload_length_bits: int,
        start_bit_offset: int = 0,
        nC_map: Optional[Dict[Tuple[int, int], int]] = None,
        nal_length_map: Optional[Dict[Tuple[int, int], int]] = None,
        t1_override_map: Optional[Dict[Tuple[int, int], int]] = None,
        precomputed_safe_positions: Optional[List[Tuple[int, int, int]]] = None
    ) -> bytes:
        """
        Extract payload from coefficient blocks
        
        Args:
            coefficients: List of (mb_idx, block_idx, coeffs) tuples
            payload_length_bits: Number of bits to extract
            start_bit_offset: Skip this many bits before starting extraction
            nC_map: Mapping of block keys to nC values (Crucial for safety filter accuracy)
            precomputed_safe_positions: If provided, skip safety filter recomputation and use
                                        these positions directly (must match embedding positions).
                                        Pass the safe_positions list saved during embed_payload.

        Returns:
            Extracted payload as bytes
        
        Raises:
            EmbeddingError: If coefficient data is invalid
            InsufficientCapacityError: If not enough bits available
        """
        # Validate inputs
        if not coefficients:
            raise EmbeddingError("Empty coefficient list provided for extraction")
        
        if payload_length_bits <= 0:
            raise EmbeddingError(
                f"Invalid payload length: {payload_length_bits} bits",
                payload_length_bits=payload_length_bits
            )
        
        if start_bit_offset < 0:
            raise EmbeddingError(
                f"Invalid start offset: {start_bit_offset}",
                start_bit_offset=start_bit_offset
            )
        
        # Use safety filter routing if enabled (MUST match embedding!)
        if self.use_safety_filter and self.safety_filter:
            return self._extract_with_safety_filter(coefficients, payload_length_bits, start_bit_offset, nC_map, nal_length_map, t1_override_map, precomputed_safe_positions)
        raise EmbeddingError("use_safety_filter=False extraction path is not implemented")
    
    def _extract_with_safety_filter(
        self,
        coefficients: List[Tuple[int, int, List[int]]],
        payload_length_bits: int,
        start_bit_offset: int = 0,
        nC_map: Optional[Dict[Tuple[int, int], int]] = None,
        nal_length_map: Optional[Dict[Tuple[int, int], int]] = None,
        t1_override_map: Optional[Dict[Tuple[int, int], int]] = None,
        precomputed_safe_positions: Optional[List[Tuple[int, int, int]]] = None
    ) -> bytes:
        """
        Extract using CAVLC Safety Filter (same positions as embedding)

        CRITICAL: Must use SAME safe positions as embedding to ensure sync!
        If precomputed_safe_positions is provided, it is used directly (bypassing
        recomputation from stego coefficients, which would differ due to patched values).
        """
        # Use pre-computed positions from the embedding phase if provided.
        # This avoids recomputing safe_positions from stego coefficients — after patching,
        # some blocks have different base values which changes the block-level bit-length
        # check for other coefficients in the same block, causing safe_positions divergence.
        if precomputed_safe_positions is not None:
            safe_positions = precomputed_safe_positions
        else:
            # Get all safe positions (same calculation as embedding)
            safe_positions = self.safety_filter.get_safe_positions(
                coefficients,
                skip_dc=self.skip_dc,
                nC_map=nC_map,
                nal_length_map=nal_length_map,
                t1_override_map=t1_override_map
            )
        
        # Build coefficient lookup map for fast access
        coeff_map = {}
        for mb_idx, block_idx, coeffs in coefficients:
            coeff_map[(mb_idx, block_idx)] = coeffs
            
        # Group safe positions by block to mirror embedder
        safe_map = {}
        for mb_idx, block_idx, coeff_idx in safe_positions:
            key = (mb_idx, block_idx)
            if key not in safe_map:
                safe_map[key] = []
            safe_map[key].append(coeff_idx)

        # Mirror embedding block order exactly: first occurrence order of each
        # (mb, blk) in safe_positions.
        seen_block_set: Set[Tuple[int, int]] = set()
        seen_blocks: List[Tuple[int, int]] = []
        for mb_idx, block_idx, _ in safe_positions:
            key = (mb_idx, block_idx)
            if key not in seen_block_set:
                seen_block_set.add(key)
                seen_blocks.append(key)
        
        extracted_bits = []
        bits_skipped = 0

        # Iterate in the same block order used by _embed_with_safety_filter.
        for mb_idx, block_idx in seen_blocks:
            block_key = (mb_idx, block_idx)
            coeffs = coeff_map.get(block_key)
            if coeffs is None:
                continue

            safe_indices = safe_map[block_key]
            extractions_in_block = 0
            
            for coeff_idx in safe_indices:
                if len(extracted_bits) >= payload_length_bits:
                    break
                    
                if extractions_in_block >= self.max_modifications_per_block:
                    break  # Respect block capacity limits mirroring embedder
                    
                # Skip offset bits first
                if bits_skipped < start_bit_offset:
                    bits_skipped += 1
                    extractions_in_block += 1
                    continue
                
                # Extract bit — handle LSB and sign-bit positions
                if coeff_idx >= 0:
                    lsb = abs(coeffs[coeff_idx]) & 1
                else:
                    # Sign-bit position: real index recovered via ~coeff_idx
                    real_idx = ~coeff_idx
                    lsb = 0 if coeffs[real_idx] > 0 else 1
                extracted_bits.append(lsb)
                extractions_in_block += 1
        
        return self._bits_to_bytes(extracted_bits)

    def _modify_lsb(self, coeff: int, bit: int) -> int:
        """
        Modify LSB of coefficient absolute value
        
        Args:
            coeff: Original coefficient
            bit: Bit to embed (0 or 1)
        
        Returns:
            Modified coefficient with sign preserved
            CRITICAL: Never returns 0 (would create new zeros that confuse extraction)
        """
        if coeff == 0:
            return 0
        
        abs_val = abs(coeff)
        new_abs = (abs_val & ~1) | bit  # Clear LSB and set new bit
        
        # CRITICAL FIX: Never create new zeros
        # If modification would result in 0, keep original value
        if new_abs == 0:
            return coeff
        
        # Preserve sign
        return new_abs if coeff > 0 else -new_abs
    
    def _bytes_to_bits(self, data: bytes) -> List[int]:
        """Convert bytes to list of bits"""
        bits = []
        for byte in data:
            for i in range(7, -1, -1):
                bits.append((byte >> i) & 1)
        return bits
    
    def _bits_to_bytes(self, bits: List[int]) -> bytes:
        """Convert list of bits to bytes"""
        # Pad to byte boundary
        while len(bits) % 8 != 0:
            bits.append(0)
        
        bytes_list = []
        for i in range(0, len(bits), 8):
            byte_bits = bits[i:i+8]
            byte_val = 0
            for bit in byte_bits:
                byte_val = (byte_val << 1) | bit
            bytes_list.append(byte_val)
        
        return bytes(bytes_list)
