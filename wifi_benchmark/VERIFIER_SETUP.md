# Hướng dẫn Setup Verifier System

## Tổng quan

**QUAN TRỌNG:** Trước khi verifier có thể verify ảnh stego, họ cần được cung cấp **Verifier Package** và setup hệ thống.

## Workflow đầy đủ

### Phase 1: Tạo và Gửi Verifier Package (Máy A - Sender)

**Bước 1: Tạo Verifier Package**

```bash
python wifi_benchmark/create_verifier_package.py
```

Package sẽ được tạo trong thư mục `verifier_package/` với cấu trúc:
```
verifier_package/
├── src/zk_stego/              # Source code để extract/verify
│   ├── hybrid_proof_artifact.py
│   ├── chaos_embedding.py
│   ├── zk_proof_generator.py
│   └── __init__.py
├── circuits/compiled/build/
│   └── verification_key.json  # ← QUAN TRỌNG: Public key
├── scripts/
│   └── verify.py               # Script verify đơn giản
├── requirements.txt            # Python dependencies
├── setup.sh                    # Setup script (Linux/Mac)
├── setup.bat                   # Setup script (Windows)
└── README.md                   # Hướng dẫn
```

**Bước 2: Gửi Package cho Verifier**

- Zip folder `verifier_package/`
- Gửi qua email/USB/cloud/network
- Verifier giải nén và setup

### Phase 2: Setup Verifier System (Máy B - Verifier)

**Bước 1: Giải nén package**

```bash
unzip verifier_package.zip
cd verifier_package
```

**Bước 2: Chạy setup script**

**Linux/Mac:**
```bash
chmod +x setup.sh
./setup.sh
```

**Windows:**
```cmd
setup.bat
```

Setup script sẽ:
- Kiểm tra Node.js và npm
- Cài đặt `snarkjs` (npm package)
- Kiểm tra Python
- Cài đặt Python dependencies (pillow, numpy)

**Bước 3: Kiểm tra setup**

```bash
python scripts/verify.py --help
```

Nếu setup thành công, sẽ thấy help message.

### Phase 3: Verification (Sau khi nhận ảnh stego)

**Verifier đã có:**
- ✅ Software đã được setup
- ✅ Verification key đã được cài đặt
- ✅ Dependencies đã được cài đặt

**Verifier nhận:**
- 📷 Ảnh stego (qua WiFi, email, USB, etc.)

**Verifier thực hiện:**
```bash
python scripts/verify.py stego_image.png
```

Hoặc với verbose output:
```bash
python scripts/verify.py stego_image.png -v
```

## Chi tiết các thành phần

### 1. Verification Key (verification_key.json)

**Vị trí:** `circuits/compiled/build/verification_key.json`

**Nội dung:**
- Public key của ZK-SNARK circuit
- Được tạo trong trusted setup phase
- Cần để verify proof
- **KHÔNG cần bảo mật** (public key)

**Cách sử dụng:**
- Được load tự động bởi `ZKProofGenerator`
- Hoặc có thể chỉ định đường dẫn

### 2. Verification Software

**Các file cần thiết:**
- `src/zk_stego/hybrid_proof_artifact.py` - Extract proof từ ảnh
- `src/zk_stego/chaos_embedding.py` - Chaos-based extraction
- `src/zk_stego/zk_proof_generator.py` - ZK proof verification
- `scripts/verify.py` - Script verify đơn giản

### 3. Dependencies

**Node.js:**
- `snarkjs` (npm package) - Để verify ZK proof

**Python:**
- `pillow` (PIL) - Xử lý ảnh
- `numpy` - Tính toán
- `json` - Xử lý JSON (built-in)

## Tạo Verifier Package

Tôi sẽ tạo script để package tất cả thành phần cần thiết cho verifier.

