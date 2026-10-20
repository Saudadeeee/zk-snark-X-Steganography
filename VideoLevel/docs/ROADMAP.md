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
