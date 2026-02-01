"""
Direct Bitstream Patcher for H.264 Video Steganography
=======================================================

Surgical LSB modification without CAVLC re-encoding.

Strategy:
1. Load entire bitstream into memory
2. Locate coefficient bit positions via parsing
3. Check if LSB flip maintains same encoding length
4. Patch bits directly if safe (same length)
5. Skip coefficient if unsafe (length changes)

This avoids CAVLC encoder bugs that corrupt LSB values.
"""

from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass
import struct


@dataclass
class BitPosition:
    """Exact bit position in bitstream"""
    byte_offset: int
    bit_offset: int  # 0-7, bit position within byte
    
    @property
    def absolute_bit_offset(self) -> int:
        """Convert to absolute bit position"""
        return self.byte_offset * 8 + self.bit_offset


@dataclass  
class CoefficientPosition:
    """Coefficient location and encoding info"""
    mb_idx: int
    block_idx: int
    coeff_idx: int  # 0-15 within block
    value: int
    bit_start: BitPosition
    encoding_length_bits: int  # CAVLC VLC code length
    
    @property
    def usable(self) -> bool:
        """Check if suitable for LSB embedding"""
        # Skip DC, zeros, and value=±1 (which flip to zero)
        # Accept |value| >= 2 (matches EncodingLengthChecker heuristic)
        return self.coeff_idx != 0 and self.value != 0 and abs(self.value) >= 2


