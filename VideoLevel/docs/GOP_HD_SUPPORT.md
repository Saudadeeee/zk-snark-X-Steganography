# GOP > 1 và luồng HD (roadmap B3)

Trạng thái: các luồng Baseline GOP > 1 (slice IDR + P) được hỗ trợ sau một GOP
policy mới của carrier profile; các luồng all-intra 720p/1080p, gồm cả nhiều
slice mỗi ảnh, parse và tính lại carrier của chúng. Hành vi all-intra giống hệt
từng byte với commit `dddb9d5` (vị trí carrier, video digest, byte stego và mọi
id carrier-profile all-intra, ghim bởi
`src/runtest/test_gop_and_hd_support.py`).

## Điều gì xảy ra trước thay đổi này

Đo trên mã `dddb9d5` với các clip CIF mã hóa bằng `-g 8` và `-g 25`:

* **Phân tích** chỉ parse các NAL unit IDR. Các slice P bị bỏ qua nhưng vẫn làm
  tăng bộ đếm ảnh, nên tọa độ carrier giữ `picture_index x MBs + mb`; không gì
  bị từ chối hay parse sai.
* **Patching** chỉ ghi lại các slice IDR; mọi NAL unit khác được ghi lại từ RBSP
  của nó. Các slice P ra giống hệt từng byte (175/175 trên container g8).
* **Canonical digest** băm các trường header và RBSP raw của mọi NAL unit không
  IDR, nên các slice P đã được gắn, trừ một malleability: parser lột mọi
  `00 00 03`, nên một byte emulation-prevention thừa đổi file nhưng không đổi
  digest.
* **Segment hóa** (`ffmpeg -f segment -segment_frames 100,200,...`) chỉ cắt ở
  các key frame. Với GOP 8 một cắt ở khung 100 dịch sang 104 và kiểm tra số khung
  fail closed ("chọn biên căn theo khung IDR"); với GOP 25 hoặc `frames_per_segment`
  là bội của GOP thì được.
* **Statement** không phân biệt cấu trúc luồng: một video GOP > 1 verify dưới
  cùng carrier profile với một video all-intra.
* **Nhiều slice mỗi ảnh** parse được (mỗi slice NAL nhận slot tọa độ cỡ-ảnh
  riêng), nhưng transport toàn cục hóa vị trí bằng `frame_offset x MBs`, nên với
  `k` slice mỗi ảnh các slot của segment `i` chồng lên các slot của segment
  `i+1`.

## Điều gì được hỗ trợ bây giờ

### GOP policy (`src/transport/gop_policy.py`)

`CarrierProfile(..., gop_policy=...)` trong `src/lattice_zk/video_pipeline.py`:

| policy | luồng | carrier | NAL unit khác |
|---|---|---|---|
| `all-intra` (mặc định) | mọi slice đã mã hóa là IDR | block luma 4x4 IDR | raw RBSP trong digest |
| `idr-carriers-inter-raw-v1` | Baseline GOP > 1: slice IDR, P và I không IDR | chỉ block luma 4x4 IDR | raw RBSP trong digest |

Mọi transport segment (cover khi nhúng, stego khi trích, cả segment carrier lẫn
segment băm-raw) được kiểm từ byte Annex B của nó trước mọi phân tích; vi phạm
ném `ValueError`, điều verifier báo là `valid=False`:

* slice đã mã hóa đầu tiên của mỗi segment là một slice IDR (nên mọi cắt là một
  access unit IDR và không segment nào tham chiếu ảnh của segment khác), và số
  ảnh bằng số khung đã giải mã của ffprobe;
* `all-intra`: không có slice không IDR nào (nên một luồng GOP > 1 bị từ chối
  dưới profile all-intra, với thông báo nêu tên GOP policy);
* chỉ slice I và P (không B, SP, SI), không data partitioning, không arbitrary
  slice order, không ảnh trộn slice IDR và không IDR, `first_mb_in_slice` trong
  ảnh, không slice group (FMO), không ảnh dư, không CABAC; một SPS Baseline
  progressive (`profile_idc` 66, `frame_mbs_only_flag` 1); SPS/PPS giống hệt
  trong một segment và có mặt trước slice đầu tiên;
