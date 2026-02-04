"""
Unit tests for Temporal Interleaver

Tests temporal distribution of payload across video frames with:
- Frame chunking and permutation
- Recurrent frame dependency
- Missing frame recovery
- Configuration management

Week 8 - Phase 3
"""

import pytest
import hashlib
import numpy as np
from src.zk_mv_stego.crypto.temporal_interleaver import (
    TemporalInterleaver,
    create_frame_manifest
)


class TestInterleaverInitialization:
    """Test temporal interleaver initialization"""
    
    def test_default_initialization(self):
        """Test default interleaver creation"""
        interleaver = TemporalInterleaver()
        
        assert interleaver.num_frames == 10
        assert interleaver.permutation_indices is None
    
    def test_custom_num_frames(self):
        """Test custom number of frames"""
        interleaver = TemporalInterleaver(num_frames=15)
        
        assert interleaver.num_frames == 15
    
    def test_custom_seed(self):
        """Test with custom seed"""
        seed = b"my_secret_seed_1234567890"
        interleaver = TemporalInterleaver(secret_seed=seed)
        
        # Should use first 4 bytes
        expected_seed = int.from_bytes(seed[:4], byteorder='big')
        assert interleaver.rng.get_state()[1][0] == expected_seed
    
    def test_invalid_num_frames(self):
        """Test that num_frames < 2 raises error"""
        with pytest.raises(ValueError, match="num_frames must be >= 2"):
            TemporalInterleaver(num_frames=1)
        
        with pytest.raises(ValueError, match="num_frames must be >= 2"):
            TemporalInterleaver(num_frames=0)


class TestInterleaving:
    """Test payload interleaving"""
    
    def test_basic_interleave(self):
        """Test basic interleaving"""
        interleaver = TemporalInterleaver(num_frames=10)
        payload = bytes(range(100))  # 100 bytes
        
        chunks, indices = interleaver.interleave(payload)
        
        # Should create 10 chunks
        assert len(chunks) == 10
        assert len(indices) == 10
        
        # Total size preserved
        assert sum(len(c) for c in chunks) == 100
        
        # Each chunk should be ~10 bytes
        for chunk in chunks:
            assert 9 <= len(chunk) <= 11
    
    def test_uneven_payload_distribution(self):
        """Test payload size not divisible by num_frames"""
        interleaver = TemporalInterleaver(num_frames=10)
        payload = bytes(range(97))  # 97 bytes, not divisible by 10
        
        chunks, indices = interleaver.interleave(payload)
        
        # Should still create 10 chunks
        assert len(chunks) == 10
        
        # Total size preserved
        assert sum(len(c) for c in chunks) == 97
        
        # Some chunks will be 10 bytes, some 9 bytes
        chunk_sizes = [len(c) for c in chunks]
        assert max(chunk_sizes) - min(chunk_sizes) <= 1
    
    def test_permutation_randomness(self):
        """Test that permutation is actually random (not identity)"""
        interleaver = TemporalInterleaver(num_frames=10, secret_seed=b"test123")
        payload = bytes(range(100))
        
        chunks, indices = interleaver.interleave(payload)
        
        # Permutation should not be identity [0,1,2,3,...]
        assert indices != list(range(10))
        
        # But should contain all indices
        assert sorted(indices) == list(range(10))
    
    def test_deterministic_permutation(self):
        """Test that same seed produces same permutation"""
        seed = b"deterministic_seed"
        payload = bytes(range(100))
        
        # First interleave
        interleaver1 = TemporalInterleaver(num_frames=10, secret_seed=seed)
        chunks1, indices1 = interleaver1.interleave(payload)
        
        # Second interleave with same seed
        interleaver2 = TemporalInterleaver(num_frames=10, secret_seed=seed)
        chunks2, indices2 = interleaver2.interleave(payload)
        
        # Should get identical permutation
        assert indices1 == indices2
        assert chunks1 == chunks2
    
    def test_empty_payload_raises_error(self):
        """Test that empty payload raises error"""
        interleaver = TemporalInterleaver(num_frames=10)
        
        with pytest.raises(ValueError, match="Payload cannot be empty"):
            interleaver.interleave(b"")


