# Payload range proof: binding the binary proof to the payload (stream C3)

Status: implemented as `src/lattice_zk/payload_range_proof.py` (parameter
sets `bdlop-payload-range-128-v1` on top of `bdlop-open-128-v2`, and
`bdlop-payload-range-toy-v1` for tests), tests in
`src/runtest/test_latticezk_payload_range_proof.py`, theorem in
`docs/paper/sections/binary_proof.tex` (`sec:payload-range`, `thm:pay`), benchmark
`benchmark/latticezk_payload_range_proof_bench.py` →
`benchmark/results/q2/payload_range_proof_bench.json`. Unaudited research
code; not constant time. Nothing in the base parameter sets, the opening,
equality and binary proofs, or the envelope formats changes.

## 1. What is proved

Public input: statement bytes `x`, a **public** payload length `L`
(`0 ≤ L ≤ 128`), and a commitment `C = (t1, t2)` made by `bdlop.commit`
under `bdlop-open-128-v2`, e.g. the commitment of an in-band envelope
(`linkage.envelope_commitment`) or of a registered credential.

The proof shows knowledge (relaxed, see below) of an opening of `C` whose
message is exactly

```text
m = codec.encode_payload(p)   for some p ∈ {0,1}^{8L}
```

Equivalently:

- every coefficient of `m` lies in `[0, 2^24)` and is the 3-byte packing of
  the framed bytes `len(p) ‖ p`, i.e. an exact 24-bit range proof on the
  payload coefficients, tied to the payload by a bit decomposition;
- coefficient 0 carries the length field `L`;
- every coefficient from `⌈(L + 2)/3⌉` on is zero, so `decode_payload(m)`
  succeeds and returns an `L`-byte payload.

The proof reveals `L` and nothing else about `p` (zero knowledge as for the
binary proof). Because the base commitment is binding with respect to relaxed
openings, a later disclosure (`video_proof.create_commitment_disclosure`,
an equality proof against `Com(encode(p'); 0)`) can only reveal `p' = p`.

Precisely (Theorem `thm:pay` with `thm:bin-ks`): an extractor that rewinds
only the last oracle query outputs a relaxed opening `(r̄, f̄)` of `C`,
`f̄ ∈ C̄`, `‖r̄‖∞ ≤ 2B`, whose message `m̄ = t2 − f̄⁻¹⟨b2, r̄⟩` equals
`encode_payload(p)` for some `L`-byte `p`, or an M-SIS solution of
`ℓ∞ ≤ 8κB` for `B1` or the auxiliary `B1'`.

Not proved: anything about the *value* of `p` (that it is a digest, a
credential, or lies in a numeric range); a hidden length; payloads above
128 bytes. See Section 7.

## 2. Options considered

The binary proof (`bdlop-binary-128-v2`, 43 022 B) shows that a commitment
hides a 256-bit string, but in-band payload commitments use the 24-bit
encoding of `codec.encode_payload`, so it said nothing about the payload.

| Option | Statement | Size (production) | Acceptance / attempt | Verdict |
|---|---|---|---|---|
| (a-full) bit-plane decomposition `m = Σ_{j<24} 2^j b_j` of all 256 coefficients, every `b_j` binary | every coefficient in `[0, 2^24)` (not the full encoder image: length and zero padding unchecked) | 256 526 B (ℓ = 24, 177 response polys) | 8.2·10⁻¹⁰ (≈1.2·10⁹ attempts) | impractical at the pinned mask bound `γ = 2^17`; needs a larger auxiliary mask bound and a new M-SIS estimate |
| (a-full, independent proofs) 24 binary commitments + 24 binary proofs + a linear proof over 25 commitments | same | ≈1.4 MB | the linear proof alone accepts with `0.191^25 ≈ 10⁻¹⁸` | impractical |
| **(a′) chosen**: bits of the payload only (public `L`), link `m = e_L + A β` folded into the binary proof's check round | `m = encode_payload(p)`, `|p| = L` (full encoder image) | 44 558 B for `L ≤ 32`, +9 216 B per further 32 B (72 206 B at 128) | 0.0100 (ℓ = 1) … 0.0012 (ℓ = 4) | **implemented** |
| (b) binary envelope from the start: `Com(encode_bits(p))`, existing binary proof per 32 B | `C` hides a 32-byte string | 6 720 + 43 022 = 49 742 B per 32 B | 0.0112 | works with no new proof, but needs a new envelope version and a new disclosure encoding; ℓ independent proofs for longer payloads |

