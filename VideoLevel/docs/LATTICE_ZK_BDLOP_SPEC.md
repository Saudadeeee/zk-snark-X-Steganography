# BDLOP video proof: protocol specification and security argument

Version 1 (`bdlop-open-v1`), implemented in `src/lattice_zk/`. This document
specifies the exact algorithms the code runs and argues each security property
from published results. It is written so the protocol can be re-implemented
and checked against the known-answer vectors in
`research/bdlop_params/kat_v2.json` (production set `bdlop-open-128-v2`;
`kat_v1.json` pins the earlier set `bdlop-open-128-v1`).

The construction is the commitment and opening proof of Baum, Damgård,
Lyubashevsky, Oechsner and Peikert (SCN 2018, ePrint 2016/997), with three
deliberate deviations listed in Section 6. The implementation has not been
audited and is not constant time.

## 1. Notation

- `R = Z[X]/(X^N + 1)`, `R_q = R / qR`, `N` a power of two.
- `q` prime with `q ≡ 5 (mod 8)`. Then `X^N + 1` factors into exactly two
  irreducible polynomials of degree `N/2` modulo `q`, and every nonzero
  `y ∈ R_q` with `‖y‖∞ < q^{1/2}/√2` is invertible (Lyubashevsky–Seiler,
  EUROCRYPT 2018, Corollary 1.2 with `k = 2`).
- `n`: M-SIS rank, `λ`: M-LWE rank, one message polynomial, `k = n + λ + 1`.
- `S_1`: polynomials with coefficients in `{-1, 0, 1}`.
- `C = {c ∈ R : ‖c‖∞ = 1, ‖c‖₁ = κ}`, the challenge set, `|C| = binom(N, κ)·2^κ`.
- `γ`: mask bound (a power of two); `B = γ − κ − 1`: response bound.
- `H`: SHAKE-256 with the domain tags given below; all integers big-endian.

## 2. Parameters

| | `bdlop-open-128-v2` |
|---|---|
| `N`, `q` | 256, `2^30 − 35` |
| `n`, `λ`, `k` | 6, 7, 14 |
| `κ`, `γ`, `B` | 60, `2^17`, `2^17 − 61` |
| `|C|` | `2^257` |
| Commitment | `(n+1)·N·30` bits = 6 720 bytes |
| Opening proof | `32 + k·N·18` bits = 8 096 bytes |
| Equality proof | `32 + 2·k·N·18` bits = 16 160 bytes |
| Per-attempt acceptance | `((2B+1)/(2γ))^{kN} ≈ 0.191` |

`parameter_id = SHA3-256("zkstego/lattice-zk/bdlop-open/v1/parameters\0" ‖
len(name) ‖ name ‖ N ‖ q ‖ n ‖ λ ‖ κ ‖ γ ‖ setup_seed)` pins every value.

Concrete security, from `research/bdlop_params/estimate.py` with the
CRYSTALS security-estimates model (commit `75c26949`), core-SVP cost:

| Problem | Instance | Block size | Classical | Quantum |
|---|---|---|---|---|
| M-SIS (binding) | `B1 ∈ R_q^{n×k}`, `ℓ∞` bound `8κB ≈ 2^25.9` | 480 | 140 | 127 |
| M-LWE (hiding) | rank `λ`, `n+1` samples, ternary secret and error | 580 | 169 | 153 |
| M-LWE, dual hybrid (lattice-estimator `e4333d9`) | same | 564 / 567 | **164** | **150** |

Reduction losses are ignored, as for ML-DSA. The claimed hiding level is the
lower dual-hybrid figure; the cross-check also reproduces the M-SIS and primal
M-LWE rows (`research/bdlop_params/CROSSCHECK.md`). The quantum M-SIS figure,
127 bits, is just below 128. The earlier set `bdlop-open-128-v1` (λ = 6,
k = 13) has the same M-SIS estimate but only 135 / 123 bits for M-LWE (dual
hybrid, β = 463); this is why the production set raises λ to 7.

## 3. Algorithms

### 3.1 Public key

