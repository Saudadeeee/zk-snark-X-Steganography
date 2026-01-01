# TODO - Phase 1: MV Embedding Implementation

**Mục tiêu:** Implement embedding payload vào Motion Vector Difference (MVD) trong H.264 encoder

**Prerequisites:** Phase 0 completed ✓

---

## Overview Phase 1

Phase 1 tập trung vào việc modify H.264 encoder để nhúng payload vào MVD. Sử dụng LSB parity embedding với chaos-based carrier selection.

**Deliverables:**
1. Modified JM encoder với embedding capability
2. Extractor tool để trích payload từ bitstream
3. Test với payload nhỏ (100-500 bytes)
4. Quality metrics (PSNR, SSIM, bitrate)
5. Phase 1 report

**Timeline:** 3-4 tuần

---

## Milestone 1.1: JM Encoder Setup & Build

### 1.1.1 Download JM Reference Software
- [ ] Download JM từ official source:
  - URL: https://iphome.hhi.de/suehring/tml/
  - Hoặc: https://github.com/Distrotech/JM (unofficial mirror)
  - Version khuyến nghị: JM 19.0 hoặc mới nhất
- [ ] Extract vào thư mục: `VideoLevel/external/JM/`
- [ ] Đọc README và INSTALL documentation

### 1.1.2 Build JM Encoder (Windows)

**Option A: Visual Studio**
- [ ] Cài Visual Studio 2019/2022 (Community Edition)
- [ ] Open JM solution file: `JM/vc10.sln`
- [ ] Build configuration: Release x64
- [ ] Build project: `lencod` (encoder)
- [ ] Verify executable: `JM/bin/lencod.exe`

**Option B: MinGW/MSYS2**
- [ ] Cài MSYS2
- [ ] Install gcc: `pacman -S mingw-w64-x86_64-gcc`
- [ ] Modify Makefile nếu cần
- [ ] Build: `make`
- [ ] Test: `./lencod.exe -h`

### 1.1.3 Test JM Encoder
- [ ] Tạo encoder config file: `encoder.cfg`
  ```cfg
  InputFile                = "../data/raw/foreman_cif.yuv"
  InputHeaderLength        = 0
  FramesToBeEncoded        = 100
  FrameRate                = 30.0
  SourceWidth              = 352
  SourceHeight             = 288
  OutputFile               = "test_jm.264"
  ReconFile                = "test_rec.yuv"
  ```
- [ ] Convert YUV from Y4M nếu cần:
  ```bash
  ffmpeg -i foreman_cif.y4m -pix_fmt yuv420p foreman_cif.yuv
  ```
- [ ] Chạy encoder: `lencod -d encoder.cfg`
- [ ] Verify output: kiểm tra `test_jm.264` được tạo
- [ ] Decode test: `ffmpeg -i test_jm.264 -f yuv4mpegpipe output.y4m`
- [ ] So sánh PSNR với baseline

---

## Milestone 1.2: Code Exploration & Documentation

### 1.2.1 Hiểu JM Code Structure
- [ ] Đọc overview documentation trong `JM/doc/`
- [ ] Xem code structure:
  ```
  JM/lencod/src/
  ├── lencod.c          # Main encoder entry
  ├── mv-search.c       # Motion estimation
  ├── rdopt.c           # RD optimization
  ├── macroblock.c      # MB processing
  ├── vlc.c             # VLC entropy coding
  └── cabac.c           # CABAC entropy coding
  ```

### 1.2.2 Trace Motion Vector Flow
- [ ] Tìm function: `MotionEstimation()`
  - Input: current MB, reference frames
  - Output: Best MV (mvx, mvy)
- [ ] Tìm function: `SetMotionVectorPredictor()`
  - Tính MVP từ neighboring blocks
- [ ] Tìm MVD calculation:
  ```c
  mvd_x = mv_x - mvp_x;
  mvd_y = mv_y - mvp_y;
  ```
- [ ] Tìm entropy encoding:
  - CAVLC: `writeMVD()` hoặc tương tự
  - CABAC: `biari_encode_symbol()` cho MVD