* không có byte ngoài NAL unit (trước start code đầu tiên, hoặc một start code
  không có NAL unit);
* emulation prevention canonical trong mọi NAL unit (escape đúng cái tối thiểu
  của RBSP của nó), và `forbidden_zero_bit = 0`. Với điều này, RBSP bằng nhau là
  NAL byte bằng nhau, nên digest gắn mọi byte slice P.

Policy là một phần của carrier profile id chỉ khi nó không phải mặc định:

```text
profile description += {"gop_policy": "idr-carriers-inter-raw-v1"}
```

nên một statement GOP > 1 có `carrier_profile_id`, policy hash, relation id và
registry entry khác với một statement all-intra, và các id all-intra không đổi.
`codec_policy_id` không đổi. Đây là thay đổi duy nhất trong `src/lattice_zk/`
(không chạm mã mật mã nào).

### Quy tắc digest

Công thức không đổi (`docs/LATTICE_ZK_BDLOP_SPEC.md` 3.6). Mỗi carrier segment:
các NAL unit IDR có carrier đóng góp các bit RBSP giữa các block carrier cộng
các block carrier đã chuẩn hóa; mọi NAL unit khác, đặc biệt mỗi slice P, đóng
góp các trường header và RBSP đầy đủ của nó. Các segment không có carrier được
băm như file. Thay đổi một bit bất kỳ của bất kỳ slice P nào đều đổi `D` (đã
test ở mức digest và end to end).

### Segment hóa

Các segment giữ độ dài cố định (`frames_per_segment`, gắn trong profile). Với
GOP > 1 hãy chọn một bội của độ dài GOP (ví dụ 104 hoặc 200 cho GOP 8, 100 cho
GOP 25); giá trị khác fail closed. Do đó các segment là các GOP trọn vẹn. Vì chỉ
ảnh IDR mang carrier, dung lượng của một segment là `frames_per_segment / GOP`
ảnh IDR; các segment dài hơn không tốn bộ nhớ (slice P không bao giờ bị parse).

### Nhiều slice mỗi ảnh

Mỗi slice đã mã hóa giữ slot tọa độ cỡ-ảnh riêng (như phân tích vốn đã làm), và
transport nay offset mỗi segment theo số slice đã mã hóa trước nó thay vì số
khung. Với một slice mỗi ảnh thì hai cái bằng nhau, đó là lý do đầu ra một-slice
giống hệt từng byte. Các luồng nhiều slice nhận vị trí toàn cục khác (nay không
va chạm), do đó một `positions_hash` khác, so với `dddb9d5`; các kiểm tra cấu
trúc chặt hơn cũng từ chối các luồng mà `dddb9d5` chấp nhận (escape không
canonical, byte ngoài NAL unit, bộ tham số thay đổi, SPS không Baseline). Đầu ra
x264 vượt qua tất cả. Các slice khởi động lại ngữ cảnh neighbour CAVLC, điều
parser vốn đã làm theo từng NAL unit. x264 phát một slice mỗi ảnh trừ khi dùng
`slices=N`, `slice-max-size` / `slice-max-mbs` hoặc sliced threads (ví dụ
`-tune zerolatency`).

### HD

* Số MB từ SPS (`80 x 45` ở 720p, `120 x 68` ở 1080p); cropping (1088 -> 1080)
  chỉ ảnh hưởng hiển thị và để decoder lo.
* Giới hạn Level: x264 chọn Level 3.1 (720p) / 4.0 (1080p); không gì trong
  parser phụ thuộc level.
