"""Lattice zero-knowledge proofs carried inside H.264 CAVLC video.

Subpackages:

* ``lattice_zk`` - BDLOP commitment, proofs, video statement and CLI;
* ``transport``  - blind carrier selection, chunk framing, GOP policy;
* ``registry``   - signed relation registry, verifier sessions, ML-DSA signer;
* ``core``, ``bitstream`` - CAVLC carrier analysis and bitstream patching;
* ``legacy``     - the pre-lattice-ZK system (Groth16 receipts, sidecar
  manifest, near-blind verifiers, trust workflows); kept runnable, not used
  by the lattice-ZK path.

Importing ``src`` loads nothing else; import the subpackage you need.  The
old one-shot API (``embed``, ``verify``, ...) lives in :mod:`src.legacy`.
"""

__version__ = "4.0-lattice-attested"
