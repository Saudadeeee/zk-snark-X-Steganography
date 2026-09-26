"""Pack message and serialized proof into the transport payload."""

from __future__ import annotations

import argparse

from common import require_artifact, require_session, run_python_logged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    args = parser.parse_args()
    session, _ = require_session(args.session)
    message_path = require_artifact(session, "message.bin")
    proof_path = require_artifact(session, "proof_129_bytes.bin")

    def pack_payload() -> None:
        from src.zk_proof import pack, unpack

        message = message_path.read_bytes()
        proof_bytes = proof_path.read_bytes()
        blob = pack(message, proof_bytes)
        unpacked_message, unpacked_proof = unpack(blob)
        if (unpacked_message, unpacked_proof) != (message, proof_bytes):
            raise AssertionError("pack/unpack round-trip mismatch")
        (session / "packed_payload.bin").write_bytes(blob)
        print(f"format=[4-byte big-endian length][message][compressed proof]")
        print(f"message_bytes={len(message)} proof_bytes={len(proof_bytes)} packed_bytes={len(blob)}")
        print(f"required_payload_bits={len(blob) * 8}")

    run_python_logged(session, "02_pack_payload.log", "Pack proof-bearing payload", pack_payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
