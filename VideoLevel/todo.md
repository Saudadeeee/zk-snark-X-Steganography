# TODO - Phase 0: Quan sát & Trích xuất Motion Vector

## Mục tiêu Phase 0
Làm quen với Motion Vector trong video H.264, quan sát đặc tính, và xây dựng công cụ trích xuất MV để phục vụ các phase tiếp theo.

---

## 1. Chuẩn bị môi trường & công cụ

### 1.1 Cài đặt công cụ cần thiết
- [ ] Cài đặt FFmpeg (với H.264 support)
- [ ] Cài đặt x264 encoder
- [ ] Cài đặt JM reference encoder (H.264/AVC reference software)
- [ ] Cài đặt Python 3.x + các thư viện cần thiết:
  - [ ] `numpy`, `opencv-python`, `matplotlib`
  - [ ] `av` (PyAV) hoặc `ffmpeg-python` cho parsing bitstream
  - [ ] `pillow` cho visualization

### 1.2 Chuẩn bị dataset test
- [ ] Tải/tạo video mẫu test (3-5 video):
  - [ ] Video tĩnh (static scene) - 5-10s
  - [ ] Video motion nhẹ (slow pan/zoom) - 5-10s
  - [ ] Video motion mạnh (fast action, camera shake) - 5-10s
- [ ] Encode các video về cùng format chuẩn:
  - Codec: H.264/AVC
  - Resolution: 1280x720 hoặc 1920x1080
  - GOP structure: IPPP... (GOP size = 30)
  - Bitrate: constant (ví dụ 2Mbps)
  - Profile: Main/High

### 1.3 Tạo cấu trúc thư mục dự án
```
VideoLevel/
├── data/
│   ├── raw/          # Video gốc
│   ├── encoded/      # Video đã encode chuẩn
│   └── output/       # Kết quả trích xuất
├── tools/
│   ├── mv_extractor/ # Code trích xuất MV
│   ├── visualizer/   # Code visualization
│   └── analyzer/     # Code phân tích thống kê
├── results/
│   ├── mv_data/      # MV data exported
│   ├── visualizations/ # Hình ảnh overlay
│   └── stats/        # Thống kê phân tích
└── docs/
    └── phase0_report.md
```
- [ ] Tạo cấu trúc thư mục

---

## 2. Quan sát Motion Vector Overlay

### 2.1 Sử dụng FFmpeg để visualize MV
- [ ] Tìm hiểu FFmpeg filter `codecview` để hiển thị MV
- [ ] Chạy lệnh export video với MV overlay:
```bash
ffmpeg -flags2 +export_mvs -i input.mp4 -vf codecview=mv=pf+bf+bb output_mv_overlay.mp4
```
- [ ] Quan sát và ghi chú:
  - [ ] Hướng và độ lớn của MV trong các vùng khác nhau
  - [ ] Sự khác biệt giữa P-frame và B-frame
  - [ ] MV trong vùng tĩnh vs vùng động
  - [ ] Pattern của skip blocks (MV=0)

### 2.2 Export MV data thô
- [ ] Sử dụng FFmpeg export MV ra file:
```bash
ffmpeg -flags2 +export_mvs -i input.mp4 -f rawvideo -pix_fmt yuv420p -an /dev/null 2>&1 | grep -A5 "motion_vector"
```
- [ ] Hoặc viết script Python sử dụng PyAV để extract MV
- [ ] Lưu MV data dưới format dễ đọc (CSV/JSON):
  - Frame index
  - Macroblock position (x, y)
  - MV components (mvx, mvy)
  - Block type (inter, intra, skip)
  - Partition size

---

## 3. Xây dựng MV Extractor

### 3.1 Implement MV Parser (Python)
- [ ] Tạo file `tools/mv_extractor/parser.py`:
  - [ ] Function `parse_h264_bitstream(video_path)`
  - [ ] Class `MVData` để lưu trữ structured data
  - [ ] Parse từng frame, phân loại I/P/B frame
  - [ ] Extract MV của P-frames (ưu tiên)
  - [ ] Extract MVD (Motion Vector Difference) nếu có thể

