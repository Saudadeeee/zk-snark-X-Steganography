"""
ZK-SNARK Steganography Core Module

A clean, modular implementation of ZK-SNARK based steganography
using chaos theory (Arnold Cat Map + Logistic Map) for position generation.

Structure:
    - prover.py   : Embed message + generate ZK proof
    - verifier.py : Extract message + verify ZK proof  
    - utils.py    : Helper functions (chaos, LSB, PNG chunks, snarkjs)

Quick Start:
    # Prover (embed message)
    from zk_stego import Prover
    
    prover = Prover()
    result = prover.embed_and_prove(
        cover_image_path="cover.png",
        output_path="stego.png",
        message="Secret message",
        chaos_key="my_secret_key"
    )
    
    # Verifier (extract message)
    from zk_stego import Verifier
    
    verifier = Verifier()
    result = verifier.extract_and_verify(
        stego_image_path="stego.png",
        chaos_key="my_secret_key"
    )
    print(result["message"])

Convenience Functions:
    from zk_stego import embed, extract, verify
    
    # Embed
    result = embed("cover.png", "stego.png", "Hello", "secret_key")
    
    # Extract
    result = extract("stego.png", "secret_key")
    
    # Verify
    is_valid = verify("stego.png", "secret_key")
"""

# Main classes
from .prover import Prover
from .verifier import Verifier

# Convenience functions
from .prover import embed
from .verifier import extract, verify, get_info

# Utility classes (for advanced usage)
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
    bits_to_bytes,
    bytes_to_bits,
)

__version__ = "2.0.0"
__all__ = [
    # Main classes
    "Prover",
    "Verifier",
    
    # Convenience functions
    "embed",
    "extract", 
    "verify",
    "get_info",
    
    # Utility classes
    "ChaosGenerator",
    "LSBProcessor",
    "PNGChunkHandler",
    "SnarkJSRunner",
    
    # Utility functions
    "generate_chaos_key_from_secret",
    "generate_random_chaos_key",
    "compute_image_hash",
    "compute_file_hash",
    "extract_feature_point",
    "message_to_bits",
    "bits_to_bytes",
    "bytes_to_bits",
]
