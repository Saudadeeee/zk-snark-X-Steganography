# ZK-SNARK Steganography Demo

Thư mục này chứa các demo chi tiết và đầy đủ cho hệ thống ZK-SNARK Steganography, bao gồm logging hiệu năng, debug thông tin, và lưu trữ kết quả.

## FOLDER Cấu trúc thư mục

```
Demo/
├── comprehensive_demo.py      # Demo đầy đủ với logging chi tiết
├── step_by_step_demo.py      # Demo từng bước đơn giản
├── performance_benchmark.py   # Benchmark hiệu năng
├── README.md                 # File này
├── doc/                      # Kết quả và báo cáo
├── logs/                     # Log files
├── output/                   # Ảnh stego và ZK proofs
└── debug/                    # Debug information
```

## STARTING Cách sử dụng

### 1. Demo từng bước (Khuyến nghị cho người mới)

```bash
cd Demo
python step_by_step_demo.py
```

**Tính năng:**
- SUCCESS Demo từng bước rõ ràng
- CHECKING Debug output chi tiết
- TIME Đo thời gian từng bước
- NOTE Lưu debug info vào file JSON
- 🖼️ Tạo ảnh stego
- SECURING Generate và verify ZK proof (nếu có)

### 2. Demo đầy đủ với logging

```bash
cd Demo
python comprehensive_demo.py
```

**Tính năng:**
- DATA Comprehensive performance metrics
- NOTE Professional logging system
- CHECKING Detailed debug information
- CHART Performance report generation
- FAST Error handling và recovery
- FOLDER Organized output structure

### 3. Performance Benchmark

```bash
cd Demo
python performance_benchmark.py
```

**Tính năng:**
- 🔬 Test multiple image sizes
- 📏 Test different message lengths  
- DATA Generate performance charts
- CHART Throughput analysis
- 💾 CSV export for analysis
- CHART Size overhead analysis

## DATA Kết quả Demo

### Thư mục `doc/`
- `performance_report_YYYYMMDD_HHMMSS.json` - Báo cáo hiệu năng chi tiết
- `performance_benchmark_YYYYMMDD_HHMMSS.json` - Kết quả benchmark
- `performance_summary_YYYYMMDD_HHMMSS.csv` - Tóm tắt dạng CSV
- `performance_charts_YYYYMMDD_HHMMSS.png` - Biểu đồ hiệu năng

### Thư mục `logs/`
- `demo_log_YYYYMMDD_HHMMSS.log` - Log chi tiết của demo

### Thư mục `output/`
- `stego_image_YYYYMMDD_HHMMSS.png` - Ảnh đã embed message
- `zk_proof_YYYYMMDD_HHMMSS.json` - ZK proof data

### Thư mục `debug/`
- `chaos_embedding_init.json` - Debug info cho chaos embedding
- `message_embedding.json` - Debug info cho message embedding
- `zk_proof_verification.json` - Debug info cho ZK proof

## CHECKING Thông tin Debug

Mỗi demo sẽ tạo ra các file debug chứa:

### Chaos Embedding Debug
```json
{
  "image_path": "/path/to/image.png",
  "image_size": 12345,
  "initialization_time": 0.0234,
  "timestamp": "2025-10-13T10:30:00"
}
```

### Message Embedding Debug
```json
{
  "original_image": "/path/to/original.png",
  "stego_image": "/path/to/stego.png", 
  "message": "Hello ZK World!",
  "embedding_time": 0.1234,
  "original_size": 12345,
  "stego_size": 12456,
  "size_difference": 111,
  "timestamp": "2025-10-13T10:30:01"
}
```

### ZK Proof Debug
```json
{
  "proof_file": "/path/to/proof.json",
  "verification_result": true,
  "proof_generation_time": 2.3456,
  "verification_time": 0.5678,
  "timestamp": "2025-10-13T10:30:03"
}
```

## CHART Performance Metrics

### Timing Metrics
- **Initialization Time**: Thời gian khởi tạo chaos embedding
- **Embedding Time**: Thời gian embed message
- **Proof Generation Time**: Thời gian tạo ZK proof
- **Verification Time**: Thời gian verify proof

### Size Metrics
- **Original Size**: Kích thước ảnh gốc
- **Stego Size**: Kích thước ảnh sau khi embed
- **Size Overhead**: Độ tăng kích thước (bytes và %)
- **Proof Size**: Kích thước ZK proof

### Throughput Metrics
- **Bytes/Second**: Throughput xử lý ảnh
- **Bits/Second**: Throughput embed message
- **Messages/Second**: Số message có thể embed per giây

## 🛠️ Customization

### Thay đổi test images
```python
# Trong script demo, thay đổi đường dẫn:
test_images_dir = Path("custom/path/to/images")
```

### Thay đổi test messages
```python
# Trong performance_benchmark.py:
test_messages = [
    "Custom message 1",
    "Custom message 2", 
    # ...
]
```

### Thay đổi output directory
```python
# Trong script:
output_dir = Path("custom/output/path")
```

## TOOLS Requirements

Để chạy được demo, cần có:
- Python 3.7+
- PIL/Pillow (cho xử lý ảnh)
- matplotlib (cho biểu đồ, optional)
- src/zk_stego modules (chaos_embedding, hybrid_proof_artifact)

## NOTE Troubleshooting

### Lỗi import module
```bash
# Đảm bảo có src/zk_stego directory và các file:
src/zk_stego/chaos_embedding.py
src/zk_stego/hybrid_proof_artifact.py
```

### Không tìm thấy test images
```bash
# Đảm bảo có ảnh test trong:
examples/testvectors/
```

### ZK proof system không hoạt động
- Demo sẽ tiếp tục mà không cần ZK proof
- Check circuits/compiled/ directory có đủ file không

## 📞 Support

Nếu gặp vấn đề với demo, check:
1. Log files trong `logs/` directory
2. Debug files trong `debug/` directory  
3. Error messages trong console output

---

**Happy Testing! COMPLETED**