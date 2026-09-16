"""
Post-Quantum Lattice-ZKP CAVLC Video Steganography.
Core CAVLC-based steganography with transparent lattice proofs and ML-DSA.
"""

__version__ = "4.0-lattice-zkp"

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
