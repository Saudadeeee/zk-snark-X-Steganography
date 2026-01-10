"""
MV Embedder - LSB Parity Embedding
===================================

Nhúng payload vào LSB (Least Significant Bit) của motion vectors.

Method: Parity Embedding
- Modify mvx LSB to match payload bit
- If mvx % 2 == bit → no change
- If mvx % 2 != bit → mvx ± 1 (choose direction minimizing distortion)

Features:
- Minimal RD-cost impact
- Simple extraction (no need decoder)
- Robust to minor modifications
"""

import json
import numpy as np
from typing import List, Tuple, Dict
from pathlib import Path

from .carrier_selector import CarrierSelector, MVCandidate
from .payload_encoder import (
    PayloadEncoder, PayloadDecoder, EmbeddingConfig,
    bytes_to_bits, bits_to_bytes
)


class MVEmbedder:
    """Embed payload into motion vectors"""
    
    def __init__(self, config: EmbeddingConfig):
        """
        Initialize MV embedder
        
        Args:
            config: Embedding configuration
        """
        self.config = config
        self.stats = {
            'modified_mvs': 0,
            'total_bits': 0,
            'avg_modification': 0.0
        }
    
    def embed(self,
              mv_data: List[dict],
              payload: bytes,
              chaos_seed: int) -> Tuple[List[dict], Dict]:
        """
        Embed payload into MV data
        
        Args:
            mv_data: List of MV dictionaries from h264_parser
            payload: Raw payload bytes
            chaos_seed: Seed for carrier selection
            
        Returns:
            (modified_mv_data, embedding_info)
        """
        print(f"\n{'='*60}")
        print("MV EMBEDDING")
        print(f"{'='*60}")
        
        # 1. Encode payload with ECC + header
        encoder = PayloadEncoder(self.config)
        encoded_payload = encoder.encode(payload, chaos_seed)
        payload_bits = bytes_to_bits(encoded_payload)
        
        print(f"[1] Payload encoding:")
        print(f"    Original: {len(payload)} bytes")
        print(f"    Encoded:  {len(encoded_payload)} bytes (+{len(encoded_payload)-len(payload)} bytes overhead)")
        print(f"    Bits:     {len(payload_bits)} bits")
        
        # 2. Select carrier MVs
        selector = CarrierSelector(
            seed=chaos_seed,
            min_magnitude=self.config.min_magnitude,
            max_magnitude=self.config.max_magnitude,
            embedding_rate=self.config.embedding_rate,
            prefer_component=self.config.component
        )
        
        carriers = selector.select_carriers(mv_data, required_bits=len(payload_bits))
        
        if len(carriers) < len(payload_bits):
            raise ValueError(f"Not enough carriers: need {len(payload_bits)}, got {len(carriers)}")
        
        print(f"[2] Carrier selection:")
        print(f"    Total MVs:      {len(mv_data)}")
        print(f"    Eligible:       {len([mv for mv in mv_data if self._is_eligible(mv)])}")
        print(f"    Selected:       {len(carriers)}")
        print(f"    Embedding rate: {100*len(carriers)/len(mv_data):.1f}%")
        
        # 3. Embed bits into carriers
        modified_mv_data = mv_data.copy()
        modifications = []
        
        for bit_idx, carrier in enumerate(carriers):
            bit_value = payload_bits[bit_idx]
            mv_idx = carrier.mv_index
            
            # Get current MV
            current_mv = modified_mv_data[mv_idx].copy()
            
            # Modify based on component
            if self.config.component == 'mvx':
                modified_value, delta = self._modify_parity(current_mv['mvx'], bit_value)
                current_mv['mvx'] = modified_value
            elif self.config.component == 'mvy':
                modified_value, delta = self._modify_parity(current_mv['mvy'], bit_value)
                current_mv['mvy'] = modified_value
            else:  # both
                # Use mvx for now
                modified_value, delta = self._modify_parity(current_mv['mvx'], bit_value)
                current_mv['mvx'] = modified_value
            
            modified_mv_data[mv_idx] = current_mv
            modifications.append(abs(delta))
        
        avg_mod = np.mean(modifications) if modifications else 0.0
        
        print(f"[3] Embedding results:")
        print(f"    Modified MVs:      {len(modifications)}")
        print(f"    Avg modification:  {avg_mod:.2f} pixels")
        print(f"    Max modification:  {max(modifications) if modifications else 0}")
        
        # 4. Create embedding info
        embedding_info = {
            'payload_size': len(payload),
            'encoded_size': len(encoded_payload),
            'bits_embedded': len(payload_bits),
            'carriers_used': len(carriers),
            'carrier_indices': [c.mv_index for c in carriers],  # Save for deterministic extraction
            'chaos_seed': chaos_seed,
            'avg_modification': float(avg_mod),
            'config': {
                'method': self.config.method,
                'component': self.config.component,
                'min_magnitude': self.config.min_magnitude,
                'ecc_enabled': self.config.ecc_enabled
            }
        }
        
        self.stats = embedding_info
        
        return modified_mv_data, embedding_info
    
    def _is_eligible(self, mv: dict) -> bool:
        """Check if MV is eligible for embedding"""
        magnitude = np.sqrt(mv['mvx']**2 + mv['mvy']**2)
        return (mv['frame_type'] == 'P' and 
                self.config.min_magnitude <= magnitude <= self.config.max_magnitude)
    
    def _modify_parity(self, value: int, target_bit: int) -> Tuple[int, int]:
        """
        Modify value to have parity = target_bit
        
        Args:
            value: Current MV component value
            target_bit: Target parity (0 or 1)
            
        Returns:
            (modified_value, delta)
        """
        current_parity = value & 1
        
        if current_parity == target_bit:
            # Already correct parity
            return value, 0
        
        # Need to flip parity
        # Choose +1 or -1 to minimize distortion
        if value >= 0:
            modified = value + 1  # Prefer increasing
            delta = 1
        else:
            modified = value - 1  # Prefer decreasing (more negative)
            delta = -1
        
        return modified, delta


