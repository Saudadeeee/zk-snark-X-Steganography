"""Known-answer vectors for the BDLOP backend.

Every input is derived from fixed seeds, so the commitment and proof bytes are
reproducible on any platform.  The vectors pin SHA-256 digests of the full
serialized outputs; regenerate them only for a deliberate format change.

    python research/bdlop_params/kat.py --output research/bdlop_params/kat_v1.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.lattice_zk import bdlop, codec, equality_proof, opening_proof  # noqa: E402
from src.lattice_zk import params as parameter_sets  # noqa: E402

CASES = (
    {"name": "empty-payload", "payload": b"", "statement": b""},
    {"name": "short-payload", "payload": b"zkstego", "statement": b"kat statement 1"},
    {"name": "max-payload", "payload": None, "statement": bytes(range(256))},
)


def _seed(label: str, case: str) -> bytes:
    return hashlib.sha3_256(f"zkstego/lattice-zk/kat/v1/{label}/{case}".encode("ascii")).digest()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def generate(parameter_set: str) -> dict[str, Any]:
    params = getattr(parameter_sets, parameter_set)
    key = bdlop.derive_key(params)
    vectors = []
    for case in CASES:
        payload = case["payload"]
        if payload is None:
            payload = bytes(index % 251 for index in range(params.max_payload_bytes))
        randomness = bdlop.sample_randomness(params, _seed("randomness", case["name"]))
        commitment = bdlop.commit(params, codec.encode_payload(params, payload), randomness)
        result = opening_proof.prove_with_stats(
            params, case["statement"], commitment, randomness,
            mask_seed=_seed("mask", case["name"]),
        )
        twin_randomness = bdlop.sample_randomness(params, _seed("twin", case["name"]))
        twin = bdlop.commit(params, codec.encode_payload(params, payload), twin_randomness)
        equal = equality_proof.prove_with_stats(
            params, case["statement"], commitment, randomness, twin, twin_randomness,
            mask_seed=_seed("equality-mask", case["name"]),
        )
        vectors.append({
            "name": case["name"],
            "payload_sha256": _digest(payload),
            "payload_bytes": len(payload),
            "statement_hex": case["statement"].hex(),
            "commitment_sha256": _digest(commitment.to_bytes(params)),
            "opening_proof_sha256": _digest(result.proof),
            "opening_attempts": result.attempts,
            "equality_proof_sha256": _digest(equal.proof),
            "equality_attempts": equal.attempts,
        })
    return {
        "parameter_set": params.name,
        "parameter_id": params.parameter_id.hex(),
        "key_sha256": _digest(key.b1_tail.astype(">u8").tobytes() + key.b2_tail.astype(">u8").tobytes()),
        "vectors": vectors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--parameter-set", default="BDLOP_OPEN_128")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = json.dumps(generate(arguments.parameter_set), indent=2) + "\n"
    if arguments.output is not None:
        arguments.output.write_text(report, encoding="utf-8")
    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
