# Kết quả đánh giá đến nay

Mục đích: tổng hợp kết quả đã đo, phân biệt rõ số của v2, số v1-era, và phần còn hoãn.
cập nhật: 2026-10-22

## 0. Kiểm tra toàn hệ dưới v3 (2026-10-26)

`scripts/ops/system_e2e_v3.sh` (codec policy v2 mặc định, `bdlop-open-128-v3`,
`ZKSTEGO_ANALYSIS_WORKERS=2–4`, máy đang tải song song nên thời gian chỉ tham
khảo). Tổng hợp: `benchmark/results/q2/system_e2e_check_20261026.json`
(`scripts/ops/system_e2e_summary.py`). **Mọi kịch bản verify từ video, từ chối
replay và sửa 1 bit.**

| Kịch bản | Chế độ | Codec | Envelope | Đoạn | PSNR sửa (dB) | Tệ nhất | SSIM | Nhúng (s) | Verify (s) | Kiểm tra thêm |
|---|---|---|---|---|---|---|---|---|---|---|
| reg_magnitude | registered | v2 | 8741 | 2 | 40.96 | 32.06 | 0.99957 | 393 | 161 | thêm byte sau stop-bit: từ chối |
| inband_magnitude | in-band | v2 | 16421 | 3 | 39.39 | 31.68 | 0.99940 | 355 | 149 | linkage + disclosure đạt |
| reg_t1 | registered | v2 | 8741 | 1 | 42.08 | 38.85 | 0.99508 | 163 | 138 | — |
| reg_stc | registered | v2 | 8741 | 2 | 42.57 | 31.24 | 0.99970 | 304 | 149 | — |
| reg_adaptive_chunk | registered (ZKBC v2) | v2 | 8741 | 2 | 39.55 | 32.35 | 0.99953 | 376 | 148 | plan khác: từ chối |
| reg_codec_v1 | registered | v1 | 8741 | 2 | 40.87 | 31.51 | 0.99956 | 411 | 175 | tương thích ngược |
| reg_gop8 | registered, GOP 8, 3000 khung | v2 | 8741 | 7 | 39.80 | 33.12 | 0.99971 | 198 | 85 | lật bit lát P: từ chối |
| inband_range32 | in-band + range proof L=32 (coastguard 3000 khung, ZKBC v2) | v2 | 63094 | 15 | 39.56 | 30.39 | 0.99967 | 1873 | 698 | linkage + disclosure đạt; plan khác: từ chối |

So với v2 (bảng mục 1): PSNR khung sửa thấp hơn 0.4–0.8 dB do envelope lớn hơn
7 %. Mật mã v3 (`crypto_bench_v3.json`, `binary_proof_bench_v3.json`,
`payload_range_proof_bench_v3.json`; một luồng, trong lúc một E2E chiếm 4 lõi):
commit 50 ms, prove median 221 ms (p95 671), verify 53 ms; equality prove 2.8 s /
verify 111 ms; binary proof 3.8 s / 86 ms (45 134 B); range proof L=32 6.3 s /
100 ms (46 670 B), L=64 3.9 s / 161 ms (55 886 B). Số đo lúc máy tải nặng hơn
giữ ở `*_v3_loaded.json`.

> Quy ước phiên bản: envelope **8741 B (registered) / 16421 B (in-band)** là
> `bdlop-open-128-v3` (sản xuất từ 2026-10-26); **8165 B / 14885 B** là
> `bdlop-open-128-v2`; **7589 B / 14309 B** là `bdlop-open-128-v1`.
> Mọi bảng lấy từ `benchmark/results/q2/SUMMARY.md` là **v1-era** trừ khi nói
> khác; kiểm tra chức năng dưới đây là v2.

## 1. Kiểm tra chức năng mọi chế độ (v2)

Nguồn: `benchmark/results/q2/system_e2e_check_20261021.json` (parameter set
`bdlop-open-128-v2`, code_commit `c027c87`). **7 kịch bản, tất cả**:
`verified_from_video_alone = true`, `replay_rejected = true`,
`tamper_rejected = true`, `payload_absent_from_output = true`.

