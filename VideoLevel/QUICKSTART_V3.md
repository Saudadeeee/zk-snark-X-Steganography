# Quick Start Guide - v3.0 Upgrade

## 🚀 Getting Started (Current Status)

**Branch:** `upgrade-v3`  
**Status:** Phase 1 skeleton ready  
**Current Week:** Week 1 (YUV Converter implementation)

### Prerequisites
```bash
# Python 3.8+
python --version

# Node.js (for ZK-SNARK circuits)
node --version

# Git
git --version
```

### Setup Development Environment

```bash
# 1. Ensure you're on upgrade-v3 branch
git checkout upgrade-v3

# 2. Install Python dependencies
pip install numpy opencv-python scikit-image scipy pytest matplotlib

# 3. Install Node.js dependencies (for circuits)
cd circuits
npm install
cd ..

# 4. Verify setup
python -c "import numpy, cv2; print('✅ Dependencies OK')"
```

### Project Structure (v3.0)
```
VideoLevel/
├── ROADMAP_UPGRADE.md          # 📋 Complete upgrade plan
├── TODO_V3.md                  # ✅ Weekly checklist
├── requirements.txt            # 📦 Python dependencies
├── src/zk_mv_stego/
│   ├── preprocessing/          # 🆕 Phase 1 (YUV+DWT)
│   │   ├── yuv_converter.py    # Week 1
│   │   ├── dwt_analyzer.py     # Week 2
│   │   └── hybrid_selector.py  # Week 3
│   ├── ecc/                    # 🆕 Phase 3 (LDPC)
│   │   ├── ldpc_codec.py       # Week 7-8
│   │   └── temporal_interleaver.py  # Week 9
│   ├── crypto/                 # Updated in Phase 2
│   │   └── rc4_cipher.py       # 🆕 Week 4
│   ├── embedder/               # Updated in Phase 2
│   │   └── context_analyzer.py # 🆕 Week 5
│   └── bitstream/              # Updated in Phase 4
```

### Current Development Tasks (Week 1)

#### Day 1-2: Research & Setup ✅
- [x] Read ROADMAP_UPGRADE.md
- [x] Read TODO_V3.md
- [ ] Read ITU-T H.264 Section 6.2
- [ ] Setup test videos

#### Day 3-4: YUV Converter Implementation
- [ ] Implement `_rgb_to_yuv()` method
- [ ] Implement `_yuv_to_rgb()` method
- [ ] Implement `extract_yuv_from_frame()`
- [ ] Implement `get_luma_channel()`
- [ ] Implement `reconstruct_from_yuv()`

#### Day 5: Testing & Validation
- [ ] Create `tests/test_yuv_converter.py`
- [ ] Test with 5 sample videos
- [ ] Benchmark conversion time
- [ ] Commit Week 1 completion

### How to Contribute

1. **Pick a task from TODO_V3.md**
2. **Implement the stubbed method**
3. **Write unit tests**
4. **Update TODO_V3.md** (check off completed items)
5. **Commit with descriptive message**

Example:
```bash
# After implementing yuv_converter.py
git add src/zk_mv_stego/preprocessing/yuv_converter.py tests/test_yuv_converter.py
git commit -m "feat: Implement YUV converter with ITU-T BT.601

- Add RGB to YUV conversion with matrix multiplication
- Implement 4:2:0 chroma subsampling
- Add bilinear upsampling for reconstruction
- Unit tests with 95% coverage
- Benchmark: 0.05s per 720p frame"
```

### Testing Strategy

```bash
# Run all tests
pytest tests/

# Run specific module tests
pytest tests/test_yuv_converter.py -v

# Run with coverage
pytest --cov=src/zk_mv_stego tests/

# Run Phase 1 tests only
pytest tests/test_yuv_converter.py tests/test_dwt_analyzer.py tests/test_hybrid_selector.py
```

### Documentation

- **ROADMAP_UPGRADE.md**: Full technical roadmap (4 phases, 12 weeks)
- **TODO_V3.md**: Detailed daily checklist
- **README.md**: General project documentation
- **README_VI.md**: Vietnamese documentation

### Weekly Progress Reviews

**Schedule:**
- End of Week 1 (Feb 11): YUV Converter review
- End of Week 3 (Feb 25): Phase 1 complete (Milestone 1)
- End of Week 6 (Mar 18): Phase 2 complete (Milestone 2)
- End of Week 9 (Apr 8): Phase 3 complete (Milestone 3)
- End of Week 12 (Apr 29): v3.0 Beta release (Milestone 4)

### Getting Help

1. Check **ROADMAP_UPGRADE.md** for technical details
2. Check **TODO_V3.md** for current tasks
3. Review referenced papers in ROADMAP
4. Check existing v2.0 code for patterns

### Next Steps

1. ✅ Read ROADMAP and TODO completely
2. ⏳ Start Week 1 tasks (YUV Converter)
3. ⏳ Setup test environment
4. ⏳ First commit by end of Week 1

---

**Last Updated:** 2026-02-04  
**Current Focus:** Phase 1 - Week 1 - YUV Converter  
**Next Milestone:** End of Week 3 (Phase 1 complete)

🚀 **Let's build v3.0!**