### 3.2 Data structure cho MV
```python
class MVData:
    frame_idx: int
    frame_type: str  # I, P, B
    mb_x: int
    mb_y: int
    mvx: int
    mvy: int
    mvd_x: int  # MVD if available
    mvd_y: int
    block_type: str  # inter_16x16, inter_8x8, skip, intra
    partition: str
```
- [ ] Implement class MVData
- [ ] Implement export/import JSON/CSV

### 3.3 Test MV Extractor
- [ ] Test với 3 video mẫu
- [ ] Verify số lượng P-frames extracted
- [ ] Verify MV range hợp lý (không có giá trị bất thường)
- [ ] Đếm số lượng blocks theo type (inter, intra, skip)

---

## 4. Phân tích đặc tính Motion Vector

### 4.1 Thống kê cơ bản
- [ ] Viết script `tools/analyzer/statistics.py`:
  - [ ] Phân phối MV magnitude: `sqrt(mvx^2 + mvy^2)`
  - [ ] Histogram mvx, mvy (phân bố giá trị)
  - [ ] Tỷ lệ MV=0 (skip/static blocks)
  - [ ] Tỷ lệ các loại block type
  - [ ] MVD distribution (nếu trích được)

### 4.2 Phân tích parity (chẵn/lẻ)
- [ ] Phân phối parity của mvx: `mvx % 2`
- [ ] Phân phối parity của mvy: `mvy % 2`
- [ ] Phân phối parity của mvd_x, mvd_y
- [ ] **Mục đích**: kiểm tra xem có bias tự nhiên không (cần cho steganography)
- [ ] Tính entropy của parity bits

### 4.3 Phân tích correlation
- [ ] Correlation giữa các MV liền kề trong không gian (spatial)
- [ ] Correlation giữa các MV theo thời gian (temporal)
- [ ] Phân tích temporal stability: MV thay đổi như thế nào qua các frame

### 4.4 Visualize phân tích
- [ ] Vẽ histogram MV magnitude
- [ ] Vẽ scatter plot (mvx vs mvy)
- [ ] Vẽ heatmap tỷ lệ MV=0 theo vùng không gian
- [ ] Vẽ temporal plot: MV activity theo thời gian
- [ ] Lưu tất cả plots vào `results/visualizations/`

---

## 5. Đánh giá khả năng embedding

### 5.1 Ước lượng capacity
- [ ] Tính số P-frames trong 1 giây video (với GOP=30)
- [ ] Tính số macroblocks có MV≠0 per P-frame (trung bình)
- [ ] Ước lượng capacity nếu embed 1 bit/MV component:
  - Công thức: `capacity = num_P_frames * num_inter_blocks * bits_per_block`
- [ ] Ước lượng capacity với embedding rate thấp (sparse embedding: 10%, 25%, 50%)

### 5.2 Phân tích vùng an toàn cho embedding
- [ ] Xác định vùng có motion activity cao (dễ nhúng, khó phát hiện)
- [ ] Xác định vùng tĩnh (MV≈0, nên tránh)
- [ ] Đề xuất tiêu chí lọc block:
  - [ ] `abs(mvx) > threshold` hoặc `abs(mvy) > threshold`
  - [ ] Block type = inter (không phải skip, không phải intra)
  - [ ] Partition size ưu tiên (16x16 hoặc 8x8)

### 5.3 Test thử sửa MV (dry run)
- [ ] Chọn ngẫu nhiên 10 MV từ P-frames
- [ ] Simulate thay đổi parity: `mvx_new = mvx + 1` hoặc `mvx - 1`
- [ ] Ghi chú: giá trị MV mới có hợp lý không?
- [ ] **Chưa encode**, chỉ phân tích tính khả thi

---

