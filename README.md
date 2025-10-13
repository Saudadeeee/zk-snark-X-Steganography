# ZK-SNARK Steganography System

Hệ thống ẩn thông tin (steganography) tiên tiến sử dụng ZK-SNARK (Zero-Knowledge Succinct Non-Interactive Argument of Knowledge) để chứng minh việc nhúng thông tin mà không tiết lộ nội dung bí mật.

## Tổng quan hệ thống

Đây là một hệ thống hoàn chỉnh kết hợp ba công nghệ chính:
1. **Chaos-based Steganography**: Sử dụng lý thuyết hỗn loạn để tạo vị trí nhúng an toàn
2. **ZK-SNARK Proofs**: Chứng minh toán học không tiết lộ thông tin
3. **Hybrid Embedding**: Kết hợp PNG chunk metadata và LSB embedding

## Kiến trúc hệ thống

```
Hệ thống ZK-SNARK Steganography
├── Lớp ZK Circuit (chaos_zk_stego.circom)
│   ├── 32 ràng buộc tối ưu hóa
│   ├── Xác minh Arnold Cat Map
│   └── Hệ thống chứng minh Groth16
├── Lớp ZK Proof (zk_proof_generator.py)
│   ├── Sinh witness tự động
│   ├── Quản lý trusted setup
│   └── Tạo và xác minh proof
├── Lớp Steganography (chaos_embedding.py)
│   ├── Arnold Cat Map cho vị trí
│   ├── Logistic Map cho nhiễu
│   └── LSB embedding với chaos
└── Lớp Tích hợp (hybrid_proof_artifact.py)
    ├── PNG chunk metadata
    ├── Chaos-based LSB embedding
    └── ZK proof integration
```

## Thuật toán và Cách hoạt động chi tiết

### 1. Arnold Cat Map - Tạo vị trí nhúng

Arnold Cat Map là một phép biến đổi hỗn loạn được định nghĩa như sau:

```
[x_new]   [2 1] [x_old]
[y_new] = [1 1] [y_old] (mod N)
```

**Cách hoạt động:**
- Input: Vị trí ban đầu (x₀, y₀) từ feature extraction
- Process: Áp dụng phép biến đổi Cat Map nhiều lần
- Output: Chuỗi vị trí (x₁, y₁), (x₂, y₂), ..., (xₙ, yₙ)

**Tại sao dùng Arnold Cat Map:**
- Tính chất ergodic: Trải đều các vị trí trên ảnh
- Tính deterministic: Cùng seed cho cùng kết quả
- Tính unpredictable: Khó đoán được vị trí tiếp theo

### 2. Logistic Map - Tạo dãy số ngẫu nhiên

```
x_{n+1} = r × x_n × (1 - x_n)
```

**Tham số:**
- r = 3.9 (vùng hỗn loạn)
- x₀ từ hash của message

**Ứng dụng:**
- Tạo bit mask cho LSB
- Quyết định thứ tự nhúng
- Tăng tính bảo mật

### 3. LSB Embedding với Chaos

**Thuật toán nhúng:**
```python
def embed_bit_at_position(image, position, bit):
    x, y = position
    channel = (x + y) % 3  # R, G, B
    pixel_value = image[y, x, channel]
    
    # Thay thế LSB
    new_value = (pixel_value & 0xFE) | bit
    image[y, x, channel] = new_value
```

**Quy trình hoàn chỉnh:**
1. Extract feature points từ ảnh gốc
2. Tạo chaos key từ message hash
3. Generate vị trí bằng Arnold Cat Map
4. Tạo logistic sequence cho bit ordering
5. Nhúng từng bit vào LSB theo chaos order
6. Tạo ZK proof cho quá trình nhúng

### 4. ZK-SNARK Circuit

**Circuit `chaos_zk_stego.circom` chứng minh:**
- Tính đúng đắn của Arnold Cat Map
- Consistency của vị trí nhúng
- Validity của chaos parameters
- Message commitment correctness

**Constraints (32 total):**
- 16 constraints cho Arnold Cat Map verification
- 8 constraints cho position validation
- 4 constraints cho message hash
- 4 constraints cho commitment scheme

### 5. Groth16 Proving System

**Trusted Setup:**
```bash
1. Compile circuit → R1CS
2. Powers of Tau ceremony → pot12_final.ptau
3. Circuit-specific setup → circuit.zkey
4. Export verification key → verification_key.json
```

