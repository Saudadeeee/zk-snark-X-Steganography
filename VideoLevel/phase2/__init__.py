"""
Phase 2: ZK-SNARK Video Steganography
======================================

Integration of Zero-Knowledge Proofs with Video MV Embedding

Components:
-----------
- ZKProofWrapper: Generate/verify Groth16 proofs using Circom circuits
- VideoProver: Embed ZK proofs into video motion vectors
- VideoVerifier: Extract and verify ZK proofs from stego videos
- VideoQualityMetrics: Assess quality impact of embedding

Workflow:
---------
1. Prover: Generate ZK proof binding message to video
2. Prover: Embed proof into video MVs using Phase 1 pipeline
3. Verifier: Extract proof from stego video
4. Verifier: Verify proof without learning secret message

Key Features:
-------------
- Zero-knowledge property: Verifier learns nothing about message
- Cryptographic binding: Proof linked to specific video via hash
- Chaos-based embedding: Deterministic carrier selection
- Quality preservation: Minimal MV modifications (<1 pixel avg)
"""

from .zk_proof_wrapper import ZKProofWrapper
from .video_prover import VideoProver
from .video_verifier import VideoVerifier
from .quality_metrics import VideoQualityMetrics

__all__ = [
    'ZKProofWrapper',
    'VideoProver',
    'VideoVerifier',
    'VideoQualityMetrics'
]
