# Hướng dẫn vận hành

Mục đích: môi trường, các lệnh chính xác (unit test, E2E, CLI, chạy lại v2 hoãn, giám sát RAM), cách đọc kết quả JSON, và hướng dẫn bộ nhớ.
cập nhật: 2026-10-22

Mọi lệnh chạy từ thư mục `VideoLevel/`. Tài liệu tái lập đầy đủ:
`ARTIFACT.md` (dữ liệu Xiph + SHA-256, mã hóa cover, bảng kết quả).

## 1. Môi trường

- Python **3.12** (đã kiểm: 3.12.10), venv `.venv312`.
- `ffmpeg`/`ffprobe` 8.x (bản có libx264) trên `PATH`.
- Gói Python ghim ở `requirements.lock`.

```bash
python -m venv .venv312
.venv312/bin/python -m pip install -r requirements.lock         # POSIX
# Windows: .venv312\Scripts\python.exe -m pip install -r requirements.lock
```

Các wrapper tự chọn interpreter (`.venv312` nếu có, nếu không `python3`/`python`
hoặc `py -3.12`); đặt `PYTHON` / `$env:PYTHON` để ép. Interpreter đã kiểm:
`D:/Code/SourceCode/Project/zk-snark-X-Steganography/VideoLevel/.venv312/Scripts/python.exe`.

## 2. Unit test (không cần dữ liệu video, ~1–2 phút)

```bash
sh scripts/run_unit_tests.sh                                    # POSIX
powershell -ExecutionPolicy Bypass -File scripts\run_unit_tests.ps1   # Windows
python scripts/repro.py unit-tests                              # trực tiếp
```

`scripts/repro.py unit-tests` chạy: (1) kiểm cú pháp mọi `.py` trong
`src/lattice_zk, src/transport, src/registry, src/core, src/bitstream,
research/bdlop_params, benchmark, scripts`; (2) một lần `pytest` trên 27 file
(11 `test_latticezk_*` + 16 test module liên quan); (3) 5 suite dạng script
(`test_lattice_pq_stack`, `test_zkp_registry`, và 3 suite legacy). Kỳ vọng:
`RESULT: PASS`. Mã thoát mỗi suite: `0`=OK, `2`=INCOMPLETE (có case bị skip,
vẫn tính đạt), khác=FAIL. Con số case cụ thể tùy phạm vi/môi trường
(đợt dọn dẹp 10/2026 ghi "434 passed, 1 skipped" cho phần pytest sau dọn
dẹp; `ARTIFACT.md` ghi "174 passed, 1 skipped" cho wrapper, có chú thích "v2
measurement pending"; `docs/review/README.md` ghi "209 passed" cho riêng
`test_latticezk_*`) — **con số chính xác cần xác nhận lại khi chạy**.

## 3. Một E2E trên clip CIF (registered và in-band)

Module: `benchmark/latticezk_video_e2e.py`. Bắt buộc `--video --output --report`
(không ghi đè file sẵn có). Chọn chế độ bằng cờ `--registered` (có = registered,
không có = in-band). Kiểm tra bảo mật (phát lại + sửa 1 bit) **chạy mặc định**;
tắt bằng `--skip-security-checks`.

```bash
# REGISTERED (video chỉ mang bằng chứng 8741 B, v3) — dùng carrier t1 cho CIF 100 khung
python -m benchmark.latticezk_video_e2e \
  --video <cif_cut>.h264 --output tmp/reg.h264 --report tmp/reg.json \
  --parameter-set BDLOP_OPEN_128 --registered --carrier t1 --chunk-bytes 8200

# IN-BAND (video mang cam kết + bằng chứng 16421 B, v3) — carrier magnitude mặc định
# (thêm --payload-range-bytes 32 để đính kèm range proof: +46 673 B, cần clip dài)
python -m benchmark.latticezk_video_e2e \
  --video <cif_cut>.h264 --output tmp/inband.h264 --report tmp/inband.json \
  --chunk-bytes 5000
```

Ghi chú: module **không** có `--frames`; độ dài segment là `--frames-per-segment`
(mặc định 100). Carrier magnitude cần nhiều khung hơn (dùng ~200 khung,
`--chunk-bytes 4200`). Lệnh gói sẵn một E2E nhỏ registered (cắt 100 khung
`container_cif_q22_g1`, ~10–15 phút, < 2 GB RAM):

