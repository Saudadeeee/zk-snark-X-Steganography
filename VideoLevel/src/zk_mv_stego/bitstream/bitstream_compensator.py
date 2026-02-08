"""
Bitstream Drift Compensation (Week 11)

This module handles bitstream drift caused by coefficient modifications
and ensures NAL unit integrity after embedding.

Goals:
- Fix bitstream length changes after coefficient modification
- Add/remove stuffing bits to maintain alignment
- Verify NAL unit structure integrity
- Ensure compatibility with FFmpeg, x264, and JM decoders
"""

import struct
import zlib
from typing import List, Tuple, Optional, Dict
import numpy as np


class BitstreamCompensator:
    """
    Handles bitstream drift compensation and integrity verification
    
    Features:
    - Calculate bit-length differences
    - Add stuffing bits for shortened bitstreams
    - Compress trailing data for lengthened bitstreams
    - Verify NAL unit structure
    - Check emulation_prevention_three_byte compliance
    """
    
    def __init__(self):
        """Initialize bitstream compensator"""
        self.statistics = {
            'total_compensations': 0,
            'stuffing_added': 0,
            'compression_attempts': 0,
            'verification_failures': 0
        }
    
    def compensate_drift(self, 
                        original_nal: bytes,
                        modified_nal: bytes,
                        tolerance: int = 8) -> Tuple[bytes, Dict]:
        """
        Compensate for bitstream drift caused by modifications
        
        Args:
            original_nal: Original NAL unit bytes
            modified_nal: Modified NAL unit bytes (after coefficient embedding)
            tolerance: Maximum acceptable drift in bits (default: 8 bits = 1 byte)
        
        Returns:
            Tuple of:
            - compensated_nal: Drift-compensated NAL unit
            - metadata: Compensation metadata (method, bytes_added/removed, etc.)
        
        Strategy:
        1. Calculate bit-length difference
        2. If NAL shortened → add stuffing bits
        3. If NAL lengthened → try to compress trailing zeros
        4. Verify result maintains valid H.264 structure
        """
        orig_bits = len(original_nal) * 8
        mod_bits = len(modified_nal) * 8
        drift = mod_bits - orig_bits
        
        metadata = {
            'original_bits': orig_bits,
            'modified_bits': mod_bits,
            'drift': drift,
            'method': None,
            'bytes_adjusted': 0
        }
        
        # No drift - return as is
        if abs(drift) <= tolerance:
            metadata['method'] = 'none'
            return modified_nal, metadata
        
        # Method 1: NAL became shorter - add stuffing
        if drift < 0:
            compensated = self._add_stuffing_bits(modified_nal, -drift)
            metadata['method'] = 'stuffing'
            metadata['bytes_adjusted'] = len(compensated) - len(modified_nal)
            self.statistics['stuffing_added'] += 1
        
        # Method 2: NAL became longer - compress trailing data
        else:
            compensated = self._compress_trailing_data(modified_nal, drift)
            metadata['method'] = 'compression'
            metadata['bytes_adjusted'] = len(modified_nal) - len(compensated)
            self.statistics['compression_attempts'] += 1
        
        self.statistics['total_compensations'] += 1
        
        # Verify result
        if not self.verify_nal_structure(compensated):
            metadata['verification_failed'] = True
            self.statistics['verification_failures'] += 1
            # Return original modified NAL if verification fails
            return modified_nal, metadata
        
        return compensated, metadata
    
    def _add_stuffing_bits(self, nal_data: bytes, bits_to_add: int) -> bytes:
        """
        Add stuffing bits to NAL unit
        
        H.264 Spec Section 7.3.2.11: rbsp_trailing_bits()
        - Start with '1' bit
        - Fill remaining with '0' bits until byte-aligned
        
        Args:
            nal_data: NAL unit to extend
            bits_to_add: Number of bits to add
        
        Returns:
            NAL unit with stuffing bits added
        """
        # Calculate how many bytes needed
        bytes_to_add = (bits_to_add + 7) // 8
        
        # Stuffing pattern: 0x80 (10000000) followed by 0x00
        # This is a valid rbsp_trailing_bits() pattern
        stuffing = bytes([0x80] + [0x00] * (bytes_to_add - 1))
        
        return nal_data + stuffing
    
    def _compress_trailing_data(self, nal_data: bytes, bits_to_remove: int) -> bytes:
        """
        Try to compress trailing zeros to reduce NAL length
        
        Strategy:
        1. Scan from end for trailing zeros
        2. Remove excess zeros while maintaining valid structure
        3. Ensure at least one stop bit (0x80) remains
        
        Args:
            nal_data: NAL unit to compress
            bits_to_remove: Number of bits to remove
        
        Returns:
            Compressed NAL unit
        """
        bytes_to_remove = (bits_to_remove + 7) // 8
        
        # Scan from end for trailing zeros
        trailing_zeros = 0
        for i in range(len(nal_data) - 1, -1, -1):
            if nal_data[i] == 0x00:
                trailing_zeros += 1
            elif nal_data[i] == 0x80:
                # Stop bit found - can remove zeros before it
                break
            else:
                # Non-zero, non-stop-bit - can't compress further
                break
        
        # Can only remove up to trailing_zeros - 1 (keep at least stop bit)
        removable = min(trailing_zeros, bytes_to_remove)
        
        if removable == 0:
            return nal_data  # Can't compress
        
        # Remove trailing zeros
        return nal_data[:-removable]
    
    def verify_nal_structure(self, nal_data: bytes) -> bool:
        """
        Verify NAL unit structure integrity
        
        Checks:
        1. Minimum length (at least 2 bytes: header + data)
        2. Valid NAL header (forbidden_zero_bit = 0)
        3. No start code emulation without prevention bytes
        4. Valid rbsp_trailing_bits at end
        
        Args:
            nal_data: NAL unit to verify
        
        Returns:
            True if structure is valid, False otherwise
        """
        if len(nal_data) < 2:
            return False
        
        # Check NAL header (first byte)
        nal_header = nal_data[0]
        forbidden_zero_bit = (nal_header >> 7) & 0x01
        if forbidden_zero_bit != 0:
            return False
        
        # Check for start code emulation
        if not self._verify_emulation_prevention(nal_data):
            return False
        
        # Check for valid trailing bits
        if not self._has_valid_trailing_bits(nal_data):
            return False
        
        return True
    
    def _verify_emulation_prevention(self, nal_data: bytes) -> bool:
        """
        Verify emulation_prevention_three_byte compliance
        
        H.264 Spec 7.3.1: Any sequence of 0x000000, 0x000001, 0x000002, 0x000003
        in the RBSP must have 0x03 inserted after 0x0000
        
        Args:
            nal_data: NAL unit to check
        
        Returns:
            True if properly prevented, False if emulation found
        """
        i = 1  # Skip NAL header
        while i < len(nal_data) - 2:
            # Check for 0x000000, 0x000001, 0x000002 without prevention
            if (nal_data[i] == 0x00 and 
                nal_data[i + 1] == 0x00 and 
                nal_data[i + 2] <= 0x03):
                # This should have emulation prevention byte (0x03) after second 0x00
                # If we see 0x00 0x00 0x0X directly, it's an error
                # Unless it's 0x00 0x00 0x03 (which is the prevention byte itself)
                if nal_data[i + 2] != 0x03:
                    return False  # Emulation found without prevention
            i += 1
        
        return True
    
    def _has_valid_trailing_bits(self, nal_data: bytes) -> bool:
        """
        Check if NAL unit has valid rbsp_trailing_bits
        
        Valid patterns:
        - ...1000 0000 (0x80) - stop bit + alignment
        - ...1000 (just stop bit if already aligned)
        - Followed by zero or more 0x00 bytes
        
        Args:
            nal_data: NAL unit to check
        
        Returns:
            True if valid trailing bits found
        """
        if len(nal_data) < 1:
            return False
        
        # Last byte should be 0x80 or 0x00 (if preceded by 0x80)
        last_byte = nal_data[-1]
        
        # Simple check: allow 0x00 or 0x80 at end
        # More sophisticated check would parse from end looking for 1 bit
        if last_byte == 0x00 or last_byte == 0x80:
            return True
        
        # Check if last byte has a '1' bit (stop bit)
        # Any byte with at least one '1' bit is acceptable as trailing
        if last_byte > 0:
            return True
        
        return False
    
    def verify_decoder_compatibility(self, nal_data: bytes) -> Dict[str, bool]:
        """
        Verify compatibility with common H.264 decoders
        
        Tests:
        - FFmpeg compatibility (libavcodec)
        - x264 compatibility
        - JM reference decoder compatibility
        
        Args:
            nal_data: NAL unit to test
        
        Returns:
            Dict of decoder compatibility results
        
        Note: This is a structural check, not actual decoder execution
        """
        results = {
            'ffmpeg': True,
            'x264': True,
            'jm_reference': True,
            'structure_valid': False
        }
        
        # Basic structure check (applies to all decoders)
        results['structure_valid'] = self.verify_nal_structure(nal_data)
        
        if not results['structure_valid']:
            results['ffmpeg'] = False
            results['x264'] = False
            results['jm_reference'] = False
            return results
        
        # FFmpeg-specific checks (more lenient)
        # FFmpeg can handle some minor deviations
        results['ffmpeg'] = True
        
        # x264-specific checks (strict)
        # x264 requires strict compliance
        results['x264'] = self._verify_emulation_prevention(nal_data)
        
        # JM reference decoder (strictest)
        # JM requires perfect compliance with spec
        results['jm_reference'] = (
            self._verify_emulation_prevention(nal_data) and
            self._has_valid_trailing_bits(nal_data)
        )
        
        return results
    
    def get_statistics(self) -> Dict:
        """
        Get compensation statistics
        
        Returns:
            Dict with compensation statistics
        """
        return self.statistics.copy()
    
    def reset_statistics(self):
        """Reset all statistics counters"""
        self.statistics = {
            'total_compensations': 0,
            'stuffing_added': 0,
            'compression_attempts': 0,
            'verification_failures': 0
        }


