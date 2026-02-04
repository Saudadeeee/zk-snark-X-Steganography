"""
Error Correction Codes (ECC) Module for ZK-SNARK Video Steganography v3.0

This module provides error correction capabilities:
- LDPC (Low-Density Parity-Check) encoding/decoding
- Temporal interleaving across video frames
- Belief Propagation decoder
- Progressive Edge-Growth matrix construction

Version: 3.0
Date: February 4, 2026
"""

__version__ = "3.0.0"
__author__ = "ZK Video Stego Team"

from .ldpc_codec import LDPCCodec
from .temporal_interleaver import TemporalInterleaver

__all__ = [
    'LDPCCodec',
    'TemporalInterleaver',
]
