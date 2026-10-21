# Cleanup inventory (October 2026)

Classification of every tracked file under `VideoLevel/` before the
layout cleanup, and what was done with it. Classes:

- **A** current lattice-ZK system (or its data/results): kept, possibly moved
  into a subpackage;
- **B** legacy but alive (imported, tested or documented by the
  pre-lattice-ZK system): kept, moved under a `legacy/` directory;
- **C** dead (no entry point, test, script or benchmark imports or runs it,
  or it cannot even be imported): deleted;
- **D** abandoned experimental probe: deleted;
- **E** generated / build artifact: none was tracked; `.gitignore` fixed.

The usage graph was built statically (AST imports plus `-m module`,
`"src.x.y"` patch strings and `path/to/file.py` strings) from these entry
points: `src/lattice_zk/cli.py`, every test in `src/runtest/`,
`scripts/*.py` and the benchmarks `scripts/repro.py` runs, the legacy runner
`benchmark/safe_benchmark_runner.py`, the Docker/compose/CI files and
`conftest.py`. Files cited by `docs/paper/**` or by result provenance in
`benchmark/results/**` were checked before deletion: the paper cites only
`src/lattice_zk/`, `research/bdlop_params/`, `benchmark/latticezk_q2_cases.json`
and `benchmark/results/q2/` (all unchanged); result files that mention a
deleted probe stay as historical records.

## Identifiers

No identifier hashes a module or class path: carrier profile ids, policy
hashes, contract ids and KAT vectors are built from constants and canonical
JSON, never from `__module__`/`__qualname__`; the analysis cache no longer
pickles (it uses marshal of plain data). The moves therefore change no id,
hash or KAT; the byte-identity tests (`test_gop_and_hd_support`,
`test_adaptive_chunking`, `test_geometry_aware_ordering`,
`test_hardening_d5_d7_d8`, `test_latticezk_kat`) pass unchanged.

## Target layout

```
VideoLevel/
  README.md  ARTIFACT.md  requirements.txt  requirements.lock  pytest.ini  conftest.py
  src/
    lattice_zk/   BDLOP commitment, proofs, video statement, CLI          (A)
    transport/    blind carrier sync, chunk framing, GOP policy, canonical digest (A)
    registry/     relation registry, verifier sessions, HTTP front end, ML-DSA (A)
    core/  bitstream/  exceptions.py   carrier analysis and CAVLC patching  (A)
    legacy/       pre-lattice-ZK embed/verify, Groth16 bridge, trust, realtime (B)
    runtest/      current tests;  runtest/legacy/  tests of src/legacy and benchmark/legacy
  benchmark/      latticezk_* + case files + results/;  legacy/  SEC1-SEC10, trust, native
  research/bdlop_params/   parameter estimates, KATs                          (A)
  scripts/        repro.py and its wrappers                                   (A)
  legacy/         circuits/ (Groth16) native/ (x264 fork, C relay) lazer/ docker/ ci.yml (B)
  docs/           current design docs, paper/, review/;  legacy/  old root docs and doc/
  data/external/trust_corpus/   two 30-frame fixtures used by tests          (A)
```

`src/__init__.py` no longer imports anything: it used to load the whole legacy
embed/verify stack (Groth16 bridge, sidecar manifest, verifiers) on every
`import src.*`, including in each analysis worker process. The old public API
is now `src.legacy` (`from src.legacy import embed, verify, ...`).

## Table

