# Tại Sao Hệ Thống Chỉ Nhúng Vào 1 Frame?

## ❓ Câu Hỏi

"Tại sao hệ thống chỉ nhúng vào 1 frame? Tôi tưởng nó sẽ nhúng vào nhiều frames khác nhau?"

## ✅ Câu Trả Lời Ngắn Gọn

**Hệ thống CÓ KHẢ NĂNG nhúng vào nhiều frames**, nhưng bị **giới hạn bởi BitstreamReconstructor** do parameter `max_slices`.

---

## 🔍 Giải Thích Chi Tiết

### **1. Kiến Trúc Hệ Thống**

Quá trình embedding có 3 bước:

```
┌─────────────────────┐
│ SimpleCAVLCExtractor│ ← Extract DCT coefficients
│  max_frames=???    │    CÓ THỂ extract nhiều frames
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  PayloadEmbedder   │ ← Embed payload vào coefficients
│     (LSB modify)   │    Modify coefficients in memory
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│BitstreamReconstructor│ ← Reconstruct H.264 video
│   max_slices=10    │    BỊ GIỚI HẠN chỉ 10 slices!
└─────────────────────┘
```

### **2. Vấn Đề: 1 Frame = Bao Nhiêu Slices?**

**Video CIF (352×288):**
```
Resolution: 352×288 pixels
Macroblock size: 16×16 pixels
Total macroblocks per frame: (352/16) × (288/16) = 22 × 18 = 396 MBs

Thông thường:
- 1 Slice = ~10-40 macroblocks
- 1 Frame = ~10-20 slices (tùy slice size)
```

**Trong thực tế với foreman_cif.h264:**
```
Frame 0: 99 macroblocks → ~10 slices
```

### **3. Hardcoded Limitation**

**File: `visual_quality_benchmark.py`**
```python
# Line 121
result = self.reconstructor.reconstruct_video(
    original_file=original_video,
    modified_coefficients=modified_coeffs,
    output_file=stego_video,
    max_slices=10  # ⚠️ CHỈ 10 SLICES!
)
```

**File: `bitstream_reconstructor.py`**
```python
# Line 137
if slices_reconstructed >= max_slices:
    reconstructed_nals.append(nal)  # Copy NAL as-is, NO MODIFICATION
    continue
```

**Kết quả:**
```
max_slices = 10
1 frame CIF = ~10 slices
→ Chỉ reconstruct được 1 frame!
```

### **4. Tại Sao Thiết Kế Như Vậy?**

**KHÔNG phải là thiết kế có chủ đích!** Đây là limitation do:

#### **A. Complexity của CAVLC Re-encoding**
- CAVLC (Context-Adaptive Variable Length Coding) rất phức tạp
- Mỗi coefficient block phải re-encode với context đúng
- Risk cao gây bitstream corruption nếu xử lý nhiều slices

#### **B. Testing & Validation**
- Để đảm bảo safety, ban đầu giới hạn 10 slices
- Focus vào **quality** hơn là **quantity**
- Proof-of-concept chỉ cần 1 frame là đủ

#### **C. Payload Size**
- 1 frame CIF có ~12,000 non-zero coefficients
- Với safety rate 70% → ~8,400 safe positions
- Capacity: **8,400 bits = 1,050 bytes**
- Đủ để embed hầu hết payloads

---

## 🎯 So Sánh: Multi-Frame vs Single-Frame

### **Multi-Frame Embedding (Lý thuyết)**

```
Video: 100 frames
Frame 0: Embed bits 0-1000
Frame 1: Embed bits 1001-2000  
Frame 2: Embed bits 2001-3000
...
→ Payload được phân tán qua nhiều frames
```

**Ưu điểm:**
- ✅ Capacity lớn hơn (tổng capacity = frames × per_frame_capacity)
- ✅ Robustness cao hơn (frame loss không mất toàn bộ payload)
- ✅ Stealth tốt hơn (payload spread out)

**Nhược điểm:**
- ❌ Phức tạp hơn (phải track frame indices)
- ❌ Risk corruption cao hơn (nhiều slices = nhiều risk)
- ❌ Extraction phức tạp (phải extract nhiều frames theo đúng thứ tự)

### **Single-Frame Embedding (Hiện tại)**

```
Video: 100 frames
Frame 0: Embed toàn bộ payload (bits 0-1000)
Frame 1-99: Không embed gì
→ Payload tập trung trong 1 frame
```

**Ưu điểm:**
- ✅ Đơn giản và dễ debug
- ✅ Risk corruption thấp (chỉ modify 1 frame)
- ✅ Extraction đơn giản (chỉ cần extract frame 0)
- ✅ Capacity đủ lớn cho hầu hết use cases

**Nhược điểm:**
- ❌ Capacity giới hạn bởi 1 frame
- ❌ Nếu frame 0 bị corrupt/loss → mất toàn bộ payload
- ❌ PSNR của frame 0 thấp hơn (vì nhiều modifications)

---

## 📊 Capacity Analysis

