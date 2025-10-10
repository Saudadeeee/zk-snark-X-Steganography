# ZK-SNARK Steganography: Correct Understanding

A project demonstrating how to use steganography as a **transport mechanism** for ZK-SNARK proofs.

## 🎯 **Correct Concept**

**ZK-SNARK logic remains unchanged** - we only change **how the proof is transmitted**.

### Traditional ZK workflow:
```
Prover → proof.json → [send file] → Verifier → verify(proof.json)
```

### Our steganographic ZK workflow:
```
Prover → proof.json → [embed in image] → stego.png → [send image] → Verifier → [extract proof] → verify(proof.json)
```

**Key insight**: Steganography is just a **transport layer**, not a cryptographic modification.

## � **Implementation**

### **PROOF Mode** - ZK-SNARK proof embedding
```bash
# 1. Generate normal ZK-proof
snarkjs groth16 prove circuit.zkey witness.wtns proof.json public.json

# 2. Embed proof into image
python3 src/zk_stego/embed_proof.py cover.png stego.png proof.json [key]

# 3. Send stego.png instead of proof.json

# 4. Extract proof from image
python3 src/zk_stego/extract_proof.py stego.png proof_extracted.json [key]

# 5. Verify as normal
snarkjs groth16 verify verification_key.json public.json proof_extracted.json
```

### **Traditional steganography** (for ZK circuit input generation)
```bash
# Generate circuit input using traditional embedding
python3 src/core/embed_message.py cover.png temp_stego.png "1010110011010101" "10110011"
python3 src/core/extract_slots.py temp_stego.png "1010110011010101" "10110011" > input.json
```

## 🚀 **Quick Demo**

Run the complete ZK-SNARK steganography workflow:
```bash
./scripts/demo/demo_zk_stego.sh
```

This demonstrates:
1. **Generate ZK-proof** (normal snarkjs workflow)
2. **Embed proof in image** (steganography as transport)
3. **Extract proof from image** 
4. **Verify proof** (normal snarkjs verification)

## 📋 **Why This Approach Works**

### ✅ **Advantages:**
- **Non-interactive preserved**: ZK-SNARK remains non-interactive
- **Security unchanged**: Cryptographic properties maintained  
- **Stealth transmission**: Proof hidden in innocent-looking image
- **Standard verification**: Normal snarkjs verification process
- **Transport flexibility**: Can use any steganography method

### 🔬 **Technical Details:**
- **Proof serialization**: JSON → Base64 → Binary bits
- **Steganographic embedding**: Chaos-based position generation for LSB embedding
- **Proof reconstruction**: Binary bits → Base64 → JSON → Verification
- **Error handling**: Auto-detection of proof length, integrity checking

## 🎯 **Use Cases**

1. **Covert ZK verification**: Send proof hidden in social media images
2. **Censorship resistance**: Proof transmission in restricted networks  
3. **Plausible deniability**: Image looks like normal photo
4. **Bandwidth efficiency**: Single file contains both image and proof
5. **Supply chain verification**: Embed authenticity proofs in product images

## 📁 **File Structure**

```
src/
├── core/                      # Traditional steganography (for ZK circuit)
│   ├── embed_message.py       # Generate test embeddings for circuit input
│   └── extract_slots.py       # Extract LSB values for ZK circuit
└── zk_stego/                  # ZK-SNARK proof steganography (main innovation)
    ├── embed_proof.py         # Embed ZK-proof into image
    └── extract_proof.py       # Extract ZK-proof from image

circuits/source/
└── stego_check_v2.circom      # ZK circuit (standard, unchanged)

scripts/
├── demo/demo_zk_stego.sh      # Complete ZK+steganography demo
└── build/verifier.sh          # Extract proof from image → verify

docs/
└── WORKFLOW_COMPLETE.md       # Detailed technical workflow
```

## 🧪 **Testing**

```bash
# Complete workflow demo
./scripts/demo/demo_zk_stego.sh

# Test individual components
python3 src/zk_stego/embed_proof.py examples/testvectors/cover_16x16.png temp/stego.png temp/proof.json
python3 src/zk_stego/extract_proof.py temp/stego.png temp/extracted.json

# Verify extraction worked
diff temp/proof.json temp/extracted.json
```

## 💡 **Key Innovation**

This project demonstrates that **steganography and ZK-SNARKs are complementary**:

- **ZK-SNARKs**: Provide cryptographic proof without revealing secrets
- **Steganography**: Provides covert communication channel

Combined: **Covert cryptographic verification** - prove statements secretly without revealing the proof mechanism itself.

---

*The mathematics of ZK-SNARKs remains unchanged; we've simply made proof transmission covert through steganographic channels.*

