"""
Payload Embedder for ZK-SNARK Video Steganography

Embeds payloads into extracted DCT coefficients using LSB modification
with comprehensive CAVLC safety checks to prevent bitstream corruption.
"""

from typing import List, Tuple, Optional, Dict
import logging
import numpy as np

from .cavlc_safety_filter import CAVLCSafetyFilter
from ..exceptions import EmbeddingError, InsufficientCapacityError

logger = logging.getLogger(__name__)


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
            max_modifications_per_block: Maximum modifications per block (1-4, default: 3)
                                        1 = safest but lowest capacity
                                        3 = balanced (recommended)
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
                     t1_override_map: Optional[Dict[Tuple[int, int], int]] = None) -> Tuple[List[Tuple[int, int, List[int]]], int]:
        """
        Embed payload into coefficient blocks with CAVLC safety checks
        
        Args:
            coefficients: List of (mb_idx, block_idx, coeffs) tuples
            payload: Binary payload to embed
            nC_map: Mapping of block keys to nC values (Crucial for safety filter accuracy)
        
        Returns:
            (modified_coefficients, bits_embedded)
        """
        # Convert payload to bits
        payload_bits = self._bytes_to_bits(payload)
        
        # Use safety filter if enabled
        if self.use_safety_filter and self.safety_filter:
            return self._embed_with_safety_filter(coefficients, payload_bits, nC_map, nal_length_map, t1_override_map)
        else:
            return self._embed_legacy(coefficients, payload_bits)
    
    def _embed_with_safety_filter(
        self,
        coefficients: List[Tuple[int, int, List[int]]],
        payload_bits: List[int],
        nC_map: Optional[Dict[Tuple[int, int], int]] = None,
        nal_length_map: Optional[Dict[Tuple[int, int], int]] = None,
        t1_override_map: Optional[Dict[Tuple[int, int], int]] = None
    ) -> Tuple[List[Tuple[int, int, List[int]]], int]:
        """
        Embed using CAVLC Safety Filter (RECOMMENDED)

        This method enforces all 5 CAVLC safety rules to prevent corruption.
        """
        # Get all safe positions across all blocks
        safe_positions = self.safety_filter.get_safe_positions(
            coefficients,
            skip_dc=self.skip_dc,
            nC_map=nC_map,
            nal_length_map=nal_length_map,
            t1_override_map=t1_override_map
        )

        # Build a map for fast lookup: (mb_idx, block_idx) -> safe_coeff_indices
        safe_map = {}
        for mb_idx, block_idx, coeff_idx in safe_positions:
            key = (mb_idx, block_idx)
            if key not in safe_map:
                safe_map[key] = []
            safe_map[key].append(coeff_idx)
        
        # Embed payload
        modified = []
        bits_embedded = 0
        
        for mb_idx, block_idx, coeffs in coefficients:
            new_coeffs = coeffs[:]  # Shallow copy
            block_key = (mb_idx, block_idx)
            
            # Flag to track if this block was actually modified
            block_modified = False
            
            # Get safe positions for this block
            if block_key in safe_map:
                safe_indices = safe_map[block_key]
                
                # Modified approach: Allow multiple modifications per block (up to limit)
                # Safety Filter validates each individual flip independently
                # By limiting to max_modifications_per_block, we balance capacity vs safety
                modifications_in_block = 0
                
                for coeff_idx in safe_indices:
                    if bits_embedded >= len(payload_bits):
                        break
                    
                    if modifications_in_block >= self.max_modifications_per_block:
                        break  # Reached limit for this block
                    
                    payload_bit = payload_bits[bits_embedded]

                    if coeff_idx >= 0:
                        # Standard LSB modification
                        original_val = coeffs[coeff_idx]
                        new_coeffs[coeff_idx] = self._modify_lsb(
                            coeffs[coeff_idx],
                            payload_bit
                        )
                        modified_val = new_coeffs[coeff_idx]
                    else:
                        # Sign-bit modification for trailing ±1 coefficients.
                        # ~coeff_idx recovers the original zigzag index.
                        real_idx = ~coeff_idx
                        original_val = coeffs[real_idx]
                        abs_val = abs(coeffs[real_idx])
                        new_val = abs_val if payload_bit == 0 else -abs_val
                        new_coeffs[real_idx] = new_val
                        modified_val = new_val
                    
                    # Check if coefficient actually changed
                    if modified_val != original_val:
                        block_modified = True
                    
                    # CRITICAL FIX: Always increment modifications counter regardless
                    # of whether value changed, otherwise extractor cannot stay in sync!
                    modifications_in_block += 1
                    bits_embedded += 1

            # CRITICAL FIX: Only append block if it was ACTUALLY modified
            # Don't return original blocks - reconstructor will handle them
            if block_modified:
                modified.append((mb_idx, block_idx, new_coeffs))

            if bits_embedded >= len(payload_bits):
                # Finished embedding, stop processing
                break

        # DON'T copy remaining blocks - reconstructor will use original coefficients for them
        
        return modified, bits_embedded
    
    def _embed_legacy(
        self, 
        coefficients: List[Tuple[int, int, List[int]]], 
        payload_bits: List[int]
    ) -> Tuple[List[Tuple[int, int, List[int]]], int]:
        """
        Legacy embedding without safety filter (NOT RECOMMENDED)
        
        Kept for backward compatibility. Use _embed_with_safety_filter instead.
        """
        modified = []
        bits_embedded = 0
        
        for mb_idx, block_idx, coeffs in coefficients:
            if bits_embedded >= len(payload_bits):
                # No more payload to embed, keep original
                modified.append((mb_idx, block_idx, coeffs[:]))
                continue
            
            # Modify coefficients in this block
            new_coeffs = coeffs[:]
            
            for i, coeff in enumerate(coeffs):
                # Check embedding criteria
                if self.skip_dc and i == 0:
                    continue
                
                if self.skip_zeros and coeff == 0:
                    continue
                
                # CAPACITY OPTIMIZATION: Conditionally skip ±1
                # If allow_small_values=False (default): Skip ±1 for stability
                # If allow_small_values=True: Use ±1 for higher capacity (risky)
                if not self.allow_small_values and abs(coeff) == 1:
                    continue
                
                if bits_embedded >= len(payload_bits):
                    break
                
                payload_bit = payload_bits[bits_embedded]
                
                # Embed one bit into LSB
                new_coeffs[i] = self._modify_lsb(coeff, payload_bit)
                bits_embedded += 1
            
            modified.append((mb_idx, block_idx, new_coeffs))
        
        return modified, bits_embedded
    
    def extract_payload(
        self,
        coefficients: List[Tuple[int, int, List[int]]],
        payload_length_bits: int,
        start_bit_offset: int = 0,
        nC_map: Optional[Dict[Tuple[int, int], int]] = None,
        nal_length_map: Optional[Dict[Tuple[int, int], int]] = None,
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
            return self._extract_with_safety_filter(coefficients, payload_length_bits, start_bit_offset, nC_map, nal_length_map, precomputed_safe_positions)
        else:
            return self._extract_legacy(coefficients, payload_length_bits, start_bit_offset)
    
    def _extract_with_safety_filter(
        self,
        coefficients: List[Tuple[int, int, List[int]]],
        payload_length_bits: int,
        start_bit_offset: int = 0,
        nC_map: Optional[Dict[Tuple[int, int], int]] = None,
        nal_length_map: Optional[Dict[Tuple[int, int], int]] = None,
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
                nal_length_map=nal_length_map
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
        
        extracted_bits = []
        bits_skipped = 0
        
        for mb_idx, block_idx, coeffs in coefficients:
            block_key = (mb_idx, block_idx)
            if block_key not in safe_map:
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
    
    def _extract_legacy(
        self, 
        coefficients: List[Tuple[int, int, List[int]]],
        payload_length_bits: int,
        start_bit_offset: int = 0
    ) -> bytes:
        """
        Legacy extraction without safety filter
        """
        extracted_bits = []
        bits_skipped = 0
        
        for mb_idx, block_idx, coeffs in coefficients:
            if len(extracted_bits) >= payload_length_bits:
                break
            
            for i, coeff in enumerate(coeffs):
                # Check extraction criteria (same as embedding)
                if self.skip_dc and i == 0:
                    continue
                
                if self.skip_zeros and coeff == 0:
                    continue
                
                # Match embedding criteria
                if not self.allow_small_values and abs(coeff) == 1:
                    continue
                
                # Skip offset bits first
                if bits_skipped < start_bit_offset:
                    bits_skipped += 1
                    continue
                
                if len(extracted_bits) >= payload_length_bits:
                    break
                
                # Extract LSB of absolute value
                lsb = abs(coeff) & 1
                extracted_bits.append(lsb)
        
        # Convert bits to bytes
        return self._bits_to_bytes(extracted_bits)
    
    def calculate_capacity(self, coefficients: List[Tuple[int, int, List[int]]]) -> int:
        """
        Calculate embedding capacity in bits
        
        Args:
            coefficients: List of (mb_idx, block_idx, coeffs) tuples
        
        Returns:
            Capacity in bits
        """
        capacity = 0
        
        for mb_idx, block_idx, coeffs in coefficients:
            for i, coeff in enumerate(coeffs):
                if self.skip_dc and i == 0:
                    continue
                
                if self.skip_zeros and coeff == 0:
                    continue
                
                # Match embedding criteria
                if not self.allow_small_values and abs(coeff) == 1:
                    continue
                
                capacity += 1
        
        return capacity
    
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
    
    def calculate_distortion(self, original: List[int], modified: List[int]) -> dict:
        """
        Calculate distortion metrics
        
        Args:
            original: Original coefficients
            modified: Modified coefficients
        
        Returns:
            Dictionary with distortion metrics
        """
        if len(original) != len(modified):
            raise ValueError("Coefficient arrays must have same length")
        
        differences = [abs(m - o) for o, m in zip(original, modified)]
        
        return {
            'max_diff': max(differences) if differences else 0,
            'avg_diff': np.mean(differences) if differences else 0,
            'num_changed': sum(1 for d in differences if d > 0),
            'total_coeffs': len(original)
        }
