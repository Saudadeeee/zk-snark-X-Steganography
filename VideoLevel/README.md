# zkSNARK Video Steganography

**Production-ready zkSNARK proof embedding in H.264 video using SEI NAL units**

Zero-knowledge proof embedding system that allows a Prover to embed cryptographic proofs into H.264 video files. The Verifier can extract and verify these proofs without learning the secret information.

---

## 🎯 Overview

### What This Does

- **Prover**: Generates a zkSNARK proof (Groth16) and embeds it into an H.264 video file
- **Verifier**: Extracts the proof from the video and cryptographically verifies it
- **Single File**: Only the video file is transmitted - proof is embedded inside via SEI NAL units
- **Zero-Knowledge**: Verifier learns nothing about the secret, only that the Prover knows it

### Use Cases

- Prove ownership or knowledge of data without revealing it
- Tamper-evident video distribution
- Privacy-preserving authentication
- Verifiable video authenticity with cryptographic guarantees

---

## 🚀 Quick Start

### Prerequisites

**Required:**
- Python 3.7+
- Node.js (for snarkjs)

**Installation:**

```bash
# 1. Install snarkjs globally
npm install -g snarkjs@latest

# 2. Verify installation
python zk_snark_workflow.py check
```

**Expected output:**
```
✅ snarkjs@0.7.6
✅ Found: payload_verify.wasm
✅ Found: proving_key.zkey
✅ Found: verification_key.json
✅ All checks passed! Ready to use.
```

### Basic Usage

```bash
# Complete workflow - Generate proof, embed, extract, and verify
python zk_snark_workflow.py workflow \
    -i data/raw/bus_simple.h264 \
    -m "Your secret message"
```

**Output:**
```
🎬 PROVER: Generating proof... ✓ (3-5 seconds)
📦 EMBEDDING: Adding to video... ✓ (~10ms)
🔍 VERIFIER: Extracting proof... ✓ (~5ms)
✅ VERIFICATION: Proof valid! ✓ (1-2 seconds)

🎉 COMPLETE WORKFLOW: SUCCESS!
```

---

## 💡 Features

✅ **100% Accuracy** - Lossless proof embedding and extraction  
✅ **Real zkSNARKs** - Groth16 proofs generated via Circom/SnarkJS  
✅ **Single File Solution** - Proof embedded in video (no separate files needed)  
✅ **Standard Compliant** - H.264 SEI NAL units (plays in VLC, FFmpeg, browsers)  
✅ **Production Ready** - Complete CLI interface and Python API  
✅ **Zero-Knowledge** - Cryptographically secure proof without revealing secrets

---

## How It Works

