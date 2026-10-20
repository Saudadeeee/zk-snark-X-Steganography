# External cryptographic review package: BDLOP video proofs

This package is for a lattice cryptographer who reviews the zero-knowledge
part of the system in a few hours. It points to the specification, the
security proofs, the code that realizes each assumption, and the tests and
known-answer vectors (KATs) that check them.

All paths are relative to `VideoLevel/`. All line ranges refer to commit
`18c5123` (branch `feature/lattice-pq-stack`). The security section of the
paper cites line numbers at an older commit (`ea96d60`). Where the two
disagree, use the ranges in this package.

## What the system does

An H.264 video carries a fixed-size envelope in CAVLC coefficient carriers.
The envelope holds a BDLOP commitment `t` (Baum et al., SCN 2018) to a payload
of up to 766 bytes. It also holds a Fiat–Shamir-with-aborts proof of knowledge
of an opening of `t`. The proof is bound to a 274-byte statement. The verifier
recomputes the statement from its own pins and from the received video: the
registry root and epoch, a session challenge, the carrier positions, and a
carrier-normalized digest of the bitstream. In registered mode the commitment
is a credential pinned by an ML-DSA-65-signed registry, and the video carries
only the proof. An equality proof between two commitments is used for linkage
and for disclosure.

Parameter set `bdlop-open-128-v1`: N = 256, q = 2^30 − 35 (q ≡ 5 mod 8),
n = λ = 6, k = 13, κ = 60, γ = 2^17, B = γ − κ − 1. Masks are uniform on
[−γ+1, γ]. This is ML-DSA-style uniform masking, not the Gaussian masking of
BDLOP.

## Scope: what to review

Ranked by how much the security claims depend on it:

1. **Opening proof** (`src/lattice_zk/opening_proof.py`): the Fiat–Shamir
   transcript, the rejection condition, hedged mask derivation, and
   verification.
2. **Parameters and estimates** (`src/lattice_zk/params.py`,
   `research/bdlop_params/`): the M-SIS ℓ∞ bound 8κB, the M-LWE instance, the
   challenge space, and invertibility of challenge differences.
3. **Equality proof** (`src/lattice_zk/equality_proof.py`): soundness of the
   common-challenge extraction, zero-randomness disclosure, and the attempt cap.
4. **Samplers and ring** (`src/lattice_zk/sampling.py`, `ring.py`,
   `codec.py`): exact uniformity, SampleInBall, and canonical encodings.
5. **Statement and envelope binding** (`src/lattice_zk/video_proof.py`, and
   the verification path of `src/lattice_zk/video_pipeline.py`): whether the
   verifier takes any statement field from the prover.
6. **Security model and proofs** (`docs/paper/sections/security.tex`,
   `security_appendix.tex`): game definitions, the ROM simulation of the
   aborting prover, forking, and the M-LWE hiding map.

The concrete questions are in [QUESTIONS.md](QUESTIONS.md). Each theorem is
mapped to code and tests in [CLAIMS.md](CLAIMS.md). Use
[CHECKLIST.md](CHECKLIST.md) while reading the code.

## Out of scope

- Steganographic undetectability and the CAVLC carrier channel
  (`src/blind_sync_streaming.py`, `src/video_canonicalization.py`). Treat
  `Place`, `Canon`, `Write` and `Read` as given deterministic functions.
  Transport failure only causes rejection.
- The ML-DSA-65 implementation (the `pqcrypto` 1.0.0 wheel). It is assumed
  EUF-CMA.
- Side channels. This is a pure-Python/NumPy research implementation and is
  **not constant time** (see CHECKLIST.md §7).
- The legacy Groth16/LaZer paths (`lazer/`, `circuits/`, the `lazer-v1`
  registry suite) and the ImageLevel project.
- Video quality, capacity and benchmark numbers.

## Time estimate

| Part | Time |
|---|---|
| Read the spec and the security section | 1.5 h |
| Core code (`params`, `sampling`, `ring`, `bdlop`, `opening_proof`, `equality_proof`, `codec`, about 900 lines) | 1.5 h |
| Statement, envelope and verification path (`video_proof`, `video_pipeline` lines 300–402) | 0.5 h |
| Parameter estimates and cross-check | 0.5 h |
| **Total** | **about 4 h** (2 h for items 1–3 of the scope only) |