`B1 = [I_n | B1']` with `B1' ∈ R_q^{n×(λ+1)}`, `b2 = [0^n | 1 | b2']` with
`b2' ∈ R_q^{1×λ}`. Both are expanded by rejection sampling from
`H("zkstego/lattice-zk/bdlop-open/v1/key\0" ‖ parameter_id)`. There is no
trapdoor and no trusted setup.

### 3.2 Commit

Input payload `p` with `|p| ≤ N·⌊(log₂q − 1)/8⌋ − 2` bytes. Encode
`len(p) (2 bytes) ‖ p ‖ 0…` as `N` coefficients of three bytes each; this
encoding is injective and its image is checked on decode. Sample `r ← S_1^k`
and output `t1 = B1·r`, `t2 = ⟨b2, r⟩ + m`.

### 3.3 Prove (opening)

Input statement bytes `x`, commitment `t = (t1, t2)`, witness `r`.

1. Check `‖r‖∞ ≤ 1` and `B1·r = t1`; otherwise refuse.
2. `K = SHA3-256(entropy ‖ len(x) ‖ x ‖ len(t) ‖ t ‖ len(r) ‖ r)` (hedged).
3. For attempt `i = 1, 2, …` (at most 512):
   - `y ← [−γ+1, γ]^{kN}` from `H(mask-domain ‖ K ‖ i)`;
   - `w = B1·y`;
   - `seed = H(fs-domain ‖ parameter_id ‖ len(x) ‖ x ‖ t ‖ w)`, 32 bytes;
   - `c = SampleInBall(seed)` (ML-DSA-style Fisher–Yates over SHAKE output, weight `κ`);
   - `z = y + c·r`; if `‖z‖∞ ≤ B` output `π = seed ‖ Pack(z + B)`.

Nothing from a rejected attempt leaves the prover.

### 3.4 Verify (opening)

Reject unless `|π|` is exact, every packed value lies in `[0, 2B]` and the
padding bits are zero. Recompute `c` from `seed`, `w' = B1·z − c·t1`, and
accept iff `seed = H(fs-domain ‖ parameter_id ‖ len(x) ‖ x ‖ t ‖ w')`.

### 3.5 Equality proof

For `t_a = Com(m; r_a)` and `t_b = Com(m; r_b)` the prover samples `y_a, y_b`,
sends `w_a = B1·y_a`, `w_b = B1·y_b`, `u = ⟨b2, y_a − y_b⟩` through the hash,
and answers `z_a = y_a + c·r_a`, `z_b = y_b + c·r_b`, aborting unless both are
in range. The verifier recomputes `w_a, w_b` as in 3.4 and
`u' = ⟨b2, z_a − z_b⟩ − c·(t2_a − t2_b)`. The prover has its own cap of 4 096
attempts (`equality_proof.MAX_ATTEMPTS`; see 4.1). Either witness may be the
all-zero vector, which is ternary: `Com(m; 0) = (0, m)` is the public
commitment used for disclosure (3.7).

### 3.6 Video statement

The Fiat–Shamir statement `x` is the fixed-width encoding

```text
u16 version ‖ relation_id ‖ parameter_id ‖ registry_root ‖ u64 registry_epoch ‖
session_challenge ‖ codec_policy_id ‖ carrier_profile_id ‖ u64 carrier_count ‖
positions_hash ‖ video_commitment
```

with every digest 32 bytes. The verifier builds it only from its pinned
configuration (relation, registry root and epoch, codec policy, carrier
profile) and from values it recomputes from the received H.264 stream:
the carrier list (hence `carrier_count` and `positions_hash`) and
`video_commitment = SHA-256("zkstego/video-zk/video-commitment/v1\0" ‖ D)`.
`D` is computed over the stream split by `ffmpeg -c:v copy -f segment` into
segments of `frames_per_segment` frames:
`D = SHA-256("zkstego/canonical-h264-segmented/v1\0" ‖ u32 F ‖ u32 L ‖
(u32 i ‖ u32 frames_i ‖ d_i)_{i<L})`. For a segment that carries envelope
chunks, `d_i` is the SHA-256 of a tagged, length-delimited serialization of its
parsed NAL units (header fields, RBSP of NAL units without carriers, and for
carrier-bearing IDR NAL units the RBSP bits between carrier blocks up to the
stop bit, with each carrier block replaced by its coefficient vector in which
every carrier is normalized); for the other segments `d_i` is the SHA-256 of
the segment file. Because `D` normalizes exactly the positions that carry
the envelope, the proof can bind the video without depending on its own bits.
What `D` does not bind is listed in the paper's security section
(`docs/paper/sections/security.tex`, integrity limits).

