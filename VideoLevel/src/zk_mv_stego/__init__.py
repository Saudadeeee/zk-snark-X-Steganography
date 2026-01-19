"""
ZK-SNARK CAVLC Video Steganography
Core CAVLC-based video steganography system with Zero-Knowledge proofs

Core Modules:
- bitstream: CAVLC encoder/decoder, H.264 parser, bitstream I/O
- decoder: CAVLC coefficient extraction
- prover: ZK-SNARK proof generation
- verifier: Proof verification
- utils: Quality metrics
- core: Payload embedding
"""

__version__ = "3.0-CAVLC-Core"
__author__ = "ZK-Stego Team"

# Core CAVLC system - minimal imports
from .bitstream.cavlc_encoder import CAVLCEncoder
from .bitstream.cavlc_decoder import CAVLCDecoder
from .bitstream.h264_parser import H264BitstreamParser
from .decoder.cavlc_extractor_simple import SimpleCAVLCExtractor

__all__ = [
    "CAVLCEncoder",
    "CAVLCDecoder",
    "H264BitstreamParser",
    "SimpleCAVLCExtractor",
]
