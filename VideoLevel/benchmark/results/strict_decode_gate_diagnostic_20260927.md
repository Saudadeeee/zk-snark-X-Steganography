# Strict-decode diagnostic — 2026-09-27

This is diagnostic evidence, not a benchmark. It does not contain or verify a lattice ZKP and must not be cited as broad codec compatibility, visual-quality, or realtime evidence.

Environment: Windows development workstation, Python 3.12, FFmpeg 8.0.1 (`essentials_build-www.gyan.dev`). Video inputs were generated with FFmpeg `testsrc2` and encoded as H.264 Baseline/CAVLC at QP 22.

| Run | Input / payload | Observed result |
|---|---|---|
| Single-frame round trip | 160×128, 1 frame; 1 byte `a5` | 8 carriers, 1 changed block; strict decode passed and extraction exactly returned `a5`. Cover/stego were each 4,894 bytes. Cover SHA-256: `06f2f1d993e4152380139e5e91f22185f9f6fe491a05e4b29d38ac12d7be1297`; stego SHA-256: `b575107e0e6348274508275c395ef8ec9842bbd6a96269c0bf74da7e9ed435b5`. Temporary artifacts: `%TEMP%/zkstego-cavlc-diag-rat5dypj/`. |
| Patchability counterexample | 352×288, 3 all-IDR frames; 154 diagnostic bytes generated with SHAKE-256 (not a proof) | The block-level filter reported 1,232 positions. Embedding changed 587 blocks; the patcher applied 579 and skipped 8. FFmpeg reported CAVLC/macroblock errors, and extraction did not exactly match. All eight skipped blocks also returned non-`None` from `validate_block_patchability`, indicating that block-level validation does not guarantee that the requested carrier modification will be applied. Cover/stego were each 28,737 bytes. Cover SHA-256: `63c233147cf8d08a4fd98aa9ea2eee449dccdf884db6ed6dbbe5ecce523550b0`; stego SHA-256: `0225fd8929707f1a5e87cbf451978c85016e5ddcc11043d5637b3a550573dcc7`. Temporary artifacts: `%TEMP%/zkstego-cavlc-1232-kjw1ez4k/`. |
| Verified-frame context regression | Same 352×288, 3-frame source and 1,232-bit diagnostic payload; SafetyFilter called with `frame_verified_data` | The previously false-approved carrier `(82,11,-3)` is now excluded: without verified frame context it was selected; with context the validator found `nC=2`, `T1 override=1`, and rejected the sign flip because it changes encoded length from 17 to 16 bits. With context enabled, the diagnostic changed/applied 631 blocks with no patcher skips and extraction was exact, but FFmpeg still rejected the stream at macroblock 1,0. This fixes one demonstrated false-positive path but does not guarantee decoder validity. Temporary artifacts: `%TEMP%/zkstego-context-direct-_okyne_k/`. |
| Public API, default candidate filtering | Same 352×288, 3-frame source; 24-byte message, 512 required bits | Two reconstructed candidates failed strict decode. Retrying without changed blocks left 268 usable bits; `embed()` raised `InsufficientCapacityError`. No stego output was promoted. Temporary artifacts: `%TEMP%/zkstego-public-embed-doccxemw/`. |
| Public API, `ffmpeg_validate=True` | Same source; 24-byte message, 512 required bits | 768 FFmpeg candidate positions narrowed to 470 after patchability filtering. `embed()` raised `InsufficientCapacityError` before publishing a final candidate. Temporary artifacts: `%TEMP%/zkstego-public-ffmpeg-aa6ebwe0/`. |
| Public API, `ffmpeg_validate=True` | Same source; 8-byte message, 376 required bits | 632 FFmpeg candidate positions narrowed to 386. The reconstructed candidate failed strict decode; excluding changed blocks left 195 positions, so `embed()` raised `InsufficientCapacityError`. No invalid stego output was promoted. Temporary artifacts: `%TEMP%/zkstego-public-small-jnlo7v4v/`. |
| Public API after verified-context fix, `ffmpeg_validate=True` | Same source; 1-byte message, 320 required bits | Took 139.13 seconds. 576 FFmpeg candidate positions narrowed to 442. A reconstructed candidate failed strict decode; excluding changed blocks left 274 positions, so `embed()` raised `InsufficientCapacityError`. No output or temporary candidate remained. Temporary artifacts: `%TEMP%/zkstego-context-fixed-c4cy5kdd/`. |
| Public API after retry-contract refactor | Same source; 24-byte message, 512 required bits | Took 19.87 seconds. `embed()` raised `InsufficientCapacityError` with 265 positions remaining; the destination and temporary candidate set were empty. No carrier list with skipped changed blocks was accepted. Temporary artifacts: `%TEMP%/zkstego-context-fixed-c4cy5kdd/`. |
| Real asset first-IDR API attempt | First access unit copied from `data/encoded/deadline_cif_q22_g1_600f.h264`; 1-byte message, 320 required bits | First-IDR test file was 28,237 bytes. `embed()` failed closed in 9.132 seconds with 245 positions remaining; the destination and temporary candidates were absent. This is one IDR only and does not measure the full 600-frame stream. Temporary artifacts: `%TEMP%/zkstego-real-idr-nxwwyou2/`. |
| Parser-offset trust audit | Full `data/encoded/deadline_cif_q22_g1_600f.h264` and `data/encoded/foreman_cif_g8_300f_b800k.h264` | FFmpeg strict decode passed for the 600-frame deadline asset. On its first 27,631-byte IDR, `TraceableCAVLCParser` returned 2,506 offsets but also 97 integrity issues (96 heuristic macroblock resyncs plus a chroma residual error). The foreman reconstruction path likewise encountered repeated heuristic resyncs at the first IDR. This confirms the parser was producing offsets after losing authoritative MB alignment. The pipeline now rejects such offsets before candidate selection instead of relying solely on the much later FFmpeg output gate. |

