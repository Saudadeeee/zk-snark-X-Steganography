# Roadmap hoàn thiện hệ thống lattice-ZK video (từ 2026-10-21)

Mục tiêu: hệ thống đủ chuẩn bài **Q2** (giai đoạn A), rồi nâng lên mức có thể
nộp **Q1** (giai đoạn B). Mỗi luồng việc có tiêu chí chấp nhận đo được; một
luồng chỉ coi là xong khi tiêu chí đạt và test xanh.

Giới hạn không vượt qua bằng code: chấp nhận bài phụ thuộc reviewer; một bài
Q1 về mật mã thường cần một chuyên gia lattice ngoài nhóm đọc lại phần chứng
minh. Roadmap chuẩn bị đầy đủ để việc đó nhanh, không thay thế nó.

## Nguyên tắc vận hành

- Một máy, 24 GB RAM, GPU RTX 3060. Thí nghiệm E2E nặng (1–3 GB RAM mỗi lượt)
  chạy **tuần tự** qua sweep ở cây chính; agent không tự chạy E2E dài.
- Mỗi agent làm trong git worktree riêng, commit trên nhánh riêng; tích hợp
  bằng merge vào `feature/lattice-pq-stack` sau khi review và chạy lại test.
- Phạm vi file của các agent không chồng nhau để tránh xung đột merge.

## Giai đoạn A — đủ chuẩn Q2

| ID | Luồng | Phạm vi | Tiêu chí chấp nhận |
|---|---|---|---|
| A0 | Thí nghiệm còn lại (cây chính) | 4CIF Harbour/Soccer/Crew, đường cong mật độ 100/50/25 %, đánh giá ML toàn bộ, sinh lại bảng | Mọi case có kết quả hoặc lý do bỏ ghi rõ; `latticezk_q2_report` và `latticezk_density_report` chạy sạch |
| A1 | Rà soát và gia cố mã mật mã | `src/lattice_zk/`, registry, sessions, test tương ứng | Không còn phát hiện CRITICAL/HIGH/MEDIUM; độ phủ test `src/lattice_zk` ≥ 85 % |
| A2 | Hiệu năng verify | transport blind, analysis cache, canonicalization | Verify nhanh ≥ 2× trên clip CIF chuẩn; vị trí carrier và digest giống hệt (test tương đương) |
| A3 | Tái lập và CI | script tái lập, `ARTIFACT.md`, requirements, CI unit test | Một lệnh chạy lại toàn bộ unit test; một lệnh tái lập một E2E nhỏ; CI không cần dữ liệu lớn |
| A4 | Hoàn thiện bản thảo | `docs/paper/` (trừ phần chứng minh) | Biên dịch PDF sạch; mọi trích dẫn đã xác minh; related work, threats to validity đầy đủ |
| A5 | Mô hình và chứng minh bảo mật | `docs/paper/sections/security.tex` | Định nghĩa trò chơi cho soundness gắn video, hiding payload, chống replay, linkage; định lý + chứng minh quy về BDLOP/FS; đối chiếu với code |
| A6 | Steganalysis CNN | script CNN mới + test | Huấn luyện CNN (GPU) trên frame bị sửa, giao thức leave-one-clip-out; báo P_E cạnh bộ dò FLD |

Điểm kiểm (Q2-ready): A0–A6 đạt; bản thảo có số đo cuối cùng; một commit
gộp trên nhánh.

## Giai đoạn B — hướng Q1 (bắt đầu sau khi A đạt)

| ID | Luồng | Tiêu chí |
|---|---|---|
| B1 | Embedding thích nghi theo chi phí (carrier chọn theo độ khó mô hình hóa, bên trích suy ra lại được) | P_E học máy tăng rõ so với hiện tại ở cùng mật độ |
| B2 | Chứng minh payload nhị phân/khoảng (ALS20 trên vành fully-splitting) | Proof đúng, test âm đầy đủ, kích thước đo được, đặc tả + chứng minh |
| B3 | Đánh giá rộng: 720p/1080p, GOP > 1 (P-slice) | Dung lượng, chất lượng, steganalysis trên bộ dữ liệu mới |
| B4 | Chuẩn bị review mật mã bên ngoài | Gói tài liệu cho người đọc lại: đặc tả, chứng minh, KAT, câu hỏi mở |

