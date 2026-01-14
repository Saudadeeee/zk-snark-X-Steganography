"""
DCT-based Steganography for H.264 Video
========================================

Embeds data into DCT coefficients of video frames using LSB modification.
Target PSNR: ≥45dB for visually lossless quality.
"""

import numpy as np
from typing import List, Tuple, Dict, Optional
import cv2
from scipy.fftpack import dct, idct

from .payload_encoder import PayloadEncoder, PayloadDecoder, bytes_to_bits, bits_to_bytes, EmbeddingConfig


class DCTEmbedder:
    """Embed payload into DCT coefficients"""
    
    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self.stats = {}
    
    def embed(self, 
              frames: List[np.ndarray],
              payload: bytes,
              chaos_seed: int) -> Tuple[List[np.ndarray], Dict]:
        """
        Embed payload into video frames using DCT steganography
        
        Args:
            frames: List of video frames (RGB/YUV)
            payload: Raw payload bytes
            chaos_seed: Seed for carrier selection
            
        Returns:
            (modified_frames, embedding_info) tuple
        """
        print(f"\n{'='*60}")
        print("DCT EMBEDDING")
        print(f"{'='*60}")
        
        # 1. Encode payload
        encoder = PayloadEncoder(self.config)
        encoded_payload = encoder.encode(payload, chaos_seed)
        payload_bits = bytes_to_bits(encoded_payload)
        
        print(f"[1] Payload encoding:")
        print(f"    Original: {len(payload)} bytes")
        print(f"    Encoded:  {len(encoded_payload)} bytes (+{len(encoded_payload)-len(payload)} bytes overhead)")
        print(f"    Bits:     {len(payload_bits)} bits")
        
        # 2. Extract DCT coefficients from all frames
        all_coeffs = []
        frame_info = []
        
        print(f"[2] Extracting DCT coefficients from {len(frames)} frames...")
        
        for frame_idx, frame in enumerate(frames):
            # Convert to YCbCr (work on Y channel for maximum capacity)
            if len(frame.shape) == 3:
                ycbcr = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
                y_channel = ycbcr[:, :, 0]
            else:
                y_channel = frame
            
            # Extract DCT coefficients from 8x8 blocks
            h, w = y_channel.shape
            coeffs = self._extract_dct_blocks(y_channel)
            
            all_coeffs.extend(coeffs)
            frame_info.append({
                'frame_idx': frame_idx,
                'num_blocks': len(coeffs),
                'shape': (h, w)
            })
        
        print(f"    Total DCT blocks: {len(all_coeffs):,}")
        
        # 3. Select carrier coefficients
        carriers = self._select_carriers(all_coeffs, len(payload_bits), chaos_seed)
        
        print(f"[3] Carrier selection:")
        print(f"    Required bits: {len(payload_bits):,}")
        print(f"    Selected carriers: {len(carriers):,}")
        print(f"    Embedding rate: {100*len(carriers)/len(all_coeffs):.2f}%")
        
        # 4. Modify DCT coefficients
        modifications = []
        modified_coeffs = all_coeffs.copy()
        
        for bit_idx, carrier_info in enumerate(carriers):
            block_idx = carrier_info['block_idx']
            coeff_idx = carrier_info['coeff_idx']
            target_bit = payload_bits[bit_idx]
            
            # Get current coefficient
            block = modified_coeffs[block_idx]
            current_val = block[coeff_idx]
            
            # Modify LSB
            modified_val = self._modify_lsb(current_val, target_bit)
            delta = abs(modified_val - current_val)
            
            # Update coefficient
            modified_coeffs[block_idx][coeff_idx] = modified_val
            modifications.append(delta)
        
        avg_mod = np.mean(modifications) if modifications else 0.0
        
        print(f"[4] Embedding results:")
        print(f"    Coefficients modified: {len(modifications):,}")
        print(f"    Avg modification: {avg_mod:.2f}")
        print(f"    Max modification: {max(modifications) if modifications else 0}")
        
        # 5. Reconstruct frames with modified DCT
        modified_frames = []
        coeff_idx = 0
        
        print(f"[5] Reconstructing frames...")
        
        for idx, info in enumerate(frame_info):
            num_blocks = info['num_blocks']
            h, w = info['shape']
            
            # Get blocks for this frame
            frame_coeffs = modified_coeffs[coeff_idx:coeff_idx + num_blocks]
            coeff_idx += num_blocks
            
            # Reconstruct Y channel
            y_reconstructed = self._reconstruct_from_dct(frame_coeffs, (h, w))
            
            # Reconstruct full frame
            if len(frames[idx].shape) == 3:
                ycbcr = cv2.cvtColor(frames[idx], cv2.COLOR_BGR2YCrCb)
                ycbcr[:, :, 0] = y_reconstructed
                frame_reconstructed = cv2.cvtColor(ycbcr, cv2.COLOR_YCrCb2BGR)
            else:
                frame_reconstructed = y_reconstructed
            
            modified_frames.append(frame_reconstructed)
        
        # 6. Create embedding info
        embedding_info = {
            'payload_size': len(payload),
            'encoded_size': len(encoded_payload),
            'bits_embedded': len(payload_bits),
            'carriers_used': len(carriers),
            'carrier_indices': [(c['block_idx'], c['coeff_idx']) for c in carriers],
            'chaos_seed': chaos_seed,
            'avg_modification': float(avg_mod),
            'total_blocks': len(all_coeffs),
            'frame_count': len(frames),
            'config': {
                'method': 'dct_lsb',
                'component': 'Y_channel',
                'min_coeff_value': self.config.min_magnitude,
                'ecc_enabled': self.config.ecc_enabled
            }
        }
        
        self.stats = embedding_info
        
        print(f"\n{'='*60}")
        print(f"DCT EMBEDDING COMPLETE")
        print(f"{'='*60}\n")
        
        return modified_frames, embedding_info
    
    def _extract_dct_blocks(self, channel: np.ndarray) -> List[np.ndarray]:
        """Extract 8x8 DCT blocks from image channel"""
        h, w = channel.shape
        blocks = []
        
        # Process 8x8 blocks
        for i in range(0, h - 7, 8):
            for j in range(0, w - 7, 8):
                block = channel[i:i+8, j:j+8].astype(np.float64)
                
                # Apply 2D DCT
                dct_block = dct(dct(block.T, norm='ortho').T, norm='ortho')
                blocks.append(dct_block.flatten())
        
        return blocks
    
    def _select_carriers(self, blocks: List[np.ndarray], 
                        required_bits: int, chaos_seed: int) -> List[Dict]:
        """Select DCT coefficients as carriers using chaos-based selection"""
        # Initialize chaos sequence
        np.random.seed(chaos_seed)
        x = np.random.random()
        r = 3.9  # Chaos parameter
        
        def logistic_map(x_val: float, r_val: float) -> float:
            """Logistic map for chaos generation"""
            return r_val * x_val * (1 - x_val)
        
        carriers = []
        visited = set()
        
        # Skip DC coefficient (index 0) and use mid-frequency coefficients (1-32)
        eligible_indices = list(range(8, 40))  # Mid-frequency range
        
        while len(carriers) < required_bits:
            # Generate chaos value
            x = logistic_map(x, r)
            
            # Select block
            block_idx = int(x * len(blocks)) % len(blocks)
            
            # Select coefficient
            x = logistic_map(x, r)
            coeff_idx = eligible_indices[int(x * len(eligible_indices)) % len(eligible_indices)]
            
            # Check if already used
            key = (block_idx, coeff_idx)
            if key in visited:
                continue
            
            # Check coefficient magnitude (avoid very small values)
            coeff_val = abs(blocks[block_idx][coeff_idx])
            if coeff_val < self.config.min_magnitude:
                continue
            
            visited.add(key)
            carriers.append({
                'block_idx': block_idx,
                'coeff_idx': coeff_idx,
                'original_value': blocks[block_idx][coeff_idx]
            })
        
        return carriers
    
    def _modify_lsb(self, value: float, target_bit: int) -> float:
        """Modify DCT coefficient to embed bit using LSB"""
        # Quantize to integer for LSB manipulation
        int_val = int(round(value))
        
        current_lsb = int_val & 1
        
        if current_lsb == target_bit:
            return value  # Already correct
        
        # Flip LSB
        if int_val >= 0:
            modified = int_val + 1 if current_lsb == 0 else int_val - 1
        else:
            modified = int_val - 1 if current_lsb == 0 else int_val + 1
        
        return float(modified)
    
    def _reconstruct_from_dct(self, blocks: List[np.ndarray], 
                             shape: Tuple[int, int]) -> np.ndarray:
        """Reconstruct image channel from DCT blocks"""
        h, w = shape
        reconstructed = np.zeros((h, w), dtype=np.float64)
        
        block_idx = 0
        for i in range(0, h - 7, 8):
            for j in range(0, w - 7, 8):
                if block_idx >= len(blocks):
                    break
                
                # Reshape and apply inverse DCT
                dct_block = blocks[block_idx].reshape(8, 8)
                block = idct(idct(dct_block.T, norm='ortho').T, norm='ortho')
                
                # Clip to valid range
                block = np.clip(block, 0, 255)
                
                reconstructed[i:i+8, j:j+8] = block
                block_idx += 1
        
        return reconstructed.astype(np.uint8)