### 1.2.3 Identify Insertion Points
- [ ] Document call stack:
  ```
  encode_one_frame()
    └── encode_one_macroblock()
          └── RDCost_for_macroblocks()
                ├── MotionEstimation() → best MV
                ├── SetMotionVectorPredictor() → MVP
                ├── Compute MVD = MV - MVP
                └── writeMVD() → entropy encode
  ```
- [ ] Xác định điểm tốt nhất để modify MVD:
  - [ ] Sau ME, sau khi tính MVD
  - [ ] Trước entropy encoding
  - [ ] Trong RD loop (nếu cần RD-aware embedding)

### 1.2.4 Create Modification Plan
- [ ] Viết document: `docs/jm_modification_plan.md`
  - Functions cần modify
  - Data structures cần thêm
  - Config parameters cần thêm
  - Build process changes

---

## Milestone 1.3: Basic Parity Embedding (No Payload)

### 1.3.1 Add Steganography Module
- [ ] Tạo file mới: `JM/lencod/src/stego.c`
- [ ] Tạo header: `JM/lencod/inc/stego.h`
- [ ] Define basic structures:
  ```c
  typedef struct {
      int enabled;           // Enable/disable stego
      int flip_pattern;      // Test pattern: 0=all_0, 1=all_1, 2=alternate
      int modify_count;      // Counter for debugging
  } StegoConfig;
  ```

### 1.3.2 Implement MVD Modification
- [ ] Implement function:
  ```c
  void modify_mvd_parity(int *mvd_x, int *mvd_y, int target_bit) {
      // Modify mvd_x to have parity = target_bit
      if ((*mvd_x & 1) != target_bit) {
          // Choose +1 or -1 for minimum distortion
          *mvd_x += (*mvd_x > 0) ? 1 : -1;
      }
  }
  ```
- [ ] Add call site in ME/RD module:
  ```c
  // After MVD calculation
  if (stego_config.enabled) {
      int test_bit = (mb_index % 2); // Alternating pattern
      modify_mvd_parity(&mvd_x, &mvd_y, test_bit);
      stego_config.modify_count++;
  }
  ```

### 1.3.3 Add Config Parameters
- [ ] Thêm vào `encoder.cfg`:
  ```cfg
  # Steganography settings
  EnableStego              = 1     # 0=off, 1=on
  StegoTestPattern         = 2     # 0=all_0, 1=all_1, 2=alternate
  ```
- [ ] Parse config trong `lencod.c`
- [ ] Pass config vào encoding functions

### 1.3.4 Test Basic Embedding
- [ ] Build modified JM
- [ ] Encode với `EnableStego=1, StegoTestPattern=2`
- [ ] Verify:
  - [ ] Encoder runs successfully
  - [ ] Output video playable
  - [ ] Log shows MVD modifications happening
- [ ] Extract MVDs từ output bitstream
- [ ] Verify parity pattern matches test pattern

---

## Milestone 1.4: Chaos-based Carrier Selection

### 1.4.1 Implement Chaos Map
- [ ] Implement Logistic Map PRNG:
  ```c
  typedef struct {
      double x;           // State [0, 1]
      double r;           // Parameter (3.9 for chaotic)
      uint64_t seed;      // Initial seed
  } ChaosMap;

  void chaos_init(ChaosMap *map, uint64_t seed) {
      map->seed = seed;
      map->r = 3.9;
      // Normalize seed to [0,1]
      map->x = (double)(seed % 100000) / 100000.0;
  }

  double chaos_next(ChaosMap *map) {
      map->x = map->r * map->x * (1.0 - map->x);
      return map->x;
  }

  int chaos_next_int(ChaosMap *map, int max) {
      return (int)(chaos_next(map) * max);
  }
  ```

### 1.4.2 Implement Carrier Selection
- [ ] Add structure:
  ```c
  typedef struct {
      int frame_idx;
      int mb_x;
      int mb_y;
      int component;      // 0=x, 1=y
  } CarrierBlock;
  ```
