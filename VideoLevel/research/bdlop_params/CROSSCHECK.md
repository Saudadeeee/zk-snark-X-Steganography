# Cross-check of `bdlop-open-128-v1` with the lattice-estimator

`estimate.py` computes core-SVP costs with the CRYSTALS security-estimates
scripts (commit `75c26949`). This note repeats the estimate with the
**malb/lattice-estimator** (commit
`e4333d9bf9ef42fd8a29651b0c559fba7ce0d834`, 2026-10-17) running under Sage.
This is an independent code base with its own attack models. Raw results are
in `lattice_estimator_crosscheck.json`, and the script that produced them is
`lattice_estimator_crosscheck.py`.

## Instances

The module problems are flattened to plain LWE/SIS of dimension rank × N,
exactly as in `estimate.py` and in the reductions of
`docs/paper/sections/security.tex`:

| Problem | Flattened instance |
|---|---|
| M-LWE hiding (rank λ = 6, n+1 = 7 ring samples) | LWE n = 1536, m = 1792, q = 2^30 − 35, secret and error uniform on {−1, 0, 1} (σ = 0.82) |
| M-SIS binding (`B1 ∈ R_q^{6×13}`, ℓ∞ ≤ 8κB) | SIS n = 1536 rows, m = 3328 columns, q = 2^30 − 35, ℓ∞ bound 62 885 280 ≈ 2^25.91 |
| ℓ2 relaxation of the same bound | ℓ2 bound √3328 · 8κB = 3 627 777 624 ≈ 2^31.76 > q |

The script pins the parameters literally. To confirm they equal the code's
parameter set, run from `VideoLevel/`:

```
python -c "from src.lattice_zk.params import BDLOP_OPEN_128 as p; print(p.mlwe_rank*p.degree, (p.msis_rank+1)*p.degree, p.width*p.degree, p.modulus, p.binding_norm_bound)"
# 1536 1792 3328 1073741789 62885280
```

## Results

Core-SVP: classical 2^(0.292β), quantum 2^(0.265β), with no polynomial
factors, as in `estimate.py`. The estimator's `*.estimate.rough` uses this
model (`RC.ADPS16`, GSA/LGSA). The estimator's default model (`RC.MATZOV`) is
shown for context.

| Problem / attack | `estimate.py` (CRYSTALS) | lattice-estimator, core-SVP | lattice-estimator, MATZOV |
|---|---|---|---|
| M-SIS ℓ∞, lattice reduction | β = 480: **140 / 127** | β = 480: **140.2 / 127.2** | β = 484: 168.7 |
| M-LWE, primal uSVP | β = 474: **138 / 125** | β = 473: **138.1 / 125.4** | β = 473: 164.5 |
| M-LWE, primal BDD | — | — | β = 466: 162.9 |
| M-LWE, dual (no hybrid) | β = 472: 138 (classical) | — | β = 482: 168.0 |
| M-LWE, dual-hybrid | — | β = 463: **135.2** classical; β = 465: **123.3** quantum | β = 457: 161.2 |
| M-LWE, coded BKW / BDD-hybrid / BDD-MITM-hybrid | — | — | 319.5 / 162.9 / 239.9 |
| ℓ2 relaxation of the M-SIS bound | — | trivially easy (bound > q; `large_norm` ≈ 2^11.7) | — |

All numbers are log2 of the cost; pairs are classical / quantum.

Findings:

1. **M-SIS agrees.** Both tools give β = 480 and 140 / 127 bits. Neither
   estimate zeroes any coordinates (ζ = 0).
2. **M-LWE primal agrees** to within one block size: β = 473 against 474,
   and 138 / 125 bits from both.
3. **The dual-hybrid attack is cheaper than everything `estimate.py`
   considers.** Under the estimator's `rough` model it costs 2^135.2
   (classical) and 2^123.3 (quantum). That is about 3 and 2 bits below the
   reported 138 / 125, and below 128 bits in the quantum column. The figure
   mixes core-SVP reduction cost with an explicit guessing cost
   (2^129.6 for t = 70 guessed coordinates). The same `rough` model rates
   Kyber512's dual-hybrid 3 bits below its uSVP. Dual-attack cost models are
   themselves under debate (Ducas–Pulles, CRYPTO 2023). We still recommend
   quoting the minimum: **M-LWE 135 / 123 bits**.
4. **The ℓ2 view of binding is vacuous.** √(kN)·8κB exceeds q, so q·e1 is
   a valid ℓ2 solution. Binding therefore rests entirely on the ℓ∞ M-SIS
   estimate, which is also how ML-DSA's M-SIS is estimated.
5. Under the estimator's default MATZOV cost model, every attack on either
   instance costs at least 2^161.

## How it was run

The lattice-estimator needs Sage. On this Windows 11 machine:

- **WSL**: the only registered distribution is `docker-desktop` (Docker's
  internal VM). There is no user distribution with Sage.
