# Realtime CAVLC Theory and Implementation

## Purpose and current status

This document defines the only acceptable realtime path for this repository:
patch H.264 Baseline CAVLC residual coefficients inside independently decodable
IDR segments. Payload bytes must not be carried by SEI, NAL headers, container
metadata, or a spatial-pixel fallback.

The repository currently has a tested realtime control plane in
`src/realtime_cavlc.py`. It bounds queue latency, reuses one proof per epoch,
and reports an acceptance result. The current Python CAVLC parser and
reconstructor remain batch implementations. Therefore the controller is not
evidence that pixel content has already been patched at camera-frame rate.

The first native data-plane layer is implemented in `native/`: Annex-B NAL
splitting and lossless reassembly, EBSP to RBSP conversion, RBSP
emulation-prevention insertion, and bounds-checked fixed-length patch plans
across multiple NAL RBSPs in one segment transform. It is tested with CTest,
including preservation of unmodified NALs during a patched-IDR segment round
trip. It also decodes the luma `total_zeros`/`run_before` residual tail for
every CAVLC `TotalCoeff` value from 1 through 16; the test suite exercises all
table columns and one tail from a real IDR RBSP. It is intentionally limited to
a patch plan and isolated residual primitives: native slice traversal,
candidate selection, full block re-encoding, and camera-segment E2E validation
remain required before deployment.

## CAVLC embedding theory

For an H.264 Baseline residual 4x4 block, let its quantized transform
coefficients in zigzag order be `c[0], ..., c[15]`. A CAVLC-safe sign channel
encodes one bit at coefficient `c[k]` as:

```text
bit 0: c'[k] =  abs(c[k])
bit 1: c'[k] = -abs(c[k])
```

The candidate must satisfy all of the following:

1. It is an AC coefficient, never DC.
2. Its magnitude is nonzero and its support does not change.
3. In the blind sign channel, it is a genuine CAVLC trailing-one sign flag;
   the flag offset is immediately after `coeff_token` and changing it must not
   alter any other CAVLC syntax bit. (The conventional LSB channel instead
   excludes trailing ones.)
4. Its re-encoded block has the same bit length as the source block.
5. The replacement must preserve a decodable slice and pass visual-quality
   policy.

Sign changes alter reconstructed pixels through the inverse transform while
keeping payload inside compressed video content. They are not metadata.

### ChromaAC context and bounds

For 4:2:0 ChromaAC, the DC transform coefficient is coded separately and an
AC block has `maxNumCoeff = 15`, not 16. Consequently `total_zeros` is absent
when `TotalCoeff == 15`; consuming the luma `TotalCoeff == 15` VLC at that
point corrupts the next block boundary.

`nC` for a ChromaAC `coeff_token` is derived from neighbouring **AC** blocks
of the same component (Cb never borrows Cr counts, and neither uses a
ChromaDC count). If both neighbouring macroblocks are available,
`nC = (nA + nB + 1) >> 1`; otherwise `nC = nA + nB`, with an unavailable,
skip, or uncoded neighbour contributing zero. This rule is a parsing invariant
for native traversal, not an optional estimator. The native full-slice reader
retains this state per component across macroblock boundaries for the locked
progressive, one-slice camera profile; FMO, MBAFF, CABAC, and nonzero
`first_mb_in_slice` are rejected rather than guessed.

## Realtime segment protocol

```text
camera encoder (Baseline, CAVLC, short all-intra GOP)
  -> Annex-B IDR segmenter
  -> bounded queue
  -> native CAVLC parser and safe-position selector
  -> proof epoch cache
  -> native sign patcher and RBSP emulation-prevention rewrite
  -> H.264 output
```

`RealtimeCAVLCScheduler` follows three operational rules:

- Capture must never wait for proof generation or a slow patch.
- At overload, discard the oldest unprocessed segment; do not silently grow
  latency.
- A proof is generated once for an epoch and reused by its segments.

The output is acceptable only when queue drops are zero and p95 CAVLC patch
latency is at most the frame interval (`1 / FPS`) or an explicitly stricter
budget.

## Native patcher contract

The pending native implementation must expose this logical function:

```text
patch_idr_segment(annex_b_segment, proof_bytes, embedding_key) -> annex_b_segment
```

It must:

1. Parse SPS/PPS once per stream and parse each IDR slice incrementally.
2. Decode enough CAVLC syntax to locate selected luma residual levels and
   retain exact start/end bit offsets.
3. Derive deterministic, key-ordered safe candidates; one modification per
   block by default.
4. Re-encode only length-invariant blocks, then rewrite the selected RBSP,
   regenerate emulation-prevention bytes, and preserve unrelated Annex-B NAL
   units byte-for-byte.
5. Return an unchanged segment when its validated capacity is insufficient;
   report that condition as a controlled drop/failure, never partial silent
   embedding.
