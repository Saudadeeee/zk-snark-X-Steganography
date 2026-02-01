"""
Payload Embedder for ZK-SNARK Video Steganography

Embeds payloads into extracted DCT coefficients using LSB modification
"""

from typing import List, Tuple
import numpy as np


class PayloadEmbedder:
    """
    Embed binary payload into DCT coefficients using LSB substitution
    
    CAPACITY OPTIMIZATION:
    - Use coefficients with |value| >= 2 (stable after LSB flip)
    - Optionally include |value| == 1 with caution (may flip to 0)
    - Skip DC (position 0) for stability
    - Skip zeros (would become ±1, changing block structure)
    """
    
    def __init__(self, skip_dc: bool = True, skip_zeros: bool = True, 
                 allow_small_values: bool = False):
        """
        Initialize embedder
        
        Args:
            skip_dc: Skip DC coefficients (position 0 in zigzag)
            skip_zeros: Skip zero coefficients
            allow_small_values: Allow embedding in |coeff| == 1 (RISKY: may flip to 0)
                               Set to True for higher capacity (up to 2x), but less stable
        """
        self.skip_dc = skip_dc
        self.skip_zeros = skip_zeros
        self.allow_small_values = allow_small_values
    
    def embed_payload(self, coefficients: List[Tuple[int, int, List[int]]], 
                     payload: bytes) -> Tuple[List[Tuple[int, int, List[int]]], int]:
        """
        Embed payload into coefficient blocks
        
        Args:
            coefficients: List of (mb_idx, block_idx, coeffs) tuples
            payload: Binary payload to embed
        
        Returns:
            (modified_coefficients, bits_embedded)
        """
        # Convert payload to bits
        payload_bits = self._bytes_to_bits(payload)
        
        # Prepare modified coefficients
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
                       payload_length_bits: int) -> bytes:
        """
        Extract payload from coefficient blocks
        
        Args:
            coefficients: List of (mb_idx, block_idx, coeffs) tuples
            payload_length_bits: Number of bits to extract
        
        Returns:
            Extracted payload as bytes
        """
        extracted_bits = []
        
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
