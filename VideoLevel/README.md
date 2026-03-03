# ZK-SNARK Video Steganography

Hide cryptographic ZK proofs inside H.264 videos using CAVLC coefficient embedding.

**Status:** Production Ready | **Branch:** `upgrade-v3` | **Tests:** 32/32 pass

---

## Overview

This system embeds a Groth16 zero-knowledge proof and a secret message into an H.264 video by modifying DCT coefficients in IDR (intra) frames. The stego video is visually identical to the original; the embedded data can only be extracted by a party who knows the embedding positions.

**What gets embedded:**
```
Blob = 4-byte length header | message bytes | 256-byte Groth16 proof
```
For a 14-byte message (`"Hello ZK-Stego"`): blob = 274 bytes = 2192 bits.

**Circuit:** `PayloadVerify` (Circom + snarkjs)
```
Proves:   commitment = SHA256(SHA256(message) || secret_key)
Public:   payload_hash[256], commitment[256], payload_length
Private:  secret[256]
```
The secret key never appears in the video. The verifier only needs the extracted proof and message.

---

## How It Works

```
INPUT VIDEO (H.264)
      |
      v
[Phase 1]  ZKSnarkBridge.generate_proof_for_payload(message, secret_key)
             -> proof_dict, public_dict  (Groth16 BN128, 256 bytes)
      |
      v
[Phase 2]  H264BitstreamParser + TraceableCAVLCParser
             -> CAVLC blocks with bit-offsets, nC values, NAL lengths
             -> BitstreamPatcher.get_unpatchable_blocks() marks non-embeddable blocks
      |
      v
[Phase 3]  CAVLCSafetyFilter.get_safe_positions()
             -> safe (mb, blk, coeff_idx) positions satisfying:
                Rule 1: zero-preservation (never 0->nonzero or nonzero->0)
                Rule 2: trailing-ones protection (last <=3 consecutive +-1)
                Rule 3: bit-length invariance (CAVLC re-encoding length unchanged)
                Rule 4: magnitude threshold (|coeff| >= 3)
             -> also produces sign-bit positions (~coeff_idx) for trailing +-1
           PayloadEmbedder.embed_payload() modifies LSBs / trailing-one signs
      |
      v
[Phase 4]  BitstreamReconstructor.reconstruct_video()
             -> BitstreamPatcher applies bit-exact patches residual per block
             -> output: stego_video.h264 (same size as input +-2%)
      |
      v
[Phase 5]  extract_bits_direct()
             -> uses original bit-offsets (patcher is length-preserving)
             -> decodes blocks at known positions in stego RBSP
             -> returns extracted blob bytes
           ZKSnarkBridge.verify(proof_dict, public_signals)
             -> cryptographic verification via snarkjs groth16 verify
```

---

## Project Structure

```
VideoLevel/
|
+-- src/                            # Main source code (flat layout)
|   +-- __init__.py
|   +-- exceptions.py
|   +-- zk_payload_format.py        # pack() / unpack() / blob_bit_length()
|   +-- zk_snark_bridge.py          # Python <-> snarkjs/Node.js bridge
|   |
|   +-- bitstream/                  # H.264 CAVLC codec
|   |   +-- bitstream_io.py         # Bit-level reader/writer
|   |   +-- bitstream_patcher.py    # Bit-exact patching of NAL bytes
|   |   +-- bitstream_reconstructor.py  # Full video reconstruction
|   |   +-- cavlc_decoder.py        # Decode DCT coefficients from RBSP
|   |   +-- cavlc_encoder.py        # Encode DCT coefficients to RBSP
|   |   +-- cavlc_tables.py         # VLC lookup tables
|   |   +-- h264_parser.py          # NAL / SPS / PPS parser
|   |   +-- nal_handler.py          # NAL unit assembly
|   |   +-- macroblock_parser.py    # Macroblock-level parsing
|   |   +-- traceable_cavlc_parser.py  # Offset-tracking CAVLC parser
|   |
|   +-- embedder/                   # Steganography
|   |   +-- cavlc_safety_filter.py  # 5-rule safety filter
|   |   +-- encoding_length_checker.py
|   |   +-- payload_embedder.py     # LSB + sign-bit embedding
|   |
|   +-- decoder/
|   |   +-- cavlc_extractor_simple.py
|   |
|   +-- crypto/                     # ZK utilities
|   |   +-- ldpc_codec.py
|   |   +-- rc4_cipher.py
|   |   +-- rs_codec.py
|   |   +-- proof_generator.py
|   |   +-- proof_serializer.py
|   |   +-- proof_wrapper.py
|   |   +-- data_interleaver.py
|   |   +-- temporal_interleaver.py
|   |
|   +-- preprocessing/
|   |   +-- context_analyzer.py
|   |   +-- dwt_analyzer.py
|   |   +-- hybrid_selector.py
|   |   +-- yuv_converter.py
|   |
|   +-- utils/
|   |   +-- quality_metrics.py
|   |
|   +-- runtest/                    # Per-phase test suite
|       +-- _helpers.py
|       +-- _idr_extract.py         # Shared IDR extraction helpers
|       +-- test_phase1_zk_proof.py
|       +-- test_phase2_h264_parser.py
|       +-- test_phase3_safety_embed.py
|       +-- test_phase4_reconstruct.py
|       +-- test_phase5_extract_verify.py
|       +-- run_all.py              # Orchestrator
|
+-- circuits/                       # Circom ZK-SNARK
|   +-- payload_verify.circom       # SHA256 commitment circuit
|   +-- package.json                # snarkjs, circomlib
|   +-- build/
|       +-- payload_verify_js/      # WASM witness generator
|       +-- proving_key.zkey        # Groth16 proving key (~31 MB)
|       +-- verification_key.json   # Verification key
|       +-- payload_verify.r1cs     # R1CS constraints
|       +-- payload_verify.sym      # Symbol table
|       +-- pot17_final.ptau        # Powers of tau (~144 MB)
|
+-- data/
|   +-- encoded/                    # H.264 test videos
|   |   +-- foreman_cif_g8.h264     # Primary test video (GOP=8, 7 IDR frames)
|   +-- raw/                        # Y4M source files
|   +-- output/                     # Stego output (cleaned after tests)
|
+-- docs/
|   +-- theory.md
|   +-- theory_detailed.md
|
+-- e2e_groth16_test.py             # End-to-end pipeline script
+-- e2e_extraction_test.py
+-- capacity_analyzer.py
+-- .gitignore
+-- README.md
```

