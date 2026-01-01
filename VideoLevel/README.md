# ZK-SNARK Video Steganography - Video Level

Hệ thống nhúng bằng chứng zk-SNARK vào Motion Vector của video H.264/H.265

## Phase 0: Quan sát & Trích xuất Motion Vector

### Mục tiêu
- Làm quen với Motion Vector trong video H.264
- Trích xuất và phân tích đặc tính MV
- Đánh giá khả năng embedding (capacity)
- Chuẩn bị cho Phase 1 (embedding implementation)

---

## Cài đặt

### 1. Yêu cầu hệ thống
- Python 3.7+
- FFmpeg (với H.264 support)

### 2. Cài đặt FFmpeg

**Windows:**
```bash
# Tải FFmpeg từ https://ffmpeg.org/download.html
# Thêm FFmpeg vào PATH
```

**Linux/macOS:**
```bash
# Ubuntu/Debian
sudo apt-get install ffmpeg

# macOS
brew install ffmpeg
```

### 3. Cài đặt Python dependencies

```bash
cd VideoLevel
pip install -r requirements.txt
```

---

## Cấu trúc thư mục

```
VideoLevel/
├── data/
│   ├── raw/          # Video gốc
│   ├── encoded/      # Video đã encode chuẩn
│   └── output/       # Output tạm
├── tools/
│   ├── mv_extractor/ # Trích xuất MV
│   ├── visualizer/   # Visualization
│   └── analyzer/     # Phân tích thống kê
├── results/
│   ├── mv_data/      # MV data (JSON/CSV)
│   ├── visualizations/ # Hình ảnh
│   └── stats/        # Thống kê
├── phase0_demo.py    # Script demo chính
├── requirements.txt  # Python dependencies
└── README.md         # File này
```

---

## Sử dụng

### Quick Start

```bash
# Chạy pipeline hoàn chỉnh với 1 lệnh
python phase0_demo.py path/to/video.mp4
```

Ví dụ:
```bash
python phase0_demo.py ../TestVideo/sample.mp4
```

Pipeline sẽ tự động:
1. ✅ Trích xuất Motion Vectors
2. ✅ Tạo visualization (overlay video, plots, heatmaps)
3. ✅ Tính toán thống kê (magnitude, parity, correlation, capacity)
4. ✅ Tạo báo cáo Phase 0

### Sử dụng từng module riêng lẻ

#### 1. Trích xuất Motion Vectors

```bash
python tools/mv_extractor/parser.py input.mp4 output_mv.json
```

#### 2. Tạo visualization

```bash
python tools/visualizer/mv_visualizer.py input.mp4 ./results/visualizations/
```

#### 3. Phân tích thống kê

```bash
python tools/analyzer/statistics.py results/mv_data/video_mv.json results/stats/
```

---

## Output

Sau khi chạy `phase0_demo.py`, bạn sẽ có:

### 📊 MV Data
- `results/mv_data/{video_name}_mv.json` - MV data dạng JSON
- `results/mv_data/{video_name}_mv.csv` - MV data dạng CSV

### 📈 Visualizations
- `results/visualizations/{video_name}_mv_overlay.mp4` - Video với MV overlay
- `results/visualizations/{video_name}_mv_arrows.png` - MV arrows plot
- `results/visualizations/{video_name}_magnitude_heatmap.png` - Magnitude heatmap
- `results/visualizations/{video_name}_temporal.png` - Temporal MV activity

### 📉 Statistics
- `results/stats/{video_name}_statistics.json` - Thống kê chi tiết
- `results/stats/magnitude_histogram.png` - Magnitude distribution
- `results/stats/mv_scatter.png` - MVx vs MVy scatter plot
- `results/stats/parity_distribution.png` - Parity analysis (quan trọng cho LSB embedding)
- `results/stats/magnitude_by_frame_type.png` - P-frame vs B-frame

### 📄 Report
- `results/phase0_report.txt` - Báo cáo tổng kết Phase 0

---

## Hiểu kết quả

### Motion Vector Statistics

**Magnitude Distribution:**
- **Small (<5 pixels)**: MV nhỏ, vùng tĩnh - tránh embed
- **Medium (5-15 pixels)**: MV vừa - **khuyến nghị embed**
- **Large (>15 pixels)**: MV lớn, motion mạnh - có thể embed

**Parity Analysis:**
- Tỷ lệ Even/Odd gần 50/50 → ✅ Tốt cho LSB embedding
- Entropy cao (~1.0) → ✅ Khó phát hiện statistical attack
- Tỷ lệ lệch nhiều → ⚠️ Cần adaptive embedding

**Capacity Estimates:**
- **All P-MVs**: Tổng capacity tối đa (không khuyến nghị)
- **Safe MVs**: Chỉ MV có magnitude >= 5 (khuyến nghị)
- **Sparse 10%-50%**: Embedding thưa → an toàn hơn, khó phát hiện hơn

---

## Lưu ý quan trọng

### Demo Mode
⚠️ **Phase 0 hiện chạy ở Demo Mode** với synthetic MV data để demonstration.

Để sử dụng trong production:
1. Implement actual H.264 bitstream parser
2. Có thể dùng PyAV hoặc modified FFmpeg
3. Hoặc parse trực tiếp bitstream với JM reference decoder

### Khuyến nghị

**Cho steganography:**
- Chỉ embed vào P-frames (không embed I-frames, B-frames tùy chọn)
- Ưu tiên MV có magnitude >= 5
- Sử dụng sparse embedding (10-25%) để tăng security
- Kiểm tra parity distribution trước khi chọn LSB scheme

**Video test tốt:**
- Video có motion activity vừa phải
- Tránh video quá tĩnh (ít MV)
- Tránh video quá nhanh (MV không ổn định)
- GOP structure đều đặn (IPPP...)

---

## Tiếp theo: Phase 1

Sau khi hoàn thành Phase 0, bạn sẽ có:
- ✅ Hiểu rõ đặc tính MV của video
- ✅ Biết capacity embedding tiềm năng
- ✅ Đã chọn được embedding strategy (LSB parity hoặc QIM)

**Phase 1** sẽ implement:
1. Patch x264 hoặc JM encoder
2. Embed payload vào MV
3. Test embedding quality (PSNR, bitrate)
4. Verify extraction accuracy

---

## Troubleshooting

### FFmpeg not found
```bash
# Kiểm tra FFmpeg đã cài đúng
ffmpeg -version

# Nếu không có, cài lại hoặc thêm vào PATH
```

### No motion vectors extracted
- Kiểm tra video file có đúng format H.264 không
- Thử encode lại video với x264:
```bash
ffmpeg -i input.mp4 -c:v libx264 -preset medium -crf 23 output.mp4
```

### Import errors
```bash
# Cài lại dependencies
pip install -r requirements.txt

# Hoặc cài manual
pip install numpy matplotlib
```

---

## Liên hệ & Đóng góp

Nếu gặp vấn đề hoặc có câu hỏi, vui lòng:
1. Kiểm tra file `instruction.md` để hiểu rõ yêu cầu
2. Xem lại `todo.md` để theo dõi tiến độ
3. Đọc Phase 0 report sau khi chạy demo

---

## License

Dự án này phục vụ mục đích nghiên cứu và giáo dục.

**Good luck with Phase 0! 🚀**
