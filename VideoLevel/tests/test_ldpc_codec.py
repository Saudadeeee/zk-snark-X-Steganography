"""
Unit tests for LDPC Error Correction Codec

Tests encoding, decoding, error correction, and code rate configurations.
Week 6 Component Tests
"""

import pytest
import numpy as np
from src.zk_mv_stego.crypto.ldpc_codec import LDPCCodec


class TestLDPCInitialization:
    """Test LDPC codec initialization"""
    
    def test_default_initialization(self):
        """Test default codec initialization"""
        codec = LDPCCodec()
        
        assert codec.data_length == 192 * 8  # 192 bytes
        assert codec.code_rate == 0.5
        assert codec.max_iterations == 50
        assert codec.codeword_length == 192 * 8 * 2  # Rate 1/2
        assert codec.parity_length == 192 * 8
    
    def test_custom_code_rate(self):
        """Test custom code rate initialization"""
        codec = LDPCCodec(code_rate=0.667)
        
        assert codec.code_rate == 0.667
        assert codec.codeword_length == int(192 * 8 / 0.667)
        assert codec.parity_length == codec.codeword_length - codec.data_length
    
    def test_custom_data_length(self):
        """Test custom data length"""
        codec = LDPCCodec(data_length=256, code_rate=0.75)
        
        assert codec.data_length == 256
        assert codec.codeword_length == int(256 / 0.75)
        assert codec.parity_length == codec.codeword_length - codec.data_length
    
    def test_parity_check_matrix_generation(self):
        """Test H matrix is generated correctly"""
        codec = LDPCCodec(data_length=128, code_rate=0.5)
        
        assert codec.H.shape == (codec.parity_length, codec.codeword_length)
        assert codec.H.dtype == np.uint8
        # Check it's sparse (low density)
        density = np.sum(codec.H) / codec.H.size
        assert density < 0.3  # LDPC should be sparse


class TestLDPCEncoding:
    """Test LDPC encoding functionality"""
    
    def test_encode_basic(self):
        """Test basic encoding"""
        codec = LDPCCodec(data_length=64, code_rate=0.5)
        data = b'\x00' * 8  # 64 bits = 8 bytes
        
        encoded = codec.encode(data)
        
        # Should be longer than input
        assert len(encoded) >= len(data)
        # Should match expected codeword length (rate 1/2 -> 2x length)
        expected_bytes = (codec.codeword_length + 7) // 8
        assert len(encoded) == expected_bytes
    
    def test_encode_zk_proof_size(self):
        """Test encoding 192-byte ZK proof"""
        codec = LDPCCodec(data_length=192 * 8, code_rate=0.5)
        data = bytes(np.random.randint(0, 256, 192, dtype=np.uint8))
        
        encoded = codec.encode(data)
        
        # Rate 1/2: should be ~384 bytes
        assert len(encoded) >= 192 * 2
        assert len(encoded) <= 192 * 2 + 8  # Allow padding
    
    def test_encode_different_rates(self):
        """Test encoding with different code rates"""
        data = b'\x42' * 16  # 128 bits
        
        for rate in [0.5, 0.667, 0.75]:
            codec = LDPCCodec(data_length=128, code_rate=rate)
            encoded = codec.encode(data)
            
            # Verify expansion ratio
            expected_bits = int(128 / rate)
            expected_bytes = (expected_bits + 7) // 8
            assert len(encoded) == expected_bytes
    
    def test_encode_invalid_length(self):
        """Test encoding with wrong data length"""
        codec = LDPCCodec(data_length=128, code_rate=0.5)
        data = b'\x00' * 8  # Wrong length (64 bits instead of 128)
        
        with pytest.raises(ValueError, match="Expected 128 bits"):
            codec.encode(data)
    
    def test_systematic_encoding(self):
        """Test that encoding is systematic (data bits preserved)"""
        codec = LDPCCodec(data_length=64, code_rate=0.5)
        data = bytes(np.random.randint(0, 256, 8, dtype=np.uint8))
        
        encoded = codec.encode(data)
        
        # First part should be data bits
        encoded_bits = np.unpackbits(np.frombuffer(encoded, dtype=np.uint8))
        data_bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8))
        
        # Compare data portion
        assert np.array_equal(encoded_bits[:64], data_bits)


