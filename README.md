# ZK-SNARK × Steganography

**Prove that a secret message was embedded — without revealing the message, the key, or the embedding positions.**

This repository implements two orthogonal steganographic channels — one for raster images (PNG / DICOM) and one for compressed video (H.264 CAVLC) — unified by the same zero-knowledge proof layer. Both channels produce a *carrier* that is visually indistinguishable from the original and a *proof* that can be verified by any third party who holds only the public verification key.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Theoretical Background](#2-theoretical-background)
   - [Zero-Knowledge Proofs and Groth16](#21-zero-knowledge-proofs-and-groth16)
   - [Chaos-Based Steganography (Image)](#22-chaos-based-steganography-image)
   - [CAVLC Coefficient Embedding (Video)](#23-cavlc-coefficient-embedding-video)
   - [Poseidon Hash and BN128](#24-poseidon-hash-and-bn128)
3. [Architecture](#3-architecture)
4. [ImageLevel — PNG / DICOM Steganography](#4-imagelevel--png--dicom-steganography)
5. [VideoLevel — H.264 CAVLC Steganography](#5-videolevel--h264-cavlc-steganography)
6. [ZK Circuits](#6-zk-circuits)
7. [Security Analysis](#7-security-analysis)
8. [Benchmark Results](#8-benchmark-results)
9. [Installation](#9-installation)
10. [Usage](#10-usage)
11. [Project Structure](#11-project-structure)
12. [References](#12-references)

---

## 1. System Overview

```
                     ┌──────────────────────────────────┐
                     │       SECRET MESSAGE + KEY        │
                     └──────────┬───────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │    ZK PROOF LAYER     │
                    │  Groth16 / BN128      │
                    │  Circom + snarkjs     │
                    └───────┬───────┬───────┘
                            │       │
              ┌─────────────▼─┐   ┌─▼──────────────────┐
              │  IMAGE LEVEL  │   │    VIDEO LEVEL      │
              │  PNG / DICOM  │   │   H.264 CAVLC IDR   │
              │  Arnold Cat   │   │   Coefficient LSB   │
              │  Map + LSB    │   │   + T1 Sign Flip    │
              └───────┬───────┘   └────────┬────────────┘
                      │                    │
              ┌───────▼───────┐   ┌────────▼────────────┐
              │  Stego PNG /  │   │   Stego H.264       │
              │  DICOM file   │   │   bitstream         │
              └───────────────┘   └─────────────────────┘
```

Both subsystems share one design invariant:

> **The verifier learns nothing about the secret message beyond the fact that it exists and is correctly formed.**

The ZK proof is embedded *inside the same carrier file* as the message. An extractor with knowledge of the embedding key retrieves both, then verifies the proof without any interaction with the prover.

---

## 2. Theoretical Background

### 2.1 Zero-Knowledge Proofs and Groth16

A **zero-knowledge proof** (ZKP) is a two-party protocol between a *prover* P and a *verifier* V in which P convinces V that a statement is true without disclosing any witness. Formally, a ZKP for an NP relation R satisfies:

- **Completeness** — if (x, w) ∈ R, an honest P always convinces V.
- **Soundness** — if x ∉ L_R, a cheating P convinces V with negligible probability.
- **Zero-knowledge** — V's view is simulatable from x alone (no information about w leaks).

This project uses **Groth16** (Groth 2016), a succinct non-interactive argument of knowledge (SNARK) in the *common reference string* (CRS) model. Its proof consists of exactly three elliptic-curve group elements (π_A, π_B, π_C) on the BN128 pairing-friendly curve, giving a constant **192-byte** proof size regardless of circuit complexity. Verification reduces to two pairing equations:

```
e(π_A, π_B) = e(α, β) · e(Σ aᵢ·γᵢ, γ) · e(π_C, δ)
```

where α, β, γ, δ are CRS parameters from the trusted Powers-of-Tau ceremony, and aᵢ are the public signals.

**Circuit compilation flow (Circom → Groth16):**

```
.circom source
    │
    ▼  circom --r1cs --wasm --sym
R1CS constraints  +  WASM witness generator
    │
    ▼  snarkjs groth16 setup  (uses Powers of Tau .ptau)
Proving key  (.zkey, 31 MB for VideoLevel)
    │
    ├──► snarkjs groth16 prove  →  proof.json  (at embed time)
    └──► snarkjs groth16 verify →  bool        (at verify time)
```

**R1CS (Rank-1 Constraint System):** Every gate in the circuit compiles to a linear constraint `(A·z) ∘ (B·z) = C·z` where z is the witness vector. The number of constraints determines the size of the proving and verifying keys.

| Circuit | Constraints | Powers-of-Tau | Proof size |
|---------|-------------|---------------|------------|
| `chaos_zk_stego.circom` (Image) | ~18,680 | pot16 | 192 B |
| `payload_verify.circom` (Video) | ~28,000 (SHA256 × 1) | pot17 | 192 B |

---

### 2.2 Chaos-Based Steganography (Image)

Classical LSB steganography places message bits at sequential pixel offsets, creating detectable statistical artifacts (the RS steganalysis test exploits this). This system replaces sequential placement with positions generated by two coupled chaotic systems.

#### Arnold Cat Map

The Arnold Cat Map (ACM) is an area-preserving, bijective transformation on the integer torus Z_N × Z_N:

```
[x_{n+1}]   [2  1] [x_n]
[y_{n+1}] = [1  1] [y_n]  (mod N)
```

The map has **period T(N)** (the sequence is eventually periodic); for N = 512 the period exceeds 300. Key properties relevant to steganography:

- **Ergodicity**: the orbit of almost every initial point is uniformly dense over Z_N × Z_N in the limit, so embedding positions are equidistributed over the image.
- **Sensitive dependence on initial conditions**: a 1-bit change in (x₀, y₀) produces a completely different orbit after ≥ 2 iterations.
- **Determinism**: given the same seed the orbit is exactly reproducible by both embedder and extractor.

In the ZK circuit (`SecureArnoldCatMap`), the standard affine recurrence is *perturbed* by a Poseidon-derived noise term at each step:

```
noise  = Poseidon(xₙ, yₙ, chaosKey + n) mod 256
xTemp  = 2·xₙ + yₙ + noise
yTemp  = xₙ + yₙ + noise
x_{n+1} = xTemp mod 1024   (lower 10 bits)
y_{n+1} = yTemp mod 1024   (lower 10 bits)
```

The noise term prevents an attacker who guesses the ACM parameters from predicting positions without also knowing the Poseidon preimage.

#### Logistic Map

The logistic map operates in the parameter regime r = 3.9 (deep chaos):

```
x_{n+1} = 3.9 · xₙ · (1 − xₙ),   x₀ ∈ (0, 1)
```

Lyapunov exponent λ ≈ ln(2r−1) > 0 confirms exponential divergence of nearby trajectories. The system generates a pseudo-random bit sequence for permuting the order of message bits before LSB embedding, providing an additional layer of diffusion beyond position selection.

#### Position Commitment (Merkle Tree)

The circuit commits to all 16 embedding positions via a depth-4 binary Merkle tree built entirely from Poseidon(2) hashes. The root is a compact cryptographic binding: changing any single position changes the root with overwhelming probability. The root is *not* published as a public signal (it is intermediate); what is published is the message commitment and nullifier.

---

### 2.3 CAVLC Coefficient Embedding (Video)

H.264 Baseline Profile mandates **CAVLC** (Context-Adaptive Variable-Length Coding) for residual DCT coefficients. This is the only entropy-coding mode that exposes coefficient values directly in the bitstream (CABAC is arithmetic and does not permit in-place modification of a single value without re-encoding the entire block). CAVLC therefore provides a natural, length-preserving steganographic channel.

#### CAVLC Structure

Each 4×4 luma or chroma DCT block is encoded as a sequence of five syntactic elements in the following order:

```
coeff_token          (total nonzero coefficients + trailing ones count)
trailing_ones_signs  (1 sign bit per T1, up to 3)
levels               (magnitudes of nonzero non-T1 coefficients, VLC)
total_zeros          (run of zeros before last nonzero, VLC)
run_before[]         (zeros before each nonzero, VLC)
```

This structure exposes two independent embedding channels:

**Channel A — Level LSB flip**

A non-T1 coefficient level *v* with |v| ≥ 3 can have its LSB flipped (v → v ⊕ 1) without changing:
- The zero/nonzero count (coeff_token is unchanged)
- The encoding length of the level VLC (because the levelCode mapping is monotone and the prefix length is determined by `levelCode >> suffixLength`)

The invariant is checked analytically via `EncodingLengthChecker.check_lsb_flip_patchability()`, which replicates the H.264 Section 9.2.2.1 VLC formula exactly.

**Channel B — Trailing-One Sign Flip**

Trailing ones (T1s) are the last ≤ 3 consecutive ±1 coefficients (in reverse scan order). Their signs are encoded as raw 1-bit flags in `trailing_ones_signs`, independent of the level VLC. Flipping one sign costs zero additional bits and does not affect `coeff_token`.

#### nC Computation and Block Parsing

The number of context neighbors `nC` for each block controls which `coeff_token` lookup table is used. A parsing error in nC produces cascading mis-decodings of all subsequent blocks. The system computes nC following x264's exact behavior:

- **Luma 4×4**: average of within-MB left and top neighbor `TotalCoeff` values; cross-MB neighbors are *not* used (they are not available without a full P-frame dependency chain).
- **Chroma DC** (1 block per channel): nC = −1 always (forces the 2×2 table).
- **Chroma AC**: average of within-MB luma `TotalCoeff` from the corresponding luma blocks.

Deviation from x264's nC choice causes bit-offset misalignment for all subsequent blocks.

#### Intra Prediction Cascade and Embedding Order

H.264 intra prediction means that each macroblock is the prediction reference for all spatially adjacent macroblocks decoded after it. Modifying early macroblocks therefore cascades errors through the entire frame. The system avoids this by embedding in **descending macroblock order** (last MB of last IDR frame first). Each modified block has no macroblocks *downstream* from it in the intra prediction graph, so the cascade length is zero.

Formally: let π : {0,…,M-1} → {0,…,M-1} be the embedding order. Define the intra error as:

```
E(π) = Σ_{i<j, π(i) < π(j)} RMSE(MB_{π(i)} → MB_{π(j)})
```

Ascending order maximizes E; descending order achieves E = 0.

#### Bit-Exact Patching

Traditional CAVLC steganography re-encodes the modified block from scratch and writes it back, which alters byte alignment for all subsequent bytes if the block encoding length changes. This system instead:

1. Parses the target block at its known bit offset (tracked by `TraceableCAVLCParser`).
2. Re-encodes the modified block to verify the encoding length is identical.
3. Patches only the affected bytes in-place using `BitstreamPatcher.patch_slice()`.

Because the patch is length-preserving, all downstream block offsets remain valid. The stego video is byte-identical to the original everywhere except the patched bytes, and its total size changes by at most ±2%.

#### FFmpeg PSNR Validation

Some T1 sign flips are structurally valid CAVLC (same bit length, no zero/nonzero changes) but trigger FFmpeg's intra prediction error handler at the pixel reconstruction level. These positions cannot be identified analytically from the CAVLC structure alone. The system runs an empirical validator per-position:

```python
validator, cleanup = rec.make_ffmpeg_position_validator(video, coefficients, fvd)
```

The validator creates a temporary patched video for each candidate position (containing only SPS + PPS + the single IDR NAL, no P-frames) and decodes it with FFmpeg. This reduces decode cost by ~50× compared to a full video. Positions that produce PSNR below threshold are skipped.

---

### 2.4 Poseidon Hash and BN128

Standard SHA-256 requires ~28,000 R1CS constraints per invocation (one 512-bit block). For the image circuit, where the message is committed inside the circuit, using SHA-256 for the inner commitment would multiply constraint count by 4–5×. **Poseidon** is a sponge construction designed for native field arithmetic over BN128's scalar field (prime p ≈ 2²⁵⁴):

- Each Poseidon round uses MDS matrix multiplication and SBOX `x → x⁵` — both cheap in R1CS (a single field multiplication = 1 constraint).
- Poseidon(2) over BN128 requires ~213 constraints, vs ~21,936 for SHA-256.
- Collision resistance: currently 2¹²⁸ for the Poseidon parameter sets used by circomlib.

The video circuit uses SHA-256 (not Poseidon) because the commitment must be compatible with standard tools that compute `SHA256(payload_hash ∥ secret)` off-circuit in Python and Node.js. The image circuit uses Poseidon exclusively, trading off external tool compatibility for dramatically lower constraint count.

---

## 3. Architecture

### Common ZK Layer

Both subsystems produce a **hybrid proof artifact**:

```
Artifact = { stego_carrier,  proof_package }

proof_package = {
    proof       : Groth16 π (192 bytes),
    public      : { payload_hash, commitment, [payload_length | nullifier] },
    message     : <plaintext, embedded in carrier>
}
```

The stego carrier *contains* the serialized proof_package (embedded as PNG chunk metadata or as a CAVLC-encoded blob in IDR frames). The verifier extracts both message and proof from the carrier and calls `snarkjs groth16 verify`.

### Separation of Concerns

```
┌──────────────────────────────────────────────────────────────┐
│                     SHARED COMPONENTS                        │
│  Groth16 (snarkjs)   BN128 curve   Poseidon hash   Circom    │
└──────────┬─────────────────────────────────┬─────────────────┘
           │                                 │
┌──────────▼──────────┐         ┌────────────▼────────────────┐
│     IMAGE LEVEL     │         │        VIDEO LEVEL          │
│                     │         │                             │
│  chaos_embedding.py │         │  h264.py  (parser)          │
│  Arnold Cat Map     │         │  cavlc.py (codec)           │
│  Logistic Map       │         │  embedder.py (safety filter)│
│  LSB pixel embed    │         │  bitstream_ops.py (patcher) │
│                     │         │                             │
│  Circuit:           │         │  Circuit:                   │
│  chaos_zk_stego     │         │  payload_verify             │
│  ~18,680 constr.    │         │  ~28,000 constr.            │
│  Poseidon commit    │         │  SHA256 commit              │
│  Nullifier system   │         │  Payload hash binding       │
└─────────────────────┘         └─────────────────────────────┘
```

---

## 4. ImageLevel — PNG / DICOM Steganography

### 4.1 Embedding Pipeline

```
Message + chaos_key
      │
      ▼
[1] Poseidon commitment
    commitment = Poseidon(Poseidon(msg[0:16]), Poseidon(msg[16:32]),
                          chaosKey, randomness)
      │
      ▼
[2] Nullifier generation
    nullifier = Poseidon(secret, nonce)
      │
      ▼
[3] Arnold Cat Map position generation (16 iterations, circuit-verified)
    (x₀, y₀) → ACM(chaosKey, iteration) → (x₁, y₁) → … → (x₁₆, y₁₆)
      │
      ▼
[4] Logistic Map bit permutation
    x_{n+1} = 3.9 · xₙ · (1 − xₙ),   seed = SHA256(message)
      │
      ▼
[5] LSB embedding at chaos positions
    pixel[y, x, ch] = (pixel[y, x, ch] & 0xFE) | message_bit
      │
      ▼
[6] Groth16 proof generation (snarkjs)
    witness = {messageBits, chaosKey, randomness, secret, nonce,
               x0, y0, positions[16][2], imageHashPrivate}
    public  = {publicCommitment, publicImageHash[8], publicNullifier}
      │
      ▼
[7] Proof embedded in PNG tEXt / iTXt chunk
    stego.png contains: modified pixels + proof JSON + public signals
```

### 4.2 DICOM Support

Medical DICOM images require special handling:
- DICOM pixel data is 16-bit per pixel (vs 8-bit for PNG). Standard chi-square and RS steganalysis are inapplicable at 16-bit depth.
- Embedding uses only the lower 8 bits of each 16-bit pixel word to avoid visible artifacts in windowed display.
- The DICOM header is preserved byte-for-byte; the proof is stored in a private DICOM tag.
- File conversion: DICOM (522 KB) → PNG carrier (112 KB, −78.5%) for public distribution.

### 4.3 ZK Circuit: `chaos_zk_stego.circom`

**Public signals** (known to verifier):
| Signal | Size | Meaning |
|--------|------|---------|
| `publicCommitment` | 1 field element | Poseidon(msg, chaosKey, randomness) |
| `publicImageHash[8]` | 8 × 254-bit | SHA-256 of cover image (split into 8 field elements) |
| `publicNullifier` | 1 field element | Poseidon(secret, nonce) — replay prevention |

**Private witness** (never leaves prover):
- `messageBits[32]` — 32 bits of message
- `chaosKey`, `randomness`, `secret`, `nonce` — key material
- `x0`, `y0` — initial ACM position
- `positions[16][2]` — 16 embedding positions
- `imageHashPrivate[8]` — image hash (verified equal to public)

**Constraint groups:**
1. Binary constraints on `messageBits[i]` (32 constraints)
2. `SecureMessageCommitment` — 3 Poseidon calls (≈ 640 constraints)
3. `Nullifier` — 1 Poseidon call (≈ 213 constraints)
4. `ImageHashVerification` — 8 equality checks (8 constraints)
5. `FullPositionVerification` — 16 × `SecureArnoldCatMap` calls (≈ 16,000 constraints)
6. `AllPositionsRangeProof` — 32 `LessThan(11)` checks (≈ 640 constraints)
7. `PositionMerkleTree` — depth-4 tree of Poseidon(2) (≈ 31 × 213 constraints)
8. Initial position bounds — 2 `LessThan(11)` (≈ 40 constraints)

**Total: ~18,680 constraints** → requires pot16 (2¹⁶ = 65,536 constraint capacity).

### 4.4 Performance (10 DICOM images, 512×512)

| Metric | Value |
|--------|-------|
| PSNR | 106.34 dB |
| SSIM | 1.0000 |
| Embedding rate | 0.0776 BPP |
| Embed time | 2.76 s |
| Extract time | 4.93 s |
| ZK proof gen | 1.23 s (chaos pos) + 2.64 s (LSB embed) |
| Peak RAM | 68.8 MB |
| Proof size (Groth16) | 192 B |
| Pot16 utilization | 28.5% |

**Steganalysis resistance:**
| Test | Cover | Sequential LSB | This Work |
|------|-------|----------------|-----------|
| RS Δ | 0.507 | 0.468 | **0.492** (most resistant) |
| SPA p̂ | 0.000584 | 0.000569 | **0.000400** (best) |
| Chi-square | p=0 | p=0 | p=0 (inapplicable to 16-bit DICOM) |

---

## 5. VideoLevel — H.264 CAVLC Steganography

### 5.1 Pipeline Overview

```
INPUT: cover.h264  +  message  +  secret_key
                              │
                 ┌────────────▼──────────────┐
                 │  Phase 1: ZK Proof Gen    │
                 │  SHA256(msg) → payload_hash│
                 │  SHA256(payload_hash ‖ key)│
                 │  → commitment             │
                 │  snarkjs groth16 prove    │
                 │  → proof (192 bytes)      │
                 └────────────┬──────────────┘
                              │  blob = len(4B) ‖ msg ‖ proof(192B)
                 ┌────────────▼──────────────┐
                 │  Phase 2: Bitstream Parse │
                 │  H264BitstreamParser      │
                 │  locate all IDR NALs      │
                 │  TraceableCAVLCParser     │
                 │  extract coefficients +   │
                 │  bit offsets per block    │
                 └────────────┬──────────────┘
                              │  coefficients, bit_offsets, nC_map
                 ┌────────────▼──────────────┐
                 │  Phase 3: Safety + Embed  │
                 │  CAVLCSafetyFilter        │
                 │  5-rule gate (see below)  │
                 │  PayloadEmbedder          │
                 │  descending MB order      │
                 │  LSB flip + T1 sign flip  │
                 └────────────┬──────────────┘
                              │  modified coefficients
                 ┌────────────▼──────────────┐
                 │  Phase 4: Reconstruct     │
                 │  BitstreamPatcher         │
                 │  patch bytes in-place     │
                 │  → stego.h264             │
                 └────────────┬──────────────┘
                              │
                 ┌────────────▼──────────────┐
                 │  Phase 5: Extract+Verify  │
                 │  extract_bits_direct()    │
                 │  (uses original offsets)  │
                 │  → recovered blob         │
                 │  snarkjs groth16 verify   │
                 │  → PASS / FAIL            │
                 └───────────────────────────┘
```

### 5.2 Safety Filter (5 Rules)

`CAVLCSafetyFilter.get_safe_positions()` admits a coefficient position only if **all five** rules pass:

| Rule | Condition | Reason |
|------|-----------|--------|
| **Zero-preservation** | `coeff ≠ 0` and `coeff ⊕ 1 ≠ 0` | Changing zero-count alters `coeff_token`, breaks downstream `total_zeros` and `run_before` parsing |
| **T1 protection** | `\|coeff\| ≠ 1` for Level channel | ±1 non-T1s would enter the trailing-ones region on re-encoding, changing `coeff_token` |
| **Bit-length invariance** | `len(VLC(coeff)) = len(VLC(coeff ⊕ 1))` | CAVLC level VLC is variable-length; a flip that changes prefix length shifts all subsequent byte offsets |
| **Magnitude threshold** | `\|coeff\| ≥ 3` | |v|=2 → |v⊕1|=3 crosses the suffix_length=0 boundary in the levelCode formula, always changing encoding length |
| **Non-patchable exclusion** | block not in `get_unpatchable_blocks()` | Blocks where `TraceableCAVLCParser` cannot verify the round-trip are excluded |

Sign-bit positions (trailing ones): encoded as raw 1-bit flags, so flipping is trivially length-preserving. These are verified separately via `_verify_block_bit_length_invariance()`.

### 5.3 Embedding Capacity

For `foreman_cif_g8.h264` (352×288 CIF, GOP=8, QP=10):

| Parameter | Value |
|-----------|-------|
| IDR frames | 7 |
| Macroblocks per IDR | 396 (22×18 CIF) |
| Safe T1 positions / IDR | ~1,205 |
| Total capacity | ~8,435 bits |
| Required for 274-byte blob | 2,192 bits |
| Capacity utilization | ~26% |

Capacity is inversely proportional to QP: at QP=10 many large coefficients dominate and |coeff| ≥ 3 positions are abundant; at QP=30 coefficients are mostly ±1 (T1 channel only).

### 5.4 ZK Circuit: `payload_verify.circom`

**Public signals:**
| Signal | Size | Meaning |
|--------|------|---------|
| `payload_hash[256]` | 256 bits | SHA-256(message ‖ proof blob) |
| `commitment[256]` | 256 bits | SHA-256(payload_hash ‖ secret_key) |
| `payload_length` | 32-bit scalar | Byte length of embedded blob |

**Private witness:**
- `secret[256]` — 256-bit secret key (never embedded in video)

**Constraint structure:**
```
SHA256(512-bit input) over BN128 R1CS
    payload_hash[256] ‖ secret[256]  →  computed[256]
    computed[i] === commitment[i]    (256 equality constraints)
    payload_length range check       (32 + 1 constraints)
```

Total: ~28,000 constraints (SHA-256 dominates at ≈27,904 for a single 512-bit block). Requires pot17 (2¹⁷ = 131,072 capacity).

### 5.5 Benchmark Results

All results use `max_greedy_per_idr=500` in the PSNR validator.

| Video | Positions | Frames modified | PSNR (modified) | PSNR (all) | SSIM |
|-------|-----------|-----------------|-----------------|------------|------|
| foreman_cif | 1,212 / 9,288 | 84% | **40.57 dB** | 43.67 dB | 0.97 |
| deadline_cif | 2,256 / 6,867 | 20% | 24.87 dB | 52.97 dB | 0.98 |
| coastguard_cif | — | 52% | 25.04 dB | 41.82 dB | 0.82 |

Note: PSNR(modified) measures the modified IDR frames only. Downstream P-frames inherit intra prediction errors from modified IDRs; foreman (low-motion) has the shortest error propagation path.

### 5.6 Test Suite

```
Phase 1  ZK Proof           7/7  pass
Phase 2  H264 Parser        8/8  pass
Phase 3  Safety + Embed     8/8  pass
Phase 4  Reconstruct        5/5  pass
Phase 5  Extract + Verify   4/4  pass
─────────────────────────────────────
TOTAL                      32/32 pass
```

---

## 6. ZK Circuits

### 6.1 Image Circuit (`ImageLevel/circuits/source/chaos_zk_stego.circom`)

```
SecureChaosZKStego
├── SecureMessageCommitment (Poseidon × 4)
│   ├── Poseidon(messageBits[0:16])
│   ├── Poseidon(messageBits[16:32])
│   ├── Poseidon(hash1, hash2)
│   └── Poseidon(combined, chaosKey, randomness) → publicCommitment
├── Nullifier (Poseidon × 1)
│   └── Poseidon(secret, nonce) → publicNullifier
├── ImageHashVerification (8 × IsEqual)
├── FullPositionVerification (16 × SecureArnoldCatMap)
│   └── SecureArnoldCatMap
│       ├── Poseidon(x, y, chaosKey+i) → hash
│       ├── Num2Bits(254) → lower 8 bits = noise
│       ├── xTemp = 2x + y + noise
│       ├── Num2Bits(12) → lower 10 bits = x mod 1024
│       └── (symmetric for y)
├── AllPositionsRangeProof (32 × LessThan(11))
└── PositionMerkleTree (31 × Poseidon(2), depth 4)
```

### 6.2 Video Circuit (`VideoLevel/circuits/payload_verify.circom`)

```
PayloadVerify
├── input_bits[512] = payload_hash[256] ‖ secret[256]
├── SHA256(512 bits) → computed_commitment[256]
├── commitment[i] === computed_commitment[i]   (256 constraints)
└── payload_length range check (Num2Bits(32))
```

---

## 7. Security Analysis

### 7.1 ZK Soundness

Groth16 provides knowledge soundness under the *q-Power Knowledge of Exponent* assumption over BN128. An adversary who produces a valid proof without knowing a valid witness breaks the knowledge assumption with negligible probability in the security parameter (currently 128-bit over BN128, equivalent to AES-128).

### 7.2 Steganographic Security

**Image channel:**
- Position space: ACM on 512×512 → 262,144 possible positions. The orbit of 16 positions is selected by (x₀, y₀, chaosKey). Exhaustive search requires testing 2²⁵⁶ (chaosKey is SHA-256 derived) × 512² initial positions.
- Channel capacity (CIF): determined by entropy of Poseidon(chaosKey, iteration), which is computationally indistinguishable from uniform.

**Video channel:**
- Embedding positions are determined by the CAVLC structure of the cover video (no additional key). The adversary who does not know the original video cannot distinguish stego from cover without a reference.
- T1 sign flips are undetectable by standard VLC histogram analysis because ±1 coefficient sign distributions are balanced in natural video.
- The ZK proof (embedded in the video as a CAVLC-encoded blob) appears to a blind observer as a sequence of CAVLC coefficient values drawn from the distribution of high-quality H.264 video.

### 7.3 Replay Prevention (Image)

The nullifier `Poseidon(secret, nonce)` is published as a public signal. A verifier maintains a spent-nullifier set. Reusing the same (secret, nonce) pair produces the same nullifier and is detected. Different (secret, nonce) pairs with the same message produce different commitments and different proofs.

### 7.4 Trusted Setup

Both circuits use the Groth16 CRS model. The setup is composed from a public Powers-of-Tau ceremony (.ptau file) followed by a circuit-specific contribution phase. The toxic waste (τ, α, β, γ, δ) must be destroyed after the ceremony. Pre-built keys are included; to run an independent ceremony, see [Section 9.3](#93-rebuilding-circuit-keys).

---

## 8. Benchmark Results

### Image Level (10 DICOM images, 512×512)

| Section | Result |
|---------|--------|
| §1 Quality | PSNR = 106.34 dB, SSIM = 1.0000, BPP = 0.0776 |
| §2 RS steganalysis | RS-Δ = 0.492 (cover=0.507, sequential=0.468) — best resistance |
| §2 SPA | p̂ = 0.000400 (cover=0.000584) — best result |
| §2 Chi-square | p=0 for all methods — metric inapplicable to 16-bit DICOM |
| §3 PSNR vs payload | +0.5 to +1.5 dB advantage at all rates |
| §4 ZK constraints | 18,680 constraints, 28.5% pot16 utilization |
| §5 Timing | 3.93 s total (chaos=1.23 s, embed=2.64 s), peak RAM 68.8 MB |
| §6 ECDSA comparison | sign=0.14 ms, verify=0.06 ms (70 B sig) vs 192 B ZK |

### Video Level (foreman_cif, GOP=8, QP=10, 50 frames)

| Metric | Value |
|--------|-------|
| Safe positions found | 1,212 of 9,288 total |
| Frames modified | 84% |
| PSNR (modified IDRs) | 40.57 dB |
| PSNR (all frames) | 43.67 dB |
| SSIM | 0.97 |
| Blob size | 274 bytes (14-byte msg + 192-byte Groth16 proof + 4-byte header + 64-byte public) |
| Bitstream size change | ±2% |
| Test suite | 32/32 pass |

---

## 9. Installation

### 9.1 Requirements

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.8+ | Main runtime |
| Node.js | 14+ | snarkjs witness generation + verification |
| npm | 6+ | Package manager |
| FFmpeg | any | Video encoding / PSNR validation |
| Pillow | latest | PNG / DICOM image I/O |
| numpy | latest | Array operations |

### 9.2 Setup

```bash
# Clone repository
git clone <repo-url>
cd zk-snark-X-Steganography

# ── Image Level ──────────────────────────────────
cd ImageLevel
pip install -r requirements.txt          # pillow, numpy, pydicom
npm install                              # snarkjs, circomlib (for circuit ops)

# ── Video Level ──────────────────────────────────
cd ../VideoLevel
pip install numpy
cd circuits && npm install && cd ..      # snarkjs, circomlib
```

Pre-built circuit keys are included:
- `ImageLevel/artifacts/keys/pot16_final.ptau`
- `VideoLevel/circuits/build/proving_key.zkey` (31 MB)
- `VideoLevel/circuits/build/verification_key.json`

### 9.3 Rebuilding Circuit Keys

**Image Level:**
```bash
cd ImageLevel/circuits/source
./../../bin/circom.exe chaos_zk_stego.circom --r1cs --wasm --sym -o ../compiled/build/
cd ../compiled/build
npx snarkjs groth16 setup chaos_zk_stego.r1cs ../../artifacts/keys/pot16_final.ptau circuit_0000.zkey
npx snarkjs zkey contribute circuit_0000.zkey chaos_zk_stego.zkey --name="contribution"
npx snarkjs zkey export verificationkey chaos_zk_stego.zkey chaos_zk_stego_verification_key.json
```

**Video Level:**
```bash
cd VideoLevel/circuits
circom payload_verify.circom --r1cs --wasm --sym -o build/
npx snarkjs powersoftau new bn128 17 build/pot17_0000.ptau
npx snarkjs powersoftau contribute build/pot17_0000.ptau build/pot17_0001.ptau --name="contribution"
npx snarkjs powersoftau prepare phase2 build/pot17_0001.ptau build/pot17_final.ptau
npx snarkjs groth16 setup build/payload_verify.r1cs build/pot17_final.ptau build/circuit_0000.zkey
npx snarkjs zkey contribute build/circuit_0000.zkey build/proving_key.zkey --name="contribution"
npx snarkjs zkey export verificationkey build/proving_key.zkey build/verification_key.json
```

### 9.4 Encoding a Test Video (Video Level)

```bash
# CIF (352×288), GOP=8, QP=10, CAVLC baseline (no CABAC)
ffmpeg -i input.y4m \
       -c:v libx264 -profile:v baseline -coder 0 \
       -qp 10 -g 8 -y output.h264
```

---

## 10. Usage

### 10.1 Image Level — Embedding

```python
from pathlib import Path
import sys
sys.path.insert(0, str(Path("ImageLevel/src")))

from zk_stego.hybrid_proof_artifact import HybridProofArtifact
from PIL import Image
import numpy as np

cover = np.array(Image.open("ImageLevel/examples/testvectors/dicom_test.png"))
hybrid = HybridProofArtifact()

stego_array, proof_package = hybrid.embed_with_proof(
    cover,
    message="Secret payload",
    chaos_key="my_secret_key_256bit"
)

Image.fromarray(stego_array).save("stego.png")
print(f"Proof size: {len(str(proof_package))} chars")
```

### 10.2 Image Level — Verification

```python
result = hybrid.verify_proof(proof_package)
print("VALID" if result else "INVALID")
```

```bash
# Command-line verification
python ImageLevel/verifier_package/scripts/verify.py stego.png
```

### 10.3 Video Level — End-to-End

```bash
cd VideoLevel

# Full pipeline (embed + verify)
python e2e_groth16_test.py

# Test suite
python src/runtest/run_all.py

# Benchmark
python benchmark/multi_quality_benchmark.py
```

**Expected e2e output:**
```
PHASE 1: GROTH16 ZK-SNARK PROOF GENERATION
  Proof size   : 192 bytes  (Groth16 BN128)

PHASE 2: PARSING BITSTREAM & EMBEDDING ACROSS ALL IDR FRAMES
  Safe embedding positions : 2340
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

### 10.4 DICOM Embedding

```bash
python ImageLevel/scripts/dicom_embed.py \
    --input  ImageLevel/examples/dicom/1-01.dcm \
    --output stego_dicom.png \
    --message "Patient ID: XYZ" \
    --key "chaos_key_here"

python ImageLevel/verifier_package/scripts/dicom_extract.py stego_dicom.png
```

---

## 11. Project Structure

```
zk-snark-X-Steganography/
│
├── README.md                          ← This file
│
├── ImageLevel/                        ← PNG / DICOM steganography
│   ├── src/zk_stego/
│   │   ├── prover.py                  ← Main embedding class
│   │   ├── chaos_embedding.py         ← ACM + Logistic Map
│   │   ├── zk_proof_generator.py      ← Groth16 wrapper
│   │   ├── hybrid_proof_artifact.py   ← High-level API
│   │   ├── poseidon.py                ← BN128-native hash (via Node.js)
│   │   ├── dicom_handler.py           ← DICOM I/O + 16-bit embedding
│   │   └── utils.py
│   ├── circuits/source/
│   │   └── chaos_zk_stego.circom      ← ~18,680 constraints (Poseidon)
│   ├── artifacts/keys/
│   │   └── pot16_final.ptau           ← Powers of Tau (capacity 2^16)
│   ├── verifier_package/              ← Standalone verifier (no prover code)
│   ├── Benchmark/                     ← 24-file benchmark suite (7 sections)
│   │   ├── run_all.py
│   │   ├── common.py                  ← Vectorized embed helpers
│   │   ├── Baseline/  Quality/  Steganalysis/
│   │   ├── Performance/  ZK/  Security/  SystemComparison/
│   └── examples/dicom/                ← 10 DICOM test files
│
└── VideoLevel/                        ← H.264 CAVLC steganography
    ├── src/
    │   ├── bitstream/
    │   │   ├── h264.py                ← H264BitstreamParser, TraceableCAVLCParser
    │   │   ├── cavlc.py               ← CAVLCDecoder, CAVLCEncoder
    │   │   ├── bitstream_ops.py       ← BitstreamPatcher, BitstreamReconstructor
    │   │   └── bitstream_io.py        ← Bit-level reader/writer
    │   ├── embedder/
    │   │   └── embedder.py            ← EncodingLengthChecker, CAVLCSafetyFilter, PayloadEmbedder
    │   ├── zk_snark_bridge.py         ← Python ↔ snarkjs bridge
    │   ├── zk_payload_format.py       ← pack() / unpack() blob serialization
    │   └── runtest/
    │       ├── run_all.py             ← 32/32 test orchestrator
    │       ├── _idr_extract.py        ← extract_all_idr_blocks, extract_bits_direct
    │       └── test_phase{1..5}_*.py
    ├── circuits/
    │   ├── payload_verify.circom      ← ~28,000 constraints (SHA-256)
    │   └── build/
    │       ├── proving_key.zkey       ← Groth16 proving key (31 MB)
    │       └── verification_key.json
    ├── data/
    │   ├── raw/                       ← Y4M source (foreman, akiyo, coastguard, deadline)
    │   └── encoded/                   ← H.264 test videos
    ├── benchmark/
    │   └── multi_quality_benchmark.py ← max_greedy_per_idr=500
    └── e2e_groth16_test.py
```

---

## 12. References

### Zero-Knowledge Proofs

- J. Groth. "On the Size of Pairing-based Non-interactive Arguments." *EUROCRYPT 2016*. LNCS 9666, pp. 305–326.
- E. Ben-Sasson et al. "Succinct Non-Interactive Zero Knowledge for a von Neumann Architecture." *USENIX Security 2014*.
- Circom language: https://docs.circom.io — constraint compilation from arithmetic circuits to R1CS.
- snarkjs: Groth16 prover/verifier in JavaScript/WASM.

### Cryptographic Primitives

- L. Grassi, D. Khovratovich, C. Rechberger, A. Roy, M. Schofnegger. "Poseidon: A New Hash Function for Zero-Knowledge Proof Systems." *USENIX Security 2021*.
- FIPS 180-4. "Secure Hash Standard (SHS)." NIST, 2015.
- BN128 pairing curve: Y. Nogami, M. Akane, Y. Sakemi, H. Kato, Y. Morikawa. "Integer Variable χ–Based Ate Pairing." *PAIRING 2008*.

### Chaos Theory and Steganography

- V.I. Arnold and A. Avez. *Ergodic Problems of Classical Mechanics*. Benjamin, 1968. (Arnold Cat Map)
- R.M. May. "Simple mathematical models with very complicated dynamics." *Nature* 261, 459–467, 1976. (Logistic Map)
- J. Fridrich. "Steganography in Digital Media: Principles, Algorithms, and Applications." Cambridge University Press, 2009.
- A. Westfeld and A. Pfitzmann. "Attacks on Steganographic Systems." *Information Hiding 1999*. LNCS 1768.

### Video and CAVLC

- ITU-T H.264 | ISO/IEC 14496-10. "Advanced Video Coding." 2003–2021. (Section 9.2: CAVLC)
- I. Richardson. "The H.264 Advanced Video Compression Standard." Wiley, 2010.
- x264 reference encoder: https://code.videolan.org/videolan/x264 (nC computation, CAVLC tables)

### DICOM

- NEMA PS3 / ISO 12052. "Digital Imaging and Communications in Medicine (DICOM) Standard." 2023.

---

*"Prove you embedded the message — without revealing the message, the key, or where it is."*