- [ ] Implement selection function:
  ```c
  int should_embed(ChaosMap *map, int frame_idx, int mb_x, int mb_y, int mv_magnitude) {
      // Filter 1: Only safe MVs (magnitude >= 5)
      if (mv_magnitude < 5) return 0;

      // Filter 2: Chaos-based sparse selection (25%)
      double rand_val = chaos_next(map);
      return (rand_val < 0.25);
  }
  ```

### 1.4.3 Integrate Selection Logic
- [ ] Modify embedding call site:
  ```c
  if (stego_config.enabled) {
      int mv_mag = sqrt(mvx*mvx + mvy*mvy);

      if (should_embed(&chaos_map, frame_idx, mb_x, mb_y, mv_mag)) {
          int payload_bit = get_next_payload_bit();
          modify_mvd_parity(&mvd_x, &mvd_y, payload_bit);
      }
  }
  ```
- [ ] Add key/seed config:
  ```cfg
  StegoKey                 = "MySecretKey123"
  StegoSeed                = 0x1234567890ABCDEF
  StegoSparseRate          = 0.25
  ```

---

## Milestone 1.5: Payload Management

### 1.5.1 Design Payload Structure
- [ ] Define header:
  ```c
  typedef struct {
      uint8_t magic[6];       // "ZKSTEG"
      uint8_t version;        // 0x01
      uint16_t payload_len;   // Length in bytes
      uint8_t chunk_size;     // Fixed chunk size
      uint16_t ecc_k;         // Reed-Solomon k parameter
      uint8_t nonce[16];      // Random nonce
      uint8_t salt[16];       // Random salt
      uint8_t reserved[20];   // Future use
  } StegoHeader; // Total: 64 bytes
  ```

### 1.5.2 Implement Payload Loading
- [ ] Function to load payload file:
  ```c
  int load_payload(const char *filename, uint8_t **data, size_t *len) {
      FILE *f = fopen(filename, "rb");
      fseek(f, 0, SEEK_END);
      *len = ftell(f);
      *data = malloc(*len);
      fseek(f, 0, SEEK_SET);
      fread(*data, 1, *len, f);
      fclose(f);
      return 0;
  }
  ```

### 1.5.3 Implement Bit Stream
- [ ] Serialize payload to bit stream:
  ```c
  typedef struct {
      uint8_t *data;
      size_t byte_pos;
      int bit_pos;
      size_t total_bits;
  } BitStream;

  int bitstream_next_bit(BitStream *bs) {
      if (bs->byte_pos * 8 + bs->bit_pos >= bs->total_bits)
          return -1; // End of stream

      int bit = (bs->data[bs->byte_pos] >> (7 - bs->bit_pos)) & 1;
      bs->bit_pos++;
      if (bs->bit_pos == 8) {
          bs->bit_pos = 0;
          bs->byte_pos++;
      }
      return bit;
  }
  ```

### 1.5.4 Integrate Payload Embedding
- [ ] Initialize payload at encoder start:
  ```c
  // In lencod.c main()
  if (stego_config.enabled) {
      load_payload(stego_config.payload_file, &payload_data, &payload_len);
      bitstream_init(&payload_stream, payload_data, payload_len);
  }
  ```
- [ ] Get bits during encoding:
  ```c
  int get_next_payload_bit() {
      return bitstream_next_bit(&payload_stream);
  }
  ```

---

## Milestone 1.6: Extractor Implementation

### 1.6.1 Create Extractor Tool
- [ ] Tạo: `VideoLevel/tools/extractor/mvd_extractor.py`
- [ ] Parse H.264 bitstream để extract MVDs
- [ ] Options:
  - Use FFmpeg với patch
  - Use H.264 bitstream parser library
  - Decode với JM decoder và log MVDs

### 1.6.2 Implement MVD Parser
- [ ] Parse P-frames only
- [ ] Extract MVD for each MB:
  ```python
  class MVDExtractor:
      def extract_mvds(self, h264_file):
          mvds = []
          # Parse bitstream
          for frame in parse_frames(h264_file):
              if frame.type == 'P':
                  for mb in frame.macroblocks:
                      mvds.append({
                          'frame': frame.index,
                          'mb_x': mb.x,
                          'mb_y': mb.y,
                          'mvd_x': mb.mvd_x,
                          'mvd_y': mb.mvd_y
                      })
          return mvds
  ```

