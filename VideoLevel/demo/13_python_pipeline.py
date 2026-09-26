"""Run the separate legacy Python embed()/verify() branch in isolation."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from common import ROOT, read_key, require_session, run_python_logged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    args = parser.parse_args()
    session, _ = require_session(args.session)
    output = session / "python_pipeline_stego.h264"
    cache = session / "python_analysis_cache"

    def run_legacy() -> None:
        from benchmark.locked_operating_contract import load_best_locked_operating_contract
        from benchmark.locked_operating_contract import LOCKED_MESSAGE
        from src.embedder import embed
        from src.verifier import verify

        required_bits = (4 + len(LOCKED_MESSAGE) + 129) * 8
        contract = load_best_locked_operating_contract(
            required_bits=required_bits,
            preferred_sequences=["deadline_q22_g1_600f", "akiyo_q22_g1",
                                "coastguard_q22_g1", "foreman_q22_g1"],
        )
        if contract is None or not Path(contract.video_path).is_file():
            raise FileNotFoundError("no valid locked Python embedding operating-point contract is available")

        previous_trust = os.environ.get("ZK_STEGO_TRUSTED_PICKLE_CACHE")
        os.environ["ZK_STEGO_TRUSTED_PICKLE_CACHE"] = "1"
        try:
            result = embed(
                video_path=contract.video_path,
                message=LOCKED_MESSAGE,
                output_path=str(output),
                circuits_dir=str(ROOT / "circuits"),
                secret_key=read_key(session),
                use_analysis_cache=True,
                analysis_cache_dir=str(cache),
            )
            verified = verify(
                stego_video_path=str(output),
                original_video_path=contract.video_path,
                circuits_dir=str(ROOT / "circuits"),
                secret_key=read_key(session),
                message_length=len(LOCKED_MESSAGE),
                precomputed_positions=result.used_positions,
                precomputed_payload_bits=result.bits_embedded,
                use_analysis_cache=True,
                analysis_cache_dir=str(cache),
            )
        finally:
            if previous_trust is None:
                os.environ.pop("ZK_STEGO_TRUSTED_PICKLE_CACHE", None)
            else:
                os.environ["ZK_STEGO_TRUSTED_PICKLE_CACHE"] = previous_trust

        if not output.is_file() or not verified.valid or verified.message != LOCKED_MESSAGE:
            raise AssertionError("Python embed()/verify() pipeline did not round-trip its message and proof")
        print(f"input_video={contract.video_path}")
        print(f"output_video={output}")
        print(f"bits_embedded={result.bits_embedded}; proof_valid={verified.valid}")

    run_python_logged(session, "13_python_pipeline.log", "Run Python embed()/verify() branch", run_legacy)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
