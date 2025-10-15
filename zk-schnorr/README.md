# ZK-Schnorr Implementation for Steganography

## 📋 Overview

This directory contains the implementation of **ZK-Schnorr protocol** for steganographic applications, providing an alternative to the existing ZK-SNARK implementation.

### Purpose

Compare two zero-knowledge proof systems for steganography:
1. **ZK-SNARK** (existing) - Based on Groth16, requires trusted setup
2. **ZK-Schnorr** (new) - Based on discrete logarithm problem, no trusted setup

---

## 🏗️ Directory Structure

```
zk-schnorr/
├── src/
│   ├── zk_schnorr_protocol.py      # Core Schnorr protocol implementation
│   └── hybrid_schnorr_stego.py     # Hybrid steganography with Schnorr proofs
├── tests/
│   └── (unit tests)
├── benchmarks/
│   └── (performance benchmarks)
└── README.md                        # This file

comparative_benchmarks/
├── compare_protocols.py             # ZK-SNARK vs ZK-Schnorr comparison
└── comparison_results/
    ├── figures/
    │   └── snark_vs_schnorr_comparison.png
    └── data/
        └── comparison_results_*.json
```

---

## 🔬 ZK-Schnorr Protocol

### Key Features

✅ **Simpler cryptography** - Based on discrete logarithm problem  
✅ **No trusted setup** - Can be initialized immediately  
✅ **Faster proof generation** - ~0.1-5 ms (vs 100+ ms for SNARK)  
✅ **Smaller proof size** - 96 bytes fixed (vs 743+ bytes for SNARK)  
✅ **Lower memory footprint** - Minimal computational requirements  

### Security

- **Security level**: 256-bit discrete logarithm problem
- **Protocol**: Schnorr identification + Fiat-Shamir transform
- **Non-interactive**: Using hash-based challenge generation
- **Soundness**: Computationally secure under DLP assumption

### Protocol Steps

1. **Setup**: Generate key pair (x, Y) where Y = x·G
2. **Commitment**: Choose random r, compute R = r·G
3. **Challenge**: c = H(R || message || Y)
4. **Response**: s = r + c·x (mod order)
5. **Verification**: Check s·G = R + c·Y

---

## 🚀 Usage

### 1. Basic ZK-Schnorr Protocol

```python
from zk_schnorr_protocol import ZKSchnorrProtocol

# Initialize protocol
schnorr = ZKSchnorrProtocol(security_bits=256)

# Generate keypair
private_key, public_key = schnorr.generate_keypair()

# Generate proof
message = "Secret message"
proof, gen_time = schnorr.generate_proof(message)

# Verify proof
is_valid, verify_time = schnorr.verify_proof(proof, message)

print(f"Proof valid: {is_valid}")
print(f"Generation: {gen_time*1000:.3f} ms")
print(f"Verification: {verify_time*1000:.3f} ms")
print(f"Proof size: {proof.proof_size_bytes} bytes")
```

### 2. Hybrid Steganography

```python
from hybrid_schnorr_stego import HybridSchnorrSteganography
from PIL import Image

# Load cover image
cover_image = Image.open("cover.png")

# Initialize system
hybrid_system = HybridSchnorrSteganography(cover_image)

# Embed message with proof
message = "Hidden secret message"
stego_image, proof, stats = hybrid_system.embed_with_proof(
    message, 
    embedding_key="my_key"
)

# Save stego image
stego_image.save("stego.png")

# Extract and verify
extracted_msg, proof_valid, verify_stats = hybrid_system.extract_and_verify(
    stego_image,
    proof,
    len(message),
    embedding_key="my_key"
)

print(f"Message: {extracted_msg}")
print(f"Proof valid: {proof_valid}")
```

### 3. Run Demo

```bash
cd zk-schnorr/src

# Test Schnorr protocol
python zk_schnorr_protocol.py

# Test hybrid steganography
python hybrid_schnorr_stego.py
```

---

## 📊 Comparative Benchmarks

### Run Comparison

```bash
cd comparative_benchmarks
python compare_protocols.py
```

This will:
1. Test both ZK-SNARK and ZK-Schnorr with multiple message sizes
2. Generate comparison plots (9 panels)
3. Save raw data in JSON format

### View Results

```bash
xdg-open comparison_results/figures/snark_vs_schnorr_comparison.png
```

---

## 📈 Performance Comparison

### Expected Results (1024×1024 image, 200 char message)

| Metric | ZK-Schnorr | ZK-SNARK | Winner |
|--------|------------|----------|--------|
| **Proof Generation** | ~0.5-3 ms | ~100-500 ms | ✓ Schnorr (100-200x faster) |
| **Proof Verification** | ~0.5-2 ms | ~50-200 ms | ✓ Schnorr (50-100x faster) |
| **Proof Size** | 96 bytes | 743-1000 bytes | ✓ Schnorr (7-10x smaller) |
| **Setup Required** | No | Yes (trusted) | ✓ Schnorr |
| **Memory Usage** | Low (~1 MB) | High (~100+ MB) | ✓ Schnorr |
| **Embedding Speed** | ~7 ms | ~7 ms | ≈ Equal |
| **Image Quality** | ~84 dB PSNR | ~84 dB PSNR | ≈ Equal |
| **Security Level** | 256-bit DLP | Groth16 | ≈ Equal |

**Key Advantages of Schnorr**:
- ✅ **100x faster** proof generation
- ✅ **10x smaller** proof size
- ✅ **No trusted setup** required
- ✅ **Simpler** implementation

**When to use SNARK**:
- Need for succinct proofs in very specific scenarios
- Already have trusted setup infrastructure
- Require specific circuit optimizations

---

## 🔍 Technical Details

### Proof Structure