### Legacy: PRF-based (still supported)
```
Secret + Message → Positions → LSB Embedding → Stego Image
                                    ↓
Circuit Input ← Extract All LSBs ← Stego Image
      ↓
ZK Proof ← Generate Witness ← Circuit Input
      ↓
Verification (Public: slots + message, Private: secret)
```

## 📋 Prerequisites

Install required dependencies:

```bash
# Node.js and circom tools
npm install -g circom snarkjs

# Python and Pillow for image processing
pip3 install pillow

# Ensure you have the following commands available:
# - circom (circuit compiler)
# - snarkjs (proof system)
# - node (JavaScript runtime)
# - python3 (Python interpreter)
```

## 🚀 Quick Start

### 1. Clone and Setup

```bash
cd /path/to/zk-snarkXsteganography
chmod +x *.sh *.py
```

### 2. Run Chaos-based Demo (New!)

```bash
python3 scripts/demo/demo_chaos.py
```

This runs a comprehensive demo showing:
- Chaos-based embedding and extraction
- Position determinism verification  
- Key sensitivity analysis
- Collision rate assessment
- Comparison with legacy approach

### 3. Quick Chaos Example

```bash
# Embed using chaos-based positions
python3 src/chaos/embed_message_chaos.py examples/testvectors/cover_16x16.png stego.png deadbeefcafe 10110011

# Extract using same key  
python3 src/chaos/extract_message_chaos.py stego.png --key deadbeefcafe --length 8

# Generate circuit input for ZK-proof
python3 src/chaos/extract_message_chaos.py stego.png --key deadbeefcafe --message 10110011 --circuit > input.json
```

### 4. Legacy Compatibility

```bash
# Original PRF-based approach (still works)
./demo.sh

# Or manually:
python3 embed_message.py testvectors/cover_16x16.png stego.png 1010110011010101 10110011
python3 extract_slots.py stego.png 1010110011010101 10110011 > input.json
```

## 📖 Detailed Workflow

### 🌀 NEW: Chaos-based Approach

#### Phase 1: Feature Extraction & Seed Derivation
```bash
# Extract image features (histogram, moments, entropy)
features = extract_features(cover_image)

# Combine with shared key using HMAC-SHA256  
seeds = derive_chaos_seeds(features, shared_key)
```

#### Phase 2: Chaotic Position Generation
```bash
# Initialize chaotic maps with derived seeds
logistic_map = LogisticMap(r=4.0, x0=seeds.logistic_seed)
arnold_map = ArnoldCatMap(N=image_size, p=seeds.arnold_param)

# Generate hybrid chaotic sequence
positions = generate_chaotic_positions(logistic_map, arnold_map, message_length)
```

#### Phase 3: Embedding & Extraction
```bash
# Embed message bits at chaotic positions
embed_bits_at_positions(cover_image, positions, message_bits) → stego_image

# Extract by regenerating same positions
positions = regenerate_positions(stego_image, shared_key, message_length)
message = extract_bits_from_positions(stego_image, positions)
```

#### Phase 4: ZK-Proof Generation
```bash
# Generate circuit input with image features as private inputs
circuit_input = {
    "slots": extract_all_lsb_slots(stego_image),      # Public
    "message": message_bits,                          # Public  
    "features": quantized_image_features,             # Private
    "key_hash": hash(shared_key)                      # Private
}

# Prove knowledge of features & key that generate correct positions
proof = generate_zk_proof(circuit_input)
```

### 🔢 Legacy: PRF-based Approach (Compatible)

#### Embedding
```bash
# Simple linear position calculation from secret
secret_int = binary_to_int(secret_bits)
positions = [(secret_int + i) % total_slots for i in range(message_length)]

# Embed message  
embed_message.py cover.png stego.png SECRET_BITS MESSAGE_BITS
```

#### Circuit Input Generation
```bash
# Extract all LSBs + include secret as private input
extract_slots.py stego.png SECRET_BITS MESSAGE_BITS > input.json
```

### 🔄 Circuit Compilation & Proving (Both Approaches)
```bash
# Compile appropriate circuit
circom circuits/source/stego_chaos.circom --r1cs --wasm --sym -o build   # Chaos
# OR
circom circuits/source/stego_check_v2.circom --r1cs --wasm --sym -o build # Legacy

# Trusted setup (one-time)
snarkjs groth16 setup build/*.r1cs pot12_final.ptau build/circuit.zkey
snarkjs zkey export verificationkey build/circuit.zkey verification_key.json

# Generate proof
snarkjs groth16 prove build/circuit.zkey witness.wtns proof.json public.json

# Verify proof  
snarkjs groth16 verify verification_key.json public.json proof.json
```

## 🧪 Test Vectors