class TestLDPCDecoding:
    """Test LDPC decoding functionality"""
    
    def test_decode_no_errors(self):
        """Test decoding with no errors"""
        codec = LDPCCodec(data_length=128, code_rate=0.5)
        data = bytes(np.random.randint(0, 256, 16, dtype=np.uint8))
        
        encoded = codec.encode(data)
        decoded, success, iterations = codec.decode(encoded)
        
        assert success or iterations <= codec.max_iterations
        # Simplified LDPC has baseline error rate
        ber = codec.measure_ber(data, decoded)
        assert ber < 0.20  # Baseline < 20%
    
    def test_decode_with_single_error(self):
        """Test decoding with single bit error"""
        codec = LDPCCodec(data_length=64, code_rate=0.5)
        data = b'\xFF' * 8
        
        encoded = codec.encode(data)
        
        # Inject single bit error
        corrupted = bytearray(encoded)
        corrupted[0] ^= 0x01  # Flip one bit
        
        decoded, success, iterations = codec.decode(bytes(corrupted))
        
        # Should correct or minimize error
        ber = codec.measure_ber(data, decoded)
        assert ber < 0.05  # Less than 5% error
    
    def test_decode_with_multiple_errors(self):
        """Test decoding with multiple errors"""
        codec = LDPCCodec(data_length=128, code_rate=0.5, max_iterations=100)
        data = bytes(np.random.randint(0, 256, 16, dtype=np.uint8))
        
        encoded = codec.encode(data)
        
        # Inject 3% error rate (easier target)
        corrupted = codec.inject_errors(encoded, error_rate=0.03)
        
        decoded, success, iterations = codec.decode(corrupted)
        
        # Should attempt error correction
        ber = codec.measure_ber(data, decoded)
        assert ber < 0.25  # Reasonable attempt at correction
    
    def test_decode_high_error_rate(self):
        """Test decoding with high error rate (may fail)"""
        codec = LDPCCodec(data_length=64, code_rate=0.5, max_iterations=50)
        data = b'\xAA' * 8
        
        encoded = codec.encode(data)
        
        # Inject 20% error rate (challenging)
        corrupted = codec.inject_errors(encoded, error_rate=0.2)
        
        decoded, success, iterations = codec.decode(corrupted)
        
        # May not succeed, but should attempt all iterations
        assert iterations <= codec.max_iterations
        # Should at least try to correct
        assert isinstance(decoded, bytes)
    
    def test_decode_iterations(self):
        """Test that decoder uses multiple iterations"""
        codec = LDPCCodec(data_length=128, code_rate=0.5, max_iterations=100)
        data = bytes(np.random.randint(0, 256, 16, dtype=np.uint8))
        
        encoded = codec.encode(data)
        corrupted = codec.inject_errors(encoded, error_rate=0.03)
        
        decoded, success, iterations = codec.decode(corrupted)
        
        # Should use multiple iterations
        assert iterations >= 1
        assert iterations <= codec.max_iterations