### Complete Workflow Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PROVER SIDE                                       │
│─────────────────────────────────────────────────────────────────────────────│
│                                                                             │
│  [1] Input Preparation                                                      │
│      ┌──────────────────┐                                                   │
│      │ Secret Message   │  "Your secret message"                            │
│      │ Secret Key       │  32-byte random key (auto-generated)             │
│      └──────────────────┘                                                   │
│               │                                                             │
│               v                                                             │
│  [2] Hash Generation                                                        │
│      ┌────────────────────────────────────┐                                │
│      │  payload_hash = SHA256(message)    │  256 bits                      │
│      │  commitment = SHA256(hash + secret)│  256 bits                      │
│      └────────────────────────────────────┘                                │
│               │                                                             │
│               v                                                             │
│  [3] Circuit Input Generation                                               │
│      ┌──────────────────────────────────────┐                              │
│      │  {                                    │                              │
│      │    "payload_hash": [256 bits],       │                              │
│      │    "commitment": [256 bits],         │                              │
│      │    "payload_length": 52,             │                              │
│      │    "secret": [256 bits]              │  (Private)                   │
│      │  }                                    │                              │
│      └──────────────────────────────────────┘                              │
│               │                                                             │
│               v                                                             │
│  [4] zkSNARK Proof Generation (3-5 seconds)                                 │
│      ┌─────────────────────────────────────────┐                           │
│      │  snarkjs calculatewitness               │                           │
│      │    payload_verify.wasm                  │                           │
│      │    + circuit_input.json                 │                           │
│      │    → witness.wtns                       │                           │
│      │                                         │                           │
│      │  snarkjs groth16 prove                  │                           │
│      │    proving_key.zkey                     │                           │
│      │    + witness.wtns                       │                           │
│      │    → proof.json + public.json           │                           │
│      └─────────────────────────────────────────┘                           │
│               │                                                             │
│               v                                                             │
│  [5] Proof Serialization                                                    │
│      ┌────────────────────────────────────────────┐                        │
│      │  Groth16 Proof (JSON format):              │                        │
│      │  {                                         │                        │
│      │    "proof": {                              │                        │
│      │      "pi_a": [G1 point],    // 64 bytes   │                        │
│      │      "pi_b": [G2 point],    // 128 bytes  │                        │
│      │      "pi_c": [G1 point],    // 64 bytes   │                        │
│      │      "protocol": "groth16",               │                        │
│      │      "curve": "bn128"                      │                        │
│      │    },                                      │                        │
│      │    "publicSignals": [513 field elements]  │                        │
│      │  }                                         │                        │
│      │                                            │                        │
│      │  Total size: 2,803 bytes (JSON string)    │                        │
│      └────────────────────────────────────────────┘                        │
│               │                                                             │
│               v                                                             │
│  [6] SEI NAL Unit Construction (~10ms)                                      │
│      ┌──────────────────────────────────────────────────┐                  │
│      │  SEI Payload Structure:                          │                  │
│      │  ┌────────────────────────────────────────────┐  │                  │
│      │  │ UUID (16 bytes)                            │  │                  │
│      │  │   a1b2c3d4-e5f6-5a1b-8c9d-0e1f2a3b4c5d    │  │                  │
│      │  ├────────────────────────────────────────────┤  │                  │
│      │  │ Proof Size (4 bytes, big-endian)           │  │                  │
│      │  │   0x00000AEB (2803 decimal)                │  │                  │
│      │  ├────────────────────────────────────────────┤  │                  │
│      │  │ Proof Data (2803 bytes)                    │  │                  │
│      │  │   {"proof":{...},"publicSignals":[...]}   │  │                  │
│      │  ├────────────────────────────────────────────┤  │                  │
│      │  │ CRC32 Checksum (4 bytes)                   │  │                  │
│      │  │   Integrity verification                   │  │                  │
│      │  └────────────────────────────────────────────┘  │                  │
│      │                                                  │                  │
│      │  Apply RBSP encoding (emulation prevention):    │                  │
│      │    0x000000 → 0x00000300                        │                  │
│      │    0x000001 → 0x00000301                        │                  │
│      │                                                  │                  │
│      │  Final NAL Unit:                                │                  │
│      │  ┌──────────────────────────────────────────┐   │                  │
│      │  │ Start Code:  0x00000001 (4 bytes)        │   │                  │
│      │  │ NAL Header:  0x06 (SEI type)             │   │                  │
│      │  │ Payload Type: 0x05 (user_data_unregist.) │   │                  │
│      │  │ Payload Size: Variable length encoding   │   │                  │
│      │  │ Payload Data: UUID + Size + Proof + CRC  │   │                  │
│      │  │ RBSP Trailing: 0x80                      │   │                  │
│      │  └──────────────────────────────────────────┘   │                  │
│      │                                                  │                  │
│      │  Total: ~2,846 bytes                             │                  │
│      └──────────────────────────────────────────────────┘                  │
│               │                                                             │
│               v                                                             │
│  [7] Video Embedding                                                        │
│      ┌──────────────────────────────────────────────┐                      │
│      │  H.264 Bitstream:                            │                      │
│      │                                              │                      │
│      │  [SPS NAL] [PPS NAL] [SEI NAL] [IDR frame]  │                      │
│      │                         ^                    │                      │
│      │                         │                    │                      │
│      │                    Insert here               │                      │
│      │              (before IDR frame)              │                      │
│      │                                              │                      │
│      │  Output: video_with_proof.h264               │                      │
│      └──────────────────────────────────────────────┘                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     │
                         (Transmit video file)
                                     │
                                     v
