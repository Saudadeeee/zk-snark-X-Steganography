# ROADMAP NÂNG CẤP: ZK-PROOF VIDEO STEGANOGRAPHY

**Phiên bản hiện tại:** 2.0 (DCT-based)  
**Mục tiêu:** Nâng cấp lên 3.0 với YUV+DWT, RC4 Encryption, LDPC ECC, và Context-Aware Embedding  
**Ngày bắt đầu:** 4 tháng 2, 2026  
**Timeline dự kiến:** 8-12 tuần

---

## 📊 TỔNG QUAN CẢI TIẾN

### Vấn đề hiện tại (v2.0)
- ❌ Chỉ sử dụng DCT coefficients trực tiếp → Nhạy cảm với re-compression
- ❌ Không có phân tích tần số trước nhúng → Dễ bị mất dữ liệu ở vùng HH (High-High)
- ❌ Thiếu mã hóa pre-embedding → ZK Proof có dấu vết thống kê
- ❌ Không có Context-Aware selection → Nhúng vào flat areas gây artifacts
- ❌ Accuracy 60% khi extraction → Cần LDPC để đạt 100%
- ❌ Thiếu Interleaving → Vulnerability với frame loss

### Cải tiến mục tiêu (v3.0)
- ✅ **YUV + DWT hybrid**: Phân tích tần số trước DCT embedding
- ✅ **RC4 Pre-encryption**: Che giấu dấu vết thống kê của ZK Proof
- ✅ **Context-Aware Embedding**: Chỉ nhúng vào texture-rich regions
- ✅ **LDPC Rate 1/2**: Nâng accuracy từ 60% → 100%
- ✅ **Temporal Interleaving**: Phân tán qua n frames
- ✅ **SEI Metadata**: Lưu stable_map và LDPC params
- ✅ **CAVLC Re-padding**: Fix bitstream corruption

---

## 🎯 GIAI ĐOẠN 1: MASTER BITSTREAM & PRE-PROCESSING
**Timeline:** Tuần 1-3 (3 tuần)  
**Mục tiêu:** Bổ sung phân tích YUV và DWT để tìm vùng nhúng ổn định

### 1.1 Chuyển đổi không gian màu YUV
**File mới:** `src/zk_mv_stego/preprocessing/yuv_converter.py`

**Tasks:**
- [ ] Implement RGB → YUV conversion cho H.264 frames
- [ ] Extract Y (Luma), Cb, Cr channels riêng biệt
- [ ] Tập trung embedding vào Y channel (mắt người ít nhạy cảm)
- [ ] Hỗ trợ YUV 4:2:0 subsampling (chuẩn H.264)

**API Design:**
```python
class YUVConverter:
    def extract_yuv_from_frame(self, frame_data: bytes) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Extract Y, Cb, Cr channels"""
        pass
    
    def get_luma_channel(self, frame_data: bytes) -> np.ndarray:
        """Get Y channel only (for embedding)"""
        pass
    
    def reconstruct_from_yuv(self, y: np.ndarray, cb: np.ndarray, cr: np.ndarray) -> bytes:
        """Reconstruct frame from YUV"""
        pass
```

**Tài liệu tham khảo:**
- ITU-T H.264 Section 6.2: Color space conversion
- "Steganography in YUV Color Space" (Li et al., 2015)

---

### 1.2 Haar DWT Analysis
**File mới:** `src/zk_mv_stego/preprocessing/dwt_analyzer.py`

**Tasks:**
- [ ] Implement Haar Wavelet Transform bậc 2
- [ ] Phân tách sub-bands: LL, LH, HL, HH
- [ ] Tính energy distribution cho mỗi sub-band
- [ ] Tạo frequency map cho mỗi macroblock

**API Design:**
```python
class HaarDWTAnalyzer:
    def analyze_macroblock(self, mb_data: np.ndarray) -> Dict[str, np.ndarray]:
        """
        Returns:
            {
                'LL': low-low coefficients,
                'LH': low-high coefficients,  # Horizontal edges
                'HL': high-low coefficients,  # Vertical edges
                'HH': high-high coefficients  # Diagonal details
            }
        """
        pass
    
    def compute_energy_map(self, dwt_coeffs: Dict) -> np.ndarray:
        """Compute energy distribution across frequency bands"""
        pass
    
    def classify_frequency_region(self, energy_map: np.ndarray) -> str:
        """Classify as 'low', 'mid', 'high' frequency"""
        pass
```

