"""
ZK-Schnorr Package
==================

Zero-Knowledge Schnorr protocol implementation for steganography.

Modules:
- zk_schnorr_protocol: Core Schnorr protocol
- hybrid_schnorr_stego: Hybrid steganography system
"""

__version__ = '1.0.0'
__author__ = 'ZK-Stego Research Team'

from .zk_schnorr_protocol import ZKSchnorrProtocol, SchnorrProof
from .hybrid_schnorr_stego import HybridSchnorrSteganography

__all__ = [
    'ZKSchnorrProtocol',
    'SchnorrProof',
    'HybridSchnorrSteganography'
]
