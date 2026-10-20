"""Size and timing benchmark for the BDLOP lattice-ZK backend.

    python -m benchmark.latticezk_crypto_bench --runs 30 --output benchmark/results/latticezk_crypto_bench.json
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.lattice_zk import bdlop, codec, equality_proof, opening_proof, video_proof  # noqa: E402
from src.lattice_zk import params as parameter_sets  # noqa: E402

GROTH16_PROOF_BYTES = 129
ML_DSA_SIGNATURE_BYTES = {"ML-DSA-44": 2420, "ML-DSA-65": 3309}
STATEMENT = bytes(274)


def _timed(function: Callable[[], Any]) -> tuple[Any, float]:
    started = time.perf_counter()
    value = function()
    return value, (time.perf_counter() - started) * 1000


def _summary(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "mean": round(statistics.fmean(ordered), 2),
        "median": round(statistics.median(ordered), 2),
        "p95": round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 2),
        "max": round(ordered[-1], 2),
    }


def run(parameter_set: str, runs: int) -> dict[str, Any]:
    params = getattr(parameter_sets, parameter_set)
    message = codec.encode_payload(params, b"benchmark payload")
    samples: dict[str, list[float]] = {
        name: [] for name in ("commit", "prove", "verify", "equality_prove", "equality_verify")
    }
    attempts: dict[str, list[int]] = {"prove": [], "equality_prove": []}
    for _ in range(runs):
        r_a, r_b = bdlop.sample_randomness(params), bdlop.sample_randomness(params)
        c_a, elapsed = _timed(lambda: bdlop.commit(params, message, r_a))
        samples["commit"].append(elapsed)
        c_b = bdlop.commit(params, message, r_b)

        opened, elapsed = _timed(lambda: opening_proof.prove_with_stats(params, STATEMENT, c_a, r_a))
        samples["prove"].append(elapsed)
        attempts["prove"].append(opened.attempts)
        accepted, elapsed = _timed(lambda: opening_proof.verify(params, STATEMENT, c_a, opened.proof))
        samples["verify"].append(elapsed)

        equal, elapsed = _timed(
            lambda: equality_proof.prove_with_stats(params, STATEMENT, c_a, r_a, c_b, r_b)
        )
        samples["equality_prove"].append(elapsed)
        attempts["equality_prove"].append(equal.attempts)
        equal_ok, elapsed = _timed(
            lambda: equality_proof.verify(params, STATEMENT, c_a, c_b, equal.proof)
        )
        samples["equality_verify"].append(elapsed)
        if not (accepted and equal_ok):
            raise RuntimeError("an honest proof failed verification")

    return {
        "parameter_set": params.name,
        "parameter_id": params.parameter_id.hex(),
        "runs": runs,
        "host": {"machine": platform.machine(), "processor": platform.processor(),
                 "python": platform.python_version(), "system": platform.platform()},
        "sizes_bytes": {
            "commitment": params.commitment_bytes,
            "opening_proof": params.proof_bytes,
            "equality_proof": equality_proof.proof_bytes(params),
            "in_band_envelope": video_proof.envelope_size(params),
            "baseline_groth16_proof": GROTH16_PROOF_BYTES,
            **{f"baseline_{name}_signature": size for name, size in ML_DSA_SIGNATURE_BYTES.items()},
        },
        "timings_ms": {name: _summary(values) for name, values in samples.items()},
        "mean_attempts": {name: round(statistics.fmean(values), 2) for name, values in attempts.items()},
        "expected_attempts": {
            "prove": round(1 / params.acceptance_probability, 2),
            "equality_prove": round(1 / params.acceptance_probability ** 2, 2),
        },
        "note": "single-threaded pure-Python reference implementation; not constant time",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--parameter-set", default="BDLOP_OPEN_128")
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = json.dumps(run(arguments.parameter_set, arguments.runs), indent=2) + "\n"
    if arguments.output is not None:
        arguments.output.write_text(report, encoding="utf-8")
    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
