# LaZer Toolkit candidate assessment (2026-09-29)

## Decision

**Revisit as the strongest located research candidate; do not integrate or claim
the system's application-level ZKP is implemented.** The Toolkit is materially
more relevant than the repository's LNP22 linear-relation probes: upstream
describes a zero-knowledge LaBRADOR variant and the source contains at least
one concrete proof statement constructed with `zk=True`. That example is a
custom-hash Merkle-membership relation, not the required payload-opening,
video/session-binding, or H.264/CAVLC relation.

This assessment combines a review of the official paper PDF and source code.
The Toolkit was not built or run on this host, and no proof bytes were
extracted. The formal theorem statements below were checked from the typeset
paper, but this is not an independent cryptographic audit of the paper or code.

## Source evidence

- The [official ePrint record](https://eprint.iacr.org/2026/1289) describes a
  Toolkit adding a zero-knowledge variant to LaBRADOR and evaluating expansion,
  compression, membership, and blind-signature use cases. The official PDF was
  retrieved via a direct read-only HTTP request after the web reader returned
  403. The paper's Theorem 1 (p. 6) states a knowledge-soundness error term
  `κ = 1/2^128 + (1/q)^λ + 1/q^(d/2) + 2/|C|`; Theorem 2 (p. 11) uses
  `κ = 5/2^128 + (1/q)^λ + 1/q^(d/2) + 2/|C|`. These bounds are conditional on
  the paper's stated M-SIS instances and parameter/norm conditions. The authors
  describe the Fiat–Shamir/composition knowledge-soundness reliance as
  heuristic in the Random Oracle Model, not as an unconditional end-to-end
  theorem for every compiled composition. The paper reports honest-verifier
  zero knowledge for the interactive composition and derives non-interactive
  ZK via Fiat–Shamir; this still requires implementation and parameter review.
- The current [official LaZer repository](https://github.com/lazer-crypto/lazer)
  describes itself as a lattice-based zero-knowledge proof library. Its runtime
  requirements specify Linux x86-64, AVX-512 and AES; the local preflight
  artifact `lazer_host_recheck_20260929.md` reports that this host lacks
  AVX-512F. Therefore no local proof-generation or verification result exists.
- The linked [official LaBRADOR implementation](https://github.com/lazer-crypto/labrador)
  explicitly labels itself research-purpose code that has not undergone the
  security review, testing, or validation required for production. This is an
  implementation-readiness warning in addition to the paper-level analysis;
  a theorem in the paper does not constitute an audit of this code.
- The upstream README pins reproduction of this paper to commit
  [`59a52f74ca39584edf77b4b8b7437dbd48f9ad94`](https://github.com/lazer-crypto/lazer/tree/59a52f74ca39584edf77b4b8b7437dbd48f9ad94).
  In contrast, this project currently pins `lazer/LAZER.lock.json` to
  `10eafeca4cd53ff4fc54193dce904dbd0026fefd`, the earlier LaZer library demo
  (`A*s=t`). The local lock is therefore not a reproducible pin for the
  Toolkit candidate and must not be mistaken for one.
- The Toolkit commit's `.gitmodules` pins `src/labrados` to
  [`3f95485139ffaa65fe572da809b90772901372e5`](https://github.com/lazer-crypto/labrador/tree/3f95485139ffaa65fe572da809b90772901372e5).
  This nested revision is now also recorded in the separate candidate lock.
- The pinned [membership proof source](https://github.com/lazer-crypto/lazer/blob/59a52f74ca39584edf77b4b8b7437dbd48f9ad94/python/succinct_zkp/membership_proof.py)
  creates a `proof_statement(..., zk=True, ...)`, adds constraints for a binary
  public key, Merkle siblings and path selectors, calls `pack_prove()`, and
  checks the result with `pack_verify()`. The statement is a particular
  polynomial/lattice-hash Merkle-membership relation. The adjacent
  [benchmark source](https://github.com/lazer-crypto/lazer/blob/59a52f74ca39584edf77b4b8b7437dbd48f9ad94/python/succinct_zkp/benchmark_membership_proof.py)
  reports trace, prove and verify timings for varying path counts; it does not
  report serialized proof byte length in the inspected code.
- A source-level security issue prevents treating the blind-signature example
  as an application-ready prover: in the pinned
  [`blind_signatures.py`](https://github.com/lazer-crypto/lazer/blob/59a52f74ca39584edf77b4b8b7437dbd48f9ad94/python/succinct_zkp/blind_signatures.py)
  `compute_commitment()` derives `SEED_USER` from the fixed public byte string
  `01` (`hashlib.shake_128(b"\x01").digest(32)`) and samples commitment
  randomness from that seed. Thus the example's randomness is reproducible
  across invocations and publicly predictable; it is suitable as an artifact
  benchmark, not as a privacy-preserving production commitment implementation.
  It also fixes the demonstrated message to one 512-coefficient binary
  polynomial. A production adaptation needs fresh CSPRNG randomness, explicit
  payload/context encoding and a re-reviewed commitment/proof relation.
- The [LaBRADOR Python wrapper](https://github.com/lazer-crypto/lazer/blob/59a52f74ca39584edf77b4b8b7437dbd48f9ad94/python/labrados.py)
  documents `pack_prove()` as returning `(error, params, proof)` where the
  latter two are C-typed structures, while `pack_verify()` consumes those
  in-memory objects. At the pinned native dependency,
  [`pack.h`](https://github.com/lazer-crypto/labrador/blob/3f95485139ffaa65fe572da809b90772901372e5/pack.h)
  defines `pack_proof` as an array of round-proof pointers, optional LNP-proof
  pointer, and final witness; `pack_params` separately contains round
  parameters and the ZK round index. The corresponding
  [`pack.c`](https://github.com/lazer-crypto/labrador/blob/3f95485139ffaa65fe572da809b90772901372e5/pack.c)
  generates and verifies these structures but has no `serialize` API in the
  reviewed source. This does **not** show that serialization is impossible;
  it means a portable canonical codec for proof fields (and a policy for
  regenerating/pinning verifier parameters) must be implemented and tested.
  The word `pack` is not evidence that the result is a video-ready wire proof.
- Section 4.3 (p. 16) also gives a blind-signature application with a
  zero-knowledge commitment-opening relation of the form
  `c = B r + H(μ, H(r)) ∈ R_q`, followed by a short-preimage signature relation.
  This is structurally relevant to a hidden payload opening, but the example's
  message, setup, custom hash and statement do not bind the repository's
  verifier-derived video/session/carrier policy. Section 4.2–4.3 uses a custom
  lattice hash rather than SHA3-256. On p. 15 the authors explicitly say the
  hash's mixing function has not received cryptanalysis and that its security
  cannot simply be justified by the cited indifferentiability argument. That
  caveat must be carried into any reuse of the commitment.
- The Toolkit is not an arbitrary H.264/CAVLC proof circuit. The application
  must still define a verifier-pinned relation that binds the opening and all
  public video/session context to the actual video-derived statement.

## Application fit and capacity

Section 4 of the paper says its proof is “around 100 KB” without ZK and
“around 110 KB” with ZK; it explicitly does not report exact sizes because the
final LaBRADOR round dominates. These are paper-level approximations, not
serialized byte measurements or this application's proof size. Against the
local Akiyo profile (1,232 operating bits = 154 bytes; 2,000 patchable bits =
250 bytes; 413,415 raw candidates = 50.5 KiB), 110 KB is about 714× the
operating capacity, 440× the patchable capacity, and 2.13× even the raw-candidate
ceiling. It cannot fit that measured Akiyo profile.

There is a larger-video lead, not a pass: the existing Coastguard 3,000-frame
scan previously found at least 1,053,680 positions passing the repository's
patchability gate for a 131,694-byte requested artifact. A paper-estimated
110-KB proof may fit that *patchability count* before full envelope overhead,
but the actual LaZer proof, quality-validated capacity, end-to-end embed,
blind extraction and decoder compatibility have not been tested. This result
is clip/configuration-specific and does not prove the candidate fits generally.

An AVX-512 runner would address only local execution. Before an isolated smoke
test can establish relevance, the project still needs (1) paper-level security
review, (2) a fixed verifier-pinned relation that proves the required payload
commitment opening and binds session/video/carrier policy, (3) a stable binary
proof serialization and measured byte length, (4) actual quality-validated
carrier capacity, and (5) blind extraction and independent verification from
the produced video.

## Disposition

| Gate | Finding | Status |
|---|---|---|
| Lattice-ZK construction exists | Upstream paper record and concrete `zk=True` membership example | Promising, theorem review pending |
| Required application relation | Blind-signature example has a relevant commitment opening, but not this video/context relation | Not met |
| Formal paper analysis | Theorem 1/2 and p. 15 hash caveat checked; independent expert/code audit remains absent | Partial |
| Commitment implementation hygiene | Pinned benchmark uses a fixed public seed for commitment randomness | Not suitable as-is |
| Proof serialization and size | C structures returned in-process; paper estimates ~110 KB ZK but exact bytes/wire codec absent | Not available |
| Current-host execution | AVX-512F prerequisite absent | Not run |
| In-band fit and blind verification | No application proof artifact to embed | Not met |

## Current-worktree spot checks

Re-ran the two narrowly scoped local checks after reviewing the current tree:

```text
py -3.12 -u src/runtest/test_lattice_zkp.py       8/8 passed
py -3.12 -u src/runtest/test_video_zkp_contract.py 9/9 passed
py -3.12 -m src.lazer_backend                     ready=false; avx512f_required
```

These confirm that the unsupported SIS path still fails closed and the
statement-helper contract tests still pass. They do not run the Toolkit, prove
the application relation, or exercise embed/extract/verify. `git diff --check`
reported no whitespace errors; Git did emit the existing LF-to-CRLF working
copy warnings.

This candidate changes the next research action: obtain access to a supported
AVX-512 runner, define whether the custom commitment hash's explicit
cryptanalysis caveat is acceptable (or design a separately reviewed
commitment), then measure a serialized proof for the exact registered payload
and video-context relation. Only after those gates should an isolated in-band
test be attempted. This is not an active production backend and does not relax
any acceptance criterion.
