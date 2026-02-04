"""
Stable Coefficient Embedder for Option D

Uses pre-computed stable_map to embed payload ONLY in proven-stable coefficients.
"""

from typing import List, Dict, Tuple
import struct


class StableEmbedder:
    """
    Embed payload using stable coefficient map
    
    Unlike PayloadEmbedder which uses heuristics, this uses actual
    stability testing results from StableCoefficientMapper.
    """
    
    def __init__(self):
        """Initialize stable embedder"""
        pass
    
    def embed_payload_in_stable_coeffs(
        self,
        macroblocks: List[Dict],
        stable_map: List[Dict],
        payload: bytes
    ) -> Tuple[List[Tuple[int, int, List[int]]], Dict]:
        """
        Embed payload using ONLY stable coefficients
        
        Args:
            macroblocks: List of MB dicts with 'coefficients' (flat 384-array)
            stable_map: List of stable coefficient entries
                        [{'mb': int, 'block': int, 'coeff': int}, ...]
            payload: Binary payload to embed
        
        Returns:
            (modified_coefficients, stats)
            - modified_coefficients: List of (mb_idx, block_idx, coeffs)
            - stats: Dict with embedding statistics
        """
        # Convert payload to bits
        payload_bits = self._bytes_to_bits(payload)
        
        if len(stable_map) < len(payload_bits):
            raise ValueError(
                f"Insufficient capacity: need {len(payload_bits)} bits, "
                f"have {len(stable_map)} stable coefficients"
            )
        
        print(f"\n{'='*70}")
        print("STABLE COEFFICIENT EMBEDDING")
        print(f"{'='*70}")
        print(f"Payload: {len(payload)} bytes = {len(payload_bits)} bits")
        print(f"Stable coefficients available: {len(stable_map)}")
        print(f"Utilization: {len(payload_bits)}/{len(stable_map)} "
              f"({100*len(payload_bits)/len(stable_map):.1f}%)")
        
        # Build modification map
        modifications = {}  # {(mb_idx, block_idx): modified_coeffs}
        bits_embedded = 0
        
        for i, payload_bit in enumerate(payload_bits):
            if i >= len(stable_map):
                break
            
            entry = stable_map[i]
            mb_idx = entry['mb']
            block_idx = entry['block']
            coeff_idx = entry['coeff']
            
            # Get current coefficient value
            if mb_idx >= len(macroblocks):
                print(f"[WARNING] MB {mb_idx} out of range, skipping")
                continue
            
            mb = macroblocks[mb_idx]
            coefficients = mb.get('coefficients', [])
            global_idx = block_idx * 16 + coeff_idx
            
            if global_idx >= len(coefficients):
                print(f"[WARNING] Coeff index {global_idx} out of range, skipping")
                continue
            
            coeff_value = coefficients[global_idx]
            
            # Modify LSB to match payload bit
            new_value = self._modify_lsb(coeff_value, payload_bit)
            
            # Store modification per block
            key = (mb_idx, block_idx)
            if key not in modifications:
                # Initialize with original block coefficients
                block_start = block_idx * 16
                block_end = block_start + 16
                modifications[key] = coefficients[block_start:block_end].copy()
            
            # Apply modification
            modifications[key][coeff_idx] = new_value
            bits_embedded += 1
        
        # Convert to standard format
        modified_coefficients = []
        for (mb_idx, block_idx), block_coeffs in modifications.items():
            modified_coefficients.append((mb_idx, block_idx, block_coeffs))
        
        # Sort by MB index for consistency
        modified_coefficients.sort(key=lambda x: (x[0], x[1]))
        
        stats = {
            'payload_bytes': len(payload),
            'payload_bits': len(payload_bits),
            'stable_capacity': len(stable_map),
            'bits_embedded': bits_embedded,
            'blocks_modified': len(modifications),
            'utilization_pct': 100 * bits_embedded / len(stable_map)
        }
        
        print(f"\n[EMBEDDING COMPLETE]")
        print(f"  Bits embedded: {bits_embedded}")
        print(f"  Blocks modified: {len(modifications)}")
        print(f"  MBs affected: {len(set(mb for mb, _ in modifications.keys()))}")
        print(f"{'='*70}")
        
        return modified_coefficients, stats
    
    def extract_payload_from_stable_coeffs(
        self,
        macroblocks: List[Dict],
        stable_map: List[Dict],
        payload_length_bytes: int
    ) -> Tuple[bytes, Dict]:
        """
        Extract payload using stable coefficient map
        
        Args:
            macroblocks: List of MB dicts with 'coefficients' (flat 384-array)
            stable_map: List of stable coefficient entries
            payload_length_bytes: Expected payload size in bytes
        
        Returns:
            (extracted_payload, stats)
        """
        payload_bits_needed = payload_length_bytes * 8
        
        if len(stable_map) < payload_bits_needed:
            raise ValueError(
                f"Insufficient stable coefficients: need {payload_bits_needed}, "
                f"have {len(stable_map)}"
            )
        
        print(f"\n{'='*70}")
        print("STABLE COEFFICIENT EXTRACTION")
        print(f"{'='*70}")
        print(f"Expected payload: {payload_length_bytes} bytes = {payload_bits_needed} bits")
        print(f"Using stable map with {len(stable_map)} entries")
        
        # Extract LSBs
        extracted_bits = []
        
        for i in range(payload_bits_needed):
            entry = stable_map[i]
            mb_idx = entry['mb']
            block_idx = entry['block']
            coeff_idx = entry['coeff']
            
            if mb_idx >= len(macroblocks):
                print(f"[WARNING] MB {mb_idx} out of range")
                extracted_bits.append(0)
                continue
            
            mb = macroblocks[mb_idx]
            coefficients = mb.get('coefficients', [])
            global_idx = block_idx * 16 + coeff_idx
            
            if global_idx >= len(coefficients):
                print(f"[WARNING] Coeff index {global_idx} out of range")
                extracted_bits.append(0)
                continue
            
            coeff_value = coefficients[global_idx]
            lsb = abs(coeff_value) & 1
            extracted_bits.append(lsb)
        
        # Convert bits to bytes
        extracted_payload = self._bits_to_bytes(extracted_bits)
        
        stats = {
            'bits_extracted': len(extracted_bits),
            'bytes_extracted': len(extracted_payload),
            'stable_coeffs_used': payload_bits_needed
        }
        
        print(f"\n[EXTRACTION COMPLETE]")
        print(f"  Bits extracted: {len(extracted_bits)}")
        print(f"  Bytes extracted: {len(extracted_payload)}")
        print(f"{'='*70}")
        
        return extracted_payload, stats
    
    def _modify_lsb(self, coeff: int, bit: int) -> int:
        """
        Modify coefficient LSB to match target bit
        
        Args:
            coeff: Original coefficient value
            bit: Target bit (0 or 1)
        
        Returns:
            Modified coefficient
        """
        if coeff == 0:
            # Should not happen with stable coefficients
            return 1 if bit == 1 else 0
        
        sign = 1 if coeff > 0 else -1
        magnitude = abs(coeff)
        current_lsb = magnitude & 1
        
        if current_lsb == bit:
            return coeff
        
        # Flip LSB
        if bit == 1:
            new_magnitude = magnitude | 1
        else:
            new_magnitude = magnitude & ~1
        
        return sign * new_magnitude
    
    def _bytes_to_bits(self, data: bytes) -> List[int]:
        """Convert bytes to list of bits"""
        bits = []
        for byte in data:
            for i in range(8):
                bits.append((byte >> (7 - i)) & 1)
        return bits
    
    def _bits_to_bytes(self, bits: List[int]) -> bytes:
        """Convert list of bits to bytes"""
        result = bytearray()
        for i in range(0, len(bits), 8):
            byte_bits = bits[i:i+8]
            if len(byte_bits) < 8:
                byte_bits += [0] * (8 - len(byte_bits))
            
            byte_value = 0
            for bit in byte_bits:
                byte_value = (byte_value << 1) | bit
            result.append(byte_value)
        
        return bytes(result)
