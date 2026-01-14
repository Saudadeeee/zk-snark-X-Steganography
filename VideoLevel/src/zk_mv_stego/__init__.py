"""
ZK-SNARK DCT Video Steganography
Production-ready video steganography using DCT coefficients + Zero-Knowledge proofs

Modules:
- embedder: DCT coefficient embedding
- encoder: Video encoding/decoding
- prover: ZK-SNARK proof generation
- verifier: Proof extraction and verification
- utils: Quality metrics and statistics
"""

__version__ = "2.0-DCT"
__author__ = "ZK-Stego Team"

from .embedder import DCTEmbedder, DCTExtractor, PayloadEncoder, PayloadDecoder
from .prover import VideoProver, ZKProofWrapper
from .verifier import VideoVerifier
from .encoder import VideoEncoder
from .utils import calculate_psnr, calculate_ssim

__all__ = [
    # Embedder
    "DCTEmbedder",
    "DCTExtractor",
    "PayloadEncoder",
    "PayloadDecoder",
    
    # Encoder
    "VideoEncoder",
    
    # Prover
    "VideoProver",
    "ZKProofWrapper",
    
    # Verifier
    "VideoVerifier",
    
    # Utils
    "calculate_psnr",
    "calculate_ssim",
]