| Path | Class | Action | Reason |
|---|---|---|---|
| `src/lattice_zk/*` (15) | A | keep | lattice-ZK backend and CLI |
| `src/blind_sync.py`, `blind_sync_streaming.py`, `blind_sync_adaptive.py`, `blind_payload_chunks.py`, `adaptive_chunks.py`, `gop_policy.py`, `video_canonicalization.py` | A | move to `src/transport/` | blind transport of the lattice envelope; groups 7 flat modules |
| `src/zkp_registry.py`, `zkp_sessions.py`, `zkp_session_http.py`, `lattice_pq.py` | A | move to `src/registry/` | relation registry, session store, ML-DSA signer used by registry and CLI |
| `src/core/*`, `src/bitstream/*`, `src/exceptions.py` | A | keep | carrier analysis and patching |
| `src/core/carrier_gate.py` | A | new (extracted) | `prune_patchable_positions`, `strict_validate_h264_decode` (from `embedder.py`) and `hash_positions`, `canonical_json_bytes` (from `manifest.py`), moved unchanged so transport does not import the legacy embedder; old names re-exported there |
| `src/core/pipeline_optimized.py` | C | delete | imported by nothing; superseded by `core/parallel_analysis.py` |
| `src/__init__.py` | A | rewrite (no imports) | eager import of the legacy API on every `import src.*` |
| `src/embedder.py`, `verifier.py`, `verifier_blind.py`, `verifier_blind_keyed.py`, `verify_modes.py`, `zk_proof.py`, `manifest.py`, `video_zkp_contract.py`, `stream_profile.py`, `realtime.py`, `lazer_backend.py` | B | move to `src/legacy/` | pre-lattice-ZK one-shot embed/verify, Groth16 bridge, sidecar manifest, LaZer statement contract, realtime transport, LaZer preflight; tested |
| `src/trust/` (10), `src/provenance/` (2) | B | move to `src/legacy/trust/`, `src/legacy/provenance/` | trust/provenance workflows; tested and run by legacy benchmarks |
| `src/legacy/__init__.py` | B | new | old `src` public API (`embed`, `verify`, `verify_*`, `StegoManifest`) |
| `src/runtest/test_*` of current modules (66 files) | A | keep; 16 merged into 4 (see below) | current tests |
| `src/runtest/test_phase11_benchmark_reproducibility.py` | C | delete | imports `benchmark.test_realtime_camera_recorder` (never in the repository) and two `run_all` helpers that no longer exist; failed at import |
| `src/runtest/test_{phase1_zk_proof,phase5_extract_verify,phase6_near_blind_manifest,phase7_regression_cases,phase12_lattice_capacity_gate,phase13_streaming_capacity_scan,phase17_blind_worker_isolation,phase19_strict_decode_gate,phase21_application_retry_contract,hardening,lattice_zkp,lazer_backend,video_zkp_contract,video_zkp_context_relation,realtime_transport,ffmpeg_fixture,ffmpeg_validation_headroom,future_trust_architecture,e2e_sec1_verify,sec5_zkp_benchmark,clean_artifacts_heavy_local,clean_artifacts_presentation,native_blind_carrier_scan,native_cli_fixture,native_pipeline_benchmark,native_relay_ffmpeg}.py`, `demo_embed_verify.py` | B | move to `src/runtest/legacy/` | their subject is a legacy module or benchmark |
| `src/runtest/test_lattice_pq_stack.py`, `test_zkp_registry.py`, `test_phase3_safety_embed.py`, `test_video_only_blind_sync_integration.py` | A | keep | subject is a current module (registry signer, registry, CAVLC filter, transport); one case each still reaches `src.legacy` |
| `src/runtest/test_lnp22_{http_api,video_e2e,video_quality_report,video_session}.py` | D | delete | only exercised the LNP22 probe |
| `src/runtest/run_all.py`, `_helpers.py`, `__init__.py` | A | keep, paths updated | phase runner covers both trees |
| `benchmark/latticezk_*.py`, `latticezk_*_cases.json`, `__init__.py` | A | keep | lattice-ZK evaluation (`scripts/repro.py`, docs) |
| `benchmark/results/**` (216) | A | keep | results and provenance; never rewritten |
| `benchmark/{sec1_quality,sec1_audit,sec2_capacity,sec3_methods,sec3_ablation,sec4_security,sec5_zkp,sec6_performance,sec6_paper_summary,sec7_tradeoff,sec8_realtime,sec9_motion_gop,sec10_gop_sweep,sec45_trust_evidence,sec46_product_readiness,sec47_zk_receipt_contracts,statistical_benchmark,safe_benchmark_runner,_common}.py` | B | move to `benchmark/legacy/` | SEC1-SEC10 suite of the README; tracked `benchmark/results/sec*` came from it |
| `benchmark/{trust_corpus.py,trust_corpus_manifest.json,trust_architecture_diagnostic.py,clean_artifacts.py,streaming_capacity_scan.py,lattice_in_video_feasibility.py,locked_operating_contract.py,patchable_capacity_scan.py,native_pipeline_matrix.py,native_carrier_normalization_probe.py,native_variable_length_patch_probe.py}` | B | move to `benchmark/legacy/` | imported by legacy tests or cited by tracked results |
| `benchmark/blind_{sync_diagnostic,core_trial,contract_operating_point,header_body_diagnostic,header_stability_diagnostic,header_redundancy_diagnostic,body_redundancy_diagnostic,payload_coding_diagnostic,partial_payload_contract,real_proof_header_diagnostic}.py`, `public_api_realization.py`, `validated_pool_proxy_diagnostic.py` | B | move to `benchmark/legacy/` | sections 32-43 of `safe_benchmark_runner.py` |
| `benchmark/{blind_body_hamming_diagnostic,blind_header_subset_search,blind_real_proof_partial_contract,native_post_encode_patch_probe}.py` | C | delete | no runner, test, doc or result refers to them |
| `benchmark/sec4_modern_detectors.py` | C | delete | fails at import (`NameError: Any`) since it was added; nothing runs it |
| `benchmark/ringo_application_probe/` (162, incl. Go vendor tree) | D | delete | Ringo/Buckler opening probe; proofs 1.6-2.7 MB, never the backend |
| `benchmark/lnp22_context_probe/` (14) | D | delete | LNP22 context-binding probe; superseded by BDLOP |
| `benchmark/isw21_application_probe/` (4) | D | delete | did not compile against the pinned backend |
| `benchmark/lazarus_bdlop_bridge_probe/` (3) | D | delete | LaBRADOR bridge probe |
| `research/isw21_r1cs_opening_smoke/` (6) | D | delete | ISW21 R1CS smoke test, not the production relation |
| `research/__init__.py`, `research/bdlop_params/**` (17) | A | keep | estimates, KAT v1/v2, cross-checks |
| `scripts/*` (13) | A | keep; `repro.py` suite paths updated | reproduction driver |
| `scripts/ops/*` (5, merged from `feature/lattice-pq-stack`) | A | keep | operational run scripts; call only `benchmark.latticezk_*` |
| `circuits/` (8), `native/` (17), `lazer/` (4), `docker/` (5), `Dockerfile.pqvideo`, `compose.yaml` | B | move to `legacy/circuits`, `legacy/native`, `legacy/lazer`, `legacy/docker/` | Groth16 circuits, x264 fork + C relay, LaZer container, legacy images; paths inside fixed (compose context is `../..`) |
| `.github/workflows/ci.yml` | B | move to `legacy/ci.yml` | nested under `VideoLevel/`, so GitHub never ran it; the live job is the repository-root `videolevel-latticezk.yml` |
| `.dockerignore` | B | keep at root, paths updated | Docker reads it from the build context (`VideoLevel/`) |
| `demo/00_prepare.py` | C | delete | imports a `common` module that was never tracked |
| `ARTIFACT_POLICY.md`, `LATTICE_PQ.md`, `OPERATING_ENVELOPE.md`, `PAPER_EVIDENCE.md`, `REALTIME.md` | B | move to `docs/legacy/` (unchanged) | pre-lattice-ZK docs |
| `doc/system_video_embedding_walkthrough.{tex,pdf}`, `doc/trust_corpus_onboarding.md` | B | move to `docs/legacy/` (unchanged) | legacy walkthrough; one docs tree |
| `docs/*.md`, `docs/review/*`, `docs/paper/**` | A | keep | current docs and paper |
| `data/external/trust_corpus/*` (4) | A | keep | fixtures read by current and legacy tests |
| `README.md`, `ARTIFACT.md`, `requirements*`, `pytest.ini`, `conftest.py`, `.gitignore` | A | keep; `.gitignore` updated | root files |