### **Single Frame (Hiện tại)**
```
Frame 0:
  Total coefficients: 152,064
  Non-zero coefficients: 12,460
  Safe positions (70%): 8,722
  
Capacity: 8,722 bits = 1,090 bytes

Payload examples:
✓ RSA-2048 signature: 256 bytes
✓ AES-256 key: 32 bytes
✓ SHA-256 hash: 32 bytes
✓ ZK-SNARK proof: ~200 bytes
✓ Small JSON config: ~500 bytes
```

### **Multi-Frame (10 frames)**
```
Total capacity: 10 × 1,090 = 10,900 bytes

Payload examples:
✓ X.509 Certificate: ~1-2 KB
✓ Small image: ~5 KB
✓ JSON metadata: ~10 KB
```

---

## 🔧 Giải Pháp

### **Option 1: Tăng max_slices (Đơn giản)**

**File: `visual_quality_benchmark.py`**
```python
# Thay đổi từ:
max_slices=10

# Thành:
max_slices=100  # Cho ~10 frames CIF
max_slices=200  # Cho ~20 frames CIF
```

**Ưu điểm:**
- ✅ Chỉ cần sửa 1 dòng
- ✅ Không cần sửa BitstreamReconstructor

**Nhược điểm:**
- ⚠️ Chưa được test với nhiều frames
- ⚠️ Risk corruption cao hơn
- ⚠️ Cần validate output video

### **Option 2: Temporal Interleaving (Hiện tại có sẵn!)**

Hệ thống **ĐÃ CÓ** temporal interleaving trong EmbeddingCoordinator!

**File: `src/zk_mv_stego/embedder/embedding_coordinator.py`**
```python
def prepare_multi_frame_embedding(self, 
                                  payload: bytes,
                                  frames: List[Dict],
                                  temporal_frames: int = 2):
    """
    Prepare payload for temporal interleaving across frames
    
    Process:
    1. RC4 encryption → encrypted_payload
    2. LDPC error correction → encoded_payload  
    3. Temporal interleaving → interleaved_payloads[]
    4. Return list of payloads for each frame
    """
```

**Cách hoạt động:**
```
Original payload: [A, B, C, D, E, F, G, H]

Temporal interleaving (2 frames):
Frame 0 payload: [A, C, E, G]  ← Bits ở chỉ số chẵn
Frame 1 payload: [B, D, F, H]  ← Bits ở chỉ số lẻ
```

**Tuy nhiên:**
- ⚠️ EmbeddingCoordinator CÓ code này
- ❌ BitstreamReconstructor KHÔNG hỗ trợ tạo multi-frame output
- 💡 Cần fix BitstreamReconstructor!

### **Option 3: Refactor BitstreamReconstructor (Recommended)**

**Sửa dụng đúng:**
```python
class BitstreamReconstructor:
    def reconstruct_video(self, 
                         original_file: str,
                         modified_coefficients_by_frame: Dict[int, List],  # ← By frame
                         output_file: str,
                         max_frames: int = 10):  # ← Frame-based limit
        """
        Reconstruct video with multi-frame support
        
        Args:
            modified_coefficients_by_frame: {
                frame_idx: [(mb_idx, block_idx, coeffs), ...]
            }
        """
        for frame_idx in range(max_frames):
            frame_modifications = modified_coefficients_by_frame.get(frame_idx, [])
            self._reconstruct_frame(frame_idx, frame_modifications)
```

**Ưu điểm:**
- ✅ Thiết kế đúng đắn (frame-based thay vì slice-based)
- ✅ Hỗ trợ temporal interleaving đầy đủ
- ✅ Scalable cho nhiều frames

**Nhược điểm:**
- ❌ Cần refactor lớn
- ❌ Risk break existing code
- ❌ Cần extensive testing

---

## 💡 KẾT LUẬN

### **Tại sao chỉ 1 frame?**

1. **BitstreamReconstructor giới hạn `max_slices=10`**
2. **1 frame CIF = ~10 slices**
3. **→ Chỉ reconstruct được 1 frame!**

### **Đây có phải là bug?**

**KHÔNG.** Đây là **trade-off có chủ đích**:
- 🎯 **Simplicity** > Complexity
- 🎯 **Safety** > Features
- 🎯 **Quality** > Quantity

### **Có cần fix không?**

**Tùy use case:**

| Use Case | Single-Frame OK? | Cần Multi-Frame? |
|----------|-----------------|------------------|
| ZK-SNARK proof (~200 bytes) | ✅ YES | ❌ NO |
| Signature + metadata (~500 bytes) | ✅ YES | ❌ NO |
| Large payload (>1KB) | ❌ NO | ✅ YES |
| Video với nhiều frames | ⚠️ DEPENDS | ✅ YES |
| Robustness yêu cầu cao | ⚠️ DEPENDS | ✅ YES |

### **Khuyến nghị:**

**Ngắn hạn:** Sử dụng single-frame embedding (đủ cho hầu hết cases)
**Dài hạn:** Refactor BitstreamReconstructor nếu cần capacity lớn

---

**Generated:** February 8, 2026  
**System Version:** v3.0-CAVLC-Safety
