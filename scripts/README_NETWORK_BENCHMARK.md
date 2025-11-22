# Network Performance Benchmark

Script đánh giá hiệu năng và payload khi truyền ảnh qua WiFi sử dụng Wireshark/tshark.

## Yêu cầu

1. **Wireshark/tshark**: Cần cài đặt Wireshark để có công cụ `tshark`
   - Windows: Download từ https://www.wireshark.org/
   - Linux: `sudo apt-get install tshark` hoặc `sudo yum install wireshark`
   - macOS: `brew install wireshark`

2. **Python packages**: 
   ```bash
   pip install -r requirements.txt
   ```

3. **Quyền truy cập**: Trên Linux/macOS, có thể cần quyền root để capture network traffic:
   ```bash
   sudo python scripts/network_benchmark.py ...
   ```

## Sử dụng

### Cơ bản

```bash
python scripts/network_benchmark.py examples/testvectors/Lenna_test_image.webp
```

### Với các tùy chọn

```bash
python scripts/network_benchmark.py \
    examples/testvectors/Lenna_test_image.webp \
    --iterations 5 \
    --output-dir my_benchmark_results \
    --message "Custom message to embed"
```

### Chỉ định network interface

```bash
python scripts/network_benchmark.py \
    examples/testvectors/Lenna_test_image.webp \
    --interface "Wi-Fi"  # Windows
    # hoặc
    --interface "wlan0"  # Linux
```

## Các metrics được đánh giá

1. **File Size**: Kích thước file ảnh gốc vs stego
2. **Total Packets**: Tổng số packet truyền đi
3. **Total Bytes**: Tổng số bytes truyền đi
4. **Packet Size**: Kích thước trung bình, min, max của packet
5. **Throughput**: Băng thông (Mbps)
6. **Transfer Time**: Thời gian truyền (giây)
7. **Packets per Second**: Số packet mỗi giây

## Kết quả

Script sẽ tạo:

1. **JSON file**: `benchmark_results/network_benchmark_YYYYMMDD_HHMMSS.json`
   - Chứa tất cả metrics chi tiết và raw data

2. **Comparison plot**: `network_benchmark_YYYYMMDD_HHMMSS_comparison.png`
   - Biểu đồ cột so sánh 6 metrics chính

3. **Trend plot**: `network_benchmark_YYYYMMDD_HHMMSS_trends.png`
   - Biểu đồ đường thể hiện xu hướng qua các iterations

4. **Bảng so sánh**: In ra console với tất cả metrics

## Ví dụ output

```
================================================================
NETWORK PERFORMANCE BENCHMARK
ZK-SNARK Steganography vs Original Image
================================================================

Original image size: 45,234 bytes
Stego image size: 45,456 bytes
Size difference: 222 bytes (0.49%)

Running 3 iterations for each image type...

================================================================
COMPARISON TABLE
================================================================
Metric                      | Original Image    | Stego Image      | Difference
----------------------------|-------------------|------------------|------------
File Size (bytes)           | 45,234           | 45,456           | +222 bytes
Total Packets               | 32.3 ± 1.2       | 33.1 ± 1.1       | +0.8
Throughput (Mbps)           | 12.345 ± 0.123   | 12.298 ± 0.145   | -0.047 Mbps
Transfer Time (s)           | 0.029 ± 0.001    | 0.030 ± 0.001    | +0.001 s
...
```

## Troubleshooting

### Lỗi "tshark not found"
- Đảm bảo Wireshark đã được cài đặt và `tshark` có trong PATH
- Windows: Thêm Wireshark vào PATH hoặc chỉ định full path

### Lỗi "Permission denied" (Linux/macOS)
- Chạy với sudo: `sudo python scripts/network_benchmark.py ...`
- Hoặc thêm user vào wireshark group: `sudo usermod -aG wireshark $USER`

### Không capture được traffic
- Kiểm tra network interface đúng chưa: `tshark -D`
- Đảm bảo HTTP server đang chạy trên port 8000
- Kiểm tra firewall không block traffic

### Kết quả không chính xác
- Tăng số iterations để có kết quả ổn định hơn: `--iterations 10`
- Đảm bảo network ổn định trong quá trình test
- Tránh có traffic khác trên cùng interface

## Advanced Usage

### Phân tích PCAP file riêng

Nếu bạn đã có PCAP file từ Wireshark, có thể phân tích trực tiếp:

```python
from scripts.network_benchmark import NetworkCapture

capture = NetworkCapture()
stats = capture.analyze_capture("your_capture.pcap")
print(stats)
```

### Tùy chỉnh filter

Sửa trong code để thay đổi filter expression cho tshark:

```python
capture.start_capture(pcap_file, filter_expr="tcp port 8000 and host 192.168.1.100")
```

