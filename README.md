# ZK-SNARK Steganography System

A complete zero-knowledge proof-based steganography system that combines chaos-based image embedding with ZK-SNARK verification.

## 🏗️ System Architecture

```
ZK-SNARK Steganography System
├── 🔐 ZK Circuit Layer (chaos_zk_stego.circom)
│   ├── 32 constraints (optimized)
│   ├── Arnold Cat Map verification  
│   └── Groth16 proving system
├── ⚡ ZK Proof Layer (zk_proof_generator.py)
│   ├── Witness generation
│   ├── Trusted setup management
│   └── Proof generation/verification
└── 🖼️ Steganography Layer (hybrid_proof_artifact.py)
    ├── Chaos-based LSB embedding
    ├── PNG chunk metadata
    └── Feature-based positioning
```

## ✨ Features

- **Zero-Knowledge Proofs**: Prove steganographic embedding without revealing secrets
- **Chaos-Based Embedding**: Uses Arnold Cat Map for secure position generation
- **Hybrid Approach**: PNG chunks + LSB embedding for robustness
- **High Performance**: 2.3s proof generation, 0.5s verification
- **Compact Proofs**: 739 bytes proof size
- **100% Success Rate**: Reliable embedding and extraction

## 📁 Project Structure

```
zk-snarkXsteganography/
├── 📋 Documentation
│   ├── PROJECT_FLOW.md              # Development workflow
│   ├── SYSTEM_TEST_REPORT.md        # Test results
│   └── README.md                    # This file
├── 🔧 Source Code
│   └── src/zk_stego/
│       ├── chaos_embedding.py       # Core steganography
│       ├── hybrid_proof_artifact.py # ZK integration
│       └── zk_proof_generator.py    # ZK proof system
├── ⚙️ Circuits
│   ├── source/chaos_zk_stego.circom # ZK circuit
│   └── compiled/build/              # Compiled artifacts
├── 🎯 Demo & Testing
│   ├── Demo/                        # Demo scripts
│   ├── examples/testvectors/        # Test images
│   └── verify_zk_stego.py          # Verification API
├── 📊 Performance Analysis
│   └── performance/                 # Benchmark results
└── 🔑 Cryptographic Keys
    └── artifacts/keys/              # ZK setup keys
```

## 🚀 Quick Start

### Prerequisites

```bash
# Install dependencies
npm install -g snarkjs
pip install pillow numpy

# Ensure circom is available
./bin/circom --version
```

### Basic Usage

```python
from src.zk_stego.hybrid_proof_artifact import HybridProofArtifact
import numpy as np
from PIL import Image

# Load image
image = Image.open("examples/testvectors/Lenna_test_image.webp")
image_array = np.array(image)

# Initialize system
hybrid = HybridProofArtifact()

# Generate ZK proof
message = "Secret message"
proof_package = hybrid.generate_proof(image_array, message)

# Verify proof
is_valid = hybrid.verify_proof(proof_package)
print(f"Proof valid: {is_valid}")
```

### Command Line Verification

```bash
# Verify steganographic content
python3 verify_zk_stego.py stego_image.png
```

## 🎮 Demo Scripts

- **`Demo/quick_start.py`**: Minimal demo for testing
- **`Demo/comprehensive_demo.py`**: Full workflow with logging
- **`Demo/performance_benchmark.py`**: Performance analysis
- **`Demo/step_by_step_demo.py`**: Educational walkthrough

```bash
# Run comprehensive demo
cd Demo && python3 comprehensive_demo.py

# Run all demos
./Demo/run_all_demos.sh
```

## 📊 Performance Metrics

| Metric | Value |
|--------|-------|
| **Proof Generation** | 2.322s |
| **Proof Verification** | 0.505s |
| **Total Workflow** | 2.827s |
| **Proof Size** | 739 bytes |
| **Circuit Constraints** | 32 |
| **Success Rate** | 100% |

## 🔐 Security Features

- **Zero-Knowledge Privacy**: Proves embedding without revealing secrets
- **Chaos-Based Security**: Arnold Cat Map for position obfuscation
- **Cryptographic Verification**: Groth16 ZK-SNARK proofs
- **Tamper Detection**: PNG chunk integrity verification
- **Feature-Based Robustness**: Image analysis for stable embedding

## 🧪 Testing

The system includes comprehensive testing:

```bash
# Run performance analysis
python3 Demo/performance_benchmark.py

# System test report
cat SYSTEM_TEST_REPORT.md

# Check performance data
ls performance/
```

## 📚 Technical Documentation

- **`PROJECT_FLOW.md`**: Complete development history
- **`performance/`**: Detailed benchmark results
- **`Demo/FINAL_ANALYSIS_REPORT.md`**: Final analysis summary
- **`circuits/source/chaos_zk_stego.circom`**: ZK circuit specification

## 🛠️ Development

### Circuit Compilation

```bash
# Compile ZK circuit
cd circuits/source
circom chaos_zk_stego.circom --r1cs --wasm --sym -o ../compiled/build/
```

### Trusted Setup

The system automatically handles trusted setup using:
- Powers of Tau ceremony (pot12_final.ptau)
- Groth16 setup for circuit-specific keys
- Verification key generation

## 🎯 Use Cases

- **Private Communication**: Hidden message transmission
- **Digital Watermarking**: Copyright protection with ZK verification
- **Forensic Analysis**: Tamper-evident image authentication
- **Privacy-Preserving Systems**: Prove data existence without revelation

## 📄 License

Open source project for research and educational purposes.

## 🤝 Contributing

1. Review `PROJECT_FLOW.md` for development history
2. Check existing demo scripts for examples
3. Run comprehensive tests before submitting changes
4. Follow the established architecture patterns

---

**Built with ZK-SNARK technology for privacy-preserving steganography** 🔐✨