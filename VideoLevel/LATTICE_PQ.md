# Lattice Post-Quantum Path

The `feature/lattice-pq-stack` branch adds an opt-in lattice cryptographic
path without attempting to squeeze a multi-kilobyte lattice proof into the
H.264 CAVLC payload.

## Active construction

- ML-DSA-65 signs the message receipt and the v3 stego manifest.
- ML-KEM-768 is available for encapsulating a shared secret for a remote
  prover/receiver transport channel.
- The video embeds `[LQ1 | message length | message | 32-byte receipt hash]`.
- `<stego>.lattice.json` stores the signed receipt; the signed manifest binds
  the stego hash and embedding positions hash.

This is a lattice-based **attestation** path, not a general lattice ZK proof.
It does not claim the zero-knowledge property offered by Groth16.

## Use

```python
from src.lattice_pq import LatticeSigner
from src.embedder import embed
from src.verifier import verify

public_key, private_key = LatticeSigner.generate_keypair()
result = embed(
    video_path="cover.h264",
    output_path="stego.h264",
    message=b"authenticated payload",
    circuits_dir="circuits",  # retained for API compatibility; unused in lattice mode
    secret_key=bytes(32),      # retained for API compatibility; unused in lattice mode
    proof_backend="lattice",
    lattice_private_key=private_key,
)

verification = verify(
    stego_video_path="stego.h264",
    original_video_path="cover.h264",
    circuits_dir="circuits",
    secret_key=bytes(32),
    message_length=len(b"authenticated payload"),
    proof_backend="lattice",
    lattice_public_key=public_key,
)
assert verification.valid
```

## Validation status

The ML-DSA receipt, ML-KEM encapsulation, manifest signature, video-reference
format, and sidecar serialization have unit coverage. The full H.264 lattice
E2E remains pending because its reconstruction path exceeded the bounded test
window; it must be rerun on a dedicated test asset before release.