**Proof Generation:**
```bash
1. Create witness từ chaos parameters
2. Generate proof với circuit.zkey
3. Extract public inputs
4. Verify proof với verification key
```

## Tính năng chính

### Về ZK-SNARK Proofs
- **Tính Zero-Knowledge**: Chứng minh có nhúng thông tin mà không tiết lộ nội dung
- **Tính Succinct**: Proof chỉ 739 bytes bất kể kích thước message
- **Tính Non-Interactive**: Không cần tương tác giữa prover và verifier
- **Soundness**: Không thể tạo proof giả với xác suất cao

### Về Chaos-Based Embedding
- **Arnold Cat Map**: Tạo vị trí nhúng unpredictable
- **Logistic Map**: Tạo sequence ngẫu nhiên cho bit ordering
- **Feature-based initialization**: Sử dụng đặc trưng ảnh làm seed
- **Deterministic reproducibility**: Cùng input → cùng output

### Về Performance
- **Proof Generation**: 2.3 giây (bao gồm witness + proof)
- **Proof Verification**: 0.5 giây
- **Embedding Speed**: <0.01 giây cho messages ngắn
- **Success Rate**: 100% trong testing
- **Memory Usage**: <50MB peak

## Cấu trúc thư mục chi tiết

```
zk-snarkXsteganography/
├── 📋 Tài liệu hệ thống
│   ├── PROJECT_FLOW.md              # Lịch sử phát triển từng bước
│   ├── SYSTEM_TEST_REPORT.md        # Báo cáo test hệ thống
│   ├── EMOJI_CLEANUP_SUMMARY.md     # Báo cáo làm sạch code
│   └── README.md                    # File này
│
├── 🛠️ Source Code chính
│   └── src/zk_stego/
│       ├── chaos_embedding.py       # Core steganography algorithms
│       │   ├── ChaosGenerator class (Arnold Cat + Logistic Map)
│       │   ├── ChaosEmbedding class (LSB embedding với chaos)
│       │   └── ChaosProofArtifact class (proof integration)
│       │
│       ├── hybrid_proof_artifact.py # ZK proof integration layer
│       │   ├── HybridProofArtifact class
│       │   ├── PNG chunk handling
│       │   └── ZK proof generation/verification
│       │
│       └── zk_proof_generator.py    # ZK-SNARK proof system
│           ├── ZKProofGenerator class
│           ├── Trusted setup automation
│           ├── Witness generation
│           └── Groth16 proof ops
│
├── ⚙️ ZK-SNARK Circuits
│   ├── source/
│   │   └── chaos_zk_stego.circom    # ZK circuit definition
│   └── compiled/build/
│       ├── stego_check_v2.r1cs      # Constraint system
│       ├── stego_check_v2.wasm      # WebAssembly witness generator
│       ├── circuit_0000.zkey        # Proving key
│       └── stego_check_v2_js/       # JavaScript interface
│
├── 🎮 Demo và Testing
│   ├── Demo/
│   │   ├── quick_start.py           # Demo nhanh (5 phút)
│   │   ├── step_by_step_demo.py     # Demo từng bước chi tiết
│   │   ├── comprehensive_demo.py    # Demo toàn diện với logging
│   │   ├── performance_benchmark.py # Benchmark hiệu suất
│   │   └── run_all_demos.sh         # Chạy tất cả demos
│   │
│   ├── examples/testvectors/
│   │   ├── cover_16x16.png          # Test image nhỏ
│   │   ├── cover_32x32.png          # Test image vừa
│   │   └── Lenna_test_image.webp    # Test image chính (512x512)
│   │
│   └── verify_zk_stego.py          # Tool verify steganographic content
│
├── 📊 Performance Analysis
│   └── performance/
│       ├── MASTER_PERFORMANCE_REPORT.md     # Báo cáo tổng hợp
│       ├── MASTER_BENCHMARK_SUMMARY.json    # Dữ liệu benchmark JSON
│       ├── image_size_performance.png       # Biểu đồ performance
│       └── security_analysis_results.json   # Phân tích bảo mật
│
└── 🔑 Cryptographic Artifacts
    └── artifacts/keys/
        ├── pot12_final.ptau         # Powers of Tau (42MB)
        └── verification_key.json    # Public verification key
```

## Hướng dẫn cài đặt và chạy

### Yêu cầu hệ thống

**Phần mềm cần thiết:**
```bash
# Node.js và snarkjs (cho ZK-SNARK operations)
npm install -g snarkjs circomlib

# Python packages
pip install pillow numpy hashlib

# Kiểm tra circom compiler
./bin/circom --version  # Phải có sẵn
```

