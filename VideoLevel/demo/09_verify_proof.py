"""Verify the recovered proof against its recovered message and session key."""

from __future__ import annotations

import argparse

from common import ROOT, read_key, require_artifact, require_session, run_python_logged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    args = parser.parse_args()
    session, _ = require_session(args.session)
    message = require_artifact(session, "recovered_message.bin").read_bytes()
    proof_bytes = require_artifact(session, "recovered_proof_129_bytes.bin").read_bytes()
    key = read_key(session)

    def verify() -> None:
        from src.zk_proof import ZKSnarkBridge

        bridge = ZKSnarkBridge(str(ROOT / "circuits"))
        proof = bridge.bytes_to_proof(proof_bytes)
        valid = bridge.verify_proof_for_payload(proof, message, key)
        if not valid:
            raise AssertionError("Groth16 verifier rejected the extracted proof")
        tampered_valid = bridge.verify_proof_for_payload(proof, message + b"!", key)
        if tampered_valid:
            raise AssertionError("Groth16 verifier accepted a modified message")
        print("recovered_proof_valid=True")
        print("modified_message_valid=False")

    run_python_logged(session, "09_verify_proof.log", "Verify extracted Groth16 proof", verify)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