class TestDeinterleaving:
    """Test payload deinterleaving"""
    
    def test_perfect_roundtrip(self):
        """Test interleave/deinterleave with no missing frames"""
        interleaver = TemporalInterleaver(num_frames=10)
        original = bytes(range(200))
        
        # Interleave
        chunks, indices = interleaver.interleave(original)
        
        # Deinterleave
        recovered = interleaver.deinterleave(chunks, indices)
        
        assert recovered == original
    
    def test_large_payload_roundtrip(self):
        """Test with larger payload (384 bytes - LDPC size)"""
        interleaver = TemporalInterleaver(num_frames=10)
        original = bytes(range(256)) + bytes(range(128))  # 384 bytes
        
        chunks, indices = interleaver.interleave(original)
        recovered = interleaver.deinterleave(chunks, indices)
        
        assert recovered == original
    
    def test_missing_frame_handling(self):
        """Test recovery with missing frames (zeros filled)"""
        interleaver = TemporalInterleaver(num_frames=10)
        original = bytes(range(100))
        
        chunks, indices = interleaver.interleave(original)
        
        # Simulate missing frame 3
        chunks[3] = None
        
        # Deinterleave (should fill with zeros)
        recovered = interleaver.deinterleave(chunks, indices)
        
        # Length should match
        assert len(recovered) == len(original)
        
        # Most of the data should be preserved (except the missing chunk)
        # Can't check exact equality since one chunk is zero-filled
    
    def test_multiple_missing_frames(self):
        """Test with multiple missing frames"""
        interleaver = TemporalInterleaver(num_frames=10)
        original = bytes(range(100))
        
        chunks, indices = interleaver.interleave(original)
        
        # Simulate missing frames 2, 5, 8
        chunks[2] = None
        chunks[5] = None
        chunks[8] = None
        
        # Should still deinterleave without crashing
        recovered = interleaver.deinterleave(chunks, indices)
        assert len(recovered) == len(original)
    
    def test_invalid_indices_length(self):
        """Test that wrong indices length raises error"""
        interleaver = TemporalInterleaver(num_frames=10)
        chunks = [b"test"] * 10
        indices = [0, 1, 2]  # Wrong length
        
        with pytest.raises(ValueError, match="Expected 10 indices"):
            interleaver.deinterleave(chunks, indices)


class TestFrameDependency:
    """Test recurrent frame dependency"""
    
    def test_compute_frame_dependency(self):
        """Test dependency computation"""
        interleaver = TemporalInterleaver(num_frames=10)
        
        # Frame 0 with initial seed
        mb_start_0 = interleaver.compute_frame_dependency(0, b"initial_seed")
        assert 0 <= mb_start_0 < 100
        
        # Frame 1 with different hash
        hash_0 = hashlib.sha256(b"chunk_0").digest()
        mb_start_1 = interleaver.compute_frame_dependency(1, hash_0)
        assert 0 <= mb_start_1 < 100
        
        # Should be different (highly likely)
        assert mb_start_0 != mb_start_1
    
    def test_deterministic_dependency(self):
        """Test that dependency is deterministic"""
        interleaver = TemporalInterleaver(num_frames=10)
        prev_hash = b"test_hash"
        
        # Multiple calls with same hash should give same result
        mb1 = interleaver.compute_frame_dependency(5, prev_hash)
        mb2 = interleaver.compute_frame_dependency(5, prev_hash)
        
        assert mb1 == mb2
    
    def test_get_frame_chain(self):
        """Test full frame dependency chain"""
        interleaver = TemporalInterleaver(num_frames=5)
        chunks = [bytes([i] * 10) for i in range(5)]
        initial_seed = b"secret"
        
        chain = interleaver.get_frame_chain(chunks, initial_seed)
        
        # Should have 5 entries
        assert len(chain) == 5
        
        # Each entry should be (mb_start, frame_hash)
        for mb_start, frame_hash in chain:
            assert 0 <= mb_start < 100
            assert len(frame_hash) == 32  # SHA256 hash
    
    def test_chain_dependency(self):
        """Test that chain creates proper dependencies"""
        interleaver = TemporalInterleaver(num_frames=5)
        chunks = [bytes([i] * 10) for i in range(5)]
        initial_seed = b"secret"
        
        chain = interleaver.get_frame_chain(chunks, initial_seed)
        
        # Extract all MB positions
        mb_positions = [mb for mb, _ in chain]
        
        # Positions should vary (not all the same)
        assert len(set(mb_positions)) > 1


