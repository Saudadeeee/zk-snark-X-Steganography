# Codebase Structure - VideoLevel Steganography System

**Version:** upgrade-v3 (refactored April 2026)
**Tests:** 32/32 pass
**Last Updated:** 2026-04-04

---

## Architecture Overview

```
INPUT VIDEO (H.264 CAVLC)
    ↓
[Phase 1] ZK Proof Generation (snarkjs Groth16)
    ↓
[Phase 2] Parse H.264 — Extract IDR coefficients + bit offsets
    ↓
[Phase 3] Safety Filter — Find embeddable T1 positions (descending order)
    ↓
[Phase 4] Embed payload + Reconstruct stego video
    ↓
[Phase 5] Extract bits + Verify ZK proof
```

---

## Source Layout

```
src/
├── exceptions.py           — Custom exception hierarchy
├── zk_proof.py             — ZK binary format + snarkjs bridge
├── embedder.py             — PUBLIC API: embed()
├── verifier.py             — PUBLIC API: verify()
├── bitstream/              — H.264 CAVLC codec (internal)
│   ├── bitstream_io.py     — Bit-level reader/writer
│   ├── bitstream_ops.py    — BitstreamPatcher + BitstreamReconstructor
│   ├── cavlc.py            — CAVLCDecoder + CAVLCEncoder + VLC tables
│   └── h264.py             — H264BitstreamParser + TraceableCAVLCParser
├── core/                   — Core pipeline logic (internal)
│   ├── pipeline.py         — extract_all_idr_blocks(), extract_bits_direct()
│   └── stego.py            — CAVLCSafetyFilter, PayloadEmbedder
└── runtest/                — Per-phase test suite
    ├── _helpers.py
    ├── run_all.py
    ├── test_phase1_zk_proof.py
    ├── test_phase2_h264_parser.py
    ├── test_phase3_safety_embed.py
    ├── test_phase4_reconstruct.py
    └── test_phase5_extract_verify.py
```

---

## Module Descriptions

### `src/embedder.py` — Public API (embed)

Entry point for embedding. Orchestrates all phases.

```python
def embed(
    video_path, message, output_path, circuits_dir, secret_key,
    max_modifications_per_block=1, ffmpeg_validate=False,
) -> EmbedResult
```

Pipeline:
1. `ZKSnarkBridge.generate_proof_for_payload(message, secret_key)`
2. `pack(message, proof_bytes)` → payload blob
3. `extract_all_idr_blocks(video_path, rec)` → coefficients + metadata
4. `PayloadEmbedder.embed_payload(...)` → modified coefficients
5. `BitstreamReconstructor.reconstruct_video(...)` → stego video file

Returns `EmbedResult(bits_embedded, capacity_bits, output_path, proof_dict, public_dict)`.

---

### `src/verifier.py` — Public API (verify)

Entry point for extraction and verification.

```python
def verify(
    stego_video_path, original_video_path, circuits_dir, secret_key, message_length,
    max_modifications_per_block=1,
) -> VerifyResult
```

Pipeline:
1. `extract_all_idr_blocks(original_video_path, rec)` → position map
2. `CAVLCSafetyFilter.get_safe_positions(...)` → same order as embedding
3. `extract_bits_direct(stego_video_path, ...)` → raw blob bytes
4. `unpack(blob)` → (message, proof_bytes)
5. `ZKSnarkBridge.verify(proof_dict, public_signals)` → bool

Returns `VerifyResult(valid, message, proof_dict, public_dict, bits_extracted)`.

---

### `src/zk_proof.py` — ZK Binary Format + Bridge

Merged from `zk_payload_format.py` + `zk_snark_bridge.py`.

**Binary format (Groth16 BN128, 256 bytes):**
```
8 field elements × 32 bytes:
  pi_a.x, pi_a.y, pi_b.x[0], pi_b.x[1], pi_b.y[0], pi_b.y[1], pi_c.x, pi_c.y
```

**Blob layout:**
```
[4 bytes big-endian: len(message)] [message bytes] [256 bytes: proof]
```

**Public functions:**
- `pack(message, proof_bytes) → bytes`
- `unpack(blob) → (message, proof_bytes)`
- `proof_to_bytes(proof_dict) → bytes`
- `bytes_to_proof(data) → dict`
- `blob_bit_length(message) → int`