6. Expose per-segment parse, patch, proof-wait and total-latency metrics.

## Performance plan

The batch benchmark is not a realtime benchmark. A target device must measure:

| Metric | Acceptance rule |
| --- | --- |
| CAVLC parse plus patch p50/p95 | p95 <= frame interval |
| End-to-end camera latency | within deployment budget |
| Queue drops | zero at sustained target FPS |
| CPU and RSS | recorded per target device |
| Decodability | FFmpeg or hardware decoder accepts every output segment |
| Quality | PSNR and SSIM against source capture |
| Payload integrity | extracted proof verifies after every run |

Run the scheduler contract test with:

```powershell
py -3.12 src/runtest/test_phase9_realtime_cavlc.py
```

The native patcher must add an E2E camera fixture and replace this controller
only acceptance with measured CAVLC segment results before realtime can be
claimed.

### Current measured boundary

On the current audit machine, the Python streaming sign-candidate pass over
the first 10 IDR slices of `deadline_cif_q22_g1_600f.h264` (16,768,616 bytes)
selected 1,096 keyed positions in 1.997 seconds (5.008 slices/s). Its bounded
selector retained only the requested positions and the observed working set
stayed below 45 MB during a full-file scan. This is evidence for bounded
candidate-selection memory, not a realtime claim: 5.008 slices/s is below a
30 FPS camera target and the measurement excludes native patch/write, proof,
and decoder validation.

### Latest end to end negative result

The Python path is not a usable embedding path yet. On the audit machine, a
one-byte blind proof payload (1,072 bits) was scheduled and patched into
`foreman_cif_q18_g1_300f.h264` (300 all-intra frames) in 280.579 seconds.
The patcher reported all 1,072 positions applied and preserved the source
byte length (3,551,610 bytes), but the resulting stream was not valid: FFmpeg
reported H.264 macroblock/CAVLC errors when run with `-xerror`, and blind
verification returned `valid: False` after 276.849 seconds (557.428 seconds
total). A normal FFmpeg invocation can conceal these errors while returning
zero; it is not an acceptable decoder acceptance test.

`patch_selected_sign_positions_streaming` now validates its temporary output
with `ffmpeg -v error -xerror` before atomically publishing it. A decoder
error therefore aborts the operation and removes the temporary file. This is
a fail-closed safety gate, not a repair for the current multi-block CAVLC
patcher. Until native slice traversal and a bit-exact per-block rewrite are
implemented and pass decoder plus blind-proof E2E tests, this repository must
not claim realtime, edge-ready, or usable blind embedding.

### Native header traversal baseline

The native `zkstego_idr_inspect` tool scanned the 600-IDR
`deadline_cif_q22_g1_600f.h264` fixture in 501.974 ms on the audit machine.
It parsed the stream's SPS/PPS and all IDR headers, selected parameter sets,
parsed the first I-macroblock, and decoded its first luma CAVLC 4x4 residual
block. It did not traverse later macroblocks or residual blocks, select blind
candidates, patch signs, or validate an output decoder. This is a functional
and performance baseline for one native residual block per IDR only; it does
not establish a realtime steganography claim.

The native library now also has a luma-I4x4 macroblock traversal primitive. It
uses CAVLC's four coded-8x8-group order, derives `nC` from already decoded
left/top 4x4 neighbours, and has unit coverage for empty coded blocks. The
implementation additionally has regression coverage for the first-level
adjustment required by H.264 9.2.2 and the empty `nC=4..7` coeff-token
(`1111`). These two details are essential because an incorrect level adjustment
can change subsequent suffix lengths, while a missing empty-block token
desynchronizes the rest of a macroblock.

`zkstego_idr_inspect --macroblock` exercises this primitive against every
IDR's first macroblock. An earlier luma-only run on
`foreman_cif_q18_g1_300f.h264` reached 300/300 first luma macroblocks in
135.755 ms. The current full-residual diagnostic reaches 300/300 first
macroblocks, including ChromaDC and all eight ChromaAC blocks. The prior NAL
123 ChromaAC failure was traced to 12 incorrect `nC=0..1` `coeff_token` rows
in the native Table 9-5(a) copy, not to a constant boundary-context rule.
The corrected table is compared programmatically with FFmpeg's canonical
Table 9-5 data and covered by per-row regression tests for `TotalCoeff=13..16`.

### Full-slice traversal evidence

The native reader now traverses the entire locked IDR slice, including mixed
I4x4 and I16x16 macroblocks, I16x16 luma DC (16 coefficients), I16x16 luma
AC (15 coefficients), 4:2:0 ChromaDC/ChromaAC, and raster neighbour state.
The I16x16 DC context follows FFmpeg's `pred_non_zero_count` mapping through
the normal luma block-zero neighbours; it is not a separate DC-grid context.
At completion the reader requires a valid `rbsp_stop_one_bit` followed only
by zero alignment bits.

