# ZK-SNARK Steganography: Complete Workflow Documentation

## 🎯 **Overview**

This project implements **steganographic transport for ZK-SNARK proofs**. Instead of sending proof files directly, we embed them into innocent-looking images.

### **Core Concept:**
```
Traditional: Prover → proof.json → Verifier
Our approach: Prover → proof.json → [embed] → stego.png → [extract] → proof.json → Verifier
```

**Key insight**: ZK-SNARK mathematics unchanged, only transmission method differs.

---

## 📋 **Complete Workflow**

### **Phase 1: ZK-SNARK Proof Generation** (Standard Process)

#### Step 1.1: Prepare Circuit Input
```bash
# Create input for steganography verification circuit
python3 src/core/embed_message.py cover.png temp_stego.png "1010110011010101" "10110011"
python3 src/core/extract_slots.py temp_stego.png "1010110011010101" "10110011" > input.json
```

**Files involved:**
- `src/core/embed_message.py` - Traditional LSB embedding
- `src/core/extract_slots.py` - Extract LSB values for circuit
- `circuits/source/stego_check_v2.circom` - ZK circuit

**Input format:**
```json
{
  "slots": [0,1,0,1,...],     // 256 LSB values (public)
  "message": [1,0,1,1,0,0,1,1], // 8 message bits (public)  
  "secret": [1,0,1,0,1,1,0,...]  // 16 secret bits (private)
}
```

#### Step 1.2: Compile Circuit (One-time setup)
```bash
cd circuits/source
circom stego_check_v2.circom --r1cs --wasm --sym -o ../compiled/build
cd ../..
```

**Outputs:**
- `circuits/compiled/build/stego_check_v2.r1cs` - Constraint system
- `circuits/compiled/build/stego_check_v2_js/` - WASM witness generator

#### Step 1.3: Generate Witness
```bash
cd circuits/compiled/build
node stego_check_v2_js/generate_witness.js stego_check_v2_js/stego_check_v2.wasm ../../../input.json ../../../witness.wtns
cd ../../..
```

**Process:**
- WASM circuit execution with input.json
- Constraint satisfaction verification
- Output: `witness.wtns` (all signal assignments)

#### Step 1.4: Generate ZK-SNARK Proof
```bash
# Setup (one-time per circuit)
snarkjs groth16 setup circuits/compiled/build/stego_check_v2.r1cs pot12_final.ptau circuit.zkey
snarkjs zkey export verificationkey circuit.zkey verification_key.json

# Prove
snarkjs groth16 prove circuit.zkey witness.wtns proof.json public.json
```

**Outputs:**
- `proof.json` - Groth16 proof (π_a, π_b, π_c)
- `public.json` - Public inputs
- `verification_key.json` - Verification key

---

### **Phase 2: Steganographic Embedding** (Our Innovation)

#### Step 2.1: Embed Proof into Image
```bash
python3 src/zk_stego/embed_proof.py cover.png stego.png proof.json [key]
```

**Process inside `embed_proof.py`:**
```python
# 1. Load proof.json
with open(proof_path, 'r') as f:
    proof_data = json.load(f)

# 2. Serialize: JSON → Base64 
proof_json = json.dumps(proof_data, separators=(',', ':'))
proof_b64 = base64.b64encode(proof_json.encode('utf-8')).decode('ascii')

# 3. Convert to binary bits
proof_bits = []
for char in proof_b64:
    char_bits = format(ord(char), '08b')  # 8-bit ASCII
    proof_bits.extend([int(b) for b in char_bits])

# 4. LSB embedding at key-derived positions
start_offset = hash(key) % 1000
for i, bit in enumerate(proof_bits):
    pos = (start_offset + i) % total_capacity
    flat_pixels[pos] = (flat_pixels[pos] & 0xFE) | bit  # Set LSB

# 5. Save stego image
stego_img.save(stego_path)
```

**Result:** `stego.png` - Normal-looking image containing ZK-proof

---

### **Phase 3: Transmission & Verification**

#### Step 3.1: Send Stego Image
- **Traditional**: Send `proof.json` + `public.json` 
- **Our method**: Send `stego.png` + `public.json`

**Advantages:**
- Covert: Looks like innocent photo
- Censorship-resistant: Hard to detect/block
- Plausible deniability: "Just a normal image"

#### Step 3.2: Extract Proof from Image
```bash
python3 src/zk_stego/extract_proof.py stego.png proof_extracted.json [key]
```

**Process inside `extract_proof.py`:**
```python
# 1. Load stego image, flatten pixels
img = Image.open(stego_path).convert('RGB')
flat_pixels = [component for r,g,b in img.getdata() for component in [r,g,b]]

# 2. Extract LSB bits at same positions
start_offset = hash(key) % 1000  # Same as embedding
proof_bits = []
for i in range(proof_length):
    pos = (start_offset + i) % total_capacity
    bit = flat_pixels[pos] & 1  # Extract LSB
    proof_bits.append(bit)

# 3. Reconstruct: Binary → ASCII → Base64 → JSON
chars = [chr(sum(proof_bits[i:i+8][j] * (2**(7-j)) for j in range(8))) 
         for i in range(0, len(proof_bits), 8)]
proof_b64 = ''.join(chars)
proof_json = base64.b64decode(proof_b64).decode('utf-8')
proof_data = json.loads(proof_json)

# 4. Save extracted proof
with open(proof_output, 'w') as f:
    json.dump(proof_data, f, indent=2)
```