* Phân tích stable-carrier đã dùng số MB từ SPS (fix trước,
  `test_non_cif_carrier_capacity.py`). Các heuristic thứ tự nhúng của các hợp
  đồng gốc (`sort_blocks_interleaved`, ưu tiên hàng dưới của chaos shuffle) vẫn
  giả định lưới CIF 22 x 18; ở 4CIF/HD chúng chỉ đổi thứ tự xác định, giống hệt
  khi nhúng và khi trích, không đổi tính đúng. Các hợp đồng `*-geo` sắp cùng các
  carrier trên lưới SPS; xem "Thứ tự carrier theo độ phân giải" bên dưới.

### Thứ tự carrier theo độ phân giải (stream C4)

**Kiểm kê** hình học CIF hard-code trong đường carrier (`22`, `396`, `18`,
`cif_mb_count`, `mb_width`, `macroblocks_per_frame`):

| nơi | hằng số | lớp | trạng thái |
|---|---|---|---|
| `core/analysis_cache._build_serial_analysis`, các job `core/parallel_analysis` | `cif_mb_count` (IDR offset của một block) | tính đúng | số từ SPS (fix trước); `396` chỉ làm fallback khi context không có |
| `core/stego.CAVLCSafetyFilter.get_safe_positions` | mặc định `cif_mb_count=396` | tính đúng (fail closed) | mọi caller đường carrier truyền số SPS; giá trị sai không tìm thấy IDR, nên không có carrier, không bao giờ sai |
| `bitstream_ops.reconstruct_video`, `analysis_cache._build_reconstruction_context` | `mb_count_per_slice`, fallback `264` khi không có SPS | tính đúng | số SPS; fallback không tới được (GOP policy đòi một SPS trước slice đầu tiên) |
| `bitstream_ops._calculate_nC(pic_width_in_mbs=22)` | width | không | mã chết (không caller); nC tính trong macroblock |
| toàn cục hóa `blind_sync_streaming`, `blind_sync_adaptive`; kiểm tra tamper RBSP E2E | MB mỗi slot | tính đúng | số SPS, một slot mỗi slice đã mã hóa |
| `core/chaos.ChaosTransformer.shuffle_positions` | `396`, `22`, hàng dưới `14` | thứ tự/chất lượng | các hợp đồng gốc (ghim); gom các "khung" 396-MB (một phần tư ảnh ở 4CIF, trải qua các ảnh ở HD) và ưu tiên các sọc 88 MB giữa ảnh |
| `core/stego.sort_blocks_interleaved` (`stego.py`, `parallel_analysis.py`) | `_CIF_MB_COUNT`, `_CIF_MB_WIDTH` | thứ tự/chất lượng | thứ tự trước-shuffle của phân tích sign-bit (`t1`) và đầy đủ; ghim cho các hợp đồng gốc, bỏ qua bởi các hợp đồng `*-geo` (canonical order trước) |
| `blind_sync._cap_per_idr`, `_filter_bottom_zone`, `derive_blind_positions_*` | `cif_mb_count=396`, `cif_mb_width=22` | thứ tự/chất lượng | chỉ dùng bởi các hợp đồng có `max_bits_per_idr` / `bottom_rows` > 0 (các hợp đồng header/diagnostic, không cái nào thuộc lattice); các hợp đồng `*-geo` truyền hình học SPS |
| `core/matrix_embedding.rank_positions_cost_guided`, chaos shuffle `embedder.py`, `core/pipeline*` | `396` | thứ tự/chất lượng | chỉ pipeline SEC1 CIF legacy, không trên đường lattice |
| `bitstream_ops.batch_psnr_validate` | "4 hàng dưới" | chất lượng | đã dùng width SPS; số hàng tinh chỉnh trên CIF (pipeline legacy) |
| `benchmark/_common.py`, `sec1_quality.py`, `sec2_capacity.py`, `sec3_methods.py`, `blind_sync_diagnostic.py`, `validated_pool_proxy_diagnostic.py`, `latticezk_adaptive_e2e.py`, `latticezk_adaptive_sim.py` | `396` / `22` | chỉ benchmark | benchmark CIF (tên case là CIF) |
| `latticezk_ml_steganalysis.py`, `latticezk_embedding_sim.py` | `--macroblocks-per-frame` mặc định `396` | chỉ benchmark | sweep Q2 truyền `macroblocks_per_frame` của case (3 600 / 8 160 trong các case HD) |

