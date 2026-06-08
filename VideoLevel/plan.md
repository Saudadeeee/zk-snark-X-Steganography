# ZK-Stego VideoLevel Plan

Last updated: 2026-06-09
Branch: `Upgrade-v2`

This plan reflects the repository as it exists now. The frozen H.264/CAVLC +
Groth16 baseline is preserved on `main` at commit `053ce2b` (`8/6`). The active
branch is now `Upgrade-v2`, which is for the broader cryptographic trust
architecture and robustness-oriented diagnostics.

---

## 1. Current Baseline Scope

The current system is:

- compressed-domain H.264 baseline / CAVLC embedding,
- strongest operating regime: GOP=1 / all-intra,
- payload format: `[4B message_length][message][129B compressed Groth16 proof]`,
- proof relation: `commitment = SHA256(SHA256(message) || secret_key)`,
- patchability-aware coefficient selection,
- reconstruction-aware applied-position accounting,
- strict non-blind verification via `src/verifier.py`,
- sidecar-assisted near-blind verification via `src/verifier_blind.py`,
- blind-core research kept out of the main claim.

The current branch must not claim:

- full blind extraction,
- robust survival through recompression/transcoding,
- generic support for CABAC / HEVC / arbitrary GOP>1,
- C2PA, fingerprint registry, watermark receipt, TEE, or ZKML production support.

---

## 2. Current Repository Reality

Use the real runner and APIs that exist in the codebase.

### Correct test commands

```powershell
py -3.12 src\runtest\run_all.py --quick
py -3.12 src\runtest\test_phase4_reconstruct.py
py -3.12 src\runtest\test_phase5_extract_verify.py
py -3.12 src\runtest\test_phase6_near_blind_manifest.py
py -3.12 src\runtest\test_phase7_regression_cases.py
```

Full suite:

```powershell
py -3.12 src\runtest\run_all.py
```

Benchmark runner:

```powershell
py -3.12 benchmark\safe_benchmark_runner.py --paper-grade
py -3.12 benchmark\safe_benchmark_runner.py --sections 1 2 3 4 5 6
```

### Commands that are not currently valid

- Do not use `python -m pytest -q` as the main validation command unless a real
  pytest suite is added.
- Do not document `python src/embedder.py --demo ...`; `embedder.py` is a module
  API, not a CLI demo.

### Current test status

`src/runtest/_helpers.py::SKIP()` now raises an explicit skip result.
`run_test()` and `summarise()` report pass/fail/skip separately.

Current validation state on 2026-06-08:

- quick suite: `23/23` passed,
- Phase 4: `5/5` passed,
- Phase 5: `2/2` passed,
- Phase 6: `2/2` passed,
- Phase 7: `3/3` passed.
- full suite: `35/35` passed, `0` failed, `0` skipped.

Phase 5/6 now exercise public API and near-blind E2E coverage without skips.
Phase 7 now uses the verified SEC1 operating artifact for `akiyo_q22_g1`.

Additional artifact-policy fix on 2026-06-08:

- SEC1 failed runs now clean their stego/sidecar artifacts.
- SEC1 real-proof metadata can carry `verify_valid` and `verify_message_match`.
- `locked_operating_contract.py` refuses SEC1 artifacts that are not verified.
- Phase 7 skips unverified SEC1 artifacts instead of using them as fixtures.
- Public API embedding now uses reconstruction-aware retry/headroom so skipped
  patcher blocks do not create false capacity under-fill.
- Phase 5/6 fresh public-API embeds now use the SEC1 `validated_pool` as the
  candidate universe, then verify against the post-reconstruction positions
  returned by `embed()`.
- SEC1/SEC2/SEC6 paper-grade artifacts have been regenerated for the locked
  `akiyo_q22_g1` operating point.
- `safe_benchmark_runner.py --sections 1 2 3 4 5 6` passed `6/6` sections
  with schema validation OK.

---

## 3. Mainline Work Remaining

### P0 - Fix validation semantics

- [x] Replace the current print-only `SKIP()` behavior with explicit skipped
      accounting.
- [x] Update `run_test()` and `summarise()` to report pass/fail/skip separately.
- [x] Re-run Phase 5/6/7 after skip semantics are fixed.
- [x] Treat E2E phases with skipped core cases as incomplete, not fully passing.

### P1 - Freeze dependency and environment notes