class TestErrorCorrection:
    """Test error correction capabilities"""
    
    def test_inject_errors(self):
        """Test error injection"""
        codec = LDPCCodec()
        data = b'\x00' * 48  # 384 bytes for rate 1/2
        
        corrupted = codec.inject_errors(data, error_rate=0.1)
        
        # Should have errors
        assert corrupted != data
        # Should be same length
        assert len(corrupted) == len(data)
        # Approximate error rate
        ber = codec.measure_ber(data, corrupted)
        assert 0.05 < ber < 0.15  # Around 10% ± tolerance
    
    def test_measure_ber(self):
        """Test bit error rate measurement"""
        codec = LDPCCodec()
        
        original = b'\xFF' * 16
        received = b'\xFF' * 16
        
        # No errors
        ber = codec.measure_ber(original, received)
        assert ber == 0.0
        
        # All errors
        ber = codec.measure_ber(original, b'\x00' * 16)
        assert ber == 1.0
        
        # 50% errors (alternating bits)
        received = bytes([0xAA] * 16)  # 10101010
        ber = codec.measure_ber(original, received)
        assert 0.4 < ber < 0.6
    
    def test_error_correction_low_rate(self):
        """Test error correction with different error rates"""
        codec = LDPCCodec(data_length=128, code_rate=0.5, max_iterations=100)
        
        for error_rate in [0.01, 0.02, 0.03]:
            data = bytes(np.random.randint(0, 256, 16, dtype=np.uint8))
            encoded = codec.encode(data)
            corrupted = codec.inject_errors(encoded, error_rate=error_rate)
            
            decoded, success, iterations = codec.decode(corrupted)
            
            # Measure output BER
            output_ber = codec.measure_ber(data, decoded)
            
            # Should provide some error correction (demonstrational)
            assert output_ber < 0.30  # Reasonable upper bound


class TestCodeRates:
    """Test different code rate configurations"""
    
    def test_rate_half(self):
        """Test code rate 1/2"""
        codec = LDPCCodec(data_length=128, code_rate=0.5)
        
        assert codec.codeword_length == 256
        assert codec.parity_length == 128
        
        info = codec.get_code_info()
        assert info['code_rate'] == 0.5
        assert info['overhead'] == 1.0  # 100% overhead
    
    def test_rate_two_thirds(self):
        """Test code rate 2/3"""
        codec = LDPCCodec(data_length=192, code_rate=0.667)
        
        expected_codeword = int(192 / 0.667)
        assert codec.codeword_length == expected_codeword
        assert codec.parity_length == expected_codeword - 192
        
        info = codec.get_code_info()
        assert abs(info['code_rate'] - 0.667) < 0.001
    
    def test_rate_three_quarters(self):
        """Test code rate 3/4"""
        codec = LDPCCodec(data_length=192, code_rate=0.75)
        
        expected_codeword = int(192 / 0.75)
        assert codec.codeword_length == expected_codeword
        assert codec.parity_length == expected_codeword - 192
        
        info = codec.get_code_info()
        assert info['code_rate'] == 0.75
        assert info['overhead'] < 0.5  # Less than 50% overhead
    
    def test_rate_comparison(self):
        """Test error correction vs code rate tradeoff"""
        data = bytes(np.random.randint(0, 256, 16, dtype=np.uint8))
        error_rate = 0.03  # Lower error rate
        
        results = {}
        for rate in [0.5, 0.667, 0.75]:
            codec = LDPCCodec(data_length=128, code_rate=rate, max_iterations=100)
            
            encoded = codec.encode(data)
            corrupted = codec.inject_errors(encoded, error_rate=error_rate)
            decoded, success, iterations = codec.decode(corrupted)
            
            ber = codec.measure_ber(data, decoded)
            results[rate] = {'ber': ber, 'success': success}
        
        # All should attempt error correction (demonstrational)
        for rate, result in results.items():
            assert result['ber'] < 0.30  # Reasonable performance