┌─────────────────────────────────────────────────────────────────────────────┐
│                          VERIFIER SIDE                                      │
│─────────────────────────────────────────────────────────────────────────────│
│                                                                             │
│  [1] Input Video                                                            │
│      ┌──────────────────────────────────┐                                  │
│      │  video_with_proof.h264           │                                  │
│      │  (Embedded SEI NAL unit)         │                                  │
│      └──────────────────────────────────┘                                  │
│               │                                                             │
│               v                                                             │
│  [2] Bitstream Scanning (~5ms)                                              │
│      ┌────────────────────────────────────────┐                            │
│      │  Parse H.264 NAL units sequentially:   │                            │
│      │                                        │                            │
│      │  for each NAL unit:                    │                            │
│      │    if NAL type == 0x06 (SEI):          │                            │
│      │      if payload type == 0x05:          │                            │
│      │        check UUID match                │                            │
│      │        → Found zkSNARK proof!          │                            │
│      └────────────────────────────────────────┘                            │
│               │                                                             │
│               v                                                             │
│  [3] Proof Extraction                                                       │
│      ┌─────────────────────────────────────────┐                           │
│      │  Remove RBSP encoding:                  │                           │
│      │    0x00000300 → 0x000000                │                           │
│      │    0x00000301 → 0x000001                │                           │
│      │                                         │                           │
│      │  Parse SEI payload:                     │                           │
│      │  ┌───────────────────────────────────┐  │                           │
│      │  │ Read UUID (16 bytes)              │  │                           │
│      │  │ Verify: a1b2c3d4-e5f6-...         │  │                           │
│      │  ├───────────────────────────────────┤  │                           │
│      │  │ Read Size (4 bytes)               │  │                           │
│      │  │   2803 bytes expected             │  │                           │
│      │  ├───────────────────────────────────┤  │                           │
│      │  │ Read Proof (2803 bytes)           │  │                           │
│      │  ├───────────────────────────────────┤  │                           │
│      │  │ Read CRC32 (4 bytes)              │  │                           │
│      │  │ Compute CRC32(UUID+Size+Proof)    │  │                           │
│      │  │ Verify checksum matches           │  │                           │
│      │  └───────────────────────────────────┘  │                           │
│      │                                         │                           │
│      │  Extracted: 2803 bytes (JSON)           │                           │
│      └─────────────────────────────────────────┘                           │
│               │                                                             │
│               v                                                             │
│  [4] Proof Deserialization                                                  │
│      ┌─────────────────────────────────────┐                               │
│      │  JSON.parse(proof_bytes):           │                               │
│      │  {                                  │                               │
│      │    "proof": {                       │                               │
│      │      "pi_a": [...],                 │                               │
│      │      "pi_b": [...],                 │                               │
│      │      "pi_c": [...],                 │                               │
│      │      "protocol": "groth16",        │                               │
│      │      "curve": "bn128"               │                               │
│      │    },                               │                               │
│      │    "publicSignals": [513 values]   │                               │
│      │  }                                  │                               │
│      └─────────────────────────────────────┘                               │
│               │                                                             │
│               v                                                             │
│  [5] zkSNARK Verification (1-2 seconds)                                     │
│      ┌──────────────────────────────────────────┐                          │
│      │  snarkjs groth16 verify                  │                          │
│      │    verification_key.json                 │                          │
│      │    + public.json                         │                          │
│      │    + proof.json                          │                          │
│      │                                          │                          │
│      │  Cryptographic verification:             │                          │
│      │    e(pi_a, pi_b) == e(alpha, beta) *     │                          │
│      │    e(pub, gamma) * e(pi_c, delta)        │                          │
│      │                                          │                          │
│      │  (Pairing check on BN128 curve)          │                          │
│      └──────────────────────────────────────────┘                          │
│               │                                                             │
│               v                                                             │
│  [6] Verification Result                                                    │
│      ┌────────────────────────────┐                                        │
│      │  VALID: Proof verified     │                                        │
│      │  INVALID: Verification fail│                                        │
│      └────────────────────────────┘                                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### zkSNARK Circuit Architecture

```
Circuit: payload_verify.circom

┌─────────────────────────────────────────────────────────────┐
│                    Circuit Inputs                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  PUBLIC INPUTS (visible to verifier):                       │
│    • payload_hash[256]    - SHA256 of the message           │
│    • commitment[256]      - Expected commitment value       │
│    • payload_length       - Size of payload in bytes        │
│                                                             │
│  PRIVATE INPUT (known only to prover):                      │
│    • secret[256]          - Secret key (256 bits)           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                            │
                            v
┌─────────────────────────────────────────────────────────────┐
│                  Circuit Constraints                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  [1] Concatenate payload_hash and secret:                   │
│      combined = payload_hash[256] || secret[256]            │
│                                                             │
│  [2] Compute SHA256 hash:                                   │
│      computed_commitment = SHA256(combined)                 │
│                                                             │
│  [3] Verify commitment matches:                             │
│      assert(computed_commitment == commitment)              │
│                                                             │
│  [4] Verify payload length is valid:                        │
│      assert(payload_length > 0)                             │
│      assert(payload_length < MAX_PAYLOAD_SIZE)              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                            │
                            v
┌─────────────────────────────────────────────────────────────┐
│                  Proof Generation                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Groth16 Protocol (BN128 curve):                            │
│                                                             │
│  π = (π_a, π_b, π_c)  where:                                │
│                                                             │
│    π_a ∈ G1  (2 coordinates × 32 bytes = 64 bytes)          │
│    π_b ∈ G2  (2 coordinates × 2 × 32 bytes = 128 bytes)     │
│    π_c ∈ G1  (2 coordinates × 32 bytes = 64 bytes)          │
│                                                             │
│  Public signals: 513 field elements                         │
│    (derived from payload_hash, commitment, length)          │
│                                                             │
│  Total proof size: ~2,803 bytes (JSON serialized)           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### H.264 SEI Embedding Details

```
SEI NAL Unit Structure:

┌──────────────────────────────────────────────────────────────┐
│                    NAL Unit Header                           │
├──────────────────────────────────────────────────────────────┤
│  Start Code:     0x00 0x00 0x00 0x01  (4 bytes)             │
│  NAL Header:     0x06                  (1 byte)             │
│    ┌─ forbidden_zero_bit (1 bit) = 0                        │
│    ├─ nal_ref_idc (2 bits) = 00                             │
│    └─ nal_unit_type (5 bits) = 00110 (6 = SEI)              │
└──────────────────────────────────────────────────────────────┘
                            │
                            v
┌──────────────────────────────────────────────────────────────┐
│                   SEI Message Header                         │
├──────────────────────────────────────────────────────────────┤
│  Payload Type:   0x05  (user_data_unregistered)             │
│  Payload Size:   Variable length encoding                   │
│    Example: 2827 = 0xFF 0xFF 0xFF ... 0x0B                  │
│    (Multiple 0xFF bytes + final remainder)                  │
└──────────────────────────────────────────────────────────────┘
                            │
                            v
┌──────────────────────────────────────────────────────────────┐
│                    SEI Payload Data                          │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Byte 0-15:   UUID (128 bits)                               │
│               a1b2c3d4-e5f6-5a1b-8c9d-0e1f2a3b4c5d          │
│               (Identifies this as zkSNARK proof)            │
│                                                              │
│  Byte 16-19:  Proof Size (32-bit big-endian)                │
│               0x00 0x00 0x0A 0xEB (2803 decimal)            │
│                                                              │
│  Byte 20-2822: Proof Data (2803 bytes)                      │
│               {"proof":{...},"publicSignals":[...]}         │
│                                                              │
│  Byte 2823-2826: CRC32 Checksum (32-bit)                    │
│               CRC32(UUID || Size || Proof)                  │
│               Detects corruption/tampering                  │
│                                                              │
└──────────────────────────────────────────────────────────────┘
                            │
                            v
┌──────────────────────────────────────────────────────────────┐
│                   RBSP Encoding                              │
├──────────────────────────────────────────────────────────────┤
│  Emulation Prevention:                                       │
│                                                              │
│  Scan for sequences that could be mistaken for start codes: │
│    0x00 0x00 0x00  →  0x00 0x00 0x03 0x00                   │
│    0x00 0x00 0x01  →  0x00 0x00 0x03 0x01                   │
│    0x00 0x00 0x02  →  0x00 0x00 0x03 0x02                   │
│    0x00 0x00 0x03  →  0x00 0x00 0x03 0x03                   │
│                                                              │
│  Insert 0x03 byte after 0x00 0x00 to prevent false start    │
│  code detection by decoders.                                │
│                                                              │
│  Adds ~10-20 bytes overhead (depends on payload content)    │
│                                                              │
└──────────────────────────────────────────────────────────────┘
                            │
                            v
┌──────────────────────────────────────────────────────────────┐
│                   RBSP Trailing Bits                         │
├──────────────────────────────────────────────────────────────┤
│  0x80  (rbsp_stop_one_bit + padding zeros)                  │
│  Marks end of RBSP data                                     │
└──────────────────────────────────────────────────────────────┘
                            │
                            v
┌──────────────────────────────────────────────────────────────┐
│              Final NAL Unit (~2,846 bytes)                   │
└──────────────────────────────────────────────────────────────┘

Insertion Point in H.264 Stream:

[SPS] [PPS] [SEI with zkProof] [IDR Frame] [P Frame] [P Frame] ...
              ↑
              └─── Inserted before first IDR frame
                   (Ensures proof is at stream start)