**Fix.** Các hợp đồng gốc giữ thứ tự lưới-CIF: carrier profile id, positions
hash, canonical digest và byte stego của chúng được ghim (ghi với commit
`c027c87` trước thay đổi) bởi `src/runtest/test_geometry_aware_ordering.py` trên
một cắt CIF của một fixture đã checked-in và một clip 4CIF tổng hợp, và cũng được
kiểm trên một cắt foreman CIF 10 khung và một cắt city 4CIF 4 khung
(`benchmark/results/q2/hd_order_compat.json`). Ba hợp đồng mới chọn thứ tự
hình-học-SPS qua một trường `carrier_order` (nên `dataclasses.asdict`, carrier
profile id, policy hash, relation và public sync key đều khác):

| E2E `--carrier` | phiên bản hợp đồng | carrier dưới dạng |
|---|---|---|
| `magnitude-geo` | `stable-carriers-sps-geometry-v1` | `magnitude` |
| `t1-geo` | `t1-sign-sps-geometry-v1` | `t1` |
| `adaptive-geo` | `adaptive-stc-magnitude-sps-geometry-v1` | `adaptive` (STC coded) |

`src/core/carrier_order.py` (`sps-geometry-low-drift-v1`): thứ tự canonical
`(mb, block, coefficient)`; gom theo slot `mb // (W x H)` từ SPS (một slot mỗi
slice đã mã hóa); trong một slot `round(2/9 x rows)` hàng cuối của phạm vi carrier
của slot trước (4 trên 18 ở CIF, 8 ở 4CIF, 10 ở 720p, 15 ở 1080p; theo từng
slice với ảnh nhiều slice, vì dự đoán intra không vượt qua slice), mỗi nhóm theo
thứ tự keyed SHA-256; các slot round-robin. Các bộ lọc `max_bits_per_idr` /
`bottom_rows` cũng dùng lưới SPS. Thứ tự chỉ phụ thuộc tập carrier (bất biến khi
nhúng), SPS và khóa, nên extractor tính lại nó từ stego.

## Số đo (CIF, QP 22, carrier magnitude)

`python -m benchmark.latticezk_gop_eval --cases benchmark/latticezk_gop_cases.json
--data-root <cây có data/raw>`; kết quả trong `benchmark/results/q2/gop_*.json`
và `gop_summary.json`. Mã hóa (trong `latticezk_gop_eval.encode_command`):

```text
ffmpeg -i data/raw/<clip>.y4m -frames:v N -c:v libx264 -profile:v baseline -coder 0 -bf 0 \
       -g G -keyint_min G -sc_threshold 0 -qp 22 -threads 4 -f h264 <clip>_gG.h264
```

Lượt chạy end-to-end dùng bộ tham số **TOY** (registered, envelope 413 byte) vì
envelope BDLOP_OPEN_128 8 165 byte (7 589 B với v1) không vừa một clip CIF
GOP > 1 200-300 khung (xem "số khung cần"); các đường mã transport, digest và
statement là như nhau. Chất lượng là luma PSNR của stego đã giải mã so với cover
đã giải mã, mọi khung kể cả khung P. Mỗi dòng là một lượt với một sync key ngẫu
nhiên, nên các carrier (và PSNR) khác nhau giữa các lượt: một lượt container GOP
8 trước đó cho 46.80 / 43.96 / 38.67 dB.

