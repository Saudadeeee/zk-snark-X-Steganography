# ZK-SNARK Proof Artifact Specification

## 📦 **Artifact Structure**

### **JSON Schema:**
```json
{
  "proof": {
    "pi_a": ["<G1_point>", "<G1_point>"],
    "pi_b": [["<G2_point>", "<G2_point>"], ["<G2_point>", "<G2_point>"]],
    "pi_c": ["<G1_point>", "<G1_point>"],
    "protocol": "groth16",
    "curve": "bn128"
  },
  "public": {
    "image_hash": "<sha256_of_cover_image>",
    "commitment_root": "<merkle_root_of_slots>", 
    "message_length": 8,
    "timestamp": 1696752000,
    "nonce": 12345
  },
  "meta": {
    "vk_id": "stego_check_v2_20241010",
    "version": "1.0",
    "domain": "steganography",
    "circuit_hash": "<sha256_of_circuit_r1cs>"
  },
  "signature": {
    "value": "<ecdsa_signature>",
    "pubkey": "<signer_public_key>",
    "algorithm": "secp256k1"
  }
}
```

## 🔍 **Field Descriptions**

### **proof**: ZK-SNARK proof elements
- **pi_a, pi_b, pi_c**: Groth16 proof components
- **protocol**: Proof system identifier
- **curve**: Elliptic curve used

### **public**: Public inputs for verification
- **image_hash**: SHA256 of original cover image (pins proof to specific image)
- **commitment_root**: Merkle root of steganographic slots (compact representation)
- **message_length**: Length of embedded message (non-sensitive metadata)
- **timestamp**: When proof was generated (prevents replay)
- **nonce**: Random value for uniqueness

### **meta**: Verification metadata
- **vk_id**: Verification key identifier (enables key rotation)
- **version**: Artifact format version
- **domain**: Application domain
- **circuit_hash**: Hash of circuit for integrity

### **signature**: Optional authenticity proof
- **value**: Digital signature over (proof_hash || public || image_hash)
- **pubkey**: Signer's public key
- **algorithm**: Signature algorithm used

## 📏 **Size Constraints**

### **PNG Chunk Limits**:
- Max chunk size: 2^31 - 1 bytes (~2GB)
- Typical artifact size: ~1-2KB
- Chunk type: `zkPF` (zk-Proof)

### **Compression**:
- JSON → CBOR (binary) for size reduction
- Optional zlib compression for large proofs

## 🔒 **Security Properties**

### **Integrity**:
- Artifact tamper detection via signature
- Image binding via image_hash in public inputs
- Circuit binding via circuit_hash in meta

### **Authenticity**:
- Optional ECDSA signature over critical fields
- Public key can be embedded or referenced

### **Replay Protection**:
- Timestamp and nonce prevent proof reuse
- Image hash prevents cross-image attacks

## 🚀 **API Design**

### **Embedding API**:
```python
def embed_proof_artifact(
    cover_image_path: str,
    stego_image_path: str, 
    proof_json: dict,
    public_json: dict,
    signing_key: Optional[bytes] = None
) -> bool
```

### **Verification API**:
```python
def verify_stego_image(
    stego_image_path: str,
    verification_key_path: str
) -> bool
```

### **CLI Interface**:
```bash
# Single command verification (desired UX)
./verify_stego.sh stego.png  # → True/False

# Detailed verification with metadata
./verify_stego.sh stego.png --verbose  # → Full artifact details
```

## 📋 **Implementation Phases**

### **Phase 1: Artifact Packing/Unpacking**
- JSON artifact serialization
- PNG chunk embedding/extraction
- Basic integrity checks

### **Phase 2: Signature Integration**
- ECDSA signing over artifact
- Public key management
- Signature verification

### **Phase 3: API Simplification**
- Single-command verification
- Error handling and reporting
- Performance optimization

### **Phase 4: Advanced Features**
- CBOR binary encoding
- Compression for large proofs
- Multi-signature support

## 🔧 **Technical Considerations**

### **PNG Chunk Safety**:
- Use ancillary chunk (safe for image editors)
- Chunk CRC for corruption detection
- Preserve other image metadata

### **Public Input Optimization**:
- Use Merkle roots instead of full arrays
- Minimize public input count for efficiency
- Balance between proof size and verification cost

### **Circuit Modifications**:
- Add image_hash as public input
- Replace slots[] array with commitment_root
- Maintain backward compatibility

## 📊 **Performance Expectations**

### **Proof Generation**: 
- Time: ~2-5 seconds (unchanged)
- Size: ~1KB artifact + original image

### **Verification**:
- Extract artifact: ~1ms
- Verify signature: ~5ms  
- Verify ZK proof: ~10ms
- **Total: ~16ms** ⚡

### **Storage Overhead**:
- Artifact size: ~1-2KB
- Image size increase: <0.1% for typical images