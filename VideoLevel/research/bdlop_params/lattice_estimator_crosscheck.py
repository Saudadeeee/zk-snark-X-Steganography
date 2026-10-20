"""Cross-check of bdlop-open-128-v1 with the malb/lattice-estimator (Sage).

Runs under Sage (or passagemath-standard) with the estimator importable; it
does not import the project, so it can run in a container without the repo
(exact commands in research/bdlop_params/CROSSCHECK.md):

    cd lattice-estimator            # checkout e4333d9bf9ef42fd8a29651b0c559fba7ce0d834
    PYTHONPATH=. python /path/to/lattice_estimator_crosscheck.py --output crosscheck.json

The module instances are flattened to plain LWE/SIS of dimension rank * N:

* Hiding (M-LWE): secret r_3 in S_1^lam, n + 1 ring samples, uniform ternary
  secret and error  ->  LWE(n = lam*N = 1536, m = (n+1)*N = 1792, q).
* Binding (M-SIS): B1 in R_q^(n x k), infinity-norm bound 8*kappa*B
  ->  SIS(n = n*N = 1536 rows, m = k*N = 3328 columns, q, ||x||_inf <= 8kB).

The parameters below are pinned literally; CROSSCHECK.md gives a one-line
check that they equal src/lattice_zk/params.py::BDLOP_OPEN_128.
"""

from __future__ import annotations

import argparse
import json
import math
import time

from sage.all import RR, log, oo  # noqa: F401  (Sage must be importable)

from estimator import LWE, ND, RC, SIS  # type: ignore[import-not-found]
from estimator.cost import Cost  # type: ignore[import-not-found]
from estimator.lwe_parameters import LWEParameters  # type: ignore[import-not-found]
from estimator.reduction import ADPS16  # type: ignore[import-not-found]
from estimator.sis_parameters import SISParameters  # type: ignore[import-not-found]

# bdlop-open-128-v1 (src/lattice_zk/params.py)
DEGREE = 256
MODULUS = (1 << 30) - 35
MSIS_RANK = 6
MLWE_RANK = 6
CHALLENGE_WEIGHT = 60
MASK_BOUND = 1 << 17
WIDTH = MSIS_RANK + MLWE_RANK + 1
RESPONSE_BOUND = MASK_BOUND - CHALLENGE_WEIGHT - 1
BINDING_BOUND = 8 * CHALLENGE_WEIGHT * RESPONSE_BOUND

ESTIMATOR_COMMIT = "e4333d9bf9ef42fd8a29651b0c559fba7ce0d834"
QUANTUM = ADPS16(mode="quantum")


def mlwe_instance() -> LWEParameters:
    ternary = ND.Uniform(-1, 1)
    return LWEParameters(
        n=MLWE_RANK * DEGREE,
        q=MODULUS,
        Xs=ternary,
        Xe=ternary,
        m=(MSIS_RANK + 1) * DEGREE,
        tag="bdlop-open-128-v1 M-LWE hiding",
    )


def msis_instance(norm=oo, bound=BINDING_BOUND) -> SISParameters:
    return SISParameters(
        n=MSIS_RANK * DEGREE,
        q=MODULUS,
        length_bound=bound,
        m=WIDTH * DEGREE,
        norm=norm,
        tag="bdlop-open-128-v1 M-SIS binding",
    )


def _number(value):
    if value == oo:
        return "inf"
    try:
        return int(value) if value == int(value) and abs(value) < 2**53 else float(value)
    except (TypeError, ValueError, OverflowError):
        return str(value)


def _summarise(cost) -> dict:
    out = {}
    for key, value in dict(cost).items():
        if key in ("rop", "red", "sieve", "guess", "mem", "N", "svp", "prob", "repetitions"):
            out[key + "_log2"] = "inf" if value == oo else round(float(log(RR(value), 2)), 2)
        elif key == "tag" or isinstance(value, str):
            out[key] = str(value)
        else:
            out[key] = _number(value)
    return out