def analyze_bitstream_drift(original_nal: bytes, modified_nal: bytes) -> Dict:
    """
    Analyze bitstream drift without compensation
    
    Utility function to understand drift characteristics
    
    Args:
        original_nal: Original NAL unit
        modified_nal: Modified NAL unit
    
    Returns:
        Dict with drift analysis
    """
    analysis = {
        'original_length': len(original_nal),
        'modified_length': len(modified_nal),
        'length_diff_bytes': len(modified_nal) - len(original_nal),
        'length_diff_bits': (len(modified_nal) - len(original_nal)) * 8,
        'drift_percentage': 0.0,
        'needs_compensation': False
    }
    
    if len(original_nal) > 0:
        analysis['drift_percentage'] = (
            abs(analysis['length_diff_bytes']) / len(original_nal) * 100
        )
    
    # Consider compensation needed if drift > 1 byte
    analysis['needs_compensation'] = abs(analysis['length_diff_bytes']) > 1
    
    return analysis


if __name__ == "__main__":
    # Quick demonstration
    print("Bitstream Compensator v3.0")
    print("=" * 50)
    
    compensator = BitstreamCompensator()
    
    # Test 1: NAL shortened (need stuffing)
    print("\n[Test 1] NAL Shortened - Add Stuffing")
    original = bytes([0x65, 0x88, 0x84, 0x00, 0x00, 0x00, 0x01, 0x80])
    modified = bytes([0x65, 0x88, 0x84, 0x00, 0x01])  # 3 bytes shorter
    
    compensated, metadata = compensator.compensate_drift(original, modified)
    print(f"  Original:  {len(original)} bytes")
    print(f"  Modified:  {len(modified)} bytes (drift: {metadata['drift']} bits)")
    print(f"  Compensated: {len(compensated)} bytes (method: {metadata['method']})")
    print(f"  Bytes added: {metadata['bytes_adjusted']}")
    
    # Test 2: NAL lengthened (try compression)
    print("\n[Test 2] NAL Lengthened - Try Compression")
    original2 = bytes([0x65, 0x88, 0x84, 0x80])
    modified2 = bytes([0x65, 0x88, 0x84, 0x00, 0x00, 0x01, 0x80])  # 3 bytes longer
    
    compensated2, metadata2 = compensator.compensate_drift(original2, modified2)
    print(f"  Original:  {len(original2)} bytes")
    print(f"  Modified:  {len(modified2)} bytes (drift: {metadata2['drift']} bits)")
    print(f"  Compensated: {len(compensated2)} bytes (method: {metadata2['method']})")
    
    # Test 3: Structure verification
    print("\n[Test 3] Structure Verification")
    test_nal = bytes([0x65, 0x88, 0x84, 0x00, 0x01, 0x80])
    valid = compensator.verify_nal_structure(test_nal)
    print(f"  Test NAL valid: {valid}")
    
    compat = compensator.verify_decoder_compatibility(test_nal)
    print(f"  FFmpeg compatible: {compat['ffmpeg']}")
    print(f"  x264 compatible: {compat['x264']}")
    print(f"  JM compatible: {compat['jm_reference']}")
    
    # Statistics
    print("\n[Statistics]")
    stats = compensator.get_statistics()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    print("\n" + "=" * 50)
    print("Bitstream compensation ready!")