**Phần cứng khuyến nghị:**
- RAM: Tối thiểu 4GB, khuyến nghị 8GB
- CPU: Multi-core cho parallel operations
- Disk: 500MB free space cho artifacts

### Sử dụng cơ bản

**1. Khởi tạo hệ thống và nhúng message:**
```python
import sys
sys.path.append('./src')

from zk_stego.hybrid_proof_artifact import HybridProofArtifact
import numpy as np
from PIL import Image

# Bước 1: Load ảnh cover
image = Image.open("examples/testvectors/Lenna_test_image.webp")
image_array = np.array(image)
print(f"Image shape: {image_array.shape}")

# Bước 2: Khởi tạo hệ thống
hybrid = HybridProofArtifact()

# Import metadata generator
from zk_stego.metadata_message_generator import MetadataMessageGenerator
metadata_gen = MetadataMessageGenerator()

# Bước 3: Tạo metadata message và nhúng với ZK proof
# Sử dụng metadata thay vì custom text để tăng tính tự nhiên
message = metadata_gen.generate_authenticity_hash_message("examples/testvectors/Lenna_test_image.webp")
print(f"Generated metadata message: {message}")
print(f"Message type: Image authenticity verification")

# Tạo stego image với ZK proof
stego_result = hybrid.embed_with_proof(
    image_array, 
    message, 
    x0=100,      # Vị trí bắt đầu X (optional)
    y0=100,      # Vị trí bắt đầu Y (optional)
    chaos_key="authenticity_verification_key"  # Key for metadata protection
)

if stego_result:
    stego_image, proof_package = stego_result
    print("✓ Metadata embedding successful!")
    print(f"✓ ZK Proof generated: {len(str(proof_package))} bytes")
    print("✓ Purpose: Image authenticity verification")
    
    # Lưu stego image
    stego_image.save("metadata_stego.png")
    print("✓ Metadata stego image saved as metadata_stego.png")
```

**2. Xác minh ZK proof:**
```python
# Xác minh proof từ stego image
verification_result = hybrid.verify_proof(proof_package)

if verification_result:
    print("✓ ZK Proof verification PASSED")
    print("✓ Message was authentically embedded")
else:
    print("✗ ZK Proof verification FAILED")
```

### Các loại Metadata Messages

**Hệ thống hỗ trợ nhiều loại metadata messages:**

**1. Authenticity Hash (Xác thực tính toàn vẹn):**
```python
message = metadata_gen.generate_authenticity_hash_message("image.jpg")
# "Authenticity Hash - SHA256: a1b2c3d4..., Verified: 2025-10-13 12:35:43"
# Mục đích: Digital forensics, evidence integrity
```

**2. File Properties (Thuộc tính file):**
```python
message = metadata_gen.generate_file_properties_message("image.jpg")
# "File: image.jpg, Size: 2048000 bytes, Created: 2025-10-13 10:30:25"
# Mục đích: File integrity verification
```

**3. Copyright Protection (Bảo vệ bản quyền):**
```python
message = metadata_gen.generate_copyright_message("Your Name", "CC BY-SA 4.0")
# "Copyright (c) 2025 Your Name. CC BY-SA 4.0. Protected: 2025-10-13..."
# Mục đích: Intellectual property protection
```

**4. Processing History (Lịch sử xử lý):**
```python
message = metadata_gen.generate_processing_history_message("Adobe Lightroom + AI enhancement")
# "Processing History - Adobe Lightroom + AI enhancement, Processed: 2025-10-13..."
# Mục đích: Technical documentation
```

**5. GPS Location (Vị trí địa lý):**
```python
message = metadata_gen.generate_location_message(21.0285, 105.8542, "Hanoi, Vietnam")
# "Location - GPS: 21.0285, 105.8542, Place: Hanoi, Vietnam, Recorded: 2025-10-13..."
# Mục đích: Geographic verification
```

### So sánh Metadata vs Custom Messages

| Tiêu chí | Metadata Messages | Custom Messages |
|----------|------------------|-----------------|
| **Natural plausibility** | ✅ Cao - thuộc về ảnh | ❌ Thấp - không liên quan |
| **Detection risk** | ✅ Thấp - expected behavior | ❌ Cao - suspicious content |
| **Legal legitimacy** | ✅ Có lý do hợp lý | ❌ Khó biện minh |
| **Flexibility** | ❌ Hạn chế theo metadata | ✅ Hoàn toàn tự do |
| **Use cases** | Forensics, copyright, integrity | Secret communication |
| **Professional applications** | ✅ Digital evidence, IP protection | ❌ Chỉ cho communication |

