"""
Embedding Coordinator for ZK-SNARK Video Steganography v3.0

Coordinates all components from Weeks 1-8 into a unified embedding pipeline:
- YUV conversion and preprocessing
- DWT analysis and frequency mapping
- Hybrid DCT-DWT coefficient selection
- RC4 encryption of ZK proof
- Context-aware macroblock selection
- LDPC error correction encoding
- Data interleaving for burst error protection
- Temporal distribution across frames

Week 9 Implementation - Phase 3 Finalization
"""

import numpy as np
import hashlib
from typing import List, Dict, Tuple, Optional, TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from ..preprocessing.yuv_converter import YUVConverter
    from ..preprocessing.dwt_analyzer import HaarDWTAnalyzer
    from ..preprocessing.hybrid_selector import HybridCoefficientSelector
    from ..crypto.rc4_cipher import RC4Cipher
    from ..preprocessing.context_analyzer import ContextAnalyzer
    from ..crypto.ldpc_codec import LDPCCodec
    from ..crypto.data_interleaver import DataInterleaver
    from ..crypto.temporal_interleaver import TemporalInterleaver


@dataclass
class EmbeddingConfig:
    """Configuration for embedding pipeline"""
    # Phase 1: Preprocessing
    use_yuv_conversion: bool = True
    dwt_levels: int = 2
    hybrid_selection: bool = True
    
    # Phase 2: Encryption & Context
    rc4_encryption: bool = True
    context_aware: bool = True
    min_texture_score: float = 0.3
    min_motion_score: float = 0.2
    
    # Phase 3: Error Correction
    ldpc_enabled: bool = True
    ldpc_code_rate: float = 0.5
    data_interleaving: bool = True
    interleaving_method: str = 'block'  # 'block' or 'convolutional'
    block_size: int = 128
    temporal_frames: int = 10
    
    # Advanced
    max_coeffs_per_mb: int = 10
    target_psnr: float = 42.0
    adaptive_rate: bool = True