| clip (khung) | GOP | seg. | bit carrier /100 kh | bit /IDR | reg. 128-bit cần (khung) | carrier dùng / IDR chạm | khung đổi | PSNR all | PSNR đổi | khung tệ nhất |
|---|---|---|---|---|---|---|---|---|---|---|
| container (200) | 1 | 100 | 50 757 | 508 | 120 | 3 600 / 100 | 100 | 63.71 | 60.70 | 55.58 |
| container (200) | 8 | 104 | 6 376 | 510 | 953 | 3 600 / 13 | 104 | 47.02 | 44.18 | 40.91 |
| container (200) | 25 | 100 | 2 030 | 507 | 2 992 | 3 896 / 8 | 200 | 39.25 | 39.25 | 32.02 |
| foreman (300) | 1 | 100 | 14 178 | 142 | 429 | 3 600 / 100 | 100 | 58.87 | 54.09 | 42.39 |
| foreman (300) | 8 | 152 | 1 793 | 142 | 3 387 | 3 896 / 38 | 300 | 53.21 | 53.21 | 44.57 |
| foreman (300) | 25 | 100 | 522 | 131 | 11 631 | không vừa (TOY cần 16 segment 27 B) | – | – | – | – |

Mọi lượt verify blind; replay, một tamper một-bit ngẫu nhiên và một lật một-bit
trong một slice P của một carrier segment đều bị từ chối (lý do: sai khớp
statement, tức digest, không phải lỗi parse); mọi slice P giống hệt từng byte
(175/175, 192/192, 262/262). Nhúng / verification mất 8-14 s / 4.7-6.3 s cho
GOP > 1 so với 16-46 s / 13-42 s all-intra (chỉ slice IDR được parse).

**Dung lượng.** Một ảnh IDR mang những gì một khung all-intra cùng nội dung
mang (508 so với 510 bit cho container), và các slice P không mang gì, nên dung
lượng mỗi khung giảm theo độ dài GOP. Envelope registered 128-bit cần ~1 000
khung (40 s ở 25 fps) cho container ở GOP 8, ~3 000 (2 phút) ở GOP 25; foreman
ít kết cấu cần 3 400 và 11 600 khung.

**Drift.** Các slice P không bị chạm nhưng dự đoán từ IDR đã sửa, nên mọi khung
của một GOP mà IDR của nó thay đổi đều khác cover (`khung đổi` = GOP x IDR
chạm). Trong một GOP lỗi không tăng cũng không giảm nhiều: container mất 0.04 dB
qua 7 khung P ở GOP 8 và 0.09 dB qua 24 ở GOP 25
(`luma_psnr_by_gop_position_in_modified_gops_db`); foreman, có chuyển động, hồi
phục 0.6 dB vào cuối GOP. Khung tệ nhất là một IDR hoặc một khung P muộn của một
GOP dày.

**Chi phí chất lượng so với all-intra.** Nó đến từ mật độ, không từ tích lũy
drift: cùng envelope được nhồi vào số ảnh ít hơn GOP lần (container: 36 carrier
mỗi IDR ở GOP 1, 277 ở GOP 8, 487 ở GOP 25), và méo của mỗi ảnh bị sửa rồi được
chép vào GOP-1 khung P. Với cùng envelope, PSNR trên khung đổi của container
giảm từ 60.7 dB xuống 44.2 và 39.3 dB, khung tệ nhất từ 55.6 xuống 40.9 (38.7 ở
lượt khác) và 32.0 dB. Foreman, có các IDR nghèo carrier, giữ ở 53-54 dB vì số
thay đổi mỗi IDR nhỏ dù thế nào.

## Mức sẵn sàng HD

Test ở đây chỉ trên encode tổng hợp (`test_gop_and_hd_support.py`): 1280x720 với
bốn slice mỗi ảnh (parse, một slot mỗi slice, carrier trong mọi slice, hai
segment một-khung với vị trí toàn cục rời nhau, trích và tính lại carrier bằng
nhau) và 1920x1080 (SPS 120 x 68, giải mã crop 1920x1080, embed/extract và tính
lại bằng nhau).

**Bộ nhớ và thời gian** (`benchmark/latticezk_hd_profile.py`, phân tích tuần
tự, một segment = cắt; phân tích + nhúng + trích; kết quả trong
`benchmark/results/q2/hd_profile_*.json`):