## Việc hoãn lại (làm vào thời gian khác)

- **Đo lại steganalysis học máy dưới v2.** Lượt chạy lại v2 (2026-10-21) bỏ
  qua bằng `ZKSTEGO_SKIP_LEARNED=1`: trích đặc trưng ML trong sweep, đánh giá
  FLD (`ml_eval*.json`), mô phỏng nhúng (`embedding_*_sim.json`,
  `adaptive_sim.json`), CNN (`cnn_*.json`, `adaptive_cnn_*.json`) và phần
  detection của `adaptive_e2e`. Các số học máy trong bài vẫn là của v1
  (envelope 7 589 B, v2 lớn hơn ~8 %) và phải ghi rõ như vậy. Cách làm lại:
  chạy sweep không có biến đó (chỉ bước ML chạy, E2E đã có sẽ bỏ qua), rồi
  `ml_steganalysis evaluate`, `embedding_sim`, `adaptive_sim`, các lệnh CNN
  trong `docs/CNN_STEGANALYSIS.md` và `docs/CARRIERS_VA_CHUNKING.md`.
- **Sweep HD** (`benchmark/latticezk_hd_cases.json`). Thứ tự nhúng theo hình
  học SPS đã có (C4: hợp đồng `magnitude-geo` / `t1-geo` / `adaptive-geo`, hợp
  đồng cũ giữ nguyên từng byte); các case HD dùng `magnitude-geo` và chunk
  thích ứng. Lệnh và ước tính RAM/thời gian: `docs/GOP_HD_SUPPORT.md`.

## Trạng thái

- 2026-10-21: commit `22d52c9` chứa toàn bộ hệ thống tới thời điểm này.
  Giai đoạn A bắt đầu.
- 2026-10-22: A1 (gia cố, độ phủ 99 %), A3 (tái lập + CI), A4 (bản thảo 19
  trang, trích dẫn đã xác minh), A5 (mô hình + chứng minh) đã merge. A5 tìm ra
  lỗ hổng D1–D6; A7 đang sửa D2/D3/D4/D6; D1 (chunk header khả biến khi chỉ có
  một chunk) sửa sau khi merge A2. Còn chạy: A2, A6, A7, A0 (mật độ 4CIF,
  Soccer/Crew).
- 2026-10-21 (tối): A7 (D2/D3/D4/D6) và A2 (verify 4,8×, embed 7,8×, đầu ra
  giống hệt) đã merge. D1 sửa: verifier chia lại envelope theo `chunk_bytes`
  đã pin và đòi chunk trích ra trùng từng byte; có test âm. Bản thảo cập nhật
  cho disclosure mới và trạng thái D1–D6. Còn chạy: A6, A0.
- 2026-10-21 (khuya): A6 merge (CNN: magnitude P_E 0,466 LOCO, T1 0,27). D1
  commit `dcb9c67`, E2E thật (registered, replay + tamper) PASS. A0 còn chạy
  (~8 h). Bắt đầu song song phần code của B1 (carrier thích nghi), B2 (proof
  nhị phân), B4 (gói review + đối chiếu lattice-estimator); B3 chờ A0 xong vì
  cần RAM cho E2E.
- 2026-10-21 (sáng): B4 merge (lattice-estimator thật: M-SIS 140/127 và
  M-LWE primal 138/125 khớp; dual hybrid 135/123 → bài nhận mức thấp hơn).
  B2 merge (proof chuỗi nhị phân, 41,9 KB, verify 72 ms; chưa nối với mã hóa
  payload 24 bit; phụ lục bài). B1 merge (STC trên carrier magnitude: ít hơn
  26–47 % thay đổi, +1,4–2,4 dB, P_E LOCO tệ nhất 0,41 → 0,43; mục mới trong
  bài). Còn: A0 (sweep 4CIF), B3.
