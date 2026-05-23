"""
ZK-SNARK CAVLC Video Steganography
Core CAVLC-based video steganography system with Zero-Knowledge proofs.
"""

__version__ = "3.1-upgrade-v3"

# Public APIs
from .embedder import embed, EmbedResult
from .verifier import verify, VerifyResult
from .verifier_blind import verify_near_blind
from .verify_modes import (
    verify_strict,
    verify_nearblind,
    verify_benchmark,
    verify_auto,
)
from .manifest import StegoManifest, compute_file_hash

__all__ = [
    "embed",
    "EmbedResult",
    "verify",
    "VerifyResult",
    "verify_near_blind",
    "verify_strict",
    "verify_benchmark",
    "verify_auto",
    "StegoManifest",
    "compute_file_hash",
]