class TestConfiguration:
    """Test configuration management"""
    
    def test_get_config(self):
        """Test configuration retrieval"""
        interleaver = TemporalInterleaver(num_frames=12, secret_seed=b"test")
        
        # Before interleaving
        config = interleaver.get_config()
        assert config['num_frames'] == 12
        assert config['permutation_indices'] is None
        
        # After interleaving
        payload = bytes(range(100))
        chunks, indices = interleaver.interleave(payload)
        
        config = interleaver.get_config()
        assert config['permutation_indices'] == indices
    
    def test_reset(self):
        """Test interleaver reset"""
        interleaver = TemporalInterleaver(num_frames=10)
        payload = bytes(range(100))
        
        # Interleave to set state
        chunks, indices = interleaver.interleave(payload)
        assert interleaver.permutation_indices is not None
        
        # Reset
        interleaver.reset()
        assert interleaver.permutation_indices is None
    
    def test_validate_chunk_sizes(self):
        """Test chunk size validation"""
        interleaver = TemporalInterleaver(num_frames=10)
        
        # Valid chunks (uniform size)
        valid_chunks = [bytes(range(10))] * 10
        assert interleaver.validate_chunk_sizes(valid_chunks) is True
        
        # Valid chunks (size difference ≤ 2)
        mixed_chunks = [bytes(range(10))] * 5 + [bytes(range(11))] * 5
        assert interleaver.validate_chunk_sizes(mixed_chunks) is True
        
        # Invalid chunks (empty)
        assert interleaver.validate_chunk_sizes([]) is False
        
        # Invalid chunks (all None)
        assert interleaver.validate_chunk_sizes([None] * 10) is False


class TestManifestCreation:
    """Test frame manifest creation"""
    
    def test_create_manifest(self):
        """Test manifest generation"""
        chunks = [bytes([i] * 10) for i in range(5)]
        indices = [2, 0, 4, 1, 3]
        initial_seed = b"seed123"
        
        manifest = create_frame_manifest(chunks, indices, initial_seed)
        
        # Check basic structure
        assert manifest['frame_count'] == 5
        assert manifest['total_bytes'] == 50
        assert manifest['chunk_sizes'] == [10, 10, 10, 10, 10]
        assert manifest['permutation'] == indices
        assert len(manifest['frames']) == 5
    
    def test_manifest_frame_info(self):
        """Test per-frame information in manifest"""
        chunks = [bytes([i] * 10) for i in range(3)]
        indices = [0, 1, 2]
        initial_seed = b"test"
        
        manifest = create_frame_manifest(chunks, indices, initial_seed)
        
        # Each frame should have required fields
        for frame in manifest['frames']:
            assert 'index' in frame
            assert 'size' in frame
            assert 'hash' in frame
            assert 'mb_start' in frame
            assert 0 <= frame['mb_start'] < 100
    
    def test_manifest_with_none_chunks(self):
        """Test manifest handles missing chunks"""
        chunks = [bytes([1] * 10), None, bytes([3] * 10)]
        indices = [0, 1, 2]
        initial_seed = b"test"
        
        # Should not crash with None chunks
        manifest = create_frame_manifest(chunks, indices, initial_seed)
        
        assert manifest['frame_count'] == 3
        # Frame 1 should have size 0
        assert manifest['chunk_sizes'][1] == 0


