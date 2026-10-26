# Bàn giao hệ thống lattice-ZK video — mục lục

Mục đích: điểm vào cho người tiếp nhận dự án; liệt kê từng tài liệu bàn giao, thứ tự đọc, và cách khởi động nhanh.
cập nhật: 2026-10-22

Bộ tài liệu này viết cho người **tiếp nhận và duy trì** hệ thống giấu tin
lattice-ZK trong video H.264 (parameter set sản xuất `bdlop-open-128-v3`,
mã nguồn trong `src/lattice_zk/`). Nó tóm tắt và liên kết tới các tài liệu kỹ
thuật tiếng Anh đã có (`docs/LATTICE_ZK_BDLOP_SPEC.md`, `docs/paper/`,
`docs/review/`), **không thay thế** chúng.

## Các tài liệu bàn giao

| File | Nội dung |
|---|---|
| `01_tong_quan.md` | Bài toán, hệ thống làm gì end-to-end, hai chế độ, "xác minh mù từ video", phạm vi, "là gì / không là gì" |
| `02_kien_truc.md` | Kiến trúc và luồng dữ liệu: pipeline nhúng và pipeline xác minh theo bước, module/hàm chính xác ở mỗi bước, bản đồ thành phần |
| `03_ly_thuyet.md` | Lý thuyết: BDLOP, Fiat–Shamir-with-aborts, relaxed opening + chặn binding `8κB`, hiding M-LWE, equality/linkage, disclosure, binary/payload-range proof, ràng buộc statement vào video, carrier + STC, mô hình bảo mật, tham số v1/v2 |
| `04_van_hanh.md` | Hướng dẫn vận hành: môi trường, lệnh chính xác (unit test, một E2E registered + in-band, CLI, chạy lại v2 hoãn, bộ giám sát RAM), đọc file kết quả JSON, hướng dẫn bộ nhớ |
| `05_ket_qua.md` | Kết quả đánh giá đến nay: kiểm tra chức năng 7 chế độ, kích thước/bảo mật v2, dung lượng theo clip/QP, PSNR, steganalysis, GOP>1 và HD; đánh dấu rõ số v1 và phần hoãn |
| `06_han_che_va_huong_phat_trien.md` | Giới hạn trung thực và hướng phát triển; ánh xạ tới `docs/ROADMAP.md` và `docs/review/QUESTIONS.md` |
| `07_checklist_ban_giao.md` | Checklist bàn giao: cách xác nhận hệ thống khỏe mạnh, tài liệu/gói review chính thức ở đâu, phần hoãn, các quyết định mở cho chủ mới |
| `08_don_dep_con_lai.md` | Dọn dẹp 10/2026 còn lại: danh sách xóa còn chờ phê duyệt và các file kết quả phải giữ (bản đồ di dời đầy đủ trong git history) |

## Thứ tự đọc đề xuất

1. `01_tong_quan.md` — để hiểu hệ thống làm gì và phạm vi.
2. `02_kien_truc.md` — để biết code ở đâu và luồng chạy thế nào.
3. `04_van_hanh.md` — để chạy được unit test và một E2E.
4. `05_ket_qua.md` + `06_han_che_va_huong_phat_trien.md` — để biết trạng thái thật và việc còn lại.
5. `03_ly_thuyet.md` — khi cần chiều sâu mật mã (đọc cùng `docs/LATTICE_ZK_BDLOP_SPEC.md`).
6. `07_checklist_ban_giao.md` — trước khi nhận bàn giao chính thức.

## Bắt đầu từ đâu (cho người duy trì mới)

1. Clone repo; làm việc trong `VideoLevel/` (nhánh hiện tại: `feature/lattice-pq-stack`).
2. Tạo venv Python 3.12: `python -m venv .venv312`.
3. Cài phụ thuộc (Windows): `.venv312\Scripts\python.exe -m pip install -r requirements.lock`
   (POSIX: `.venv312/bin/python -m pip install -r requirements.lock`). Cần `ffmpeg`/`ffprobe` (có libx264) trên `PATH`.
4. Chạy unit test (không cần dữ liệu video): `sh scripts/run_unit_tests.sh`
   hoặc `python scripts/repro.py unit-tests` — kỳ vọng `RESULT: PASS`.
5. Xem một E2E nhỏ (registered, ~10–15 phút, < 2 GB RAM): `sh scripts/reproduce_small.sh`
   (bên trong gọi `benchmark/latticezk_video_e2e.py`); báo cáo ghi ra `tmp/repro_small/`.
6. Chạy thủ công một E2E in-band / registered: xem các lệnh `python -m benchmark.latticezk_video_e2e ...` trong `04_van_hanh.md`.
7. CLI tách-vai-trò (issuer / holder / verifier) nằm ở `src/lattice_zk/cli.py`:
   `python -m src.lattice_zk.cli --help`.
8. Hướng dẫn tái lập đầy đủ (dữ liệu Xiph, mã hóa cover, bảng kết quả): `ARTIFACT.md`.
9. Bản đồ di dời file sau đợt dọn dẹp 10/2026: git history; phần dọn dẹp còn lại: `08_don_dep_con_lai.md`.
10. Tài liệu mật mã chính thức: `docs/LATTICE_ZK_BDLOP_SPEC.md`; gói review ngoài: `docs/review/`.

## Bổ sung 2026-10-26

- `docs/LATTICE_ZK_BDLOP_SPEC.md` §2, §3.7 — bộ `bdlop-open-128-v3`, envelope
  phiên bản 2 (đính kèm range proof), phiên offline theo epoch.
- `docs/CABAC_SUPPORT.md` — hỗ trợ H.264 Main/High (CABAC): thiết kế, dạng
  chuẩn tắc, carrier, digest, cách chạy, kết quả, giới hạn.
- `docs/ROBUST_MODE.md` — chế độ bền với nén lại (semi-fragile): thiết kế,
  tham số đã hiệu chuẩn, kết quả benchmark, giới hạn.
- `docs/review/INTERNAL_REVIEW_SOUNDNESS.md` — review soundness đối kháng nội
  bộ và các sửa đã áp dụng.
- `research/bdlop_params/CROSSCHECK.md` (mục v3) — đối chiếu lattice-estimator.
- `scripts/ops/system_e2e_v3.sh` — E2E toàn hệ dưới v3 (gồm `inband_range32`,
  `reg_codec_v1`).
