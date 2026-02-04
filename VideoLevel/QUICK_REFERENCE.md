# Quick Reference - Current Project State

**Last Updated**: Week 4 Complete  
**Branch**: `upgrade-v3`  
**Status**: Phase 1 Complete, Starting Phase 2

---

## ✅ What's Complete

### Phase 1: Preprocessing (Weeks 1-4)

```
RGB → YUV → DWT → Hybrid Selection → RC4 Encryption
       ↓      ↓         ↓                  ↓
    18K MB/s 26K MB/s 16K MB/s         1.2 MB/s
```

**Components**:
1. **YUV Converter** (`src/zk_mv_stego/preprocessing/yuv_converter.py`)
   - ITU-T BT.601 conversion
   - 4:2:0 chroma subsampling
   - 11/11 tests passing

2. **DWT Analyzer** (`src/zk_mv_stego/preprocessing/dwt_analyzer.py`)
   - 2-level Haar wavelet
   - Energy map + region classification
   - 16/16 tests passing

3. **Hybrid Selector** (`src/zk_mv_stego/preprocessing/hybrid_selector.py`)
   - DCT-DWT coefficient selection
   - 6 selection rules
   - 20/20 tests passing

4. **RC4 Cipher** (`src/zk_mv_stego/crypto/rc4_cipher.py`)
   - KSA + PRGA implementation
   - Entropy measurement
   - 24/24 tests passing

**Integration**: 14/14 tests passing, 3,326 MB/sec throughput

---

## 🔄 Next Steps - Week 5: Context Analyzer

### Goal
Add texture and motion analysis to improve coefficient selection quality.

### Implementation Plan

**File to Create**: `src/zk_mv_stego/preprocessing/context_analyzer.py`

**Class Structure**:
```python
class ContextAnalyzer:
    def analyze_texture(self, macroblock: np.ndarray) -> float:
        """Compute texture complexity (Laplacian variance)"""
        
    def extract_motion_vectors(self, h264_data) -> Dict:
        """Parse motion vectors from H.264 bitstream"""
        
    def compute_context_score(self, texture: float, motion: float) -> float:
        """Combine texture + motion into single score"""
        
    def get_embedding_suitability(self, mb_index: int) -> float:
        """Score for hybrid selector integration"""
```

**Integration Point**:
Modify `hybrid_selector.py`:
```python
# Current
context_score = 1.0  # Fixed value

# After Week 5
context_score = context_analyzer.get_embedding_suitability(mb_index)
```

**Expected Deliverables**:
- Implementation: ~400 LOC
- Unit tests: ~350 LOC (18 tests)
- Demo script: ~300 LOC
- Progress report

---

## 📊 Current Performance

| Component | Throughput | Bottleneck? |
|-----------|------------|-------------|
| YUV Converter | 18,191 MB/sec | No |
| DWT Analyzer | 25,742 MB/sec | No |
| Hybrid Selector | 16,000 MB/sec | No |
| RC4 Cipher | 1.2 MB/sec | No (small payload) |
| **Full Pipeline** | **3,326 MB/sec** | ✅ Acceptable |

**Real-world**:
- 720p: 1.08s/frame (0.9 fps)
- 1080p: 2.44s/frame (0.4 fps)

---

## 🧪 Test Status

```bash
pytest tests/ -v
```

**Result**: 85/85 passing (100%)

**Breakdown**:
- YUV: 11 tests
- DWT: 16 tests
- Hybrid: 20 tests
- RC4: 24 tests
- Integration: 14 tests

---

## 📁 Key Files

### Implementation
```
src/zk_mv_stego/
├── preprocessing/
│   ├── yuv_converter.py      (230 LOC) ✅
│   ├── dwt_analyzer.py       (390 LOC) ✅
│   ├── hybrid_selector.py    (336 LOC) ✅
│   └── context_analyzer.py   (TBD - Week 5)
├── crypto/
│   └── rc4_cipher.py         (239 LOC) ✅
```

### Tests
```
tests/
├── test_yuv_converter.py     (220 LOC) ✅
├── test_dwt_analyzer.py      (450 LOC) ✅
├── test_hybrid_selector.py   (480 LOC) ✅
├── test_rc4_cipher.py        (348 LOC) ✅
├── test_integration.py       (330 LOC) ✅
└── test_context_analyzer.py  (TBD - Week 5)
```

### Documentation
```
PROGRESS_WEEK1.md  ✅
PROGRESS_WEEK2.md  ✅
PROGRESS_WEEK3.md  ✅
PROGRESS_WEEK4.md  ✅
PROGRESS_OVERALL.md ✅
TODO_V3.md         (roadmap)
```

---

## 🚀 How to Run

