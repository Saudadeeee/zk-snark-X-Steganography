# ZK-SNARK Steganography Verifier Package

## Setup

### 1. Cài đặt Node.js và snarkjs

```bash
# Cài đặt Node.js (nếu chưa có)
# Download từ: https://nodejs.org/

# Cài đặt snarkjs
npm install -g snarkjs
```

### 2. Cài đặt Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Kiểm tra setup

```bash
python scripts/verify.py --help
```

## Sử dụng

### Verify ảnh stego

```bash
python scripts/verify.py path/to/stego_image.png
```

### Verify với verbose output

```bash
python scripts/verify.py path/to/stego_image.png -v
```

### Verify và output JSON

```bash
python scripts/verify.py path/to/stego_image.png --json
```

## Cấu trúc Package

```
verifier_package/
├── src/zk_stego/          # Source code để extract/verify
├── circuits/compiled/build/
│   └── verification_key.json  # Public key (không cần bảo mật)
├── scripts/
│   └── verify.py          # Script verify
├── requirements.txt        # Python dependencies
└── README.md              # File này
```

## Lưu ý

- **Verification key** là public key, không cần bảo mật
- **Secret key** KHÔNG cần thiết để verify proof (chỉ cần để extract message)
- Tất cả thông tin cần thiết đã có trong ảnh stego (metadata + proof)
