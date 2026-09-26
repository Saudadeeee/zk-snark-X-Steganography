"""Generate a real Groth16 proof for the session's message."""

from __future__ import annotations

import argparse
import json

from common import ROOT, read_key, require_session, run_python_logged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    args = parser.parse_args()
    session, _ = require_session(args.session)
    message = (session / "message.bin").read_bytes()
    key = read_key(session)

    def generate() -> None:
        from src.zk_proof import ZKSnarkBridge, proof_to_bytes

        bridge = ZKSnarkBridge(str(ROOT / "circuits"))
        proof, public = bridge.generate_proof_for_payload(message, key)
        compressed = proof_to_bytes(proof)
        if len(compressed) != 129:
            raise AssertionError(f"expected compressed Groth16 proof size 129 bytes; got {len(compressed)}")
        (session / "proof.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
        (session / "proof_129_bytes.bin").write_bytes(compressed)
        (session / "zk_public_signals.json").write_text(json.dumps(public, indent=2), encoding="utf-8")
        print(f"message_bytes={len(message)}")
        print(f"proof_compressed_bytes={len(compressed)}")
        print(f"public_signal_count={len(public)}")

    run_python_logged(session, "01_generate_proof.log", "Generate Groth16 proof", generate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