**Công thức Haar DWT:**
$$
\begin{aligned}
LL_{i,j} &= \frac{1}{2}(x_{2i,2j} + x_{2i+1,2j} + x_{2i,2j+1} + x_{2i+1,2j+1}) \\
LH_{i,j} &= \frac{1}{2}(x_{2i,2j} - x_{2i+1,2j} + x_{2i,2j+1} - x_{2i+1,2j+1}) \\
HL_{i,j} &= \frac{1}{2}(x_{2i,2j} + x_{2i+1,2j} - x_{2i,2j+1} - x_{2i+1,2j+1}) \\
HH_{i,j} &= \frac{1}{2}(x_{2i,2j} - x_{2i+1,2j} - x_{2i,2j+1} + x_{2i+1,2j+1})
\end{aligned}
$$

---

### 1.3 Hybrid DCT-DWT Selection Strategy
**File mới:** `src/zk_mv_stego/preprocessing/hybrid_selector.py`

**Tasks:**
- [ ] Kết hợp DWT frequency analysis với DCT coefficients
- [ ] Lọc bỏ DCT coeffs trong vùng HH (high-high) của DWT
- [ ] Ưu tiên DCT coeffs trong vùng LH/HL (edge information)
- [ ] Tạo stability score cho mỗi coefficient

**Decision Rules:**
```python
def should_use_coefficient(dct_coeff: int, dwt_region: str, position: int) -> bool:
    # Rule 1: Skip DC (position 0)
    if position == 0:
        return False
    
    # Rule 2: Skip high-frequency regions (DWT HH)
    if dwt_region == 'HH':
        return False  # Dễ bị triệt tiêu khi re-encode
    
    # Rule 3: Skip zeros and ±1
    if abs(dct_coeff) < 2:
        return False
    
    # Rule 4: Prioritize mid-frequency (LH, HL)
    if dwt_region in ['LH', 'HL'] and abs(dct_coeff) >= 3:
        return True  # Best candidates
    
    # Rule 5: Use low-frequency (LL) cautiously
    if dwt_region == 'LL' and abs(dct_coeff) >= 5:
        return True  # Only strong coefficients
    
    return False
```

**Deliverables:**
- [ ] `yuv_converter.py` (150 dòng)
- [ ] `dwt_analyzer.py` (200 dòng)
- [ ] `hybrid_selector.py` (180 dòng)
- [ ] Unit tests cho 3 modules
- [ ] Benchmark: Tăng stability score trung bình 30-40%

---

## 🔐 GIAI ĐOẠN 2: THUẬT TOÁN NHÚNG THÍCH NGHI
**Timeline:** Tuần 4-6 (3 tuần)  
**Mục tiêu:** Bổ sung RC4 encryption và Context-Aware embedding

### 2.1 RC4 Pre-embedding Encryption
**File mới:** `src/zk_mv_stego/crypto/rc4_cipher.py`

**Tasks:**
- [ ] Implement RC4 stream cipher
- [ ] Tạo keystream từ secret key
- [ ] Encrypt ZK Proof trước khi embedding
- [ ] Đảm bảo output giống white noise (entropy > 7.9)

**API Design:**
```python
class RC4Cipher:
    def __init__(self, key: bytes):
        """Initialize RC4 with secret key (128-256 bits)"""
        self.S = self._ksa(key)  # Key Scheduling Algorithm
        
    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt data using RC4 stream cipher"""
        return self._prga(plaintext)  # Pseudo-Random Generation Algorithm
    
    def decrypt(self, ciphertext: bytes) -> bytes:
        """Decrypt (same as encrypt for stream cipher)"""
        return self._prga(ciphertext)
    
    def measure_entropy(self, data: bytes) -> float:
        """Measure Shannon entropy (should be close to 8.0)"""
        pass
```

**Lợi ích:**
- ZK Proof có cấu trúc toán học đặc trưng (G1/G2 points)
- RC4 biến proof thành random bits → Steganalysis resistance
- Lightweight (nhanh hơn AES cho payloads nhỏ)

