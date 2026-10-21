"""Pre-lattice-ZK system, kept runnable but separate from the current path.

One-shot embed/verify with a signed sidecar manifest (ML-DSA lattice
receipt, optional Groth16 circuits in ``legacy/circuits``), the near-blind
and keyed verifiers, the LaZer statement contract, the realtime Annex-B
transport, the LaZer host preflight and the trust/provenance workflows.
This used to be the public API of the ``src`` package.
"""

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
