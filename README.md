# ZK-SNARK Steganography Proof of Concept

A zero-knowledge proof system for steganographic embedding that proves message existence without revealing the secret key.

## 🎯 Purpose

This PoC demonstrates:
- **Secret-based positioning**: Use secret bits to determine where message bits are embedded in image LSBs
- **Zero-knowledge proving**: Prove that specific LSB positions contain the claimed message without revealing the secret
- **End-to-end workflow**: embed → generate witness → prove → verify

## 🏗️ Architecture

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

### 2. Run Complete Demo

```bash
./demo.sh
```

This runs the full end-to-end workflow and explains each step.

### 3. Run Unit Tests

```bash
python3 test_poc.py
```

### 4. Manual Step-by-Step

```bash
# Step 1: Embed message into cover image
python3 embed_message.py testvectors/cover_16x16.png stego.png 1010110011010101 10110011

# Step 2: Extract slots and generate circuit input
python3 extract_slots.py stego.png 1010110011010101 10110011 > input.json

# Step 3: Compile circuit, setup, and generate proof
./prover.sh input.json

# Step 4: Verify the proof
./verifier.sh
```

## 📖 Detailed Workflow

### Step 1: Install Dependencies

```bash
# Install Node.js (if not already installed)
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt-get install -y nodejs

# Install circom and snarkjs
npm install -g circom snarkjs

# Install Python dependencies
pip3 install pillow
```

### Step 2: Compile Circuit

```bash
# Compile the circuit (done automatically by prover.sh)
./circom stego_check_v2.circom --r1cs --wasm --sym -o build

# This creates:
# - build/stego_check_v2.r1cs (rank-1 constraint system)
# - build/stego_check_v2_js/ (witness generator)
# - build/stego_check_v2.sym (symbol table)
```

### Step 3: Trusted Setup (Groth16)

```bash
# Download powers of tau ceremony file (one-time, done automatically)
wget https://storage.googleapis.com/zkevm/ptau/powersOfTau28_hez_final_12.ptau -O pot12_final.ptau

# Perform trusted setup
snarkjs groth16 setup build/stego_check_v2.r1cs pot12_final.ptau build/circuit_0000.zkey

# Export verification key
snarkjs zkey export verificationkey build/circuit_0000.zkey verification_key.json
```

### Step 4: Embed Message

```bash
# Embed 8-bit message using 16-bit secret
python3 embed_message.py cover.png stego.png SECRET_BITS MESSAGE_BITS

# Example:
python3 embed_message.py testvectors/cover_16x16.png stego.png 1010110011010101 10110011

# This will:
# - Calculate positions based on secret: position = (secret_int + i) % total_slots
# - Modify LSB at each position to match message bit
# - Save stego image
```

### Step 5: Extract Slots & Form Input

```bash
# Extract all LSB values and generate circuit input
python3 extract_slots.py stego.png SECRET_BITS MESSAGE_BITS > input.json

# The input.json contains:
# {
#   "slots": [0,1,0,1,...],     // 256 LSB values (public)
#   "message": [1,0,1,1,...],   // 8 message bits (public)
#   "secret": [1,0,1,0,...]     // 16 secret bits (private)
# }
```

### Step 6: Generate Witness & Proof

```bash
# Generate witness from input
node build/stego_check_v2_js/generate_witness.js build/stego_check_v2_js/stego_check_v2.wasm input.json witness.wtns

# Generate zero-knowledge proof
snarkjs groth16 prove build/circuit_0000.zkey witness.wtns proof.json public.json

# This creates:
# - proof.json (the zk-SNARK proof)
# - public.json (public inputs: slots + message)
# - witness.wtns (witness file)
```

### Step 7: Verify Proof

```bash
# Verify the proof
snarkjs groth16 verify verification_key.json public.json proof.json

# Success output: "OK"
# This proves that the LSBs at secret-determined positions equal the message
# WITHOUT revealing the secret!
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
├── stego_check_v2.circom       # Working circuit definition
├── stego_check.circom          # Original circuit (may have syntax issues)
├── circom                      # Circom compiler binary
├── build/                      # Compiled circuit artifacts
│   ├── stego_check_v2.r1cs    # Constraint system
│   ├── stego_check_v2_js/     # Witness generator
│   └── circuit_0000.zkey      # Proving key
├── prover.sh                  # Build + setup + prove pipeline
├── verifier.sh                # Verification script
├── demo.sh                    # Complete end-to-end demo
├── embed_message.py           # Embed message into image
├── extract_slots.py           # Extract LSBs and generate input
├── generate_input.py          # Helper for input formatting
├── test_poc.py               # Unit tests
├── create_test_images.py     # Generate test cover images
├── testvectors/              # Test images and expected outputs
├── README.md                 # This file
├── pot12_final.ptau         # Powers of tau ceremony file
├── verification_key.json    # Public verification key
├── proof.json               # Generated proof
├── public.json              # Public inputs
└── input.json               # Circuit input
```

## 🔬 Circuit Parameters

- **N_SLOTS**: 256 (maximum LSB positions to consider)
- **MSG_LEN**: 8 (message length in bits)
- **SECRET_LEN**: 16 (secret length in bits)

These can be modified in `stego_check.circom` for different requirements.

## ⚠️ PoC Limitations

### Security Limitations:
1. **LSB fragility**: LSB embedding is vulnerable to image recompression/editing
2. **No error correction**: No ECC to handle bit flips
3. **Simple positioning**: Linear addressing is predictable
4. **Public slots**: All LSBs are public inputs (production should use hashing)

### Scale Limitations:
1. **Fixed circuit size**: Circuit is compiled for specific N_SLOTS/MSG_LEN
2. **Memory usage**: Large circuits require significant RAM for proving
3. **Proof time**: Grows with circuit complexity

### Production Requirements:
1. **Transform domain**: Use DCT/DWT instead of spatial LSB
2. **Cryptographic hashing**: Hash slots instead of exposing them
3. **ECC protection**: Add Reed-Solomon or similar
4. **Key management**: Proper key derivation and storage
5. **Metadata**: Include timestamps, signatures, provenance

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

✅ **Embedding works**: Message successfully embedded in image LSBs  
✅ **Extraction works**: Can recover message bits from known positions  
✅ **Circuit compiles**: No syntax errors in circom code  
✅ **Witness generation**: Input.json produces valid witness  
✅ **Proof generation**: Witness produces valid proof  
✅ **Verification passes**: Proof verifies with public inputs  
✅ **Tamper detection**: Modified stego fails verification  

## 🚀 Next Steps for Production

1. **Enhanced Stego**: Implement DCT-domain embedding with ECC
2. **Circuit Optimization**: Use Poseidon hash for slot commitment
3. **Universal Setup**: Migrate to Plonk for better scalability
4. **Key Management**: Integrate with HSM/KMS systems
5. **Audit Trail**: Add blockchain anchoring for provenance
6. **Performance**: Optimize for larger images and messages

## 📝 License

This is a Proof of Concept for educational purposes. Not suitable for production use without significant security hardening.