**Security Note:**
- RC4 không an toàn cho encryption chung, nhưng OK cho steganography obfuscation
- Key derivation: `secret_key = HMAC-SHA256(master_key, "RC4_STEGO_V3")`

---

### 2.2 Context-Aware Embedding (NLSA-inspired)
**File mới:** `src/zk_mv_stego/embedder/context_analyzer.py`

**Tasks:**
- [ ] Phân tích texture complexity của mỗi macroblock
- [ ] Tính motion vectors từ P-frames (nếu có)
- [ ] Tạo attention map cho embedding regions
- [ ] Chỉ nhúng vào high-texture hoặc high-motion areas

**Texture Analysis:**
```python
class ContextAnalyzer:
    def compute_texture_score(self, macroblock: np.ndarray) -> float:
        """
        Compute texture complexity using Laplacian variance
        
        High score (>100) = complex texture = good for embedding
        Low score (<20) = flat area = avoid embedding
        """
        laplacian = cv2.Laplacian(macroblock, cv2.CV_64F)
        variance = laplacian.var()
        return variance
    
    def compute_motion_score(self, mvs: List[Tuple[int, int]]) -> float:
        """
        Compute motion magnitude from motion vectors
        
        High motion = good for embedding (temporal masking)
        """
        if not mvs:
            return 0.0
        magnitudes = [np.sqrt(mx**2 + my**2) for mx, my in mvs]
        return np.mean(magnitudes)
    
    def create_attention_map(self, frame_data: Dict) -> np.ndarray:
        """
        Create attention map combining texture + motion
        
        Returns:
            Binary mask (1 = embed, 0 = skip)
        """
        texture_map = self._texture_analysis(frame_data)
        motion_map = self._motion_analysis(frame_data)
        
        # Combined score (weighted)
        attention = 0.6 * texture_map + 0.4 * motion_map
        
        # Threshold (top 40% regions)
        threshold = np.percentile(attention, 60)
        return (attention >= threshold).astype(np.uint8)
```

**Embedding Strategy:**
```python
def select_embedding_coefficients(coeffs: List, attention_map: np.ndarray, 
                                  dwt_regions: np.ndarray) -> List[int]:
    """
    Multi-criteria selection:
    1. DWT region is LH or HL (not HH)
    2. Attention map indicates high-texture/motion
    3. |coefficient| >= 3
    4. Not DC (position 0)
    """
    selected = []
    for i, coeff in enumerate(coeffs):
        mb_idx = i // 16  # Macroblock index
        
        # Check all criteria
        if (dwt_regions[mb_idx] in ['LH', 'HL'] and
            attention_map[mb_idx] == 1 and
            abs(coeff) >= 3 and
            i % 16 != 0):
            selected.append(i)
    
    return selected
```

**Deliverables:**
- [ ] `rc4_cipher.py` (120 dòng)
- [ ] `context_analyzer.py` (250 dòng)
- [ ] Integration với `payload_embedder.py`
- [ ] Benchmark: Giảm visual artifacts 50-60%

---

## 🛡️ GIAI ĐOẠN 3: TÍCH HỢP ECC & CẤU TRÚC PHÂN TÁN
**Timeline:** Tuần 7-9 (3 tuần)  
**Mục tiêu:** LDPC coding + Temporal Interleaving để đạt 100% accuracy

### 3.1 LDPC Error Correction Code
**File mới:** `src/zk_mv_stego/ecc/ldpc_codec.py`

**Tasks:**
- [ ] Implement LDPC encoder với rate 1/2
- [ ] Tạo parity-check matrix (H-matrix)
- [ ] Implement Belief Propagation decoder
- [ ] Test với bit error rate 5-10%