### Sử dụng Command Line

**Verify steganographic content trong ảnh:**
```bash
# Cú pháp cơ bản
python3 verify_zk_stego.py <path_to_stego_image>

# Ví dụ với metadata
python3 verify_zk_stego.py metadata_stego.png

# Với verbose output
python3 verify_zk_stego.py output_stego.png --verbose

# Output dạng JSON
python3 verify_zk_stego.py output_stego.png --json
```

**Expected Output:**
```
Analyzing steganographic image: output_stego.png
ZK-SNARK Proof Successfully Extracted!
   Algorithm: chaos_embedding
   Proof elements: pi_a, pi_b, pi_c
   Data size: 192 bits
   Positions used: 24
   Arnold iterations: 16
   Logistic parameter: 3.9
SUCCESS: ZK-SNARK Proof Verified in output_stego.png
```

## Hướng dẫn chạy Demo chi tiết

### 1. Quick Start Demo (Demo/quick_start.py)

**Mục đích:** Test nhanh các chức năng cơ bản
**Thời gian:** 30 giây
**Output files:** Temporary stego images trong /tmp/

```bash
cd Demo
python3 quick_start.py
```

**Expected Output:**
```
QUICK START - ZK Steganography Demo
=====================================
Time: 12:06:04

Using image: Lenna_test_image.webp
   Size: 427,806 bytes

Testing imports...
   ChaosEmbedding imported
   HybridProofArtifact imported

Quick functionality test...
   Initializing with Lenna_test_image.webp...
   Chaos embedding initialized
   Message embedded successfully
   Stego image saved: /tmp/tmpbkh7y_gj.png
   ZK system initialized

QUICK TEST COMPLETED SUCCESSFULLY!
Image dimensions: (512, 512, 3)
Message length: 6 characters
Steganography: Basic chaos embedding works
ZK Support: Available
```

### 2. Step-by-Step Demo (Demo/step_by_step_demo.py)

**Mục đích:** Demo giáo dục với giải thích từng bước
**Thời gian:** 2-3 phút
**Output files:** 
- `demo_output/` - Thư mục chứa kết quả
- `debug/` - Thông tin debug chi tiết
- `logs/` - Log files

```bash
cd Demo
python3 step_by_step_demo.py
```

**Các bước thực hiện:**
1. **Environment Check** - Kiểm tra môi trường
2. **Module Import** - Import các module cần thiết
3. **Image Loading** - Load và phân tích test images
4. **Chaos Initialization** - Khởi tạo chaos parameters
5. **Message Preparation** - Chuẩn bị message for embedding
6. **Embedding Process** - Thực hiện chaos-based LSB embedding
7. **ZK Proof Generation** - Tạo ZK-SNARK proof (nếu có circuit)
8. **Verification** - Verify embedded content
9. **Output Generation** - Tạo các file kết quả

### 3. Comprehensive Demo (Demo/comprehensive_demo.py)

**Mục đích:** Demo toàn diện với logging và metrics
**Thời gian:** 5-10 phút
**Output files:**
- `results/comprehensive_demo_YYYYMMDD_HHMMSS/` - Thư mục kết quả
- Performance metrics JSON
- Detailed logs
- Debug information

```bash
cd Demo
python3 comprehensive_demo.py
```

**Features:**
- Timing measurements cho mỗi operation
- Memory usage tracking
- Error handling và recovery
- Detailed performance metrics
- Automated report generation

### 4. Performance Benchmark (Demo/performance_benchmark.py)

**Mục đích:** Đo hiệu suất và tạo báo cáo benchmark
**Thời gian:** 10-15 phút
**Output files:**
- `benchmark_results/` - Thư mục kết quả benchmark
- `benchmark_summary_YYYYMMDD_HHMMSS.csv` - Tóm tắt dạng CSV
- `performance_report_YYYYMMDD_HHMMSS.md` - Báo cáo chi tiết
- `performance_charts_YYYYMMDD_HHMMSS.png` - Biểu đồ (nếu có matplotlib)

```bash
cd Demo
python3 performance_benchmark.py
```

**Test scenarios:**
- Multiple message lengths (2, 12, 54, 114, 200 characters)
- Different image sizes
- Memory usage profiling
- Speed optimization analysis
- Success rate calculation