Option (a′) costs 1 536 B more than the binary proof and, unlike (b), applies
to the *existing* payload commitment: no new envelope format, the existing
disclosure and linkage proofs apply unchanged, and the proof can be produced
out of band for a video that was embedded before. With the commitment
counted, (a′) is 6 720 + 44 558 = 51 278 B against 49 742 B for (b), so the
two are within 3 %. Option (b) needs no new code (it is
`binary_proof.prove(BINARY_128, x, Com(encode_bits(p)), …)`) and is
therefore not reimplemented; its sizes are in the benchmark JSON.

Why (a′) is so much cheaper than (a-full): binarity of a polynomial costs `k`
lift polynomials (design doc §2.2, the Toeplitz argument), so the cost scales
with the number of *bit polynomials*. A short payload has `8L` payload bits,
which fill `⌈8L/256⌉` polynomials, while the 24 bit-planes of a full
coefficient vector always need 24. The zero coefficients and the length
field are public-affine and cost nothing: they are part of the link
`m − A β − e_L = 0`.

## 3. Protocol (`payload_range_proof._prove`, `_recomputed_seed`)

Notation as in `docs/BINARY_PROOF_DESIGN.md` §3; `k = k' = 5`.

- **Encoding map.** `encode_payload(p) = e_L + A β(p)`, `e_L = encode_payload(0^L)`
  (only coefficient 0 is nonzero: `256 L`), `β(p)` the bits of `p`
  (MSB first) in `ℓ = max(1, ⌈8L/N⌉)` binary polynomials `β_j`, and `A`
  the public map that sends payload bit `s` to coefficient
  `⌊(2 + ⌊s/8⌋)/3⌋` with weight `2^{8(2 − (2+⌊s/8⌋) mod 3) + 7 − s mod 8}`
  (`payload_encoding`, `decompose`, `recompose`; checked against `codec` for
  every length in the tests).
1. Fresh ternary `r'` (hedged from the entropy, `x`, `pid`, `L`, `C`, `m`,
   `r` and the bits). `D_0 = (t1' = B1' r', t_{β_j} = ⟨b_{β_j}, r'⟩ + β_j)`.
2. `γ_{j,i} ← H_lift(pid, x, L, C, D_0)` for `j < ℓ`, `i < k`.
3. `D_1 = (t_{u_{j,i}} = ⟨b_u, r'⟩ + σ(γ_{j,i} ∘ β_j), t_{g_t} = ⟨b_g, r'⟩ + g_t)`
   with `ct(g_t) = 0`; same `r'`, new rows of the same auxiliary key.
4. `ρ_{t,(j,i)}, μ_{t,(j,i)}, ρ^L_t ← H_check(seed, D_1)`; the prover sends
   `h_t = g_t + E_t` without its constant coefficient, where
   `E_t = Σ_{j,i} [σ(ρ) u − R β_j + μ u (β_j − J)] + σ(ρ^L_t) m
   − Σ_j σ(A_j^T ρ^L_t) β_j − ⟨ρ^L_t, e_L⟩`, so
   `ct(E_t) = Σ ⟨ρ, Δ⟩ + μ Q + ⟨ρ^L_t, m − A β − e_L⟩`
   (`test_check_polynomial_constant_term_is_the_random_functional_of_the_error`,
   `test_link_functional_is_the_transpose_of_the_encoding`).
