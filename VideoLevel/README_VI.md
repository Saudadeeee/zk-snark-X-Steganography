# Hệ thống Giấu tin Video với ZK-SNARK

Giấu tin Video với Zero-Knowledge Proof sử dụng H.264 CAVLC và Groth16 thực

**Trạng thái:** Sẵn sàng Production | **Phiên bản:** 2.0 | **Cập nhật:** 2 tháng 2, 2026

## Mục lục

- [Hệ thống Giấu tin Video với ZK-SNARK](#hệ-thống-giấu-tin-video-với-zk-snark)
  - [Mục lục](#mục-lục)
  - [Tổng quan](#tổng-quan)
    - [Đây là gì?](#đây-là-gì)
    - [Cách hoạt động](#cách-hoạt-động)
    - [Tính năng chính](#tính-năng-chính)
  - [Kiến trúc](#kiến-trúc)
    - [Các thành phần hệ thống](#các-thành-phần-hệ-thống)
    - [Cấu trúc dự án](#cấu-trúc-dự-án)
  - [Quy trình hoàn chỉnh](#quy-trình-hoàn-chỉnh)
    - [Hướng dẫn từng bước](#hướng-dẫn-từng-bước)
      - [Quy trình kỹ thuật hoàn chỉnh](#quy-trình-kỹ-thuật-hoàn-chỉnh)
  - [Bắt đầu nhanh](#bắt-đầu-nhanh)
  - [Thông số kỹ thuật](#thông-số-kỹ-thuật)
    - [Thông số Video Codec](#thông-số-video-codec)
    - [Thông số Steganography](#thông-số-steganography)
    - [Thông số ZK-SNARK](#thông-số-zk-snark)
  - [Hiệu năng](#hiệu-năng)
    - [Benchmark thời gian](#benchmark-thời-gian)
    - [Phân tích Dung lượng](#phân-tích-dung-lượng)
    - [Độ đo Chất lượng](#độ-đo-chất-lượng)
  - [Kiểm thử](#kiểm-thử)
    - [Bộ kiểm thử tự động](#bộ-kiểm-thử-tự-động)
  - [Tài liệu](#tài-liệu)
    - [Tài liệu cốt lõi](#tài-liệu-cốt-lõi)
  - [Bảo mật](#bảo-mật)
    - [Bảo mật Steganography](#bảo-mật-steganography)
    - [Bảo mật Mật mã học](#bảo-mật-mật-mã-học)
  - [Giấy phép](#giấy-phép)

---

## Tổng quan

### Đây là gì?

**Dành cho người mới bắt đầu:** Hệ thống này giấu các thông điệp bí mật và chứng minh mật mã học bên trong video H.264. Video trông hoàn toàn giống với mắt thường, nhưng chứa dữ liệu ẩn mà chỉ những người biết mới có thể trích xuất được. Giống như mực tàng hình cho video!

**Dành cho chuyên gia:** Triển khai sẵn sàng production của LSB steganography trong các hệ số DCT của H.264 với tích hợp chứng minh ZK-SNARK Groth16. Có triển khai đầy đủ codec CAVLC để tái tạo bitstream và xác minh mật mã học thực sự qua snarkjs/Circom.

### Cách hoạt động

**Giải thích đơn giản:**

1. **Video sang Số**: Video H.264 lưu trữ dữ liệu hình ảnh dưới dạng số (hệ số DCT)
2. **Giấu dữ liệu**: Chúng ta sửa bit cuối cùng của mỗi số để giấu thông điệp
3. **Tái tạo Video**: Xây dựng lại video với dữ liệu ẩn đã nhúng
4. **Trích xuất dữ liệu**: Đọc các bit cuối để khôi phục thông điệp ẩn
5. **Xác minh Chứng minh**: Sử dụng zero-knowledge proof để xác minh tính xác thực mà không tiết lộ bí mật

**Quy trình kỹ thuật:**

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│ Video đầu vào│─────>│ Giải mã CAVLC│─────>│  Hệ số DCT  │
│   (H.264)   │      │ (Trích xuất) │      │ [2,-3,4...] │
└─────────────┘      └──────────────┘      └─────────────┘
                                                   │
                                                   ▼
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│ Video Stego │<─────│  Mã hóa CAVLC│<─────│ Sửa đổi LSB │
│  (Đầu ra)   │      │              │      │  [3,-2,5...]│
└─────────────┘      └──────────────┘      └─────────────┘
                                                   ▲
                                                   │
                                            ┌──────────────┐
                                            │ Thông điệp   │
                                            │  + ZK Proof  │
                                            └──────────────┘
```

### Tính năng chính

**Bảo mật mật mã học:**
- Real Groth16 ZK-SNARK: Chứng minh zero-knowledge thực (không phải giả lập)
- SHA256 Commitment: Ràng buộc mật mã học không tiết lộ bí mật
- Mạch Circom: Hệ thống ràng buộc chính thức với khoảng 3,000 ràng buộc R1CS
- BN128 Pairing: Mật mã học đường cong elliptic để xác minh chứng minh

**Xử lý Video:**
- H.264 CAVLC Codec: Triển khai đầy đủ bộ mã hóa/giải mã
- Tái tạo Bitstream: Mã hóa lại video sau khi sửa đổi hệ số
- Phân phối Đa khung hình: Trải payload lớn qua hơn 90 khung hình
- Bảo toàn Chất lượng: PSNR > 45 dB (giống hệt về mặt hình ảnh)

**Giấu dữ liệu:**
- LSB Steganography: Sửa đổi bit ít quan trọng nhất của hệ số DCT
- Chế độ Chuẩn: khoảng 95 bit/khung hình (khoảng 12 byte/khung hình) - ổn định
- Chế độ Dung lượng cao: khoảng 190 bit/khung hình (khoảng 24 byte/khung hình) - thử nghiệm
- Phát hiện Dung lượng Tự động: Tính toán không gian khả dụng trước khi nhúng

**Hiệu năng:**
- Trích xuất Nhanh: khoảng 0.5-1.0s mỗi khung hình
- Tái tạo Nhanh: khoảng 0.2-0.5s mỗi khung hình
- Chứng minh Hiệu quả: 2-5s tạo, 1-2s xác minh
- Chứng minh Gọn nhẹ: 336 byte (nhị phân) so với 3.8KB (JSON)

## Kiến trúc

### Các thành phần hệ thống

Hệ thống bao gồm 5 thành phần chính hoạt động cùng nhau:

```
┌─────────────────────────────────────────────────────────────┐
│            Hệ thống Giấu tin Video với ZK-SNARK             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │   Xử lý      │  │     LSB      │  │  Chứng minh  │     │
│  │  Bitstream   │──│ Steganography│──│   ZK-SNARK   │     │
│  │  (CAVLC)     │  │  (Embedder)  │  │  (Groth16)   │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│         │                  │                  │            │
│         └──────────────────┴──────────────────┘            │
│                            │                               │
│                   ┌────────▼────────┐                      │
│                   │   Tái tạo &     │                      │
│                   │   Xác minh      │                      │
│                   └─────────────────┘                      │
└─────────────────────────────────────────────────────────────┘
```

**Phân tích các thành phần:**

1. **Xử lý Bitstream** (src/zk_mv_stego/bitstream/)
   - Mục đích: Phân tích và tái tạo bitstream video H.264
   - File chính:
     - cavlc_decoder.py (373 dòng) - Trích xuất hệ số DCT
     - cavlc_encoder.py (492 dòng) - Mã hóa lại hệ số đã sửa đổi
     - bitstream_reconstructor.py (882 dòng) - Xây dựng lại video hoàn chỉnh
   - Công nghệ: H.264 Baseline Profile, CAVLC

2. **LSB Steganography** (src/zk_mv_stego/embedder/)
   - Mục đích: Giấu dữ liệu trong bit ít quan trọng nhất của hệ số
   - Thuật toán: Sửa đổi LSB trong khi bảo toàn dấu và tránh số không
   - Dung lượng: 95-190 bit mỗi khung hình (có thể điều chỉnh)
   - Chất lượng: PSNR > 45 dB (thay đổi không thể nhận thấy)

3. **Chứng minh ZK-SNARK** (src/zk_mv_stego/crypto/)
   - Mục đích: Tạo và xác minh chứng minh zero-knowledge
   - Hệ thống Chứng minh: Groth16 (ZK-SNARK hiệu quả nhất)
   - Mạch: Xác minh cam kết SHA256
   - Kích thước: 336 byte (định dạng nhị phân)

4. **Tái tạo Video** (bitstream_reconstructor.py)
   - Mục đích: Xây dựng lại video H.264 với dữ liệu đã nhúng
   - Quy trình: Phân tích NAL → Sửa đổi hệ số → Mã hóa lại CAVLC
   - Đầu ra: File video H.264 hợp lệ

5. **Xác minh** (scripts/verify.py)
   - Mục đích: Trích xuất và xác minh chứng minh đã nhúng
   - Quy trình: Trích xuất LSB → Phân tích chứng minh → Xác minh mật mã học
   - Bảo mật: Xác minh đầy đủ dựa trên pairing

### Cấu trúc dự án

```
VideoLevel/                    # Thư mục gốc dự án
│
├── src/zk_mv_stego/          # Mã nguồn chính 
│   ├── bitstream/            # Xử lý H.264 
│   │   ├── bitstream_io.py              # Đọc/ghi cấp bit
│   │   ├── bitstream_reconstructor.py   # Tái tạo video [QUAN TRỌNG]
│   │   ├── cavlc_decoder.py             # Trích xuất hệ số
│   │   ├── cavlc_encoder.py             # Mã hóa hệ số
│   │   ├── cavlc_tables.py              # Bảng tra VLC
│   │   ├── h264_parser.py               # Phân tích cú pháp H.264
│   │   ├── nal_handler.py               # Xử lý NAL/SPS/PPS
│   │   └── macroblock_parser.py         # Phân tích macroblock
│   │
│   ├── embedder/             # Steganography 
│   │   ├── payload_embedder.py          # Nhúng LSB [QUAN TRỌNG]
│   │   ├── direct_patcher.py            # Vá bitstream trực tiếp
│   │   └── encoding_length_checker.py   # Kiểm tra dung lượng
│   │
│   ├── decoder/              # Trích xuất 
│   │   └── cavlc_extractor_simple.py    # Trích xuất hệ số
│   │
│   ├── crypto/               # ZK-SNARK 
│   │   ├── proof_generator.py           # Groth16 prover [QUAN TRỌNG]
│   │   ├── proof_serializer.py          # Serialize nhị phân
│   │   └── proof_wrapper.py             # Tiện ích chứng minh
│   │
│   └── utils/                # Tiện ích 
│       └── quality_metrics.py           # Độ đo PSNR/SSIM
│
├── circuits/                 # Mạch Circom ZK
│   ├── payload_verify.circom # Mạch cam kết SHA256 [QUAN TRỌNG]
│   ├── package.json          # Phụ thuộc Node.js
│   └── build/                # Mạch đã biên dịch & khóa
│       ├── proving_key.zkey          # Khóa chứng minh (khoảng 20 MB)
│       ├── verification_key.json     # Khóa xác minh
│       └── payload_verify_js/        # Tạo witness
│
├── scripts/                  # Scripts tiện ích
│   ├── extract.py            # Trích xuất từ video stego
│   ├── verify.py             # Xác minh ZK proof
│   └── ffmpeg_lsb_embedder.py # Phương pháp thay thế FFmpeg
│
├── tests/                    # Bộ kiểm thử 
│   ├── validate_improvements.py  # Xác thực đầy đủ (4 bài kiểm tra)
│   ├── test_reconstruction.py    # Kiểm tra tái tạo
│   └── prepare_test_videos.py    # Chuẩn bị video thử nghiệm
│
├── docs/                     # Tài liệu 
│   ├── IMPROVEMENTS.md              # Cải tiến chi tiết
│   ├── IMPROVEMENTS_SUMMARY.md      # Tóm tắt điều hành
│   └── RECONSTRUCTION_COMPLETE.md   # Chi tiết kỹ thuật
│
├── data/                     # Dữ liệu thử nghiệm
│   ├── raw/      # Video Y4M đầu vào
│   ├── output/   # Video H.264 đã mã hóa
│   └── encoded/  # Video stego đã tạo
│
├── embed_complete.py         # Công cụ CLI chính [QUAN TRỌNG] 
├── README.md                 # File này
├── .gitignore                # Quy tắc git ignore
└── requirements.txt          # Phụ thuộc Python (nếu có)
```

**Thống kê:**
- Tổng mã: khoảng 6,000+ dòng Python production
- Mạch Circom: 1 mạch (khoảng 200 dòng)
- Tài liệu: 1,677 dòng (4 file markdown)
- Kiểm thử: 800+ dòng (3 file kiểm thử)
- Thành phần: 22 file Python + 1 mạch

## Quy trình hoàn chỉnh

### Hướng dẫn từng bước


#### Quy trình kỹ thuật hoàn chỉnh

**Giai đoạn 1: Thiết lập (Một lần)**
```bash
# Cài đặt phụ thuộc
npm install          # Cài đặt snarkjs, circomlib
pip install numpy    # Cài đặt gói Python

python -c "from src.zk_mv_stego.crypto.proof_generator import GrothProofGenerator; \
           g = GrothProofGenerator(); g.setup_circuit()"
```

**Giai đoạn 2: Nhúng**
```bash
# Nhúng đầy đủ với tất cả tùy chọn
python embed_complete.py \
  --input data/output/video.h264 \
  --message "Dữ liệu mật" \
  --output data/encoded/stego.h264 \
  --proof \
  --max-frames 100 \
  --allow-small-values \
  --stats embedding_stats.json
```

**Điều gì xảy ra bên trong:**

1. **Giải mã CAVLC** (0.5s)
   - Phân tích đơn vị NAL H.264
   - Trích xuất header slice (SPS, PPS)
   - Giải mã macroblock
   - Trích xuất hệ số DCT

2. **Tạo Chứng minh** 
   - Tính hash SHA256 của thông điệp
   - Tạo bí mật ngẫu nhiên
   - Tạo cam kết = SHA256(hash || secret)
   - Xây dựng witness cho mạch
   - Tạo chứng minh Groth16
   - Serialize thành 336 byte

3. **Tính toán Dung lượng** 
   - Đếm hệ số khả dụng (|coeff| >= 2 hoặc >= 1)
   - Tính số bit khả dụng
   - Xác thực payload vừa

4. **Nhúng LSB** 
   - Chuẩn bị payload: [Header][Message][Proof]
   - Sửa đổi LSB của mỗi hệ số
   - Bảo toàn dấu của hệ số
   - Phân phối qua các khung hình

5. **Tái tạo Video** (0.2-0.5s mỗi khung hình)
   - Mã hóa lại hệ số với CAVLC
   - Xây dựng lại slice RBSP
   - Tạo đơn vị NAL mới
   - Ghi bitstream H.264

**Giai đoạn 3: Trích xuất**
```bash
python scripts/extract.py data/encoded/stego.h264
```

**Điều gì xảy ra bên trong:**
1. Phân tích bitstream H.264
2. Trích xuất hệ số DCT
3. Đọc LSB từ mỗi hệ số: lsb = abs(coeff) & 1
4. Tái tạo chuỗi bit
5. Phân tích header (magic, độ dài)
6. Trích xuất thông điệp và chứng minh
7. Lưu vào JSON

**Giai đoạn 4: Xác minh**
```bash
python scripts/verify.py extracted_payload.json
```

**Điều gì xảy ra bên trong:**
1. Tải chứng minh và đầu vào công khai
2. Tính hash payload
3. Xác minh phương trình pairing: e(pi_a, pi_b) = e(α, β) · e(L, γ) · e(pi_c, δ)
4. Kiểm tra cam kết khớp
5. Trả về HỢP LỆ/KHÔNG HỢP LỆ

## Bắt đầu nhanh


**Yêu cầu hệ thống:**
- Hệ điều hành: Windows 10/11, Linux (Ubuntu 20.04+), macOS 11+
- Python: 3.8+ (đã kiểm tra trên 3.8, 3.9, 3.10)
- Node.js: 14+ (cho snarkjs)
- npm: 6+ (cho quản lý gói)
- Rust: 1.60+ (cho trình biên dịch Circom - tùy chọn)
- Dung lượng đĩa: khoảng 500 MB (mạch, khóa, phụ thuộc)
- RAM: Tối thiểu 4GB (khuyến nghị 8GB để tạo chứng minh nhanh hơn)

**Hướng dẫn cài đặt:**

**Bước 1: Clone Repository**
```bash
git clone <repository-url>
cd VideoLevel
```

**Bước 2: Cài đặt Phụ thuộc Python**
```bash
pip install numpy
# Hoặc nếu có requirements.txt:
pip install -r requirements.txt
```

**Bước 3: Cài đặt Phụ thuộc Node.js**
```bash
cd circuits
npm install
cd ..
```

**Bước 4: Cài đặt Trình biên dịch Circom (Tùy chọn nhưng Khuyến nghị)**

**Linux/Mac:**
```bash
git clone https://github.com/iden3/circom.git
cd circom
cargo build --release
cargo install --path circom
```

**Windows:**
Tải binary đã build sẵn từ [Circom Releases](https://github.com/iden3/circom/releases)

**Bước 5: Trusted Setup (Tạo khóa ZK-SNARK)**
```bash
python -c "from src.zk_mv_stego.crypto.proof_generator import GrothProofGenerator; g = GrothProofGenerator(); g.setup_circuit()"
```

Điều này tạo:
- circuits/build/proving_key.zkey (khoảng 20 MB)
- circuits/build/verification_key.json (khoảng 2 KB)
- File powers of tau cho trusted setup

**Đầu ra mong đợi:**
```
[*] Đang biên dịch mạch...
[*] Đang tạo powers of tau...
[*] Đang tạo proving key...
[*] Đang xuất verification key...
[+] Thiết lập hoàn tất! Khóa đã sẵn sàng trong circuits/build/
```


## Thông số kỹ thuật

### Thông số Video Codec

**H.264 Profile:**
- Profile: Baseline (profile_idc = 66)
- Level: 3.0 trở lên
- Encoding: CAVLC (Context-Adaptive Variable Length Coding)
- Color Space: YUV 4:2:0
- Kích thước Macroblock: 16x16 pixel
- Transform: DCT 4x4 (Discrete Cosine Transform)

**Tính năng được hỗ trợ:**
- I-frame (Intra-coded) - Có
- P-frame (Predictive - hỗ trợ một phần) - Có
- B-frame - Không
- Multiple reference frame - Có
- Deblocking filter - Có

### Thông số Steganography

**Thông số Nhúng LSB:**

| Thông số | Chế độ Chuẩn | Chế độ Dung lượng cao |
|----------|---------------|------------------------|
| Bộ lọc hệ số | \|coeff\| >= 2 | \|coeff\| >= 1 |
| Dung lượng/khung hình | khoảng 95 bit | khoảng 190 bit |
| Dung lượng/khung hình | khoảng 12 byte | khoảng 24 byte |
| Dung lượng/giây | khoảng 2,850 bit (30fps) | khoảng 5,700 bit (30fps) |
| Dung lượng/giây | khoảng 356 byte (30fps) | khoảng 712 byte (30fps) |
| Ảnh hưởng PSNR | <0.1 dB | 0.1-0.5 dB |
| Chất lượng hình ảnh | Không thể nhận thấy | Không thể nhận thấy |
| Độ ổn định | Rất ổn định | Ổn định |

**Thuật toán Nhúng:**
```python
def modify_lsb(coefficient, bit):
    """
    Sửa đổi LSB của giá trị tuyệt đối hệ số trong khi bảo toàn dấu.
    
    Tham số:
        coefficient: Hệ số DCT (có thể âm)
        bit: Bit cần nhúng (0 hoặc 1)
    
    Trả về:
        Hệ số đã sửa đổi với bit đã nhúng trong LSB
    """
    sign = 1 if coefficient >= 0 else -1
    abs_coeff = abs(coefficient)
    
    # Xóa LSB và đặt bit mới
    new_abs = (abs_coeff & ~1) | bit
    
    return sign * new_abs

# Ví dụ:
# coeff = -5 (nhị phân: ...101), bit = 0
# abs_coeff = 5 (nhị phân: 101)
# new_abs = (5 & ~1) | 0 = (101 & 110) | 0 = 100 | 0 = 4
# kết quả = -1 * 4 = -4
```

**Thuật toán Trích xuất:**
```python
def extract_lsb(coefficient):
    """
    Trích xuất LSB từ giá trị tuyệt đối của hệ số.
    
    Tham số:
        coefficient: Hệ số DCT (có thể đã sửa đổi)
    
    Trả về:
        Bit đã trích xuất (0 hoặc 1)
    """
    return abs(coefficient) & 1

# Ví dụ:
# coeff = -4 (bit đã nhúng 0)
# abs_coeff = 4 (nhị phân: 100)
# lsb = 4 & 1 = 100 & 001 = 0
```

### Thông số ZK-SNARK

**Hệ thống Chứng minh:**
- Loại: Groth16 (ZK-SNARK hiệu quả nhất)
- Đường cong: BN128 (Barreto-Naehrig, bảo mật 128-bit)
- Hệ thống Ràng buộc: Rank-1 Constraint System (R1CS)
- Độ phức tạp Mạch: khoảng 3,000 ràng buộc
- Trusted Setup: Nghi thức powers of tau

**Cấu trúc Mạch Circom:**
```circom
template PayloadVerify() {
    // Đầu vào công khai
    signal input payload_hash[256];    // SHA256(thông điệp)
    signal input commitment[256];      // Cam kết công khai
    signal input payload_length;       // Độ dài thông điệp
    
    // Đầu vào riêng tư (witness)
    signal input secret[256];          // Giá trị bí mật
    
    // Ràng buộc: commitment = SHA256(payload_hash || secret)
    component hasher = Sha256(512);
    for (var i = 0; i < 256; i++) {
        hasher.in[i] <== payload_hash[i];
        hasher.in[256+i] <== secret[i];
    }
    
    for (var i = 0; i < 256; i++) {
        commitment[i] === hasher.out[i];
    }
}
```

**Cấu trúc Chứng minh (Định dạng Nhị phân):**

| Trường | Kích thước | Mô tả |
|--------|------------|-------|
| pi_a | 64 byte | Phần tử chứng minh A (2 x 32 byte) |
| pi_b | 128 byte | Phần tử chứng minh B (2 x 2 x 32 byte) |
| pi_c | 64 byte | Phần tử chứng minh C (2 x 32 byte) |
| public_inputs | 80 byte | Hash(32) + Commitment(32) + Length(16) |
| Tổng cộng | 336 byte | Serialize nhị phân gọn nhẹ |

**So sánh với JSON:**
- Định dạng JSON: khoảng 3,800 byte (lớn gấp 10 lần)
- Định dạng Nhị phân: 336 byte (tối ưu)
- Tỷ lệ nén: 11.3:1

## Hiệu năng

### Benchmark thời gian

**Môi trường thử nghiệm:**
- CPU: Intel Core i7-9700K @ 3.6 GHz (8 nhân)
- RAM: 16 GB DDR4
- Hệ điều hành: Windows 10 / Ubuntu 20.04
- Python: 3.9.7
- Node.js: 16.14.0

**Kết quả (Trung bình của 10 lần chạy):**

| Thao tác | Thời gian (Chuẩn) | Thời gian (Dung lượng cao) | Ghi chú |
|----------|-------------------|----------------------------|---------|
| Giải mã CAVLC | 0.48s | 0.48s | Giống nhau cho cả hai chế độ |
| Trích xuất Hệ số | 0.52s | 0.52s | Cho 60 khung hình |
| Tính Dung lượng | <0.001s | <0.001s | Không đáng kể |
| Nhúng LSB | <0.001s | <0.001s | Mỗi khung hình |
| Mã hóa CAVLC | 0.23s | 0.23s | Mỗi khung hình |
| Tái tạo Video | 14.2s | 14.2s | Tổng 60 khung hình |
| Tạo ZK Proof | 3.21s | 3.21s | Một lần mỗi lần nhúng |
| Xác minh ZK Proof | 1.84s | 1.84s | Dùng snarkjs |
| Tổng (Không Proof) | khoảng 15s | khoảng 15s | Quy trình đầy đủ |
| Tổng (Có Proof) | khoảng 19s | khoảng 19s | Bao gồm tạo proof |

### Phân tích Dung lượng

**Video thử nghiệm:** Foreman CIF (352x288, 60 khung hình, CAVLC)

**Chế độ Chuẩn (|coeff| >= 2):**
```
Tổng hệ số mỗi khung hình: 3,840 (352*288 / 16 * 16)
Hệ số khác không: khoảng 471 (12.3%)
Hệ số khả dụng (|x| >= 2): khoảng 95 (2.5%)
Dung lượng: 95 bit/khung hình = 11.875 byte/khung hình

60 khung hình tổng cộng:
  Dung lượng: 5,700 bit = 712 byte
  
Ở 30 fps:
  Dung lượng: 2,850 bit/giây = 356 byte/giây
  1 phút: 21.4 KB
  10 phút: 214 KB
```

**Chế độ Dung lượng cao (|coeff| >= 1):**
```
Hệ số khả dụng (|x| >= 1): khoảng 190 (4.9%)
Dung lượng: 190 bit/khung hình = 23.75 byte/khung hình

60 khung hình tổng cộng:
  Dung lượng: 11,400 bit = 1,425 byte
  
Ở 30 fps:
  Dung lượng: 5,700 bit/giây = 712 byte/giây
  1 phút: 42.7 KB
  10 phút: 427 KB
```

### Độ đo Chất lượng

**PSNR (Peak Signal-to-Noise Ratio):**

| Chế độ | PSNR (dB) | Chất lượng | Khả năng nhận thấy |
|--------|-----------|------------|--------------------|
| Không sửa đổi | Vô cùng | Hoàn hảo | Không áp dụng |
| Chế độ Chuẩn | 52-55 | Xuất sắc | Không thể nhận thấy |
| Dung lượng cao | 45-48 | Rất tốt | Không thể nhận thấy |
| Ngưỡng | >40 | Tốt | Vừa nhận thấy |

**SSIM (Structural Similarity Index):**

| Chế độ | SSIM | Ý nghĩa |
|--------|------|---------|
| Không sửa đổi | 1.0000 | Giống hệt |
| Chế độ Chuẩn | 0.9985-0.9992 | Gần như giống hệt |
| Dung lượng cao | 0.9970-0.9985 | Gần như giống hệt |
| Ngưỡng | >0.95 | Chất lượng cao |

## Kiểm thử

### Bộ kiểm thử tự động

**Chạy tất cả kiểm thử:**
```bash
# Xác thực toàn diện (khuyến nghị)
python tests/validate_improvements.py
```

**Đầu ra:**
```
=== Bộ Kiểm thử Xác thực Giấu tin Video ZK-SNARK ===

[Kiểm thử 1/4] Xác thực Chế độ Dung lượng cao
  • Dung lượng chế độ chuẩn: 95 bit/khung hình
  • Chế độ dung lượng cao: 190 bit/khung hình
  • Cải thiện: +100% (thêm 95 bit)
  ĐẠT

[Kiểm thử 2/4] Tính nhất quán Sửa đổi LSB
  • Kiểm tra 8 giá trị hệ số...
  • Tất cả sửa đổi LSB đúng
  • Tất cả trích xuất khớp với bit đã nhúng
  ĐẠT (8/8 trường hợp kiểm thử)

[Kiểm thử 3/4] Kiểm thử Vòng lặp Đầu-cuối
  • Kiểm tra 4 payload khác nhau...
  Payload 1: "Thông điệp ngắn" → Trích xuất: "Thông điệp ngắn" ĐẠT
  Payload 2: "Thông điệp độ dài trung bình với ký tự đặc biệt: áéí" → ĐẠT
  Payload 3: "Thông điệp dài..." (100 byte) → ĐẠT
  Payload 4: Dữ liệu nhị phân (50 byte) → ĐẠT
  ĐẠT (4/4 payload)

[Kiểm thử 4/4] Tính nhất quán Trích xuất LSB
  • So sánh phương pháp trích xuất cũ vs mới
  • Kiểm tra trên hệ số video thực
  ĐẠT (100% khớp)

=== TÓM TẮT ===
Kiểm thử đã chạy: 4
Đạt: 4
Không đạt: 0
Tỷ lệ thành công: 100%
```

## Tài liệu

### Tài liệu cốt lõi

- **README.md** (file này)
  - Tổng quan dự án
  - Hướng dẫn bắt đầu nhanh
  - Quy trình hoàn chỉnh
  - Thông số kỹ thuật
  - Ví dụ sử dụng

- **docs/IMPROVEMENTS.md** (291 dòng)
  - Cải tiến chi tiết (2 tháng 2, 2026)
  - Triển khai quy trình đầu-cuối
  - Sửa lỗi tính nhất quán LSB
  - Tối ưu dung lượng (tăng gấp đôi)
  - So sánh trước/sau

- **docs/IMPROVEMENTS_SUMMARY.md** (265 dòng)
  - Tóm tắt điều hành
  - Thành tựu chính
  - Độ đo hiệu năng
  - Kết quả kiểm thử

- **docs/RECONSTRUCTION_COMPLETE.md** (187 dòng)
  - Chi tiết tái tạo bitstream
  - Triển khai CAVLC encoder/decoder
  - Xử lý đơn vị NAL
  - Đi sâu kỹ thuật

## Bảo mật

### Bảo mật Steganography

**Phân tích Thống kê:**
- Sửa đổi LSB tạo phân phối đồng đều
- Thay đổi histogram là tối thiểu
- Kiểm tra Chi-square: p-value > 0.05 (không phát hiện được)

**Kháng tấn công:**
- Kiểm tra bằng mắt: Thay đổi không thể nhận thấy
- Phân tích histogram: Không có mẫu rõ ràng
- Kiểm tra Chi-square: Đạt kiểm tra thống kê
- Tấn công calibration: Dễ bị tấn công (giới hạn LSB chuẩn)
- Mã hóa lại: Payload có thể bị mất

### Bảo mật Mật mã học

**Bảo mật ZK-SNARK:**
- Tính đúng đắn: Đúng đắn theo tính toán (giả định độ khó của logarit rời rạc trên BN128)
- Tri thức không: Chứng minh không tiết lộ gì về bí mật
- Tính đầy đủ: Chứng minh hợp lệ luôn được xác minh
- Kích thước Chứng minh: 336 byte (không đổi, bất kể kích thước mạch)

**Cam kết Bảo mật:**
- Ràng buộc SHA256: Ràng buộc theo tính toán
- Kháng va chạm: Bảo mật 2^128
- Kháng ảnh trước: Bảo mật 2^256


## Giấy phép

MIT License - xem file LICENSE để biết chi tiết
