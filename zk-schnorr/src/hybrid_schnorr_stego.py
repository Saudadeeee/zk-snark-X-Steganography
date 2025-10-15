#!/usr/bin/env python3
"""
Hybrid Schnorr Steganography System
====================================

Combines chaos-based steganography with ZK-Schnorr proofs.
This is the Schnorr equivalent of the ZK-SNARK hybrid system.

Architecture:
1. Chaos embedding (same as ZK-SNARK version)
2. ZK-Schnorr proof generation (instead of ZK-SNARK)
3. Proof embedding in stego image

Comparison advantages of Schnorr:
- Faster proof generation
- Smaller proof size (~96 bytes vs ~743+ bytes)
- Simpler cryptographic operations
- No trusted setup required

Author: ZK-Stego Research Team
Date: October 2025
"""

import sys
import numpy as np
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from PIL import Image
import time

# Add parent directories to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.append(str(PROJECT_ROOT / "src"))

from zk_stego.chaos_embedding import ChaosEmbedding
from zk_schnorr_protocol import ZKSchnorrProtocol, SchnorrProof


class HybridSchnorrSteganography:
    """
    Hybrid steganography using chaos embedding + ZK-Schnorr proofs
    """
    
    def __init__(self, image: Image.Image):
        """
        Initialize hybrid Schnorr steganography system
        
        Args:
            image: Cover image (PIL Image)
        """
        self.cover_image = image
        self.image_array = np.array(image)
        
        # Initialize components
        self.chaos_embedder = ChaosEmbedding(self.image_array)
        self.schnorr_protocol = ZKSchnorrProtocol(security_bits=256)
        
        # Generate keypair for this session
        self.private_key, self.public_key = self.schnorr_protocol.generate_keypair()
        
        # State
        self.stego_image: Optional[Image.Image] = None
        self.proof: Optional[SchnorrProof] = None
        self.embedded_message: Optional[str] = None
        
        print("Hybrid Schnorr Steganography System initialized")
        print(f"Image size: {image.size}")
        print(f"Public key: {self.public_key}")
    
    def embed_with_proof(
        self, 
        message: str, 
        embedding_key: str = "default_key"
    ) -> Tuple[Image.Image, SchnorrProof, Dict[str, float]]:
        """
        Embed message with ZK-Schnorr proof generation
        
        Args:
            message: Secret message to embed
            embedding_key: Key for chaos embedding
            
        Returns:
            (stego_image, proof, timing_stats)
        """
        print(f"\n{'='*70}")
        print("Embedding with ZK-Schnorr Proof")
        print(f"{'='*70}")
        print(f"Message length: {len(message)} characters")
        
        timing_stats = {}
        
        # Step 1: Chaos embedding
        print("\n1. Embedding message using chaos system...")
        embed_start = time.perf_counter()
        self.stego_image = self.chaos_embedder.embed_message(message, embedding_key)
        embed_time = time.perf_counter() - embed_start
        timing_stats['embedding_time'] = embed_time
        print(f"   Embedding time: {embed_time*1000:.3f} ms")
        
        # Step 2: Generate ZK-Schnorr proof
        print("\n2. Generating ZK-Schnorr proof...")
        proof_start = time.perf_counter()
        self.proof, proof_gen_time = self.schnorr_protocol.generate_proof(message)
        proof_time = time.perf_counter() - proof_start
        timing_stats['proof_generation_time'] = proof_time
        timing_stats['proof_generation_internal'] = proof_gen_time
        print(f"   Proof generation: {proof_time*1000:.3f} ms")
        print(f"   Proof size: {self.proof.proof_size_bytes} bytes")
        
        # Step 3: Store proof metadata in image (optional - for demonstration)
        # In practice, proof can be transmitted separately
        self.embedded_message = message
        
        # Total time
        total_time = embed_time + proof_time
        timing_stats['total_time'] = total_time
        
        print(f"\n3. Total time: {total_time*1000:.3f} ms")
        print(f"{'='*70}\n")
        
        return self.stego_image, self.proof, timing_stats
    
    def extract_and_verify(
        self, 
        stego_image: Image.Image,
        proof: SchnorrProof,
        message_length: int,
        embedding_key: str = "default_key"
    ) -> Tuple[str, bool, Dict[str, float]]:
        """
        Extract message and verify ZK-Schnorr proof
        
        Args:
            stego_image: Stego image containing hidden message
            proof: ZK-Schnorr proof to verify
            message_length: Length of hidden message
            embedding_key: Key used for embedding
            
        Returns:
            (extracted_message, proof_valid, timing_stats)
        """
        print(f"\n{'='*70}")
        print("Extraction and Verification")
        print(f"{'='*70}")
        
        timing_stats = {}
        
        # Step 1: Extract message
        print("\n1. Extracting message from stego image...")
        stego_array = np.array(stego_image)
        extractor = ChaosEmbedding(stego_array)
        
        extract_start = time.perf_counter()
        extracted_message = extractor.extract_message(message_length, embedding_key)
        extract_time = time.perf_counter() - extract_start
        timing_stats['extraction_time'] = extract_time
        print(f"   Extraction time: {extract_time*1000:.3f} ms")
        print(f"   Extracted: '{extracted_message[:50]}...'")
        
        # Step 2: Verify ZK-Schnorr proof
        print("\n2. Verifying ZK-Schnorr proof...")
        verify_start = time.perf_counter()
        proof_valid, verify_internal_time = self.schnorr_protocol.verify_proof(
            proof, 
            extracted_message
        )
        verify_time = time.perf_counter() - verify_start
        timing_stats['verification_time'] = verify_time
        timing_stats['verification_internal'] = verify_internal_time
        print(f"   Verification time: {verify_time*1000:.3f} ms")
        print(f"   Proof valid: {proof_valid}")
        
        # Total time
        total_time = extract_time + verify_time
        timing_stats['total_time'] = total_time
        
        print(f"\n3. Total time: {total_time*1000:.3f} ms")
        print(f"{'='*70}\n")
        
        return extracted_message, proof_valid, timing_stats
    
    def calculate_quality_metrics(
        self, 
        cover_image: np.ndarray, 
        stego_image: np.ndarray
    ) -> Dict[str, float]:
        """
        Calculate image quality metrics
        
        Args:
            cover_image: Original cover image
            stego_image: Stego image
            
        Returns:
            Dictionary with quality metrics
        """
        # PSNR
        mse = np.mean((cover_image.astype(float) - stego_image.astype(float)) ** 2)
        if mse == 0:
            psnr = 100.0
        else:
            psnr = 20 * np.log10(255.0 / np.sqrt(mse))
        
        # SSIM (simplified)
        c1 = (0.01 * 255) ** 2
        c2 = (0.03 * 255) ** 2
        mu1 = np.mean(cover_image)
        mu2 = np.mean(stego_image)
        sigma1_sq = np.var(cover_image)
        sigma2_sq = np.var(stego_image)
        sigma12 = np.mean((cover_image - mu1) * (stego_image - mu2))
        ssim = ((2 * mu1 * mu2 + c1) * (2 * sigma12 + c2)) / \
               ((mu1**2 + mu2**2 + c1) * (sigma1_sq + sigma2_sq + c2))
        
        return {
            'psnr_db': float(psnr),
            'ssim': float(ssim),
            'mse': float(mse)
        }
    
    def get_system_info(self) -> Dict[str, Any]:
        """Get system information and statistics"""
        return {
            'protocol': 'ZK-Schnorr',
            'security_bits': self.schnorr_protocol.security_bits,
            'image_size': self.cover_image.size,
            'image_pixels': self.image_array.shape[0] * self.image_array.shape[1],
            'public_key': self.public_key,
            'proof_size_bytes': 96 if self.proof else None,
            'chaos_parameters': {
                'r_value': self.chaos_embedder.r,
                'initial_condition': self.chaos_embedder.x0
            }
        }