The carrier profile also fixes a GOP policy (`src/gop_policy.py`), checked on
every segment before analysis: `all-intra` (default; every coded slice is IDR)
or `idr-carriers-inter-raw-v1` (GOP > 1: carriers only in IDR slices, P and
non-IDR I slices hashed as raw RBSP in `d_i`, every segment starting with an
IDR). Both require canonical emulation prevention, so RBSP equality is NAL
byte equality. A non-default policy is added to the carrier-profile
description as `"gop_policy"`; all-intra profile identifiers are unchanged.
See `docs/GOP_HD_SUPPORT.md`.

### 3.7 Envelope

```text
in-band     "ZKLB" ‖ 0x01 ‖ parameter_id ‖ session_challenge ‖ t ‖ π
registered  "ZKLR" ‖ 0x01 ‖ parameter_id ‖ session_challenge ‖ π
```

Carrier positions are ordered by a keyed shuffle. With a secret stego key
shared with the verifier the channel stays undetectable to anyone without the
key; with the key derived from public configuration
(`public_sync_key = SHA-256(domain ‖ parameter_id ‖ carrier_profile_id)`,
CLI `--public-carrier-order`) anyone holding the registry can verify, at the
cost of undetectability. The proof's soundness and zero knowledge do not depend
on this key.

In registered mode `t` is a credential commitment whose bytes are hashed into
the relation descriptor that the issuer signs (ML-DSA-65) into the registry.
The session challenge is a 32-byte value issued by the verifier and consumed
once, atomically, after a successful verification.

**Holder identity.** The issuer may bind the credential to a holder identifier
`h` (a non-empty NFC-normalized UTF-8 string of at most 256 bytes; CLI
`--holder-id`). The registry field set is unchanged: the descriptor's
`verifier_key_hash` becomes

```text
SHA-256(B1' ‖ b2' ‖ t ‖ SHA-256("zkstego/lattice-zk/video-pipeline/v1/holder-id\0" ‖ u16 |h| ‖ h))
```

instead of `SHA-256(B1' ‖ b2' ‖ t)` (key blocks as big-endian 64-bit words,
`t` packed as on the wire); every part has a length fixed by
`parameter_id`, so the encoding is unambiguous, and without `h` the
descriptor (and every existing registry) is unchanged. A holder id is refused
for in-band profiles. Pins resolve only when the verifier supplies the same
`h` (`pins_from_registry(..., holder_id=h)`), so the issuer's signature covers
"commitment `t` belongs to holder `h`".

**Pins and credential.** `verify_video_proof` recomputes the relation id of
`(parameter set, carrier profile, credential, holder id)` and raises
`ValueError` unless it equals `pins.relation_id`. A mismatch (pins resolved
for one credential used with another, in-band pins with a registered profile
or the reverse, a wrong or missing holder id) is verifier misconfiguration,
reported before the video is read; video content only ever yields
`valid = False`.

**Disclosure.** The holder reveals the payload `p` of a commitment `t` to one
recipient without handing over `r`:

```text
ctx         = "zkstego/lattice-zk/disclosure/v1\0" ‖ parameter_id ‖
              u64 32 ‖ statement_id ‖ u64 32 ‖ nonce
t'          = Com(encode(p); 0) = (0, encode(p))
π_eq        = equality proof (3.5) of (t, r) and (t', 0) for statement ctx
disclosure  = "ZKLD" ‖ 0x01 ‖ parameter_id ‖ u16 |p| ‖ p ‖ π_eq
```

