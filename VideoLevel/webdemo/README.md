# ZK-Video Studio (webdemo)

Ứng dụng web chạy thật trong trình duyệt, dựng lại pipeline của hệ thống
steganography H.264 + chứng minh zero-knowledge trên lattice (BDLOP):
phân tích khung → commitment → chứng minh ZKP → nhúng vào carrier →
kiểm tra mù từ video + mô phỏng tấn công.

Cập nhật: 2026-10-22.

## Mức "thật" tới đâu
- **Thật:** số học vành R_q = Z_q[X]/(X^N+1); commitment BDLOP; chứng minh mở
  kiểu Lyubashevsky với Fiat–Shamir **có abort** (rejection sampling); verify
  thật; ràng buộc statement bằng digest video + thử thách phiên; chống
  tamper/replay; nhúng/trích LSB carrier; PSNR/SSIM. Chọn bộ **Sản xuất (N=256)**
  chạy đúng tham số `bdlop-open-128-v3` (N=256, q=2³⁰−35, width=15, κ=60).
- **Mô phỏng:** biến đổi khung dùng **DCT 8×8 + lượng tử hoá** thay cho biến đổi
  nội khung H.264 Baseline (cùng vai trò, nhưng không phải parser H.264 thật).
  SHA-256 tự cài để chạy trong mọi sandbox.
- Đây là bản dựng lại độc lập để dạy/minh hoạ, **không** cùng-byte với KAT của
  mã Python trong `src/lattice_zk/`.

## Chạy
Mở qua http(s), không mở bằng `file://` (getImageData bị chặn với file://):

    cd VideoLevel/webdemo
    python -m http.server 8000
    # mở http://localhost:8000/

Bấm **▶ Chạy toàn bộ** hoặc làm từng bước 1→5.

## Cấu trúc
- `index.html` — khung giao diện (5 bước) + nạp script.
- `css/styles.css` — giao diện, chủ đề sáng/tối.
- `js/`
  - `sha256.js` — SHA-256 thuần.
  - `rng.js` — PRNG tất định (SHA-256 stream).
  - `ring.js` — số học vành negacyclic R_q (mulmod tách limb, không BigInt).
  - `params.js` — bộ tham số demo (N=64) và sản xuất (N=256).
  - `bdlop.js` — khoá, randomness, commitment t₁/t₂, mã hoá payload.
  - `opening_proof.js` — SampleInBall, prove/verify Fiat–Shamir-with-aborts, serialize.
  - `dct.js` — DCT/IDCT 8×8 + lượng tử (phân tích/dựng lại khung).
  - `carriers.js` — chọn carrier (magnitude) + chuẩn hoá cho digest.
  - `statement.js` — digest ràng buộc video + phiên.
  - `embed.js` — nhúng/trích LSB.
  - `metrics.js` — PSNR, SSIM.
  - `pipeline.js` — nối các bước (verifier làm việc ở miền hệ số, rải nhiều khung).
  - `ui.js` — controller.
- `data/{container,akiyo,foreman}.png` — khung 256×256 trích từ video thật của hệ thống.

## Kiểm chứng toán (headless)
Logic đã được chạy thử bằng node: demo verify TRUE (D sai/ r giả → FALSE),
sản xuất N=256 ~1,2 s/lượt, pipeline đầy đủ honest TRUE và tamper/replay FALSE.
