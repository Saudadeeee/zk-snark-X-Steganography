"""
Unit tests for RC4 Stream Cipher

Tests:
- KSA initialization
- PRGA keystream generation
- Encrypt/decrypt round-trip
- Entropy measurement
- ZK proof data encryption
- Test vectors validation
"""

import unittest
import numpy as np
from src.zk_mv_stego.crypto.rc4_cipher import (
    RC4Cipher,
    encrypt_data,
    decrypt_data,
    measure_entropy
)


class TestRC4Cipher(unittest.TestCase):
    """Test RC4 implementation"""
    
    def setUp(self):
        """Initialize test fixtures"""
        self.test_key = b'test_key_128bit!'  # 16 bytes
        self.cipher = RC4Cipher(self.test_key)
    
    def test_initialization_valid_key(self):
        """Test RC4 initialization with valid key"""
        cipher = RC4Cipher(b'valid_key')
        
        # State should be initialized
        self.assertIsNotNone(cipher.S)
        self.assertEqual(len(cipher.S), 256)
        
        # State should be a permutation of 0-255
        sorted_state = np.sort(cipher.S)
        expected = np.arange(256, dtype=np.uint8)
        np.testing.assert_array_equal(sorted_state, expected)
    
    def test_initialization_empty_key(self):
        """Test RC4 with empty key (should fail)"""
        with self.assertRaises(ValueError) as ctx:
            RC4Cipher(b'')
        
        self.assertIn('empty', str(ctx.exception).lower())
    
    def test_initialization_short_key(self):
        """Test RC4 with very short key (should warn)"""
        with self.assertRaises(ValueError) as ctx:
            RC4Cipher(b'ab')  # Only 2 bytes
        
        self.assertIn('too short', str(ctx.exception).lower())
    
    def test_initialization_different_types(self):
        """Test RC4 with different input types"""
        # Bytes
        c1 = RC4Cipher(b'test_key')
        self.assertIsNotNone(c1.S)
        
        # Bytearray
        c2 = RC4Cipher(bytearray(b'test_key'))
        self.assertIsNotNone(c2.S)
        
        # List of integers
        c3 = RC4Cipher([116, 101, 115, 116])  # 'test'
        self.assertIsNotNone(c3.S)
    
    def test_encrypt_decrypt_roundtrip(self):
        """Test encryption followed by decryption"""
        plaintext = b'Hello, World! This is a test message.'
        
        # Encrypt
        ciphertext = self.cipher.encrypt(plaintext)
        
        # Ciphertext should be different from plaintext
        self.assertNotEqual(plaintext, ciphertext)
        self.assertEqual(len(plaintext), len(ciphertext))
        
        # Decrypt
        decrypted = self.cipher.decrypt(ciphertext)
        
        # Should recover original plaintext
        self.assertEqual(plaintext, decrypted)
    
    def test_encrypt_different_types(self):
        """Test encryption with different input types"""
        plaintext_bytes = b'test'
        plaintext_list = [116, 101, 115, 116]  # 'test'
        plaintext_bytearray = bytearray(b'test')
        
        # All should produce same ciphertext
        ct1 = self.cipher.encrypt(plaintext_bytes)
        
        # Create new ciphers to ensure same state
        cipher2 = RC4Cipher(self.test_key)
        ct2 = cipher2.encrypt(plaintext_list)
        
        cipher3 = RC4Cipher(self.test_key)
        ct3 = cipher3.encrypt(plaintext_bytearray)
        
        self.assertEqual(ct1, ct2)
        self.assertEqual(ct1, ct3)
    
    def test_same_key_produces_same_output(self):
        """Test that same key produces same encryption"""
        plaintext = b'consistent encryption test'
        
        cipher1 = RC4Cipher(self.test_key)
        ct1 = cipher1.encrypt(plaintext)
        
        cipher2 = RC4Cipher(self.test_key)
        ct2 = cipher2.encrypt(plaintext)
        
        # Same key should produce same ciphertext
        self.assertEqual(ct1, ct2)
    
    def test_different_keys_produce_different_output(self):
        """Test that different keys produce different encryption"""
        plaintext = b'different keys test'
        
        cipher1 = RC4Cipher(b'key_one_16bytes!')
        ct1 = cipher1.encrypt(plaintext)
        
        cipher2 = RC4Cipher(b'key_two_16bytes!')
        ct2 = cipher2.encrypt(plaintext)
        
        # Different keys should produce different ciphertext
        self.assertNotEqual(ct1, ct2)
    
    def test_empty_data(self):
        """Test encryption of empty data"""
        plaintext = b''
        
        ciphertext = self.cipher.encrypt(plaintext)
        
        # Empty input should produce empty output
        self.assertEqual(ciphertext, b'')
        
        # Decrypt should also return empty
        decrypted = self.cipher.decrypt(ciphertext)
        self.assertEqual(decrypted, b'')
    
    def test_large_data(self):
        """Test encryption of large data (>1KB)"""
        # Generate 10KB of random data
        plaintext = np.random.bytes(10240)
        
        # Encrypt
        ciphertext = self.cipher.encrypt(plaintext)
        
        # Verify
        self.assertEqual(len(plaintext), len(ciphertext))
        
        # Decrypt
        decrypted = self.cipher.decrypt(ciphertext)
        self.assertEqual(plaintext, decrypted)
    
    def test_zk_proof_data(self):
        """Test encryption of ZK-SNARK proof data (192 bytes)"""
        # Simulate ZK proof: 2 G1 points (64 bytes each) + 1 G2 point (64 bytes)
        zk_proof = np.random.bytes(192)
        
        # Encrypt
        encrypted_proof = self.cipher.encrypt(zk_proof)
        
        # Verify size
        self.assertEqual(len(encrypted_proof), 192)
        
        # Decrypt and verify
        decrypted_proof = self.cipher.decrypt(encrypted_proof)
        self.assertEqual(zk_proof, decrypted_proof)
    
    def test_entropy_plaintext_low(self):
        """Test entropy of low-entropy data"""
        # Repeated pattern (very low entropy)
        low_entropy_data = b'AAAAAAAAAA' * 100
        
        entropy = self.cipher.compute_entropy(low_entropy_data)
        
        # Should be very low (close to 0)
        self.assertLess(entropy, 1.0)
    
    def test_entropy_encrypted_high(self):
        """Test entropy of encrypted data (should be high)"""
        # Low-entropy plaintext
        plaintext = b'AAAAAAAAAA' * 100
        
        # Encrypt
        ciphertext = self.cipher.encrypt(plaintext)
        
        # Measure entropy
        entropy = self.cipher.compute_entropy(ciphertext)
        
        # Encrypted data should have high entropy (>7.9 bits/byte target)
        self.assertGreater(entropy, 7.5)
        self.assertLessEqual(entropy, 8.0)
    
    def test_entropy_random_data(self):
        """Test entropy of truly random data"""
        # Generate random data
        random_data = np.random.bytes(1000)
        
        entropy = self.cipher.compute_entropy(random_data)
        
        # Should be close to maximum (8.0)
        # Note: Real random data typically 7.8-8.0
        self.assertGreater(entropy, 7.7)
    
    def test_entropy_empty_data(self):
        """Test entropy of empty data"""
        entropy = self.cipher.compute_entropy(b'')
        
        # Should be 0
        self.assertEqual(entropy, 0.0)
    
    def test_entropy_single_byte(self):
        """Test entropy of single repeated byte"""
        data = b'A' * 1000
        
        entropy = self.cipher.compute_entropy(data)
        
        # Should be 0 (only one symbol)
        self.assertEqual(entropy, 0.0)
    
    def test_entropy_two_bytes_equal(self):
        """Test entropy of two equally distributed bytes"""
        # 50% A, 50% B
        data = b'AB' * 500
        
        entropy = self.cipher.compute_entropy(data)
        
        # Should be 1.0 (log2(2) = 1)
        self.assertAlmostEqual(entropy, 1.0, places=5)
    
    def test_generate_key(self):
        """Test random key generation"""
        # Generate 16-byte key
        key = RC4Cipher.generate_key(16)
        
        self.assertEqual(len(key), 16)
        self.assertIsInstance(key, bytes)
        
        # Generate 32-byte key
        key32 = RC4Cipher.generate_key(32)
        self.assertEqual(len(key32), 32)
    
    def test_convenience_functions(self):
        """Test convenience encrypt/decrypt functions"""
        plaintext = b'convenience function test'
        key = b'shared_key_16bit'
        
        # Encrypt
        ciphertext = encrypt_data(plaintext, key)
        
        # Decrypt
        decrypted = decrypt_data(ciphertext, key)
        
        self.assertEqual(plaintext, decrypted)
    
    def test_measure_entropy_function(self):
        """Test convenience entropy measurement function"""
        random_data = np.random.bytes(1000)
        
        entropy = measure_entropy(random_data)
        
        # Should be high
        self.assertGreater(entropy, 7.5)
    
    def test_known_vector_1(self):
        """Test with known RC4 test vector"""
        # Test vector from Wikipedia
        key = b'Key'
        plaintext = b'Plaintext'
        
        cipher = RC4Cipher(key)
        ciphertext = cipher.encrypt(plaintext)
        
        # Known output (in hex): BBF316E8D940AF0AD3
        expected = bytes.fromhex('BBF316E8D940AF0AD3')
        
        self.assertEqual(ciphertext, expected)
    
    def test_known_vector_2(self):
        """Test with known RC4 test vector (RFC 6229)"""
        # Test vector: key = all zeros, output first 16 bytes
        key = bytes([0] * 16)
        plaintext = bytes([0] * 16)
        
        cipher = RC4Cipher(key)
        keystream = cipher.encrypt(plaintext)
        
        # Known keystream (first 16 bytes)
        # de 18 89 41 a3 37 5d 3a 8a 06 1e 67 57 6e 92 6d
        expected = bytes.fromhex('de188941a3375d3a8a061e67576e926d')
        
        self.assertEqual(keystream, expected)
    
    def test_state_independence(self):
        """Test that multiple encryptions don't affect state"""
        plaintext1 = b'first message'
        plaintext2 = b'second message'
        
        # Encrypt first message
        cipher = RC4Cipher(self.test_key)
        ct1_first = cipher.encrypt(plaintext1)
        
        # Encrypt second message with same cipher
        ct2 = cipher.encrypt(plaintext2)
        
        # Create new cipher and encrypt first message again
        cipher_new = RC4Cipher(self.test_key)
        ct1_second = cipher_new.encrypt(plaintext1)
        
        # Should produce same ciphertext
        self.assertEqual(ct1_first, ct1_second)
    
    def test_performance_benchmark(self):
        """Benchmark RC4 encryption speed"""
        import time
        
        # Test data: 1MB
        plaintext = np.random.bytes(1024 * 1024)
        
        # Measure encryption time
        start = time.perf_counter()
        
        iterations = 10  # Reduced for reasonable test time
        for _ in range(iterations):
            cipher = RC4Cipher(self.test_key)
            _ = cipher.encrypt(plaintext)
        
        elapsed = time.perf_counter() - start
        avg_time_ms = (elapsed / iterations) * 1000
        throughput_mbps = (len(plaintext) * iterations) / elapsed / (1024 * 1024)
        
        print(f"\nRC4 Performance:")
        print(f"  Avg time: {avg_time_ms:.3f} ms/MB")
        print(f"  Throughput: {throughput_mbps:.1f} MB/sec")
        
        # RC4 in Python is relatively slow (~1-2 MB/sec is expected)
        # For production, use C extension or Cython
        self.assertLess(avg_time_ms, 2000)  # Less than 2s per MB


if __name__ == '__main__':
    unittest.main()
