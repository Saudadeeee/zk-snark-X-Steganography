"""
ZK-SNARK Motion Vector Steganography
Production-ready video steganography using H.264 motion vectors + Zero-Knowledge proofs

Modules:
- extractor: H.264 motion vector extraction (PyAV-based)
- embedder: Payload embedding into motion vectors
- prover: ZK-SNARK proof generation for steganography
- verifier: Message extraction and proof verification
- utils: Shared utilities (statistics, quality metrics)
"""

__version__ = "2.0.0"
__author__ = "ZK-Stego Team"

from .extractor import H264MVExtractor
from .embedder import CarrierSelector, PayloadEncoder, MVEmbedder, MVExtractor
from .prover import VideoProver, ZKProofWrapper
from .verifier import VideoVerifier
from .utils import MVStatistics, QualityMetrics

__all__ = [
    # Extractor
    "H264MVExtractor",
    
    # Embedder
    "CarrierSelector",
    "PayloadEncoder",
    "MVEmbedder",
    "MVExtractor",
    
    # Prover
    "VideoProver",
    "ZKProofWrapper",
    
    # Verifier
    "VideoVerifier",
    
    # Utils
    "MVStatistics",
    "QualityMetrics",
]