- [x] Keep `requirements.txt` as the installable minimal dependency list.
- [x] Keep `requirements.lock` as the audited local package snapshot.
- [x] Document required native tools:
      Node.js, circom, snarkjs, ffmpeg.
- [x] Ensure `circuits/package.json` remains the source of JS dependency truth.
- [x] Do not commit private proving keys or large circuit build artifacts unless
      explicitly intended and allowed by artifact policy.

Observed local toolchain on 2026-06-08:

- Python: `3.12.10`
- Node.js: `22.20.0`
- circom: `2.2.0`
- snarkjs: `0.7.6`
- ffmpeg: `8.0.1`

### P2 - Stabilize current docs

- [x] Keep `README.md` aligned with current benchmark JSON, current API, and
      the new pass/fail/skip runner semantics.
- [x] Keep `system.txt` as the plain-text current-system summary.
- [x] Keep `PAPER_EVIDENCE.md` as claim-to-evidence map.
- [x] Keep `OPERATING_ENVELOPE.md` focused on current supported envelope.
- [x] Keep `ARTIFACT_POLICY.md` aligned with committed benchmark artifacts.
- [x] Keep `COMPLETION.md` honest about completed E2E phase coverage.
- [x] Keep `doc/system_video_embedding_walkthrough.tex` buildable.

### P3 - Current benchmark reproducibility

- [x] Run paper-grade sections through `safe_benchmark_runner.py`.
- [x] Ensure SEC2 schema consistently uses `validated_pool_bits`, while accepting
      legacy `validated_bits` only for backward compatibility.
- [x] Ensure benchmark metadata records environment, random seeds where relevant,
      and git commit when possible.
- [x] Keep diagnostic blind-core outputs separate from paper-grade evidence.
- [x] Prevent failed SEC1 attempts from leaving contract-looking sidecars.
- [x] Require `verify_valid=True` before a SEC1 artifact can become a locked
      operating contract.
- [x] Include SEC5 in the paper-grade default runner.
- [x] Validate SEC1/SEC2/SEC3/SEC4/SEC5/SEC6 schemas in the runner.
- [x] Treat empty SEC2 capacity JSON and SEC6 `zk_valid=false` as invalid
      paper-grade evidence.
- [x] Restore at least one verified SEC1 operating artifact for Phase 5/6/7 and
      SEC2 replay.
- [x] Refresh SEC6 so paper-grade performance rows have `zk_valid=true`.

Current runner status:

- Locked paper-grade operating point: `akiyo_q22_g1`.
- SEC1: `1232/1232` bits embedded, `verify_valid=true`, full-video PSNR
  `53.01 dB`, modified-frame minimum PSNR `40.30 dB`, average SSIM `0.9997`.
- SEC2: non-empty capacity data for `akiyo_q22_g1`; raw safe `413415` bits,
  patchable usable `2000` bits, validated pool `1449` bits, operating
  `1232` bits.
- SEC6: public API path timing for `akiyo_q22_g1`; total `85.0 s`,
  bits embedded `1232`, capacity `1449`, `zk_valid=true`.
- Runner: `py -3.12 -m benchmark.safe_benchmark_runner --sections 1 2 3 4 5 6`
  passed `6/6` sections with paper-grade schema validation OK on the final
  2026-06-08 validation pass.

### P4 - Current API correctness

- [x] Keep `embed()` behavior stable for legacy v1 payload format.
- [x] Keep `verify()` strict non-blind path stable.
- [x] Keep `verify_near_blind()` explicitly sidecar-assisted.
- [x] Keep manifest v1.0.0 backward-compatible.
- [x] Avoid refactoring `embedder` / `verifier` unless tests are strengthened
      first. Current refactor risk is higher than the benefit before paper freeze.

Current API validation:

- Phase 5 public `embed()` + strict `verify()` passes.
- Phase 6 public `embed()` + sidecar-assisted `verify_near_blind()` passes.
- Phase 7 verified SEC1 strict and near-blind fixtures pass.
- Public embedding keeps additional patchability headroom and retries after
  reconstruction if modified blocks were skipped by the patcher.

### P5 - Minimal runnable demo

Add a real demo only if it uses existing APIs and existing sample assets.

Proposed location:

```text
src/runtest/demo_embed_verify.py
```

Requirements:

- [x] Use `src.embedder.embed()` as a Python API.
- [x] Use `src.verifier.verify()` or `src.verifier_blind.verify_near_blind()`.
- [x] Fail gracefully if benchmark assets, verified SEC1 contract, or circuit
      artifacts are missing.
