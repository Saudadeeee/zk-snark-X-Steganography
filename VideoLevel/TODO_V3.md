# TODO CHECKLIST - UPGRADE V3.0

**Ngày bắt đầu:** 4 tháng 2, 2026  
**Sprint hiện tại:** Giai đoạn 1 - Week 1

---

## 🎯 GIAI ĐOẠN 1: YUV + DWT (Tuần 1-3)

### Week 1: YUV Converter
- [x] **Day 1-2**: Setup & Research ✅ (2025-01-15)
  - [x] Đọc ITU-T H.264 Section 6.2 (Color space) ✅
  - [x] Nghiên cứu YUV 4:2:0 subsampling ✅
  - [x] Setup test environment với sample videos ✅
  
- [x] **Day 3-4**: Implementation ✅ (2025-01-15)
  - [x] Tạo file `src/zk_mv_stego/preprocessing/__init__.py` ✅
  - [x] Implement `yuv_converter.py`: ✅
    - [x] `extract_yuv_from_frame()` method ✅
    - [x] `get_luma_channel()` method ✅
    - [x] `reconstruct_from_yuv()` method ✅
  - [x] Unit tests cho YUV conversion ✅
  - [x] All tests passing (11/11) ✅
  - [x] Performance optimization (vectorized upsampling) ✅
  
- [ ] **Day 5**: Validation
  - [ ] Test với 5 sample videos
  - [ ] Verify Y/Cb/Cr channels riêng biệt
  - [ ] Benchmark conversion time

**Week 1 Results**: 
- Performance: Luma 1.06ms/frame (945 fps), Full YUV 1.88ms (533 fps)
- Accuracy: MAE 1.37, 99.6% pixels error <10
- Code: 230 lines (yuv_converter.py), 270 lines (tests), 150 lines (demo)
- Git commit: 7623e22

### Week 2: DWT Analyzer
- [x] **Day 1-2**: Haar DWT Research ✅ (2025-02-04)
  - [x] Đọc paper "DWT-DCT-SVD Based Steganography" ✅
  - [x] Understand LL, LH, HL, HH sub-bands ✅
  - [x] Mathematical verification của Haar transform ✅
  
- [x] **Day 3-5**: Implementation ✅ (2025-02-04)
  - [x] Implement `dwt_analyzer.py`: ✅
    - [x] `analyze_macroblock()` method ✅
    - [x] `compute_energy_map()` method ✅
    - [x] `classify_frequency_region()` method ✅
    - [x] 2-level Haar DWT decomposition ✅
    - [x] Inverse DWT reconstruction ✅
  - [x] Unit tests cho DWT analysis (16/16 passing) ✅
  - [x] Demo script with visualization ✅
  
- [ ] **Day 6-7**: Integration
  - [ ] Integrate với existing H.264 parser
  - [ ] Create frequency maps cho test videos
  - [ ] Visualize DWT sub-bands (debugging)

**Week 2 Results**: 
- Performance: 0.462ms per 16x16 MB (2,164 MB/sec)
- Reconstruction: MAE <1e-6 (perfect)
- Tests: 16/16 passing
- Code: 390 lines (dwt_analyzer.py), 277 lines (tests), 223 lines (demo)
- Git commits: 98638f2, 07df7b2
  - [ ] Integrate với existing H.264 parser
  - [ ] Create frequency maps cho test videos
  - [ ] Visualize DWT sub-bands (debugging)

### Week 3: Hybrid Selector
- [ ] **Day 1-2**: Selection Strategy Design
  - [ ] Define stability scoring algorithm
  - [ ] Create decision rules (reference ROADMAP)
  - [ ] Design test cases
  
- [ ] **Day 3-5**: Implementation
  - [ ] Implement `hybrid_selector.py`:
    - [ ] `should_use_coefficient()` function
    - [ ] `compute_stability_score()` method
    - [ ] Integration với DWT + DCT
  
- [ ] **Day 6-7**: Testing & Benchmark
  - [ ] Compare với v2.0 selection
  - [ ] Measure stability improvement (target: +30%)
  - [ ] Update `payload_embedder.py` để sử dụng hybrid selector
  
- [ ] **End of Week 3**: Deliverables Check
  - [ ] 3 new files completed (~530 lines)
  - [ ] All unit tests passing
  - [ ] Benchmark report generated
  - [ ] Code review & merge to `upgrade-v3` branch

---

## 🔐 GIAI ĐOẠN 2: RC4 + CONTEXT-AWARE (Tuần 4-6)

### Week 4: RC4 Cipher
- [ ] **Day 1**: RC4 Algorithm Study
  - [ ] Understand KSA (Key Scheduling Algorithm)
  - [ ] Understand PRGA (Pseudo-Random Generation)
  - [ ] Security considerations cho steganography
  