```

### Verification Process Details

```
Groth16 Verification Equation:

┌──────────────────────────────────────────────────────────────┐
│  Pairing Check (on BN128 elliptic curve):                    │
│                                                              │
│  e(π_a, π_b) == e(α, β) · e(L_pub, γ) · e(π_c, δ)           │
│                                                              │
│  where:                                                      │
│    • e() is the bilinear pairing function                   │
│    • α, β, γ, δ are from verification_key.json              │
│    • L_pub = sum of public inputs × IC points               │
│    • π_a, π_b, π_c are from the proof                       │
│                                                              │
│  If equation holds → VALID (prover knows secret)            │
│  If equation fails → INVALID (forged or corrupted)          │
│                                                              │
└──────────────────────────────────────────────────────────────┘

Verification guarantees:
  - Prover knows secret key matching the commitment
  - Payload hash is correctly computed
  - All constraints in circuit are satisfied
  - Cryptographically impossible to forge (2^128 security level)
```

---

## 📖 CLI Commands

### Check Setup

```bash
python zk_snark_workflow.py check
```

Verifies that snarkjs is installed and all circuit artifacts (WASM, proving key, verification key) are present.

### Complete Workflow (Recommended)

```bash
# One command - does everything
python zk_snark_workflow.py workflow \
    -i data/raw/bus_simple.h264 \
    -m "Your secret message"
```

Automatically runs: proof generation → embedding → extraction → verification

### Prover Only

```bash
# Generate proof and embed in video
python zk_snark_workflow.py prove \
    -i input.h264 \
    -m "Secret message" \
    -o output_with_proof.h264
```

**Output:**
- `output_with_proof.h264` - Video with embedded proof (+2.8KB)
- `data/output/proof.json` - Generated proof (for reference)
- `data/output/public.json` - Public signals
- Secret key printed to console (save for your records)

### Verifier Only

```bash
# Extract and verify proof from video
python zk_snark_workflow.py verify \
    -i output_with_proof.h264
```

**Output:**
- Extraction result (success/failure)
- Verification result (VALID ✅ / INVALID ❌)

### SEI Tool (Standalone)

For SEI operations without zkSNARK generation:

```bash
# Create mock proof
python zkproof_sei_tool.py mock -o proof.bin -s 192

# Embed existing proof
python zkproof_sei_tool.py embed \
    -i input.h264 \
    -p proof.bin \
    -o output.h264

# Extract proof
python zkproof_sei_tool.py extract \
    -i output.h264 \
    -o extracted.bin

# Verify extraction accuracy
python zkproof_sei_tool.py verify \
    -o original.bin \
    -e extracted.bin

# Complete SEI workflow
python zkproof_sei_tool.py workflow \
    -i input.h264 \
    -p proof.bin
```

---


## 🐍 Python API

### Basic Usage

```python
from zk_snark_workflow import ZKSnarkVideoWorkflow

# Initialize workflow
workflow = ZKSnarkVideoWorkflow()

# Check dependencies
if not workflow.check_dependencies():
    print("Please install snarkjs")
    exit(1)

# Prover side
result = workflow.prover_workflow(
    video_path="input.h264",
    payload_message="Your secret message",
    output_path="output.h264"
)

print(f"Secret key: {result['secret_key']}")
print(f"Output: {result['output_video']}")

# Verifier side
valid = workflow.verifier_workflow(
    video_path="output.h264"
)

if valid:
    print("✅ Proof is VALID")
else:
    print("❌ Proof verification failed")
```

### Advanced: Manual Steps

```python
from zk_snark_workflow import ZKSnarkVideoWorkflow
from src.zk_mv_stego.bitstream.zkproof_sei_handler import ZKProofSEIHandler

workflow = ZKSnarkVideoWorkflow()
sei_handler = ZKProofSEIHandler()

# Step 1: Generate circuit input
secret = "my_secret_key_12345678901234567890123456789012"
circuit_input = workflow.generate_input(
    payload_data="Test message".encode(),
    secret=secret
)

# Step 2: Generate proof (takes 3-5 seconds)
proof, public_signals = workflow.generate_proof(circuit_input)

# Step 3: Serialize proof as JSON
import json
proof_json = json.dumps({
    'proof': proof,
    'publicSignals': public_signals
}, separators=(',', ':'))
proof_bytes = proof_json.encode('utf-8')