- **conda/mamba**: not installed. Sage on conda-forge is Linux/macOS only.
  Native Windows `passagemath` wheels exist for `passagemath-categories` and
  `-modules` only, not for `-symbolics`, `-pari` or `-flint`, which the
  estimator imports through `sage.all`.
- **Docker** (used): Docker Desktop (engine/CLI 28.5.1) runs a `python:3.12-slim`
  container (`python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1`,
  CPython 3.12.15) with a 2 GB memory cap. It runs **passagemath-standard
  10.8.13**, the pip-installable modularized SageMath distribution (Sage
  library 10.8; numpy 2.5.4, scipy 1.18.1, mpmath 1.3.0). This was used
  instead of the multi-GB `sagemath/sagemath` image to limit RAM and disk
  use.

Commands (`$W` is a host directory mounted at `/work`):

```
docker desktop start
docker pull python:3.12-slim
docker run -d --name le-sage --memory=2g --memory-swap=2g -v "$W:/work" python:3.12-slim sleep infinity
docker exec le-sage pip install --no-cache-dir --only-binary=:all: passagemath-standard   # 10.8.13

# estimator source at the pinned commit (no git inside the container)
curl -sL -o "$W/le.tar.gz" https://github.com/malb/lattice-estimator/archive/e4333d9bf9ef42fd8a29651b0c559fba7ce0d834.tar.gz
tar -xzf "$W/le.tar.gz" -C "$W"
cp research/bdlop_params/lattice_estimator_crosscheck.py "$W/"

E=/work/lattice-estimator-e4333d9bf9ef42fd8a29651b0c559fba7ce0d834
# smoke test against the estimator README
docker exec -e PYTHONPATH=$E -w $E le-sage python -c \
  "from estimator import *; print(LWE.primal_usvp(schemes.Kyber512)); SIS.estimate.rough(schemes.Dilithium2_MSIS_WkUnf)"
# -> usvp rop 2^143.8, beta 406 ; lattice rop 2^123.5, beta 423   (identical to the README)

docker exec -e PYTHONPATH=$E -w $E le-sage \
  python /work/lattice_estimator_crosscheck.py --output /work/lattice_estimator_crosscheck.json
```

(Under Git Bash, prefix the `docker run`/`docker exec` lines with
`MSYS_NO_PATHCONV=1`.) The full run takes about 5 minutes. `LWE.estimate`
alone takes 256 s, with `arora-gb` denied because it does not apply to
m = 1792 ≪ n² samples. The run stayed within the 2 GB container cap (no OOM kill).

Estimator calls (see the script for details):

- `LWE.estimate.rough(lwe)`: `primal_usvp` and `dual_hybrid` with `RC.ADPS16`.
- `LWE.primal_usvp(lwe, red_cost_model=RC.ADPS16 | ADPS16("quantum") | RC.MATZOV, red_shape_model="gsa")`.
- `LWE.primal_bdd(lwe, red_cost_model=RC.MATZOV)`.
- `LWE.dual_hybrid(lwe, red_cost_model=RC.ADPS16 | ADPS16("quantum") | RC.MATZOV)`.
- `LWE.estimate(lwe, deny_list=("arora-gb",))` (default MATZOV model).
- `SIS.estimate.rough(sis)` and `SIS.lattice(sis, red_cost_model=RC.ADPS16 | ADPS16("quantum"), red_shape_model="lgsa")`.
- `SIS.lattice(sis, red_cost_model=RC.MATZOV)` and `SIS.estimate(sis)`.
- `SIS.estimate.rough` on the ℓ2 relaxation.

## Suggested text for the paper

This replaces `\todo{cross-check M-SIS/M-LWE estimates with lattice-estimator}`
in `docs/paper/main.tex`. It is not applied here.

> … an independent cross-check with the
> lattice-estimator~\cite{ref:aps15,ref:latticeestimator} (commit
> \texttt{e4333d9}, same core-SVP model) reproduces the M-SIS estimate
> ($\beta=480$, 140/127 bits) and the primal M-LWE estimate ($\beta=473$,
> 138/125 bits). Its dual-hybrid attack on M-LWE is slightly cheaper
> ($\beta=463$, $2^{135}$ classical; $2^{123}$ quantum), so we take
> 135/123 bits for hiding. The $\ell_2$ relaxation of the binding bound
> exceeds $q$, so binding rests on the $\ell_\infty$ estimate. Under the
> estimator's default cost model, every attack on either instance costs at
> least $2^{161}$.

If this text is adopted, the M-LWE row of `docs/paper/tables/params.tex`
(and the comment above `BDLOP_OPEN_128` in `src/lattice_zk/params.py`) should
read `135 / 123 bits` (dual-hybrid, β = 463). The alternative is to keep
138/125 and state explicitly that it is the primal estimate.
