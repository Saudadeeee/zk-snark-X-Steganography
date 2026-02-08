"""
CAVLC Safety Filter for Video Steganography
============================================

Implements 5 critical rules to prevent H.264 bitstream corruption during embedding:

Rule 1: Zero-Preservation
    - Never change 0 → non-zero
    - Never change non-zero → 0
    - Reason: Changes TotalCoeffs parameter, breaks decoder

Rule 2: Trailing Ones Preservation  
    - Never modify last 3 coefficients if they are ±1
    - Reason: These are encoded specially in coeff_token VLC

Rule 3: Bit-Length Invariance
    - Only modify coefficients where new value has same CAVLC encoding length
    - Reason: Avoids recalculating slice headers and byte alignment

Rule 4: Matrix Embedding (Optional)
    - Use Hamming coding to minimize modifications
    - Embed k bits into n coefficients by modifying at most 1
    
Rule 5: CAVLC Re-encoding
    - Always re-encode modified blocks with proper CAVLC

Reference: 
- ITU-T H.264 Section 9.2 (CAVLC specification)
- Westfeld (2001) - F5 Steganographic Algorithm
- Fridrich et al. (2007) - Matrix Embedding for Digital Steganography
"""

from typing import List, Tuple, Optional, Set, Dict
from dataclasses import dataclass
from functools import lru_cache
import numpy as np

from .encoding_length_checker import EncodingLengthChecker
from ..exceptions import SafetyFilterError


@dataclass
class CoefficientInfo:
    """Information about a coefficient for safety checking"""
    block_idx: Tuple[int, int]  # (mb_idx, block_idx)
    coeff_idx: int               # Position in zigzag (0-15)
    value: int                   # Coefficient value
    is_trailing_one: bool        # Part of trailing ±1 sequence
    is_dc: bool                  # DC coefficient (position 0)
    encoding_bits: int           # CAVLC encoding length