- [x] Do not pretend `embedder.py` is a CLI.

Implemented:

```text
src/runtest/demo_embed_verify.py
```

Current locked contract is available through `akiyo_q22_g1`.

---

## 4. Current Paper Claim Guardrails

Safe framing:

> A proof-verifiable compressed-domain H.264/CAVLC steganography system that
> embeds a compact Groth16 payload at a patchability-aware operating point and
> verifies extraction through strict or sidecar-assisted verifier modes.

Use these terms carefully:

- `raw_safe_bits`: structural CAVLC-safe positions.
- `patchable_usable_bits`: positions surviving patchability checks.
- `validated_pool_bits`: benchmark-validated pool.
- `operating_bits`: final locked operating-point budget.
- `applied_position_bits`: positions that survived reconstruction.

Avoid these claims on `main`:

- fully blind,
- robust watermark,
- universal H.264 support,
- C2PA-ready production system,
- detector receipt system,
- model attestation system.

---

## 5. Upgrade-v2: Cryptographic Trust Architecture

This section records the active upgrade direction. Keep these results separate
from the frozen baseline until they are promoted with their own benchmark family
and claim language.

The strategic goal is to evolve from a fragile compressed-domain steganography
prototype into a broader video provenance and attestation framework.

### 5.0 Execution Order

Build the future branch in this order:

1. Provenance anchor and manifest hash contract.
2. Private fingerprint registry lookup.
3. Robust watermark receipt.
4. TEE attestation bundle.
5. ZKML only after a realistic proving target exists.

Rules:

- Keep one trust plane per benchmark family.
- Do not mix fragile and robust metrics in one table.
- Promote a layer only after it has a stable schema, tests, and regression
  cases.

Current implementation status:

- [x] Add experimental trust-plane package under `src/trust`.
- [x] Add diagnostic runner `benchmark/trust_architecture_diagnostic.py`.
- [x] Add interface tests in `src/runtest/test_future_trust_architecture.py`.
- [x] Register diagnostic-grade runner section `44`.
- [x] Validate section `44` through `safe_benchmark_runner.py`.
- [ ] Promote any future trust plane into paper-grade benchmark evidence.

Current diagnostic status on 2026-06-09:

- Future trust interface tests now pass `11/11`.
- Section `44`: passed with schema validation OK.
- `fingerprint_verify.circom`: compiled and proved, `606` non-linear
  constraints, `842` linear constraints, Groth16 verify passed.
- `detector_receipt.circom`: compiled and proved, `465` non-linear
  constraints, `448` linear constraints, Groth16 verify passed.
- The diagnostic JSON is `benchmark/results/trust_architecture_diagnostic.json`.
- Real-clip fingerprint diagnostics now run on local H.264 assets.
- Committed synthetic fingerprint diagnostics now include positive and negative
  controls.
- Detector transform diagnostics now include positive and negative controls.
- Current synthetic fingerprint sweet spot: thresholds `8-16` reach
  `true_accept_rate=1.0` and `false_accept_rate=0.0`.
- Current detector transform diagnostic: `accuracy=1.0`,
  `positive_accept_rate=1.0`, `false_accept_rate=0.0`.

### 5.1 ZK + C2PA Provenance Root

Value:

- C2PA is strong as a metadata standard, but metadata can be stripped.
- The current compressed-domain embedding path can act as a physical anchor for
  a C2PA manifest root hash.
- If the external C2PA metadata disappears, an extractor can recover the root
  hash from the video bitstream and compare it with a registry or published
  manifest.

Feasibility:

- High.
- A C2PA root hash is only 32 bytes, and the current 146-byte proof-bearing
  payload budget can carry it.
- The existing `payload_verify.circom` can be reused initially by treating the
  C2PA root as the message/payload.

Risks:

- Still fragile: re-encoding can destroy exact hidden bits.
- Requires registry or manifest retrieval policy.
- Needs careful wording: this anchors provenance; it is not robust watermarking.

Future tasks:

- [x] Add experimental canonical provenance root helper in `src/trust/provenance.py`.
- [x] Define canonical manifest hashing.
- [x] Add production-style `src/provenance/c2pa_bridge.py`.
- [x] Add manifest fields for `provenance_uri` and `provenance_root_hash`.
- [x] Add tamper-evidence test vector.
- [x] Add C2PA anchor-to-stego-manifest roundtrip test.
- [x] Validate 32-byte embedded root payload and manifest tamper detection in
      section `44`.

