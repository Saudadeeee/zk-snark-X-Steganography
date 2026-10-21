# Open questions for the reviewer

The questions are ranked by how much of the security argument fails if the
answer is "no". Every question names the claim it concerns, using the labels
of `docs/paper/sections/security.tex` and `security_appendix.tex`, and the
code it depends on. Line numbers are at commit `18c5123`. "Ours" marks what
the authors currently believe, so the reviewer can confirm or reject it
quickly.

---

## Tier 1: the main theorems depend on these

### Q1. Simulating the aborting prover in the classical ROM (Lemma `lem:sim`, hybrid G3)

The simulator never reproduces the random-oracle queries of rejected
attempts. The argument has two parts: (a) acceptance is *exactly*
independent of the witness and of `c` (Lemma `lem:hvzk`); (b) every hidden
query point contains `w = B1·y` with min-entropy at least
`η = nN·log2(2B+1) ≈ 27 647` bits, because `B1 = [I_n | B1']`. The
per-proof loss is `2(Q_H+Q_P)2^-256 + (A_max+1)(Q_H+(A_max+1)Q_P)2^-η`.

- Does this correctly avoid the flaw in earlier CMA-to-NMA proofs of
  Fiat–Shamir with aborts, which Barbosa et al. (CRYPTO 2023) found and
  Devevey et al. analysed? In particular, is it sound to replace a rejected
  attempt's challenge by a uniform `h_i` that is never written into `H_fs`,
  given that `y_i` comes from a hedged stream and not from fresh coins (G1–G2)?
- Is the min-entropy bound for a mask *conditioned on rejection* right? The
  paper uses `η_y − log2(1/(1−p_acc))`, which needs `η_y − 0.35 ≥ η`.
- Ours: correct in the classical ROM. The exact-uniformity property is what
  makes this simpler than the Gaussian case.
- Code: `opening_proof.py:77–136`, `sampling.py:60–66`.

### Q2. Relaxed-opening soundness at the ℓ∞ bound 8κB (Theorems `thm:binding`, `thm:se`)

Two extracted transcripts give `(r̄, f)` with `‖r̄‖∞ ≤ 2B` and `f ∈ C̄`.
Binding against two relaxed openings needs M-SIS for `B1` with
`‖x‖∞ ≤ β = 8κB = 62 885 280 ≈ 2^25.91`, which is about `q/17`. The
constructor enforces `2β < q` (`params.py:66–68`).

- Is `‖f'r̄ − f r̄'‖∞ ≤ ‖f'‖₁‖r̄‖∞ + ‖f‖₁‖r̄'‖∞ = 8κB` the right bound to
  estimate, and is `2β < q` the right side condition? (It makes `x ≢ 0 mod q`
  equivalent to `x ≠ 0` over ℤ.)
- The ℓ2 view is vacuous: `√(kN)·β ≈ 2^31.75 > q`, so `q·e1` already
  satisfies the ℓ2 bound (the lattice-estimator reports "trivially easy").
  Security therefore rests entirely on ℓ∞ M-SIS with a large bound. Are the
  ℓ∞ cost models (CRYSTALS `SIS_linf_cost` and lattice-estimator
  `SIS.lattice`, norm=∞) adequate this close to `q`? Is there an attack that
  exploits `β/q ≈ 1/17`, e.g. many coordinates near `±q/2` or the ζ trick of
  zeroing coordinates? The estimator optimum chose ζ = 0.
- Can the bound be tightened? For example, extract with one challenge
  difference fixed, or use the structure `r̄ = z − z'` (both in `[−B, B]`).
  Ours: 8κB is a correct, loose worst case.
- Numbers: β = 480, 140 / 127 bits (core-SVP classical/quantum) from both
  estimators. See `research/bdlop_params/CROSSCHECK.md`.

### Q3. Invertibility of challenge differences for q ≡ 5 mod 8 (Lemma `lem:invertible`)

The paper cites Lyubashevsky–Seiler (EUROCRYPT 2018), Corollary 1.2 with
k = 2: every nonzero `y` with `‖y‖∞ < √(q/2) ≈ 23 170` is invertible, and
`‖f‖∞ ≤ 2` for `f ∈ C̄`.

- Please confirm that the hypotheses hold: q prime, q ≡ 5 (mod 8), N = 256.
  Then `X^N+1 = (X^{N/2} − ρ)(X^{N/2} + ρ)` with `ρ² ≡ −1`, both factors
  irreducible (the order of q modulo 2N is N/2).
