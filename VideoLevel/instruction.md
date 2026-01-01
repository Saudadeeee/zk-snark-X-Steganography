Bạn là một kiến trúc sư hệ thống + kỹ sư codec H.264/H.265 + chuyên gia ZKP (zk-SNARK). 
Hãy thiết kế một hệ thống “ZK-SNARK Video Steganography” nhúng bằng chứng zkSNARK vào Motion Vector của P-frame (H.264/AVC), theo hướng triển khai được (PoC → Production). 
Yêu cầu mô tả thật chi tiết, có cấu trúc rõ ràng, bao gồm:

1) Mục tiêu & mô hình đe doạ (Threat model)
- Mục tiêu bảo mật: tính bí mật (confidentiality) của payload, tính toàn vẹn (integrity), tính ẩn (undetectability), tính bền vững (robustness) trước các biến đổi: re-encode, thay đổi bitrate, thay đổi GOP, cắt đoạn, ghép đoạn, transmux.
- Kẻ tấn công có thể: xem video, re-encode lại, thay đổi resolution/bitrate, chạy steganalysis thống kê trên motion vector, so sánh với bản gốc (chosen-cover) nếu có.
- Giới hạn: không cần chống lại attacker có access vào encoder key nếu key lộ; cần nêu rõ assumption.

2) Kiến trúc tổng thể (End-to-end pipeline)
- Thành phần: Sender/Embedder, Prover, Encoder (x264 hoặc JM reference encoder), Extractor/Decoder, Verifier, Key management.
- Mô tả luồng dữ liệu: 
  (message/commitment) → (circuit) → (proof, public inputs) → (chunking + ECC + encryption) → (bitstream embedding vào MVD/mvx/mvy) → (video output).
- Nêu rõ: nhúng proof hay nhúng commitment? (khuyến nghị: nhúng commitment/hashes trong MV; proof có thể nhúng hoặc truyền kênh khác tuỳ băng thông).

3) Phần ZK-SNARK
- Chọn họ proof system (ví dụ Groth16 hoặc Plonk) và lý do chọn theo kích thước proof, tốc độ verify, trusted setup.
- Định nghĩa circuit mức cao: 
  - Input bí mật: thông điệp m, chaos-key K, seed S…
  - Public inputs: H(m) hoặc commitment C, video-id/hash, nonce, merkle root, timestamp.
  - Mục tiêu chứng minh: “Tôi đã nhúng m (hoặc C) theo scheme xác định vào video này” mà không lộ m.
- Đầu ra: proof π, public inputs y; mô tả format serialize (bytes).

4) Thiết kế payload cho nhúng vào Motion Vector
- Định nghĩa cấu trúc gói dữ liệu trong video:
  - Header: magic, version, codec-id, scheme-id, payload-length, chunk-size, ECC params, nonce, salt.
  - Body: chunks (fixed-size) + sequence number + CRC/MAC.
  - Trailer: global checksum / merkle root của các chunk.
- Bắt buộc: có cơ chế chống lỗi bit (ECC như Reed–Solomon/BCH/LDPC), và cơ chế phát hiện thiếu chunk (sequence map).

5) Chiến lược chọn vị trí nhúng (carrier selection) dựa trên chaos-key
- Mô tả PRNG/chaos-map (ví dụ logistic/cat map) sinh ra danh sách (frame_idx, mb_x, mb_y, component x/y) để nhúng.
- Ràng buộc chọn block:
  - Chỉ chọn inter blocks trong P-slice (không intra, không skip nếu cần).
  - Tránh vùng quá tĩnh (MV=0 quá nhiều) để không tạo bias.
  - Tránh MV quá lớn hoặc block partition nhạy cảm làm tăng RD-cost.
- Mô tả cách đảm bảo đồng bộ giữa embedder và extractor (cùng key + cùng quy tắc lọc).