- [ ] **Day 2-3**: Implementation
  - [ ] Tạo file `src/zk_mv_stego/crypto/rc4_cipher.py`
  - [ ] Implement RC4 core algorithm
  - [ ] Add entropy measurement function
  
- [ ] **Day 4-5**: Testing
  - [ ] Test với ZK Proof data (192 bytes)
  - [ ] Verify entropy > 7.9
  - [ ] Performance benchmark
  
- [ ] **Day 6-7**: Integration
  - [ ] Integrate vào embedding workflow
  - [ ] Update `embed_complete.py`
  - [ ] End-to-end test

### Week 5: Context Analyzer
- [ ] **Day 1-2**: Texture Analysis Research
  - [ ] Study Laplacian variance method
  - [ ] Study motion vector extraction từ H.264
  - [ ] Read paper "Context-Aware Steganography"
  
- [ ] **Day 3-5**: Implementation
  - [ ] Implement `context_analyzer.py`:
    - [ ] `compute_texture_score()` method
    - [ ] `compute_motion_score()` method
    - [ ] `create_attention_map()` method
  
- [ ] **Day 6-7**: Validation
  - [ ] Test với videos có different complexity
  - [ ] Visualize attention maps
  - [ ] Verify high-texture regions selected

### Week 6: Integration & Testing
- [ ] **Day 1-3**: Full Integration
  - [ ] Update `payload_embedder.py`:
    - [ ] Add RC4 pre-encryption step
    - [ ] Add context-aware selection
    - [ ] Combine với hybrid selector từ Phase 1
  
- [ ] **Day 4-5**: Testing
  - [ ] End-to-end embedding tests
  - [ ] Measure visual quality improvement
  - [ ] Steganalysis resistance tests
  
- [ ] **Day 6-7**: Deliverables & Review
  - [ ] 2 new files (~370 lines)
  - [ ] Integration tests passing
  - [ ] Visual artifacts benchmark (target: -50%)
  - [ ] Code review & documentation

---

## 🛡️ GIAI ĐOẠN 3: LDPC + INTERLEAVING (Tuần 7-9)

### Week 7: LDPC Encoder
- [ ] **Day 1-2**: LDPC Theory
  - [ ] Study Belief Propagation algorithm
  - [ ] Read "LDPC Codes for Steganography" paper
  - [ ] Understand Progressive Edge-Growth (PEG)
  
- [ ] **Day 3-5**: Implementation
  - [ ] Tạo file `src/zk_mv_stego/ecc/ldpc_codec.py`
  - [ ] Implement parity-check matrix generation (PEG)
  - [ ] Implement LDPC encoder
  
- [ ] **Day 6-7**: Testing
  - [ ] Test encoding với 192-byte ZK Proof
  - [ ] Verify output = 384 bytes (rate 1/2)
  - [ ] Unit tests cho encoder

### Week 8: Temporal Interleaver ✅ COMPLETE
- [x] **Day 1-2**: Interleaving Strategy Design
  - [x] Design recurrent strategy (hash-based frame dependency)
  - [x] Define frame dependency logic (cumulative hashing)
  - [x] Security analysis (prevents partial extraction)
  
- [x] **Day 3-5**: Implementation
  - [x] Implement `temporal_interleaver.py` (340 LOC):
    - [x] `interleave()` method - Split and permute
    - [x] `deinterleave()` method - Reconstruct with missing tolerance
    - [x] `compute_frame_dependency()` method - Hash-based MB positioning
    - [x] `get_frame_chain()` - Full dependency chain
    - [x] `create_frame_manifest()` - Distribution metadata
  
- [x] **Day 6-7**: Testing & Deliverables
  - [x] Test with frame drops (30% loss handled)
  - [x] End-to-end with LDPC (integration verified)
  - [x] 32 comprehensive tests (100% passing)
  - [x] Demo with 6 scenarios
  - [x] Performance: <1ms per operation
  - [x] Overall: 207/210 tests passing (98.6%)

### Week 9: Adaptive Quantization
- [ ] **Day 1-2**: Quantization Strategy Design
  - [ ] Study H.264 quantization parameters
  - [ ] Design adaptive rate control
  - [ ] Define quality-capacity tradeoff
  
- [ ] **Day 3-5**: Implementation
  - [ ] Implement `adaptive_quantizer.py`:
    - [ ] `compute_qp()` method - Context-aware QP selection
    - [ ] `adjust_embedding_rate()` - Variable bits per coefficient
    - [ ] `estimate_capacity()` - Frame-level capacity prediction
  