- Elementary check for k = 2, which we believe is enough: write
  `f = a(X) + X^{N/2}·b(X)`. Then `f ≡ a ± ρb` in each factor. Since each
  factor is irreducible, `f` is a non-unit only if `a_i ≡ ∓ρ b_i` for all i.
  That gives `a_i² + b_i² ≡ 0 (mod q)` with `0 < a_i² + b_i² ≤ 8 < q`, which
  is impossible. Is this airtight?
- Code: `ring.py:42–57` (modulus check, `√−1`), `params.py:63–65` (the
  constructor checks `2√2 < √q`), `ring.py:106–114` (`is_invertible`, used in
  tests only).

### Q4. Extraction loss and the meaning of "knowledge soundness" (Theorem `thm:se`, Lemma `lem:fork`)

The bound has the usual square-root loss of the general forking lemma: for
`Q_H = 2^64`, an extraction probability of `2^-128` gives only
`ε ≲ 2^-32`.

- Is the theorem worth stating in this form, or should the main claim be
  the tight SelfTargetMSIS route (Kiltz–Lyubashevsky–Schaffner 2018)? The
  cost is a non-standard assumption with no separate estimate here.
- The extractor outputs only a *relaxed* opening. The extracted message
  `m̄ = t2 − f⁻¹⟨b2, r̄⟩` need not be in the payload encoder's image
  (`codec.py:49–60`). Is it accurate to call the property "knowledge
  soundness bound to the statement", given that the statement is only bound
  to "some message" that a later disclosure must match?
- Does the programmed-point case in Theorem `thm:se` (an adversary reusing
  `(x_i, t_i, w_i)` with a new `z`) also cover a mauled `z` with the same
  seed? The paper turns this case into an M-SIS solution of norm ≤ 2B.

### Q5. M-LWE hiding instance and leakage through proofs (Theorem `thm:hiding`, Lemma `lem:mlwe-instance`)

Hiding maps `Com(m; r)` to an M-LWE sample of rank λ = 7 with n+1 = 7 ring
samples: `A ∈ R_q^{7×7}`, uniform ternary secret and error. Flattened, this
is LWE with n = 1792, m = 1792, q = 2^30−35 and σ = √(2/3).

- Is the map `(t1 − B'_{1,2}(t2 − m), t2 − m) = A·r3 + (r1, r2)` a bijection
  for fixed m, and is `A` uniform? Ours: yes. D11 corrected a typo in the
  specification.
- Estimates (see CROSSCHECK.md). Primal uSVP: β = 580, 169 / 153 bits.
  **Dual-hybrid in the lattice-estimator "rough" model: β = 564, 2^164.9
  classical, and β = 567, 2^150.3 quantum.** This is below the 169 / 153
  bits of the CRYSTALS primal/dual scripts and is the claimed 164 / 150. (For
  `bdlop-open-128-v1`, λ = 6, the same attack gave 2^135.2 / 2^123.3, which is
  why λ was raised to 7.) Is ~164 bits the correct headline? Should a hybrid attack on a
  uniform ternary secret, with only 1792 samples, be considered beyond what
  the estimator covers?
- Leakage. Registered credentials are proven many times with the same `r`.
  Each accepted `z` is exactly uniform on `[−B, B]^{kN}`, independent of `r`.
  Does any other output depend on `r`? Candidates: the attempt count, which
  is witness-independent; timing (CHECKLIST §7); and the hedged mask key
  (Q7). Does any of these give an M-LWE "hint"?

### Q6. Zero knowledge from rejection sampling with uniform masks (Lemma `lem:hvzk`)

Masks are uniform on `[−γ+1, γ]`, which is asymmetric. A response is
accepted iff `‖z‖∞ ≤ B = γ − κ − 1`. Since `‖c·r‖∞ ≤ κ`, every `z_i ∈ [−B, B]`
corresponds to one mask value in `[−γ+1, γ−1]`.

- Please confirm that acceptance is exactly
  `p_acc = ((2B+1)/2γ)^{kN} ≈ 0.1912` for every witness and challenge, and
  that accepted `z` is exactly uniform on `Z`. Also confirm that
  `B = γ − κ − 1` is the largest bound that preserves this.
- The mask sampler draws 18-bit values below `2γ = 2^18`, so there is no
  rejection at all (`sampling.py:60–66`). Is the exact-uniformity claim
  therefore immune to sampler bias?
- The chi-square test `test_accepted_response_coordinate_is_uniform_for_any_witness`
  only checks marginals on a tiny parameter set. Would the reviewer want a
  stronger empirical check?

---