class MVExtractor:
    """Extract payload from motion vectors"""
    
    def __init__(self):
        """Initialize MV extractor"""
        self.stats = {}
    
    def extract(self,
                mv_data: List[dict],
                chaos_seed: int = None,
                expected_bits: int = None,
                component: str = 'mvx',
                carrier_indices: List[int] = None) -> Tuple[bytes, bool]:
        """
        Extract payload from MV data
        
        Args:
            mv_data: List of MV dictionaries
            chaos_seed: Seed for carrier selection (if carrier_indices not provided)
            expected_bits: Number of bits to extract
            component: 'mvx', 'mvy', or 'both'
            carrier_indices: Exact carrier indices to use (overrides chaos_seed)
            
        Returns:
            (payload, valid) tuple
        """
        print(f"\n{'='*60}")
        print("MV EXTRACTION")
        print(f"{'='*60}")
        
        # 1. Select carriers
        if carrier_indices is not None:
            # Use exact carrier indices (deterministic)
            print(f"[1] Using exact carrier indices: {len(carrier_indices)} carriers")
            
            # Extract bits directly
            extracted_bits = []
            for idx in carrier_indices:
                mv = mv_data[idx]
                
                # Extract LSB based on component
                if component == 'mvx':
                    bit = mv['mvx'] & 1
                elif component == 'mvy':
                    bit = mv['mvy'] & 1
                else:
                    bit = mv['mvx'] & 1
                
                extracted_bits.append(bit)
            
            print(f"[2] Bit extraction:")
            print(f"    Bits extracted: {len(extracted_bits)}")
            
        else:
            # Use chaos-based selection (fallback)
            print(f"[1] Chaos-based carrier selection...")
            selector = CarrierSelector(
                seed=chaos_seed,
                min_magnitude=2.0,  # Stable under ±1 modification
                max_magnitude=50.0,
                embedding_rate=0.5,  # Higher to ensure we get enough
                prefer_component=component
            )
            
            carriers = selector.select_carriers(mv_data, required_bits=expected_bits)
            
            print(f"    Total MVs:   {len(mv_data)}")
            print(f"    Carriers:    {len(carriers)}")
            print(f"    Expected:    {expected_bits} bits")
            
            if len(carriers) < expected_bits:
                print(f"[ERROR] Not enough carriers: {len(carriers)} < {expected_bits}")
                return None, False
            
            # 2. Extract bits from carriers
            extracted_bits = []
            
            for carrier in carriers[:expected_bits]:
                mv = mv_data[carrier.mv_index]
                
                # Extract LSB based on component
                if component == 'mvx':
                    bit = mv['mvx'] & 1
                elif component == 'mvy':
                    bit = mv['mvy'] & 1
                else:
                    bit = mv['mvx'] & 1  # Default to mvx
                
                extracted_bits.append(bit)
            
            print(f"[2] Bit extraction:")
            print(f"    Bits extracted: {len(extracted_bits)}")
        
        # 3. Convert bits to bytes
        extracted_bytes = bits_to_bytes(extracted_bits)
        
        print(f"[3] Byte conversion:")
        print(f"    Bytes: {len(extracted_bytes)}")
        
        # 4. Decode payload (header + ECC)
        decoder = PayloadDecoder()
        payload, valid = decoder.decode(extracted_bytes)
        
        if valid:
            print(f"[4] Payload decoded successfully!")
            print(f"    Payload size: {len(payload)} bytes")
        else:
            print(f"[4] Payload decode FAILED")
        
        return payload, valid