**ZK-Schnorr Proof (96 bytes)**:
```
Commitment (R):  32 bytes  (256-bit group element)
Challenge (c):   32 bytes  (256-bit hash output)
Response (s):    32 bytes  (256-bit scalar)
Total:           96 bytes  (fixed size)
```

**ZK-SNARK Proof (743+ bytes)**:
```
Base proof:      743 bytes  (Groth16 proof)
Message overhead: ~2 bytes/char (varies with message)
Metadata:        variable
Total:           743-2000+ bytes (grows with message)
```

### Cryptographic Primitives

**ZK-Schnorr**:
- Group: Large prime order subgroup
- Hash: SHA-256 for Fiat-Shamir
- Operations: Modular exponentiation
- Complexity: O(log n) for generation/verification

**ZK-SNARK**:
- Curve: BN254 (Barreto-Naehrig)
- Hash: MiMC or Poseidon (circuit-friendly)
- Operations: Elliptic curve pairings
- Complexity: O(n) for generation, O(1) for verification

---

## 🧪 Testing

### Unit Tests

```bash
cd zk-schnorr/tests
pytest test_schnorr_protocol.py
pytest test_hybrid_schnorr.py
```

### Benchmarks

```bash
cd zk-schnorr/benchmarks
python benchmark_schnorr.py
```

---

## 📊 Comparison Visualizations

The comparative benchmark generates 9 plots:

**A-C**: Performance Metrics
- A. Proof Generation Time
- B. Proof Verification Time  
- C. Proof Size

**D-F**: Efficiency Analysis
- D. Total Processing Time
- E. Image Quality (PSNR)
- F. Schnorr Speedup Factor

**G-I**: Summary
- G. Proof Size Ratio
- H. Average Metrics Bar Chart
- I. Summary Comparison Table

---

## 🎯 Use Cases

### When to Use ZK-Schnorr

✅ **Real-time applications** - Low latency requirements  
✅ **Resource-constrained devices** - IoT, mobile, embedded  
✅ **High-throughput systems** - Processing many messages/second  
✅ **Simple deployment** - No trusted setup infrastructure  
✅ **Transparent setup** - No need for ceremony  

### When to Use ZK-SNARK

✅ **Blockchain applications** - On-chain verification  
✅ **Complex circuits** - Advanced computation proofs  
✅ **Existing infrastructure** - Already have trusted setup  
✅ **Specific optimizations** - Circuit-level customization  

---

## 📚 References

### ZK-Schnorr
- C.P. Schnorr (1991): "Efficient Signature Generation by Smart Cards"
- Fiat-Shamir Transform: "How to Prove Yourself" (1986)

### ZK-SNARK
- Groth16: "On the Size of Pairing-based Non-interactive Arguments" (2016)
- Pinocchio Protocol: "Pinocchio: Nearly Practical Verifiable Computation" (2013)

### Security Analysis
- Discrete Logarithm Problem (DLP) hardness
- Random Oracle Model for Fiat-Shamir
- Computational soundness proofs

---

## 🛠️ Development

### Add New Features

1. **Custom group parameters**:
   - Edit `zk_schnorr_protocol.py`
   - Modify `_get_safe_prime()` method
   - Use standardized curves (secp256k1, etc.)

2. **Optimize performance**:
   - Use fast exponentiation libraries
   - Implement batch verification
   - Parallelize proof generation

3. **Extend security**:
   - Add multi-signature support
   - Implement threshold schemes
   - Add proof aggregation

### Dependencies

```bash
pip install numpy pillow
```

Optional (for benchmarks):
```bash
pip install matplotlib scipy
```

---

## ✅ Checklist

Implementation complete:
- [x] Core ZK-Schnorr protocol
- [x] Key generation
- [x] Proof generation (Fiat-Shamir)
- [x] Proof verification
- [x] Hybrid steganography system
- [x] Comparative benchmark suite
- [x] Performance analysis
- [x] Visualization tools
- [x] Documentation

---

## 🎉 Quick Start

```bash
# 1. Test Schnorr protocol
cd zk-schnorr/src
python zk_schnorr_protocol.py

# 2. Test hybrid steganography
python hybrid_schnorr_stego.py

# 3. Run comparison benchmark
cd ../../comparative_benchmarks
python compare_protocols.py

# 4. View results
xdg-open comparison_results/figures/snark_vs_schnorr_comparison.png
```

---

## � Additional Documentation

### Understanding DLP-256

- **DLP256_SIMPLE.md** - 🔰 **Giải thích đơn giản cho người mới** (recommended!)
  - Ví dụ cụ thể với số nhỏ
  - So sánh với AES-256
  - Tại sao an toàn?
  - Khi nào dùng?

- **DLP256_EXPLAINED.md** - 🔬 **Chi tiết kỹ thuật đầy đủ**
  - Mathematical foundation
  - Security proofs
  - Implementation details
  - Quantum vulnerability
  - Use cases & limitations

### Comparative Analysis

- **../comparative_benchmarks/QUICK_SUMMARY.md** - So sánh nhanh Schnorr vs SNARK
- **../comparative_benchmarks/COMPARISON_REPORT.md** - Báo cáo chi tiết 20+ trang
- **../ZK_SCHNORR_SUMMARY.md** - Tóm tắt implementation

---

## 📞 Support

For questions or issues:
1. **Basic understanding**: Read `DLP256_SIMPLE.md` first
2. **Technical details**: Check `DLP256_EXPLAINED.md`
3. **Performance**: See comparative benchmark results
4. **Implementation**: Review protocol code
5. **Debugging**: Run unit tests

---

*ZK-Schnorr Implementation v1.0*  
*October 2025*  
*Part of ZK-Steganography Research Project*