## Tier 2: design choices that could change parameters or wording

### Q7. Hedged mask derivation and its domain separation (D7, open)

`K = SHA3-256(e ‖ u64(|x|) ‖ x ‖ u64(|t|) ‖ t ‖ u64(|r|) ‖ r)`, with 32
bytes of entropy `e` (`opening_proof.py:77–90`). The masks are
`y_i = SHAKE-256("…/bdlop-open/v1/mask\0" ‖ K ‖ u32(i))`. The equality proof
uses its own mask tag but the same `K` construction, over both commitments
and both witnesses (`equality_proof.py:124–131`).

- The SHA3-256 input has no domain tag. Its separation from the other
  (tagged) SHA3-256 uses relies on `e` being uniform. Should a tag be added?
  This changes the KATs. Is the ROM treatment of `H_hg` in G1 still right
  when `e` comes from a weak RNG?
- Is binding `K` to `(x, t, r)` enough against fault and nonce-reuse attacks
  of the "same mask, two challenges" kind? The opening and equality proofs
  never share `K`, because their inputs and mask tags differ.

### Q8. Equality proof: acceptance, attempt cap and the disclosure variant (Lemma `lem:eq-ss`, Theorem `thm:link`; D4 fixed)

An attempt is accepted with probability `p_acc² ≈ 0.0463`. The cap is 4096,
which gives a failure probability of about `2^-279`
(`equality_proof.py:46–64`).

- Is a larger cap free for zero knowledge? `A_max` enters `ε_zk` only
  through `2^-η` terms. Ours: yes.
- Disclosure proves equality between `t` and `Com(enc(p); 0) = (0, enc(p))`
  with witness `r_b = 0`, so `z_b = y_b`. Is the simulator for this
  degenerate witness still correct? Does extraction really force `r̄_b = 0`
  unless M-SIS is broken (appendix, "Disclosure by proof")?
- The announcement `u = ⟨b2, y_a − y_b⟩` reveals a linear combination of
  masks. Is min-entropy through `w_a` alone enough for the hidden-query
  argument?

### Q9. One global commitment key (D9, open)

`ck` is expanded by SHAKE-256 from `parameter_id`, which is fixed and public
(`bdlop.py:111–123`). Every user and every registry share one M-SIS matrix
and one M-LWE matrix.

- A one-time lattice reduction of cost about 2^140 against `[I | B1']`
  would break binding for every commitment ever made. Multi-target hiding
  loses a factor Q in Lemma `lem:row`. Should the key be per registry or per
  issuer, e.g. derived from the registry root? Is the concrete-security
  statement acceptable with a single key?
- Is a key derived from public data in the ROM ("nothing up my sleeve") an
  adequate model of a uniform key in the reductions? The appendix programs
  the key-expansion point before the adversary starts.

### Q10. Fiat–Shamir in the QROM (Section `sec:sec-qrom`; no theorem claimed)

All theorems are classical-ROM. The paper says "plausibly post-quantum" and
cites Barbosa et al. (QROM CMA-to-NMA for Fiat–Shamir with aborts), Don et
al. 2019 and Liu–Zhandry 2019.

- Do the measure-and-reprogram results of Don et al. apply to a Σ-protocol
  with relaxed special soundness and an aborting prover? If so, what loss
  should be quoted? Is "plausibly post-quantum" honest wording, or should it
  be weaker?
- The challenge seed has 256 bits and `|C| = 2^257`. Is that enough against
  Grover-style search in the QROM soundness bound? Ours: yes for 128-bit
  quantum security.

### Q11. Statement binding and uniqueness of encodings (Theorem `thm:se`, appendix items 1, 2, 5)

The opening proof hashes
`SHAKE-256(tag ‖ pid ‖ u64(|x|) ‖ x ‖ enc(t) ‖ enc(w))`. Only `x` is length
prefixed; `t` (6 720 bytes) and `w` (n·N big-endian 64-bit words) have
lengths fixed by `pid` (`opening_proof.py:43–51`). The statement is a
fixed-width 274-byte string (`video_proof.py:89–98`).

- Is the transcript injective? Does it include everything the extractor's
  statement needs? It hashes `t1` and `t2`, but not `ck` itself, which `pid`
  determines.
- The verifier takes only `N_s` from the envelope, and `N_s` is part of `x`.
  It reads all other statement fields from its own pins and from
  `Read(vid*)` (`video_pipeline.py:369–389`). Please check for any path
  where a prover-controlled value enters `x` unverified.
