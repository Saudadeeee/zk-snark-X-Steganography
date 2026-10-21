# Đường hậu lượng tử lattice (legacy)

> Tài liệu legacy mô tả subsystem tiền-lattice-ZK (đã đóng băng, vẫn được giữ và
> có test). Các đường dẫn module bên trong đã cũ sau đợt dọn dẹp 10/2026 (ví dụ
> `src.lattice_pq` nay ở `src.registry.lattice_pq`, `src.embedder`/`src.verifier`
> nay ở `src.legacy`). Backend lattice-ZK hiện tại là một hệ khác; xem
> [../LATTICE_ZK_BDLOP_PLAN.md](../LATTICE_ZK_BDLOP_PLAN.md).

Nhánh `feature/lattice-pq-stack` thêm một đường mật mã lattice opt-in mà không
cố nhồi một proof lattice nhiều kilobyte vào payload H.264 CAVLC.

## Cấu trúc đang hoạt động

- ML-DSA-65 ký biên nhận message và stego manifest v3.
- ML-KEM-768 có sẵn để encapsulate một shared secret cho kênh transport
  prover/receiver từ xa.
- Video nhúng `[LQ1 | độ dài message | message | hash biên nhận 32-byte]`.
- `<stego>.lattice.json` lưu biên nhận đã ký; manifest đã ký gắn hash stego và
  hash các vị trí nhúng.

Đây là một đường **chứng thực (attestation)** dựa trên lattice, không phải một
chứng minh lattice ZK tổng quát. Nó không tuyên bố tính chất zero-knowledge mà
Groth16 cung cấp.

## Backend lattice zero-knowledge

Một backend nghiên cứu riêng trong `src/lattice_zk/` thực sự mang một proof
lattice ZK bên trong video: một cam kết BDLOP với chứng minh
Fiat-Shamir-with-aborts về tri thức opening của nó, gắn với video đã chuẩn hóa
carrier, session challenge và relation registry đã ký, và verify chỉ từ video
stego. Giao thức, tham số, tuyên bố, giới hạn và trạng thái ở
[../LATTICE_ZK_BDLOP_PLAN.md](../LATTICE_ZK_BDLOP_PLAN.md). Nó tự cài đặt từ giao
thức đã công bố và chưa audit. Đường ML-DSA dưới đây không đổi.

## Cách dùng

```python
from src.lattice_pq import LatticeSigner
from src.embedder import embed
from src.verifier import verify

public_key, private_key = LatticeSigner.generate_keypair()
result = embed(
    video_path="cover.h264",
    output_path="stego.h264",
    message=b"authenticated payload",
    circuits_dir="circuits",  # giữ cho tương thích API; không dùng ở chế độ lattice
    secret_key=bytes(32),      # giữ cho tương thích API; không dùng ở chế độ lattice
    proof_backend="lattice",
    lattice_private_key=private_key,
)

verification = verify(
    stego_video_path="stego.h264",
    original_video_path="cover.h264",
    circuits_dir="circuits",
    secret_key=bytes(32),
    message_length=len(b"authenticated payload"),
    proof_backend="lattice",
    lattice_public_key=public_key,
)
assert verification.valid
```

## Trạng thái kiểm thử

Biên nhận ML-DSA, encapsulation ML-KEM, chữ ký manifest, định dạng
video-reference và serialization sidecar có độ phủ unit test. E2E lattice H.264
đầy đủ vẫn còn hoãn vì đường tái dựng của nó vượt cửa sổ test có giới hạn; phải
chạy lại trên một test asset chuyên dụng trước khi release.