**API Design:**
```python
class LDPCCodec:
    def __init__(self, code_rate: float = 0.5, block_size: int = 1536):
        """
        Args:
            code_rate: Rate 1/2 means 192 bytes → 384 bytes
            block_size: Total bits (192 bytes * 8 = 1536 bits)
        """
        self.rate = code_rate
        self.k = block_size  # Information bits
        self.n = int(block_size / code_rate)  # Codeword bits
        self.H = self._generate_parity_check_matrix()
    
    def encode(self, data: bytes) -> bytes:
        """
        Encode data with LDPC
        
        Input: 192 bytes (ZK Proof)
        Output: 384 bytes (with redundancy)
        """
        bits = self._bytes_to_bits(data)
        
        # Add parity bits
        parity = self._compute_parity(bits)
        codeword = bits + parity
        
        return self._bits_to_bytes(codeword)
    
    def decode(self, received: bytes, max_iter: int = 50) -> Tuple[bytes, bool]:
        """
        Decode with Belief Propagation
        
        Returns:
            (decoded_data, success_flag)
        """
        bits = self._bytes_to_bits(received)
        
        # Belief Propagation iterations
        decoded_bits, converged = self._bp_decode(bits, max_iter)
        
        # Extract information bits
        info_bits = decoded_bits[:self.k]
        
        return self._bits_to_bytes(info_bits), converged
    
    def _bp_decode(self, received_bits: List[int], max_iter: int) -> Tuple[List[int], bool]:
        """Belief Propagation algorithm"""
        # Initialize log-likelihood ratios (LLRs)
        llr = np.array([1.0 if b == 0 else -1.0 for b in received_bits])
        
        for iteration in range(max_iter):
            # Check node update
            # Variable node update
            # Check convergence
            pass
        
        return decoded_bits, converged
```

**LDPC Matrix Design:**
- Sử dụng **Progressive Edge-Growth (PEG)** algorithm
- Target girth ≥ 6 (tránh short cycles)
- Column weight = 3, Row weight = 6 (regular LDPC)

---

### 3.2 Temporal Interleaving Strategy
**File mới:** `src/zk_mv_stego/embedder/temporal_interleaver.py`

**Tasks:**
- [ ] Phân tán 384 bytes LDPC qua n frames (n=8-16)
- [ ] Implement Recurrent Strategy (frame n+1 phụ thuộc frame n)
- [ ] Tạo interleaving pattern với pseudo-random permutation
- [ ] Xử lý frame loss (robust decoding)

**Interleaving Design:**
```python
class TemporalInterleaver:
    def __init__(self, num_frames: int = 10, secret_seed: bytes = None):
        """
        Args:
            num_frames: Số frames để phân tán payload
            secret_seed: Seed cho PRNG (từ ZK secret)
        """
        self.num_frames = num_frames
        self.rng = np.random.RandomState(int.from_bytes(secret_seed[:4], 'big'))
    
    def interleave(self, payload: bytes) -> List[bytes]:
        """
        Phân tán payload qua n frames
        
        Input: 384 bytes (LDPC encoded)
        Output: List of n chunks (38-40 bytes each)
        """
        # Chia payload thành n chunks
        chunk_size = len(payload) // self.num_frames
        chunks = []
        
        for i in range(self.num_frames):
            start = i * chunk_size
            end = start + chunk_size if i < self.num_frames - 1 else len(payload)
            chunk = payload[start:end]
            chunks.append(chunk)
        
        # Pseudo-random permutation (để tăng security)
        indices = list(range(self.num_frames))
        self.rng.shuffle(indices)
        
        return [chunks[i] for i in indices], indices
    
    def deinterleave(self, chunks: List[bytes], indices: List[int]) -> bytes:
        """
        Ghép lại payload từ các chunks
        
        Robust với missing frames (LDPC sẽ recover)
        """
        # Restore original order
        ordered_chunks = [None] * self.num_frames
        for i, chunk in zip(indices, chunks):
            ordered_chunks[i] = chunk
        
        # Handle missing chunks (fill with zeros - LDPC will correct)
        for i in range(self.num_frames):
            if ordered_chunks[i] is None:
                ordered_chunks[i] = b'\x00' * (len(chunks[0]) if chunks else 40)
        
        return b''.join(ordered_chunks)
    
    def compute_frame_dependency(self, frame_idx: int, prev_hash: bytes) -> int:
        """
        Recurrent Strategy: Frame n+1 phụ thuộc hash của frame n
        
        Returns:
            Starting position for embedding in current frame
        """
        hash_val = int.from_bytes(hashlib.sha256(prev_hash).digest()[:4], 'big')
        return hash_val % 100  # Starting macroblock index
```