- Are the domain tags (key, randomness, Fiat–Shamir and mask for opening and
  equality, challenge-poly; each ending in its only NUL byte) prefix-free
  across *all* SHAKE-256 uses, including `XofStream` seeds?
- The payload encoding has a 2-byte length and 3 bytes per coefficient
  (`codec.py:36–60`). Is the "exact image" decoder enough for the
  disclosure claim `enc(p) = m̄`?

---

## Tier 3: engineering and wording (no parameter change expected)

### Q12. Production-strength enforcement only at pin resolution (resolved)

`require_production_strength()` (challenge space ≥ 2^256) runs in
`pins_from_registry` (`video_pipeline.py:192–193`). It does not run in
`verify_video_proof`, `verify_envelope` or `opening_proof.verify`. A caller
that builds `VerifierPins` by hand with the `TOY` set would accept toy
proofs. Should every verifier entry point refuse non-production parameters?

- **Resolved.** `video_proof.require_verifier_parameters` now runs first in
  every application-level verifier: `verify_video_proof` (inside the
  configuration check, before the video is read), `verify_envelope`,
  `verify_registered_envelope`, `verify_disclosure_proof`,
  `verify_commitment_disclosure`, `linkage.verify_linkage` and
  `pins_from_registry`. Each raises `ValueError` for a set below 2^256 unless
  the caller passes `allow_toy_parameters=True` (tests and the TOY benchmark
  only). The proof primitives (`opening_proof.verify`, `equality_proof.verify`,
  `binary_proof.verify`) stay parameter-agnostic building blocks; nothing in
  the video pipeline calls them except through the verifiers above.
  Tests: `src/runtest/test_hardening_d5_d7_d8.py` (hand-built TOY pins are
  refused).

### Q13. Session and replay semantics (Theorem `thm:replay`)

Store mode consumes `N_s` with a single conditional
`UPDATE … WHERE consumed_at IS NULL AND expires_at > now` inside
`BEGIN IMMEDIATE` (`zkp_sessions.py:181–205`). Stateless mode
(`expected_session`) gives no replay protection, and no mode prevents
relaying. Is this the right split of claims? Is the
`Q_H·Q_I·2^-256` precomputation bound for (iii) stated correctly?

### Q14. Remaining self-review items

- **D5** (resolved by a new codec policy): scope of the canonical digest.
  Unbound items were RBSP bits after the stop bit, raw-segment digests
  without a tag, and the segmenter version. Codec policy v2
  (`CODEC_POLICY_V2`, opt-in per carrier profile, new profile/policy/relation
  identifiers) hashes the full RBSP of carrier IDR NAL units with its length,
  tags raw-segment digests and types every segment digest, and pins the
  segmentation: the segments must be exactly the access-unit partition of
  the input, checked byte for byte, so the digest no longer depends on the
  segmenter. The ffmpeg version is deliberately not hashed (it would bind the
  verifier's installation, not the video). Codec policy v1 is unchanged byte
  for byte for existing videos and still leaves zero bits after the stop bit
  of a carrier NAL unit unbound: a zero byte appended there is accepted under
  v1 and rejected under v2 through the real transport
  (`test_zero_bits_after_the_stop_bit_are_accepted_by_v1_and_rejected_by_v2`).
- **D7** (resolved): the hedged mask key is domain-separated by a tag, the
  protocol label and the parameter id. `bdlop-open-128-v1` keeps the untagged
  derivation, so `kat_v1.json` is unchanged; `kat_v2.json` and the binary
  KAT were regenerated (commitments unchanged). Verification never recomputes
  a mask; proofs from either derivation verify.
- **D8** (resolved): `Commitment` carries its parameter set and rejects
  non-canonical coefficients at construction, holding read-only copies;
  verifiers still re-check objects built around the constructor.
- **D10** (open): `verify_statement_binding` serves only `lazer-v1`
  (`zkp_registry.py:170–220`). The BDLOP path uses `pins_from_registry`.
  This is API hygiene.
- **D11** (open): specification §4.2 cites an "ML-DSA specification,
  Appendix B" for the zero-knowledge argument. Please confirm or replace the
  reference.

### Q15. Concrete-estimate methodology

Core-SVP ignores reduction overheads, as for ML-DSA. The MATZOV cost model
gives 194 / 190 (M-LWE primal/dual-hybrid) and 171 (M-SIS) bits. Is reporting
core-SVP 140/127 (M-SIS) and 164/150 (M-LWE, the dual-hybrid minimum) the
right convention for a 128-bit claim? The quantum M-SIS figure is just below 128. See `research/bdlop_params/CROSSCHECK.md`.
