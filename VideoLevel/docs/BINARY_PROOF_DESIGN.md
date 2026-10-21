# Binary-message proof for BDLOP commitments (roadmap B2)

Status: implemented as `src/lattice_zk/binary_proof.py` (parameter sets
`bdlop-binary-128-v2` and `bdlop-binary-toy-v1`), tests in
`src/runtest/test_latticezk_binary_proof.py`, theorem drafts in
`docs/paper/sections/binary_proof.tex` (not wired into `main.tex`).
Unaudited research code; not constant time.

## 1. What is proved

Statement: bytes `x` and a commitment `C = (t1, t2) = Com(m; r)` made by
`bdlop.commit` under the unchanged base set `bdlop-open-128-v2`.
The proof shows knowledge of a relaxed opening of `C` whose message `m̄` has
every coefficient in `{0, 1}`, i.e. `C` hides a 256-bit string
(`encode_bits` / `decode_bits`, 32 bytes, most significant bit first).

`C` is an ordinary base commitment, so the opening, equality and disclosure
proofs apply to it unchanged (test
`test_binary_commitment_stays_compatible_with_the_base_proofs`). Nothing in
`bdlop-open-128-v2`, its key, its proofs or the envelope formats changes.

## 2. Design decision

### 2.1 Why not ALS20 / ENS20 as published

ALS20 (Attema–Lyubashevsky–Seiler, CRYPTO 2020) proves ring-level products
`m·(m − 1) = 0` in `R_q`. In a ring that splits into `l` factors, that only
makes each CRT slot of `m` lie in `{0, 1}`, so it encodes `l` bits per
polynomial; binary *coefficients* need the message in NTT slots of a fully
(or almost fully) splitting ring (ENS20, BLS19). With `q ≡ 5 (mod 8)` our
ring has two slots: 2 bits per polynomial. Options considered:

- **(a) New fully splitting modulus** (`q ≡ 1 mod 2N`). Rejected: challenge
  differences are then not guaranteed invertible, so the opening-proof
  extraction of the spec (§4.3) breaks; the product proof has per-slot error
  ≈ `1/q` and needs ALS20's automorphism amplification; binding/hiding would
  need a new estimator run; the commitment would no longer be a
  `bdlop-open-128-v2` commitment.
- **(b) NTT-slot encoding over our ring.** Impossible: two slots.
- **(c) Chosen.** Keep the ring and the base commitment; prove the
  coefficient-wise relation with the constant-coefficient / automorphism
  linearization of LNP22 (Lyubashevsky–Nguyen–Plançon, CRYPTO 2022) and an
  ALS20-style quadratic (product) proof. Our ring is the favourable case for
  the product part: because `c − c'` is invertible for distinct challenges,
  a nonzero degree-2 polynomial over `R_q` vanishes on at most `2` challenges
  per CRT component, and `c ↦ c mod φ` is injective on the challenge set,
  so the product round has error `2/|C| = 2^-256`. The construction below
  is our own instantiation of these techniques; it is not copied from either
  paper, and it has not been reviewed by their authors.

### 2.2 Why auxiliary "lifts" are necessary

With `σ(X) = X^-1` we have `ct(σ(a)·b) = <a, b>`, and any quadratic form an
honest verifier can reach from one committed polynomial `m` with ring
operations, `σ` and `ct` is `m^T T_w m` with `T_w` negacyclic Toeplitz. Its
diagonal is `w_0·I`, so it only ever sees `Σ m_j^2`, never a random diagonal
form `Σ γ_j m_j^2`. Binarity of all `N` coefficients needs random diagonal
forms, so the prover must commit to `u_i = σ(γ_i ∘ m)` after `γ_i` is known
and prove the (Z_q-linear, not R_q-linear) consistency of `u_i` with `m`.

### 2.3 Why a fresh auxiliary commitment

If the lifts were committed with the base randomness `r` (extra BDLOP slots),
two proofs for one commitment would publish `t_u − t'_u = σ((γ − γ') ∘ m)`
and reveal `m`. Every proof therefore creates a fresh commitment
`D = Com_aux(u, g, G; r')` under its own key (domain-separated from the
base key), and the product proof uses masked openings of both `C` and `D`
with one challenge, as the equality proof does. `C` can be proved binary any
number of times.