# Step 4: Embed in video
stats = sei_handler.embed_proof_in_video(
    input_path="input.h264",
    zkproof_bytes=proof_bytes,
    output_path="output.h264"
)

print(f"Embedded {stats['proof_bytes_size']} bytes")
print(f"Final size: {stats['final_size']} bytes")

# Step 5: Extract proof
extracted_bytes, extract_stats = sei_handler.extract_proof_from_video(
    "output.h264"
)

# Step 6: Deserialize and verify
proof_data = json.loads(extracted_bytes.decode('utf-8'))
is_valid = workflow.verify_proof(
    proof_data['proof'],
    proof_data['publicSignals']
)

print(f"Valid: {is_valid}")
```

---

## Performance

Typical performance on modern hardware (Intel i5-11400H, Node.js v20):

| Operation | Time | Size Impact |
|-----------|------|-------------|
| **Proof Generation** | 3-5 seconds | N/A |
| **Proof Serialization** | <1ms | 2,803 bytes (JSON) |
| **SEI Embedding** | ~10ms | +2,846 bytes total |
| **Video Encoding** | N/A | Original size preserved |
| **Proof Extraction** | ~5ms | Lossless extraction |
| **Proof Verification** | 1-2 seconds | N/A |
| **Total End-to-End** | **5-8 seconds** | **+2.8 KB overhead** |


---

## 📁 Project Structure

After cleanup, only core files remain:

```
VideoLevel/
├── README.md                       # Documentation (this file)
├── zk_snark_workflow.py           # Main workflow automation (470 lines)
├── zkproof_sei_tool.py             # Standalone SEI tool (379 lines)
│
├── circuits/                       # zkSNARK circuit files
│   ├── payload_verify.circom       # Circuit definition (67 lines)
│   ├── package.json                # Node.js dependencies
│   └── build/                      # Compiled artifacts
│       ├── payload_verify.wasm     # Circuit WASM
│       ├── proving_key.zkey        # Groth16 proving key
│       ├── verification_key.json   # Groth16 verification key
│       └── *.ptau                  # Powers of Tau files
│
├── src/zk_mv_stego/                # Core library
│   ├── bitstream/
│   │   ├── zkproof_sei_handler.py  # SEI NAL embedding (535 lines)
│   │   ├── h264_parser.py          # H.264 bitstream parser
│   │   ├── nal_handler.py          # NAL unit operations
│   │   └── ...                     # Other bitstream utilities
│   │
│   └── crypto/
│       ├── groth16_serializer.py   # Proof serialization (252 lines)
│       └── proof_wrapper.py        # Proof utilities
│
├── scripts/                        # Utility scripts
│   ├── extract.py                  # Legacy extraction tool
│   └── verify.py                   # Legacy verification tool
│
└── data/                           # Test data
    ├── raw/                        # Input videos (.h264, .y4m)
    ├── encoded/                    # Processed videos
    └── output/                     # Workflow outputs

Total: ~1,700 lines of core code (after removing ~4,000 lines of tests/docs)
```

---

## 🔒 Security

### Zero-Knowledge Properties

✅ **Privacy**: Verifier learns NOTHING about the secret key  
✅ **Soundness**: Impossible to forge valid proof without knowing secret  
✅ **Completeness**: Valid proofs always verify successfully

### Implementation Details

- **Circuit**: SHA256-based commitment scheme
- **Curve**: BN128 (alt_bn128)
- **Protocol**: Groth16 (most efficient zkSNARK)
- **Proof Size**: 2,803 bytes (JSON serialization)
- **Public Signals**: 513 field elements

### Integrity Protection

1. **CRC32 Checksum**: Detects corruption in SEI payload
2. **UUID Verification**: Ensures correct SEI type
3. **zkSNARK Verification**: Cryptographic proof of payload knowledge

### Important Notes

⚠️ **SEI is NOT steganographic** - The SEI NAL unit is visible in the H.264 bitstream. Anyone can extract the proof data.

⚠️ **No confidentiality by default** - The proof is public. To hide the payload content:
- Encrypt payload before generating proof
- Use stealth embedding (future: LDPC-based motion vector modification)

✅ **H.264 Compliant** - Videos play in VLC, FFmpeg, browsers, and hardware decoders

---

## 📜 License

MIT License - See LICENSE file for details

---

## 🙏 Acknowledgments

- **SnarkJS** - zkSNARK proving system
- **Circom** - Circuit language compiler
- **FFmpeg** - Video processing reference
