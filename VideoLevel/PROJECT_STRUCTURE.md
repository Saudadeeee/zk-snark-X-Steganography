# ZK-SNARK Video Steganography - Core System

## 📁 Project Structure

```
VideoLevel/
├── src/zk_mv_stego/              # Core steganography system
│   ├── bitstream/                 # H.264 bitstream processing
│   │   ├── h264_parser.py         # NAL unit parser
│   │   ├── cavlc_encoder.py       # CAVLC encoder
│   │   ├── cavlc_decoder.py       # CAVLC decoder  
│   │   ├── bitstream_reconstructor.py  # Video reconstruction
│   │   └── ...
│   ├── crypto/                    # Cryptographic components
│   │   ├── proof_generator.py     # ZK-SNARK proof generation
│   │   ├── rc4_cipher.py          # RC4 encryption
│   │   └── ...
│   ├── embedder/                  # Payload embedding
│   │   ├── payload_embedder.py    # DCT coefficient embedding
│   │   ├── cavlc_safety_filter.py # CAVLC safety rules
│   │   ├── embedding_coordinator.py # Pipeline coordinator
│   │   └── ...
│   ├── decoder/                   # Coefficient extraction
│   │   └── cavlc_extractor_simple.py
│   └── exceptions.py              # Custom exceptions
│
├── circuits/                      # ZK-SNARK circuits (Circom)
│   ├── payload_verify.circom      # Verification circuit
│   └── build/                     # Compiled circuit artifacts
│
├── data/
│   ├── raw/                       # Original test videos
│   │   ├── foreman_cif.h264
│   │   ├── bus_cif.h264
│   │   └── ...
│   ├── encoded/                   # (empty - for stego outputs)
│   └── output/                    # (empty - for test outputs)
│
├── zk_snark_workflow_v3.py        # Main workflow (embed/extract)
├── benchmark_video_quality.py     # Quality measurement tool
├── requirements.txt               # Python dependencies
└── README.md                      # Documentation
```

## 🚀 Core Components

### 1. **ZK-SNARK Workflow** (`zk_snark_workflow_v3.py`)
- Complete embedding/extraction pipeline
- CAVLC Safety Filter integration
- RC4 encryption + LDPC error correction
- Bitstream drift compensation

### 2. **CAVLC Safety Filter** (`cavlc_safety_filter.py`)
- 5 safety rules prevent bitstream corruption:
  1. Zero preservation
  2. Trailing ones protection
  3. DC coefficient skip
  4. Bit-length invariance
  5. Sign bit preservation

### 3. **Bitstream Reconstructor** (`bitstream_reconstructor.py`)
- CAVLC re-encoding with modified DCT coefficients
- NAL unit structure preservation
- H.264 compliance maintained

### 4. **Quality Benchmark Tool** (`benchmark_video_quality.py`)
- PSNR measurement (Peak Signal-to-Noise Ratio)
- SSIM calculation (Structural Similarity Index)
- DCT domain and pixel domain comparison

## 📊 Usage

### Embed ZK Proof into Video:
```bash
python zk_snark_workflow_v3.py embed \
  --input data/raw/foreman_cif.h264 \
  --proof proof.bin \
  --output stego.h264 \
  --key secret_key_hex
```

### Extract ZK Proof from Video:
```bash
python zk_snark_workflow_v3.py extract \
  --input stego.h264 \
  --output extracted_proof.bin \
  --key secret_key_hex \
  --metadata stego.h264.meta.json \
  --chunks 10
```

### Measure Video Quality:
```bash
python benchmark_video_quality.py \
  --original data/raw/foreman_cif.h264 \
  --stego stego.h264 \
  --frames 5 \
  --output results.json
```

## ✨ Key Features

- ✅ **Zero Corruption Risk**: CAVLC Safety Filter ensures valid H.264
- ✅ **High Capacity**: ~70% of non-zero DCT coefficients usable
- ✅ **Cryptographic Security**: RC4 encryption + ZK-SNARK proofs
- ✅ **Quality Preservation**: SSIM > 0.97 (excellent visual quality)
- ✅ **Error Correction**: LDPC codes for robustness

## 📚 Documentation

See [README.md](README.md) for detailed documentation.