**Recurrent Strategy:**
```
Frame 0: Embed chunk[0] tại MB[0:20]
         Hash(chunk[0]) → seed cho Frame 1

Frame 1: Embed chunk[1] tại MB[seed%100 : seed%100+20]
         Hash(chunk[0] || chunk[1]) → seed cho Frame 2

Frame 2: Embed chunk[2] tại MB[seed%100 : seed%100+20]
         ...
```

**Lợi ích:**
- Attacker không thể extract nếu thiếu bất kỳ frame nào
- LDPC có thể recover với 10-20% bit errors
- Tăng robustness với video streaming (frame drops)

**Deliverables:**
- [ ] `ldpc_codec.py` (400 dòng)
- [ ] `temporal_interleaver.py` (250 dòng)
- [ ] Integration tests với simulated errors
- [ ] Benchmark: 100% recovery với ≤15% bit errors

---

## 🔧 GIAI ĐOẠN 4: FIX CAVLC & DRIFT COMPENSATION
**Timeline:** Tuần 10-12 (3 tuần)  
**Mục tiêu:** Đảm bảo bitstream integrity và SEI metadata

### 4.1 SEI Metadata Storage
**File update:** `src/zk_mv_stego/bitstream/sei_handler.py`

**Tasks:**
- [ ] Tạo User Data Unregistered SEI
- [ ] Lưu trữ: stable_map, LDPC params, interleaving indices
- [ ] Ensure SEI không bị decoder loại bỏ
- [ ] Compact serialization (< 500 bytes)

**SEI Payload Structure:**
```python
class SEIMetadata:
    """
    SEI User Data Unregistered payload
    
    Structure:
    - UUID (16 bytes): "ZKSTEGO3" identifier
    - Version (1 byte): 0x03
    - Stable Map (compressed, ~200 bytes)
    - LDPC Params (16 bytes):
        - code_rate (float32)
        - block_size (uint32)
        - num_iterations (uint16)
    - Interleaving Info (20 bytes):
        - num_frames (uint8)
        - permutation indices (variable)
        - seed (8 bytes)
    - Checksum (4 bytes): CRC32
    """
    
    def serialize(self) -> bytes:
        """Serialize metadata to SEI payload"""
        payload = b''
        
        # UUID
        payload += b'ZKSTEGO3' + b'\x00' * 8
        
        # Version
        payload += b'\x03'
        
        # Stable map (compressed with zlib)
        stable_map_compressed = zlib.compress(self.stable_map_bytes, level=9)
        payload += struct.pack('>H', len(stable_map_compressed))
        payload += stable_map_compressed
        
        # LDPC params
        payload += struct.pack('>fIH', 
                              self.code_rate,
                              self.block_size,
                              self.ldpc_iterations)
        
        # Interleaving
        payload += struct.pack('>B', self.num_frames)
        payload += bytes(self.permutation_indices)
        payload += self.interleaving_seed
        
        # Checksum
        crc = zlib.crc32(payload)
        payload += struct.pack('>I', crc)
        
        return payload
    
    def deserialize(self, payload: bytes) -> None:
        """Parse SEI payload"""
        # Verify checksum
        # Extract all fields
        pass
```

**SEI Insertion:**
- Insert SEI NAL unit **sau SPS/PPS, trước slice data**
- NAL type = 6 (SEI)
- Payload type = 5 (User Data Unregistered)

---

### 4.2 CAVLC Re-padding & Drift Fix
**File update:** `src/zk_mv_stego/bitstream/cavlc_encoder.py`

**Tasks:**
- [ ] Tính toán bit-length change sau khi modify coefficients
- [ ] Re-pad NAL unit để giữ alignment
- [ ] Fix slice_qp_delta nếu cần
- [ ] Verify với H.264 reference decoder