def test_embedding():
    """Test embedding and extraction"""
    print("Testing MV Embedding/Extraction Pipeline")
    print("=" * 80)
    
    # Create fake MV data
    np.random.seed(42)
    mv_data = []
    
    for frame_idx in range(50):
        frame_type = 'I' if frame_idx % 30 == 0 else 'P'
        for mb_idx in range(100):
            mv_data.append({
                'frame_idx': frame_idx,
                'frame_type': frame_type,
                'timestamp': frame_idx / 30.0,
                'mb_x': mb_idx % 22,
                'mb_y': mb_idx // 22,
                'mvx': np.random.randint(-20, 20),
                'mvy': np.random.randint(-20, 20),
                'block_type': '16x16'
            })
    
    print(f"Generated {len(mv_data)} fake MVs")
    
    # Test payload
    test_payload = b"Hello ZK-SNARK! This is a secret message embedded in motion vectors."
    chaos_seed = 12345
    
    print(f"\nTest payload: {len(test_payload)} bytes")
    print(f"Content: {test_payload[:50]}...")
    
    # Embed
    config = EmbeddingConfig(
        component='mvx',
        min_magnitude=2.0,  # Stable under ±1 modification
        embedding_rate=0.3,
        ecc_enabled=True
    )
    
    embedder = MVEmbedder(config)
    modified_mv_data, info = embedder.embed(mv_data, test_payload, chaos_seed)
    
    print(f"\n{'='*60}")
    print("Embedding completed")
    print(f"{'='*60}")
    print(json.dumps(info, indent=2))
    
    # Extract
    extractor = MVExtractor()
    recovered_payload, valid = extractor.extract(
        modified_mv_data,
        chaos_seed=chaos_seed,
        expected_bits=info['bits_embedded'],
        component='mvx'
    )
    
    print(f"\n{'='*60}")
    print("FINAL RESULT")
    print(f"{'='*60}")
    print(f"Extraction valid: {valid}")
    print(f"Payload match: {recovered_payload == test_payload}")
    if recovered_payload:
        print(f"Recovered: {recovered_payload[:50]}...")


if __name__ == '__main__':
    test_embedding()
