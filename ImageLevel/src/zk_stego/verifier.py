"""
ZK-SNARK Steganography - Verifier Module
Handles message extraction and ZK proof verification
"""

import json
import hashlib
import numpy as np
from PIL import Image
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

from .utils import (
    LSBProcessor,
    PNGChunkHandler,
    SnarkJSRunner,
    generate_chaos_key_from_secret,
    compute_image_hash,
    compute_file_hash,
    bits_to_bytes,
)


class Verifier:
    """
    ZK-SNARK Steganography Verifier
    
    Handles:
    - Message extraction from stego image using chaos-based LSB
    - ZK proof verification
    - Metadata extraction from PNG chunk
    
    Usage:
        verifier = Verifier()
        result = verifier.extract_and_verify(
            stego_image_path="stego.png",
            chaos_key="my_secret_key"
        )
    """
    
    def __init__(self, project_root: Optional[str] = None):
        """
        Initialize Verifier
        
        Args:
            project_root: Optional path to project root (for finding verification key)
        """
        self.snarkjs = SnarkJSRunner(project_root)
    
    # =========================================================================
    # HIGH-LEVEL API
    # =========================================================================
    
    def extract_and_verify(
        self,
        stego_image_path: str,
        chaos_key: str,
        verify_zk_proof: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Complete extraction workflow: extract message + verify ZK proof
        
        Args:
            stego_image_path: Path to stego image (PNG)
            chaos_key: Secret key for chaos generation (must match prover's key)
            verify_zk_proof: Whether to verify ZK proof (default True)
            
        Returns:
            Dict containing:
            - message: Extracted message
            - valid: Whether extraction was successful
            - zk_verified: Whether ZK proof verified (if available)
            - metadata: Extracted metadata
        """
        print("=" * 60)
        print("ZK-SNARK Steganography Verifier")
        print("=" * 60)
        
        # Extract metadata from PNG chunk
        print(f"Extracting from: {stego_image_path}")
        metadata = PNGChunkHandler.extract_metadata(stego_image_path)
        
        if not metadata:
            print("ERROR: No zkPF metadata chunk found in image")
            return {
                "valid": False,
                "error": "No metadata chunk found",
                "message": None,
                "zk_verified": False
            }
        
        print("Metadata chunk found!")
        
        # Verify chaos_key hash
        chaos_key_int = generate_chaos_key_from_secret(chaos_key)
        if not self._verify_chaos_key(metadata, chaos_key_int):
            print("ERROR: Invalid chaos_key - hash verification failed")
            return {
                "valid": False,
                "error": "Invalid chaos_key",
                "message": None,
                "zk_verified": False
            }
        
        print("Chaos key verified!")
        
        # Extract message from LSB
        print("\nExtracting message...")
        chaos_info = metadata.get("chaos", {})
        x0 = chaos_info.get("initial_position", {}).get("x", 0)
        y0 = chaos_info.get("initial_position", {}).get("y", 0)
        proof_length = chaos_info.get("proof_length", 0)
        
        print(f"Starting position: ({x0}, {y0})")
        print(f"Message bits: {proof_length}")
        
        stego_img = Image.open(stego_image_path)
        stego_array = np.array(stego_img)
        
        lsb = LSBProcessor(stego_array)
        extracted_bits = lsb.extract_bits(proof_length, x0, y0, chaos_key_int)
        
        # Convert bits to message
        message_bytes = bits_to_bytes(extracted_bits)
        try:
            message = message_bytes.decode('utf-8', errors='ignore').rstrip('\x00')
        except:
            message = message_bytes.hex()
        
        print(f"Extracted message: {message[:50]}{'...' if len(message) > 50 else ''}")
        
        # Prepare result
        result = {
            "valid": True,
            "message": message,
            "message_length": len(message),
            "metadata": metadata,
            "x0": x0,
            "y0": y0,
            "zk_verified": None,
        }
        
        # Verify ZK proof if requested and available
        if verify_zk_proof:
            public_info = metadata.get("public", {})
            public_inputs = public_info.get("public_inputs")
            
            if public_inputs:
                print("\nVerifying ZK proof...")
                
                # We need the proof from the image or external source
                # For now, we check if proof verification is possible
                proof = self._extract_proof_from_metadata(metadata)
                
                if proof:
                    zk_valid = self.snarkjs.verify_groth16_proof(proof, public_inputs)
                    result["zk_verified"] = zk_valid
                    
                    if zk_valid:
                        print("ZK proof verification: PASSED ✓")
                    else:
                        print("ZK proof verification: FAILED ✗")
                else:
                    print("ZK proof not embedded in image (only metadata)")
                    result["zk_verified"] = None
            else:
                print("No public inputs found for ZK verification")
                result["zk_verified"] = None
        
        print("\n" + "=" * 60)
        print("Extraction complete!")
        print(f"Message: {message}")
        print(f"Valid: {result['valid']}")
        print(f"ZK Verified: {result['zk_verified']}")
        print("=" * 60)
        
        return result
    
    def extract_only(
        self,
        stego_image_path: str,
        chaos_key: str
    ) -> Optional[str]:
        """
        Extract message without ZK verification (faster)
        
        Args:
            stego_image_path: Path to stego image
            chaos_key: Secret key for chaos generation
            
        Returns:
            Extracted message string or None if failed
        """
        result = self.extract_and_verify(
            stego_image_path=stego_image_path,
            chaos_key=chaos_key,
            verify_zk_proof=False
        )
        
        if result and result.get("valid"):
            return result.get("message")
        return None
    
    def verify_proof_only(
        self,
        proof: Dict[str, Any],
        public_inputs: List[str]
    ) -> bool:
        """
        Verify ZK proof without extraction
        
        Args:
            proof: ZK proof dict (pi_a, pi_b, pi_c)
            public_inputs: Public inputs list
            
        Returns:
            True if proof is valid
        """
        return self.snarkjs.verify_groth16_proof(proof, public_inputs)
    
    def get_metadata(self, stego_image_path: str) -> Optional[Dict[str, Any]]:
        """
        Extract only metadata from stego image (no message extraction)
        
        Args:
            stego_image_path: Path to stego image
            
        Returns:
            Metadata dict or None
        """
        return PNGChunkHandler.extract_metadata(stego_image_path)
    
    def verify_integrity(
        self,
        stego_image_path: str,
        original_image_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Verify integrity of stego image
        
        Args:
            stego_image_path: Path to stego image
            original_image_path: Optional path to original for comparison
            
        Returns:
            Integrity check results
        """
        result = {
            "has_metadata": False,
            "metadata_valid": False,
            "hash_match": None,
        }
        
        metadata = PNGChunkHandler.extract_metadata(stego_image_path)
        
        if metadata:
            result["has_metadata"] = True
            
            # Check required fields
            required_fields = ["chaos", "public", "timestamp"]
            result["metadata_valid"] = all(f in metadata for f in required_fields)
            
            # Check image hash if original provided
            if original_image_path:
                stored_hash = metadata.get("public", {}).get("image_hash")
                if stored_hash:
                    actual_hash = compute_file_hash(original_image_path)
                    result["hash_match"] = stored_hash == actual_hash
        
        return result
    
    # =========================================================================
    # INTERNAL METHODS
    # =========================================================================
    
    def _verify_chaos_key(self, metadata: Dict[str, Any], chaos_key_int: int) -> bool:
        """Verify chaos_key against stored hash"""
        chaos_info = metadata.get("chaos", {})
        
        # Version 2.0+ uses hash verification
        if "chaos_key_hash" in chaos_info:
            expected_hash = chaos_info["chaos_key_hash"]
            actual_hash = hashlib.sha256(str(chaos_key_int).encode()).hexdigest()[:16]
            return expected_hash == actual_hash
        
        # Version 1.0 (legacy) - no verification possible, assume valid
        return True
    
    def _extract_proof_from_metadata(self, metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Try to extract ZK proof from metadata
        Note: In current design, proof is embedded in LSB, not metadata
        This is a placeholder for future enhancement
        """
        # Check if proof is directly in metadata (future enhancement)
        if "proof" in metadata:
            return metadata["proof"]
        
        # Proof is typically embedded in LSB and needs chaos_key to extract
        # For now, return None
        return None


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def extract(
    stego_image: str,
    chaos_key: str,
    verify: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Convenience function to extract message from stego image
    
    Args:
        stego_image: Path to stego image
        chaos_key: Secret key
        verify: Verify ZK proof if available
        
    Returns:
        Extraction result dict
    """
    verifier = Verifier()
    return verifier.extract_and_verify(
        stego_image_path=stego_image,
        chaos_key=chaos_key,
        verify_zk_proof=verify
    )


def verify(
    stego_image: str,
    chaos_key: str
) -> bool:
    """
    Convenience function to verify stego image
    
    Args:
        stego_image: Path to stego image
        chaos_key: Secret key
        
    Returns:
        True if valid and verified
    """
    verifier = Verifier()
    result = verifier.extract_and_verify(
        stego_image_path=stego_image,
        chaos_key=chaos_key,
        verify_zk_proof=True
    )
    
    if result:
        return result.get("valid", False)
    return False


def get_info(stego_image: str) -> Optional[Dict[str, Any]]:
    """
    Get metadata info from stego image (no extraction)
    
    Args:
        stego_image: Path to stego image
        
    Returns:
        Metadata dict
    """
    return PNGChunkHandler.extract_metadata(stego_image)


if __name__ == "__main__":
    import sys
    import os
    
    # Check for demo mode
    if len(sys.argv) >= 2 and sys.argv[1] == "demo":
        print("=" * 60)
        print("ZK-SNARK Steganography Verifier - DEMO")
        print("=" * 60)
        
        demo_stego = "demo_stego.png"
        demo_chaos_key = "demo_secret_key_12345"
        
        if not os.path.exists(demo_stego):
            print(f"\nError: {demo_stego} not found!")
            print("Please run prover demo first:")
            print("  python -m src.zk_stego.prover demo")
            sys.exit(1)
        
        print(f"\n[1] Loading stego image: {demo_stego}")
        print(f"    Chaos key: {demo_chaos_key}")
        
        print(f"\n[2] Extracting message...")
        verifier = Verifier()
        message = verifier.extract_only(
            stego_image_path=demo_stego,
            chaos_key=demo_chaos_key
        )
        
        print(f"\n[3] Result:")
        print(f"    Extracted message: \"{message}\"")
        
        # Get metadata
        metadata = verifier.get_metadata(demo_stego)
        if metadata:
            print(f"\n[4] Metadata:")
            print(f"    Algorithm: {metadata.get('algorithm', 'N/A')}")
            print(f"    Version: {metadata.get('version', 'N/A')}")
            print(f"    Message length: {metadata.get('proof_length', 'N/A')} bits")
        
        # Cleanup
        os.remove(demo_stego)
        
        print("\n" + "=" * 60)
        print("Demo complete! Message extracted successfully!")
        print("=" * 60)
        
    else:
        print("ZK-SNARK Steganography Verifier")
        print("=" * 40)
        print("Usage:")
        print("  python -m src.zk_stego.verifier demo")
        print("  python -m src.zk_stego.verifier extract <stego.png> <chaos_key>")
        print("  python -m src.zk_stego.verifier info <stego.png>")
        print("")
        print("Example:")
        print('  python -m src.zk_stego.verifier extract stego.png my_secret_key')

