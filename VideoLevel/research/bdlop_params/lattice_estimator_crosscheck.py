"""Cross-check of a BDLOP parameter set with the malb/lattice-estimator (Sage).

The flattened LWE/SIS instances are derived from a parameter set in
src/lattice_zk/params.py (``--parameter-set``, default ``BDLOP_OPEN_128_V1``
so the recorded v1 result stays reproducible).  The estimator runs under Sage
in a container where the project is usually not importable, so the run has
two steps (exact commands in research/bdlop_params/CROSSCHECK.md):

    # 1. host, from VideoLevel/ (plain Python, no Sage needed)
    python research/bdlop_params/lattice_estimator_crosscheck.py \
        --parameter-set BDLOP_OPEN_128_V2 --write-instance instance_v2.json

    # 2. Sage / passagemath-standard, estimator checkout on PYTHONPATH
    cd lattice-estimator            # checkout e4333d9bf9ef42fd8a29651b0c559fba7ce0d834
    PYTHONPATH=. python /path/to/lattice_estimator_crosscheck.py \
        --instance-json instance_v2.json --output crosscheck_v2.json

If src/lattice_zk is importable (the script adds VideoLevel/ to sys.path),
step 2 can take ``--parameter-set`` directly instead of ``--instance-json``.

The module instances are flattened to plain LWE/SIS of dimension rank * N:

* Hiding (M-LWE): secret r_3 in S_1^lam, n + 1 ring samples, uniform ternary
  secret and error  ->  LWE(n = lam*N, m = (n+1)*N, q).
* Binding (M-SIS): B1 in R_q^(n x k), k = n + lam + 1, infinity-norm bound
  8*kappa*B  ->  SIS(n = n*N rows, m = k*N columns, q, ||x||_inf <= 8kB).

For v1 (n = lam = 6, N = 256): LWE n = 1536, m = 1792; SIS n = 1536,
m = 3328, bound 62 885 280.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

ESTIMATOR_COMMIT = "e4333d9bf9ef42fd8a29651b0c559fba7ce0d834"
DEFAULT_PARAMETER_SET = "BDLOP_OPEN_128_V1"


def instance_from_params(params) -> dict:
    """Flatten a ``BdlopParams`` into the LWE/SIS sizes used by the estimator."""
    degree, msis_rank, mlwe_rank = params.degree, params.msis_rank, params.mlwe_rank
    width = msis_rank + mlwe_rank + 1
    response_bound = params.mask_bound - params.challenge_weight - 1
    binding_bound = 8 * params.challenge_weight * response_bound
    if width != params.width or binding_bound != params.binding_norm_bound:
        raise ValueError("flattening disagrees with BdlopParams.width / binding_norm_bound")
    return {
        "parameter_set": params.name,
        "degree": degree,
        "modulus": params.modulus,
        "msis_rank": msis_rank,
        "mlwe_rank": mlwe_rank,
        "width": width,
        "challenge_weight": params.challenge_weight,
        "mask_bound": params.mask_bound,
        "binding_bound": binding_bound,
        "mlwe": {"n": mlwe_rank * degree, "m": (msis_rank + 1) * degree},
        "msis": {"n": msis_rank * degree, "m": width * degree},
    }


def load_instance(parameter_set: str) -> dict:
    """Import src/lattice_zk/params.py and flatten the named attribute."""
    parents = Path(__file__).resolve().parents
    if len(parents) > 2 and str(parents[2]) not in sys.path:  # VideoLevel/ inside the repo
        sys.path.insert(0, str(parents[2]))
    try:
        from src.lattice_zk import params as params_module
    except ImportError as error:
        raise SystemExit(
            f"cannot import src.lattice_zk.params ({error}); run with --write-instance "
            "on the host and pass the file here with --instance-json"
        ) from error
    params = getattr(params_module, parameter_set, None)
    if params is None:
        raise SystemExit(f"src/lattice_zk/params.py has no attribute {parameter_set!r}")
    return instance_from_params(params)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--parameter-set", default=DEFAULT_PARAMETER_SET,
                        help="attribute of src/lattice_zk/params.py (default %(default)s)")
    parser.add_argument("--instance-json", help="flattened instance written by --write-instance")
    parser.add_argument("--write-instance", help="write the flattened instance and exit (no Sage)")
    parser.add_argument("--output", help="estimator results JSON")
    parser.add_argument("--estimator-commit", default=ESTIMATOR_COMMIT)
    parser.add_argument("--skip-full", action="store_true", help="skip LWE.estimate / SIS.estimate")
    arguments = parser.parse_args()
    if not arguments.write_instance and not arguments.output:
        parser.error("one of --output or --write-instance is required")
    return arguments


def _number(value, oo):
    if value == oo:
        return "inf"
    try:
        return int(value) if value == int(value) and abs(value) < 2**53 else float(value)
    except (TypeError, ValueError, OverflowError):
        return str(value)


def _summarise(cost, sage) -> dict:
    out = {}
    for key, value in dict(cost).items():
        if key in ("rop", "red", "sieve", "guess", "mem", "N", "svp", "prob", "repetitions"):
            out[key + "_log2"] = ("inf" if value == sage.oo
                                  else round(float(sage.log(sage.RR(value), 2)), 2))
        elif key == "tag" or isinstance(value, str):
            out[key] = str(value)
        else:
            out[key] = _number(value, sage.oo)
    return out


def _runner(results: dict, sage, cost_type):
    def run(label: str, thunk) -> None:
        started = time.time()
        try:
            value = thunk()
            if not isinstance(value, cost_type):
                summary = {name: _summarise(cost, sage) for name, cost in value.items()}
            else:
                summary = _summarise(value, sage)
            results[label] = {"result": summary, "seconds": round(time.time() - started, 1)}
        except Exception as error:  # record and continue with the remaining attacks
            results[label] = {"error": f"{type(error).__name__}: {error}"}
        print(label, json.dumps(results[label]), flush=True)
    return run


def run_estimator(instance: dict, skip_full: bool) -> dict:
    import sage.all as sage  # noqa: F401  (Sage must be importable)
    from estimator import LWE, ND, RC, SIS  # type: ignore[import-not-found]
    from estimator.cost import Cost  # type: ignore[import-not-found]
    from estimator.lwe_parameters import LWEParameters  # type: ignore[import-not-found]
    from estimator.reduction import ADPS16  # type: ignore[import-not-found]
    from estimator.sis_parameters import SISParameters  # type: ignore[import-not-found]

    name, q, bound = instance["parameter_set"], instance["modulus"], instance["binding_bound"]
    ternary = ND.Uniform(-1, 1)
    lwe = LWEParameters(n=instance["mlwe"]["n"], q=q, Xs=ternary, Xe=ternary,
                        m=instance["mlwe"]["m"], tag=f"{name} M-LWE hiding")

    def msis(norm=sage.oo, length_bound=bound):
        return SISParameters(n=instance["msis"]["n"], q=q, length_bound=length_bound,
                             m=instance["msis"]["m"], norm=norm, tag=f"{name} M-SIS binding")

    sis, quantum, gsa = msis(), ADPS16(mode="quantum"), {"red_shape_model": "gsa"}
    results: dict = {}
    run = _runner(results, sage, Cost)
    run("mlwe.rough", lambda: LWE.estimate.rough(lwe, quiet=True))
    run("mlwe.primal_usvp.core_svp_classical",
        lambda: LWE.primal_usvp(lwe, red_cost_model=RC.ADPS16, **gsa))
    run("mlwe.primal_usvp.core_svp_quantum",
        lambda: LWE.primal_usvp(lwe, red_cost_model=quantum, **gsa))
    run("mlwe.primal_usvp.matzov", lambda: LWE.primal_usvp(lwe, red_cost_model=RC.MATZOV))
    run("mlwe.primal_bdd.matzov", lambda: LWE.primal_bdd(lwe, red_cost_model=RC.MATZOV))
    run("mlwe.dual_hybrid.core_svp_classical", lambda: LWE.dual_hybrid(lwe, red_cost_model=RC.ADPS16))
    run("mlwe.dual_hybrid.core_svp_quantum", lambda: LWE.dual_hybrid(lwe, red_cost_model=quantum))
    run("mlwe.dual_hybrid.matzov", lambda: LWE.dual_hybrid(lwe, red_cost_model=RC.MATZOV))

    run("msis_linf.rough", lambda: SIS.estimate.rough(sis, quiet=True))
    run("msis_linf.lattice.core_svp_classical",
        lambda: SIS.lattice(sis, red_cost_model=RC.ADPS16, red_shape_model="lgsa"))
    run("msis_linf.lattice.core_svp_quantum",
        lambda: SIS.lattice(sis, red_cost_model=quantum, red_shape_model="lgsa"))
    run("msis_linf.lattice.matzov", lambda: SIS.lattice(sis, red_cost_model=RC.MATZOV))
    # l2 conversion: ||x||_2 <= sqrt(m) * ||x||_inf exceeds q, so the l2 instance
    # is trivial (q * e_1 is a solution); recorded to show why l_inf is needed.
    l2_bound = math.floor(math.sqrt(instance["msis"]["m"]) * bound)
    run("msis_l2_from_linf.rough",
        lambda: SIS.estimate.rough(msis(norm=2, length_bound=l2_bound), quiet=True))

    if not skip_full:
        run("mlwe.estimate_full", lambda: LWE.estimate(lwe, deny_list=("arora-gb",), quiet=True))
        run("msis_linf.estimate_full", lambda: SIS.estimate(sis, quiet=True))
    return {"results": results, "l2_bound": l2_bound}


def _report(instance: dict, run: dict, estimator_commit: str) -> dict:
    try:
        import sage.version as sage_version
        sage_release = sage_version.version
    except ImportError:
        sage_release = "unknown"
    q, bound, l2_bound = instance["modulus"], instance["binding_bound"], run["l2_bound"]
    return {
        "parameter_set": instance["parameter_set"],
        "estimator": "malb/lattice-estimator",
        "estimator_commit": estimator_commit,
        "sage_version": sage_release,
        "instances": {
            "mlwe": {"n": instance["mlwe"]["n"], "m": instance["mlwe"]["m"], "q": q,
                     "Xs": "uniform{-1,0,1}", "Xe": "uniform{-1,0,1}"},
            "msis_linf": {"n": instance["msis"]["n"], "m": instance["msis"]["m"], "q": q,
                          "norm": "inf", "length_bound": bound,
                          "length_bound_log2": round(math.log2(bound), 2)},
            "msis_l2_from_linf": {"length_bound": l2_bound,
                                  "length_bound_log2": round(math.log2(l2_bound), 2),
                                  "q_log2": round(math.log2(q), 2)},
        },
        "results": run["results"],
    }


def main() -> int:
    arguments = _parse_arguments()
    if arguments.instance_json:
        with open(arguments.instance_json, encoding="utf-8") as handle:
            instance = json.load(handle)
    else:
        instance = load_instance(arguments.parameter_set)
    if arguments.write_instance:
        with open(arguments.write_instance, "w", encoding="utf-8") as handle:
            json.dump(instance, handle, indent=2)
            handle.write("\n")
        print(json.dumps(instance))
        return 0
    report = _report(instance, run_estimator(instance, arguments.skip_full),
                     arguments.estimator_commit)
    with open(arguments.output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