```bash
sh scripts/reproduce_small.sh        # repro.py small; báo cáo vào tmp/repro_small/
```

Lưu ý: trong `scripts/repro.py small`, cờ bảo mật **ngược lại** — phải thêm
`--security-checks` để bật (mặc định tắt).

## 4. CLI tách vai trò

`src/lattice_zk/cli.py` (`python -m src.lattice_zk.cli <subcommand>`):
`issuer-keygen`, `registry-sign`, `credential-new`, `embed`, `disclose`,
`session-issue`, `verify`, `disclosure-verify`. Verifier nhận **sync key** qua
biến môi trường `ZKSTEGO_LATTICEZK_SYNC_KEY_HEX` (64 hex); nó không đọc sidecar,
video gốc hay bí mật holder. Chuỗi lệnh mẫu (keygen → credential → registry →
session → embed → verify → disclose) có trong `docs/LATTICE_ZK_BDLOP_PLAN.md`.

## 5. Chạy lại đánh giá v2 (hoãn) và system E2E — `scripts/ops/`

> Cảnh báo: các script trong `scripts/ops/` **hard-code** `.venv312/Scripts/python.exe`
> và đường dẫn **cây chính** `.../zk-snark-X-Steganography/VideoLevel` (không phải
> worktree). Chạy chúng từ cây chính.

- `scripts/ops/rerun_v2_eval.sh` — **chạy lại toàn bộ đánh giá** (viết cho
  `bdlop-open-128-v2`; với v3 dùng `scripts/ops/system_e2e_v3.sh` cho E2E). Đặt `ZKSTEGO_SKIP_LEARNED=1` (hoãn steganalysis học máy:
  trích đặc trưng ML, đánh giá FLD, mô phỏng nhúng, CNN) và
  `ZKSTEGO_ANALYSIS_WORKERS=2`. Mỗi bước log vào `tmp/rerun_v2/<step>.log`; bước
  lỗi không dừng cả run. Các bước: `repro.py all --skip-prepare --workers 1`,
  GOP>1 eval, STC adaptive E2E, binary proof bench, idle-timing, rồi sinh báo cáo
  (`say "ALL DONE"` là mốc kết thúc). Launcher: `scripts/ops/launch_rerun_v2_eval.sh`
  (ghi ra `tmp/rerun_v2.out`).
- `scripts/ops/system_e2e.sh` — **kiểm tra chức năng mọi chế độ** dưới v2; mỗi
  kịch bản nhúng, verify từ video, và từ chối phát lại + sửa 1 bit. Đặt
  `ZKSTEGO_ANALYSIS_WORKERS=4`, `timeout 2400` mỗi kịch bản (quá 40 phút coi là
  treo). 7 kịch bản (magnitude, in-band, t1, STC, adaptive-chunk, codec v2,
  gop8), rồi `repro.py unit-tests`. Launcher: `launch_system_e2e.sh`. Kết quả:
  `benchmark/results/q2/system_e2e_check_*.json`.

### Bộ giám sát RAM — `scripts/ops/sweep_supervisor.ps1`

Dừng (pause) run v2 khi bộ nhớ căng, chạy lại khi máy có chỗ; vì run v2 bỏ qua
case đã xong nên pause chỉ mất case đang chạy dở. Theo dõi `\Memory\Available
MBytes` và `\Memory\% Committed Bytes In Use`, poll mỗi 30 s, log vào
`tmp/rerun_v2/supervisor.txt`; dừng bằng cách xóa cờ `tmp/rerun_v2/supervise.flag`.

- **Pause** (taskkill các tiến trình sweep khớp): khi commit **≥ 97 %**.
- **Resume** (chạy lại launcher): khi available **≥ 6000 MB** và commit **< 85 %**
  liên tục 6 lần poll (~3 phút).
- **Thoát**: khi `tmp/rerun_v2/progress.txt` chứa `ALL DONE`.

## 6. Hướng dẫn bộ nhớ và biến môi trường

- **`ZKSTEGO_ANALYSIS_WORKERS`** (`src/core/parallel_analysis.py`): giới hạn số
  tiến trình worker phân tích carrier. Mặc định `max(1, min(8, cpu_count))`;
  `0`/`1` = tuần tự. Nhiều worker = nhiều buffer đồng thời = RSS đỉnh cao hơn.