| Kịch bản | Chế độ | Carrier contract | Envelope (B) | Seg | PSNR mod. (dB) | Worst (dB) |
|---|---|---|---:|---:|---:|---:|
| inband_magnitude | in-band | stable-carriers-video-only-v1 | 14885 | 3 | 39.97 | 31.40 |
| reg_magnitude | registered | stable-carriers-video-only-v1 | 8165 | 2 | 41.71 | 33.68 |
| reg_t1 | registered | t1-sign-video-only-v2 | 8165 | 1 | 42.09 | 38.76 |
| reg_stc | registered | adaptive-stc-magnitude-video-only-v1 | 8165 | 2 | 43.28 | 33.78 |
| reg_adaptive_chunk | registered | stable-carriers-video-only-v1 (ZKBC v2) | 8165 | 2 | 39.29 | 34.03 |
| reg_codec_v2 | registered | stable + codec policy v2 | 8165 | 2 | 41.23 | 32.75 |
| reg_gop8 | registered | stable + GOP>1 | 8165 | 7 | 40.45 | 33.04 |

Bổ sung: in-band có `disclosure_verifies = true` và `linked_to_credential =
true`; reg_codec_v2 có `trailing_rbsp_zero_rejected = true`; reg_gop8 có
`p_slice_tamper_rejected = true`. Thời gian embed/verify mỗi kịch bản ~1–5 phút
(phần lớn là phân tích CAVLC pure-Python, không phải chứng minh).

## 2. Kích thước và bảo mật v2

Nguồn: `src/lattice_zk/params.py`, `docs/LATTICE_ZK_BDLOP_SPEC.md` §2,
`research/bdlop_params/`.

- v3: commitment **7 680 B**, opening proof **8 672 B**, equality proof
  **17 312 B**; envelope registered **8 741 B**, in-band **16 421 B**; payload
  range proof đính kèm **46 670 B** (L ≤ 32) … **74 318 B** (L = 128).
  (v2: 6 720 / 8 096 / 16 160; 8 165 / 14 885.)
- Core-SVP v3 (classical/quantum): M-SIS binding **172 / 156**; M-LWE hiding
  **164 / 150** (dual hybrid; primal 169 / 153). lattice-estimator khớp
  (172,0 / 156,1; 164,9 / 150,3). v2: binding 140 / 127.
- Timing proof-only (micro-benchmark, **v1-era**): prove ~187 ms, verify
  ~41.9 ms (`SUMMARY.md` Baselines). **Số v2 cho prove/verify: cần đo lại.**

## 3. Dung lượng theo clip/QP (v1-era, `SUMMARY.md`)

Dung lượng carrier phụ thuộc mạnh vào clip, QP và loại carrier. Ví dụ
(bits/100 khung, mean):

| Clip | QP | magnitude | T1-sign | Registered vừa | In-band vừa |
|---|---|---:|---:|---|---|
| container_cif | 22 | ~49 768 | ~467 583 | có | có |
| coastguard_cif | 22 | ~36 331 | ~549 737 | có | không (magnitude) |
| city_4cif | 22 | ~82 265 | — | có | có |
| city_4cif | 28 | ~5 387 | — | không | không |
| crew_4cif | 22 | ~13 236 | — | không | không |

Ý chính: carrier **T1-sign** cho dung lượng lớn hơn magnitude khoảng một bậc;
clip QP cao (28) hoặc nhiều chuyển động (crew, football) có thể **không đủ**
chứa envelope. Số chi tiết: `SUMMARY.md` §"Carrier capacity" và
`benchmark/results/q2/capacity_*.json`.

## 4. Chất lượng (PSNR) (v1-era, `SUMMARY.md`)

- Registered: PSNR khung-bị-sửa thường ~**40–50 dB**, worst-frame ~**32–44 dB**,
  SSIM ~0.998–0.99998.
- In-band: ~40–45 dB (worst ~32–36 dB).
- STC giảm số thay đổi/bit (0.505 → 0.27–0.37) và tăng PSNR ~**+1.4–2.4 dB** so
  với nhúng trực tiếp (`SUMMARY.md` §STC).
- Kiểm tra chức năng v2 (§1) nằm trong cùng khoảng (39–43 dB mod).

## 5. Steganalysis

### Cổ điển (v1-era, `SUMMARY.md` §"Targeted classical steganalysis")

- Pairs-of-Values P(embed): 0.000 cho cả cover và stego (không áp dụng cho
  H.264 CAVLC theo cách này).