@dataclass
class SafetyCheckResult:
    """Result of safety filter check"""
    is_safe: bool
    reason: str
    original_value: int
    modified_value: int
    encoding_bits_original: int
    encoding_bits_modified: int


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
            self.length_checker = EncodingLengthChecker()
        else:
            self.length_checker = None
        
        # Cache for trailing ones detection (performance optimization)
        self._trailing_ones_cache: Dict[Tuple[int, ...], Set[int]] = {}
    
    def check_coefficient_safety(
        self,
        block_coeffs: List[int],
        coeff_idx: int,
        new_value: int,
        suffix_length: int = 1
    ) -> SafetyCheckResult:
        """
        Check if modifying a coefficient is safe according to all enabled rules
        
        Args:
            block_coeffs: All 16 coefficients in block (zigzag order)
            coeff_idx: Index of coefficient to modify (0-15)
            new_value: Proposed new value
            suffix_length: CAVLC suffix_length context (typically 1)
        
        Returns:
            SafetyCheckResult with detailed information
        """
        original_value = block_coeffs[coeff_idx]
        
        # RULE 1: Zero-Preservation
        if self.enable_zero_preservation:
            if original_value == 0 and new_value != 0:
                return SafetyCheckResult(
                    is_safe=False,
                    reason="Rule 1: Cannot change zero to non-zero (breaks TotalCoeffs)",
                    original_value=original_value,
                    modified_value=new_value,
                    encoding_bits_original=0,
                    encoding_bits_modified=0
                )
            
            if original_value != 0 and new_value == 0:
                return SafetyCheckResult(
                    is_safe=False,
                    reason="Rule 1: Cannot change non-zero to zero (breaks TotalCoeffs)",
                    original_value=original_value,
                    modified_value=new_value,
                    encoding_bits_original=0,
                    encoding_bits_modified=0
                )
        
        # RULE 2: Trailing Ones Preservation
        if self.enable_trailing_ones:
            trailing_positions = self._detect_trailing_ones(block_coeffs)
            if coeff_idx in trailing_positions:
                return SafetyCheckResult(
                    is_safe=False,
                    reason=f"Rule 2: Coefficient is trailing ±1 at position {coeff_idx} (CAVLC special encoding)",
                    original_value=original_value,
                    modified_value=new_value,
                    encoding_bits_original=1,
                    encoding_bits_modified=1
                )
        
        # RULE 3: Bit-Length Invariance
        if self.enable_bit_length and self.length_checker:
            is_patchable, orig_bits, new_bits = self.length_checker.check_lsb_flip_patchability(
                original_value, 
                suffix_length
            )
            
            if not is_patchable:
                return SafetyCheckResult(
                    is_safe=False,
                    reason=f"Rule 3: Encoding length changes ({orig_bits}→{new_bits} bits)",
                    original_value=original_value,
                    modified_value=new_value,
                    encoding_bits_original=orig_bits,
                    encoding_bits_modified=new_bits
                )
        
        # Additional heuristic: Magnitude threshold
        if abs(original_value) < self.min_safe_magnitude:
            return SafetyCheckResult(
                is_safe=False,
                reason=f"Heuristic: Magnitude |{original_value}| < {self.min_safe_magnitude} (unstable)",
                original_value=original_value,
                modified_value=new_value,
                encoding_bits_original=0,
                encoding_bits_modified=0
            )
        
        # PASSED ALL CHECKS
        return SafetyCheckResult(
            is_safe=True,
            reason="All safety checks passed",
            original_value=original_value,
            modified_value=new_value,
            encoding_bits_original=0,
            encoding_bits_modified=0
        )
    
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
        
        # Find first non-zero coefficient from the end
        last_nonzero_idx = -1
        for i in range(15, -1, -1):
            if coeffs[i] != 0:
                last_nonzero_idx = i
                break
        
        if last_nonzero_idx == -1:
            # All zeros
            return trailing_positions
        
        # Scan backward from last non-zero, looking for ±1
        # CAVLC encodes MAXIMUM 3 trailing ones
        count = 0
        for i in range(last_nonzero_idx, -1, -1):
            if coeffs[i] in [-1, 1] and count < 3:
                trailing_positions.add(i)
                count += 1
            else:
                # Hit a non-±1 coefficient, stop
                break
        
        return trailing_positions
    
    def get_safe_positions(
        self,
        coefficients: List[Tuple[int, int, List[int]]],
        skip_dc: bool = True
    ) -> List[Tuple[int, int, int]]:
        """
        Get list of safe embedding positions across all blocks
        
        Args:
            coefficients: List of (mb_idx, block_idx, coeffs) tuples
            skip_dc: Skip DC coefficient (position 0)
        
        Returns:
            List of (mb_idx, block_idx, coeff_idx) tuples that are safe to modify
        
        Raises:
            SafetyFilterError: If coefficient data is invalid
        """
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
            # Detect trailing ones for this block
            trailing_positions = self._detect_trailing_ones(coeffs)
            
            # Check each coefficient
            for coeff_idx in range(len(coeffs)):
                # Skip DC if requested
                if skip_dc and coeff_idx == 0:
                    continue
                
                # Skip zeros
                if coeffs[coeff_idx] == 0:
                    continue
                
                # Skip trailing ones
                if coeff_idx in trailing_positions:
                    continue
                
                # Skip small magnitudes
                if abs(coeffs[coeff_idx]) < self.min_safe_magnitude:
                    continue
                
                # Calculate LSB-flipped value
                original = coeffs[coeff_idx]
                sign = 1 if original > 0 else -1
                abs_val = abs(original)
                new_abs = (abs_val & ~1) | ((abs_val & 1) ^ 1)  # Flip LSB
                new_val = sign * new_abs
                
                # Ensure not creating zero
                if new_val == 0:
                    continue
                
                # Check bit-length invariance if enabled
                if self.enable_bit_length and self.length_checker:
                    is_patchable, _, _ = self.length_checker.check_lsb_flip_patchability(
                        original
                    )
                    if not is_patchable:
                        continue
                
                # SAFE!
                safe_positions.append((mb_idx, block_idx, coeff_idx))
        
        return safe_positions
    
    def filter_blocks_for_embedding(
        self,
        coefficients: List[Tuple[int, int, List[int]]],
        min_capacity_per_block: int = 1
    ) -> List[Tuple[int, int, List[int], List[int]]]:
        """
        Filter blocks and return only those with sufficient safe positions
        
        Args:
            coefficients: List of (mb_idx, block_idx, coeffs) tuples
            min_capacity_per_block: Minimum safe positions required per block
        
        Returns:
            List of (mb_idx, block_idx, coeffs, safe_indices) tuples
            where safe_indices are local indices within the block
        """
        filtered_blocks = []
        
        for mb_idx, block_idx, coeffs in coefficients:
            # Get safe positions for this block
            block_safe_positions = []
            trailing_positions = self._detect_trailing_ones(coeffs)
            
            for coeff_idx in range(1, len(coeffs)):  # Skip DC (idx 0)
                if coeffs[coeff_idx] == 0:
                    continue
                if coeff_idx in trailing_positions:
                    continue
                if abs(coeffs[coeff_idx]) < self.min_safe_magnitude:
                    continue
                
                # Check LSB flip
                original = coeffs[coeff_idx]
                sign = 1 if original > 0 else -1
                abs_val = abs(original)
                new_abs = (abs_val & ~1) | ((abs_val & 1) ^ 1)
                new_val = sign * new_abs
                
                if new_val == 0:
                    continue
                
                if self.enable_bit_length and self.length_checker:
                    is_patchable, _, _ = self.length_checker.check_lsb_flip_patchability(original)
                    if not is_patchable:
                        continue
                
                block_safe_positions.append(coeff_idx)
            
            # Only include block if it has enough safe positions
            if len(block_safe_positions) >= min_capacity_per_block:
                filtered_blocks.append((mb_idx, block_idx, coeffs, block_safe_positions))
        
        return filtered_blocks
    
    def get_statistics(
        self,
        coefficients: List[Tuple[int, int, List[int]]]
    ) -> dict:
        """
        Generate statistics about coefficient safety
        
        Returns:
            Dictionary with:
            - total_coeffs: Total non-zero coefficients
            - safe_coeffs: Coefficients passing all safety checks
            - rejected_by_rule: Breakdown by rejection reason
            - safety_rate: Percentage of safe coefficients
        """
        total_nonzero = 0
        safe_count = 0
        rejected_by_rule = {
            'zero_preservation': 0,
            'trailing_ones': 0,
            'bit_length': 0,
            'magnitude_threshold': 0
        }
        
        for mb_idx, block_idx, coeffs in coefficients:
            trailing_positions = self._detect_trailing_ones(coeffs)
            
            for coeff_idx, val in enumerate(coeffs):
                if val == 0:
                    continue
                
                total_nonzero += 1
                
                # Check each rule
                is_safe = True
                
                # Skip DC
                if coeff_idx == 0:
                    is_safe = False
                    rejected_by_rule['magnitude_threshold'] += 1
                    continue
                
                # Trailing ones
                if coeff_idx in trailing_positions:
                    is_safe = False
                    rejected_by_rule['trailing_ones'] += 1
                    continue
                
                # Magnitude
                if abs(val) < self.min_safe_magnitude:
                    is_safe = False
                    rejected_by_rule['magnitude_threshold'] += 1
                    continue
                
                # Bit-length
                if self.enable_bit_length and self.length_checker:
                    is_patchable, _, _ = self.length_checker.check_lsb_flip_patchability(val)
                    if not is_patchable:
                        is_safe = False
                        rejected_by_rule['bit_length'] += 1
                        continue
                
                if is_safe:
                    safe_count += 1
        
        safety_rate = (safe_count / total_nonzero * 100) if total_nonzero > 0 else 0
        
        return {
            'total_nonzero_coeffs': total_nonzero,
            'safe_coeffs': safe_count,
            'rejected_by_rule': rejected_by_rule,
            'safety_rate': safety_rate,
            'capacity_bits': safe_count  # 1 bit per safe coefficient
        }