`statement_id` names what is disclosed (the verified video statement id for
an in-band envelope; for a registered credential, any 32-byte id the
recipient names, such as the relation id) and `nonce` is a 32-byte value the
recipient chose, so a disclosure made for one recipient or one video does not
verify for another. The recipient recomputes `t'` from `p` and verifies `π_eq`
against the commitment it already holds (`verify_disclosure_proof` for an
envelope, `verify_commitment_disclosure` for a credential; CLI `disclose` and
`disclosure-verify`). Size: 39 bytes + `|p|` + 16 160 bytes for the
production set. The proof is transferable: a third party who trusts that the
nonce was fresh is convinced too. `self_check_opening` (formerly
`verify_disclosure`) checks `(p, r)` directly and is a holder-side self-check
only: anyone given `r` can prove knowledge of the opening for new statements.

## 4. Security argument

Throughout, `‖c·v‖∞ ≤ ‖c‖₁·‖v‖∞`.

### 4.1 Completeness

`‖c·r‖∞ ≤ κ`, so an honest attempt is accepted with probability
`((2B+1)/(2γ))^{kN}` (Section 2), the expected number of attempts is its
inverse (5.23 for the production set; measured 4.68 over 50 runs with
`bdlop-open-128-v1` (v2 measurement pending)), and an
accepted `z` satisfies the verification equation because `t1 = B1·r`.
The probability that 512 attempts all abort is `(1 − 0.191)^{512} < 2^{-156}`.
The equality proof (3.5) accepts with probability `0.191^2 ≈ 0.037` per
attempt (mean 27.4 attempts). It has its own cap of 4 096 attempts, so it
fails with probability `(1 − 0.037)^{4096} ≈ 2^{-220}` (the shared cap of 512
used before gave `2^{-35}` with `bdlop-open-128-v1`). The larger cap does not affect zero knowledge,
because acceptance is independent of the witness, including the zero witness
of a disclosure. `test_equality_prover_cap_gives_negligible_completeness_error`
checks the bound `< 2^{-128}` from the parameters.

### 4.2 Honest-verifier zero knowledge of accepted transcripts

Fix `c` and `v = c·r` with `‖v‖∞ ≤ κ`. For any `z0` with `‖z0‖∞ ≤ B`, the mask
`y = z0 − v` lies in `[−B−κ, B+κ] = [−γ+1, γ−1] ⊂ [−γ+1, γ]`. Hence every such
`z0` has probability exactly `(2γ)^{−kN}`, and conditioned on acceptance `z`
is uniform on `[−B, B]^{kN}` independently of `r`. A simulator samples `z`
uniformly from that set and `c` uniformly from `C`, sets
`w = B1·z − c·t1`, and programs the random oracle at
`(parameter_id, x, t, w)`. This is the argument of the ML-DSA specification
(Appendix B) applied to the BDLOP key; it requires `w` to have high
min-entropy, which holds because `B1 = [I_n | B1']` and `y` is uniform over
`2^{18·kN}` values. The bias that rejection sampling introduces in the random
oracle, missed by earlier analyses, is treated by Barbosa et al. (2023) and
Devevey et al. (2023); their fixed ROM proofs apply to this transform.

The test `test_accepted_response_coordinate_is_uniform_for_any_witness`
checks the uniformity on a small parameter set, and
`test_respond_accepts_exactly_the_response_range` checks the acceptance edge.

### 4.3 Special soundness and knowledge soundness

Two accepting transcripts `(w, c, z)`, `(w, c', z')` with `c ≠ c'` give
`B1·(z − z') = (c − c')·t1`. Put `f = c − c'` and `r̄ = z − z'`. Then
`‖f‖∞ ≤ 2 < q^{1/2}/√2`, so `f` is invertible in `R_q`, and `‖r̄‖∞ ≤ 2B`.
The pair `(r̄, f)` is a *relaxed opening*: it defines the message
`m̄ = t2 − f^{−1}·⟨b2, r̄⟩`. The forking lemma turns this into knowledge
soundness of the non-interactive proof in the random-oracle model, with a
non-tight reduction. The test
`test_two_transcripts_with_one_mask_yield_a_relaxed_opening` checks these
equations on real transcripts.