- 2026-10-21 (trưa): chuyển sang `bdlop-open-128-v2` (λ = 7; hiding 164/150,
  binding 140/127); KAT v2; bắt đầu chạy lại toàn bộ đánh giá lúc 12:24,
  khởi động lại 12:51.
- 2026-10-26: hoàn thiện phần mật mã và phạm vi. (1) Bộ sản xuất
  `bdlop-open-128-v3` (n = 7): binding 172 / 156, hiding 164 / 150 bit, đối
  chiếu lattice-estimator khớp; KAT v3; proof nhị phân/khoảng chuyển sang nền
  v3 (`bdlop-binary-128-v3`, `bdlop-payload-range-128-v2`), bản cũ giữ nguyên
  id. (2) Codec policy v2 là mặc định cho profile mới (v1 còn chọn được). (3)
  Payload range proof đính kèm được vào envelope in-band (phiên bản envelope
  2, `--payload-range-bytes`). (4) Chế độ phiên offline theo epoch beacon ký
  ML-DSA-65 (`epoch-issue`, `--epoch-beacon`, sổ chống phát lại theo
  verifier). (5) Review soundness đối kháng nội bộ
  (`docs/review/INTERNAL_REVIEW_SOUNDNESS.md`): không có lỗi Critical/High;
  các sửa về phát biểu định lý và số liệu đã áp vào bài/tài liệu;
  `soundness_bits` tính theo tổng lỗi các vòng (≈ 149,0 bit). (6) **CABAC
  (Main/High)**: parser/encoder CABAC thuần Python cho lát I/IDR
  (`src/bitstream/cabac/`), transport `src/transport/cabac_sync.py`, codec
  policy `CODEC_POLICY_CABAC_V1` (digest = re-encode chuẩn tắc của cú pháp đã
  chuẩn hoá carrier + mọi NAL khác từng byte); 56 test; sản xuất 300 khung
  High: registered 1 đoạn, PSNR-Y 45,8 dB; in-band 2 đoạn, 47,8 dB
  (`docs/CABAC_SUPPORT.md`). (7) **Chế độ bền với nén lại** (semi-fragile,
  `src/robust/`): QIM trên DCT 16×16 luma + mã chập K=7/Viterbi mềm + CRC-32,
  vân tay nội dung (luma 64×64 mọi khung + chroma 128×128 mỗi 6 khung, blob
  v2) gắn vào statement; decode có ngân sách bộ nhớ/timeout, ffmpeg chỉ
  protocol file, verify fail-closed; sống qua x264 CRF 18/23 và x265
  CRF 23 (31/36 lượt), 30/30 sửa đổi bị bắt kèm định vị (gồm đổi màu); PSNR 35–37 dB, không
  che giấu (`docs/ROBUST_MODE.md`, `benchmark/results/robust/`). (8) E2E toàn hệ
  dưới v3: **8/8 kịch bản đạt** (`benchmark/results/q2/system_e2e_check_20261026.json`,
  gồm `inband_range32` 63 094 B trên 3 000 khung và `reg_codec_v1`); full test
  suite 1 196 pass. Còn chờ: đo lại steganalysis học máy, sweep HD.
- 2026-10-26 (tiếp): CABAC nay gọi được từ CLI sản xuất (`--codec-policy cabac`,
  `--gop-policy`), đã kiểm end-to-end registered trên clip 300 khung High
  (envelope 8 741 B, verify mù đạt, replay chặn); test wiring
  `test_latticezk_cli_codec_wiring.py`. Robust mode được cấp CLI riêng
  (`src/robust/cli.py`). Còn chờ: đo lại steganalysis học máy, sweep HD, review
  lattice ngoài, các `\todo` bảng sweep v1/v2 trong bài.