### Test Case 1: Basic Functionality
- **Cover**: `testvectors/cover_16x16.png` (768 slots)
- **Secret**: `1010110011010101` (binary) = 44501 (decimal)
- **Message**: `10110011` (binary) = 179 (decimal)
- **Expected positions**: [44501%768, (44501+1)%768, ..., (44501+7)%768]

### Test Case 2: Larger Image
- **Cover**: `testvectors/cover_32x32.png` (3072 slots)
- **Secret**: `1111000011110000` (binary) = 61680 (decimal)  
- **Message**: `01010101` (binary) = 85 (decimal)

## 📁 File Structure

```
├── README.md                       # This file (updated for chaos upgrade)
├── docs/
│   ├── CHAOS_UPGRADE.md           # 🆕 Detailed chaos implementation guide
│   ├── PROJECT_SUMMARY.md         # Project overview
│   └── LOGGING_SUMMARY.md         # Logging documentation
├── src/
│   ├── chaos/                      # 🆕 Chaos-based steganography
│   │   ├── __init__.py            # Module exports
│   │   ├── feature_extractor.py   # Image feature extraction
│   │   ├── chaos_generator.py     # Logistic + Arnold maps
│   │   ├── position_generator.py  # Main position orchestrator
│   │   ├── embed_chaos.py         # Chaos-based embedder
│   │   ├── extract_chaos.py       # Chaos-based extractor
│   │   ├── embed_message_chaos.py # CLI embedding tool
│   │   └── extract_message_chaos.py # CLI extraction tool
│   ├── core/                      # Legacy components (still functional)
│   │   ├── embed_message.py       # Original embedding
│   │   └── extract_slots.py       # Original extraction
│   └── utils/
│       └── generate_input.py      # Input formatting utilities
├── circuits/
│   ├── source/
│   │   ├── stego_chaos.circom     # 🆕 Chaos-based circuit
│   │   └── stego_check_v2.circom  # Legacy circuit (working)
│   └── compiled/                  # Compiled circuit artifacts
├── scripts/
│   ├── demo/
│   │   ├── demo_chaos.py          # 🆕 Comprehensive chaos demo
│   │   └── demo.sh                # Legacy demo script
│   ├── build/
│   │   ├── prover.sh              # Circuit compilation + proving
│   │   └── verifier.sh            # Proof verification
│   └── test/
│       └── run_with_logs.sh       # Testing with logs
├── examples/
│   ├── testvectors/               # Test images
│   │   ├── cover_16x16.png       # Small test image
│   │   └── cover_32x32.png       # Medium test image
│   ├── basic/                     # Basic usage examples
│   └── advanced/                  # Advanced usage patterns
├── artifacts/
│   ├── keys/                      # Cryptographic keys
│   │   ├── pot12_final.ptau      # Powers of tau
│   │   └── verification_key.json # ZK verification key
│   ├── proofs/                    # Generated proofs
│   └── images/                    # Generated stego images
├── temp/                          # Temporary files
├── tests/
│   ├── unit/                      # Unit tests
│   ├── integration/
│   │   └── test_poc.py           # Integration tests
│   └── performance/
│       ├── test_overhead_analysis.py  # Performance analysis
│       └── test_scale_analysis.py     # Scalability tests
└── config/                        # Configuration files
```

## 🔬 Circuit Parameters

### Chaos-based Circuit (`stego_chaos.circom`)
- **N_SLOTS**: 256 (maximum LSB positions to consider)
- **MSG_LEN**: 8 (message length in bits)
- **FEATURES**: 8 (quantized image features)
- **Key inputs**: Feature vector + key hash (private)
- **Position generation**: In-circuit chaos computation

### Legacy Circuit (`stego_check_v2.circom`)  
- **N_SLOTS**: 256 (maximum LSB positions to consider)
- **MSG_LEN**: 8 (message length in bits)
- **SECRET_LEN**: 16 (secret length in bits)
- **Key inputs**: Secret bits (private)
- **Position generation**: Simple linear calculation

Both circuits can be modified for different requirements by updating the parameters.

## ⚠️ Implementation Notes

### 🌀 Chaos-based Advantages:
✅ **Enhanced Security**: Image-dependent positions, non-sequential patterns  
✅ **Key Sensitivity**: Exponential sensitivity to key changes  
✅ **Collision Resistance**: Built-in collision detection and mitigation  
✅ **Deterministic**: Reproducible across platforms and runs  
✅ **Scalable**: Supports larger images and longer messages  

### 🔢 Legacy Compatibility:
✅ **Backward Compatible**: Original PRF approach still fully supported  
✅ **Performance**: Faster for simple use cases  
✅ **Simplicity**: Easier to understand and debug  
✅ **Circuit Size**: Smaller constraint systems  

