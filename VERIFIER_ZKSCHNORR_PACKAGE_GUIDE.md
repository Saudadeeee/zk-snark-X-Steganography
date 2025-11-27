# ZK-Schnorr Verifier Package - Setup Guide

## 📦 Package đã tạo thành công!

Bạn đã có:
- ✅ `download_verifier_zkschnorr_package.py` - Script download package từ server
- ✅ `verifier_zkschnorr_package/` - Verifier package hoàn chỉnh

## 📁 Cấu trúc Package

```
verifier_zkschnorr_package/
├── README.md                    # Hướng dẫn sử dụng chi tiết
├── requirements.txt             # Python dependencies (numpy, Pillow)
├── setup.sh                     # Linux/Mac setup script
├── setup.bat                    # Windows setup script
├── demo_stego_with_proof.png    # Demo image để test
├── demo_proof.json              # Proof JSON reference
├── src/
│   ├── zk_stego/               # Chaos embedding utilities
│   │   ├── __init__.py
│   │   └── chaos_embedding.py
│   └── zk_schnorr/             # Schnorr proof system
│       ├── __init__.py
│       ├── schnorr_proof.py
│       └── chaos_schnorr_pipeline.py
└── scripts/
    └── verify_schnorr.py        # Main verification script
```

## 🚀 Cách sử dụng

### 1. Setup Package (lần đầu)

```bash
cd verifier_zkschnorr_package
pip install -r requirements.txt
```

Hoặc chạy script setup:
- **Windows**: `setup.bat`
- **Linux/Mac**: `./setup.sh`

### 2. Verify ảnh stego

```bash
# Basic verification
python scripts/verify_schnorr.py demo_stego_with_proof.png -v

# Output:
# ✓ Schnorr proof metadata extracted
# ✓ Proof verification: VALID
```

### 3. Extract message (nếu có chaos key)

```bash
python scripts/verify_schnorr.py demo_stego_with_proof.png \
    --extract --chaos-key demo-chaos-key-2024 -v
```

## 🎯 Test đã thành công

```
Analyzing steganographic image: demo_stego_with_proof.png
✓ Schnorr proof metadata extracted
  Feature point: (452, 460)
  Message bits: 528
  Timestamp: 1764149026
✓ Proof verification: VALID
```

## 🌐 Deploy lên Server

### Bước 1: Copy package lên server

```bash
scp -r verifier_zkschnorr_package/ user@192.168.1.119:/var/www/html/
```

### Bước 2: Client download

```bash
python download_verifier_zkschnorr_package.py
```

Script sẽ download tất cả files cần thiết từ:
- `http://192.168.1.119:8006/verifier_zkschnorr_package/`

## ⚡ So sánh với ZK-SNARK

| Feature | ZK-SNARK Package | ZK-Schnorr Package |
|---------|-----------------|-------------------|
| Dependencies | Node.js, snarkjs, Python | Chỉ Python |
| Setup Time | ~5-10 minutes | ~1 minute |
| Verification Speed | ~5-10 ms | < 1 ms |
| Proof Size | ~192 bytes | ~64 bytes |
| Complexity | High | Low |

## 📝 Các lệnh hay dùng

```bash
# Help
python scripts/verify_schnorr.py --help

# Verbose verification
python scripts/verify_schnorr.py image.png -v

# JSON output
python scripts/verify_schnorr.py image.png --json

# Full verification with message extraction
python scripts/verify_schnorr.py image.png \
    --extract --chaos-key your-secret -v
```

## 🔧 Troubleshooting

### "No valid Schnorr proof artifact found"
- Ảnh không chứa Schnorr proof metadata
- Ảnh đã bị compress/resize
- Sử dụng `create_demo_schnorr_stego.py` để tạo ảnh test mới

### Import errors
- Chạy từ đúng directory: `cd verifier_zkschnorr_package`
- Kiểm tra Python path

## 🎉 Hoàn thành!

Package ZK-Schnorr verifier đã sẵn sàng để:
- ✅ Verify Schnorr steganographic proofs
- ✅ Extract hidden messages (với chaos key)
- ✅ Deploy lên server để phân phối
- ✅ So sánh performance với zkSNARK

---

**Created**: 2025-11-26  
**Tested**: ✅ PASS - Verification working correctly