## 3. Protocol (`binary_proof._prove`, `_recomputed_seed`)

`k` = lift repetitions, `k'` = check repetitions (5 and 5 in production);
`J` = all-ones polynomial; all seeds are 32-byte SHAKE-256 outputs, each
domain-separated and chained to the previous seed.

1. `γ_1..γ_k ← H_lift(pid, x, C)` (uniform in `Z_q^N`).
2. Prover: `u_i = σ(γ_i ∘ m)`, `g_t` uniform with `ct(g_t) = 0`, fresh ternary
   `r'`; sends `D = (B1' r', <b_{u_i}, r'> + u_i, <b_{g_t}, r'> + g_t)`.
3. `ρ_{t,i} ∈ Z_q^N, μ_{t,i} ∈ Z_q ← H_check(seed, D)`. With
   `R_{t,i} = σ(γ_i ∘ σ(ρ_{t,i}))` the prover sends
   `h_t = g_t + Σ_i [σ(ρ_{t,i}) u_i − R_{t,i} m + μ_{t,i} u_i (m − J)]`
   without its constant coefficient (implicitly 0). One checks
   `ct(h_t) − ct(g_t) = Σ_i <ρ_{t,i}, Δ_i> + μ_{t,i} Q_i` with
   `Δ_i = u_i − σ(γ_i ∘ m)`, `Q_i = ct(u_i (m − J))`, and
   `Q_i = <γ_i, m ∘ (m − 1)>` when `Δ_i = 0`
   (`test_check_polynomial_constant_term_is_the_random_functional_of_the_error`).
4. `α_t ∈ R_q ← H_combine(seed, h)`; `P = Σ_t α_t (g_t + E_t − h_t)`, a
   quadratic relation `ψ·m + L(m, u, g) − H = 0` with `ψ = Σ_i β_i u_i`.
5. Each attempt: masks `y, y'`; with `a_j = <b_j, y or y'>` the prover
   commits the garbage `G = −(ψ a_m + a_ψ m + L(a))` in slot `G` of `D`, and
   hashes `t_G, w = B1 y, w' = B1' y', v = a_ψ a_m + a_G` into
   `c = SampleInBall(H_c(seed, t_G, w, w', v))`; answers
   `z = y + c r`, `z' = y' + c r'`, restarting unless both are in `[−B, B]`.
6. Verifier: recomputes every seed, `w = B1 z − c t1`, `w' = B1' z' − c t1'`,
   the masked openings `f_j = c t_j − <b_j, z>`, and
   `v = f_ψ f_m + c (L(f) − c H) − f_G`, and compares the final seed. Honestly
   `v = c^2 P + Γ0 + a_G` with `P = 0`.

Decoding is strict: exact length, every packed coefficient in range, zero
padding, `ct(h_t) = 0` by construction, canonical commitments only.
Randomness is hedged (`opening_proof.hedged_mask_key` over the entropy,
statement, binary `parameter_id`, commitment, message and `r`), so even an
explicit known-answer seed never reuses `r'` under two auxiliary keys.

## 4. Soundness

Round-by-round errors of the interactive protocol, for a statement whose
committed (relaxed-opening) message is not binary, assuming no M-SIS solution
is found for the base key or the auxiliary key:

| Round | Bad event | Error |
|---|---|---|
| lift (`γ`) | all `<γ_i, m̄ ∘ (m̄ − 1)> = 0` | `q^-k = 2^-150` |
| check (`ρ, μ`) | `φ_t(e) = −ct(ḡ_t)` for all `t`, error `e ≠ 0` fixed before `ρ` | `q^-k' = 2^-150` |
| combine (`α`) | `Σ α_t P̄_t = 0` with some `P̄_t ≠ 0` | `q^-N/2 = 2^-3840` |
| challenge (`c`) | `c` is a root of `c^2 P̄ + c X + Y` with `P̄ ≠ 0` | `2/|C| = 2^-256` |