- SPA cover ≈ stego ở mọi case (ví dụ 0.407 vs 0.407) → **không phân biệt được**
  bằng SPA/histogram. T1-sign có p thấp hơn ở vài case (tức dễ lộ hơn magnitude).

### Học máy (FLD) và CNN — **còn là số v1 và đang hoãn đo lại v2**

Nguồn (v1): `SUMMARY.md` §"Learned steganalysis", §"CNN", và
`benchmark/results/q2/ml_eval*.json`, `cnn_*.json`.

- FLD ensemble / logistic, LOCO (leave-one-clip-out): P_E ≈ **0.40–0.46**
  (gần ngẫu nhiên 0.5); paired-split P_E ≈ 0.32–0.42.
- CNN magnitude LOCO: P_E frame **0.466**, segment 0.412; CNN **t1-spread** LOCO:
  P_E ~**0.27** (dễ phát hiện hơn magnitude). Khuếch đại 2× làm P_E sụt mạnh
  (bằng chứng CNN bắt được tín hiệu khi biên độ lớn).
- STC so với trực tiếp: P_E học máy worst-case LOCO 0.406 (direct) → 0.43
  (STC uniform) — khó phát hiện hơn một chút.

> **Hoãn (deferred)**: lượt chạy lại v2 (`rerun_v2_eval.sh`) đặt
> `ZKSTEGO_SKIP_LEARNED=1`, nên **mọi số steganalysis học máy vẫn là của v1**
> (envelope 7589 B; v2 lớn hơn ~8 %). Cần đo lại dưới v2 — xem `docs/ROADMAP.md`
> §"Việc hoãn lại" và `docs/CNN_STEGANALYSIS.md`.

## 6. GOP > 1 và HD

GOP > 1 (v1-era, `SUMMARY.md` §"GOP > 1"): carrier chỉ trong IDR, P-slice ràng
buộc raw; `p_slice_tamper_rejected = yes`. Dung lượng giảm mạnh theo GOP
(container 200 khung: ~50.8 → 6.4 → 2.0 kbit/100 khung ở GOP 1 → 8 → 25); PSNR
cũng giảm theo GOP. coastguard/container GOP8 3000 khung mang envelope 7589 B
thành công.

HD (720p/1080p): mới thử trên **encode tổng hợp** (`docs/GOP_HD_SUPPORT.md`,
`hd_profile_*`/`hd_order_*`), dùng thứ tự nhúng theo hình học SPS
(`magnitude-geo`) và chunk thích nghi; tốn RAM (~80 MB/khung 720p, ~180 MB/khung
1080p). **Sweep HD đầy đủ còn hoãn** (`benchmark/latticezk_hd_cases.json`).

## 7. So sánh baseline (v1-era, `SUMMARY.md` §Baselines)

| Scheme | PQ | ZK | Bytes trong video | Prove (ms) | Verify (ms) | Setup |
|---|---|---|---:|---:|---:|---|
| BDLOP (this work, registered) | có | có | 7589 (v1) | 187 | 41.9 | transparent |
| BDLOP (this work, in-band) | có | có | 14309 (v1) | 187 | 41.9 | transparent |
| Groth16 (BN128) | không | có | 147 | 7222 | 2550 | trusted, mỗi circuit |
| ML-DSA-44 (chữ ký) | có | không | 2420 | 18.6 | 0.33 | none |
| ISW21 (ghi nhận) | giả định KS hỏng | ZK 2^-40 | 23907 | 328 | 0.6 | trusted, DV |

Đây là so sánh định hướng (envelope v1); Groth16 nhỏ hơn nhưng **không** hậu
lượng tử và cần trusted setup; BDLOP minh bạch và hậu lượng tử.

## 8. Tóm tắt trạng thái

- Chức năng v2: **đạt** (7 chế độ verify từ video, chống phát lại + sửa 1 bit).
- Kích thước/bảo mật v3: đã chốt (M-SIS 172/156, M-LWE 164/150); v2 giữ để
  tham chiếu (140/127).
- Số v1-era cần cập nhật sang v2: steganalysis học máy/CNN, timing prove/verify
  đầy đủ, bảng E2E/capacity/baselines trong `SUMMARY.md` → **cần đo lại** khi
  chạy lại đánh giá v2 có bật ML.