### 5. Chạy tất cả Demos (Demo/run_all_demos.sh)

**Mục đích:** Thực hiện full test suite
**Thời gian:** 15-20 phút

```bash
cd Demo
chmod +x run_all_demos.sh
./run_all_demos.sh
```

**Process:**
1. Environment validation
2. Chạy tất cả demo scripts
3. Collect results
4. Generate summary report
5. Create aggregated documentation

## Ý nghĩa các file xuất ra

### A. Files được tạo ra từ ZK-SNARK System

**1. ZK Circuit Artifacts (`circuits/compiled/build/`)**
```
stego_check_v2.r1cs      # Rank-1 Constraint System (circuit compiled)
├── Mô tả: Constraint system dạng binary cho ZK circuit
├── Kích thước: ~50KB
├── Nội dung: 32 constraints cho Arnold Cat Map verification
└── Sử dụng: Input cho trusted setup phase

stego_check_v2.wasm      # WebAssembly witness generator  
├── Mô tả: Fast witness generation từ inputs
├── Kích thước: ~100KB
├── Nội dung: Compiled circuit logic  
└── Sử dụng: Generate witness từ chaos parameters

circuit_0000.zkey        # Proving key (circuit-specific)
├── Mô tả: Secret key cho proof generation
├── Kích thước: ~20MB
├── Bảo mật: Chứa secret randomness từ trusted setup
└── Sử dụng: Input cho snarkjs prove command

verification_key.json    # Public verification key
├── Mô tả: Public key để verify proofs
├── Kích thước: ~2KB  
├── Nội dung: G1, G2 points trên elliptic curves
└── Sử dụng: Verify ZK proofs publicly
```

**2. ZK Proof Artifacts (runtime generated)**
```
proof_TIMESTAMP.json     # ZK-SNARK proof
├── Cấu trúc: {"pi_a": [...], "pi_b": [...], "pi_c": [...]}
├── Kích thước: 739 bytes constant
├── Nội dung: Groth16 proof elements
└── Ý nghĩa: Chứng minh toán học về việc nhúng

public_TIMESTAMP.json    # Public inputs  
├── Cấu trúc: [field_element_1, field_element_2, ...]
├── Kích thước: ~200 bytes
├── Nội dung: Image hash, commitment root, timestamp
└── Ý nghĩa: Public inputs cho proof verification

witness_TIMESTAMP.wtns  # Witness file (temporary)
├── Mô tả: Intermediate computation results
├── Kích thước: ~10KB
├── Lifecycle: Tạo ra và xóa ngay sau proof generation
└── Ý nghĩa: Bridge giữa inputs và proof
```

### B. Files được tạo ra từ Steganography

**3. Stego Images và Metadata**
```
output_stego.png         # Stego image chính
├── Format: PNG với embedded data
├── Kích thước: Gần bằng original image  
├── Visual: Không thể phân biệt với mắt thường
├── Content: Original image + embedded message + PNG chunks
└── Sử dụng: Chứa thông tin ẩn và ZK proof metadata

PNG Chunks trong stego image:
├── stEg (custom): Chaos parameters và metadata
├── tEXt: Human-readable steganography info  
├── IDAT: Image data với LSB modifications
└── Standard PNG chunks: Unchanged
```

**4. Debug và Analysis Files**
```
chaos_metadata.json      # Chaos embedding parameters
├── Structure: {
│   "arnold_iterations": 16,
│   "logistic_r": 3.9,
│   "initial_position": [x0, y0],
│   "positions_used": [...],
│   "message_length": n_bits
│   }
├── Ý nghĩa: Debug info cho chaos algorithm
└── Sử dụng: Reproduce embedding process

embedding_positions.json # Vị trí nhúng chi tiết
├── Structure: [[x1,y1,channel], [x2,y2,channel], ...]
├── Ý nghĩa: Exact pixels modified during embedding  
└── Sử dụng: Verify correctness, debug issues
```

### C. Performance và Benchmark Files