### 4.4 Binding with respect to relaxed openings

Suppose `(r̄, f, m)` and `(r̄', f', m')` are relaxed openings of one commitment
with `m ≠ m'`. From `f·t1 = B1·r̄` and `f'·t1 = B1·r̄'`,
`B1·x = 0` for `x = f'·r̄ − f·r̄'`. If `x = 0` then `⟨b2, x⟩ = 0`, which with
`f·t2 = ⟨b2, r̄⟩ + f·m` and `f'·t2 = ⟨b2, r̄'⟩ + f'·m'` gives
`f·f'·(m − m') = 0`, contradicting invertibility of `f, f'`. So `x ≠ 0` is an
M-SIS solution for `B1` with `‖x‖∞ ≤ 2·(2κ)·(2B) = 8κB`, the bound estimated in
Section 2. The constructor of `BdlopParams` rejects any set in which
`2·8κB ≥ q`, where the solution could wrap modulo `q`.

### 4.5 Hiding

Write `r = (r1, r2, r3) ∈ R^n × R × R^λ` and `B1' = [B1'_2 | B1'_3]`. Then
`t2 − m = r2 + b2'·r3` and `t1 − B1'_2·(t2 − m) = r1 + (B1'_3 − B1'_2·b2')·r3`.
For each fixed `m`, the map `(t1, t2) ↦ (t1 − B1'_2·(t2 − m), t2 − m)` is a
public bijection, and its image is an M-LWE instance with secret `r3` of rank
`λ`, `n + 1` ring samples, ternary error `(r1, r2)` and the uniform matrix
`[B1'_3 − B1'_2·b2' ; b2']`. This is the instance estimated in Section 2.

### 4.6 Equality proof

Two accepting transcripts with one `(w_a, w_b, u)` give relaxed openings
`(r̄_a, f)` and `(r̄_b, f)` with a *common* `f`, and from the third equation
`f·(t2_a − t2_b) = ⟨b2, r̄_a − r̄_b⟩`. Substituting into the message
definitions gives `m̄_a = m̄_b`. Zero knowledge follows as in 4.2, applied to
both responses.

### 4.7 Binding to the video and the session

All of `parameter_id`, `x` and the full commitment enter the hash before `c`
is derived. `x` is length-prefixed; `parameter_id`, the commitment and `w`
have lengths fixed by `parameter_id`, so the hash input is uniquely decodable
and a proof verifies only for the exact statement and commitment it was made
for. The verifier never reads statement values from the video: it recomputes
them and compares the session challenge with its own store. Changing any
non-carrier syntax that `D` covers changes `D`; changing a carrier changes
the envelope. Both are rejected
(`test_envelope_is_rejected_under_any_other_statement`, the tamper checks in
the E2E runs). The verifier also re-chunks the extracted envelope under the
pinned `chunk_bytes` and rejects unless the extracted pieces equal that
encoding byte for byte, so the carrier bits are the unique encoding of the
envelope. Without this check a single-chunk envelope left the 16-bit
`chunk_size` header field free (any value from the envelope length to
65 535); `test_rewritten_single_chunk_header_is_rejected` covers it.
Proofs and bounds: `docs/paper/sections/security.tex`.

### 4.8 What the proof establishes

- **In-band mode**: the creator of this video, for this session, knows an
  opening of the commitment it carries. The payload stays hidden and can be
  disclosed later to a chosen party. This does not identify the creator.
  Disclosure (3.7) is an equality proof against `(0, encode(payload))` with
  zero randomness: extraction gives a relaxed opening `(r̄', f)` of
  `(0, encode(p))` with `B1·r̄' = 0`, so `r̄' = 0` unless M-SIS is broken and
  the carried commitment hides `p`. The randomness `r` is not revealed, so the
  recipient cannot prove anything about the commitment afterwards.