5. `α_t ← H_combine(seed, h)`: `P = Σ_j ψ_j β_j + L(m, β, u, g) − Σ_t α_t(h_t + ⟨ρ^L_t, e_L⟩)`
   with `ψ_j = Σ_i β'_{j,i} u_{j,i}`.
6. Per attempt (only this step repeats on abort): masks `y, y'`, garbage
   `G = −(Σ_j ψ_j a_{β_j} + a_{ψ_j} β_j + L(a))` committed in slot `G` of `D`,
   `c = SampleInBall(H_c(seed, t_G, w, w', v))`, `v = Σ_j a_{ψ_j} a_{β_j} + a_G`;
   `z = y + c r`, `z' = y' + c r'`, restart unless both lie in `[−B, B]`.
7. Verifier: recomputes every seed and
   `v = Σ_j f_{ψ_j} f_{β_j} + c (L(f) − c H') − f_G`.

Proof bytes: `Pack(D_0) ‖ Pack(D_1) ‖ Pack(h without ct) ‖ Pack(t_G) ‖ seed ‖ Pack(z, z')`.
Decoding is strict (exact length for `L`, every packed value in range, zero
padding). The auxiliary key is expanded from `parameter_id ‖ ℓ`, so every
`ℓ` has its own key, and `r'` is never reused under two keys.

## 4. Soundness

Round errors (same as the binary proof; `L` does not change them):

| Round | Bad event | Error |
|---|---|---|
| lift (`γ`) | some `β̄_j` non-binary and all `⟨γ_{j,i}, β̄_j ∘ (β̄_j − J)⟩ = 0` | `q^-k = 2^-150` |
| check (`ρ, μ, ρ^L`) | error `e = (Δ, Q, m̄ − Aβ̄ − e_L) ≠ 0` fixed before, and `ct(ḡ_t) + φ_t(e) = 0` for all `t` | `q^-k' = 2^-150` |
| combine (`α`) | `Σ α_t P̄_t = 0` with some `P̄_t ≠ 0` | `q^-N/2 = 2^-3840` |
| challenge (`c`) | `c` a root of a nonzero quadratic | `2/|C| = 2^-256` |

`m̄ − Aβ̄ − e_L` is fixed by `C` and `D_0`, both hashed before `ρ^L`; if it is
zero and `β̄` is binary, then `m̄ = Aβ̄ + e_L` over the integers (all values are
below `2^24 < q`), i.e. `m̄ = encode_payload(p)`.

Non-interactive knowledge soundness (Theorem `thm:bin-ks`, applies verbatim):
an adversary with `Q` oracle queries that makes the verifier accept a false
statement succeeds with probability at most

```text
(Q + 1)(q^-k + q^-k' + q^-N/2 + 2/|C|) + Σ_{i=1..3} sqrt((Q + 1) α_i) + β + Q^2 2^-256
```

where `α_i, β` are the probabilities that explicit forking algorithms find an
M-SIS solution of `ℓ∞ ≤ 8κB`. The statistical part is `(Q + 1)·2^-149.99`;
the M-SIS terms have the usual square-root forking loss (as for the opening
proof, Lemma `lem:fork`). Aborts repeat only the last round; extraction
forks only the last oracle (AFK22's Σ-protocol extractor, expected `3 + 2Q`
runs), and the statistical rounds are bounded by a plurality argument against
the computationally bound messages. The sketch is in
`docs/paper/sections/binary_proof.tex` after Theorem `thm:bin-rbr`, with the
remaining gaps listed there.

## 5. Concrete security of the auxiliary key