### 1.6.3 Implement Payload Extraction
- [ ] Reconstruct carrier selection:
  ```python
  def extract_payload(mvds, key, seed):
      chaos = ChaosMap(seed)
      bits = []

      for mvd in mvds:
          mag = math.sqrt(mvd['mvd_x']**2 + mvd['mvd_y']**2)

          if should_embed(chaos, mvd['frame'], mvd['mb_x'], mvd['mb_y'], mag):
              # Extract LSB parity
              bit = mvd['mvd_x'] & 1
              bits.append(bit)

      # Convert bits to bytes
      payload = bits_to_bytes(bits)
      return payload
  ```

### 1.6.4 Test Extraction
- [ ] Embed known payload (e.g., "Hello World")
- [ ] Extract từ encoded bitstream
- [ ] Verify extracted = original
- [ ] Test với different keys/seeds

---

## Milestone 1.7: Quality & Performance Metrics

### 1.7.1 Implement Quality Measurement
- [ ] Script: `tools/metrics/quality_metrics.py`
- [ ] Measure PSNR:
  ```python
  def compute_psnr(original_yuv, encoded_yuv):
      # Load YUV files
      # Compute MSE
      # PSNR = 10 * log10(255^2 / MSE)
  ```
- [ ] Measure SSIM (sử dụng opencv hoặc scikit-image)
- [ ] Optional: VMAF (sử dụng libvmaf)

### 1.7.2 Compare with Baseline
- [ ] Encode cùng video với stego OFF
- [ ] Encode với stego ON
- [ ] Compare:
  ```
  Metric          | Baseline | With Stego | Delta
  ----------------+----------+------------+-------
  PSNR (dB)       | 42.5     | 42.3       | -0.2
  SSIM            | 0.975    | 0.973      | -0.002
  Bitrate (kbps)  | 513      | 518        | +5 (1%)
  Encode time (s) | 3.2      | 3.4        | +0.2 (6%)
  ```

### 1.7.3 Test Multiple Videos
- [ ] Test với 3 videos: foreman, akiyo, bus
- [ ] Test với different payload sizes: 100B, 500B, 1KB
- [ ] Test với different sparse rates: 10%, 25%, 50%
- [ ] Record metrics trong spreadsheet

---

## Milestone 1.8: Robustness Testing (Optional for Phase 1)

### 1.8.1 Test Re-encode Robustness
- [ ] Encode với stego + payload
- [ ] Re-encode với FFmpeg:
  ```bash
  ffmpeg -i stego.mp4 -c:v libx264 -crf 23 reencoded.mp4
  ```
- [ ] Extract payload từ reencoded
- [ ] Measure Bit Error Rate (BER)
- [ ] Note: High BER expected without ECC → cần Phase 2

### 1.8.2 Test GOP/Bitrate Changes
- [ ] Re-encode với different GOP: 15, 60
- [ ] Re-encode với different bitrate: 256k, 1M
- [ ] Measure extraction accuracy

---

## Milestone 1.9: Documentation & Reporting

### 1.9.1 Code Documentation
- [ ] Add comments trong modified JM code
- [ ] Document functions trong `stego.h`
- [ ] Create README: `JM/README_STEGANOGRAPHY.md`

### 1.9.2 Usage Guide
- [ ] Write: `docs/phase1_usage_guide.md`
  - How to build modified JM
  - How to configure embedding
  - How to extract payload
  - Troubleshooting

### 1.9.3 Phase 1 Report
- [ ] Write: `docs/phase1_report.md`
  - Summary of implementation
  - Quality metrics results
  - Extraction accuracy
  - Challenges encountered
  - Lessons learned
  - Recommendations for Phase 2

---

## Deliverables Checklist

### Code
- [ ] Modified JM encoder với embedding capability
- [ ] Extractor tool (Python)
- [ ] Test scripts
- [ ] Config files