- **Registered mode**: the creator knows the opening of a credential
  commitment that the issuer registered, so only the credential holder can
  produce the proof. The argument needs, besides binding, that a relaxed
  opening of an honestly generated commitment is hard to find (M-SIS, or
  M-LWE when the opening found is the holder's own `r`). With a holder id
  (3.7) the issuer's signature also covers "this commitment belongs to holder
  `h`", and the proof then authenticates `h`. Without one, the registered
  descriptor binds the commitment only and the link from a commitment to a
  person comes from outside the signed registry. Either way the issuer is
  trusted to have checked who `h` is.
- **Linkage**: two carried commitments, or a carried commitment and a
  credential, hide the same payload.

It does not establish that the payload is true, that a camera recorded the
video, or that an H.264 encoder ran correctly.

## 5. Post-quantum wording

The proofs above are in the classical random-oracle model under M-SIS and
M-LWE. No tight quantum-random-oracle proof is claimed. The appropriate
wording is "plausibly post-quantum": the underlying problems have no known
efficient quantum algorithm, and generic results (Don, Fehr, Majenz,
Schaffner, CRYPTO 2019; Liu–Zhandry, CRYPTO 2019) indicate the Fiat–Shamir
transform preserves soundness of such protocols against quantum adversaries
with polynomial loss.

## 6. Deviations from BDLOP and why

1. **Uniform masking instead of Gaussian.** Exact integer arithmetic and an
   exactly uniform accepted response (4.2), at the cost of a larger extracted
   norm. Binding is therefore estimated in `ℓ∞` with bound `8κB` rather than
   reused from the paper's table.
2. **Fiat–Shamir with an explicit statement.** The original is an interactive
   protocol; here the challenge is derived from the full statement and
   commitment, with hedged mask derivation.
3. **Different parameters.** Smaller ring degree with larger module rank,
   chosen by the estimator for size at the 128-bit level. The paper's own
   parameter table is not used.

## 7. Known limitations

- Soundness is relaxed (Section 4.3); the payload is bound only through
  binding with respect to relaxed openings.
- Not constant time: Python big-integer arithmetic and data-dependent
  rejection loops.
- In-band mode does not authenticate the creator; the session challenge is
  not secret, so issue it over an authenticated channel if that matters.
- The opening proof of this version says nothing about the message. Two
  optional, separate proofs over this same ring change nothing specified
  here: a proof that a base commitment hides a 256-bit binary string
  (`docs/BINARY_PROOF_DESIGN.md`, `src/lattice_zk/binary_proof.py`), and a
  payload range proof that a payload commitment of 3.2 hides
  `encode(p)` for some `p` of a public length `L ≤ 128` bytes, i.e. every
  coefficient is a 24-bit packing of payload bytes with the length field and
  zero padding of 3.2 (`docs/PAYLOAD_RANGE_PROOF.md`,
  `src/lattice_zk/payload_range_proof.py`, 44 558 bytes for `L ≤ 32`). The
  latter applies to the commitment of an existing in-band envelope or
  credential and can be sent out of band; it reveals `L`. A hidden-length or
  full 24-bit (all 256 coefficients) range proof is not provided.

## 8. References

- C. Baum, I. Damgård, V. Lyubashevsky, S. Oechsner, C. Peikert. More
  efficient commitments from structured lattice assumptions. SCN 2018.
- V. Lyubashevsky, G. Seiler. Short, invertible elements in partially
  splitting cyclotomic rings. EUROCRYPT 2018.
- V. Lyubashevsky. Fiat–Shamir with aborts. ASIACRYPT 2009; Lattice
  signatures without trapdoors. EUROCRYPT 2012.
- L. Ducas et al. CRYSTALS-Dilithium specification, round 3 (2021).
- M. Barbosa et al. Fixing and mechanizing the security proof of Fiat–Shamir
  with aborts and Dilithium. CRYPTO 2023.
- J. Devevey, P. Fallahpour, A. Passelègue, D. Stehlé. A detailed analysis of
  Fiat–Shamir with aborts. CRYPTO 2023.
- J. Don, S. Fehr, C. Majenz, C. Schaffner. Security of the Fiat–Shamir
  transformation in the quantum random-oracle model. CRYPTO 2019.
- T. Attema, V. Lyubashevsky, G. Seiler. Practical product proofs for lattice
  commitments. CRYPTO 2020.