- **`ZKSTEGO_SKIP_LEARNED=1`**: hoãn/bỏ các bước steganalysis học máy (ML/CNN).
- **`ZKSTEGO_LATTICEZK_SYNC_KEY_HEX`**: sync key verifier (64 hex) cho đường CLI.

Ước lượng RAM (trích tài liệu):

| Tình huống | RAM | Nguồn |
|---|---|---|
| Một E2E CIF | 1–3 GB mỗi lượt | `ARTIFACT.md:263` |
| `reproduce_small` (100 khung) | < 2 GB; đỉnh ~1 736 MiB | `ARTIFACT.md:212, 324` |
| 4CIF với 8 worker (mặc định) | đỉnh ~7 GB | `scripts/ops/rerun_v2_eval.sh:10` |
| 4CIF, 2 case nặng cạnh IDE | **vượt 24 GB** → chạy `--workers 1` | `rerun_v2_eval.sh:27` |
| HD 720p / 1080p | ~80 MB / ~180 MB mỗi khung; segment đỉnh ~2 GB | `docs/GOP_HD_SUPPORT.md` |

**Bẫy RAM đã biết**: 8 worker mặc định trên 4CIF (~7 GB) là quá nhiều khi mở IDE
+ agent — đặt `ZKSTEGO_ANALYSIS_WORKERS=2` và chạy sweep `--workers 1` cho 4CIF;
dùng `sweep_supervisor.ps1` để tự pause ở ngưỡng commit 97 %.

## 7. Đọc file kết quả JSON (`benchmark/results/q2/`)

Tiền tố file: `capacity_*` (quét dung lượng), `e2e_*` (báo cáo E2E mỗi case,
hậu tố `_reg`/`_inband`/`_t1`/`_d25`/`_d50`; `.skipped.json` = envelope không
vừa), `steg_*` (steganalysis cổ điển), `ml_eval*.json` (steganalysis học máy
FLD), `cnn_*` (CNN), `adaptive_*` (carrier/chunk thích nghi), `gop_*` (GOP>1),
`hd_*` (HD), `binary_proof_bench.json`, `payload_range_proof_bench.json`,
`baselines_<ngày>.json`, `system_e2e_check_<ngày>.json`, `SUMMARY.md` (bảng gộp).
Trường then chốt trong báo cáo E2E/system: `verified_from_video_alone`,
`replay_rejected`, `tamper_rejected`, `payload_absent_from_output`,
`envelope_bytes`, `psnr_modified_db`, `psnr_worst_db`.

### Chế độ offline theo epoch và đính kèm range proof (CLI, 2026-10-26)

```bash
# ISSUER: phát một thử thách cho cửa sổ giờ hiện tại (ký ML-DSA-65)
python -m src.lattice_zk.cli epoch-issue --issuer-private issuer.key --out epoch.json --window-seconds 3600

# HOLDER: nhúng không cần phiên tương tác
python -m src.lattice_zk.cli embed --video cover.h264 --output stego.h264 --epoch-beacon epoch.json   --payload-file payload.bin --opening-out opening.json   --registry registry.json --issuer-public issuer.pub --minimum-epoch 1

# VERIFIER: --database giữ sổ chống phát lại của riêng verifier này
python -m src.lattice_zk.cli verify --video stego.h264 --database ledger.sqlite --epoch-beacon epoch.json   --registry registry.json --issuer-public issuer.pub --minimum-epoch 1

# IN-BAND + range proof: ghim độ dài 32 byte ở mọi phía (registry-sign, embed, verify,
# disclosure-verify); payload ngắn hơn được đệm tự động (0x80 rồi 0x00).
python -m src.lattice_zk.cli registry-sign --issuer-private issuer.key --epoch 1 --out registry.json --payload-range-bytes 32
```

Mặc định codec policy nay là `v2`; video/registry cũ dùng `--codec-policy v1`;
video H.264 Main/High (CABAC) dùng `--codec-policy cabac` (carrier ở lát I/IDR,
hợp đồng CABAC tự chọn; `docs/CABAC_SUPPORT.md` §6). `--gop-policy
idr-carriers-inter-raw-v1` cho luồng GOP>1 (CAVLC hoặc CABAC).
`--adaptive-chunks` bật ZKBC v2 thích nghi dung lượng (thay `--chunk-bytes`).
E2E toàn hệ dưới v3: `bash scripts/ops/system_e2e_v3.sh` (báo cáo
`tmp/system_e2e_v3/*.json`, gồm kịch bản `inband_range32` và `reg_codec_v1`).