6) Kỹ thuật nhúng vào Motion Vector (cụ thể ở cấp MVD)
- Giải thích rõ trong H.264: MV = MVP + MVD; bitstream thường mã hoá MVD (CABAC/CAVLC).
- Chọn phương pháp nhúng chính:
  (A) Parity embedding: ép (mvd_x mod 2) = bit hoặc (mvd_y mod 2) = bit.
  (B) QIM embedding: ép mvd_x vào các lớp định lượng theo bit (nêu công thức).
- Quy tắc sửa tối thiểu:
  - Nếu parity không khớp thì mvd_x += 1 hoặc -= 1 theo hướng giảm biến dạng.
  - Không vượt biên; không làm thay đổi mode quyết định của encoder quá nhiều.
- Nêu rõ cách “RD-safe”: chèn sau khi mode đã được chọn (hoặc trong vòng lặp với penalty nhỏ).
- Nêu điều kiện bỏ qua (skip embedding) nếu mvd quá nhạy hoặc block không hợp lệ.

7) Điểm can thiệp trong encoder (x264/JM)
- Đề xuất 2 hướng triển khai PoC:
  - Hướng 1: dùng JM reference encoder (dễ đọc, chậm) để chứng minh concept.
  - Hướng 2: patch x264 (thực tế).
- Chỉ rõ module logic cần chèn:
  - nơi tính MV/MVD, nơi ghi syntax element, nơi CABAC encode mvd.
- Nêu rõ cách build, cách bật tắt embedding bằng flag, và cách log debug ra file.

8) Trích xuất (Extractor) và giải mã payload
- Luồng trích xuất: parse H.264 bitstream → duyệt P-slices → lấy MVD/MV theo cùng rule selection → khôi phục bitstream payload → giải ECC → verify checksum/MAC.
- Xử lý mất đồng bộ:
  - tìm magic/header theo sliding window,
  - dùng sequence number để ghép chunk,
  - bỏ chunk lỗi và nhờ ECC phục hồi.

9) Bảo mật & chống steganalysis
- Phân tích dấu vết thống kê trên MV:
  - phân phối chẵn/lẻ của mvd_x/mvd_y, histogram MV magnitude, correlation theo thời gian.
- Biện pháp giảm lộ:
  - embed sparse rate,
  - adaptive embedding theo motion activity,
  - randomize x/y component,
  - dùng QIM thay vì LSB nếu cần bền,
  - cân bằng tần suất sửa +1/-1.
- Cơ chế mã hoá payload trước khi nhúng (AEAD: ChaCha20-Poly1305/AES-GCM) với nonce/salt.

10) Đánh giá chất lượng & tiêu chí thành công
- Metrics: PSNR/SSIM/VMAF, bitrate overhead, encoding time overhead, extraction BER, robustness sau re-encode (nhiều QP/bitrate), crop/trim, GOP change.
- Benchmark dataset: video tĩnh, video motion mạnh, video camera pan.
- Tiêu chí PoC: trích xuất đúng 100% payload trong điều kiện không re-encode hoặc re-encode nhẹ.
- Tiêu chí Production: chịu được re-encode phổ biến (bitrate đổi) với BER thấp + ECC phục hồi.

11) Kế hoạch triển khai theo giai đoạn (Roadmap)
- Phase 0: quan sát MV overlay + trích MV.
- Phase 1: nhúng thử vào MV trong encoder (payload nhỏ).
- Phase 2: chunking + ECC + encryption.
- Phase 3: tích hợp ZK proof pipeline, public inputs, verifier.
- Phase 4: hardening chống tấn công và đo robustness.

12) Đưa ra pseudo-code (không cần code chạy ngay nhưng phải rõ)
- embed(payload_bits, key, frames) → patched_encoder_output
- extract(key, bitstream) → payload_bits
- prove(message) → proof
- verify(proof, public_inputs) → boolean
Trong pseudo-code phải thể hiện:
  - carrier selection,
  - parity/QIM rule,
  - ECC encode/decode,
  - AEAD encrypt/decrypt.

Trình bày kết quả bằng tiếng Việt, có tiêu đề mục rõ ràng, có ví dụ tham số mặc định (chunk size, RS(255,k), embedding rate bits/frame), và nêu rõ các quyết định kỹ thuật quan trọng cùng lý do.