The exact elapsed time, CPU, and RSS of the public-API attempts were not instrumented, so this report does not claim timing or resource measurements. The FFmpeg candidate-validation run visibly took on the order of minutes for a three-frame synthetic clip; it is not realtime evidence.

## CAVLC coeff_token correction investigation — 2026-09-27

An added regression suite checks normative Table 9-5 codewords for the `nC` classes, including the shared `nC=4..7` table, the `nC>=8` codewords, and the dedicated chroma-DC table. Those known vectors pass. A further test exposed and now prevents the old behavior where a truncated/invalid coeff_token was silently converted into `(TotalCoeff=0, TrailingOnes=0)` after fallback attempts. The decoder now uses only the table selected by `nC` and raises an error on invalid input; this is fail-closed behavior, not a complete parser fix.

On the same first IDR of `deadline_cif_q22_g1_600f.h264`, the strict decoder returned 2,613 candidate offsets and 159 integrity issues, including invalid chroma-AC coefficient counts and invalid luma coeff_tokens, and marked the result untrusted. The earlier fallback-enabled diagnostic recorded 2,506 offsets and 97 issues. These counts are not a success improvement: removing fallback exposes more malformed parse paths rather than hiding them as plausible coefficients. The parser still cannot be used for embedding this valid input, so the pipeline correctly rejects it. The input itself is a valid FFmpeg-decodable H.264 stream; parser compatibility remains unresolved.

Verification:

```text
py -3.12 -m pytest -q src/runtest/test_cavlc_coeff_token_tables.py src/runtest/test_phase22_parser_integrity_gate.py
12 passed
```

This is parser debugging evidence only; it does not measure ZKP generation, extraction success, quality, resource use, or realtime performance.

The chroma neighbor predictor was also changed to represent picture-boundary neighbors as unavailable (`None`) rather than inserting a synthetic count of 2. A focused unit test covers both-missing, one-available, and two-available cases. Re-running the same IDR after this correction still reports 160 integrity issues: 96 heuristic resynchronizations, 51 luma residual errors, and 13 chroma-AC errors. Thus the correction addresses a specific wrong `nC` input but does not materially resolve end-to-end parser trust; the stream remains rejected.

Combined selected regression run:

```text
py -3.12 -m pytest -q src/runtest/test_phase19_strict_decode_gate.py src/runtest/test_phase20_analysis_cache_patchability_context.py src/runtest/test_phase21_application_retry_contract.py src/runtest/test_phase22_parser_integrity_gate.py src/runtest/test_cavlc_coeff_token_tables.py src/runtest/test_cavlc_nc_prediction.py src/runtest/test_phase13_streaming_capacity_scan.py
25 passed
```

## `run_before` table audit — 2026-09-27

Comparing the local Table 9-10 codewords against FFmpeg 8.0 `h264_cavlc.c` exposed additional normative table errors: the `zerosLeft=4` codebook omitted runs 3/4 and the `zerosLeft>=7` codewords had incorrect lengths/mappings. The corrected implementation uses the shared long zero-prefix codebook for `zerosLeft>=7` and bounds decoded runs against the remaining zeros. A read-only comparison of all contexts `zerosLeft=1..14` against FFmpeg now reports zero mismatches. See the [FFmpeg 8.0 CAVLC source](https://www.ffmpeg.org/doxygen/8.0/h264__cavlc_8c_source.html), Tables initialized from `run_len`/`run_bits`.

After this correction, the same first IDR yields 2,446 candidate offsets but remains untrusted with 208 parser integrity issues (102 heuristic resyncs, 54 luma residual errors, 52 chroma-AC errors). This is fewer surfaced issues than the immediately preceding strict run (335), but it is still a parser failure, not successful extraction. The source H.264 remains outside the embedder's accepted set until all integrity errors are resolved.

The run-before regression vectors and the previously selected strict-decode/CAVLC suite pass (32 tests). The `total_zeros` VLC maps were also compared against the FFmpeg 8.0 source and had no codeword mismatches; the remaining issue is therefore not evidence of a differing `total_zeros` table and needs further syntax/neighbor-context investigation.

## First-level CAVLC adjustment audit — 2026-09-27

The same FFmpeg source comparison found that `_decode_levels` applied the first non-trailing level offset to the wrong condition: it adjusted `TrailingOnes == 3` rather than `TrailingOnes < 3`. This affects decoded level values and can change the adaptive suffix length for later levels in the same block. Regression cases now cover the boundary for `TrailingOnes=0,1,2,3` and both signs, and all pass after correcting the first-level offset.

Re-running the same valid first IDR after this change produces 2,945 candidate offsets and 146 integrity issues (77 heuristic resyncs, 31 luma residual errors, 38 chroma-AC errors). The first recorded issue is at macroblock 25, versus macroblock 1 before this correction. This is concrete improvement in parser progress, but not proof that earlier offsets or the full stream are correct: `parse_trusted` remains false and pipeline use remains blocked. FFmpeg independently decodes the input successfully with `-v error -xerror` (exit 0), establishing that the observed failure is in the custom parser path, not a decoder rejection of the source.

Latest selected regression run:

```text
py -3.12 -m pytest -q src/runtest/test_phase19_strict_decode_gate.py src/runtest/test_phase20_analysis_cache_patchability_context.py src/runtest/test_phase21_application_retry_contract.py src/runtest/test_phase22_parser_integrity_gate.py src/runtest/test_cavlc_coeff_token_tables.py src/runtest/test_cavlc_nc_prediction.py src/runtest/test_cavlc_coefficient_bit_ranges.py src/runtest/test_phase13_streaming_capacity_scan.py
38 passed
```

## Code change and verification

`src.core.analysis_cache` now passes verified frame/offset context into `CAVLCSafetyFilter`, allowing it to use the patcher's recovered `nC` and trailing-ones override rather than relying only on the trace parser's values. `src.embedder.embed()` reconstructs into a temporary candidate, requires a strict full-video FFmpeg decode, and atomically promotes only a candidate that passes. Invalid candidates are rejected and their changed blocks are excluded for a retry; an output that fails validation is not reported as successful.

Verification run:

```text
py -3.12 -m pytest -q src/runtest/test_phase19_strict_decode_gate.py src/runtest/test_phase20_analysis_cache_patchability_context.py src/runtest/test_phase21_application_retry_contract.py
8 passed

py -3.12 -m py_compile src/embedder.py src/core/analysis_cache.py src/runtest/test_phase19_strict_decode_gate.py src/runtest/test_phase20_analysis_cache_patchability_context.py src/runtest/test_phase21_application_retry_contract.py
passed

py -3.12 src/runtest/test_phase13_streaming_capacity_scan.py
11/11 passed

git diff --check
passed
```

These checks and fixes do not make the system complete. The verified-context fix removes one false-positive carrier, but the 1,232-bit diagnostic still produces an FFmpeg-invalid stream; the public API fails closed for the tested operating points. Total capacity, blind extraction, actual ZKP embedding, visual quality, resource use, HTTP API, and edge/realtime performance remain unverified here.

The parser-integrity gate is an additional safety stop, not a parser repair: the legacy `test_phase4_reconstruct.py` now fails at fixture construction because its valid foreman bitstream triggers parser recovery and is correctly refused. The next implementation task is to make the CAVLC parser spec-correct on these streams, then require zero recovery/errors and rerun strict-decode end-to-end tests before restoring a positive capacity claim.

## Encoder/decoder first-level symmetry — 2026-09-27

A round-trip test was added for the CAVLC encoder's first non-trailing level with `TrailingOnes` values 0 through 3, both signs, and `TotalCoeff > 10`. Before the correction, all five low-coefficient cases failed: the decoder produced magnitude 3 for encoded magnitude 2, and the `TrailingOnes=3` cases could lose block alignment. The encoder used the inverse first-level offset condition from the decoder and incorrectly incremented initial `suffixLength` for `TrailingOnes=3`.

The encoder now applies the first-level `levelCode` offset when `i == 0 && TrailingOnes < 3`, and initializes `suffixLength` to 1 only when `TotalCoeff > 10 && TrailingOnes < 3`. The tests capture the writer's meaningful bit count before byte-alignment padding; this avoids treating trailing storage padding as CAVLC syntax.

Verification on the current worktree:

```text
py -3.12 -m pytest -q src/runtest/test_cavlc_coeff_token_tables.py src/runtest/test_cavlc_nc_prediction.py src/runtest/test_phase2_h264_parser.py src/runtest/test_phase19_strict_decode_gate.py src/runtest/test_phase22_parser_integrity_gate.py
43 passed
```

The full `src/runtest` pytest collection is currently blocked before tests run because `test_phase11_benchmark_reproducibility.py` imports the absent `benchmark.test_realtime_camera_recorder` module. That legacy realtime-camera suite was not silently skipped or represented as passing.

The same `deadline_cif_q22_g1_600f.h264` first IDR was re-parsed after this change (the change is in the encoder and does not alter the decoder path): 2,945 candidate offsets, `parse_trusted=False`, 146 integrity issues (77 heuristic resynchronizations, 31 luma residual errors, 38 chroma-AC errors). The first issues occur at MB 25 and MB 32. This confirms the encoder round-trip defect is fixed by focused vectors but the core parser-trust gate remains unresolved; it is not evidence of a valid full-video embedding or a usable lattice-ZKP pipeline.

## MB 25 bit-boundary trace — 2026-09-27

Instrumented the actual first-IDR parse around the first desynchronization without changing parser behavior. The parser enters MB 24 at RBSP bit 19,923, reads `mb_type=0`, `CBP=47`, `intra_chroma_pred_mode=2`, then consumes its coded luma/chroma residual calls through bit 20,946. At the next macroblock header, the parser reads `intra_chroma_pred_mode=6`, which is invalid; it resets to bit 20,946, then the existing recovery heuristic skips 100 bits and accepts a later candidate at bit 21,046.

This narrows the symptom to an incorrect boundary before/at the macroblock following MB 24; it does not identify which residual block or context first diverges. All instrumented CAVLC calls for MB 24 returned syntactically valid values, so this trace alone cannot prove they consumed the correct syntax. The correct next investigation is an independent per-block syntax/context comparison around MB 24, not reducing the recovery threshold or accepting the candidate at bit 21,046.

## MB 24 context and level-decoder differential — 2026-09-27

Two isolated hypotheses were tested without changing production code:

- Recomputed `nC` independently from the stored luma/chroma neighbor-count grids for MB 24. All 16 luma contexts and all 8 chroma-AC contexts matched the parser's selected context; the chroma contexts were `2,2,1,2,2,1,2,2`.
- Temporarily substituted a second level decoder written from the FFmpeg 8 CAVLC algorithm (including first-level handling and adaptive suffix updates) while keeping the current coeff-token/zeros/run parsing. It produced the same parser result: 2,945 offsets and the same 146 integrity issues, with the first resync still at MB 25 / bit 21,046. This makes the level-decoding branch an unlikely cause of the first desync, though the experiment is not an independent full-block decoder.

FFmpeg 8's source orders luma residuals by four 4x4 blocks per 8x8 group, then the two chroma-DC blocks, then chroma-AC blocks by component; this matches the current loop order for the tested 4:2:0 stream ([FFmpeg CAVLC source](https://www.ffmpeg.org/doxygen/8.0/h264__cavlc_8c_source.html), `decode_luma_residual` and chroma residual calls). This is only an order cross-check, not proof that the custom parser's bit positions are correct. The installed FFmpeg binary's debug flags did not expose per-block traces, so exact bit-for-bit comparison against its internal reader remains unavailable from that binary.

## Chroma CBP metadata semantics — 2026-09-27

A focused regression test exposed an independent metadata bug in `MacroblockParser._decode_cbp_to_blocks`: for `coded_block_pattern_chroma == 2`, it had set `chroma_dc_present=False` and `chroma_ac_present=True`. The syntax value 2 means chroma DC and AC are both present; value 1 means DC only, while values 0 means neither and 3 means both. The flags now use the semantic ranges (`dc = chroma_cbp >= 1`, `ac = chroma_cbp >= 2`).

The test was first run red (1 failure for value 2), then passed with the fix. The combined selected parser/CAVLC suite reports 47 passed, and `py_compile`, Ruff on the new test, and `git diff --check` pass. Re-running the real first-IDR fixture produces the unchanged result: `parse_trusted=False`, 2,945 offsets, and 146 issues (77 heuristic resyncs, 31 luma residual errors, 38 chroma-AC errors). The incorrect flag was not the cause of MB 25 desynchronization because the extraction loop independently derived chroma presence using the semantic ranges already; the correction fixes the `MacroblockData` contract only.

## FFmpeg macroblock-type map cross-check — 2026-09-27

Ran the installed FFmpeg 8.0.1 decoder with `-debug mb_type` on the same Annex-B source. Its first-frame map labels addresses 0–53 as intra-4x4 (`i`). The custom parser independently records `mb_type=0` (I_4x4) for MB addresses 0–24, matching that coarse map. At MB 25 the custom parser also reads `mb_type=0` but then fails on `intra_chroma_pred_mode=6` and does not commit metadata. This supports that the parser reaches plausible macroblock classes through MB 24; it does not validate CBP, prediction-mode syntax, or any residual bit offsets, so it does not locate the first wrong residual block.

## Bit-cursor and CBP-table source audit — 2026-09-27

Inspected the shared `BitstreamReader`: `position` and `tell()` both read the same `pos` field, while `read_bits`, `seek`, and parser recovery all update that field. No second cursor or `position`/`pos` divergence was found. `H264BitstreamParser` strips the one-byte NAL header before constructing `rbsp_byte` and removes emulation-prevention bytes before the slice parser starts.

Compared the local 48-entry Intra CBP mapping used for I_4x4 macroblocks with FFmpeg's `ff_h264_golomb_to_intra4x4_cbp`; entries match exactly ([FFmpeg h264data.c](https://www.ffmpeg.org/doxygen/8.1/h264data_8c_source.html)). Thus neither the cursor alias nor this CBP lookup explains the observed MB 25 error. These checks still do not verify every parsed header bit or CAVLC codeword boundary; the unresolved defect remains in the custom syntax/residual progression.

## Multi-fixture parser trust check — 2026-09-27

Parsed the first IDR of four local H.264 fixtures using the same `TraceableCAVLCParser` and current SPS/PPS parser. `foreman_cif_q22_g1.h264` parsed all 396 macroblocks with 948 patch offsets, `parse_trusted=True`, and no integrity issues. `coastguard_cif_q22_g1_600f.h264` parsed 396 macroblock attempts and produced 2,624 offsets, but remained untrusted with 148 issues (first heuristic resync at MB 5 / bit 3,030). `foreman_cif_g8_300f_b800k.h264` was untrusted with 687 issues (first resync MB 53 / bit 31,605); `tmpqy_9nb6j_ffmpeg_pos_validate.h264` was untrusted with 207 issues (first resync MB 29 / bit 22,738). These are parser outcomes, not independent validity claims for the latter fixtures.

Added a real success-path regression for the Foreman QP22/GOP1 fixture alongside the existing fail-closed deadline fixture in `test_phase22_parser_integrity_gate.py`. Verification: 48 selected parser/CAVLC tests passed; FFmpeg 8.0.1 strict-decoded the complete Foreman file with `-v error -xerror` (exit 0). This establishes one valid all-intra/CAVLC fixture the current parser can trust, not general parser correctness. The Coastguard/deadline desynchronizations remain unresolved and still block broad embedding claims.

## Full phase-runner execution — 2026-09-27

Ran `py -3.12 src/runtest/run_all.py` to completion. The runner exited 1: 58/68 reported tests passed and two skipped. Phases 4 (reconstruction) failed all six checks on the Foreman GOP8 fixture because the strict parser gate rejected heuristic recovery at MB 53; Phase 5 skipped both lattice receipt/API tests because no benchmark asset was available; Phase 6 failed the near-blind video path on the deadline parser desynchronization; Phase 7 failed its all-intra operating-point case on the same deadline failure. Phases 1–3 passed, but Phase 1 is a legacy Groth16 utility test, not the required lattice-ZKP. Phases 12–18 passed their contract/preflight tests; Phase 14 verifies fail-closed LaZer preflight and does not execute a proof backend. This run confirms the user-facing full runner is not green and no end-to-end lattice proof is being exercised.

## CAVLC encoder override rejection — 2026-09-27

The pytest-style Phase 20 context test failed on its old fixture. The fixture had two trailing `-1` levels but forced `TrailingOnes=1`. The current encoder emitted a block that the local decoder parsed as `[0, -2, 2, -1, ...]` rather than `[0, -2, -1, -1, ...]`; this was not a valid patchability test vector. With the canonical override `TrailingOnes=2`, the block round-tripped exactly and verified context exposed only the two actual sign-bit carriers. `CAVLCEncoder.analyze_block` now rejects a supplied override that is outside 0..3 or differs from the coefficient block's actual trailing-one count. A regression first failed because the encoder accepted the invalid override, then passed after the guard was added. The Phase 20 fixture now asserts rejection of the noncanonical encoding and the validated sign-bit behavior. The four pytest-style phases 19–22 now execute through the main phase runner and all pass individually: Phase 19 4/4, 20 2/2, 21 2/2, 22 3/3. These checks do not clear the independent real-video parser failures recorded above.

## Phase 6 resource recheck — 2026-09-28

Ran `py -3.12 src/runtest/test_phase6_near_blind_manifest.py` against the test's selected `deadline_cif_q22_g1.h264` asset. The test was still running after about 15 minutes with no result output; the Python process had accumulated about 687 CPU seconds and reached approximately 5.15 GiB working set, while free physical memory fell to about 3.77 GiB. It was interrupted with a soft Ctrl+C at the predeclared 5 GiB safety threshold. The process exited and the test's temporary `test_p6_near_blind*` artifacts were absent; free physical memory recovered to about 8.96 GiB. This is an incomplete, resource-limited run—not a pass and not an assertion failure. It reconfirms that the legacy whole-video API path is not operationally practical on this host for the selected long clip. Phase 6 is also a near-blind sidecar-based legacy path, so even a successful run would not satisfy the video-only lattice-proof objective.