def _run(label: str, thunk, results: dict) -> None:
    started = time.time()
    try:
        value = thunk()
        if not isinstance(value, Cost):
            summary = {name: _summarise(cost) for name, cost in value.items()}
        else:
            summary = _summarise(value)
        results[label] = {"result": summary, "seconds": round(time.time() - started, 1)}
    except Exception as error:  # record and continue with the remaining attacks
        results[label] = {"error": f"{type(error).__name__}: {error}"}
    print(label, json.dumps(results[label]), flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", required=True)
    parser.add_argument("--estimator-commit", default=ESTIMATOR_COMMIT)
    parser.add_argument("--skip-full", action="store_true", help="skip LWE.estimate / SIS.estimate")
    arguments = parser.parse_args()

    lwe, sis = mlwe_instance(), msis_instance()
    results: dict = {}
    gsa = {"red_shape_model": "gsa"}
    _run("mlwe.rough", lambda: LWE.estimate.rough(lwe, quiet=True), results)
    _run("mlwe.primal_usvp.core_svp_classical",
         lambda: LWE.primal_usvp(lwe, red_cost_model=RC.ADPS16, **gsa), results)
    _run("mlwe.primal_usvp.core_svp_quantum",
         lambda: LWE.primal_usvp(lwe, red_cost_model=QUANTUM, **gsa), results)
    _run("mlwe.primal_usvp.matzov", lambda: LWE.primal_usvp(lwe, red_cost_model=RC.MATZOV), results)
    _run("mlwe.primal_bdd.matzov", lambda: LWE.primal_bdd(lwe, red_cost_model=RC.MATZOV), results)
    _run("mlwe.dual_hybrid.core_svp_classical",
         lambda: LWE.dual_hybrid(lwe, red_cost_model=RC.ADPS16), results)
    _run("mlwe.dual_hybrid.core_svp_quantum",
         lambda: LWE.dual_hybrid(lwe, red_cost_model=QUANTUM), results)
    _run("mlwe.dual_hybrid.matzov", lambda: LWE.dual_hybrid(lwe, red_cost_model=RC.MATZOV), results)

    _run("msis_linf.rough", lambda: SIS.estimate.rough(sis, quiet=True), results)
    _run("msis_linf.lattice.core_svp_classical",
         lambda: SIS.lattice(sis, red_cost_model=RC.ADPS16, red_shape_model="lgsa"), results)
    _run("msis_linf.lattice.core_svp_quantum",
         lambda: SIS.lattice(sis, red_cost_model=QUANTUM, red_shape_model="lgsa"), results)
    _run("msis_linf.lattice.matzov", lambda: SIS.lattice(sis, red_cost_model=RC.MATZOV), results)
    # l2 conversion: ||x||_2 <= sqrt(m) * ||x||_inf exceeds q, so the l2 instance
    # is trivial (q * e_1 is a solution); recorded to show why l_inf is needed.
    l2_bound = math.floor(math.sqrt(WIDTH * DEGREE) * BINDING_BOUND)
    _run("msis_l2_from_linf.rough",
         lambda: SIS.estimate.rough(msis_instance(norm=2, bound=l2_bound), quiet=True), results)

    if not arguments.skip_full:
        _run("mlwe.estimate_full", lambda: LWE.estimate(lwe, deny_list=("arora-gb",), quiet=True), results)
        _run("msis_linf.estimate_full", lambda: SIS.estimate(sis, quiet=True), results)

    try:
        import sage.version as sage_version
        sage_release = sage_version.version
    except ImportError:
        sage_release = "unknown"
    report = {
        "parameter_set": "bdlop-open-128-v1",
        "estimator": "malb/lattice-estimator",
        "estimator_commit": arguments.estimator_commit,
        "sage_version": sage_release,
        "instances": {
            "mlwe": {"n": MLWE_RANK * DEGREE, "m": (MSIS_RANK + 1) * DEGREE, "q": MODULUS,
                     "Xs": "uniform{-1,0,1}", "Xe": "uniform{-1,0,1}"},
            "msis_linf": {"n": MSIS_RANK * DEGREE, "m": WIDTH * DEGREE, "q": MODULUS,
                          "norm": "inf", "length_bound": BINDING_BOUND,
                          "length_bound_log2": round(math.log2(BINDING_BOUND), 2)},
            "msis_l2_from_linf": {"length_bound": l2_bound,
                                  "length_bound_log2": round(math.log2(l2_bound), 2),
                                  "q_log2": round(math.log2(MODULUS), 2)},
        },
        "results": results,
    }
    with open(arguments.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
