"""
zk-Schnorr experimental module.

Exports the Schnorr proof system and chaos-integrated pipeline used for
comparing against the Groth16 zkSNARK baseline.
"""

from .schnorr_proof import SchnorrProofSystem  # noqa: F401
from .chaos_schnorr_pipeline import SchnorrChaosPipeline  # noqa: F401