## How to run

Run everything from `VideoLevel/` with Python 3.12, `numpy`,
`pqcrypto==1.0.0` and `pytest` (`pip install -r requirements.txt`). No
ffmpeg is needed: the pipeline tests use an in-memory fake transport.

| What | Command | Expected (commit `18c5123`, Windows 11, CPython 3.12) |
|---|---|---|
| All lattice-ZK tests | `python -B -m pytest -p no:cacheprovider -q src/runtest/test_latticezk_*.py` | `209 passed, 1 skipped` in about 50 s. The skip is a POSIX file-mode test on Windows. |
| Cryptographic core only | `python -B -m pytest -p no:cacheprovider -q src/runtest/test_latticezk_ring.py src/runtest/test_latticezk_bdlop.py src/runtest/test_latticezk_equality.py src/runtest/test_latticezk_kat.py src/runtest/test_latticezk_linkage.py src/runtest/test_latticezk_video_proof.py` | all pass |
| KAT regeneration and comparison | `python -B research/bdlop_params/kat.py > /tmp/kat.json && diff /tmp/kat.json research/bdlop_params/kat_v1.json` | no diff (`kat.py` has no `--check` flag; `test_latticezk_kat.py` performs the same comparison) |
| Session store and chunk framing | `python -B -m pytest -p no:cacheprovider -q src/runtest/test_zkp_sessions.py src/runtest/test_blind_payload_chunks.py` | `22 passed` |
| Registry (script-style test) | `python -B src/runtest/test_zkp_registry.py` | `7/7 passed` |
| Core-SVP estimate (CRYSTALS scripts) | `git clone https://github.com/pq-crystals/security-estimates && git -C security-estimates checkout 75c26949 && python research/bdlop_params/estimate.py --estimator security-estimates` | reproduces `research/bdlop_params/bdlop_open_128.estimate.json` |
| lattice-estimator cross-check (Sage) | see `research/bdlop_params/CROSSCHECK.md` | `research/bdlop_params/lattice_estimator_crosscheck.json` |

## File map (security-critical code)