class DCTExtractor:
    """Extract payload from DCT coefficients"""
    
    def __init__(self):
        self.stats = {}
    
    def extract(self,
                frames: List[np.ndarray],
                carrier_indices: List[Tuple[int, int]],
                chaos_seed: int = None,
                expected_bits: int = None) -> Tuple[bytes, bool]:
        """
        Extract payload from video frames
        
        Args:
            frames: List of video frames
            carrier_indices: List of (block_idx, coeff_idx) tuples
            chaos_seed: For deterministic extraction
            expected_bits: Number of bits to extract
            
        Returns:
            (payload, valid) tuple
        """
        print(f"\n{'='*60}")
        print("DCT EXTRACTION")
        print(f"{'='*60}")
        
        # 1. Extract DCT coefficients
        print(f"[1] Extracting DCT coefficients...")
        
        all_coeffs = []
        for frame in frames:
            if len(frame.shape) == 3:
                ycbcr = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
                y_channel = ycbcr[:, :, 0]
            else:
                y_channel = frame
            
            h, w = y_channel.shape
            blocks = self._extract_dct_blocks(y_channel)
            all_coeffs.extend(blocks)
        
        print(f"    Total DCT blocks: {len(all_coeffs):,}")
        
        # 2. Extract bits from carriers
        print(f"[2] Extracting bits from {len(carrier_indices)} carriers...")
        
        extracted_bits = []
        for block_idx, coeff_idx in carrier_indices:
            if block_idx >= len(all_coeffs):
                break
            
            coeff_val = all_coeffs[block_idx][coeff_idx]
            int_val = int(round(coeff_val))
            bit = int_val & 1
            extracted_bits.append(bit)
        
        print(f"    Bits extracted: {len(extracted_bits)}")
        
        # 3. Convert to bytes
        extracted_bytes = bits_to_bytes(extracted_bits)
        
        print(f"[3] Byte conversion:")
        print(f"    Bytes: {len(extracted_bytes)}")
        
        # 4. Decode payload
        decoder = PayloadDecoder()
        payload, valid = decoder.decode(extracted_bytes)
        
        if valid:
            print(f"[4] Payload decoded successfully!")
            print(f"    Payload size: {len(payload)} bytes")
        else:
            print(f"[4] Payload decode FAILED")
        
        return payload, valid
    
    def _extract_dct_blocks(self, channel: np.ndarray) -> List[np.ndarray]:
        """Extract 8x8 DCT blocks (same as embedder)"""
        h, w = channel.shape
        blocks = []
        
        for i in range(0, h - 7, 8):
            for j in range(0, w - 7, 8):
                block = channel[i:i+8, j:j+8].astype(np.float64)
                dct_block = dct(dct(block.T, norm='ortho').T, norm='ortho')
                blocks.append(dct_block.flatten())
        
        return blocks