Implementation sequence:

1. Freeze the manifest byte canonicalization rule.
2. Hash the manifest root outside the circuit first.
3. Decide whether the root hash is carried in payload bytes or sidecar policy.
4. Add strip-metadata and tamper tests on representative assets.
5. Measure whether the current payload budget still holds after any schema change.

Definition of done:

- The embedded root hash survives metadata stripping.
- A registry mismatch fails verification cleanly.
- The paper wording stays on "provenance anchor", not "robust watermark".
- The audit sidecar can be saved, loaded, and re-verified without cover video.

### 5.2 ZK + Fingerprint Registry

Value:

- Separates content identity from metadata identity.
- A perceptual fingerprint can represent visual/audio content even when metadata
  changes.
- ZK can let a platform prove membership or near-match against a private
  registry without exposing the registry fingerprint database.
- The inverse use case is also possible: a user proves ownership or match
  without uploading the original video.

Feasibility:

- Medium.
- Fingerprint extraction is feasible outside the circuit.
- Circuit feasibility depends on fingerprint length and Hamming-distance logic.

Risks:

- Perceptual hashes are noisy and threshold-sensitive.
- False positives and false negatives become policy issues.
- A useful circuit may be larger than the current SHA256 commitment circuit.

Future tasks:

- [x] Add deterministic pHash/vHash prototype.
- [x] Define deterministic frame sampling and preprocessing policy.
- [x] Design `fingerprint_verify.circom`.
- [x] Measure circuit constraint count through section `44`.
- [x] Add synthetic threshold behavior rows for false-accept/true-accept sanity.
- [x] Measure Groth16 proving time for `fingerprint_verify.circom`.
- [x] Add a local-clip fingerprint benchmark over available H.264 assets.
- [x] Benchmark false accept/reject behavior on a committed synthetic clip set.
- [ ] Expand false accept/reject behavior to a larger real-video corpus.

Implementation sequence:

1. Choose one fingerprint family and lock the preprocessing steps.
2. Define the registry lookup policy: exact match, Hamming threshold, or bucketed
   candidate set.
3. Keep the fingerprint extractor outside the circuit unless the circuit size is
   still practical.
4. Add privacy tests for registry leakage and failure mode clarity.
5. Benchmark false accept and false reject rates on committed clips.

Definition of done:

- The registry path can prove membership or near-match without exposing the
  private fingerprint database.
- Threshold calibration is stable across reruns.
- Constraint count and proving time are documented.

### 5.3 ZK + Watermark Receipt For GenAI

Value:

- This is the most commercially interesting direction.
- Systems such as SynthID or Video Seal face a detector-trust problem: third
  parties need confidence in detector results, but the detector/key/weights
  cannot simply be open-sourced without increasing bypass risk.
- A ZK circuit can wrap a lightweight detector and output only a threshold
  result plus proof.

Ideal workflow:

```text
generated video
  -> watermark detector inside ZK circuit
  -> score >= threshold
  -> public boolean + ZK proof
```

Breakthrough:

- ZK can hide detector keying material and detector weights.
- The current repo already has a Groth16 bridge, but the circuit must change
  from SHA256 payload verification to lightweight threshold logic.

Feasibility:

- Medium to low for real detector parity.
- High for a small proof-of-concept detector.

Risks:

- Real detectors may be too large for Circom/Groth16.
- Robust watermarking must survive compression, resize, crop, frame-rate change,
  and screen recording.
- This is not the same problem as exact bit extraction from CAVLC coefficients.

Future tasks:

- [x] Define a tiny feature extractor.
- [x] Define a small dot-product or threshold detector.
- [x] Create `detector_receipt.circom`.
- [x] Model a receipt that exposes only a boolean threshold result plus commitments.
- [x] Measure circuit constraint count through section `44`.
- [x] Measure Groth16 proving time for `detector_receipt.circom`.
- [x] Benchmark detector behavior under a small transform matrix.
- [x] Benchmark detector accuracy and proof overhead on a broader synthetic
      transform set.
- [ ] Replace the toy detector with a stronger robust-video detector candidate.

Implementation sequence:

1. Build a tiny detector that can run on fixed features.
2. Keep the detector keying material and weights outside public artifacts.
3. Make the circuit output only the threshold result, not the detector internals.
4. Test the detector under recompression, resize, crop, and frame-rate change.
5. Compare robustness against the current fragile plane, but in a separate
   benchmark family.

Definition of done:

- The proof certifies a detector decision, not a raw model dump.
- Robustness survives the transform matrix defined for the branch.
- The benchmark story is separate from the fragile CAVLC embedding story.

### 5.4 TEE / Model Attestation + ZKML

Value:

- Answers a stronger provenance question:
  "Did this exact model binary/configuration, running in this attested
  environment, produce or approve this video?"
- Useful for legal/audit-grade chains of custody.

Feasibility:

- TEE signature path: medium.
- Full ZKML video-generation proof: low today due to massive proving cost.

Risks:

- TEE trust shifts to hardware/vendor attestation roots.
- ZKML for video generation is likely too expensive for this repo's current
  scope.
- Should be framed as highest-security audit tier, not normal UGC workflow.

Future tasks:

- [x] Add a mock TEE signer interface in `src/trust/attestation.py`.
- [x] Sign canonical attestation bundles containing video/model/policy hashes.
- [x] Sidecar the signature under fragile audit mode.
- [x] Keep ZKML as interface/stub only until a realistic proving target exists.

Implementation sequence:

1. Define the attestation bundle fields and canonical hash order.
2. Add a mock signer first so the interface is stable before hardware binding.
3. Keep TEE signatures separate from C2PA and watermark proofs.
4. Treat ZKML as an interface contract, not a promised implementation target.
5. Only promote ZKML if a concrete video-generation circuit target becomes
   realistic.

Definition of done:

- An audit bundle can be verified end-to-end with a stable signature policy.
- The attestation path does not depend on fragile CAVLC extraction.
- ZKML remains clearly marked as future interface work unless and until a
  realistic proving target exists.

---

## 6. Fragile vs Robust Bottleneck

The current system is intentionally fragile:

- it requires exact bit recovery from H.264/CAVLC residual coefficients,
- `CAVLCSafetyFilter` and reconstruction logic assume bitstream-level stability,
- lossy re-encoding can destroy the hidden payload.

The future watermark/provenance directions, especially GenAI watermark receipts,
need robustness:

- survive recompression,
- survive resizing/cropping,
- survive frame-rate changes,
- survive platform transcodes.

These goals conflict. Do not try to make one mode satisfy both.

### Correct reconciliation strategy

Use a dual-plane architecture:

1. Fragile plane
   - Current H.264/CAVLC exact-bit embedding.
   - Best for archives, audit logs, tamper evidence, C2PA root anchoring in
     controlled workflows.
   - Verification fails if the bitstream is altered, which is a feature for
     tamper evidence.

2. Robust plane
   - Future watermark or detector-receipt path.
   - Does not depend on exact bit recovery from CAVLC positions.
   - Uses perceptual/feature-domain detection and threshold proofs.
   - Must have separate benchmarks and claims.

3. Registry / attestation plane
   - Public registry, sidecar, C2PA manifest, TEE signature, or model attestation
     binds the fragile and robust evidence together.

### Plane Map

- Fragile plane: exact-bit CAVLC embedding and C2PA root anchoring.
- Robust plane: fingerprint registry and watermark receipt.
- Attestation plane: TEE signatures and model provenance bundles.

### Design rule

Do not retrofit robust behavior into the current fragile CAVLC path by simply
adding redundancy. That will increase payload size, damage capacity, and still
fail under real transcoding.

Do not merge fragile, robust, and attestation evidence into one benchmark row.
Each plane must keep its own files, metrics, and failure modes.

Instead:

- keep current CAVLC path for exact-bit provenance and tamper evidence,
- add robust detector/feature logic as a separate mode,
- bind both modes through manifest/registry semantics.

---

## 7. Exit Conditions For Current Baseline

The current baseline is ready to freeze when:

- [x] `plan.md` uses only real commands and APIs.
- [x] quick suite passes.
- [x] Phase 4 passes.
- [x] Phase 5/6/7 report pass/fail/skip accurately.
- [x] paper-grade benchmark sections validate through `safe_benchmark_runner.py`.
- [x] docs and benchmark JSON tell the same story in `plan.md`.
- [x] future architecture is documented as future branch work only.
- [x] git status contains only intentional files for the baseline commit.
- [x] full runtime suite has been re-run after the final benchmark/code edits.
