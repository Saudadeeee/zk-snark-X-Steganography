# Network Performance Benchmark - Tóm tắt

## Tổng quan

Script `network_benchmark.py` đánh giá hiệu năng mạng khi truyền ảnh gốc so với ảnh stego qua WiFi, sử dụng Wireshark/tshark để capture và phân tích traffic.

## Các metrics được đo

### 1. File Metrics
- **File Size**: Kích thước file (bytes, KB)
- **Size Difference**: Chênh lệch giữa stego và original

### 2. Network Metrics
- **Total Packets**: Tổng số packet truyền đi
- **Total Bytes**: Tổng số bytes truyền đi
- **TCP Packets/Bytes**: Số packet/bytes ở layer TCP
- **HTTP Packets/Bytes**: Số packet/bytes ở layer HTTP

### 3. Performance Metrics
- **Throughput**: Băng thông (Mbps)
- **Transfer Time**: Thời gian truyền (giây)
- **Packets per Second**: Số packet mỗi giây
- **Average Packet Size**: Kích thước packet trung bình
- **Max/Min Packet Size**: Kích thước packet lớn nhất/nhỏ nhất

### 4. Statistical Metrics
- **Mean ± Standard Deviation**: Giá trị trung bình và độ lệch chuẩn qua các iterations
- **Trend Analysis**: Xu hướng performance qua các lần test

## Output Files

### 1. JSON Results
File JSON chứa:
- Tất cả metrics chi tiết
- Raw data từ mỗi iteration
- Statistical analysis
- Comparison data

### 2. Comparison Plot (PNG)
Biểu đồ cột so sánh 6 metrics chính:
- File Size
- Total Packets
- Throughput
- Transfer Time
- Average Packet Size
- Total Bytes

### 3. Trend Plot (PNG)
Biểu đồ đường thể hiện xu hướng qua các iterations:
- Throughput trends
- Transfer Time trends
- Packet count trends
- Byte count trends

### 4. Console Table
Bảng so sánh in ra console với tất cả metrics và differences

## Sử dụng

### Basic
```bash
python scripts/network_benchmark.py path/to/image.png
```

### Advanced
```bash
python scripts/network_benchmark.py path/to/image.png \
    --iterations 5 \
    --output-dir results \
    --message "Custom message"
```

### Quick Test
```bash
python scripts/quick_network_test.py
```

## Kết quả mong đợi

### So sánh điển hình

| Metric | Original | Stego | Difference |
|--------|----------|-------|------------|
| File Size | ~45 KB | ~45.2 KB | +0.4% |
| Packets | ~32 | ~33 | +1-2 packets |
| Throughput | ~12 Mbps | ~12 Mbps | ±0.1 Mbps |
| Transfer Time | ~0.03s | ~0.03s | ±0.001s |

### Insights

1. **File Size**: Stego image thường lớn hơn 0.1-1% do metadata và proof data
2. **Packets**: Số packet tăng nhẹ do file size lớn hơn
3. **Throughput**: Thường tương đương, có thể giảm nhẹ do overhead
4. **Transfer Time**: Tăng nhẹ tương ứng với file size

## Technical Details

### Network Capture
- Sử dụng tshark để capture traffic
- Filter: `tcp port 8000` (HTTP server port)
- Capture cả TCP và HTTP layers

### HTTP Server
- Local HTTP server trên port 8000
- Serve ảnh qua GET request
- Measure transfer time chính xác

### Analysis
- Parse PCAP file với tshark
- Extract packet-level metrics
- Calculate statistical measures
- Generate visualizations

## Requirements

- Wireshark/tshark
- Python 3.7+
- Dependencies: numpy, PIL, matplotlib, pandas

## Troubleshooting

Xem `README_NETWORK_BENCHMARK.md` để biết chi tiết về troubleshooting.