def demo_safety_filter():
    """Demonstrate CAVLC Safety Filter usage"""
    print("=" * 80)
    print("CAVLC Safety Filter Demonstration")
    print("=" * 80)
    
    # Create sample coefficient blocks
    sample_blocks = [
        # Block 1: Mixed coefficients with trailing ones
        (0, 0, [12, -5, 3, 0, 0, 2, -1, 1, 0, 0, 0, 0, 0, 0, 1, 0]),
        
        # Block 2: No trailing ones
        (0, 1, [8, 4, -3, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
        
        # Block 3: All small values
        (0, 2, [2, 1, -1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]),
    ]
    
    # Initialize filter with all rules enabled
    filter = CAVLCSafetyFilter(
        enable_zero_preservation=True,
        enable_trailing_ones_protection=True,
        enable_bit_length_check=True,
        min_safe_magnitude=3
    )
    
    print("\nAnalyzing coefficient blocks...")
    print("-" * 80)
    
    for mb_idx, block_idx, coeffs in sample_blocks:
        print(f"\nBlock ({mb_idx}, {block_idx})")
        print(f"  Coefficients: {[c for c in coeffs if c != 0]}")
        
        # Detect trailing ones
        trailing = filter._detect_trailing_ones(coeffs)
        print(f"  Trailing ±1 positions: {sorted(trailing) if trailing else 'None'}")
        
        # Check each non-zero coefficient
        safe_positions = []
        for idx, val in enumerate(coeffs):
            if val == 0 or idx == 0:  # Skip zeros and DC
                continue
            
            # Calculate LSB-flipped value
            sign = 1 if val > 0 else -1
            abs_val = abs(val)
            new_abs = (abs_val & ~1) | ((abs_val & 1) ^ 1)
            new_val = sign * new_abs
            
            # Check safety
            result = filter.check_coefficient_safety(coeffs, idx, new_val)
            
            if result.is_safe:
                safe_positions.append(idx)
                print(f"  ✓ Position {idx:2d}: {val:3d} → {new_val:3d} SAFE")
            else:
                print(f"  ✗ Position {idx:2d}: {val:3d} → {new_val:3d} UNSAFE ({result.reason})")
        
        print(f"  → Safe positions: {len(safe_positions)}/{len([c for c in coeffs if c != 0])}")
    
    # Overall statistics
    print("\n" + "=" * 80)
    stats = filter.get_statistics(sample_blocks)
    print("Overall Statistics:")
    print(f"  Total non-zero coeffs: {stats['total_nonzero_coeffs']}")
    print(f"  Safe coeffs: {stats['safe_coeffs']}")
    print(f"  Safety rate: {stats['safety_rate']:.1f}%")
    print(f"  Embedding capacity: {stats['capacity_bits']} bits")
    print(f"\nRejection breakdown:")
    for rule, count in stats['rejected_by_rule'].items():
        if count > 0:
            print(f"    {rule}: {count}")
    print("=" * 80)


if __name__ == '__main__':
    demo_safety_filter()