- [ ] **Day 6-7**: Testing & Deliverables
  - [ ] Test with various video types
  - [ ] Measure PSNR impact
  - [ ] End-to-end with temporal interleaver
  - [ ] All Phase 3 deliverables completed
  - [ ] Accuracy benchmark (target: 100%)

---

## 🔧 GIAI ĐOẠN 4: SEI + CAVLC FIX (Tuần 10-12)

### Week 10: SEI Metadata
- [ ] **Day 1-2**: SEI Design
  - [ ] Design SEI payload structure
  - [ ] Define UUID và version scheme
  - [ ] Compression strategy cho stable_map
  
- [ ] **Day 3-5**: Implementation
  - [ ] Update `sei_handler.py`:
    - [ ] `SEIMetadata` class
    - [ ] `serialize()` method
    - [ ] `deserialize()` method
  - [ ] Add CRC32 checksum
  
- [ ] **Day 6-7**: Testing
  - [ ] Test SEI insertion/extraction
  - [ ] Verify SEI survives decoding
  - [ ] Test với FFmpeg decoder

### Week 11: CAVLC Drift Fix
- [ ] **Day 1-2**: Analysis
  - [ ] Analyze bitstream drift scenarios
  - [ ] Study emulation_prevention_three_byte
  - [ ] Design compensation strategy
  
- [ ] **Day 3-5**: Implementation
  - [ ] Update `cavlc_encoder.py`:
    - [ ] `compensate_bitstream_drift()` function
    - [ ] `verify_bitstream_integrity()` function
  - [ ] Add stuffing bits logic
  
- [ ] **Day 6-7**: Validation
  - [ ] Test với FFmpeg
  - [ ] Test với x264
  - [ ] Test với JM reference decoder
  - [ ] All 3 decoders must pass

### Week 12: Final Integration & Testing
- [ ] **Day 1-2**: Full Integration
  - [ ] Integrate all 4 phases
  - [ ] Update `embed_complete.py` CLI
  - [ ] Update `zk_snark_workflow.py`
  
- [ ] **Day 3-4**: Comprehensive Testing
  - [ ] Run full test suite (`test_upgrade_v3.py`)
  - [ ] End-to-end workflow tests
  - [ ] Performance benchmarks
  - [ ] Comparison với v2.0
  
- [ ] **Day 5-6**: Documentation
  - [ ] Update README.md
  - [ ] Write migration guide
  - [ ] API documentation
  - [ ] Tutorial examples
  
- [ ] **Day 7**: Release Preparation
  - [ ] Code review final
  - [ ] Tag v3.0.0-beta
  - [ ] Announcement draft
  - [ ] Deploy to test environment

---

## 📊 WEEKLY PROGRESS TRACKING

### Week 1 Status: ⬜ Not Started
- YUV Converter: ⬜
- Unit Tests: ⬜
- Benchmark: ⬜

### Week 2 Status: ⬜ Not Started
- DWT Analyzer: ⬜
- Integration: ⬜
- Visualization: ⬜

### Week 3 Status: ⬜ Not Started
- Hybrid Selector: ⬜
- Testing: ⬜
- Deliverables: ⬜

---

## 🎯 MILESTONES

- [ ] **Milestone 1**: Giai đoạn 1 Complete (End of Week 3)
  - Target: 3 new files, +30% stability
  
- [ ] **Milestone 2**: Giai đoạn 2 Complete (End of Week 6)
  - Target: RC4 + Context-Aware working, -50% artifacts
  
- [ ] **Milestone 3**: Giai đoạn 3 Complete (End of Week 9)
  - Target: LDPC 100% recovery @ 10% errors
  
- [ ] **Milestone 4**: v3.0 Beta Release (End of Week 12)
  - Target: All features complete, all tests passing

---

## 📝 NOTES & DECISIONS

### Design Decisions
- **2026-02-04**: Chọn Haar DWT (thay vì Daubechies) vì simplicity và speed
- **2026-02-04**: LDPC rate 1/2 (có thể adaptive trong future)
- **2026-02-04**: Temporal interleaving với n=10 frames default

### Risks & Mitigations
- **Risk**: LDPC implementation phức tạp → **Mitigation**: Sử dụng existing library (pyldpc) nếu cần
- **Risk**: DWT overhead làm chậm processing → **Mitigation**: GPU acceleration (nice-to-have)
- **Risk**: SEI metadata bị strip bởi encoders → **Mitigation**: Test với multiple encoders

### Resources Needed
- Test videos: 10-20 H.264 videos với varying complexity
- Papers: Access to IEEE/ACM papers (có sẵn references)
- Hardware: GPU for DWT testing (optional)

---

**LAST UPDATED:** 2026-02-04  
**NEXT REVIEW:** End of Week 1 (2026-02-11)