**`ZKSnarkBridge` class:**
- `generate_proof_for_payload(payload, secret_key) → (proof_dict, public_dict)`
  - Builds circuit input: `payload_hash = SHA256(payload)`, `commitment = SHA256(payload_hash || secret)`
  - Runs `node generate_witness.js` → WASM witness
  - Runs `npx snarkjs groth16 prove` → proof JSON
- `verify(proof_dict, public_signals) → bool`
  - Runs `npx snarkjs groth16 verify`
- `_build_public_signals(payload, secret) → list`

---

### `src/core/pipeline.py` — IDR Extraction Pipeline

Moved from `src/runtest/_idr_extract.py`.

**`extract_all_idr_blocks(video_path, reconstructor)`**

Parses all IDR NAL units. Returns:
- `coefficients` — list of `(mb_global, blk_idx, coeffs)` for non-zero luma blocks
- `frame_verified_data` — `{idr_mb_offset: (global_offsets, global_blocks)}`
- `nC_map` — `{(mb_global, blk_idx): nC}` for CAVLC context
- `nal_length_map` — `{(mb_global, blk_idx): bit_length}` (-1 = non-patchable)
- `t1_override_map` — `{(mb_global, blk_idx): trailing_ones_override}`

**`extract_bits_direct(stego_video_path, embed_safe_positions, ...)`**

Extracts embedded bits from stego video using original bit offsets (valid because patcher is length-preserving). Decodes each block at its known offset, reads LSB or T1 sign bit.

---

### `src/core/stego.py` — Safety Filter + Embedder

Moved from `src/embedder/embedder.py`.

**`CAVLCSafetyFilter`**

`get_safe_positions(coefficients, nC_map, nal_length_map, t1_override_map)`

Returns positions `(mb, blk, coeff_idx)` sorted **descending** (`-mb, -blk`) — Fix #7.

Five safety rules:
| Rule | Check |
|------|-------|
| Zero-preservation | Never 0↔nonzero (breaks TotalCoeffs) |
| T1 protection | Sign-bit slots for trailing ±1 coefficients |
| Bit-length invariance | Re-encoded block must match original NAL length |
| Magnitude threshold | `|coeff| >= 3` (LSB flip on 2→3 changes encoding) |
| Non-patchable exclusion | `nal_length_map == -1` → skip |

**`PayloadEmbedder`**

`embed_payload(coefficients, payload_blob, ...)` → `(modified_coefficients, bits_embedded)`