class TestEdgeCases:
    """Test edge cases and error handling"""
    
    def test_minimum_frames(self):
        """Test with minimum number of frames (2)"""
        interleaver = TemporalInterleaver(num_frames=2)
        payload = bytes(range(20))
        
        chunks, indices = interleaver.interleave(payload)
        recovered = interleaver.deinterleave(chunks, indices)
        
        assert recovered == payload
    
    def test_large_num_frames(self):
        """Test with large number of frames"""
        interleaver = TemporalInterleaver(num_frames=50)
        payload = bytes(range(200))
        
        chunks, indices = interleaver.interleave(payload)
        recovered = interleaver.deinterleave(chunks, indices)
        
        assert recovered == payload
    
    def test_small_payload(self):
        """Test with payload smaller than num_frames"""
        interleaver = TemporalInterleaver(num_frames=10)
        payload = bytes(range(5))  # Only 5 bytes for 10 frames
        
        chunks, indices = interleaver.interleave(payload)
        
        # Some chunks will be 1 byte, others 0 bytes
        assert len(chunks) == 10
        assert sum(len(c) for c in chunks) == 5
    
    def test_text_payload(self):
        """Test with text payload"""
        interleaver = TemporalInterleaver(num_frames=10)
        payload = b"The quick brown fox jumps over the lazy dog"
        
        chunks, indices = interleaver.interleave(payload)
        recovered = interleaver.deinterleave(chunks, indices)
        
        assert recovered == payload


class TestIntegration:
    """Integration tests"""
    
    def test_ldpc_integration(self):
        """Test integration with typical LDPC payload"""
        interleaver = TemporalInterleaver(num_frames=10)
        
        # Simulate LDPC output (384 bytes at rate 1/2)
        ldpc_payload = bytes(range(256)) + bytes(range(128))
        
        # Interleave
        chunks, indices = interleaver.interleave(ldpc_payload)
        
        # Each chunk should be ~38-39 bytes
        for chunk in chunks:
            assert 37 <= len(chunk) <= 40
        
        # Deinterleave
        recovered = interleaver.deinterleave(chunks, indices)
        assert recovered == ldpc_payload
    
    def test_multiple_interleave_cycles(self):
        """Test multiple interleave/deinterleave cycles"""
        interleaver = TemporalInterleaver(num_frames=8)
        
        for i in range(5):
            payload = bytes(range(i * 20, (i + 1) * 20))
            
            chunks, indices = interleaver.interleave(payload)
            recovered = interleaver.deinterleave(chunks, indices)
            
            assert recovered == payload


class TestPerformance:
    """Performance tests"""
    
    def test_interleave_performance(self):
        """Test interleaving performance"""
        import time
        
        interleaver = TemporalInterleaver(num_frames=10)
        payload = bytes(range(256)) + bytes(range(128))  # 384 bytes
        
        start = time.time()
        for _ in range(100):
            chunks, indices = interleaver.interleave(payload)
        elapsed = time.time() - start
        
        # Should be fast (<1ms per operation)
        assert elapsed < 0.1  # 100 operations in <100ms
    
    def test_deinterleave_performance(self):
        """Test deinterleaving performance"""
        import time
        
        interleaver = TemporalInterleaver(num_frames=10)
        payload = bytes(range(256)) + bytes(range(128))  # 384 bytes
        chunks, indices = interleaver.interleave(payload)
        
        start = time.time()
        for _ in range(100):
            recovered = interleaver.deinterleave(chunks, indices)
        elapsed = time.time() - start
        
        # Should be fast
        assert elapsed < 0.1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
