"""Baseline comparison: BDLOP lattice-ZK against Groth16, ML-DSA and ISW21.

BDLOP, ML-DSA and Groth16 are measured on this host.  ISW21 cannot run on
Windows; its figures are the repository's own Linux-container measurements of
2026-10-01 (git history, commit 07c02d9) and are labelled as recorded.

    python -m benchmark.latticezk_baselines --output benchmark/results/latticezk_baselines.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark import latticezk_crypto_bench  # noqa: E402
from src.lattice_zk import video_proof  # noqa: E402
from src.lattice_zk.params import BDLOP_OPEN_128  # noqa: E402

ISW21_RECORDED = {
    "source": ("repository run 2026-10-01, Ubuntu 24.04 container on the same i7-12700H; "
               "docs/lattice_zk_backend_candidate_isw21_20261001.md at commit 07c02d9; not re-run here"),
    "proof_bytes": 21_331,
    "in_video_envelope_bytes": 23_907,
    "verifier_key_bytes": 2_419_872,
    "setup_ms": 9_026,
    "prove_ms": 328,
    "verify_ms": 0.6,
    "peak_rss_mib": 470,
}

PROPERTIES = {
    "bdlop_open_128_registered": {
        "post_quantum_assumption": "M-SIS / M-LWE", "zero_knowledge": True,
        "setup": "transparent (seeded key)", "verifier": "public key material only",
        "binds_video_statement_here": True, "hides_payload": True,
    },
    "groth16_bn128": {
        "post_quantum_assumption": "none (pairings; broken by Shor)", "zero_knowledge": True,
        "setup": "circuit-specific trusted setup", "verifier": "public",
        "binds_video_statement_here": False, "hides_payload": False,
    },
    "ml_dsa_44": {
        "post_quantum_assumption": "M-SIS / M-LWE (FIPS 204)", "zero_knowledge": False,
        "setup": "none", "verifier": "public",
        "binds_video_statement_here": "if the signed message includes it", "hides_payload": False,
    },
    "isw21": {
        "post_quantum_assumption": "LWE; knowledge assumption broken by quantum oblivious sampling",
        "zero_knowledge": "statistical, 2^-40", "setup": "trusted, designated verifier",
        "verifier": "designated (secret key)", "binds_video_statement_here": "toy context only",
        "hides_payload": True,
    },
}


def _timed(function: Callable[[], Any], runs: int) -> tuple[Any, dict[str, float]]:
    samples, value = [], None
    for _ in range(runs):
        started = time.perf_counter()
        value = function()
        samples.append((time.perf_counter() - started) * 1000)
    ordered = sorted(samples)
    return value, {"median_ms": round(statistics.median(ordered), 3),
                   "p95_ms": round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 3)}


def measure_ml_dsa(runs: int) -> dict[str, Any]:
    from pqcrypto.sign import ml_dsa_44, ml_dsa_65

    results = {}
    message = bytes(274)
    for name, scheme in (("ml_dsa_44", ml_dsa_44), ("ml_dsa_65", ml_dsa_65)):
        (public, private), keygen = _timed(scheme.keygen, runs)
        signature, sign = _timed(lambda: scheme.sign(private, message), runs)
        _, verify = _timed(lambda: scheme.verify(public, message, signature), runs)
        results[name] = {"signature_bytes": len(signature), "public_key_bytes": len(public),
                         "keygen": keygen, "sign": sign, "verify": verify}
    return results


def measure_groth16(runs: int) -> dict[str, Any]:
    try:
        from benchmark.legacy.sec5_zkp import _measure_groth16
        return _measure_groth16(n_trials=runs)
    except Exception as error:  # node/snarkjs or circuit artifacts unavailable
        return {"error": f"{type(error).__name__}: {error}"}


def run(runs: int, groth16_runs: int) -> dict[str, Any]:
    bdlop = latticezk_crypto_bench.run("BDLOP_OPEN_128", runs)
    return {
        "host_note": "Windows 11, Intel i7-12700H; single-threaded; BDLOP is pure Python",
        "bdlop_open_128": {
            "proof_bytes": BDLOP_OPEN_128.proof_bytes,
            "commitment_bytes": BDLOP_OPEN_128.commitment_bytes,
            "in_video_envelope_bytes": {
                "registered": video_proof.envelope_size(BDLOP_OPEN_128, registered=True),
                "in_band": video_proof.envelope_size(BDLOP_OPEN_128),
            },
            "timings_ms": bdlop["timings_ms"],
            "mean_attempts": bdlop["mean_attempts"],
        },
        "ml_dsa": measure_ml_dsa(runs),
        "groth16_bn128": measure_groth16(groth16_runs),
        "isw21_recorded": ISW21_RECORDED,
        "properties": PROPERTIES,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=50)
    parser.add_argument("--groth16-runs", type=int, default=5)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    text = json.dumps(run(arguments.runs, arguments.groth16_runs), indent=2) + "\n"
    if arguments.output is not None:
        arguments.output.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