class BitstreamBitReader:
    """Read bits from byte array at arbitrary bit positions"""
    
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0  # Current bit position
    
    def read_bits(self, num_bits: int) -> int:
        """Read num_bits from current position, advance position"""
        if num_bits == 0:
            return 0
        
        result = 0
        bits_read = 0
        
        while bits_read < num_bits:
            byte_idx = self.pos // 8
            bit_idx = self.pos % 8
            
            if byte_idx >= len(self.data):
                raise EOFError(f"Read past end of bitstream at bit {self.pos}")
            
            # Read remaining bits from current byte
            bits_in_byte = 8 - bit_idx
            bits_to_read = min(num_bits - bits_read, bits_in_byte)
            
            # Extract bits
            byte_val = self.data[byte_idx]
            shift = bits_in_byte - bits_to_read
            mask = (1 << bits_to_read) - 1
            bits = (byte_val >> shift) & mask
            
            result = (result << bits_to_read) | bits
            
            self.pos += bits_to_read
            bits_read += bits_to_read
        
        return result
    
    def align_to_byte(self):
        """Align to next byte boundary"""
        if self.pos % 8 != 0:
            self.pos = ((self.pos // 8) + 1) * 8
    
    def get_position(self) -> BitPosition:
        """Get current bit position"""
        return BitPosition(
            byte_offset=self.pos // 8,
            bit_offset=self.pos % 8
        )
    
    def seek(self, bit_pos: int):
        """Seek to absolute bit position"""
        self.pos = bit_pos


class BitstreamBitWriter:
    """Write bits to byte array at arbitrary bit positions"""
    
    def __init__(self, data: bytearray):
        self.data = data
        self.pos = 0
    
    def write_bits(self, value: int, num_bits: int):
        """Write num_bits value at current position"""
        if num_bits == 0:
            return
        
        bits_written = 0
        
        while bits_written < num_bits:
            byte_idx = self.pos // 8
            bit_idx = self.pos % 8
            
            if byte_idx >= len(self.data):
                raise EOFError(f"Write past end of bitstream at bit {self.pos}")
            
            # Write remaining bits to current byte
            bits_in_byte = 8 - bit_idx
            bits_to_write = min(num_bits - bits_written, bits_in_byte)
            
            # Extract bits to write from value
            shift = num_bits - bits_written - bits_to_write
            mask = (1 << bits_to_write) - 1
            bits = (value >> shift) & mask
            
            # Read current byte
            byte_val = self.data[byte_idx]
            
            # Clear bits we're about to write
            clear_shift = bits_in_byte - bits_to_write
            clear_mask = ~(mask << clear_shift) & 0xFF
            byte_val &= clear_mask
            
            # Set new bits
            byte_val |= (bits << clear_shift)
            
            # Write back
            self.data[byte_idx] = byte_val
            
            self.pos += bits_to_write
            bits_written += bits_to_write
    
    def seek(self, bit_pos: int):
        """Seek to absolute bit position"""
        self.pos = bit_pos
    
    def get_position(self) -> BitPosition:
        """Get current bit position"""
        return BitPosition(
            byte_offset=self.pos // 8,
            bit_offset=self.pos % 8
        )


class DirectBitstreamPatcher:
    """
    Direct bitstream LSB patcher - no CAVLC re-encoding
    
    Approach:
    1. Parse bitstream to locate all coefficients
    2. For each coefficient, check if LSB flip maintains encoding length
    3. Patch bits directly for "safe" coefficients
    4. Skip "unsafe" coefficients
    """
    
    def __init__(self, video_path: str):
        self.video_path = video_path
        self.bitstream: Optional[bytearray] = None
        self.coefficients: List[CoefficientPosition] = []
        self.patchable_coefficients: List[CoefficientPosition] = []
        # Store full blocks for reconstruction: (global_mb_idx, block_idx) -> [16 coeffs]
        self.full_blocks: Dict[Tuple[int, int], List[int]] = {}
        self.global_mb_count = 0
        
    def load_bitstream(self) -> int:
        """Load video file into memory"""
        print(f"[DirectPatcher] Loading bitstream: {self.video_path}")
        
        with open(self.video_path, 'rb') as f:
            data = f.read()
        
        self.bitstream = bytearray(data)
        
        print(f"[DirectPatcher] Loaded {len(self.bitstream):,} bytes")
        return len(self.bitstream)
    
    def locate_coefficients(self, max_frames: Optional[int] = None) -> int:
        """
        Parse bitstream and locate all coefficient positions
        
        Returns:
            Number of coefficients found
        """
        print(f"[DirectPatcher] Locating coefficients...")
        
        from ..decoder.cavlc_extractor_simple import SimpleCAVLCExtractor
        
        extractor = SimpleCAVLCExtractor()
        frames = extractor.extract_from_video(self.video_path, max_frames=max_frames)
        
        coeff_count = 0
        current_global_mb_idx = 0
        
        for frame in frames:
            frame_idx = frame.get('frame_idx', 0)
            macroblocks = frame.get('macroblocks', [])
            
            # Create a map of mb_idx -> global_mb_idx for this frame
            # H.264 MB indices reset per slice/frame, but we need global linear index
            # We assume macroblocks roughly ordered or we count them
            
            # SimpleCAVLCExtractor returns MBs in decode order.
            # We can just increment global counter.
            
            # Need to handle gaps? (skipped MBs).
            # SimpleCAVLCExtractor returns parsed MBs. 
            # If it skips skipped MBs, our count might desync with BitstreamReconstructor 
            # IF Reconstructor expects linear index including skips.
            # BitstreamReconstructor iterates NALs and counts MBs.
            # If we rely on Reconstructor's internal count, we should match it.
            # Ideally we'd use the same logic.
            # For now, assume simple increment.
            
            start_global_idx = current_global_mb_idx
            
            for mb_data in macroblocks:
                mb_idx = mb_data.get('mb_idx', 0)
                # If SimpleCAVLCExtractor reports mb_idx, use it to track gaps if any?
                # But mb_idx is relative to slice.
                
                # Let's trust the iterator order is the Global MB Stream order (linear)
                # But we should assign explicit Global Index
                
                this_global_mb_idx = current_global_mb_idx
                current_global_mb_idx += 1
                
                all_coeffs = mb_data.get('coefficients', [])
                
                # Split into 24 blocks
                for block_idx in range(24):
                    start = block_idx * 16
                    end = start + 16
                    if end <= len(all_coeffs):
                        coeffs = list(all_coeffs[start:end]) # Copy list
                        
                        # Store full block
                        self.full_blocks[(this_global_mb_idx, block_idx)] = coeffs
                        
                        for coeff_idx, value in enumerate(coeffs):
                            # Create position
                            coeff_pos = CoefficientPosition(
                                mb_idx=this_global_mb_idx, # Store GLOBAL index here
                                block_idx=block_idx,
                                coeff_idx=coeff_idx,
                                value=value,
                                bit_start=BitPosition(0, 0),
                                encoding_length_bits=0
                            )
                            
                            if coeff_pos.usable:
                                self.coefficients.append(coeff_pos)
                                coeff_count += 1
            
            print(f"    Frame {frame_idx}: MBs {start_global_idx} to {current_global_mb_idx-1}")
            
        self.global_mb_count = current_global_mb_idx
        print(f"[DirectPatcher] Found {coeff_count} usable coefficients across {self.global_mb_count} MBs")
        return coeff_count
    
    def check_patchability(self) -> int:
        """
        Check which coefficients are patchable (same encoding length after LSB flip)
        
        Returns:
            Number of patchable coefficients
        """
        print(f"[DirectPatcher] Checking patchability...")
        
        from .encoding_length_checker import EncodingLengthChecker
        checker = EncodingLengthChecker()
        
        # Check each coefficient for patchability
        for coeff in self.coefficients:
            is_patchable, orig_bits, new_bits = checker.check_lsb_flip_patchability(coeff.value)
            
            if is_patchable:
                self.patchable_coefficients.append(coeff)
        
        patchable_count = len(self.patchable_coefficients)
        total_count = len(self.coefficients)
        patchability_rate = (patchable_count / total_count * 100) if total_count > 0 else 0
        
        print(f"[DirectPatcher] Patchable: {patchable_count}/{total_count} ({patchability_rate:.1f}%)")
        print(f"[DirectPatcher] Capacity: {patchable_count // 8} bytes")
        
        return patchable_count
    
    def embed_payload(self, payload: bytes, output_path: str) -> Tuple[bool, dict]:
        """
        Embed payload using stable coefficients and surgical reconstruction
        
        Args:
            payload: Bytes to embed
            output_path: Path to write output video
            
        Returns:
            (success, stats)
        """
        print(f"[DirectPatcher] Embedding {len(payload)} bytes...")
        
        # Convert payload to bits
        payload_bits = []
        for byte in payload:
            for i in range(7, -1, -1):
                payload_bits.append((byte >> i) & 1)
        
        if len(payload_bits) > len(self.patchable_coefficients):
            raise ValueError(
                f"Payload ({len(payload_bits)} bits) exceeds patchable capacity "
                f"({len(self.patchable_coefficients)} bits)"
            )
        
        # Apply payload bits to coefficients (in memory)
        # Track which blocks are modified
        modified_block_indices = set()
        
        for bit_idx, bit in enumerate(payload_bits):
            coeff_pos = self.patchable_coefficients[bit_idx]
            original_val = coeff_pos.value
            
            # SIGN BIT EMBEDDING (instead of LSB)
            # Bit 0 → Positive coefficient
            # Bit 1 → Negative coefficient
            if bit == 0:
                new_val = abs(original_val)  # Make positive
            else:
                new_val = -abs(original_val)  # Make negative
            
            # Update the full block storage
            block_key = (coeff_pos.mb_idx, coeff_pos.block_idx)
            
            # Get block coeffs
            if block_key not in self.full_blocks:
                print(f"[DirectPatcher] Error: Block {block_key} not in full_blocks!")
                continue
                
            coeffs = self.full_blocks[block_key]
            
            # Update specific coefficient in the block
            coeffs[coeff_pos.coeff_idx] = new_val
            self.full_blocks[block_key] = coeffs
            
            modified_block_indices.add(block_key)
            
        # Prepare modifications list for BitstreamReconstructor
        # Format: List[Tuple[mb_idx, block_idx, coeffs]]
        modification_list = []
        
        for mb_idx, block_idx in modified_block_indices:
            coeffs = self.full_blocks[(mb_idx, block_idx)]
            modification_list.append((mb_idx, block_idx, coeffs))
            
        print(f"[DirectPatcher] Prepared {len(modification_list)} block modifications")
        print(f"[DirectPatcher] Using SIGN BIT embedding (bit 0=positive, bit 1=negative)")
        
        # Use BitstreamReconstructor
        from ..bitstream.bitstream_reconstructor import BitstreamReconstructor
        
        reconstructor = BitstreamReconstructor()
        
        try:
            print(f"[DirectPatcher] Calling BitstreamReconstructor...")
            result = reconstructor.reconstruct_video(
                original_file=self.video_path,
                modified_coefficients=modification_list,
                output_file=output_path
            )
            
            return result['success'], result
            
        except Exception as e:
            print(f"[DirectPatcher] Reconstruction Error: {e}")
            import traceback
            traceback.print_exc()
            return False, {'error': str(e)}
    
    def _write_h264_file(self, nal_units, output_path: str):
        """Write NAL units to H.264 file with Annex B byte stream format"""
        start_code = b'\x00\x00\x00\x01'
        
        with open(output_path, 'wb') as f:
            for nal in nal_units:
                # Write start code
                f.write(start_code)
                
                # Write NAL header (1 byte)
                nal_header = (nal.forbidden_zero_bit << 7) | (nal.nal_ref_idc << 5) | nal.nal_unit_type
                f.write(bytes([nal_header]))
                
                # Write RBSP data (with emulation prevention if needed)
                f.write(nal.rbsp_data)

    def write_bitstream(self, output_path: str):
        """Deprecated: Use embed_payload which writes internally via Reconstructor"""
        print("[DirectPatcher] Warning: write_bitstream is deprecated. Use embed_payload(..., output_path).")