## Tests merged

Four groups of one-to-five-case pytest files on the same module were merged
(each section keeps its original test names; no case changed):

| New file | Merged from |
|---|---|
| `src/runtest/test_cavlc_tables.py` | `test_cavlc_coeff_token_tables.py`, `test_cavlc_encoder_lookup_cache.py`, `test_cavlc_nc_prediction.py`, `test_cavlc_vlc_prefix_cache.py` |
| `src/runtest/test_h264_syntax.py` | `test_h264_chroma_cbp_flags.py`, `test_h264_mb_type_mapping.py`, `test_h264_p_slice_real_stream.py`, `test_bitstream_reader_read_bits.py`, `test_nal_parser_hotpath.py` |
| `src/runtest/test_patchability.py` | `test_patchability_canonical_fastpath.py`, `test_patchability_context_cache.py`, `test_patchability_window_decode.py`, `test_patchability_verified_nc_propagation.py` |
| `src/runtest/test_safety_filter.py` | `test_safety_filter_max_num_coeff.py`, `test_safety_filter_original_length_cache.py`, `test_safety_filter_verified_length_reuse.py` |

Files named in `scripts/repro.py`, `run_all.py` or `conftest.py` were not
merged, so those lists keep their entries.

## Moved documents (for the docs stream)

Moved unchanged; links to them and the code paths inside them are stale:

| From | To |
|---|---|
| `ARTIFACT_POLICY.md` | `docs/legacy/ARTIFACT_POLICY.md` |
| `LATTICE_PQ.md` | `docs/legacy/LATTICE_PQ.md` |
| `OPERATING_ENVELOPE.md` | `docs/legacy/OPERATING_ENVELOPE.md` |
| `PAPER_EVIDENCE.md` | `docs/legacy/PAPER_EVIDENCE.md` |
| `REALTIME.md` | `docs/legacy/REALTIME.md` |
| `doc/system_video_embedding_walkthrough.tex` / `.pdf` | `docs/legacy/` |
| `doc/trust_corpus_onboarding.md` | `docs/legacy/trust_corpus_onboarding.md` |
| `docker/README.md` | `legacy/docker/README.md` |
| `lazer/README.md` | `legacy/lazer/README.md` |
| `native/README.md`, `native/x264_fork/README.md` | `legacy/native/` |

Documents (not moved) that name a moved module or path: `README.md` (most),
`ARTIFACT.md`, `docs/ADAPTIVE_CARRIERS.md`, `docs/ADAPTIVE_CHUNKING.md`,
`docs/GOP_HD_SUPPORT.md`, `docs/LATTICE_BACKEND_SURVEY.md` (also cites the
deleted LNP22/ISW21 probes), `docs/LATTICE_ZK_BDLOP_SPEC.md`,
`docs/review/README.md`. Module renames to apply: `src.X` becomes
`src.transport.X` for the seven transport modules, `src.registry.X` for
`zkp_registry`, `zkp_sessions`, `zkp_session_http`, `lattice_pq`, and
`src.legacy.X` for the legacy modules; `benchmark.X` becomes
`benchmark.legacy.X` for the non-`latticezk_` scripts. `legacy/native/README.md`
links `native_payload_capacity_probe_20260930.md` and `legacy/lazer/README.md`
uses `docker compose`; both go stale with the pending deletions below.

## Second pass: pending deletions

A stricter rule was requested afterwards: keep a tracked file only if the
current system, a working and tested legacy subsystem, or paper/result
provenance needs it. The files below fail that rule. They are **not deleted
yet**: the deletion was blocked by the session's permission check and waits
for explicit approval. Nothing that is kept imports or reads them.