Pinned CRYSTALS model (`python research/bdlop_params/estimate.py --estimator
<security-estimates> --parameter-set PAYLOAD_RANGE_128 --binary-polys ℓ`):
for `ℓ = 1` (M-SIS `6 × 25`, 18 M-LWE samples) and `ℓ = 4` (`6 × 43`, 36
samples) the levels equal the base set's: M-SIS β = 480 (140 / 127 bits),
primal M-LWE β = 580 (169 / 153), dual β = 578
(`research/bdlop_params/bdlop_payload_range_128_l{1,4}.estimate.json`). The
reason is that of the binary proof (design doc §7): the optimal M-SIS
sub-dimension is below every width and extra M-LWE samples beyond the optimum
do not help. The lattice-estimator dual-hybrid cross-check (164 / 150 bits for
the base) was not re-run for these instances.

## 6. Sizes and timings (production, `bdlop-payload-range-128-v1`)

| `L` (bytes) | ℓ | Proof bytes | Acceptance | Expected attempts |
|---|---|---|---|---|
| 0–32 | 1 | 44 558 | 0.00996 | 100 |
| 33–64 | 2 | 53 774 | 0.00490 | 204 |
| 65–96 | 3 | 62 990 | 0.00241 | 415 |
| 97–128 | 4 | 72 206 | 0.00119 | 843 |

Parts for ℓ = 1: `D_0` 6 720, `D_1` 9 600, `h` 4 782, `t_G` 960, seed 32,
responses (39 polys × 256 × 18 bits) 22 464. Attempt cap `2^17`: all-abort
probability `2^-1892` (ℓ = 1), `2^-225` (ℓ = 4).

Measured (`benchmark/results/q2/payload_range_proof_bench.json`, 10 runs,
fresh payload/randomness/entropy per run, Python 3.12 single thread, laptop
**heavily loaded by a concurrent benchmark sweep**, so absolute times are
pessimistic and noisy; compare with the binary proof only on the same host):

| `L` | prove median (ms) | prove mean | attempts mean (expected) | verify median (ms) |
|---|---|---|---|---|
| 32 | 2 049 | 6 683 | 54.7 (100.4) | 228 |
| 64 | 24 120 | 32 909 | 153.5 (204.1) | 514 |

Per attempt about 120 ms (ℓ = 1) and 210 ms (ℓ = 2) on that host; in a
same-host comparison the ℓ = 1 attempt costs 1.2–1.45× a binary-proof
attempt. Prover time is dominated by the geometric number of attempts.

Tests: 61 in `test_latticezk_payload_range_proof.py` (about 10 s, including a
production KAT and a production ℓ = 2 proof); line coverage of
`payload_range_proof.py` 99 % (the one missed line is an internal
consistency guard).

## 7. Open questions for an external cryptographer

1. Check the link term: `ρ^L_t` is drawn with the check challenges, after
   `C` and `D_0` (which fix `m̄` and `β̄`) are hashed. Is folding the
   Z_q-linear relation `m = Aβ + e_L` into the same `k'` functionals as the
   lift-consistency checks sound (one error vector, one uniform functional)?
2. `β` is committed in `D_0` before `γ` and the lifts are added later under
   the same `r'`. We argue that binding w.r.t. relaxed openings of `t1'` fixes
   every row's message; is this incremental use of one BDLOP randomness
   vector covered by the standard binding/hiding arguments?
3. Check the knowledge-soundness sketch (`thm:bin-ks`): the plurality
   argument for the statistical rounds, the use of AFK22 with an adaptively
   chosen prefix, and the `Q^2 2^-256` seed-ordering term.
4. A hidden length (`L` secret, `≤ 32ℓ`) would need a proof that bytes after
   `L` are zero, e.g. with a committed one-hot length indicator and one more
   quadratic relation. Is there a cheaper way?
5. A full 24-bit range proof of all 256 coefficients is impractical at the
   pinned mask bound (Section 2). Would a separate, larger mask bound for the
   auxiliary key (with a fresh M-SIS estimate at the larger `8κB'`) be
   acceptable, or is a different technique (e.g. a smaller digit base, or
   LNP22-style approximate range proofs) preferable?