**Drift Compensation:**
```python
def compensate_bitstream_drift(original_nal: bytes, modified_nal: bytes) -> bytes:
    """
    Fix bitstream drift caused by coefficient modification
    
    Steps:
    1. Calculate bit-length difference
    2. Adjust emulation_prevention_three_byte
    3. Re-calculate NAL size
    4. Update slice header if needed
    """
    orig_bits = len(original_nal) * 8
    mod_bits = len(modified_nal) * 8
    drift = mod_bits - orig_bits
    
    if drift == 0:
        return modified_nal  # No drift
    
    # Method 1: Add stuffing bits (0x80 followed by zeros)
    if drift < 0:
        # NAL became shorter, add stuffing
        stuffing_bits = -drift
        stuffing_bytes = bytes([0x80] + [0x00] * (stuffing_bits // 8))
        return modified_nal + stuffing_bytes
    
    # Method 2: Try to compress other coefficients slightly
    # (Advanced technique - modify trailing zeros)
    else:
        # NAL became longer, compress if possible
        return try_compress_trailing_data(modified_nal, drift)

def verify_bitstream_integrity(nal_data: bytes) -> bool:
    """
    Verify NAL unit integrity
    
    Checks:
    - Start code present
    - No forbidden_zero_bit violations
    - Valid slice header
    - CAVLC decoding succeeds
    """
    # Parse NAL header
    # Verify slice header
    # Test decode with reference decoder
    pass
```

**Testing Strategy:**
```bash
# Test với FFmpeg decoder
ffmpeg -i stego_video.h264 -f null -

# Test với x264 decoder
x264 --output /dev/null stego_video.h264

# Test với JM reference software
ldecod -i stego_video.h264
```

**Deliverables:**
- [ ] SEI metadata handler (150 dòng)
- [ ] CAVLC drift compensation (200 dòng)
- [ ] Bitstream verification tool
- [ ] Passed với 3 decoders: FFmpeg, x264, JM

---

## 🧪 TESTING & VALIDATION

### Test Suite Expansion
**File mới:** `tests/test_upgrade_v3.py`

```python
class TestUpgradeV3:
    def test_yuv_dwt_integration(self):
        """Test YUV + DWT preprocessing pipeline"""
        pass
    
    def test_rc4_encryption(self):
        """Verify RC4 entropy > 7.9"""
        pass
    
    def test_context_aware_selection(self):
        """Verify embedding in high-texture regions only"""
        pass
    
    def test_ldpc_recovery(self):
        """Test LDPC with 0%, 5%, 10%, 15% bit errors"""
        assert recovery_rate_0 == 100%
        assert recovery_rate_5 == 100%
        assert recovery_rate_10 == 100%
        assert recovery_rate_15 >= 98%
    
    def test_temporal_interleaving(self):
        """Test with frame drops"""
        pass
    
    def test_bitstream_integrity(self):
        """Verify no corruption with FFmpeg/x264/JM"""
        pass
    
    def test_end_to_end_v3(self):
        """Complete workflow: embed → extract → verify"""
        pass
```

### Benchmarks
| Metric | v2.0 (Current) | v3.0 (Target) |
|--------|----------------|---------------|
| **Extraction Accuracy** | 60% | **100%** |
| **PSNR** | 45 dB | **48 dB** |
| **Capacity** | 95 bits/frame | **120 bits/frame** (with LDPC overhead) |
| **Robustness** | Low (re-encode fails) | **High (survives 1-2 re-encodes)** |
| **Steganalysis Resistance** | Medium | **High (RC4 + Context-Aware)** |
| **Processing Time** | 0.5s/frame | **0.8s/frame** (DWT+LDPC overhead) |

---

## 📦 DELIVERABLES SUMMARY

### New Files (13 files)
1. `src/zk_mv_stego/preprocessing/yuv_converter.py` (150 lines)
2. `src/zk_mv_stego/preprocessing/dwt_analyzer.py` (200 lines)
3. `src/zk_mv_stego/preprocessing/hybrid_selector.py` (180 lines)
4. `src/zk_mv_stego/crypto/rc4_cipher.py` (120 lines)
5. `src/zk_mv_stego/embedder/context_analyzer.py` (250 lines)
6. `src/zk_mv_stego/ecc/ldpc_codec.py` (400 lines)
7. `src/zk_mv_stego/ecc/temporal_interleaver.py` (250 lines)
8. `tests/test_upgrade_v3.py` (300 lines)
9. `docs/YUV_DWT_DESIGN.md`
10. `docs/LDPC_SPECIFICATION.md`
11. `docs/CONTEXT_AWARE_EMBEDDING.md`
12. `benchmarks/v3_performance.py`
13. `examples/workflow_v3.py`