### Data
- [ ] Test videos với embedded payload
- [ ] Quality metrics spreadsheet
- [ ] Extraction accuracy results

### Documentation
- [ ] JM modification plan
- [ ] Usage guide
- [ ] Phase 1 report
- [ ] Code comments

---

## Phase 1 Success Criteria

### Must Have (P0)
- [ ] JM encoder modified successfully
- [ ] Basic parity embedding works
- [ ] Can embed & extract 100 bytes with 100% accuracy (no re-encode)
- [ ] PSNR > 40 dB
- [ ] Bitrate increase < 5%

### Should Have (P1)
- [ ] Chaos-based carrier selection works
- [ ] Can embed 500 bytes
- [ ] SSIM > 0.95
- [ ] Extraction works from different encoders (FFmpeg vs JM)

### Nice to Have (P2)
- [ ] Multiple video tests passed
- [ ] Sparse rate configurable
- [ ] Re-encode BER measured
- [ ] x264 exploration started

---

## Risk & Mitigation

### Risk 1: JM Build Issues
**Risk:** Không build được JM trên Windows
**Mitigation:**
- Dùng pre-built binary nếu có
- Dùng Linux VM hoặc WSL
- Dùng Docker container với build environment

### Risk 2: Code Complexity
**Risk:** JM code quá phức tạp, khó modify
**Mitigation:**
- Start simple: chỉ modify 1 function
- Extensive logging để debug
- Tham khảo JM documentation và papers

### Risk 3: Quality Degradation
**Risk:** Embedding làm giảm PSNR quá nhiều
**Mitigation:**
- RD-aware embedding (chọn +1 hoặc -1 based on RD cost)
- Reduce sparse rate
- Only embed trong large motion regions

### Risk 4: Extraction Failure
**Risk:** Không extract được payload
**Mitigation:**
- Extensive logging ở cả embedder và extractor
- Test với simple known pattern trước
- Verify carrier selection logic match exactly

---

## Timeline & Milestones

```
Week 1: Setup & Exploration
├── Day 1-2: Download, build, test JM
├── Day 3-4: Code exploration, trace MV flow
└── Day 5-7: Document insertion points, modification plan

Week 2: Basic Embedding
├── Day 8-10: Add stego module, implement parity embedding
├── Day 11-12: Test basic embedding, verify modifications
└── Day 13-14: Implement chaos carrier selection

Week 3: Payload & Extraction
├── Day 15-16: Payload structure, loading, bitstream
├── Day 17-18: Integrate payload embedding
├── Day 19-20: Implement extractor tool
└── Day 21: Test full pipeline

Week 4: Testing & Documentation
├── Day 22-23: Quality metrics, multiple videos
├── Day 24-25: Robustness testing (optional)
├── Day 26-27: Documentation, usage guide
└── Day 28: Phase 1 report, demo

Total: 28 days (~4 weeks)
```

---

## Next Steps After Phase 1

Once Phase 1 completed:
1. ✓ Basic embedding works
2. → Phase 2: Add ECC (Reed-Solomon) for robustness
3. → Phase 2: Encryption (ChaCha20-Poly1305)
4. → Phase 2: Chunking for large payloads
5. → Phase 3: ZK-SNARK integration
6. → Phase 4: Security hardening, steganalysis testing

---

## References

**JM Reference Software:**
- JM Documentation: `JM/doc/`
- H.264 Standard: ITU-T H.264 / ISO/IEC 14496-10

**Papers:**
- "Video Steganography using Motion Vectors" - tìm trên Google Scholar
- "LSB Matching Revisited" - Mielikainen, 2006
- "Chaos-based Steganography" - various authors

**Tools:**
- H.264 bitstream analyzer: https://github.com/shi-yan/H264Naked
- FFmpeg source code (libavcodec/h264*)

---

**Start Date:** TBD
**Target Completion:** 4 weeks from start
**Status:** READY TO START

**Previous:** [PHASE0_COMPLETED.md](PHASE0_COMPLETED.md)
**Next:** Phase 2 planning (after Phase 1 completion)