#### Step 3.3: Standard ZK Verification
```bash
snarkjs groth16 verify verification_key.json public.json proof_extracted.json
```

**Process:**
- Standard Groth16 verification algorithm
- Pairing checks on elliptic curves
- Returns: `OK` or verification failure

---

## 🛠️ **Implementation Files**

### **Core ZK-SNARK Components:**
```
circuits/source/stego_check_v2.circom    # ZK circuit (unchanged)
src/core/embed_message.py               # Generate test steganography
src/core/extract_slots.py               # Extract LSBs for circuit input
```

### **Steganographic Transport:**
```
src/zk_stego/embed_proof.py             # Embed proof → image
src/zk_stego/extract_proof.py           # Extract proof ← image
```

### **Automation Scripts:**
```
scripts/demo/demo_zk_stego.sh           # Complete workflow demo
scripts/build/verifier.sh               # Extract + verify from image
```

---

## 🧪 **Testing & Validation**

### **Complete Workflow Test:**
```bash
./scripts/demo/demo_zk_stego.sh
```

**Expected output:**
```
🚀 ZK-SNARK STEGANOGRAPHY DEMO
Phase 1: Generate ZK-SNARK Proof
✓ Circuit input generated
✓ Witness generated  
✓ ZK-proof generated

Phase 2: Embed Proof into Image
✓ Proof embedded into stego image
Cover size: 1536 bytes
Stego size: 1536 bytes

Phase 3: Verification Workflow
✓ Proof extracted from stego image
✓ Proofs match exactly
✓ PROOF VERIFICATION SUCCESSFUL!

🎉 ZK-SNARK STEGANOGRAPHY DEMO COMPLETED SUCCESSFULLY!
```

### **Individual Component Tests:**
```bash
# Test proof embedding
python3 src/zk_stego/embed_proof.py examples/testvectors/cover_16x16.png test_stego.png temp/proof.json

# Test proof extraction  
python3 src/zk_stego/extract_proof.py test_stego.png test_extracted.json

# Compare proofs
diff temp/proof.json test_extracted.json
```

---

## 🔬 **Technical Specifications**

### **Proof Size Analysis:**
```
Typical Groth16 proof:
- JSON format: ~600-800 characters
- Base64 encoded: ~800-1100 characters  
- Binary bits: ~6400-8800 bits

Image capacity (16x16 RGB):
- Total pixels: 256
- RGB channels: 768
- LSB capacity: 768 bits
- Status: ❌ Too small for typical proofs

Image capacity (64x64 RGB):
- Total pixels: 4096  
- RGB channels: 12288
- LSB capacity: 12288 bits
- Status: ✅ Sufficient for most proofs
```

### **Security Considerations:**
- **Steganographic security**: LSB embedding detectable by statistical analysis
- **Key security**: Simple hash-based offset vulnerable to brute force
- **Proof integrity**: No cryptographic binding between image and proof
- **Production recommendations**: 
  - Use advanced steganography (DCT-based, adaptive embedding)
  - Implement cryptographic signatures
  - Add error correction codes

### **Performance Metrics:**
```
Embedding time: ~50ms (typical image + proof)
Extraction time: ~30ms (typical image + proof)  
Verification time: ~100ms (standard snarkjs)
Total workflow: ~10-60s (dominated by proof generation)
```

---

## 🎯 **Use Cases & Applications**

### **1. Covert ZK Verification:**
- **Scenario**: Journalist proves authenticity of leaked documents
- **Process**: Embed authenticity proof in metadata image
- **Benefit**: Document verification without revealing verification method

### **2. Censorship-Resistant Proof Transmission:**
- **Scenario**: Financial privacy in restricted networks
- **Process**: ZK-proof of valid transaction hidden in social media images
- **Benefit**: Proof transmission despite network monitoring

### **3. Supply Chain Verification:**
- **Scenario**: Product authenticity without revealing supplier details
- **Process**: Embed ZK-proof of manufacturing compliance in product images
- **Benefit**: Verifiable authenticity with privacy protection

### **4. Anonymous Credential Systems:**
- **Scenario**: Age verification without revealing exact age/identity
- **Process**: ZK-proof of age eligibility embedded in profile pictures
- **Benefit**: Credential verification with privacy preservation

---

## 🚀 **Future Enhancements**

### **Immediate Improvements:**
1. **Advanced steganography**: DCT-domain embedding, adaptive algorithms
2. **Robust extraction**: Error correction, multiple embedding strategies
3. **Security hardening**: Cryptographic signatures, tamper detection
4. **Performance optimization**: Faster embedding/extraction, batch processing

### **Research Directions:**
1. **Quantum-resistant steganography**: Post-quantum steganographic methods
2. **Blockchain integration**: On-chain verification with off-chain proofs
3. **Machine learning detection**: Adversarial steganography against AI detection
4. **Cross-media embedding**: Video, audio, multi-modal steganography

---

## 💡 **Key Innovation Summary**

**This project demonstrates that steganography and ZK-SNARKs are complementary technologies:**

- **ZK-SNARKs**: Provide mathematical proof without revealing secrets
- **Steganography**: Provides covert communication channel for proof transmission
- **Combined result**: **Covert cryptographic verification** - prove mathematical statements secretly without revealing the verification process itself

**The mathematics of zero-knowledge remains unchanged; we've simply made the proof transmission covert through steganographic channels.**