The masks `g_t` must be committed before `ρ`, and `D` after `γ`; `h` before
`α`; `t_G, w, w', v` before `c` — the implementation hashes in exactly this
order. Round-by-round soundness `ε_rbr = 2^-149.99` gives Fiat–Shamir
soundness `≤ (Q_H + 1)·ε_rbr` against `Q_H` hash queries (Canetti et al.,
STOC 2019; Attema–Fehr–Klooß, TCC 2022): an attacker who makes `Q_H` queries
forges a binarity claim with probability at most `(Q_H + 1)·2^-150`, about
150 bits in the work-over-advantage metric (the base opening proof has 256).
Knowledge of the relaxed opening is extracted by forking the last
round exactly as in spec §4.3 (three accepting transcripts with pairwise
invertible challenge differences pin `P̄ = 0`, as in the equality proof).

The multi-round Fiat–Shamir-with-aborts composition is now written out
(paper, Theorem `thm:bin-ks`): aborts repeat only the last round, so a
rejected attempt is just a discarded `H_4` query; the extractor forks only
`H_4` (the Σ-protocol case of AFK22, expected `3 + 2Q` runs, error
`(Q + 1)·2/|C|`); and the three statistical rounds are bounded against the
*computationally* bound messages by a plurality/forking argument, giving
`(Q + 1)·ε_i + sqrt((Q + 1)·α_i)` per round with `α_i` the success
probability of an explicit M-SIS finder. Total:
`ε ≤ (Q + 1)·ε_rbr + Σ_i sqrt((Q + 1)·α_i) + β + Q²·2^-256`. Remaining gaps
are listed after the theorem (non-tight M-SIS terms, adaptive prefix in
AFK22, `SampleInBall` modelled as uniform, classical ROM only).

Consistency of masked openings: from two transcripts `y* = z − c r̄/f̄` is the
same for all accepting `c` unless `f̄(z − z'') − (c − c'')r̄` is a nonzero M-SIS
solution of norm `≤ 8κB` (the bound of spec §4.4), for `B1` and for `B1'`.

`bdlop-binary-toy-v1` (`k = k' = 2`, `q ≈ 2^20`) has 40-bit soundness and is
for tests only (`require_production_strength` rejects it).

## 5. Zero knowledge (sketch)

Accepted `(z, z')` are uniform on `[−B, B]` independently of `(r, r')`
(the uniform-masking argument of spec §4.2 over `kN + k_aux N` coefficients).
Hybrids: (1) sample `z, z'` uniformly and program the four random-oracle
points (the first message has min-entropy through `w`, `w'`); (2) replace
every row of `D` and `t_G` by uniform under M-LWE for the auxiliary key with
secret/error `r'` — `t_G`'s message `G` is a function of public values and
the witness only (ALS20 argument), so the reduction can compute it; (3) then
`g_t` appears only in `h_t`, which is uniform on `{ct = 0}`. `w, w', v` are
determined by the verification equations. `C` is hidden as before (spec §4.5).
`r` is reused across proofs only through rejection-sampled `z`, as for the
opening proof; `r'` is fresh for each proof.

## 6. Sizes and timings (production, `bdlop-binary-128-v2`)

| Part | Bytes |
|---|---|
| Statement commitment `C` (unchanged base) | 6 720 |
| Auxiliary commitment `t1'`, `t_u`, `t_g` (16 polys × 960) | 15 360 |
| Masks `h` (5 × 255 coefficients × 30 bits) | 4 782 |
| Garbage `t_G` | 960 |
| Challenge seed | 32 |
| Responses `z, z'` (38 polys × 256 × 18 bits) | 21 888 |
| **Proof total** | **43 022** |

Acceptance per attempt `((2B+1)/2γ)^{38·256} = 0.0112` (mean 89 attempts;
cap 16 384, all-abort probability `2^-266`). Measured timings (median of 20
runs, shared machine): see `benchmark/results/q2/binary_proof_bench.json`
and Section 9 (measured with `bdlop-binary-128-v1`; v2 measurement pending).

The arithmetic uses `fast_ring.py`: exact negacyclic products through
float64 matrix products on 15-bit limbs (all partial sums are integers below
`2^53`, so BLAS results are exact and order-independent), checked against
`ring.poly_mul` in the tests.

## 7. Concrete security of the auxiliary key