## 6. Nghiên cứu H.264 bitstream structure

### 6.1 Đọc tài liệu H.264/AVC standard
- [ ] Đọc ITU-T H.264 spec (hoặc tài liệu rút gọn):
  - [ ] Slice structure
  - [ ] Macroblock structure
  - [ ] Motion Vector Prediction (MVP)
  - [ ] Motion Vector Difference (MVD = MV - MVP)
  - [ ] CABAC/CAVLC encoding của MVD

### 6.2 Phân tích bitstream mẫu
- [ ] Sử dụng công cụ parse bitstream (ví dụ: `h264_analyze` hoặc JM decoder debug mode)
- [ ] Quan sát syntax elements:
  - [ ] NAL unit types
  - [ ] Slice header
  - [ ] MB prediction mode
  - [ ] MVD values (mvd_lx[][][])
- [ ] Ghi chú vị trí MVD trong bitstream

### 6.3 Xác định điểm can thiệp trong encoder
- [ ] Tải source code JM reference encoder
- [ ] Hoặc tải source code x264
- [ ] Tìm module:
  - [ ] Motion estimation (ME)
  - [ ] Motion vector prediction (MVP calculation)
  - [ ] MVD calculation: `MVD = MV - MVP`
  - [ ] Entropy encoding của MVD (CABAC/CAVLC)
- [ ] Đánh dấu các hàm cần can thiệp trong Phase 1

---

## 7. Tài liệu & Báo cáo Phase 0

### 7.1 Viết báo cáo `docs/phase0_report.md`
- [ ] Tóm tắt mục tiêu Phase 0
- [ ] Dataset đã sử dụng
- [ ] Kết quả quan sát MV overlay (có ảnh minh họa)
- [ ] Thống kê MV:
  - Phân phối magnitude, parity
  - Correlation spatial/temporal
- [ ] Ước lượng capacity embedding
- [ ] Đề xuất tiêu chí chọn block cho embedding
- [ ] Kết luận: Phase 0 đạt được gì, bài học kinh nghiệm
- [ ] Đề xuất cho Phase 1

### 7.2 Chuẩn bị checklist cho Phase 1
- [ ] Liệt kê các prerequisite từ Phase 0
- [ ] Xác định encoder nào sẽ dùng (JM hay x264)
- [ ] Đề xuất kỹ thuật embedding đầu tiên sẽ test (parity hoặc QIM)

---

## 8. Deliverables Phase 0

### Checklist cuối cùng
- [ ] ✅ Đã trích xuất được MV từ ít nhất 3 video
- [ ] ✅ Đã visualize MV overlay
- [ ] ✅ Đã tính được các thống kê cơ bản (magnitude, parity, correlation)
- [ ] ✅ Đã ước lượng được capacity embedding
- [ ] ✅ Đã nghiên cứu H.264 bitstream structure và MVD
- [ ] ✅ Đã xác định được điểm can thiệp trong encoder (JM hoặc x264)
- [ ] ✅ Đã viết báo cáo Phase 0
- [ ] ✅ Đã có kế hoạch rõ ràng cho Phase 1

---

## Tham khảo

### Công cụ
- FFmpeg: https://ffmpeg.org/
- x264: https://www.videolan.org/developers/x264.html
- JM Reference Software: https://iphome.hhi.de/suehring/tml/
- PyAV: https://pyav.org/

### Tài liệu
- ITU-T H.264 Recommendation
- "The H.264 Advanced Video Compression Standard" (Iain Richardson)
- Paper: "Video Steganography using Motion Vectors" (tìm trên Google Scholar)

### Code examples
- FFmpeg motion vector extraction examples
- x264/JM source code documentation

---

**Ước lượng thời gian hoàn thành Phase 0**: Tùy thuộc vào kinh nghiệm, khoảng 1-2 tuần làm việc.

**Next**: Phase 1 - Nhúng thử vào MV trong encoder (payload nhỏ)