| File | Lines | What it does |
|---|---|---|
| `src/lattice_zk/params.py` | 33–68 | `BdlopParams` and its constructor checks: prime q ≡ 5 mod 8, `2√2 < √q` (63–65), `2·8κB < q` (66–68) |
| | 70–122 | Derived quantities: k, shift bound κ, `B = γ−κ−1` (80–83), `8κB` (85–88), sizes, challenge-space bits (114–116), acceptance probability (118–122) |
| | 124–144 | `parameter_id` (SHA3-256 over every field and the setup seed); `require_production_strength` (challenge space ≥ 2^256) |
| | 147–175 | Setup seed, `BDLOP_OPEN_128`, `TOY` |
| `src/lattice_zk/ring.py` | 1–9, 42–57 | Two-factor splitting rationale; `validate_modulus`; `sqrt_minus_one` |
| | 60–103 | `center`; exact negacyclic `poly_mul` by Kronecker substitution; `mat_vec` |
| | 106–114 | `is_invertible` (CRT test, used by tests only) |
| `src/lattice_zk/sampling.py` | 12–47 | SHAKE-256 `XofStream`; `_rejection_sample` (no modular reduction) |
| | 50–66 | Uniform R_q (key), ternary (randomness), mask on [−γ+1, γ] |
| | 69–81 | `challenge_poly`: sign bits, then Fisher–Yates as in ML-DSA SampleInBall |
| `src/lattice_zk/bdlop.py` | 24–56 | Domain tags; integer/shape/reduction checks; ternary witness check |
| | 59–108 | `CommitmentKey` (B1 = [I_n \| B1'], b2 = [0^n \| 1 \| b2']); `Commitment` canonical (de)serialization |
| | 111–154 | `derive_key` (one global key from `parameter_id`); `sample_randomness`; `commit`; `verify_opening` |
| `src/lattice_zk/opening_proof.py` | 31–51 | Domain tags; `MAX_ATTEMPTS = 512`; Fiat–Shamir hash `H(tag‖pid‖u64(\|x\|)‖x‖enc(t)‖enc(w))` |
| | 54–90 | Prover entropy; canonical-commitment checks; `hedged_mask_key` (SHA3-256, no domain tag, D7) |
| | 93–136 | One attempt `_respond` (rejection iff ‖z‖∞ > B); `prove_with_stats` loop |
| | 145–168 | `verify`: exact length, packed range, recomputed w', constant-time seed comparison |
| `src/lattice_zk/equality_proof.py` | 44–82 | Tags; `MAX_ATTEMPTS = 4096` (D4 fix); Fiat–Shamir over both commitments and (w_a, w_b, u) |
| | 89–149 | Witness checks (same message); prover with two masks per attempt |
| | 162–193 | `verify` |
| `src/lattice_zk/codec.py` | 10–33 | Canonical fixed-width packing; zero padding and range checks |
| | 36–60 | Injective payload encoding (2-byte length, 3 bytes per coefficient) and exact-image decoder |
| `src/lattice_zk/linkage.py` | 29–64 | Linkage context hash; equality proof between two video commitments |
| `src/lattice_zk/video_proof.py` | 26–41 | Tags and envelope layouts |
| | 70–102 | `VideoStatement` fixed-width encoding (274 bytes) and `statement_id` |
| | 126–154 | Video-commitment domain separation; envelope size; `build_statement` |
| | 157–225 | Envelope encode/decode (strict layout, pinned `pid`, canonical t); `create_envelope`; `verify_envelope` |
| | 246–289 | Registered (proof-only) envelope: create, session parsing, verify |
| | 294–415 | Zero-knowledge disclosure: context, `Com(enc(p); 0)`, equality proof, strict decoding |
| `src/lattice_zk/video_pipeline.py` | 135–213 | Relation descriptor (key, credential, holder-id digest); `pins_from_registry` (signature, epoch floor, exactly one match, production strength) |
| | 216–235 | Session binding; public carrier-order key |
| | 250–297 | Embed: placeholder layout, then statement, then proof (prover side) |
| | 300–402 | **Verification path**: configuration checks including relation-id recomputation (D6, 300–326); extraction and canonical re-chunking (D1, 351–367); verifier-built statement (369–389); session `verify_and_consume` (390–397) |
| `src/zkp_registry.py` | 30–101 | Descriptor field set; `relation_id` = SHA-256 over canonical JSON |
| | 104–168 | Signed registry: root, signing bytes, ML-DSA-65 verify, `resolve` |
| | 170–220 | `verify_statement_binding`: `lazer-v1` only, not used by BDLOP (D10) |
| `src/zkp_sessions.py` | 113–155 | Challenge digest; `issue` (fresh 32 bytes from `secrets`, `BEGIN IMMEDIATE`) |
| | 157–241 | `is_active`; atomic `consume` (`UPDATE … WHERE consumed_at IS NULL AND expires_at > now`); `verify_and_consume` |
| `src/blind_payload_chunks.py` | 10–44 | Chunk header and `payload_chunk_count` |
| | 47–81 | `pack_payload_chunks` (the verifier recomputes this for D1) |
| | 84–137 | `assemble_payload_chunks` |

Supporting documents:

| File | Contents |
|---|---|
| `docs/LATTICE_ZK_BDLOP_SPEC.md` | Protocol specification (§3), informal security argument (§4), deviations from BDLOP (§6), limitations (§7) |
| `docs/paper/sections/security.tex` | Model, games, theorem statements |
| `docs/paper/sections/security_appendix.tex` | Full proofs; specification/code cross-check; discrepancies D1–D11 |
| `docs/paper/tables/params.tex` | Parameter table |
| `research/bdlop_params/estimate.py`, `bdlop_open_128.estimate.json` | Core-SVP estimate (CRYSTALS security-estimates model) |
| `research/bdlop_params/lattice_estimator_crosscheck.py`, `.json`, `CROSSCHECK.md` | Independent cross-check with the lattice-estimator |
| `research/bdlop_params/kat.py`, `kat_v1.json` | KAT generator and pinned digests (commitments, opening proofs, equality proofs, key) |

## Status of the self-review findings

The appendix lists discrepancies D1–D11. D1–D4 and D6 are fixed, each with a
negative test. D8 is mitigated: every verifier entry point requires a
canonical commitment. **D5, D7, D9, D10 and D11 are open.** They are restated
as questions in QUESTIONS.md.
