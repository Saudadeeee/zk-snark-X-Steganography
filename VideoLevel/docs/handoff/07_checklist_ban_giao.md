# Checklist bàn giao

Mục đích: các bước xác nhận hệ thống khỏe mạnh, nơi tài liệu/gói review chính thức, phần hoãn, và các quyết định mở cho chủ mới.
cập nhật: 2026-10-22

## 1. Xác nhận hệ thống khỏe mạnh

- [ ] **Clone + nhánh**: làm việc trong `VideoLevel/`, nhánh
  `feature/lattice-pq-stack`.
- [ ] **venv**: `python -m venv .venv312` rồi
  `.venv312\Scripts\python.exe -m pip install -r requirements.lock`
  (POSIX: `.venv312/bin/python -m pip install -r requirements.lock`).
  `ffmpeg`/`ffprobe` (có libx264) trên `PATH`.
- [ ] **Unit test PASS**: `sh scripts/run_unit_tests.sh` (hoặc
  `python scripts/repro.py unit-tests`) → `RESULT: PASS`. Con số case cụ thể
  tùy phạm vi/môi trường (xem `04_van_hanh.md` §2) — **cần xác nhận lại khi chạy**.
- [ ] **KAT khớp**: `test_latticezk_kat.py` (nằm trong unit test) sinh lại và so
  KAT; hoặc thủ công cho set sản xuất:
  ```bash
  python research/bdlop_params/kat.py --parameter-set BDLOP_OPEN_128_V2 --output tmp/kat_check.json
  cmp tmp/kat_check.json research/bdlop_params/kat_v2.json    # Windows: fc /b; không output = giống
  ```
  (v1: `--parameter-set BDLOP_OPEN_128_V1` so với `kat_v1.json`).
- [ ] **Một E2E verify + chống phát lại + chống sửa**: `sh scripts/reproduce_small.sh`
  (registered, ~10–15 phút) → báo cáo `tmp/repro_small/.../` có
  `verified_from_video_alone`, payload vắng mặt; để kiểm phát lại + sửa 1 bit,
  chạy trực tiếp `benchmark/latticezk_video_e2e.py` **không** `--skip-security-checks`
  (xem `04_van_hanh.md` §3) và xác nhận `replay_rejected`/`tamper_rejected = true`.
  Bằng chứng v2 đã có sẵn: `benchmark/results/q2/system_e2e_check_20261021.json`
  (7 chế độ đạt).
- [ ] **Không rò bí mật**: verifier không cần video gốc/sidecar/khóa holder; chỉ
  cần cấu hình pin + sync key + session store.

## 2. Tài liệu chính thức ở đâu

- Đặc tả + lập luận bảo mật: `docs/LATTICE_ZK_BDLOP_SPEC.md`.
- Bài báo: `docs/paper/` (`sections/security.tex`, `security_appendix.tex`,
  bảng/figure sinh tự động).
- Gói review mật mã bên ngoài: `docs/review/` — `README.md` (phạm vi + bản đồ
  code), `CLAIMS.md` (claim↔code↔test), `QUESTIONS.md` (câu hỏi mở xếp theo
  mức độ), `CHECKLIST.md`.
- Tái lập: `ARTIFACT.md`; driver `scripts/repro.py`; tham số/KAT
  `research/bdlop_params/` (+ `CROSSCHECK.md`).
- Thiết kế bổ trợ: `docs/ADAPTIVE_CARRIERS.md`, `docs/ADAPTIVE_CHUNKING.md`,
  `docs/GOP_HD_SUPPORT.md`, `docs/BINARY_PROOF_DESIGN.md`,
  `docs/PAYLOAD_RANGE_PROOF.md`, `docs/CNN_STEGANALYSIS.md`,
  `docs/LATTICE_BACKEND_SURVEY.md`.
- Bản đồ di dời/xóa file (dọn dẹp 10/2026): `docs/CLEANUP_INVENTORY.md`.
- Kế hoạch/trạng thái (tiếng Việt): `docs/LATTICE_ZK_BDLOP_PLAN.md`,
  `docs/ROADMAP.md`.

## 3. Phần đang hoãn (deferred)

- **Steganalysis học máy dưới v2**: lượt chạy lại v2 đặt `ZKSTEGO_SKIP_LEARNED=1`;
  mọi số ML/CNN trong bài vẫn là **v1** (envelope 7589 B). Cách chạy lại: bỏ biến
  đó, chạy sweep (chỉ bước ML), rồi `ml_steganalysis evaluate`, `embedding_sim`,
  `adaptive_sim`, các lệnh CNN trong `docs/CNN_STEGANALYSIS.md`.
  (ROADMAP §"Việc hoãn lại")
- **Sweep HD** (`benchmark/latticezk_hd_cases.json`): mới chạy encode tổng hợp;
  lệnh + ước tính RAM/thời gian trong `docs/GOP_HD_SUPPORT.md`.
- **Số đo v2 còn thiếu**: timing prove/verify đầy đủ, số lần abort kỳ vọng, KAT
  v2 đo lại — nhiều chỗ trong tài liệu ghi "v2 measurement pending".

## 4. Quyết định mở cho chủ mới

1. **Chuyển mặc định sang v2?** `BDLOP_OPEN_128 = BDLOP_OPEN_128_V2`, nhưng vài
   đường/tài liệu cũ còn mặc định v1. Có nên thống nhất v2 ở mọi nơi và đo lại
   số v1 không?
2. **Nâng rank M-SIS để binding quantum đạt 128 bit?** Hiện M-SIS quantum 127 <
   128 (QUESTIONS Q2/Q15). Nâng `n` tăng kích thước commitment/envelope — cân
   nhắc đánh đổi.
3. **Đặt review mật mã bên ngoài?** Một chuyên gia lattice đọc lại
   FS-with-aborts, relaxed-soundness, khóa toàn cục (QUESTIONS Q1/Q2/Q9); gói
   sẵn ở `docs/review/` (ROADMAP B4).
4. **Đo lại steganalysis học máy dưới v2?** Để số trong bài khớp envelope v2 và
   khép phần hoãn (A6/B1).
5. **Mở rộng phạm vi?** CABAC, profile cao hơn, bền vững trước transcode, nối
   binary/payload-range proof vào envelope (hiện ngoài băng) — xem giai đoạn B.

## 5. Lưu ý vận hành khi nhận máy

- E2E nặng (1–3 GB/lượt, 4CIF tới ~7 GB với 8 worker): đặt
  `ZKSTEGO_ANALYSIS_WORKERS=2`, sweep `--workers 1` cho 4CIF, dùng
  `scripts/ops/sweep_supervisor.ps1` (pause ở commit 97 %). Xem `04_van_hanh.md`
  §6.
- Các script `scripts/ops/*` hard-code `.venv312` và đường **cây chính** (không
  phải worktree) — chạy từ cây chính.