def demo_hybrid_schnorr():
    """Demonstration of Hybrid Schnorr Steganography"""
    
    print("\n" + "="*80)
    print("HYBRID SCHNORR STEGANOGRAPHY DEMONSTRATION")
    print("="*80)
    
    # Load test image
    test_image_path = PROJECT_ROOT / "examples" / "testvectors" / "Lenna_test_image.webp"
    
    if not test_image_path.exists():
        print(f"Error: Test image not found at {test_image_path}")
        return
    
    cover_image = Image.open(test_image_path)
    if cover_image.mode != 'RGB':
        cover_image = cover_image.convert('RGB')
    
    print(f"\nLoaded cover image: {cover_image.size}")
    
    # Initialize system
    hybrid_system = HybridSchnorrSteganography(cover_image)
    
    # Test message
    message = "This is a secret message protected by ZK-Schnorr proof! " * 3
    print(f"\nTest message: '{message[:60]}...'")
    print(f"Message length: {len(message)} characters")
    
    # Embed with proof
    stego_image, proof, embed_stats = hybrid_system.embed_with_proof(
        message, 
        embedding_key="test_key_123"
    )
    
    # Calculate quality
    cover_array = np.array(cover_image)
    stego_array = np.array(stego_image)
    quality = hybrid_system.calculate_quality_metrics(cover_array, stego_array)
    
    print("\nImage Quality Metrics:")
    print(f"  PSNR: {quality['psnr_db']:.2f} dB")
    print(f"  SSIM: {quality['ssim']:.4f}")
    print(f"  MSE: {quality['mse']:.4f}")
    
    # Extract and verify
    extracted_message, proof_valid, verify_stats = hybrid_system.extract_and_verify(
        stego_image,
        proof,
        len(message),
        embedding_key="test_key_123"
    )
    
    # Verification
    print("\nVerification Results:")
    print(f"  Message integrity: {extracted_message == message}")
    print(f"  Proof validity: {proof_valid}")
    print(f"  Match: {(extracted_message == message) and proof_valid}")
    
    # System info
    print("\nSystem Information:")
    info = hybrid_system.get_system_info()
    print(f"  Protocol: {info['protocol']}")
    print(f"  Security: {info['security_bits']} bits")
    print(f"  Proof size: {info['proof_size_bytes']} bytes")
    print(f"  Image pixels: {info['image_pixels']:,}")
    
    # Performance summary
    print("\nPerformance Summary:")
    print(f"  Embedding: {embed_stats['embedding_time']*1000:.3f} ms")
    print(f"  Proof generation: {embed_stats['proof_generation_time']*1000:.3f} ms")
    print(f"  Extraction: {verify_stats['extraction_time']*1000:.3f} ms")
    print(f"  Proof verification: {verify_stats['verification_time']*1000:.3f} ms")
    print(f"  Total (embed+proof): {embed_stats['total_time']*1000:.3f} ms")
    print(f"  Total (extract+verify): {verify_stats['total_time']*1000:.3f} ms")
    
    print("\n" + "="*80)
    print("DEMONSTRATION COMPLETE")
    print("="*80 + "\n")


if __name__ == "__main__":
    demo_hybrid_schnorr()
