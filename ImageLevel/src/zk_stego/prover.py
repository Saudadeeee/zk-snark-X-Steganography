"""
ZK-SNARK Steganography - Prover Module
Handles message embedding and ZK proof generation
"""

import json
import time
import numpy as np
from PIL import Image
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

from .utils import (
    ChaosGenerator,
    LSBProcessor,
    PNGChunkHandler,
    SnarkJSRunner,
    generate_chaos_key_from_secret,
    generate_random_chaos_key,
    compute_image_hash,
    compute_file_hash,
    extract_feature_point,
    message_to_bits,
    bytes_to_bits,
    hash_to_field_elements,
)


class Prover:
    """
    ZK-SNARK Steganography Prover
    
    Handles:
    - Message embedding into cover image using chaos-based LSB
    - ZK proof generation for proving correct embedding
    - PNG chunk metadata embedding
    
    Usage:
        prover = Prover()
        result = prover.embed_and_prove(
            cover_image_path="cover.png",
            output_path="stego.png", 
            message="Secret message",
            chaos_key="my_secret_key"
        )
    """
    
    def __init__(self, project_root: Optional[str] = None):
        """
        Initialize Prover
        
        Args:
            project_root: Optional path to project root (for finding circuit files)
        """
        self.snarkjs = SnarkJSRunner(project_root)
        self.chunk_handler = PNGChunkHandler()
    
    # =========================================================================
    # HIGH-LEVEL API
    # =========================================================================
    
    def embed_and_prove(
        self,
        cover_image_path: str,
        output_path: str,
        message: str,
        chaos_key: Optional[str] = None,
        x0: Optional[int] = None,
        y0: Optional[int] = None,
        generate_zk_proof: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Complete embedding workflow: embed message + generate ZK proof
        
        Args:
            cover_image_path: Path to cover image (PNG)
            output_path: Path for output stego image
            message: Message to embed (private input)
            chaos_key: Secret key for chaos generation (private input)
                      If None, generates a new random key
            x0, y0: Optional starting position (auto-detected if None)
            generate_zk_proof: Whether to generate ZK proof (default True)
            
        Returns:
            Dict containing:
            - stego_image_path: Path to stego image
            - chaos_key: The chaos key used (SAVE THIS!)
            - proof: ZK proof (if generated)
            - public_inputs: Public inputs for verification
            - metadata: Embedding metadata
        """
        print("=" * 60)
        print("ZK-SNARK Steganography Prover")
        print("=" * 60)
        
        # Load cover image
        cover_img = Image.open(cover_image_path)
        cover_array = np.array(cover_img)
        print(f"Cover image: {cover_image_path}")
        print(f"Image size: {cover_array.shape}")
        
        # Generate or use provided chaos_key
        if chaos_key is None:
            chaos_key = generate_random_chaos_key()
            print(f"Generated new chaos_key: {chaos_key[:16]}... (SAVE THIS!)")
        else:
            print(f"Using provided chaos_key: {chaos_key[:16]}...")
        
        chaos_key_int = generate_chaos_key_from_secret(chaos_key)
        
        # Extract feature point for starting position
        if x0 is None or y0 is None:
            x0, y0 = extract_feature_point(cover_array)
            print(f"Auto-detected starting position: ({x0}, {y0})")
        else:
            print(f"Using provided starting position: ({x0}, {y0})")
        
        # Convert message to bits
        message_bits = message_to_bits(message)
        print(f"Message length: {len(message)} chars, {len(message_bits)} bits")
        
        # Embed message into image
        print("\nEmbedding message...")
        lsb = LSBProcessor(cover_array)
        stego_array = lsb.embed_bits(message_bits, x0, y0, chaos_key_int)
        
        # Save stego image
        stego_img = Image.fromarray(stego_array.astype(np.uint8))
        stego_img.save(output_path)
        print(f"Stego image saved: {output_path}")
        
        # Prepare result
        result = {
            "stego_image_path": output_path,
            "chaos_key": chaos_key,
            "x0": x0,
            "y0": y0,
            "message_length": len(message),
            "message_bits": len(message_bits),
            "timestamp": int(time.time()),
            "proof": None,
            "public_inputs": None,
        }
        
        # Generate ZK proof if requested
        if generate_zk_proof:
            print("\nGenerating ZK proof...")
            proof_result = self._generate_zk_proof(
                cover_array, message, chaos_key, x0, y0
            )
            
            if proof_result:
                result["proof"] = proof_result["proof"]
                result["public_inputs"] = proof_result["public_inputs"]
                result["witness_input"] = proof_result["witness_input"]
                print("ZK proof generated successfully!")
            else:
                print("WARNING: ZK proof generation failed, continuing without proof")
        
        # Create and embed metadata chunk
        print("\nEmbedding metadata chunk...")
        chaos_metadata = self._create_chaos_metadata(
            x0, y0, chaos_key_int, len(message_bits)
        )
        
        chunk_metadata = {
            "chaos": chaos_metadata,
            "public": {
                "image_hash": compute_file_hash(cover_image_path),
                "message_length": len(message),
                "proof_length": len(message_bits),
                "timestamp": result["timestamp"],
            },
            "meta": {
                "version": "2.0",
                "algorithm": "chaos_lsb_zksnark",
            },
            "timestamp": result["timestamp"],
        }
        
        if result["public_inputs"]:
            chunk_metadata["public"]["public_inputs"] = result["public_inputs"]
        
        success = PNGChunkHandler.embed_metadata(output_path, chunk_metadata)
        if success:
            print("Metadata chunk embedded successfully!")
            result["metadata"] = chunk_metadata
        else:
            print("WARNING: Failed to embed metadata chunk")
        
        print("\n" + "=" * 60)
        print("Embedding complete!")
        print(f"Output: {output_path}")
        print(f"Chaos key (SAVE THIS!): {chaos_key}")
        print("=" * 60)
        
        return result
    
    def embed_only(
        self,
        cover_image_path: str,
        output_path: str,
        message: str,
        chaos_key: str,
        x0: Optional[int] = None,
        y0: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Embed message without generating ZK proof (faster)
        
        Args:
            cover_image_path: Path to cover image
            output_path: Path for output stego image
            message: Message to embed
            chaos_key: Secret key for chaos generation
            x0, y0: Optional starting position
            
        Returns:
            Embedding result dict
        """
        return self.embed_and_prove(
            cover_image_path=cover_image_path,
            output_path=output_path,
            message=message,
            chaos_key=chaos_key,
            x0=x0,
            y0=y0,
            generate_zk_proof=False
        )
    
    def generate_proof_only(
        self,
        cover_image_path: str,
        message: str,
        chaos_key: str,
        x0: Optional[int] = None,
        y0: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Generate ZK proof without embedding (for pre-embedded images)
        
        Args:
            cover_image_path: Path to original cover image
            message: Message that was embedded
            chaos_key: Chaos key that was used
            x0, y0: Starting position that was used
            
        Returns:
            Proof package dict
        """
        cover_img = Image.open(cover_image_path)
        cover_array = np.array(cover_img)
        
        if x0 is None or y0 is None:
            x0, y0 = extract_feature_point(cover_array)
        
        return self._generate_zk_proof(cover_array, message, chaos_key, x0, y0)
    
    # =========================================================================
    # INTERNAL METHODS
    # =========================================================================
    
    def _create_chaos_metadata(
        self, 
        x0: int, 
        y0: int, 
        chaos_key: int,
        proof_length: int
    ) -> Dict[str, Any]:
        """Create metadata for PNG chunk"""
        import hashlib
        chaos_key_hash = hashlib.sha256(str(chaos_key).encode()).hexdigest()[:16]
        
        return {
            "initial_position": {"x": x0, "y": y0},
            "chaos_key_hash": chaos_key_hash,
            "proof_length": proof_length,
            "algorithm": "arnold_cat_logistic",
            "version": "2.0"
        }
    
    def _generate_zk_proof(
        self,
        image_array: np.ndarray,
        message: str,
        chaos_key: str,
        x0: int,
        y0: int
    ) -> Optional[Dict[str, Any]]:
        """Generate ZK proof for embedding"""
        try:
            # Setup trusted setup if needed
            if not self.snarkjs.setup_trusted_setup():
                return None
            
            # Extract chaos parameters
            chaos_params = self._extract_chaos_parameters(
                image_array, message, chaos_key, x0, y0
            )
            
            # Create witness input
            witness_input = self._create_witness_input(chaos_params)
            
            # Generate witness
            witness_file = self.snarkjs.generate_witness(witness_input)
            if not witness_file:
                return None
            
            # Generate proof
            proof_result = self.snarkjs.generate_groth16_proof(witness_file)
            if not proof_result:
                return None
            
            proof, public_inputs = proof_result
            
            return {
                "proof": proof,
                "public_inputs": public_inputs,
                "chaos_parameters": chaos_params,
                "witness_input": witness_input,
            }
            
        except Exception as e:
            print(f"ERROR: ZK proof generation failed: {e}")
            return None
    
    def _extract_chaos_parameters(
        self,
        image_array: np.ndarray,
        message: str,
        chaos_key: str,
        x0: int,
        y0: int
    ) -> Dict[str, Any]:
        """Extract parameters for witness generation"""
        import hashlib
        
        height, width = image_array.shape[:2]
        
        image_hash = compute_image_hash(image_array)
        
        # Convert message to bits
        message_bytes = message.encode('utf-8')[:32]
        proof_bits = []
        for byte in message_bytes:
            for i in range(7, -1, -1):
                proof_bits.append((byte >> i) & 1)
        
        # Generate positions using Arnold Cat Map
        positions = []
        curr_x, curr_y = x0, y0
        for i in range(64):
            new_x = (2 * curr_x + curr_y) % width
            new_y = (curr_x + curr_y) % height
            curr_x, curr_y = new_x, new_y
            positions.append((curr_x, curr_y))
        
        position_data = json.dumps(positions, sort_keys=True)
        commitment_root = hashlib.sha256(position_data.encode()).hexdigest()
        
        return {
            "x0": x0,
            "y0": y0,
            "chaos_key": chaos_key,
            "image_hash": image_hash,
            "commitment_root": commitment_root,
            "proof_bits": proof_bits,
            "positions": positions,
            "proof_length": len(proof_bits),
            "timestamp": int(time.time())
        }
    
    def _create_witness_input(self, chaos_params: Dict[str, Any]) -> Dict[str, Any]:
        """Create witness input for circuit"""
        proof_bits = chaos_params["proof_bits"]
        positions = chaos_params["positions"]
        
        # Pad/truncate to circuit requirements
        if len(proof_bits) > 256:
            proof_bits = proof_bits[:256]
        proof_bits_padded = proof_bits + [0] * (256 - len(proof_bits))
        
        if len(positions) > 64:
            positions = positions[:64]
        positions_padded = positions + [(0, 0)] * (64 - len(positions))
        
        # Adjust for actual circuit (based on compiled circuit)
        proof_bits_adjusted = proof_bits_padded[:32]
        positions_adjusted = positions_padded[:16]
        
        image_hash = chaos_params["image_hash"]
        image_hash_single = int.from_bytes(bytes.fromhex(image_hash), 'big') % (2**254)
        
        chaos_key = chaos_params["chaos_key"]
        if isinstance(chaos_key, str):
            chaos_key_int = int(chaos_key, 16) if len(chaos_key) > 8 else generate_chaos_key_from_secret(chaos_key)
        else:
            chaos_key_int = chaos_key
        
        commitment_root = chaos_params["commitment_root"]
        
        return {
            "commitmentRoot": str(int(commitment_root, 16)),
            "proofLength": str(chaos_params["proof_length"]),
            "timestamp": str(chaos_params["timestamp"]),
            "x0": str(chaos_params["x0"]),
            "y0": str(chaos_params["y0"]),
            "chaosKey": str(chaos_key_int),
            "proofBits": [str(bit) for bit in proof_bits_adjusted],
            "positions": [[str(pos[0]), str(pos[1])] for pos in positions_adjusted],
            "imageHash": str(image_hash_single)
        }


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def embed(
    cover_image: str,
    output_path: str,
    message: str,
    chaos_key: Optional[str] = None,
    with_proof: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Convenience function to embed message into image
    
    Args:
        cover_image: Path to cover image
        output_path: Path for stego image
        message: Message to embed
        chaos_key: Secret key (auto-generated if None)
        with_proof: Generate ZK proof (default True)
        
    Returns:
        Result dict with chaos_key, proof, etc.
    """
    prover = Prover()
    return prover.embed_and_prove(
        cover_image_path=cover_image,
        output_path=output_path,
        message=message,
        chaos_key=chaos_key,
        generate_zk_proof=with_proof
    )


if __name__ == "__main__":
    import sys
    import os
    
    # Check for demo mode
    if len(sys.argv) >= 2 and sys.argv[1] == "demo":
        print("=" * 60)
        print("ZK-SNARK Steganography Prover - DEMO")
        print("=" * 60)
        
        # Create demo cover image
        demo_cover = "demo_cover.png"
        demo_stego = "demo_stego.png"
        demo_message = "Hello ZK-SNARK Steganography!"
        demo_chaos_key = "demo_secret_key_12345"
        
        print(f"\n[1] Creating demo cover image: {demo_cover}")
        img = Image.new("RGB", (512, 512), color=(128, 128, 128))
        pixels = np.array(img)
        np.random.seed(42)
        pixels = (pixels + np.random.randint(-30, 30, pixels.shape)).astype(np.uint8)
        Image.fromarray(pixels).save(demo_cover)
        print(f"    Created 512x512 RGB image")
        
        print(f"\n[2] Embedding message: \"{demo_message}\"")
        print(f"    Chaos key: {demo_chaos_key}")
        
        prover = Prover()
        result = prover.embed_only(
            cover_image_path=demo_cover,
            output_path=demo_stego,
            message=demo_message,
            chaos_key=demo_chaos_key
        )
        
        print(f"\n[3] Result:")
        print(f"    Stego image saved: {demo_stego}")
        print(f"    Starting position: ({result['x0']}, {result['y0']})")
        print(f"    Message bits: {result['message_bits']}")
        
        # Cleanup cover
        os.remove(demo_cover)
        
        print("\n" + "=" * 60)
        print("Demo complete! Now run verifier to extract:")
        print(f"  python -m src.zk_stego.verifier demo")
        print("=" * 60)
        
    else:
        print("ZK-SNARK Steganography Prover")
        print("=" * 40)
        print("Usage:")
        print("  python -m src.zk_stego.prover demo")
        print("  python -m src.zk_stego.prover embed <cover.png> <output.png> <message> [chaos_key]")
        print("")
        print("Example:")
        print('  python -m src.zk_stego.prover embed cover.png stego.png "Hello World" my_key')