**5. Benchmark Results**
```
benchmark_summary_YYYYMMDD_HHMMSS.csv
├── Columns: message_length, embed_time, extract_time, memory_peak, success
├── Data: Performance metrics cho multiple test cases
├── Format: Standard CSV for analysis
└── Sử dụng: Performance comparison, optimization

performance_report_YYYYMMDD_HHMMSS.md  
├── Content: Detailed analysis với charts và insights
├── Sections: Executive summary, detailed metrics, recommendations
├── Format: Markdown with embedded data
└── Sử dụng: Human-readable performance analysis

performance_charts_YYYYMMDD_HHMMSS.png
├── Content: Visual charts (time vs message_length, memory usage)
├── Generated: Khi có matplotlib available
├── Format: PNG image với multiple subplots
└── Sử dụng: Visual performance analysis
```

**6. System Analysis Files**
```
MASTER_BENCHMARK_SUMMARY.json
├── Content: Aggregated data từ tất cả test runs
├── Structure: {
│   "total_tests": n,
│   "success_rate": percentage,  
│   "avg_metrics": {...},
│   "test_history": [...]
│   }
└── Sử dụng: Long-term performance tracking

security_analysis_results.json
├── Content: Security assessment data
├── Metrics: Entropy analysis, pattern detection results
├── Structure: {"entropy": float, "randomness_test": bool, ...}
└── Sử dụng: Verify security properties của chaos algorithms
```

### D. Temporary và Log Files

**7. Runtime Files**
```
/tmp/tmp*.png            # Temporary stego images từ quick tests
├── Lifecycle: Created và deleted automatically
├── Sử dụng: Testing purposes only
└── Note: Có thể remain nếu process interrupted

Demo/debug/             # Debug information từ demos
├── step_debug_*.json   # Per-step debug info
├── error_logs_*.txt    # Error messages và stack traces
└── timing_*.json       # Detailed timing measurements

Demo/logs/              # Execution logs
├── demo_execution_*.log # Full execution logs
├── performance_*.log    # Performance-specific logs  
└── error_*.log          # Error logs
```

## Metrics và Performance Data

### Performance Benchmarks Chi tiết

| Metric | Value | Giải thích |
|--------|--------|-----------|
| **ZK Proof Generation** | 2.322s | Thời gian từ chaos params → final proof |
| **ZK Proof Verification** | 0.505s | Thời gian verify proof với public inputs |
| **Chaos Embedding** | 0.001-0.005s | LSB embedding với Arnold Cat Map |
| **Feature Extraction** | 0.030s | Extract starting points từ image |
| **Total End-to-End** | 2.827s | Complete workflow: embed + prove |
| **Proof Size** | 739 bytes | Constant size bất kể message length |
| **Circuit Constraints** | 32 | Optimized constraint count |
| **Success Rate** | 100% | Thành công trong tất cả test cases |
| **Memory Peak** | 45MB | Maximum RAM usage during proof gen |
| **Scalability** | Linear | O(n) với message length |

### Message Length Performance

| Length | Embed Time | Proof Time | Total Time | Success |
|---------|------------|------------|------------|---------|
| 2 chars | 0.0008s | 2.322s | 2.323s | ✓ |
| 12 chars | 0.0009s | 2.325s | 2.326s | ✓ |
| 54 chars | 0.0021s | 2.330s | 2.332s | ✓ |
| 114 chars | 0.0030s | 2.340s | 2.343s | ✓ |
| 200 chars | 0.0046s | 2.355s | 2.360s | ✓ |

**Nhận xét:**
- Embedding time tăng tuyến tính với message length
- ZK proof time gần như constant (chỉ phụ thuộc circuit)
- Memory usage stable across different message sizes
- 100% success rate cho tất cả test scenarios

## Bảo mật và Thuộc tính Security

### Zero-Knowledge Properties

**1. Completeness** 
- Nếu statement đúng → prover có thể convince verifier với xác suất 1
- Trong hệ thống: Nếu message thực sự được nhúng → proof sẽ verify thành công

**2. Soundness**
- Nếu statement sai → không thể tạo valid proof với xác suất negligible  
- Security level: 2^128 (computational soundness)
- Trong hệ thống: Không thể fake proof cho message không được nhúng

**3. Zero-Knowledge**
- Proof không tiết lộ thông tin gì về witness (message content)
- Verifier chỉ biết "có message được nhúng" chứ không biết nội dung
- Privacy: Message content vẫn an toàn ngay khi proof bị public

### Chaos-Based Security

**Arnold Cat Map Security:**
```
Security properties:
├── Ergodicity: Vị trí nhúng phân bố đều trên toàn ảnh
├── Sensitivity: Thay đổi nhỏ input → thay đổi lớn output  
├── Periodicity: Chuỗi vị trí không lặp lại trong phạm vi thực tế
└── Unpredictability: Không thể đoán vị trí tiếp theo without key
```