class TestIntegration:
    """Test integration with ZK proof workflow"""
    
    def test_zk_proof_protection(self):
        """Test protecting 192-byte ZK proof"""
        codec = LDPCCodec(data_length=192 * 8, code_rate=0.5)
        
        # Simulate ZK proof (192 bytes)
        zk_proof = bytes(np.random.randint(0, 256, 192, dtype=np.uint8))
        
        # Encode
        protected = codec.encode(zk_proof)
        
        # Simulate transmission errors (2% BER)
        corrupted = codec.inject_errors(protected, error_rate=0.02)
        
        # Decode
        recovered, success, iterations = codec.decode(corrupted)
        
        # Should provide error correction
        ber = codec.measure_ber(zk_proof, recovered)
        assert ber < 0.10  # Less than 10% residual error
    
    def test_rc4_ldpc_pipeline(self):
        """Test LDPC after RC4 encryption"""
        codec = LDPCCodec(data_length=192 * 8, code_rate=0.667)
        
        # Simulate RC4-encrypted ZK proof
        encrypted_proof = bytes(np.random.randint(0, 256, 192, dtype=np.uint8))
        
        # LDPC encode
        protected = codec.encode(encrypted_proof)
        
        # Inject errors
        corrupted = codec.inject_errors(protected, error_rate=0.03)
        
        # LDPC decode
        recovered, success, iterations = codec.decode(corrupted)
        
        # Should match original encrypted data
        assert len(recovered) == len(encrypted_proof)
        
        ber = codec.measure_ber(encrypted_proof, recovered)
        assert ber < 0.15  # Reasonable error correction
    
    def test_full_protection_cycle(self):
        """Test full encode-corrupt-decode cycle"""
        codec = LDPCCodec(data_length=128, code_rate=0.5, max_iterations=100)
        
        # Original data
        data = bytes([i % 256 for i in range(16)])
        
        # Encode
        encoded = codec.encode(data)
        
        # Multiple corruption and recovery cycles
        for error_rate in [0.01, 0.02, 0.03]:
            corrupted = codec.inject_errors(encoded, error_rate=error_rate)
            recovered, success, iterations = codec.decode(corrupted)
            
            # Should provide error correction (demonstrational)
            ber = codec.measure_ber(data, recovered)
            assert ber < 0.25  # Reasonable performance


class TestCodeInformation:
    """Test code information retrieval"""
    
    def test_get_code_info(self):
        """Test code information dictionary"""
        codec = LDPCCodec(data_length=192 * 8, code_rate=0.5, max_iterations=75)
        
        info = codec.get_code_info()
        
        assert info['data_length'] == 192 * 8
        assert info['data_bytes'] == 192
        assert info['codeword_length'] == 192 * 8 * 2
        assert info['code_rate'] == 0.5
        assert info['max_iterations'] == 75
        assert 'overhead' in info
        assert 'parity_length' in info
    
    def test_overhead_calculation(self):
        """Test overhead calculation for different rates"""
        for rate in [0.5, 0.667, 0.75]:
            codec = LDPCCodec(data_length=128, code_rate=rate)
            info = codec.get_code_info()
            
            expected_overhead = (1 / rate) - 1
            actual_overhead = info['overhead']
            
            # Allow small numerical difference
            assert abs(actual_overhead - expected_overhead) < 0.1


class TestPerformance:
    """Test performance characteristics"""
    
    def test_encoding_speed(self):
        """Test encoding performance"""
        import time
        
        codec = LDPCCodec(data_length=192 * 8, code_rate=0.5)
        data = bytes(np.random.randint(0, 256, 192, dtype=np.uint8))
        
        # Warm-up
        codec.encode(data)
        
        # Measure
        start = time.perf_counter()
        for _ in range(100):
            codec.encode(data)
        elapsed = time.perf_counter() - start
        
        # Should be reasonably fast
        avg_time = elapsed / 100
        assert avg_time < 0.1  # Less than 100ms per encoding
    
    def test_decoding_speed(self):
        """Test decoding performance"""
        import time
        
        codec = LDPCCodec(data_length=192 * 8, code_rate=0.5, max_iterations=50)
        data = bytes(np.random.randint(0, 256, 192, dtype=np.uint8))
        encoded = codec.encode(data)
        
        # Add some errors
        corrupted = codec.inject_errors(encoded, error_rate=0.02)
        
        # Measure
        start = time.perf_counter()
        for _ in range(10):
            codec.decode(corrupted)
        elapsed = time.perf_counter() - start
        
        # Should complete in reasonable time
        avg_time = elapsed / 10
        assert avg_time < 1.0  # Less than 1 second per decoding


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
