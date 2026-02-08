"""
Payload Embedder for ZK-SNARK Video Steganography

Embeds payloads into extracted DCT coefficients using LSB modification
with comprehensive CAVLC safety checks to prevent bitstream corruption.
"""

from typing import List, Tuple, Optional
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
    4. Magnitude Threshold: Only |value| >= 2 (stable after LSB flip)
    5. CAVLC Re-encoding: Always re-encode modified blocks
    
    CAPACITY OPTIMIZATION:
    - Use coefficients with |value| >= 2 (stable after LSB flip)
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
                 enable_bit_length_check: bool = True):
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
        """
        self.skip_dc = skip_dc
        self.skip_zeros = skip_zeros
        self.allow_small_values = allow_small_values
        self.use_safety_filter = use_safety_filter
        
        # Initialize CAVLC Safety Filter if enabled
        if self.use_safety_filter:
            min_magnitude = 1 if allow_small_values else 2
            self.safety_filter = CAVLCSafetyFilter(
                enable_zero_preservation=True,
                enable_trailing_ones_protection=enable_trailing_ones_protection,
                enable_bit_length_check=enable_bit_length_check,
                min_safe_magnitude=min_magnitude
            )
        else:
            self.safety_filter = None
    
    def embed_payload(self, coefficients: List[Tuple[int, int, List[int]]], 
                     payload: bytes) -> Tuple[List[Tuple[int, int, List[int]]], int]:
        """
        Embed payload into coefficient blocks with CAVLC safety checks
        
        Args:
            coefficients: List of (mb_idx, block_idx, coeffs) tuples
            payload: Binary payload to embed
        
        Returns:
            (modified_coefficients, bits_embedded)
        """
        # Convert payload to bits
        payload_bits = self._bytes_to_bits(payload)
        
        # Use safety filter if enabled
        if self.use_safety_filter and self.safety_filter:
            return self._embed_with_safety_filter(coefficients, payload_bits)
        else:
            return self._embed_legacy(coefficients, payload_bits)
    
    def _embed_with_safety_filter(
        self, 
        coefficients: List[Tuple[int, int, List[int]]], 
        payload_bits: List[int]
    ) -> Tuple[List[Tuple[int, int, List[int]]], int]:
        """
        Embed using CAVLC Safety Filter (RECOMMENDED)
        
        This method enforces all 5 CAVLC safety rules to prevent corruption.
        """
        # Get all safe positions across all blocks
        safe_positions = self.safety_filter.get_safe_positions(
            coefficients, 
            skip_dc=self.skip_dc
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
            new_coeffs = coeffs[:]
            block_key = (mb_idx, block_idx)
            
            # Get safe positions for this block
            if block_key in safe_map:
                safe_indices = safe_map[block_key]
                
                for coeff_idx in safe_indices:
                    if bits_embedded >= len(payload_bits):
                        break
                    
                    payload_bit = payload_bits[bits_embedded]
                    
                    # Embed bit using LSB modification
                    new_coeffs[coeff_idx] = self._modify_lsb(
                        coeffs[coeff_idx], 
                        payload_bit
                    )
                    bits_embedded += 1
            
            modified.append((mb_idx, block_idx, new_coeffs))
            
            if bits_embedded >= len(payload_bits):
                # Finished embedding, copy remaining blocks as-is
                break
        
        # Copy any remaining blocks that weren't processed
        remaining_start = len(modified)
        for i in range(remaining_start, len(coefficients)):
            mb_idx, block_idx, coeffs = coefficients[i]
            modified.append((mb_idx, block_idx, coeffs[:]))
        
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
    
    def extract_payload(self, coefficients: List[Tuple[int, int, List[int]]],
                       payload_length_bits: int, start_bit_offset: int = 0) -> bytes:
        """
        Extract payload from coefficient blocks
        
        Args:
            coefficients: List of (mb_idx, block_idx, coeffs) tuples
            payload_length_bits: Number of bits to extract
            start_bit_offset: Skip this many bits before starting extraction
        
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
            return self._extract_with_safety_filter(coefficients, payload_length_bits, start_bit_offset)
        else:
            return self._extract_legacy(coefficients, payload_length_bits, start_bit_offset)
    
    def _extract_with_safety_filter(
        self, 
        coefficients: List[Tuple[int, int, List[int]]],
        payload_length_bits: int,
        start_bit_offset: int = 0
    ) -> bytes:
        """
        Extract using CAVLC Safety Filter (same positions as embedding)
        
        CRITICAL: Must use SAME safe positions as embedding to ensure sync!
        """
        # Get all safe positions (same calculation as embedding)
        safe_positions = self.safety_filter.get_safe_positions(
            coefficients, 
            skip_dc=self.skip_dc
        )
        
        # Build coefficient lookup map for fast access
        coeff_map = {}
        for mb_idx, block_idx, coeffs in coefficients:
            coeff_map[(mb_idx, block_idx)] = coeffs
        
        # Extract bits from safe positions only
        extracted_bits = []
        bits_skipped = 0
        
        for mb_idx, block_idx, coeff_idx in safe_positions:
            # Skip offset bits first
            if bits_skipped < start_bit_offset:
                bits_skipped += 1
                continue
            
            if len(extracted_bits) >= payload_length_bits:
                break
            
            # Get coefficient value from map
            key = (mb_idx, block_idx)
            if key in coeff_map:
                coeffs = coeff_map[key]
                coeff = coeffs[coeff_idx]
                # Extract LSB
                lsb = abs(coeff) & 1
                extracted_bits.append(lsb)
        
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
