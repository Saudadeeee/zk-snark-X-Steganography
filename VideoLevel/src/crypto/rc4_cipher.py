"""
RC4 Stream Cipher Implementation

Key Scheduling Algorithm (KSA) + Pseudo-Random Generation Algorithm (PRGA)
Used to encrypt ZK-SNARK proof data before embedding into video

Security Notes:
- RC4 is used here for entropy improvement, NOT for cryptographic security
- Purpose: Make embedded data look more random (entropy > 7.9 bits/byte)
- Key size: 128-256 bits recommended
- DO NOT use for actual encryption in production (use AES-GCM instead)

Reference: RFC 7465 (RC4 Cipher Suites Prohibition)
Use case: Steganography data randomization only
"""

import numpy as np
from typing import Union, List


class RC4Cipher:
    """
    RC4 stream cipher for data randomization
    
    Usage:
        cipher = RC4Cipher(key=b'secret_key_128bit')
        encrypted = cipher.encrypt(plaintext_bytes)
        decrypted = cipher.decrypt(encrypted)
    """
    
    def __init__(self, key: Union[bytes, bytearray, List[int]]):
        """
        Initialize RC4 with given key
        
        Args:
            key: Encryption key (16-32 bytes recommended)
        
        Raises:
            ValueError: If key is empty or too short
        """
        if isinstance(key, list):
            key = bytes(key)
        elif isinstance(key, bytearray):
            key = bytes(key)
        
        if len(key) == 0:
            raise ValueError("Key cannot be empty")
        
        # Relaxed key length check (allow short keys for test vectors)
        if len(key) < 3:
            raise ValueError("Key too short (minimum 3 bytes)")
        
        self.key = key
        self.S = None  # State array
        self._initialize_state()
    
    def _initialize_state(self):
        """
        Key Scheduling Algorithm (KSA)
        
        Initializes the permutation S using the key
        """
        # Initialize state array S = [0, 1, 2, ..., 255]
        self.S = np.arange(256, dtype=np.uint8)
        
        key_length = len(self.key)
        j = 0
        
        # KSA main loop
        for i in range(256):
            # j = (j + S[i] + key[i mod key_length]) mod 256
            j = (j + int(self.S[i]) + self.key[i % key_length]) % 256
            
            # Swap S[i] and S[j]
            self.S[i], self.S[j] = self.S[j], self.S[i]
    
    def _generate_keystream(self, length: int) -> bytes:
        """
        Pseudo-Random Generation Algorithm (PRGA)
        
        Generates keystream bytes for encryption/decryption
        
        Args:
            length: Number of keystream bytes to generate
        
        Returns:
            Keystream bytes
        """
        # Make a copy of state for this encryption
        S = self.S.copy()
        keystream = bytearray(length)
        
        i = 0
        j = 0
        
        for k in range(length):
            # i = (i + 1) mod 256
            i = (i + 1) % 256
            
            # j = (j + S[i]) mod 256
            j = (j + int(S[i])) % 256
            
            # Swap S[i] and S[j]
            S[i], S[j] = S[j], S[i]
            
            # Output = S[(S[i] + S[j]) mod 256]
            t = (int(S[i]) + int(S[j])) % 256
            keystream[k] = S[t]
        
        return bytes(keystream)
    
    def encrypt(self, plaintext: Union[bytes, bytearray, List[int]]) -> bytes:
        """
        Encrypt plaintext using RC4
        
        Args:
            plaintext: Data to encrypt
        
        Returns:
            Encrypted ciphertext
        """
        if isinstance(plaintext, list):
            plaintext = bytes(plaintext)
        elif isinstance(plaintext, bytearray):
            plaintext = bytes(plaintext)
        
        # Generate keystream
        keystream = self._generate_keystream(len(plaintext))
        
        # XOR plaintext with keystream
        ciphertext = bytes([p ^ k for p, k in zip(plaintext, keystream)])
        
        return ciphertext
    
    def decrypt(self, ciphertext: Union[bytes, bytearray, List[int]]) -> bytes:
        """
        Decrypt ciphertext using RC4
        
        Note: RC4 encryption and decryption are identical (XOR is symmetric)
        
        Args:
            ciphertext: Data to decrypt
        
        Returns:
            Decrypted plaintext
        """
        # RC4 decryption is identical to encryption (XOR property)
        return self.encrypt(ciphertext)
    
    def compute_entropy(self, data: Union[bytes, bytearray, List[int]]) -> float:
        """
        Compute Shannon entropy of data
        
        Entropy formula: H(X) = -Σ P(x) * log2(P(x))
        
        Args:
            data: Byte sequence to analyze
        
        Returns:
            Entropy in bits per byte (0.0 - 8.0)
        """
        if isinstance(data, (list, bytearray)):
            data = bytes(data)
        
        if len(data) == 0:
            return 0.0
        
        # Count byte frequencies
        freq = np.bincount(np.frombuffer(data, dtype=np.uint8), minlength=256)
        
        # Calculate probabilities
        probabilities = freq / len(data)
        
        # Remove zero probabilities
        probabilities = probabilities[probabilities > 0]
        
        # Shannon entropy: -Σ p * log2(p)
        entropy = -np.sum(probabilities * np.log2(probabilities))
        
        return float(entropy)
    
    @staticmethod
    def generate_key(size: int = 16) -> bytes:
        """
        Generate random key for RC4
        
        Args:
            size: Key size in bytes (default: 16 = 128 bits)
        
        Returns:
            Random key bytes
        """
        return np.random.bytes(size)


# Convenience functions

def encrypt_data(data: bytes, key: bytes) -> bytes:
    """
    Quick encrypt function
    
    Args:
        data: Plaintext to encrypt
        key: Encryption key
    
    Returns:
        Ciphertext
    """
    cipher = RC4Cipher(key)
    return cipher.encrypt(data)


def decrypt_data(data: bytes, key: bytes) -> bytes:
    """
    Quick decrypt function
    
    Args:
        data: Ciphertext to decrypt
        key: Decryption key
    
    Returns:
        Plaintext
    """
    cipher = RC4Cipher(key)
    return cipher.decrypt(data)


def measure_entropy(data: bytes) -> float:
    """
    Quick entropy measurement
    
    Args:
        data: Data to analyze
    
    Returns:
        Shannon entropy (bits/byte)
    """
    cipher = RC4Cipher(b'dummy')  # Key not needed for entropy
    return cipher.compute_entropy(data)