Iterates positions in **descending** order (Fix #7: start from last MB of last IDR to avoid intra prediction cascade). For each position:
- `coeff_idx >= 0`: flip LSB of `coefficients[coeff_idx]`
- `coeff_idx < 0` (encoded as `~real_idx`): flip sign of T1 coefficient

**`EncodingLengthChecker`**

`check(coefficients, nC, original_bit_length, t1_override)` → `bool`

Re-encodes block with `CAVLCEncoder` and compares bit count to `nal_length_map` value.

---

### `src/bitstream/h264.py` — H.264 Parser (~1,500 lines)

**Key classes:**
- `H264BitstreamParser` — top-level NAL unit parser; finds SPS, PPS, IDR, P-frame NALs
- `TraceableCAVLCParser` — parses IDR slices and tracks exact bit offsets per block
- `MacroblockParser` — parses one 16×16 macroblock; computes nC for each 4×4 block
- `NALUnit`, `SPS`, `PPS`, `SliceHeader` — data structures

**Bugs fixed in this module:**
- Fix #1: Chroma AC nC — use only within-MB luma TCs (not cross-MB)
- Fix #2: Luma nC — set `left_key = top_key = None` at cross-MB boundaries

---

### `src/bitstream/cavlc.py` — CAVLC Codec (~1,800 lines)

**`CAVLCDecoder`**
- `decode_block_cavlc(nC, max_num_coeff)` — Decode one 4×4 block from RBSP
- Returns `CAVLCBlock(levels, total_coeffs, trailing_ones, zeros_left, runs)`

**`CAVLCEncoder`**
- `encode_block(coefficients, nC)` — Encode one 4×4 block to RBSP bits
- `_analyze_block(coeffs)` — Count trailing ones, build encoding plan
- Fix #4: `_detect_trailing_ones` scans non-zero positions in reverse (not raw coefficients)

**VLC tables** (H.264 Table 9-2 through 9-7):
- `COEFF_TOKEN_TABLE` — nC-dependent lookup for (trailing_ones, total_coeffs)
- `TOTAL_ZEROS_TABLE`, `RUN_BEFORE_TABLE`

---

### `src/bitstream/bitstream_ops.py` — Patcher + Reconstructor

**`BitstreamPatcher`**

`get_unpatchable_blocks(rbsp_bytes, offsets)` → `(unpatch_set, matched_blocks)`

Identifies blocks where CAVLC re-encoding length != original. These get `nal_length_map = -1` and are excluded from embedding.

`patch_slice(rbsp_bytes, patches)` → `bytes`

Applies a list of `(bit_offset, old_bits, new_bits)` patches in-place. Patches must be length-preserving.

**`BitstreamReconstructor`**

`reconstruct_video(video_path, modified_coeffs, output_path, frame_verified_data)` → `bytes`

Rewrites the H.264 file: IDR NALs are patched at tracked bit offsets; P-frames are copied byte-for-byte.

`make_ffmpeg_position_validator(video_path, coefficients, frame_verified_data)` → `(validator_fn, cleanup_fn)`

Creates a temporary 1-IDR test video and tests each candidate position individually with FFmpeg. Positions that cause pixel errors (PSNR < threshold) are excluded. This is the empirical safety check that structural CAVLC analysis cannot provide.

`batch_psnr_validate(video_path, positions, ...)` → `list[valid_positions]`

Batch PSNR validation with greedy extension. Uses single-IDR FFmpeg decode for ~50x speedup. Fix #8: `max_greedy_per_idr=500` needed for sufficient capacity.

---

### `src/bitstream/bitstream_io.py` — Bit I/O Primitives

- `BitstreamReader` — Reads H.264 VLC codes: `read_bit()`, `read_ue()`, `read_se()`, Exp-Golomb
- `BitstreamWriter` — Writes H.264 VLC codes: `write_bit()`, `write_ue()`, `write_se()`
- `BitArray` — Indexed bit access over `bytes` object

---

### `src/exceptions.py` — Exception Hierarchy

- `ZKStegoError` — Base exception with context tracking
- `EmbeddingError` — Error during payload embedding
- `SafetyFilterError` — No safe positions found
- `InsufficientCapacityError` — Capacity < required bits

---

## Key Design Decisions

### Why descending embedding order? (Fix #7)

H.264 intra prediction: each macroblock is predicted from its left/top neighbors.
Modifying MB₀ cascades pixel errors through MB₁, MB₂, … → PSNR 7–11 dB.
Embedding from the **last** MB of the **last** IDR frame backwards means modified blocks have no downstream dependents → PSNR 22–36 dB.

### Why length-preserving patching?

`extract_bits_direct()` uses **original** bit offsets recorded during parse of the original video. If any patch changed a block's bit length, all subsequent offsets would be wrong. Length-preserving T1 sign flips and LSB flips (on `|coeff| >= 3`) guarantee offsets stay valid.

### Why empirical FFmpeg validation?

CAVLC structural checks (zero-preservation, bit-length invariance) cannot detect all unsafe positions. Some T1 flips produce valid CAVLC but trigger FFmpeg's intra prediction error handler, causing large pixel corruption. Only empirical testing reveals these positions.

### Blob format

```
[4B length][message][256B Groth16 proof]
```
The 4-byte header stores `len(message)` so the extractor knows where the proof starts. The proof is always 256 bytes (8 × 32-byte BN128 field elements).

---

## Test Suite

```
src/runtest/run_all.py
```

| Phase | File | Tests | What |
|-------|------|-------|------|
| 1 | test_phase1_zk_proof.py | 7 | pack/unpack, proof_to_bytes, ZK generate+verify |
| 2 | test_phase2_h264_parser.py | 8 | NAL parsing, SPS/PPS, IDR detection, offset tracking |
| 3 | test_phase3_safety_embed.py | 8 | Safety filter rules, embedding, extraction |
| 4 | test_phase4_reconstruct.py | 5 | Bitstream reconstruction, byte-level diff |
| 5 | test_phase5_extract_verify.py | 4 | Full round-trip: embed → extract → ZK verify |

All 32/32 pass.

---

## Embedding Capacity

For `foreman_cif_g8.h264` (352×288 CIF, QP=10, GOP=8, 7 IDR frames):
- ~1,205 safe T1 positions per IDR frame
- ~8,435 total bits available
- Required for 14-byte message: `(4 + 14 + 256) × 8 = 2,192 bits`
- Margin: **3.8×**