### Quick Test
```bash
# Run all tests
python -m pytest tests/ -v

# Run specific component
python -m pytest tests/test_rc4_cipher.py -v

# Run with coverage
python -m pytest tests/ --cov=src/zk_mv_stego
```

### Performance Benchmark
```bash
# Individual components
python examples/demo_yuv_converter.py
python examples/demo_dwt_analyzer.py
python examples/demo_hybrid_selector.py
python examples/demo_rc4_cipher.py

# Integration pipeline
python examples/demo_integration.py
```

### Full Pipeline Example
```python
from src.zk_mv_stego.preprocessing import (
    YUVConverter, HaarDWTAnalyzer, HybridCoefficientSelector
)
from src.zk_mv_stego.crypto import RC4Cipher

# Load RGB frame
rgb_frame = load_frame('video.mp4', frame_idx=0)

# 1. Convert to YUV
yuv_converter = YUVConverter()
yuv_data = yuv_converter.extract_yuv_from_frame(rgb_frame)

# 2. DWT analysis
dwt_analyzer = HaarDWTAnalyzer()
dwt_results = dwt_analyzer.analyze_macroblock(yuv_data['Y'], level=2)

# 3. Select coefficients
selector = HybridCoefficientSelector()
selected = selector.select_coefficients([dwt_results])

# 4. Encrypt ZK proof
zk_proof = b'\x00' * 192  # Placeholder
rc4_key = RC4Cipher.generate_key(16)
cipher = RC4Cipher(rc4_key)
encrypted_proof = cipher.encrypt(zk_proof)

# 5. Embed (Week 6+)
# embedder.embed_payload(encrypted_proof, selected)
```

---

## 🛠️ Common Commands

### Git Workflow
```bash
# Check status
git status

# View commits
git log --oneline

# Current branch
git branch

# Diff
git diff
```

### Testing
```bash
# Fast test (no benchmarks)
pytest tests/ -v -k "not benchmark"

# With output
pytest tests/ -v -s

# Stop on first failure
pytest tests/ -v -x
```

### Performance
```bash
# Profile code
python -m cProfile -s cumtime examples/demo_integration.py

# Memory usage
python -m memory_profiler examples/demo_integration.py
```

---

## 📋 Checklist for Week 5

### Day 1-2: Texture Analysis
- [ ] Create `context_analyzer.py`
- [ ] Implement Laplacian variance calculation
- [ ] Implement local standard deviation
- [ ] Add complexity scoring
- [ ] Write 6 unit tests

### Day 3-4: Motion Analysis
- [ ] Parse H.264 motion vectors (if available)
- [ ] Compute motion magnitude
- [ ] Identify high-motion regions
- [ ] Write 6 unit tests

### Day 5-6: Integration
- [ ] Combine texture + motion scores
- [ ] Update `hybrid_selector.py` to use context scores
- [ ] Add Rules 7-8 (context-based)
- [ ] Write 6 integration tests

### Day 7: Documentation
- [ ] Create `demo_context_analyzer.py`
- [ ] Write `PROGRESS_WEEK5.md`
- [ ] Update `PROGRESS_OVERALL.md`
- [ ] Commit and push

---

## 💡 Tips for Week 5

### Texture Analysis
Use Laplacian operator for edge detection:
```python
laplacian = cv2.Laplacian(macroblock, cv2.CV_64F)
variance = laplacian.var()  # High variance = textured
```

### Motion Vectors
If H.264 motion vectors not available, use optical flow:
```python
flow = cv2.calcOpticalFlowFarneback(prev_frame, curr_frame, ...)
magnitude = np.sqrt(flow[..., 0]**2 + flow[..., 1]**2)
```

### Context Score Formula
```python
context_score = (
    0.6 * texture_score +  # Texture weight
    0.4 * motion_score     # Motion weight
)
```

### Integration
Update selection rules:
- **Rule 7**: Prefer high-texture regions (variance > threshold)
- **Rule 8**: Avoid low-motion regions (magnitude < threshold)

---

## 🎯 Success Criteria

Week 5 is complete when:
- [x] `context_analyzer.py` implemented (~400 LOC)
- [x] 18 unit tests passing
- [x] Hybrid selector uses context scores
- [x] Demo shows texture/motion visualization
- [x] Progress report written
- [x] All 103 tests passing (85 + 18)

---

## 📞 Quick Help

**Can't find a file?**
```bash
find . -name "*.py" -path "*/preprocessing/*"
```

**Import error?**
```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

**Test failing?**
```bash
pytest tests/test_X.py::TestClass::test_method -v -s
```

**Performance regression?**
```bash
python -m pytest tests/ -v --benchmark-only
```

---

**Last Command Run**: `git commit -m "docs: Add comprehensive overall progress report"`  
**Next Task**: Implement Context Analyzer (Week 5)  
**Estimated Time**: 7 days