| cắt | MB/ảnh | block luma mã hóa/khung | đỉnh MB/khung | s/khung (3 pass) |
|---|---|---|---|---|
| city 4CIF (tự nhiên) | 1 584 | 24 200 | 35.5 | 10.2 |
| container upscale lên 720p | 3 600 | 38 000 | 69.3 | 8.5 |
| container upscale lên 1080p | 8 160 | 70 400 | 117 (phân tích) | 24.1 |
| testsrc2 + noise, 1080p (mọi block mã hóa) | 8 160 | 130 000 | 199 | 41.3 |

Bộ nhớ là 1.2-1.6 KB mỗi block luma mã hóa (offset, hệ số, nC, độ dài giữ theo
từng block) cộng ~50 MB. Scale nội dung 4CIF tự nhiên theo macroblock cho
**~80 MB mỗi khung 720p và ~180 MB mỗi khung 1080p** (chặn trên ~90 / ~200 MB)
của segment, và ~7.7 / ~17.6 s mỗi khung mỗi pass (tuần tự). Đỉnh phụ thuộc
`frames_per_segment` thôi (mỗi lúc chỉ một segment được phân tích), nên các case
HD dùng segment 25-khung (720p) và 10-khung (1080p): đỉnh ~2.1 GB và ~1.9 GB.
Với GOP > 1 chỉ ảnh IDR tính (một segment GOP 8 200 khung ở 720p chứa 25 IDR,
~2.1 GB). Dung lượng HD tự nhiên chưa đo; scale city 4CIF (~1 000 bit mỗi khung
ở QP 22) gợi ý ~2 300 (720p) và ~5 200 (1080p) bit mỗi khung, nên một envelope
registered 128-bit cần 2-3 segment.

### Đo trên các cắt HD tự nhiên (stream C4, một phần)

Các cắt 10 khung, libx264 Baseline all-intra QP 22 (`-g 1 -keyint_min 1
-sc_threshold 0 -coder 0 -bf 0`), `frames_per_segment` 5, carrier magnitude,
`ZKSTEGO_ANALYSIS_WORKERS=2`, chạy cạnh một job nặng bộ nhớ khác. Kết quả trong
`benchmark/results/q2/hd_order_*.json` (`benchmark/latticezk_hd_order.py`).
Bộ canh RAM (available < 1.2 GB, do job kia gây ra) đã ngắt ba lượt chạy; file
của chúng ghi `"complete": false`, và các benchmark này sau đó bị hoãn.

| cắt | bit carrier / ảnh | envelope registered v2 (8 165 B) cần |
|---|---|---|
| park_joy 720p | 4 668-6 157 (mean 5 455) | 13 ảnh (fill 1.0), 14 (0.9), 25 (0.5) |
| park_joy 720p, 4 slice | 4 666-6 178 (mean 5 474) | như trên |
| riverbed 1080p | 147-205 (mean 171) | ~400 ảnh; cả clip 250-khung chứa < 43 kbit, nên **không vừa** với carrier magnitude |

Vậy envelope v2 không vừa bất kỳ cắt HD 10-khung nào; lượt chạy end-to-end dùng
bộ **TOY** registered (413 B): park_joy 720p, adaptive chunk, một segment mang
3 584 carrier; `magnitude-geo` verify blind, replay và một tamper một-bit bị từ
chối (embed 61 s, verify 52 s, đỉnh RSS cây tiến trình 477 MB); thứ tự
`magnitude` gốc trên cùng cắt cũng verify (37 s / 28 s, 448 MB; sync key ngẫu
nhiên khác giữa hai lượt).

PSNR của các khung đổi / khung tệ nhất (dB), thứ tự lưới-CIF gốc -> thứ tự
hình-học-SPS, cùng payload, khóa và chunk layout mỗi cặp:

| cắt, fill | gốc | hình học |
|---|---|---|
| park_joy 720p, 0.25 (key 0 / key 1) | 42.68 / 37.25, 44.09 / 39.67 | 41.69 / 37.42, 44.14 / 38.67 |
| park_joy 720p, 0.5 | 37.98 / 33.37 | 40.67 / 34.93 |
| park_joy 720p, 0.9 | 36.84 / 33.84 | 36.40 / 30.90 |
| park_joy 720p 4 slice, 0.25 | 43.84 / 39.77 | 45.72 / 41.60 |
| park_joy 720p 4 slice, 0.5 | 40.00 / 36.29 | 40.96 / 34.88 |
| riverbed 1080p, 0.5 | 49.37 / 47.09 | 51.75 / 49.44 |
| E2E TOY (12 % của segment 0, khóa khác) | 48.38 / 46.49 | 46.80 / 42.95 |

Qua bảy lượt theo cặp, thứ tự hình học được +0.9 dB trên các khung đổi trung
bình (khoảng -1.0 đến +2.7) và +0.1 dB trên khung tệ nhất (khoảng -2.9 đến
+2.4): không có cải thiện chất lượng nhất quán ở cỡ mẫu này. Dồn các carrier đầu
vào 22 % dưới của mỗi ảnh rút ngắn đường drift nhưng nâng mật độ thay đổi cục
bộ, và hai hiệu ứng gần như triệt tiêu. Do đó các hợp đồng hình học là một fix
tính-đúng/nhất-quán của thứ tự (ảnh thật, hàng dưới thật, vùng theo slice),
không phải một cải thiện chất lượng đã chứng minh. Bộ nhớ đỉnh: ~690 MB cho
segment 720p 5-khung (phân tích + embed + trích), ~955 MB cho segment 1080p
5-khung; ~10 s mỗi khung 720p mỗi embed (hai pass phân tích, tái dựng, kiểm tra
giải mã) dưới tranh chấp.

**Chưa đo** (hoãn): lặp đa khóa (5 trên 12 lượt xong), multi-slice và 1080p fill
0.9 với trích, dung lượng old_town_cross và pedestrian, dung lượng trailing-one
(`t1-geo`) ở HD, bất kỳ lượt end-to-end HD v2 (8 165 B) nào, và
`latticezk_hd_profile` trên các cắt tự nhiên.

## Giới hạn

* Carrier chỉ đến từ slice IDR; slice I không IDR và slice P không mang gì
  (carrier residual slice P sẽ cần kiểm soát drift bù chuyển động và patching
  CAVLC inter, chưa thử).
* GOP > 1 cần một GOP cố định mà độ dài chia hết `frames_per_segment` (mã hóa
  với `-keyint_min G -sc_threshold 0`, GOP đóng, không khung B); các recovery
  point open-GOP, slice B, FMO/ASO và ảnh dư bị từ chối.
* Drift tới mọi khung của một GOP bị chạm. Guard chất lượng operating-envelope
  (mọi khung bị sửa >= 40 dB) đạt cho foreman ở GOP 8 (tệ nhất 44.6 dB), biên
  giới cho container ở GOP 8 (40.9 / 38.7 dB trong hai lượt) và thất bại ở GOP 25
  (32.0 dB), kể cả với envelope 413 byte; trải envelope qua nhiều GOP hơn (chunk
  nhỏ hơn, clip dài hơn) là đòn bẩy, như với all-intra.
* Bộ nhớ HD tăng theo `frames_per_segment x MB mỗi ảnh` (phân tích giữ offset
  của mọi block mã hóa); chọn segment ngắn ở 1080p.
* Các heuristic thứ tự của hợp đồng gốc giả định lưới CIF (chỉ thứ tự, ghim); các
  hợp đồng `*-geo` dùng lưới SPS, không có lợi ích PSNR nhất quán nào đo được tới
  nay.
* Carrier magnitude mỏng trên nội dung 1080p mượt (riverbed: ~171 bit mỗi ảnh),
  quá ít cho envelope 128-bit trong cả clip; các clip như vậy cần carrier
  trailing-one, mà dung lượng HD của nó chưa đo.
* Envelope 128-bit chưa được chạy end to end trên GOP > 1 hay HD ở đây (ràng
  buộc máy); các lệnh ở dưới.

## Lệnh cho người tích hợp