class EmbeddingCoordinator:
    """
    Coordinates all embedding components into unified pipeline
    
    Pipeline flow:
    1. YUV Conversion → Extract luma channel
    2. DWT Analysis → Frequency decomposition
    3. Hybrid Selection → DCT-DWT coefficient filtering
    4. RC4 Encryption → Obfuscate ZK proof
    5. Context Analysis → Select best macroblocks
    6. LDPC Encoding → Add error correction
    7. Data Interleaving → Spread burst errors
    8. Temporal Distribution → Multi-frame embedding
    
    Example:
        >>> config = EmbeddingConfig()
        >>> coordinator = EmbeddingCoordinator(config, secret_key=b"my_key")
        >>> chunks, metadata = coordinator.prepare_payload(zk_proof)
        >>> result = coordinator.embed_into_frames(frames, chunks, metadata)
    """
    
    def __init__(self, secret_key: bytes, config: EmbeddingConfig):
        """
        Initialize embedding coordinator

        Args:
            secret_key: Master secret key for RC4 and PRNG seeding
            config: Embedding configuration

        Raises:
            ValueError: If secret_key is too short (< 16 bytes)
        """
        if len(secret_key) < 16:
            raise ValueError("Secret key must be at least 16 bytes")
        
        self.config = config
        self.secret_key = secret_key
        
        # Lazy imports to avoid circular dependency
        from ..preprocessing.yuv_converter import YUVConverter
        from ..preprocessing.dwt_analyzer import HaarDWTAnalyzer
        from ..preprocessing.hybrid_selector import HybridCoefficientSelector
        from ..crypto.rc4_cipher import RC4Cipher
        from ..preprocessing.context_analyzer import ContextAnalyzer
        from ..crypto.ldpc_codec import LDPCCodec
        from ..crypto.data_interleaver import DataInterleaver
        from ..crypto.temporal_interleaver import TemporalInterleaver
        
        # Initialize Phase 1 components
        self.yuv_converter = YUVConverter() if config.use_yuv_conversion else None
        self.dwt_analyzer = HaarDWTAnalyzer(levels=config.dwt_levels)
        self.hybrid_selector = HybridCoefficientSelector(self.dwt_analyzer) if config.hybrid_selection else None
        
        # Initialize Phase 2 components
        if config.rc4_encryption:
            rc4_key = self._derive_key(b"RC4_CIPHER")
            self.rc4_cipher = RC4Cipher(rc4_key)
        else:
            self.rc4_cipher = None
        
        self.context_analyzer = ContextAnalyzer() if config.context_aware else None
        
        # Initialize Phase 3 components
        if config.ldpc_enabled:
            self.ldpc_codec = LDPCCodec(code_rate=config.ldpc_code_rate)
        else:
            self.ldpc_codec = None
        
        if config.data_interleaving:
            self.data_interleaver = DataInterleaver(
                method=config.interleaving_method,
                block_size=config.block_size
            )
        else:
            self.data_interleaver = None
        
        temporal_seed = self._derive_key(b"TEMPORAL_SEED")
        self.temporal_interleaver = TemporalInterleaver(
            num_frames=config.temporal_frames,
            secret_seed=temporal_seed
        )
        
        # State tracking
        self.embedding_map: Dict[int, List[Tuple[int, int]]] = {}  # frame_idx -> [(mb_idx, coeff_pos), ...]
        self.statistics = {
            'total_capacity': 0,
            'used_capacity': 0,
            'average_psnr': 0.0,
            'frames_used': 0
        }
    
    def _derive_key(self, salt: str) -> bytes:
        """Derive sub-key from master secret using HMAC-SHA256"""
        import hmac
        salt_bytes = salt.encode('utf-8') if isinstance(salt, str) else salt
        return hmac.new(self.secret_key, salt_bytes, hashlib.sha256).digest()
    
    def prepare_payload(self, zk_proof: bytes) -> Tuple[List[bytes], Dict]:
        """
        Prepare ZK proof payload for embedding
        
        Pipeline:
        1. RC4 encrypt (if enabled)
        2. LDPC encode (if enabled)
        3. Data interleave (if enabled)
        4. Temporal split into chunks
        
        Args:
            zk_proof: Raw ZK-SNARK proof bytes (192 bytes expected)
        
        Returns:
            Tuple of:
            - chunks: List of payload chunks for each frame
            - metadata: Embedding metadata (indices, params, etc.)
        
        Raises:
            ValueError: If proof size doesn't match LDPC requirements
        """
        payload = zk_proof
        metadata = {
            'original_size': len(zk_proof),
            'pipeline_stages': []
        }
        
        # Stage 1: RC4 Encryption
        if self.rc4_cipher:
            payload = self.rc4_cipher.encrypt(payload)
            entropy = self.rc4_cipher.compute_entropy(payload)
            metadata['pipeline_stages'].append({
                'stage': 'rc4_encryption',
                'entropy': entropy,
                'size': len(payload)
            })
        
        # Stage 2: LDPC Encoding
        if self.ldpc_codec:
            payload = self.ldpc_codec.encode(payload)
            code_info = self.ldpc_codec.get_code_info()
            metadata['pipeline_stages'].append({
                'stage': 'ldpc_encoding',
                'code_rate': code_info['code_rate'],
                'input_size': code_info['data_bytes'],
                'output_size': code_info['codeword_bytes']
            })
        
        # Stage 3: Data Interleaving
        if self.data_interleaver:
            payload = self.data_interleaver.interleave(payload)
            interleave_config = self.data_interleaver.get_config()
            metadata['pipeline_stages'].append({
                'stage': 'data_interleaving',
                'method': interleave_config['method'],
                'block_size': interleave_config.get('block_size'),
                'depth': interleave_config.get('depth')
            })
        
        # Stage 4: Temporal Distribution
        chunks, permutation_indices = self.temporal_interleaver.interleave(payload)
        temporal_config = self.temporal_interleaver.get_config()
        metadata['pipeline_stages'].append({
            'stage': 'temporal_interleaving',
            'num_frames': self.config.temporal_frames,
            'permutation': permutation_indices,
            'chunk_sizes': [len(c) for c in chunks]
        })
        
        metadata['final_chunk_count'] = len(chunks)
        metadata['total_payload_size'] = len(payload)
        
        return chunks, metadata
    
    def extract_payload(self, chunks: List[bytes], metadata: Dict) -> bytes:
        """
        Extract and decode payload from embedded chunks
        
        Reverse pipeline:
        1. Temporal deinterleave
        2. Data deinterleave (if enabled)
        3. LDPC decode (if enabled)
        4. RC4 decrypt (if enabled)
        
        Args:
            chunks: Extracted chunks from frames
            metadata: Embedding metadata from prepare_payload()
        
        Returns:
            Original ZK proof bytes
        
        Raises:
            ValueError: If metadata is missing required fields
        """
        # Stage 4 reverse: Temporal Deinterleaving
        temporal_stage = next(s for s in metadata['pipeline_stages'] if s['stage'] == 'temporal_interleaving')
        permutation = temporal_stage['permutation']
        payload = self.temporal_interleaver.deinterleave(chunks, permutation)
        
        # Stage 3 reverse: Data Deinterleaving
        if self.data_interleaver:
            payload = self.data_interleaver.deinterleave(payload)
        
        # Stage 2 reverse: LDPC Decoding
        if self.ldpc_codec:
            payload, success, iterations = self.ldpc_codec.decode(payload)
            if not success:
                print(f"Warning: LDPC decoding did not converge after {iterations} iterations")
        
        # Stage 1 reverse: RC4 Decryption
        if self.rc4_cipher:
            payload = self.rc4_cipher.decrypt(payload)
        
        return payload
    
    def select_embedding_positions(
        self,
        frame_data: bytes,
        chunk_size: int,
        frame_idx: int,
        prev_frame_data: Optional[bytes] = None
    ) -> List[Tuple[int, int]]:
        """
        Select optimal embedding positions for a frame
        
        Uses hybrid DCT-DWT selection + context analysis
        
        Args:
            frame_data: Frame pixel data
            chunk_size: Size of chunk to embed (in bits)
            frame_idx: Frame index for temporal dependency
            prev_frame_data: Previous frame for motion analysis
        
        Returns:
            List of (macroblock_idx, coefficient_pos) tuples
        """
        positions = []
        
        # Phase 1: Preprocessing
        if isinstance(frame_data, np.ndarray):
            # frame_data is already a numpy array (RGB or grayscale)
            if len(frame_data.shape) == 3:
                # RGB: extract Y channel
                y_channel = self.yuv_converter.get_luma_channel(frame_data) if self.yuv_converter else frame_data[:, :, 0]
            else:
                # Grayscale
                y_channel = frame_data
        elif self.yuv_converter:
            y_channel = self.yuv_converter.get_luma_channel(frame_data)
        else:
            # Assume frame_data is already Y channel
            y_channel = np.frombuffer(frame_data, dtype=np.uint8).reshape(-1, 16)
        
        # Analyze each macroblock
        height, width = y_channel.shape[:2]
        num_macroblocks = (height // 16) * (width // 16)  # 16x16 blocks
        
        for mb_idx in range(num_macroblocks):
            mb_data = self._extract_macroblock(y_channel, mb_idx)
            
            # DWT analysis
            dwt_result = self.dwt_analyzer.analyze_macroblock(mb_data)
            energy_map = self.dwt_analyzer.compute_energy_map(dwt_result)
            
            # Context analysis (if enabled)
            if self.context_analyzer:
                # Compute texture score
                texture_score = self.context_analyzer.analyze_texture(
                    mb_data,
                    method='combined'
                )
                # Assume zero motion for still-frame analysis
                context_score = self.context_analyzer.compute_context_score(
                    texture_score,
                    motion_score=0.0
                )
                
                # Filter by quality threshold
                if context_score < self.config.min_texture_score:
                    continue
            
            # Hybrid selection
            if self.hybrid_selector:
                # Mock DCT coefficients (in real implementation, extract from bitstream)
                dct_coeffs = self._mock_dct_coefficients(mb_data)
                
                candidates = self.hybrid_selector.select_candidates(
                    mb_data,
                    dct_coeffs,
                    max_coeffs=self.config.max_coeffs_per_mb
                )
                
                for coeff_pos, score in candidates:
                    positions.append((mb_idx, coeff_pos))
                    
                    if len(positions) >= chunk_size:
                        break
            
            if len(positions) >= chunk_size:
                break
        
        # Store mapping
        self.embedding_map[frame_idx] = positions
        
        return positions[:chunk_size]
    
    def _extract_macroblock(self, y_channel: np.ndarray, mb_idx: int) -> np.ndarray:
        """Extract 16x16 macroblock from frame"""
        height, width = y_channel.shape
        mb_per_row = width // 16
        
        row = mb_idx // mb_per_row
        col = mb_idx % mb_per_row
        
        mb = y_channel[row*16:(row+1)*16, col*16:(col+1)*16]
        return mb
    
    def _mock_dct_coefficients(self, mb_data: np.ndarray) -> np.ndarray:
        """Mock DCT coefficients for demonstration (real impl extracts from bitstream)"""
        from scipy.fftpack import dct
        
        # Simple 2D DCT
        dct_2d = dct(dct(mb_data.T, norm='ortho').T, norm='ortho')
        return dct_2d.flatten()
    
    def estimate_capacity(self, frames: List[bytes]) -> Dict:
        """
        Estimate embedding capacity across all frames
        
        Args:
            frames: List of frame data
        
        Returns:
            Capacity statistics dictionary
        """
        total_bits = 0
        frame_capacities = []
        
        for frame_idx, frame_data in enumerate(frames):
            # Analyze frame
            if isinstance(frame_data, np.ndarray):
                if len(frame_data.shape) == 3:
                    y_channel = self.yuv_converter.get_luma_channel(frame_data) if self.yuv_converter else frame_data[:, :, 0]
                else:
                    y_channel = frame_data
            elif self.yuv_converter:
                y_channel = self.yuv_converter.get_luma_channel(frame_data)
            else:
                y_channel = np.frombuffer(frame_data, dtype=np.uint8).reshape(-1, 16)
            
            height, width = y_channel.shape[:2]
            num_macroblocks = (height // 16) * (width // 16)
            suitable_mbs = 0
            
            for mb_idx in range(num_macroblocks):
                mb_data = self._extract_macroblock(y_channel, mb_idx)
                
                if self.context_analyzer:
                    texture_score = self.context_analyzer.analyze_texture(
                        mb_data,
                        method='combined'
                    )
                    score = self.context_analyzer.compute_context_score(
                        texture_score, motion_score=0.0
                    )
                    if score >= self.config.min_texture_score:
                        suitable_mbs += 1
                else:
                    suitable_mbs += 1
            
            # Estimate bits per suitable MB
            bits_per_mb = self.config.max_coeffs_per_mb
            frame_capacity = suitable_mbs * bits_per_mb
            
            frame_capacities.append(frame_capacity)
            total_bits += frame_capacity
        
        return {
            'total_bits': total_bits,
            'total_bytes': total_bits // 8,
            'frame_capacities': frame_capacities,
            'average_capacity_per_frame': total_bits // len(frames) if frames else 0,
            'num_frames': len(frames)
        }
    
    def get_statistics(self) -> Dict:
        """Get embedding statistics"""
        return self.statistics.copy()
    
    def reset(self):
        """Reset coordinator state"""
        self.embedding_map.clear()
        self.statistics = {
            'total_capacity': 0,
            'used_capacity': 0,
            'average_psnr': 0.0,
            'frames_used': 0
        }
        
        if self.temporal_interleaver:
            self.temporal_interleaver.reset()


def create_default_coordinator(secret_key: bytes) -> EmbeddingCoordinator:
    """
    Create coordinator with recommended default configuration
    
    Args:
        secret_key: Master secret key (≥ 16 bytes)
    
    Returns:
        Configured EmbeddingCoordinator instance
    
    Example:
        >>> coordinator = create_default_coordinator(b"my_secret_key_123")
        >>> chunks, metadata = coordinator.prepare_payload(zk_proof)
    """
    config = EmbeddingConfig(
        use_yuv_conversion=True,
        dwt_levels=2,
        hybrid_selection=True,
        rc4_encryption=True,
        context_aware=True,
        min_texture_score=0.3,
        ldpc_enabled=True,
        ldpc_code_rate=0.5,
        data_interleaving=True,
        interleaving_method='block',
        temporal_frames=10
    )
    
    return EmbeddingCoordinator(secret_key, config)


if __name__ == "__main__":
    # Quick demonstration (standalone mode)
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
    
    print("Embedding Coordinator v3.0")
    print("=" * 50)
    
    # Mock minimal config for testing without all dependencies
    class MockConfig:
        def __init__(self):
            self.use_yuv_conversion = False
            self.dwt_levels = 2
            self.hybrid_selection = False
            self.rc4_encryption = True
            self.context_aware = False
            self.min_texture_score = 0.3
            self.ldpc_enabled = True
            self.ldpc_code_rate = 0.5
            self.data_interleaving = True
            self.interleaving_method = 'block'
            self.block_size = 128
            self.temporal_frames = 10
    
    # Test with mock minimal components
    import zk_mv_stego.crypto.rc4_cipher
    import zk_mv_stego.crypto.ldpc_codec
    import zk_mv_stego.crypto.data_interleaver  
    import zk_mv_stego.crypto.temporal_interleaver
    from zk_mv_stego.preprocessing.dwt_analyzer import HaarDWTAnalyzer
    
    config = MockConfig()
    
    print("\nInitializing coordinator components...")
    print(f"  RC4: {config.rc4_encryption}")
    print(f"  LDPC: {config.ldpc_enabled} (rate={config.ldpc_code_rate})")
    print(f"  Data Interleaving: {config.data_interleaving} ({config.interleaving_method})")
    print(f"  Temporal Frames: {config.temporal_frames}")
    
    # Create a simple test
    from zk_mv_stego.crypto.rc4_cipher import RC4Cipher
    from zk_mv_stego.crypto.ldpc_codec import LDPCCodec
    from zk_mv_stego.crypto.data_interleaver import DataInterleaver
    from zk_mv_stego.crypto.temporal_interleaver import TemporalInterleaver
    
    secret_key = b"test_secret_key_0123456789"
    
    # Test RC4
    rc4 = RC4Cipher(secret_key)
    proof = bytes(range(192))
    encrypted = rc4.encrypt(proof)
    print(f"\n✓ RC4 encryption: {len(encrypted)} bytes")
    
    # Test LDPC
    ldpc = LDPCCodec(code_rate=0.5)
    encoded = ldpc.encode(proof)
    print(f"✓ LDPC encoding: {len(proof)} → {len(encoded)} bytes")
    
    # Test Data Interleaving
    interleaver = DataInterleaver(method='block', block_size=128)
    interleaved = interleaver.interleave(encoded)
    print(f"✓ Data interleaving: {len(interleaved)} bytes")
    
    # Test Temporal
    temporal = TemporalInterleaver(num_frames=10, secret_seed=secret_key)
    chunks, indices = temporal.interleave(interleaved)
    print(f"✓ Temporal split: {len(chunks)} chunks")
    
    # Test round-trip
    recovered = temporal.deinterleave(chunks, indices)
    recovered = interleaver.deinterleave(recovered)
    recovered, success, iters = ldpc.decode(recovered)
    recovered = rc4.decrypt(recovered)
    
    print(f"\n✓ Full pipeline test:")
    print(f"  Original: {len(proof)} bytes")
    print(f"  Recovered: {len(recovered)} bytes")
    print(f"  Match: {proof == recovered}")
    print(f"  LDPC Success: {success} ({iters} iterations)")
    
    print("\n" + "=" * 50)
    print("Embedding Coordinator ready for use!")