On `foreman_cif_q18_g1_300f.h264` (3,551,610 bytes, SHA-256
`867CC0C68BBA4461E5699C1214236DF5CC75C658398C85F2E11BCCC11935DF57`), the
Release CTest traversed all 300 IDR slices, each with 396 macroblocks:
**118,800 macroblocks total**. It additionally asserts that I16x16,
ChromaDC, and ChromaAC paths were encountered. The command
`zkstego_idr_inspect ... --slice` independently reported the same counts and
the source fixture passes `ffmpeg -v error -xerror`. This proves native reader
coverage for that pinned fixture; it does **not** prove a generic H.264 reader
and does not yet establish rewrite, blind extraction, decoder-valid stego
output, or realtime operation. Those remain release gates.

### Length-invariant sign rewrite evidence

For each residual block with one or more trailing ones, native traversal emits
only the first trailing-one sign flag as its candidate. That bit follows the
`coeff_token`, so changing it cannot alter `TotalCoeff`, `TrailingOnes`, level
coding, run coding, or the RBSP bit length. Candidate identity is the tuple
`(NAL index, macroblock address, residual category, block index, RBSP bit
offset)`, deliberately using RBSP rather than EBSP offsets because regenerated
emulation-prevention bytes may move EBSP positions.

The native regression flips one such candidate, verifies the output bit and
the complete ordered candidate map after a full reparse, and CTest passes.
Independently, `zkstego_idr_inspect --flip-first-sign <new-file>` flipped NAL
3 / macroblock 0 / RBSP bit 91 in the pinned fixture; its temporary output had
3,551,610 bytes and SHA-256
`E1415CCC2CCA3DC13B7D71225401E8C9FEEEFF1BC493A119FE406EA5E138A7F0`.
`ffmpeg -v error -xerror -i <new-file> -f null -` returned successfully.
This is real strict-decoder evidence for **one** native sign rewrite. It does
not validate a keyed multi-bit schedule, payload framing, extraction, proof
verification, stream operation, or realtime performance.

### Canonical blind schedule (implementation gate)

The next native channel must use this single schedule contract; an extractor
derives it from the stego stream itself and never receives positions or a
sidecar. A candidate is exactly one parsed trailing-one sign bit per residual
block, with identity serialized as ASCII:

```text
<nal_index>:<macroblock_address>:<category>:<block_index>:<rbsp_bit_offset>
```

where `category` is `0=LumaDc`, `1=Luma4x4`, `2=ChromaDc`, or `3=ChromaAc`.
For a 32-byte secret `K`, the ordering score is the 32-byte HMAC-SHA-256
digest of that serialization under
the literal ASCII bytes `blind-native-cavlc-v1`, followed by one NUL byte and `K`.
Candidates are sorted lexicographically by
`(score, serialized identity)`, and the first `required_bits` candidates carry
payload bits in that order. The framing layer must authenticate and length-bind
the payload before embedding, so a wrong key produces an authentication failure
rather than a plausible message.

The native selector now has fixed candidate serialization, HMAC-score and
wrong-key order vectors. The `(score, identity)` tie fallback is deterministic;
creating a real SHA-256 HMAC collision for a runtime vector is not a feasible
test strategy. The schedule remains unimplemented end-to-end: Python parity,
embed/extract with a correct key, authenticated framing, and wrong-key
authentication rejection are all required before this is called blind extraction.

### September 2026 diagnostic update

The `nC=0` versus `nC=2..3` ChromaAC discrepancy must not be fixed by a
constant frame-edge value. A controlled probe that seeded unavailable ChromaAC
neighbours with `2` made Foreman NAL 123 parse, but then made NAL 3 reject a
ChromaAC `total_zeros` value outside its 15-coefficient bound. The probe was
discarded. Comparing native rows against FFmpeg instead found the malformed
Table 9-5(a) entries and corrected the actual source of the desynchronization.

FFmpeg's CAVLC decoder calculates `nC` from its populated
`non_zero_count_cache`; it does not substitute a fixed edge context. Native
completion still requires macroblock-by-macroblock availability and cache
state matching for luma and each chroma component before any CAVLC token may
be rewritten. The full-slice reader now implements that cache for the locked
one-slice profile and remains fail-closed outside it.

The legacy Python public-API E2E test is also not an edge benchmark. Its
Phase-5 full-file `embed`/`verify` execution accumulated approximately
3.33 GiB working set while processing the fixture, so it was stopped before
host memory exhaustion. It uses sidecars and a batch parser; it cannot be
used as evidence for the required sidecar-free native edge data plane.

## Blind extraction relationship

Blind extraction and realtime use the same sign-invariant candidate policy.
`src/blind.py` derives sign-only positions from the stego bitstream and secret
key. The native patcher must preserve this policy exactly; otherwise a stream
can be fast but cannot be extracted without a sidecar.