**Logistic Map Security:**
```
Parameters: r = 3.9 (chaotic regime)
Properties:
├── Lyapunov exponent > 0 (chaotic behavior confirmed)
├── Uniform distribution trên [0,1] interval
├── High entropy: ~0.9998 bits per sample
└── No periodic patterns trong practical ranges
```

### Cryptographic Security

**Groth16 Security Assumptions:**
1. **q-Strong Bilinear Diffie-Hellman (q-SBDH)**
2. **q-Power Knowledge of Exponent (q-PKE)**  
3. **Generic Group Model assumptions**

**Security Level:** 128-bit (equivalent to AES-128)

**Trusted Setup:**
- Powers of Tau ceremony: Universal, reusable
- Circuit-specific setup: Per-circuit, requires trust
- Verification key: Public, can be audited

### Attack Resistance

**1. Steganalysis Resistance**
```
Chi-square test: PASS (p-value > 0.05)
Visual inspection: PASS (no visible artifacts)
Histogram analysis: PASS (no suspicious patterns)
LSB analysis: Chaotic patterns → hard to detect
```

**2. ZK Proof Security**
```
Forge resistance: Computational soundness 2^128
Privacy: Perfect zero-knowledge property
Non-malleability: Cannot modify proofs
Proof size: Constant 739 bytes → no info leakage
```

**3. Chaos Algorithm Security**
```
Brute force: 2^256 search space (SHA-256 based keys)
Pattern analysis: Chaotic behavior → no patterns
Statistical tests: Pass NIST randomness tests
Correlation: No correlation between positions
```

## Troubleshooting và Debug

### Common Issues và Solutions

**1. ZK Circuit Issues**
```bash
# Problem: "R1CS file not found"
Solution: 
cd circuits/source
circom chaos_zk_stego.circom --r1cs --wasm --sym -o ../compiled/build/

# Problem: "Powers of Tau not found"  
Solution:
wget -O artifacts/keys/pot12_final.ptau \
    https://hermez.s3-eu-west-1.amazonaws.com/powersOfTau28_hez_final_12.ptau

# Problem: "Circuit key not found"
Solution: Chạy trusted setup:
python3 -c "from src.zk_stego.zk_proof_generator import ZKProofGenerator; ZKProofGenerator().setup_trusted_setup()"
```

**2. Python Import Errors**
```bash
# Problem: "ModuleNotFoundError: No module named 'zk_stego'"
Solution:
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"
# Or: sys.path.append('./src') trong Python script

# Problem: "PIL import error"
Solution: pip install Pillow

# Problem: "numpy not found" 
Solution: pip install numpy
```

**3. Performance Issues**
```bash
# Problem: "Proof generation too slow"
Solutions:
- Increase RAM allocation
- Use SSD instead of HDD
- Close other applications
- Check swap usage

# Problem: "Memory errors during proof generation"
Solutions:  
- Increase virtual memory
- Use smaller circuit (reduce constraints)
- Run on machine with more RAM
```

**4. Embedding Issues**
```bash
# Problem: "Message too long for image"
Solution: 
- Use larger image
- Reduce message length  
- Check capacity: (width * height * 3) / 8 bits

# Problem: "Embedding positions overlap"
Solution:
- Increase Arnold iterations
- Use different chaos key
- Check image size compatibility
```

### Debug Commands

**Verify system components:**
```bash
# Check all dependencies
python3 Demo/quick_start.py

# Verify ZK circuit compilation
ls circuits/compiled/build/
file circuits/compiled/build/stego_check_v2.r1cs

# Test chaos algorithms only
python3 -c "
from src.zk_stego.chaos_embedding import ChaosEmbedding
import numpy as np
from PIL import Image
img = np.array(Image.open('examples/testvectors/Lenna_test_image.webp'))
ce = ChaosEmbedding(img)
result = ce.embed_message('test')
print('✓ Chaos embedding works')
"

# Test ZK proof system
python3 -c "
from src.zk_stego.zk_proof_generator import ZKProofGenerator
zk = ZKProofGenerator()
print('✓ ZK generator initializes')
"
```

**Debug với verbose output:**
```bash
# Enable debug logging
export DEBUG=1
python3 Demo/comprehensive_demo.py

# Check specific component
python3 verify_zk_stego.py output_stego.png --verbose

# Performance profiling
python3 -m cProfile Demo/performance_benchmark.py
```

## Tài liệu tham khảo

