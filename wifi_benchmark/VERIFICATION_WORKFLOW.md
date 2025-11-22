# Workflow Verification và Extraction từ Stego Image

## Tổng quan

Hệ thống sử dụng **Hybrid Approach** để lưu trữ proof và message:
1. **PNG Chunk Metadata**: Lưu chaos parameters và public inputs (không cần secret key để đọc)
2. **Pixel Data (LSB)**: Lưu proof và message sử dụng chaos-based positioning (cần chaos parameters để extract)

## Quy trình khi Verifier nhận ảnh Stego

### Bước 1: Extract Metadata từ PNG Chunk (Không cần secret key)

```python
from zk_stego.hybrid_proof_artifact import extract_chaos_proof

# Verifier chỉ cần ảnh stego, KHÔNG cần secret key
artifact = extract_chaos_proof("stego_image.png")
```

**Metadata chứa:**
- `chaos`: Chaos parameters (x0, y0, chaos_key, proof_length, algorithm, etc.)
- `public`: Public inputs cho ZK verification (image_hash, commitment_root, etc.)
- `meta`: Metadata về version, algorithm
- `timestamp`: Thời gian tạo

### Bước 2: Extract Proof từ Pixel Data

Sử dụng chaos parameters từ metadata để extract proof:

```python
# Chaos parameters đã có trong metadata, không cần secret key
chaos_metadata = artifact["chaos"]
x0 = chaos_metadata["initial_position"]["x"]
y0 = chaos_metadata["initial_position"]["y"]
chaos_key = chaos_metadata["chaos_key"]  # Đã được lưu trong metadata!
proof_length = chaos_metadata["proof_length"]

# Extract proof từ pixel data
proof_bytes = chaos_artifact.extract_proof_chaos(
    stego_array, chaos_metadata
)
proof_json = json.loads(proof_bytes.decode('utf-8'))
```

### Bước 3: Verify ZK Proof

```python
from zk_stego.zk_proof_generator import ZKProofGenerator

zk_gen = ZKProofGenerator()
is_valid = zk_gen.verify_proof(
    proof_json,  # Từ bước 2
    artifact["public"]  # Từ metadata
)
```

### Bước 4: Extract Message (Nếu cần)

Nếu verifier muốn extract message, cần biết:
- Message length (có thể từ metadata hoặc cần thông tin thêm)
- Chaos parameters (đã có trong metadata)

```python
from zk_stego.chaos_embedding import ChaosEmbedding

chaos_embed = ChaosEmbedding(stego_array)
message = chaos_embed.extract_message(
    message_length,  # Cần biết độ dài message
    secret_key  # Cần secret key để generate chaos_key
)
```

**Lưu ý:** Nếu `chaos_key` đã được lưu trong metadata, có thể không cần secret_key.

## Điểm quan trọng

### ✅ Verifier CÓ THỂ verify proof mà KHÔNG cần secret key vì:

1. **Chaos parameters được lưu trong PNG chunk metadata**
   - `x0`, `y0`: Initial position
   - `chaos_key`: Key để generate positions
   - `proof_length`: Độ dài proof
   - Tất cả đều có trong metadata chunk

2. **Public inputs có trong metadata**
   - `image_hash`: Hash của ảnh gốc
   - `commitment_root`: Commitment của positions
   - Đủ để verify ZK proof

3. **Proof được extract từ pixel data**
   - Sử dụng chaos parameters từ metadata
   - Không cần secret key nếu chaos_key đã có trong metadata

### ⚠️ Verifier CẦN secret key nếu muốn extract message:

- Message length có thể không có trong metadata
- Secret key cần để verify/regenerate chaos sequence cho message
- Nhưng nếu chỉ verify proof thì KHÔNG cần

## Workflow trong Benchmark

Trong benchmark hiện tại:
1. **Máy A (Sender)**: Tạo stego image với proof và message
2. **Máy B (Receiver)**: Nhận ảnh stego qua WiFi
3. **Verifier**: Có thể verify proof ngay từ ảnh nhận được

**Verifier không cần:**
- Secret key (nếu chỉ verify proof)
- Original image
- Bất kỳ thông tin nào khác ngoài ảnh stego

**Verifier chỉ cần:**
- Ảnh stego (đã có proof và metadata)
- Verification key (public key của ZK-SNARK, có thể hardcode hoặc lấy từ metadata)

## Demo Code

```python
# Verifier workflow
from zk_stego.hybrid_proof_artifact import extract_chaos_proof
from zk_stego.zk_proof_generator import ZKProofGenerator

# 1. Extract toàn bộ artifact từ ảnh stego
artifact = extract_chaos_proof("stego_image.png")

if artifact:
    # 2. Verify ZK proof
    zk_gen = ZKProofGenerator()
    is_valid = zk_gen.verify_proof(
        artifact["proof"],
        artifact["public"]
    )
    
    if is_valid:
        print("✓ Proof verified! Message was correctly embedded.")
        print(f"  Timestamp: {artifact['timestamp']}")
        print(f"  Algorithm: {artifact['chaos']['algorithm']}")
    else:
        print("✗ Proof verification failed!")
else:
    print("✗ No proof found in image!")
```

## Kết luận

**Benchmark chỉ gửi ảnh stego là ĐỦ** vì:
- Tất cả thông tin cần thiết đã được embed trong ảnh
- Metadata (chaos parameters, public inputs) trong PNG chunk
- Proof và message trong pixel data
- Verifier có thể verify mà không cần thêm thông tin


