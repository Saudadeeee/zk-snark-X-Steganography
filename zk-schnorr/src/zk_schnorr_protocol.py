#!/usr/bin/env python3


import hashlib
import secrets
import time
from typing import Tuple, Optional, Dict, Any
from dataclasses import dataclass
import json


@dataclass
class SchnorrProof:
    """Container for Schnorr ZK proof"""
    commitment: int  # R = r*G (commitment)
    challenge: int   # c = H(R || message)
    response: int    # s = r + c*x (response)
    message_hash: str
    timestamp: float
    proof_size_bytes: int
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'commitment': self.commitment,
            'challenge': self.challenge,
            'response': self.response,
            'message_hash': self.message_hash,
            'timestamp': self.timestamp,
            'proof_size_bytes': self.proof_size_bytes
        }
    
    def to_json(self) -> str:
        """Serialize to JSON"""
        return json.dumps(self.to_dict())
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'SchnorrProof':
        """Create from dictionary"""
        return SchnorrProof(**data)


class ZKSchnorrProtocol:

    
    def __init__(self, security_bits: int = 256):
        """
        Initialize ZK-Schnorr protocol
        
        Args:
            security_bits: Security level in bits (128, 192, 256)
        """
        self.security_bits = security_bits
        
        self.prime = self._get_safe_prime(security_bits)
        self.generator = 2  # Generator for the group
        
        # Private/Public key pair
        self.private_key: Optional[int] = None
        self.public_key: Optional[int] = None
        
        print(f"ZK-Schnorr Protocol initialized")
        print(f"Security level: {security_bits} bits")
        print(f"Prime modulus: {self.prime.bit_length()} bits")
    
    def _get_safe_prime(self, bits: int) -> int:
        """
        Get a safe prime for the given security level
        For demonstration - in production use standardized primes
        """
        if bits == 128:
            # 128-bit prime
            return 2**127 - 1  # Mersenne prime
        elif bits == 192:
            # 192-bit prime
            return 2**192 - 2**64 - 1
        else:  # 256 bits
            # 256-bit prime (secp256k1 order)
            return 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
    
    def generate_keypair(self) -> Tuple[int, int]:
        """
        Generate private/public key pair
        
        Returns:
            (private_key, public_key) where public_key = private_key * G
        """
        # Private key: random number in [1, prime-1]
        self.private_key = secrets.randbelow(self.prime - 1) + 1
        
        # Public key: private_key * G (mod prime)
        self.public_key = pow(self.generator, self.private_key, self.prime)
        
        return self.private_key, self.public_key
    
    def _hash_message(self, *components) -> int:
        """
        Hash multiple components using SHA-256
        Returns integer hash value
        """
        hasher = hashlib.sha256()
        for comp in components:
            if isinstance(comp, int):
                hasher.update(comp.to_bytes(32, byteorder='big'))
            elif isinstance(comp, str):
                hasher.update(comp.encode('utf-8'))
            else:
                hasher.update(str(comp).encode('utf-8'))
        
        digest = hasher.digest()
        return int.from_bytes(digest, byteorder='big') % self.prime
    
    def generate_proof(self, message: str) -> Tuple[SchnorrProof, float]:
        """
        Generate Schnorr zero-knowledge proof for a message
        
        Args:
            message: Message to prove knowledge of
            
        Returns:
            (proof, generation_time)
        """
        if self.private_key is None:
            raise ValueError("Must generate keypair first")
        
        start_time = time.perf_counter()
        nonce = secrets.randbelow(self.prime - 1) + 1
        
        commitment = pow(self.generator, nonce, self.prime)
        
        message_hash = hashlib.sha256(message.encode()).hexdigest()
        challenge = self._hash_message(commitment, message, self.public_key)
        
        response = (nonce + challenge * self.private_key) % (self.prime - 1)
        
        generation_time = time.perf_counter() - start_time
        proof_size = 32 + 32 + 32  #
        
        proof = SchnorrProof(
            commitment=commitment,
            challenge=challenge,
            response=response,
            message_hash=message_hash,
            timestamp=time.time(),
            proof_size_bytes=proof_size
        )
        
        return proof, generation_time
    
    def verify_proof(self, proof: SchnorrProof, message: str) -> Tuple[bool, float]:
        """
        Verify Schnorr zero-knowledge proof
        
        Args:
            proof: SchnorrProof to verify
            message: Original message
            
        Returns:
            (is_valid, verification_time)
        """
        if self.public_key is None:
            raise ValueError("Must have public key to verify")
        
        start_time = time.perf_counter()
        
        # Step 1: Recompute challenge
        expected_challenge = self._hash_message(
            proof.commitment, 
            message, 
            self.public_key
        )
        
        # Step 2: Check challenge matches
        if proof.challenge != expected_challenge:
            verification_time = time.perf_counter() - start_time
            return False, verification_time
        
        # Step 3: Verify equation: s*G = R + c*Y (mod prime)
        # Left side: s*G
        left = pow(self.generator, proof.response, self.prime)
        
        # Right side: R + c*Y = commitment * (public_key^challenge)
        right = (proof.commitment * pow(self.public_key, proof.challenge, self.prime)) % self.prime
        
        is_valid = (left == right)
        verification_time = time.perf_counter() - start_time
        
        return is_valid, verification_time
    
    def get_proof_size(self, proof: SchnorrProof) -> Dict[str, int]:
        """
        Get detailed proof size breakdown
        
        Returns:
            Dictionary with size components
        """
        return {
            'commitment_bytes': 32,
            'challenge_bytes': 32,
            'response_bytes': 32,
            'metadata_bytes': len(proof.message_hash) + 8,  # hash + timestamp
            'total_bytes': proof.proof_size_bytes,
            'total_kb': proof.proof_size_bytes / 1024
        }
    
    def benchmark_performance(self, message: str, iterations: int = 100) -> Dict[str, Any]:
        """
        Benchmark proof generation and verification
        
        Args:
            message: Test message
            iterations: Number of iterations
            
        Returns:
            Performance statistics
        """
        print(f"\nBenchmarking ZK-Schnorr protocol ({iterations} iterations)...")
        
        gen_times = []
        verify_times = []
        
        for i in range(iterations):
            # Generate proof
            proof, gen_time = self.generate_proof(message)
            gen_times.append(gen_time)
            
            # Verify proof
            is_valid, verify_time = self.verify_proof(proof, message)
            verify_times.append(verify_time)
            
            if not is_valid:
                print(f"Warning: Proof {i} failed verification!")
        
        import numpy as np
        
        stats = {
            'iterations': iterations,
            'message_length': len(message),
            'generation': {
                'mean_ms': np.mean(gen_times) * 1000,
                'std_ms': np.std(gen_times) * 1000,
                'min_ms': np.min(gen_times) * 1000,
                'max_ms': np.max(gen_times) * 1000,
            },
            'verification': {
                'mean_ms': np.mean(verify_times) * 1000,
                'std_ms': np.std(verify_times) * 1000,
                'min_ms': np.min(verify_times) * 1000,
                'max_ms': np.max(verify_times) * 1000,
            },
            'proof_size': self.get_proof_size(proof),
            'success_rate': sum(1 for t in verify_times if t > 0) / iterations
        }
        
        print(f"Generation: {stats['generation']['mean_ms']:.3f} ± {stats['generation']['std_ms']:.3f} ms")
        print(f"Verification: {stats['verification']['mean_ms']:.3f} ± {stats['verification']['std_ms']:.3f} ms")
        print(f"Proof size: {stats['proof_size']['total_bytes']} bytes")
        
        return stats


