"""
ZK-SNARK CAVLC Video Steganography (Python orchestration layer).

The H.264/CAVLC media core is native C++ (native/, driven through the
zkstego_blind_bits CLI); this package holds the Groth16 proof bridge and
payload format, manifests/key policy, the HTTP service and test tooling.
"""

__version__ = "3.1-upgrade-v3"

from .zk_proof import PROOF_SIZE_BYTES, pack, unpack

__all__ = ["PROOF_SIZE_BYTES", "pack", "unpack", "__version__"]