### 🚧 Chaos Limitations (Current):
⚠️ **Circuit Complexity**: Chaos circuits require more constraints  
⚠️ **Numerical Precision**: Floating-point operations need careful handling  
⚠️ **Parameter Tuning**: Optimal chaos parameters depend on image properties  
⚠️ **Memory Overhead**: Additional state for chaotic maps (~1KB)  

### 🎯 Production Requirements:
1. **Robust Feature Extraction**: Handle edge cases (uniform images, noise)
2. **Numerical Stability**: Fixed-point arithmetic for cross-platform consistency  
3. **Circuit Optimization**: Reduce constraint count for chaos operations
4. **Error Correction**: ECC integration for real-world robustness
5. **Key Management**: Proper key derivation and secure storage
6. **Comprehensive Testing**: Stress testing with diverse image types

## 🐛 Troubleshooting

### Circuit Compilation Errors:
```bash
# If circom fails, check:
circom --version  # Should be 2.0.0+
node --version    # Should be 14+
```

### Trusted Setup Issues:
```bash
# If powers of tau download fails:
wget https://hermez.s3-eu-west-1.amazonaws.com/powersOfTau28_hez_final_12.ptau -O pot12_final.ptau

# Verify file size (about 288MB)
ls -lh pot12_final.ptau
```

### Proof Generation Failures:
```bash
# Check input.json format:
jq . input.json

# Verify array lengths:
# - slots: 256 elements
# - message: 8 elements  
# - secret: 16 elements
```

### Verification Failures:
- Ensure all files exist: `verification_key.json`, `proof.json`, `public.json`
- Check that public.json matches the actual public inputs
- Verify proof.json is not corrupted

## 🎉 Success Criteria

### 🌀 Chaos-based Implementation:
✅ **Position Determinism**: Same image + key → identical positions  
✅ **Key Sensitivity**: 1-bit key change → 100% different positions  
✅ **Message Integrity**: Embedding → extraction → perfect recovery  
✅ **Collision Handling**: <10% collision rate for practical message sizes  
✅ **Feature Stability**: Robust features across identical image content  
✅ **Cross-platform**: Consistent results across different systems  

### 🔢 Legacy Compatibility:  
✅ **Backward Compatible**: All original functionality preserved  
✅ **Performance**: Legacy mode faster for simple use cases  
✅ **Circuit Verification**: Original circuit still compiles and works  

### 🔧 ZK-SNARK Integration:
✅ **Circuit Design**: Both chaos and legacy circuits compile successfully  
✅ **Witness Generation**: Input.json produces valid witness  
✅ **Proof Generation**: Witness produces valid proof  
✅ **Verification**: Proof verifies with public inputs  
✅ **Tamper Detection**: Modified stego fails verification  

### 📊 Demo Validation:
```
🎉 OVERALL RESULT: SUCCESS - All tests passed!
✅ Chaos Embedding: PASS
✅ Position Determinism: PASS  
✅ Robustness Tests: PASS
✅ Key Sensitivity: PASS (100% position change)
✅ Low Collisions: PASS (<10% collision rate)
```  

## 🚀 Next Steps for Production

### 🌀 Chaos Enhancement Roadmap:
1. **Advanced Feature Extraction**: SIFT/SURF keypoints, DCT coefficients, robust descriptors
2. **Multi-scale Chaos**: Hierarchical position generation for different image scales  
3. **Adaptive Parameters**: Dynamic chaos parameter selection based on image properties
4. **Compression Robustness**: Features stable under JPEG/PNG compression
5. **Quantum Resistance**: Analysis of chaos behavior under quantum computing attacks

### 🔧 Circuit Optimization:
1. **Constraint Reduction**: Optimize chaos computations for fewer constraints
2. **Fixed-point Arithmetic**: Replace floating-point with deterministic fixed-point
3. **Parallel Verification**: Batch verification of multiple proofs
4. **Universal Setup**: Migrate to PLONK for better scalability
5. **Hardware Acceleration**: GPU/FPGA optimization for proof generation

### 🛡️ Security Hardening:
1. **Formal Security Analysis**: Provable security under chosen-plaintext attacks
2. **Side-channel Resistance**: Constant-time implementations  
3. **Key Management**: Integration with HSM/KMS systems
4. **Audit Trail**: Blockchain anchoring for provenance and timestamping
5. **Error Correction**: Reed-Solomon integration for robustness

### 📈 Performance & Scale:
1. **Memory Optimization**: Reduce memory footprint for large images
2. **Streaming Processing**: Support for video and large files
3. **Distributed Computing**: Cloud-based proof generation
4. **Caching Strategies**: Feature and position caching for repeated operations
5. **Mobile Integration**: Lightweight implementations for mobile devices

## 📝 License

This is a Proof of Concept for educational purposes. Not suitable for production use without significant security hardening.