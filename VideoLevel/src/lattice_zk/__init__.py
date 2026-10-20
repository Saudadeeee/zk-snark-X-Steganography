"""Research lattice zero-knowledge backend (BDLOP commitment + opening proof).

Self-implemented from the published protocol; unaudited and not constant time.
Entry points for the video path are :func:`embed_video_proof` and
:func:`verify_video_proof`; see ``docs/LATTICE_ZK_BDLOP_PLAN.md``.
"""

from .params import BDLOP_OPEN_128, BdlopParams
from .video_proof import (
    create_commitment_disclosure,
    create_disclosure,
    verify_commitment_disclosure,
    verify_disclosure_proof,
)
from .video_pipeline import (
    CarrierProfile,
    Credential,
    embed_video_proof,
    holder_id_digest,
    pins_from_registry,
    public_sync_key,
    relation_descriptor,
    relation_id,
    session_binding,
    verify_video_proof,
)

__all__ = [
    "BDLOP_OPEN_128",
    "BdlopParams",
    "CarrierProfile",
    "Credential",
    "create_commitment_disclosure",
    "create_disclosure",
    "embed_video_proof",
    "holder_id_digest",
    "pins_from_registry",
    "public_sync_key",
    "relation_descriptor",
    "relation_id",
    "session_binding",
    "verify_commitment_disclosure",
    "verify_disclosure_proof",
    "verify_video_proof",
]
