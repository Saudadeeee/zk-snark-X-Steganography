"""Core-SVP estimates for a pinned BDLOP opening-proof parameter set.

Uses the CRYSTALS security-estimates model (the scripts behind the Dilithium
and Kyber specifications), which is not vendored here:

    git clone https://github.com/pq-crystals/security-estimates
    git -C security-estimates checkout 75c26949a902ca297b181375bfb7cfaf22cce784
    python research/bdlop_params/estimate.py --estimator security-estimates

Binding is M-SIS in the infinity norm for B1 in R_q^(n x k) with the bound
8 * kappa * (gamma - kappa - 1) reached by two relaxed openings.  Hiding is
M-LWE with a ternary secret of rank lam and n + 1 ring samples.

``--parameter-set BINARY_128`` estimates the auxiliary commitment of the
binary proof (``src/lattice_zk/binary_proof.py``): the same bound, the wider
key B1' in R_q^(n x aux_width) and n + aux_slots M-LWE samples.  The base
commitment of that proof is the unchanged BDLOP_OPEN_128 instance.
``--parameter-set PAYLOAD_RANGE_128 --binary-polys L`` does the same for the
auxiliary commitment of the payload range proof
(``src/lattice_zk/payload_range_proof.py``) with ``L`` bit polynomials.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.lattice_zk import binary_proof, payload_range_proof  # noqa: E402
from src.lattice_zk import params as parameter_sets  # noqa: E402
from src.lattice_zk.params import BdlopParams  # noqa: E402

ESTIMATOR_COMMIT = "75c26949a902ca297b181375bfb7cfaf22cce784"
MAX_BLOCK_SIZE = 1400
TERNARY_STDDEV = math.sqrt(2 / 3)


def _scan(cost: Callable[[int], float], low: int, high: int) -> tuple[float, int]:
    """Coarse-to-fine minimisation of a block-size cost curve."""
    best_cost, best_block, step = math.inf, low, 16
    while step >= 1:
        for block in range(low, high + 1, step):
            value = cost(block)
            if value < best_cost:
                best_cost, best_block = value, block
        low, high = max(50, best_block - step), best_block + step
        step //= 4
    return best_cost, best_block


def _primal_block(model: dict, q: int, secret_dim: int, samples: int) -> int:
    """Smallest BKZ block size for which the primal uSVP attack succeeds."""
    best = MAX_BLOCK_SIZE
    for used in sorted({samples, samples * 3 // 4, samples // 2}):
        low, high = 50, secret_dim + used

        def succeeds(block: int) -> bool:
            cost = model["primal"](q, secret_dim, used, TERNARY_STDDEV, block)
            return cost < model["infinity"]

        if not succeeds(high):
            continue
        while low < high:
            middle = (low + high) // 2
            low, high = (low, middle) if succeeds(middle) else (middle + 1, high)
        best = min(best, low)
    return best


class AuxInstance:
    """The auxiliary commitment of a binary-proof set, shaped like a ``BdlopParams``."""

    def __init__(self, params: binary_proof.BinaryParams) -> None:
        base = params.base
        self.name = params.name + "/aux"
        self.parameter_id = params.parameter_id
        self.modulus, self.degree = base.modulus, base.degree
        self.msis_rank, self.mlwe_rank = base.msis_rank, base.mlwe_rank
        self.width = params.aux_width
        self.mlwe_samples = params.mlwe_samples
        self.binding_norm_bound = base.binding_norm_bound
        self.commitment_bytes = params.aux_commitment_bytes
        self.proof_bytes = params.proof_bytes
        self.challenge_space_bits = base.challenge_space_bits
        self.acceptance_probability = params.acceptance_probability


class PayloadAuxInstance(AuxInstance):
    """The auxiliary commitment of a payload-range set with ``polys`` bit polynomials."""

    def __init__(self, params: payload_range_proof.PayloadRangeParams, polys: int) -> None:
        base = params.base
        length = min(params.max_payload_bytes, polys * params.degree // 8)
        layout = params.layout(length)
        if layout.binary_polys != polys:
            raise ValueError("unsupported number of bit polynomials")
        self.name = f"{params.name}/aux/l={polys}"
        self.parameter_id = params.parameter_id
        self.modulus, self.degree = base.modulus, base.degree
        self.msis_rank, self.mlwe_rank = base.msis_rank, base.mlwe_rank
        self.width = layout.aux_width
        self.mlwe_samples = params.mlwe_samples(length)
        self.binding_norm_bound = base.binding_norm_bound
        parts = params.proof_parts(length)
        self.commitment_bytes = parts["aux_commitment_d0"] + parts["aux_commitment_d1"]
        self.proof_bytes = params.proof_bytes(length)
        self.challenge_space_bits = base.challenge_space_bits
        self.acceptance_probability = params.acceptance_probability(length)


def _parameter_set(name: str, polys: int = 1):
    if hasattr(parameter_sets, name):
        return getattr(parameter_sets, name)
    if hasattr(payload_range_proof, name):
        return PayloadAuxInstance(getattr(payload_range_proof, name), polys)
    return AuxInstance(getattr(binary_proof, name))


def estimate(params: BdlopParams, model: dict) -> dict:
    q, degree = params.modulus, params.degree
    secret_dim = params.mlwe_rank * degree
    # BdlopParams: t1 and t2 are n + 1 samples; AuxInstance: n + aux_slots.
    samples = getattr(params, "mlwe_samples", params.msis_rank + 1) * degree
    classical, quantum = model["classical"], model["quantum"]

    primal = _primal_block(model, q, secret_dim, samples)
    dual_cost, dual_block = _scan(
        lambda block: model["dual"](q, secret_dim, samples, TERNARY_STDDEV, block), 50, MAX_BLOCK_SIZE
    )
    sis_cost, sis_block = _scan(
        lambda block: model["sis_linf"](
            q, degree * params.width, degree * params.msis_rank, params.binding_norm_bound, block
        ),
        50,
        MAX_BLOCK_SIZE,
    )
    repetitions = sis_cost - classical(sis_block)
    return {
        "parameter_set": params.name,
        "parameter_id": params.parameter_id.hex(),
        "estimator": "pq-crystals/security-estimates@" + ESTIMATOR_COMMIT,
        "sizes_bytes": {"commitment": params.commitment_bytes, "proof": params.proof_bytes},
        "challenge_space_bits": round(params.challenge_space_bits, 1),
        "acceptance_probability": round(params.acceptance_probability, 3),
        "msis_binding": {
            "norm": "linf",
            "bound_log2": round(math.log2(params.binding_norm_bound), 2),
            "block_size": sis_block,
            "classical_bits": math.floor(sis_cost),
            "quantum_bits": math.floor(quantum(sis_block) + repetitions),
        },
        "mlwe_hiding": {
            "primal_block_size": primal,
            "primal_classical_bits": math.floor(classical(primal)),
            "primal_quantum_bits": math.floor(quantum(primal)),
            "dual_block_size": dual_block,
            "dual_classical_bits": math.floor(dual_cost),
        },
    }


def _load_model(estimator_dir: Path) -> dict:
    sys.path.insert(0, str(estimator_dir.resolve(strict=True)))
    import MLWE_security  # type: ignore[import-not-found]
    import MSIS_security  # type: ignore[import-not-found]
    import model_BKZ  # type: ignore[import-not-found]

    return {
        "primal": MLWE_security.LWE_primal_cost,
        "dual": MLWE_security.LWE_dual_cost,
        "sis_linf": MSIS_security.SIS_linf_cost,
        "classical": model_BKZ.svp_classical,
        "quantum": model_BKZ.svp_quantum,
        "infinity": model_BKZ.log_infinity,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--estimator", type=Path, required=True)
    parser.add_argument("--parameter-set", default="BDLOP_OPEN_128")
    parser.add_argument("--binary-polys", type=int, default=1, help="payload range sets only")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    params = _parameter_set(arguments.parameter_set, arguments.binary_polys)
    report = json.dumps(estimate(params, _load_model(arguments.estimator)), indent=2) + "\n"
    if arguments.output is not None:
        arguments.output.write_text(report, encoding="utf-8")
    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