### Updated Files (4 files)
1. `src/zk_mv_stego/bitstream/sei_handler.py` (+150 lines)
2. `src/zk_mv_stego/bitstream/cavlc_encoder.py` (+200 lines)
3. `src/zk_mv_stego/embedder/payload_embedder.py` (+100 lines)
4. `embed_complete.py` (+80 lines)

### Total New Code
- **~2,380 lines** of new production code
- **~500 lines** of test code
- **~800 lines** of documentation

---

## 🎓 REFERENCES & PAPERS

### Steganography
1. **"DWT-DCT-SVD Based Steganography"** (Kumar et al., 2018)
   - Hybrid wavelet-DCT approach
2. **"Context-Aware Steganography"** (Holub et al., 2014)
   - Texture analysis for embedding selection
3. **"Steganography in YUV Color Space"** (Li et al., 2015)
   - Color space advantages

### Error Correction
4. **"LDPC Codes for Steganography"** (Fridrich et al., 2007)
   - Matrix embedding with LDPC
5. **"Progressive Edge-Growth LDPC Construction"** (Hu et al., 2005)
   - Optimal parity-check matrices

### Video Codec
6. **ITU-T H.264 Specification** (ISO/IEC 14496-10)
   - Section 7.3: Syntax
   - Section 9.2: CAVLC
7. **"H.264/AVC Steganography"** (Zhang et al., 2016)
   - Best practices for coefficient modification

---

## 🚀 MIGRATION PLAN

### Backward Compatibility
- v3.0 có thể **đọc** video từ v2.0 (fallback mode)
- v2.0 **không thể** đọc video từ v3.0 (có SEI metadata v3)
- Cần version flag trong SEI để detect

### Version Detection
```python
def detect_stego_version(video_path: str) -> str:
    """
    Detect steganography version
    
    Returns: "v2.0" | "v3.0" | "unknown"
    """
    # Check for SEI metadata
    sei_data = extract_sei_metadata(video_path)
    
    if sei_data and sei_data.startswith(b'ZKSTEGO3'):
        return "v3.0"
    elif has_embedded_data(video_path):
        return "v2.0"  # Old format (no SEI)
    else:
        return "unknown"
```

### Deployment Strategy
1. **Week 12**: Release v3.0-beta (branch: `upgrade-v3`)
2. **Week 13-14**: Beta testing với test videos
3. **Week 15**: Merge vào `main`, tag `v3.0.0`
4. **Week 16**: Documentation update & tutorial

---

## ✅ SUCCESS CRITERIA

### Must Have (P0)
- [ ] LDPC recovery rate ≥ 99% với 10% bit errors
- [ ] PSNR ≥ 47 dB
- [ ] Bitstream valid với FFmpeg/x264/JM decoders
- [ ] Backward compatible reader cho v2.0 videos

### Should Have (P1)
- [ ] Context-aware embedding giảm artifacts 50%
- [ ] RC4 entropy ≥ 7.9
- [ ] Temporal interleaving với frame drop tolerance

### Nice to Have (P2)
- [ ] GPU acceleration cho DWT
- [ ] Adaptive LDPC rate (0.4 - 0.6)
- [ ] Real-time processing (< 0.5s/frame)

---

## 📞 CONTACT & SUPPORT

**Project Lead:** ZK Video Stego Team  
**Version:** 3.0 Roadmap  
**Last Updated:** February 4, 2026

**Next Review:** End of Week 3 (Giai đoạn 1 completion)

---

## 🎯 QUICK START CHECKLIST

- [ ] Tạo branch mới: `git checkout -b upgrade-v3`
- [ ] Setup môi trường: `pip install pywavelets opencv-python`
- [ ] Đọc papers về DWT-DCT hybrid
- [ ] Bắt đầu với `yuv_converter.py`
- [ ] Tạo test videos cho validation
- [ ] Weekly progress reviews

**LET'S BUILD v3.0! 🚀**