| Path | Reason |
|---|---|
| `benchmark/legacy/` except `_common`, `blind_core_trial`, `clean_artifacts`, `lattice_in_video_feasibility`, `locked_operating_contract`, `native_pipeline_matrix`, `sec4_security`, `sec5_zkp`, `streaming_capacity_scan`, `trust_corpus` (+ manifest): 31 scripts (SEC1-3, SEC6-10, SEC45-47, `safe_benchmark_runner`, `statistical_benchmark`, blind diagnostics, `public_api_realization`, `validated_pool_proxy_diagnostic`, `trust_architecture_diagnostic`, `patchable_capacity_scan`, two native probes) | no test runs them; the kept ten are imported by a test or by a current `latticezk_*` benchmark (`_common`, `sec4_security`, `sec5_zkp`) |
| `benchmark/latticezk_profile.py` | one-off profiler; no script, doc or test names it |
| `src/legacy/verifier_blind_keyed.py` | its only caller was `blind_contract_operating_point.py` |
| `src/runtest/legacy/demo_embed_verify.py` | demo script, not a test; needs a Groth16 build |
| `src/runtest/legacy/test_native_cli_fixture.py` | tests `zkstego_blind_bits`, which no CMake target builds; always skipped |
| `legacy/docker/` (7), `legacy/ci.yml`, `.dockerignore` | untested images; a CI file GitHub never ran |
| `docs/legacy/ARTIFACT_POLICY.md`, `OPERATING_ENVELOPE.md`, `PAPER_EVIDENCE.md`, `trust_corpus_onboarding.md`, `system_video_embedding_walkthrough.tex/.pdf` | describe the frozen pre-lattice baseline (June-September 2026); `ARTIFACT.md`, this inventory and `docs/review/CLAIMS.md` cover the current equivalents. If the docs stream wants the old supported-envelope list (codec/profile/GOP/QP limits), take it from `OPERATING_ENVELOPE.md` before deletion |
| `benchmark/results/` non-`q2` outputs of the scripts above and old diagnostics: 19 `.md`/`.txt` notes, 4 `ringo_*`, 2 `streaming_*_capacity_*`, `lattice_zkp_unreviewed_capacity_probe.json`, 2 `native_pipeline_matrix_*` summaries, all `sec1`-`sec7` PNGs and `sec2`-`sec7` data, the `sec45` PNG, `sec46`/`sec47` data, `trust_architecture_diagnostic.json` | cited by no paper table, current doc or test |

Kept on purpose: `benchmark/results/q2/**`, the `latticezk_*` results
(current system), `sec1_quality_data.json` (read by
`test_phase7_regression_cases`), `sec45_trust_evidence_data.json` and
`trust_corpus_validation.json` (read by `src.legacy.trust.product_readiness`
in `test_future_trust_architecture`).

## Verification

- `python -B scripts/repro.py unit-tests`: PASS; the pytest part is 434
  passed, 1 skipped, the same as on the tree before the cleanup; the five
  script suites are OK.
- Pre-existing failures at `1a01cd3`, unchanged by the cleanup:
  `test_adaptive_carriers::test_direct_contract_serialisation_and_profile_ids_are_unchanged`
  (MAGNITUDE profile id `ad6321a5...` against the pinned `ff66b446...`),
  one of four cases of `test_cavlc_coefficient_bit_ranges`, and the Groth16
  cases of `legacy/test_phase1_zk_proof` and `legacy/test_hardening`, which
  need a `legacy/circuits/build`.
- Importing `src.lattice_zk.cli`, `benchmark.latticezk_video_e2e`,
  `benchmark.latticezk_q2_sweep` or `benchmark.latticezk_capacity_scan` loads
  no `src.legacy` or `benchmark.legacy` module.
- `legacy/native` builds with CMake (MinGW); its ctest and
  `legacy/test_native_relay_ffmpeg.py` pass against that build.
- 200-frame CIF registered E2E (`container_cif_q22_g1`, `--chunk-bytes 4200`,
  magnitude carrier, `bdlop-open-128-v2`): the 8165-byte envelope verified
  from the video alone; the replayed session and the tampered copy were
  rejected.
