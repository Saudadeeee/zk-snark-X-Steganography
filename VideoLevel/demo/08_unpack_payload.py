"""Split the blind-extracted payload into its message and compressed proof."""

from __future__ import annotations

import argparse

from common import require_artifact, require_session, run_python_logged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    args = parser.parse_args()
    session, _ = require_session(args.session)
    extracted = require_artifact(session, "extracted_payload.bin").read_bytes()

    def unpack_payload() -> None:
        from src.zk_proof import unpack

        message, proof = unpack(extracted)
        (session / "recovered_message.bin").write_bytes(message)
        (session / "recovered_proof_129_bytes.bin").write_bytes(proof)
        print(f"recovered_message_bytes={len(message)}")
        print(f"recovered_proof_bytes={len(proof)}")
        print(f"recovered_message={message!r}")

    run_python_logged(session, "08_unpack_payload.log", "Unpack extracted message and proof", unpack_payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