Same `q, N, n = 6, λ = 7, κ, γ` and the same M-SIS bound `8κB ≈ 2^25.9` as
the base; the auxiliary M-SIS matrix is `n × 24` (base: `n × 14`) and the
auxiliary M-LWE instance has `n + 11 = 17` ring samples (base: 7).
The pinned CRYSTALS estimate
(`research/bdlop_params/bdlop_binary_128_v2.estimate.json`) gives the same
levels as the base set: M-SIS β = 480 (140 / 127 bits), primal M-LWE β = 580
(169 / 153 bits), dual β = 578. The reasons:

- M-LWE: extra samples do not help beyond the optimum, so 7 and 17 available
  ring samples give the same block size. (For `bdlop-binary-128-v1` an own
  ADPS16 script gave 473 against the pinned base estimate 474.)
- M-SIS: the optimal attack dimension `sqrt(nN ln q / ln δ_480) ≈ 3 022`
  is below both widths (3 584 and 6 144), so the extra columns do not lower
  the block size of 480.

`python research/bdlop_params/estimate.py --estimator <security-estimates>
--parameter-set BINARY_128` runs the pinned model on the auxiliary instance
and produced that file.

## 8. Compatibility with the envelope

- Compatible: the statement commitment is a `bdlop-open-128-v2` commitment;
  existing proofs, disclosure and registry descriptors work on it unchanged.
- Not automatic: today's payload commitments encode `len ‖ payload` with three
  bytes per coefficient (`codec.encode_payload`), which is *not* binary; the
  binary proof applies to commitments of `encode_bits(32-byte string)` (for
  example a digest or a 256-bit credential secret).
- A 43.0 KB proof is about 2.9× the in-band envelope (14 885 bytes); carrying
  it in-band needs a new envelope version and the carrier capacity measured
  by the Q2 sweep. Out-of-band (registered mode, or alongside a disclosure)
  needs no format change. The integrator decides.
- Implemented since: `payload_range_proof.py` (`docs/PAYLOAD_RANGE_PROOF.md`)
  proves that an existing payload commitment hides `encode_payload(p)` for a
  public length `L ≤ 128`, by committing the payload bits in the auxiliary
  commitment and adding the Z_q-linear link `m = e_L + A β` as one more term of
  the check functionals (44 558 B for `L ≤ 32`). A range proof of all 256
  coefficients by 24 bit-planes would cost `24·(1 + k)` auxiliary
  polynomials (256 526 B, acceptance `8·10^-10`) and remains impractical.

## 9. Measured results

Measured with `bdlop-binary-128-v1` (v2 measurement pending).
`benchmark/results/q2/binary_proof_bench.json`: 20 runs, fresh message,
randomness and entropy per run, Intel Family 6 Model 154 laptop running
another benchmark at the same time, Python 3.12, single thread.

| | median | mean | min | p90 | max |
|---|---|---|---|---|---|
| prove (ms) | 2 208 | 3 011 | 456 | 9 490 | 11 342 |
| verify (ms) | 71.7 | 73.3 | 68.7 | 76.9 | 96.5 |
| attempts | 62.5 | 84.5 | | | 322 (expected 70.5) |

Prover time is dominated by the geometric number of attempts (about 30 ms
each). Tests: 45 in `test_latticezk_binary_proof.py` (about 8 s, including
one production-sized KAT proof), line coverage 100 % of `binary_proof.py`
and of `fast_ring.py`.

## 10. Open questions for an external cryptographer

1. Check the round-by-round analysis (Section 4), in particular that the
   masks `g_t` committed after `γ` but before `ρ` cannot be exploited, and
   that `ct(h_t) = 0` via the encoding is equivalent to an explicit check.
2. Check the multi-round Fiat–Shamir-with-aborts composition, now written out
   as Theorem `thm:bin-ks` (aborts restart only the last round with the
   earlier seeds fixed; extraction forks only the last hash; statistical
   rounds by a plurality argument with a square-root M-SIS term).
3. Confirm the auxiliary M-SIS/M-LWE estimates with the pinned estimator.
4. `k = k' = 5` gives `2^-150` per round. Matching the `2^-256` challenge
   space would need `k = k' = 9` (about +12 KB).
5. Whether a smaller construction exists over a two-slot ring (one lift
   polynomial per repetition seems necessary by the Toeplitz argument of 2.2,
   but the masks `g_t` and `h_t` might be shared).