---

## Quick Start

### Requirements

- Python 3.8+
- Node.js 14+ with npm
- numpy (`pip install numpy`)

### Setup

```bash
# 1. Install Python dependencies
pip install numpy

# 2. Install Node.js dependencies (snarkjs)
cd circuits
npm install
cd ..
```

### Prepare input video

The video must be encoded as H.264 baseline with CAVLC (not CABAC). Use ffmpeg:

```bash
ffmpeg -i input.y4m -c:v libx264 -profile:v baseline -coder 0 -qp 10 -g 8 -y output.h264
```

The `-g` value controls the GOP size (IDR frame interval). A smaller value means more IDR frames and more embedding capacity. The test video uses `-g 8`.

### Run end-to-end test

```bash
python e2e_groth16_test.py
```

Expected output (abbreviated):
```
PHASE 1: GROTH16 ZK-SNARK PROOF GENERATION
  Proof size   : 256 bytes  (Groth16 BN128)
  Proof sanity : VALID

PHASE 2: PARSING BITSTREAM & EMBEDDING ACROSS ALL IDR FRAMES
  Safe embedding positions : 2340  (292 bytes capacity)
  Payload size             : 274 bytes  (2192 bits)
  Embedded 2192/2192 bits into 1120 blocks

PHASE 3: RECONSTRUCTING STEGO VIDEO
  Stego video : data/output/stego_groth16.h264

PHASE 4: EXTRACTING BLOB FROM STEGO VIDEO
  Extracted blob : 274 bytes

PHASE 5: INTEGRITY CHECK & ZK PROOF VERIFICATION
  [OK] Blob is bit-perfect
  [OK] Message matches original
  [OK] Groth16 proof VALID

  [SUCCESS] End-to-end ZK-SNARK steganography verified!
```

### Run test suite

```bash
python src/runtest/run_all.py
```

```
  [+] Phase 1   ZK Proof                7/7 passed
  [+] Phase 2   H264 Parser             8/8 passed
  [+] Phase 3   Safety + Embed          8/8 passed
  [+] Phase 4   Reconstruct             5/5 passed
  [+] Phase 5   Extract + Verify        4/4 passed
  TOTAL: 32/32 passed
  [SUCCESS] All test phases passed.
```

---

## Technical Details

### Embedding capacity

Capacity depends on the video: number of IDR frames, macroblock count, and coefficient magnitudes.

For `foreman_cif_g8.h264` (352x288 CIF, GOP=8, 7 IDR frames):
- ~330 safe positions per IDR frame (1 bit per position)
- ~2300+ bits total across 7 IDR frames
- Sufficient for 274-byte Groth16 blob (2192 bits)

### Safety filter rules

`CAVLCSafetyFilter.get_safe_positions()` enforces 5 rules per coefficient:

| Rule | What it checks |
|------|----------------|
| Zero-preservation | Never 0->nonzero or nonzero->0 (breaks TotalCoeffs) |
| Trailing-ones protection | Last <=3 consecutive +-1 get sign-bit slots, not LSB slots |
| Bit-length invariance | CAVLC re-encode of modified block must match NAL bit length exactly |
| Magnitude threshold | `|coeff| >= 3` (LSB flip on 2->3 changes encoding length) |
| Non-patchable exclusion | Blocks rejected by `BitstreamPatcher.get_unpatchable_blocks()` |

Sign-bit positions (`~coeff_idx < 0`): flip the sign of trailing +-1 coefficients. These are 1-bit invariant when truly encoded as trailing-one sign bits, verified via the same `_verify_block_bit_length_invariance()` check.

### Bit-exact patching

`BitstreamPatcher` replaces full CAVLC re-encoding with targeted bit patches:
1. Parse original block at known bit offset
2. Re-encode the modified block
3. If new encoding == old length, patch those bytes in-place
4. Blocks where lengths differ (or tracer couldn't parse) are excluded by nal_length_map=-1

This keeps the output video byte-size nearly identical to the input.

### Extraction without tracer

After reconstruction, extraction uses `extract_bits_direct()` which bypasses the CAVLC tracer entirely:
- Uses the original bit-offsets from `frame_verified_data` (valid because patcher is length-preserving)
- Decodes each block at its known offset using the verified nC
- Reads LSB or sign from the correct coefficient index

This avoids parse errors caused by patched bytes confusing the sequential tracer state machine.

### Multi-IDR embedding

All IDR frames are embedded into using a shared global macroblock counter. Blocks from each IDR frame are appended in order to form a single flat embedding space. The extractor reproduces the same ordering to guarantee bit-perfect round-trip.

---

## Requirements

### Software

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.8+ | Main runtime |
| Node.js | 14+ | snarkjs witness generation |
| npm | 6+ | Package manager for snarkjs |
| ffmpeg | any | Video encoding (optional, for preparing test videos) |

### Python packages

```bash
pip install numpy
```

### Node.js packages

```bash
cd circuits && npm install
```

The `circuits/node_modules/` directory (~65 MB) contains snarkjs and circomlib.

### Rebuilding circuit keys (optional)

The pre-built proving key (`circuits/build/proving_key.zkey`) is included. To rebuild from scratch:

```bash
cd circuits

# 1. Compile circuit (requires circom binary)
circom payload_verify.circom --r1cs --wasm --sym -o build/

# 2. Powers of tau ceremony
npx snarkjs powersoftau new bn128 17 build/pot17_0000.ptau -v
npx snarkjs powersoftau contribute build/pot17_0000.ptau build/pot17_0001.ptau --name="contribution" -v
npx snarkjs powersoftau prepare phase2 build/pot17_0001.ptau build/pot17_final.ptau -v

# 3. Groth16 setup
npx snarkjs groth16 setup build/payload_verify.r1cs build/pot17_final.ptau build/circuit_0000.zkey
npx snarkjs zkey contribute build/circuit_0000.zkey build/proving_key.zkey --name="contribution" -v
npx snarkjs zkey export verificationkey build/proving_key.zkey build/verification_key.json
```

---

## Troubleshooting

### `node not found` / `snarkjs not found`

Phases 1 and 5 (ZK proof generation/verification) require Node.js. Install from https://nodejs.org, then run `npm install` in the `circuits/` directory. Tests that need Node.js will SKIP automatically if not available.

### `Not enough safe embedding positions`

The input video does not have enough IDR frames or large enough coefficients. Re-encode with:
- Lower QP (`-qp 10` instead of higher values) — produces larger coefficients
- Smaller GOP (`-g 8` or `-g 4`) — produces more IDR frames

### UnicodeEncodeError on Windows

Force UTF-8 output:
```bash
set PYTHONIOENCODING=utf-8
python e2e_groth16_test.py
```

---

## Version History

### upgrade-v3 (current — March 2026)

- Migrated source layout from `src/zk_mv_stego/` to flat `src/`
- Added `BitstreamPatcher` for bit-exact patching (no full CAVLC re-encoding)
- Added `TraceableCAVLCParser` for block offset tracking
- Extended safety filter: sign-bit positions for trailing +-1 coefficients with bit-length verification
- Multi-IDR frame embedding spanning all IDR frames in video
- T1-override support for bit-exact reproduction of edge-case blocks
- Added `src/runtest/` per-phase test suite: 32/32 pass
- Fixed `verify()` substring bug (`"valid" in "invalid"`)
- Fixed `_extract_with_safety_filter` sign-bit position handling

### v3.1-CAVLC-Safety (February 2026)

- CAVLC Safety Filter: 5-rule system (zero-preservation, trailing-ones, bit-length, magnitude, re-encoding)
- Full Groth16 ZK-SNARK integration (snarkjs + circom)
- 100% bit-perfect round-trip verified
- NAL P-frame bypassing: embed only in IDR frames, copy P/B frames unchanged