### Academic Papers và References

**ZK-SNARK Theory:**
1. "Quadratic Span Programs and Succinct NIZKs without PCPs" - Gennaro et al.
2. "On the Size of Pairing-based Non-interactive Arguments" - Groth 2016  
3. "Scalable Zero Knowledge via Cycles of Elliptic Curves" - Ben-Sasson et al.

**Chaos Theory trong Cryptography:**
1. "A New Chaos-Based Fast Image Encryption Algorithm" - Chen et al.
2. "Arnold Cat Map and its Applications in Cryptography" - Liu et al.
3. "Logistic Map Cryptanalysis and Its Application" - Kocarev et al.

**Steganography Methods:**
1. "Information Hiding: Steganography and Watermarking" - Katzenbeisser
2. "Chaos-Based Image Steganography" - Zhang et al.
3. "LSB Steganography in Digital Images" - Johnson & Jajodia

### Technical Documentation

**System Documentation:**
- **`PROJECT_FLOW.md`**: Complete development history từ concept đến implementation
- **`SYSTEM_TEST_REPORT.md`**: Comprehensive test results và analysis
- **`Demo/FINAL_ANALYSIS_REPORT.md`**: Final performance analysis summary
- **`performance/MASTER_PERFORMANCE_REPORT.md`**: Detailed benchmark data

**Code Documentation:**
- **`circuits/source/chaos_zk_stego.circom`**: ZK circuit specification với comments
- **`src/zk_stego/`**: Python source code với docstrings chi tiết
- **`Demo/README.md`**: Demo-specific documentation

### Development và Contributing

**Circuit Development:**
```bash
# Compile và test ZK circuit
cd circuits/source
circom chaos_zk_stego.circom --r1cs --wasm --sym -o ../compiled/build/

# Test circuit với sample inputs
npx snarkjs wtns calculate ../compiled/build/chaos_zk_stego.wasm input.json witness.wtns
```

**Python Development:**
```bash
# Setup development environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run tests
python3 -m pytest tests/ -v

# Code quality
flake8 src/
mypy src/
```

**Trusted Setup Process:**
```bash
# The system tự động handle trusted setup:
1. Download Powers of Tau: pot12_final.ptau (42MB)
2. Generate circuit-specific keys: circuit.zkey (~20MB)  
3. Export verification key: verification_key.json (2KB)
4. All keys stored trong artifacts/keys/
```

## Use Cases trong thực tế

### 1. Private Communication
**Scenario:** Gửi thông tin nhạy cảm qua kênh public
**Implementation:**
- Nhúng message vào family photos
- Share photos trên social media
- Receiver verify và extract message
- ZK proof đảm bảo authenticity

### 2. Digital Watermarking  
**Scenario:** Bảo vệ bản quyền hình ảnh
**Implementation:**
- Nhúng copyright info vào images
- Tạo ZK proof ownership
- Publish images với embedded watermark
- Verify ownership without revealing watermark

### 3. Forensic Analysis
**Scenario:** Tamper detection cho evidence images
**Implementation:**
- Embed hash của original metadata
- Tạo ZK proof cho integrity
- Store images trong evidence database
- Verify tampering without exposing evidence details

### 4. Privacy-Preserving Authentication
**Scenario:** Prove identity without revealing personal info
**Implementation:**
- Embed identity tokens vào profile pictures
- Generate ZK proof cho valid identity
- Verify credentials publicly
- Maintain privacy của personal data

## License và Legal

**Open Source License:** MIT License
- ✓ Commercial use allowed
- ✓ Modification allowed  
- ✓ Distribution allowed
- ✓ Private use allowed
- ✗ Liability protection
- ✗ Warranty provided

**Legal Considerations:**
- Cryptography export controls may apply
- Check local laws về steganography usage
- ZK-SNARK patents may apply trong commercial settings
- Use responsibly và ethically

## Contact và Support

**Repository:** https://github.com/Saudadeeee/zk-snark-X-Steganography
**Issues:** Use GitHub Issues cho bug reports
**Discussions:** GitHub Discussions cho questions
**Documentation:** All docs trong repository

**Contributing Guidelines:**
1. Fork repository và create feature branch
2. Follow existing code style và patterns
3. Add tests cho new functionality  
4. Update documentation accordingly
5. Submit pull request với clear description

---

**🔐 Built with ZK-SNARK technology for privacy-preserving steganography 🔐**

*"Prove you embedded the message without revealing what you embedded"*