def demo_zk_schnorr():
    """Demonstration of ZK-Schnorr protocol"""
    
    print("="*70)
    print("ZK-Schnorr Protocol Demonstration")
    print("="*70)
    
    # Initialize protocol
    schnorr = ZKSchnorrProtocol(security_bits=256)
    
    # Generate keypair
    print("\n1. Generating keypair...")
    private_key, public_key = schnorr.generate_keypair()
    print(f"   Private key: {private_key} (kept secret)")
    print(f"   Public key: {public_key}")
    
    # Create a message
    message = "This is a secret message hidden in steganography!"
    print(f"\n2. Message: '{message}'")
    
    # Generate proof
    print("\n3. Generating ZK proof...")
    proof, gen_time = schnorr.generate_proof(message)
    print(f"   Generation time: {gen_time*1000:.3f} ms")
    print(f"   Proof size: {proof.proof_size_bytes} bytes")
    print(f"   Commitment: {proof.commitment}")
    print(f"   Challenge: {proof.challenge}")
    print(f"   Response: {proof.response}")
    
    # Verify proof
    print("\n4. Verifying proof...")
    is_valid, verify_time = schnorr.verify_proof(proof, message)
    print(f"   Verification time: {verify_time*1000:.3f} ms")
    print(f"   Proof valid: {is_valid}")
    
    # Try with wrong message
    print("\n5. Testing with wrong message...")
    wrong_message = "This is a different message"
    is_valid_wrong, _ = schnorr.verify_proof(proof, wrong_message)
    print(f"   Proof valid: {is_valid_wrong} (should be False)")
    
    # Benchmark
    print("\n6. Running performance benchmark...")
    stats = schnorr.benchmark_performance(message, iterations=100)
    
    print("\n" + "="*70)
    print("Demonstration complete!")
    print("="*70)


if __name__ == "__main__":
    demo_zk_schnorr()
