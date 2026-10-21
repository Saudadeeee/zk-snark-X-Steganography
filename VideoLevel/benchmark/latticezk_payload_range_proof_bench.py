"""Size and timing benchmark for the BDLOP payload range proof (stream C3).

    python -m benchmark.latticezk_payload_range_proof_bench --runs 10 --lengths 32,64 \
        --output benchmark/results/q2/payload_range_proof_bench.json

Every run draws a fresh random payload, commitment randomness and prover
entropy, so the attempt count (and with it the prover time) follows the
geometric distribution of Fiat-Shamir with aborts.  The machine load is not
controlled; compare medians, not single runs.  Besides the measured lengths
the report lists the computed sizes for every supported length, the
alternative "binary payload from the start" (the existing binary proof on
``Com(encode_bits(p))``) and the hypothetical full 24-bit range proof over all
256 payload coefficients.
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

from src.lattice_zk import bdlop, binary_proof, codec, payload_range_proof, video_proof  # noqa: E402

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


def _hypothetical(params: payload_range_proof.PayloadRangeParams, polys: int) -> dict[str, Any]:
    """Size and acceptance of the same construction with ``polys`` bit polynomials (not run)."""
    base, k, checks = params.base, params.lift_repetitions, params.check_repetitions
    layout = payload_range_proof.Layout(0, polys, k * polys, checks, base.msis_rank, base.mlwe_rank)
    rows = layout.first_rows + layout.second_rows
    response_polys = base.width + layout.aux_width
    size = (
        (rows * params.degree * base.modulus_bits + 7) // 8
        + (checks * (params.degree - 1) * base.modulus_bits + 7) // 8
        + (params.degree * base.modulus_bits + 7) // 8 + 32
        + (response_polys * params.degree * base.response_bits + 7) // 8
    )
    kept = (2 * base.response_bound + 1) / (2 * base.mask_bound)
    acceptance = kept ** (response_polys * params.degree)
    return {"binary_polys": polys, "proof_bytes": size, "acceptance_probability": acceptance,
            "expected_attempts": round(1 / acceptance, 1)}


def _measure(params: payload_range_proof.PayloadRangeParams, length: int, runs: int) -> dict[str, Any]:
    base = params.base
    prove_ms: list[float] = []
    verify_ms: list[float] = []
    attempts: list[int] = []
    for _ in range(runs):
        payload = os.urandom(length)
        randomness = bdlop.sample_randomness(base)
        commitment = bdlop.commit(base, codec.encode_payload(base, payload), randomness)
        result, elapsed = _timed(lambda: payload_range_proof.prove_with_stats(
            params, STATEMENT, commitment, payload, randomness
        ))
        prove_ms.append(elapsed)
        attempts.append(result.attempts)
        accepted, elapsed = _timed(lambda: payload_range_proof.verify(
            params, STATEMENT, commitment, length, result.proof
        ))
        verify_ms.append(elapsed)
        if not accepted or len(result.proof) != params.proof_bytes(length):
            raise RuntimeError("an honest payload range proof failed verification")
    layout = params.layout(length)
    return {
        "payload_bytes": length,
        "binary_polys": layout.binary_polys,
        "aux_slots": layout.slots,
        "aux_width": layout.aux_width,
        "aux_mlwe_ring_samples": params.mlwe_samples(length),
        "proof_bytes": params.proof_bytes(length),
        "proof_parts": params.proof_parts(length),
        "timings_ms": {"prove": _summary(prove_ms), "verify": _summary(verify_ms)},
        "attempts": {
            "mean": round(statistics.fmean(attempts), 2),
            "median": statistics.median(attempts),
            "max": max(attempts),
            "expected": round(1 / params.acceptance_probability(length), 2),
            "acceptance_probability": round(params.acceptance_probability(length), 5),
            "abort_cap": payload_range_proof.MAX_ATTEMPTS,
            "abort_probability_log2": round(payload_range_proof.abort_probability_log2(params, length), 1),
        },
    }


def run(parameter_set: str, runs: int, lengths: list[int]) -> dict[str, Any]:
    params = getattr(payload_range_proof, parameter_set)
    base = params.base
    binary = binary_proof.BINARY_128 if base is binary_proof.BINARY_128.base else binary_proof.BINARY_TOY
    supported = sorted({max(1, polys * params.degree // 8) for polys in range(1, params.max_binary_polys + 1)})
    full_range_polys = 8 * base.payload_bytes_per_coefficient
    return {
        "parameter_set": params.name,
        "parameter_id": params.parameter_id.hex(),
        "base_parameter_set": base.name,
        "runs": runs,
        "host": {"machine": platform.machine(), "processor": platform.processor(),
                 "python": platform.python_version(), "system": platform.platform()},
        "repetitions": {"lift": params.lift_repetitions, "check": params.check_repetitions},
        "max_payload_bytes": params.max_payload_bytes,
        "statement": "commitment C hides codec.encode_payload(p) for some p of the public length L",
        "soundness": {
            "round_errors_log2": {name: round(value, 2) for name, value in params.round_soundness_log2.items()},
            "soundness_bits": round(params.soundness_bits, 2),
        },
        "measured": [_measure(params, length, runs) for length in lengths],
        "computed_sizes_bytes": {str(length): params.proof_bytes(length) for length in supported},
        "reference_sizes_bytes": {
            "commitment": base.commitment_bytes,
            "opening_proof": base.proof_bytes,
            "in_band_envelope_v1": video_proof.envelope_size(base),
            "alternative_b_binary_payload": {
                "description": "binary proof on Com(encode_bits(p)), exactly 32-byte payloads per polynomial",
                "commitment_plus_proof_per_32_bytes": base.commitment_bytes + binary.proof_bytes,
                "binary_proof": binary.proof_bytes,
            },
            "full_24_bit_range_all_coefficients_hypothetical": _hypothetical(params, full_range_polys),
        },
        "note": (
            "single-threaded Python + numpy reference implementation (float64 BLAS for exact "
            "negacyclic products); not constant time; machine shared with other jobs"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--parameter-set", default="PAYLOAD_RANGE_128")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--lengths", default="32,64")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    lengths = [int(value) for value in arguments.lengths.split(",") if value]
    report = json.dumps(run(arguments.parameter_set, arguments.runs, lengths), indent=2) + "\n"
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(report, encoding="utf-8")
    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