Không có nguồn 720p/1080p trong `data/raw`, và không có trong
`scripts/data_manifest.json`. Các chuỗi Xiph derf đã dùng (kích thước kiểm bằng
`curl -I`, 2026-10-21; thêm SHA-256 của chúng vào manifest sau khi tải):

```sh
cd VideoLevel
curl -L -o data/raw/park_joy_420_720p50.y4m       https://media.xiph.org/video/derf/y4m/park_joy_420_720p50.y4m        # 691 MB, 500 khung
curl -L -o data/raw/old_town_cross_420_720p50.y4m https://media.xiph.org/video/derf/y4m/old_town_cross_420_720p50.y4m  # 691 MB, 500 khung
curl -L -o data/raw/pedestrian_area_1080p25.y4m   https://media.xiph.org/video/derf/y4m/pedestrian_area_1080p25.y4m    # 1.17 GB, 375 khung
curl -L -o data/raw/riverbed_1080p25.y4m          https://media.xiph.org/video/derf/y4m/riverbed_1080p25.y4m           # 778 MB, 250 khung
sha256sum data/raw/*_720p50.y4m data/raw/*_1080p25.y4m
```

1. Sweep HD (mã hóa, quét dung lượng, E2E BDLOP_OPEN_128 registered với kiểm
   tra replay/tamper, steganalysis cổ điển), một case mỗi lần:

   ```sh
   ZKSTEGO_ANALYSIS_WORKERS=2 python -m benchmark.latticezk_q2_sweep \
       --cases benchmark/latticezk_hd_cases.json --workers 1 --work tmp/hd_sweep
   ```

   Các case dùng `magnitude-geo` (720p) / `t1-geo` (1080p) với chunk thích ứng
   theo dung lượng (không quét dung lượng; kế hoạch greedy dừng ở segment hoàn
   tất envelope, nên chỉ các segment đó được phân tích) và segment ngắn (10 khung
   ở 720p, 5 ở 1080p, 80 = 10 IDR cho case GOP 8). Ước tính từ các số đo trên:
   đỉnh ~1.1 GB mỗi tiến trình ở 720p (segment 10-khung) và ~1 GB ở 1080p
   (segment 5-khung), cộng ffmpeg. park_joy 720p cần ~14 ảnh (2 segment): ~10-15
   phút với các kiểm tra bảo mật; old_town_cross 720p chưa đo (ngân sách 30-60
   phút); case GOP 8 park_joy ~2 segment 10 IDR, ~20-30 phút. Các case `t1-geo`
   1080p là phần không chắc chắn: phân tích sign-bit tốn ~17 s mỗi khung 4CIF mỗi
   pass, tức ~90 s mỗi khung 1080p mỗi pass, và dung lượng của chúng chưa biết;
   đo nó trước và bỏ hoặc chỉnh cỡ các case đó nếu nó thấp:
   `ZKSTEGO_ANALYSIS_WORKERS=2 python -m benchmark.latticezk_capacity_scan data/encoded/riverbed_1080p_q22_g1_100f.h264 --carrier t1-geo --frames-per-segment 2 --segments 1`.
   So sánh thứ tự trên một cắt:
   `python -m benchmark.latticezk_hd_order --video <cắt> --frames-per-segment 5 --fill 0.25 0.5 --keys 3 --output benchmark/results/q2/hd_order_<name>.json`.
2. Envelope 128-bit ở GOP > 1 (CIF, nguồn lặp; phân tích chỉ-IDR, đỉnh < 1 GB):

   ```sh
   ZKSTEGO_ANALYSIS_WORKERS=2 python -m benchmark.latticezk_gop_eval \
       --cases benchmark/latticezk_gop_cases.json \
       --only container_g8_3000f_reg128 coastguard_g8_3000f_reg128 container_g25_6000f_reg128
   ```

   Kỳ vọng: container GOP 8 cần ~7 segment 200 khung (1 400 khung), coastguard
   GOP 8 ~8 (1 600), container GOP 25 ~17 (3 400); 10-30 phút mỗi cái.
3. Các case CIF ngắn được tái lập bằng cùng lệnh không có `--only`.
