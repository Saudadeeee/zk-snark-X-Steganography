"""Size and timing benchmark for the BDLOP binary-message proof (roadmap B2).

    python -m benchmark.latticezk_binary_proof_bench --runs 20 \
        --output benchmark/results/q2/binary_proof_bench.json

Every run draws a fresh random 256-bit message, commitment randomness and
prover entropy, so the attempt count (and with it the prover time) follows the
geometric distribution of Fiat-Shamir with aborts.  The machine load is not
controlled; compare medians, not single runs.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.lattice_zk import binary_proof, equality_proof  # noqa: E402

STATEMENT = bytes(274)


def _timed(function: Callable[[], Any]) -> tuple[Any, float]:
    started = time.perf_counter()
    value = function()
    return value, (time.perf_counter() - started) * 1000


def _summary(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        "median": round(statistics.median(ordered), 2),
        "mean": round(statistics.fmean(ordered), 2),
        "min": round(ordered[0], 2),
        "p90": round(ordered[min(len(ordered) - 1, int(0.9 * len(ordered)))], 2),
        "max": round(ordered[-1], 2),
    }


def run(parameter_set: str, runs: int) -> dict[str, Any]:
    params = getattr(binary_proof, parameter_set)
    base = params.base
    prove_ms: list[float] = []
    verify_ms: list[float] = []
    attempts: list[int] = []
    for _ in range(runs):
        message = binary_proof.encode_bits(params, os.urandom(params.message_bytes))
        randomness = binary_proof.sample_randomness(params)
        commitment = binary_proof.commit(params, message, randomness)
        result, elapsed = _timed(lambda: binary_proof.prove_with_stats(
            params, STATEMENT, commitment, message, randomness
        ))
        prove_ms.append(elapsed)
        attempts.append(result.attempts)
        accepted, elapsed = _timed(lambda: binary_proof.verify(params, STATEMENT, commitment, result.proof))
        verify_ms.append(elapsed)
        if not accepted or len(result.proof) != params.proof_bytes:
            raise RuntimeError("an honest binary proof failed verification")

    return {
        "parameter_set": params.name,
        "parameter_id": params.parameter_id.hex(),
        "base_parameter_set": base.name,
        "runs": runs,
        "host": {"machine": platform.machine(), "processor": platform.processor(),
                 "python": platform.python_version(), "system": platform.platform()},
        "message_bits": params.degree,
        "repetitions": {"lift": params.lift_repetitions, "check": params.check_repetitions},
        "sizes_bytes": {
            "commitment": base.commitment_bytes,
            "binary_proof": params.proof_bytes,
            "binary_proof_parts": {
                "aux_commitment": params.aux_commitment_bytes,
                "masks_h": params.mask_bytes,
                "garbage_t_G": params.garbage_bytes,
                "challenge_seed": 32,
                "responses_z_z_aux": params.response_bytes,
            },
            "opening_proof": base.proof_bytes,
            "equality_proof": equality_proof.proof_bytes(base),
        },
        "soundness": {
            "round_errors_log2": {name: round(value, 2) for name, value in params.round_soundness_log2.items()},
            "soundness_bits": round(params.soundness_bits, 2),
        },
        "timings_ms": {"prove": _summary(prove_ms), "verify": _summary(verify_ms)},
        "attempts": {
            "mean": round(statistics.fmean(attempts), 2),
            "median": statistics.median(attempts),
            "max": max(attempts),
            "expected": round(1 / params.acceptance_probability, 2),
            "acceptance_probability": round(params.acceptance_probability, 5),
            "abort_cap": binary_proof.MAX_ATTEMPTS,
            "abort_probability_log2": round(binary_proof.abort_probability_log2(params), 1),
        },
        "reference_opening_attempts_expected": round(1 / base.acceptance_probability, 2),
        "note": (
            "single-threaded Python + numpy reference implementation (float64 BLAS for exact "
            "negacyclic products); not constant time; machine shared with other jobs"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--parameter-set", default="BINARY_128")
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = json.dumps(run(arguments.parameter_set, arguments.runs), indent=2) + "\n"
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(report, encoding="utf-8")
    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
