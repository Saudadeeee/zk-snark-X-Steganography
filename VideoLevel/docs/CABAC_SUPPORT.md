# Hỗ trợ H.264 CABAC (Main/High profile)

Cập nhật: 2026-10-26.

Tài liệu này mô tả phần hỗ trợ **CABAC gốc** cho pipeline bằng chứng lattice
(BDLOP) ẩn trong video: giấu phong bì vào chính dòng bit CABAC, kiểm tra mù chỉ
từ video stego, từ chối sửa đổi và phát lại. Trước đây hệ chỉ nhận Baseline
CAVLC; nay nhận cả video Main/High profile do libx264 (và bộ mã hoá chuẩn khác)
tạo ra.

## 1. Phạm vi

| Hỗ trợ | Không hỗ trợ (bị từ chối rõ ràng) |
|---|---|
| Main (77) và High (100) profile, `entropy_coding_mode_flag = 1` | Baseline/CAVLC (đi đường cũ `CODEC_POLICY_V1/V2`) |
| 8-bit, 4:2:0, khung lũy tiến (`frame_mbs_only_flag = 1`) | Xen kẽ (field, MBAFF), 4:2:2, 4:4:4, bit depth > 8 |
| Lát I/IDR: I_NxN (biến đổi 4×4 **và** 8×8), I_16x16, I_PCM | `qpprime_y_zero_transform_bypass` (lossless) |
| Nhiều lát mỗi khung, ma trận lượng tử tuỳ biến (không cần giải lượng tử) | FMO (slice groups), redundant pictures, SP/SI, data partitioning |
| GOP > 1 với lát P **và B** (giữ nguyên từng byte) | Đoạn (segment) không bắt đầu bằng IDR |

Carrier chỉ nằm trong **lát IDR**; lát P/B/I-không-IDR không bao giờ được giải mã
CABAC, chỉ bị khoá nguyên byte trong digest (cùng ý tưởng `IDR_CARRIERS_INTER_RAW`).

## 2. Kiến trúc

```
src/bitstream/cabac/
  tables.py   bảng chuẩn (Bảng 9-12..9-33, 9-43, 9-44, 9-45), sinh tự động
  engine.py   bộ giải mã số học (9.3.3.2) và bộ mã hoá (9.3.4)
  headers.py  SPS/PPS/slice header (Main/High), emulation prevention
  syntax.py   macroblock_layer() của lát I — MỘT đường duyệt dùng cho cả
              giải mã lẫn mã hoá
  slice.py    giải mã NAL IDR -> cú pháp; mã hoá lại dạng chính tắc
  stream.py   tách/ghép Annex B, tập tham số
src/transport/cabac_sync.py
  hợp đồng carrier, kiểm tra cấu trúc đoạn, digest, transport (chunk cố định
  ZKBC v1 và chunk thích nghi ZKBC v2)
research/cabac/gen_cabac_tables.py
  sinh lại tables.py từ FFmpeg n7.1
```

### 2.1 Bảng chuẩn và nguồn gốc

`tables.py` được **sinh cơ học** bởi `research/cabac/gen_cabac_tables.py` từ mã
nguồn FFmpeg tag `n7.1` (commit `507a51fb…`): `libavcodec/cabac.c`
(`ff_h264_cabac_tables`) và `libavcodec/h264_cabac.c` (`cabac_context_init_I`,
`significant_coeff_flag_offset_8x8`). Đây là dữ liệu chuẩn của ITU-T H.264; không
dùng mã FFmpeg nào. Script kiểm tra cấu trúc (hàng LPS lặp, bước chuyển MPS/LPS)
và `test_cabac_engine.py` ghim digest của toàn bộ giá trị + đối chiếu vài giá trị
nổi tiếng của chuẩn (rangeTabLPS[0] = 128,176,208,240; transIdxLPS[63] = 63;
khởi tạo ctx 60–63, 399–401).

### 2.2 Một đường duyệt cho hai chiều

`syntax.code_macroblock(engine, mb, …)` đi đúng thứ tự `macroblock_layer()`:
`mb_type` → (`transform_size_8x8_flag`) → mode nội 4×4/8×8 →
`intra_chroma_pred_mode` → `coded_block_pattern` → `mb_qp_delta` → residual (DC
16×16, AC/4×4, 8×8, DC sắc độ, AC sắc độ) → `end_of_slice_flag`. Với
`CabacDecoder` nó đọc; với `CabacEncoder` nó ghi. Việc chọn ngữ cảnh
(ctxIdxInc theo hàng xóm trái/trên, `coded_block_flag` suy luận cho khối 8×8,
quy tắc I_PCM/không khả dụng) do **cùng một mã** tính ở cả hai chiều, nên mã hoá
lại một lát vừa giải mã cho đúng mã chính tắc của cú pháp đó.

I_PCM: sau bin terminate = 1, bộ giải mã đứng đúng sau bit cuối của EncodeFlush;
đọc `pcm_alignment_zero_bit`, 384 byte mẫu, rồi khởi tạo lại engine (9.3.1.2).
Đã kiểm chứng: FFmpeg giải ra **đúng từng mẫu** PCM ta ghi.

## 3. Dạng chính tắc (canonical) — vì sao cần

libx264 kết thúc mã số học bằng một mẫu flush riêng (phụ thuộc số khung) thay vì
`EncodeFlush` của 9.3.4. Hai cách đều giải ra **cùng cú pháp**, nhưng khác byte
cuối. Đo trên 5 clip thật: mã hoá lại khớp libx264 ở **mọi byte trừ byte cuối**,
và khớp hoàn toàn ở ~một nửa số lát.

Hệ quả thiết kế:

* **Dạng chính tắc** của một lát = `encode_slice(decode_slice(nal))`: header giữ
  nguyên bit, `cabac_alignment_one_bit`, mã 9.3.4 kết thúc bằng EncodeFlush (bit
  cuối là `rbsp_stop_one_bit`), `rbsp_alignment_zero_bit`, giữ nguyên số
  `cabac_zero_word`, emulation prevention tối thiểu (kể cả `0x03` cuối khi RBSP
  kết thúc bằng `cabac_zero_word`, 7.4.1).
* Bộ nhúng **mã hoá lại mọi lát IDR** của đoạn mang carrier ở dạng chính tắc.
* Bộ kiểm tra **từ chối** đoạn mang carrier nếu có lát IDR không bằng đúng dạng
  chính tắc của cú pháp của nó.
* Digest băm **mã chính tắc của cú pháp đã chuẩn hoá carrier**. Vì stego phải
  chính tắc, cú pháp xác định duy nhất mọi byte của lát ⇒ digest ràng buộc toàn
  bộ byte nhận được (không còn "bit tự do" như vùng sau stop bit).

## 4. Hợp đồng carrier `CabacMagnitudeContract`

* Chỉ lát IDR; các khối residual **không phải DC**: luma 4×4, AC của I_16x16,
  luma 8×8, AC sắc độ (DC luma 16×16 và DC sắc độ bị loại vì ảnh hưởng thị giác lớn).
* Mỗi khối một carrier (`dedup_per_block`): hệ số có chỉ số quét lớn nhất với
  `|level| ≥ 2` (`min_magnitude`, phải chẵn).
* Nhúng = lật LSB của `|level|`, giữ dấu. Vì `|level| ≥ 2` vẫn `≥ 2` sau khi lật
  (2↔3, 4↔5, …) và chọn "chỉ số lớn nhất" không đổi, **tập carrier của stego bằng
  của cover** — bộ kiểm tra tự tính lại được.
* Thứ tự: thứ tự hình học SPS có khoá (`src/core/carrier_order.py`,
  `sps-geometry-low-drift-v1`) — ưu tiên hàng macroblock cuối mỗi lát để giảm trôi
  dự đoán nội; khoá thứ tự = HMAC(sync_key, digest công khai của tập carrier).
* Vị trí: `(slot × MB/khung + mbAddr, block, chỉ số quét)`; block 0–15 luma
  4×4/AC, 16–19 luma 8×8, 20–27 AC sắc độ (Cb 20–23, Cr 24–27). Một slot cho mỗi
  lát mã hoá, giống đường CAVLC.

Dung lượng đo được: ~950 carrier/khung CIF (foreman, QP 22, High). Tắt
`dedup_per_block` cho ~7 300/khung (nhiều hơn 7,7×) khi cần dung lượng lớn.

## 5. Codec policy và phạm vi digest

`video_pipeline.CODEC_POLICY_CABAC_V1`
(`h264-main-high-cabac/canonical-cabac-syntax-carrier-normalized-sha256-v1/full-nal/tagged-raw-segments/segmentation=…`)
ánh xạ tới digest `cabac-canonical-syntax-carrier-normalized-v1`:

* Đoạn phải là **phân hoạch access-unit được ghim** (`SEGMENTATION_RULE_V2`).
* Đoạn mang carrier: băm theo thứ tự dòng, mọi tiền tố start code và mọi NAL;
  lát IDR = mã chính tắc của cú pháp đã xoá LSB tại các carrier **được dùng**;
  mọi NAL khác (SPS, PPS, SEI, P/B, I-không-IDR) băm nguyên byte. Có tag kiểu và
  độ dài.
* Đoạn không mang carrier: băm nguyên byte với domain riêng.
* Digest tổng hợp có domain riêng, ghim quy tắc phân đoạn, kiểu từng đoạn (bản
  thích nghi còn ghim plan id, vai trò, dung lượng, cỡ chunk từng đoạn).

Policy, contract và GOP policy đều vào `carrier_profile_id` ⇒ bằng chứng làm theo
CABAC không bao giờ verify dưới profile CAVLC và ngược lại.

## 6. Dùng thế nào

```python
from src.lattice_zk import video_pipeline as pipeline
from src.transport.cabac_sync import CabacMagnitudeContract
from src.transport.adaptive_chunks import AdaptiveChunkPlan

profile = pipeline.CarrierProfile(
    CabacMagnitudeContract(),
    codec_policy=pipeline.CODEC_POLICY_CABAC_V1,   # chọn transport CABAC tự động
    chunk_plan=AdaptiveChunkPlan(),                # hoặc chunk_bytes=… (ZKBC v1)
    gop_policy="all-intra",                        # hoặc "idr-carriers-inter-raw-v1"
    registered=True,
)
# phần còn lại (registry, pins, embed_video_proof, verify_video_proof) y như CAVLC
```

**Từ dòng lệnh (CLI sản xuất).** Chọn `--codec-policy cabac`; mọi bước khác y hệt
luồng CAVLC. Hợp đồng carrier `CabacMagnitudeContract` được chọn tự động, và
`--gop-policy idr-carriers-inter-raw-v1` dùng cho luồng GOP>1 (carrier ở lát IDR,
lát P/B khoá từng byte). Ví dụ registered một đoạn trên clip 300 khung High:

```bash
export ZKSTEGO_LATTICEZK_SYNC_KEY_HEX=<hex ≥ 16 byte>
OPTS="--codec-policy cabac --frames-per-segment 300 --chunk-bytes 8800"
python -m src.lattice_zk.cli issuer-keygen --public i.pub --private i.key
python -m src.lattice_zk.cli credential-new --payload-file dev.bin --public cred.pub.json --private cred.key.json
python -m src.lattice_zk.cli registry-sign --issuer-private i.key --epoch 1 --credential cred.pub.json --out r.json $OPTS
CH=$(python -m src.lattice_zk.cli session-issue --database s.sqlite --registry r.json \
     --issuer-public i.pub --minimum-epoch 1 --credential cred.pub.json $OPTS | python -c "import sys,json;print(json.load(sys.stdin)['challenge'])")
python -m src.lattice_zk.cli embed --video in.h264 --output stego.h264 --session "$CH" \
     --credential-private cred.key.json --registry r.json --issuer-public i.pub --minimum-epoch 1 $OPTS
python -m src.lattice_zk.cli verify --video stego.h264 --database s.sqlite --registry r.json \
     --issuer-public i.pub --minimum-epoch 1 --credential cred.pub.json $OPTS
```

Đã kiểm end-to-end 26/10 trên `foreman_cif_cabac_high_g1_300f.h264`: envelope
8 741 B, 70 224 carrier, 1 đoạn; verify mù `valid=true`; phát lại phiên đã tiêu
thụ → `valid=false`. (In-band 16 421 B cần nhiều khung hơn hoặc `--adaptive-chunks`.)

Tạo video thử (libx264):

```bash
ffmpeg -i data/raw/foreman_cif_300f.y4m -c:v libx264 -profile:v high -coder 1 \
       -g 1 -bf 0 -qp 22 data/encoded/foreman_cif_cabac_high_g1_300f.h264
```

`src/runtest/cabac_media.py` tự sinh các clip thử nếu thiếu (cần `data/raw/*.y4m`).

Chạy test:

```bash
python -m pytest -q src/runtest/test_cabac_engine.py src/runtest/test_cabac_slices.py \
                    src/runtest/test_cabac_robustness.py src/runtest/test_cabac_pipeline.py
```

## 7. Kết quả kiểm thử

Đo ngày 2026-10-26 (Windows 11, Python thuần, ffmpeg/libx264):

**Engine và cú pháp** (`test_cabac_engine.py`, 32 test): bin ngẫu nhiên 20 000 ×
6 seed đi vòng đúng và kết thúc đúng vị trí stop bit; residual mọi ctxBlockCat
(kể cả thoát UEG0 cho `|level| ≥ 15`, 8×8); ảnh macroblock ngẫu nhiên 99 MB ×
12 seed gồm I_NxN 4×4/8×8, I_16x16, I_PCM, mb_qp_delta, mọi CBP — mã hoá rồi giải
mã ra đúng cú pháp; digest bảng chuẩn được ghim.

**Lát thật** (`test_cabac_slices.py`, 12 test): 126 lát IDR của 5 clip (Main/High,
QP 4/22/26, CRF 18 + AQ, 4 lát/khung) giải mã và mã hoá lại; **mọi byte trừ byte
cuối** trùng libx264 (66/126 trùng hoàn toàn); dạng chính tắc là điểm bất động.
Lật ~10 % carrier (1 223–2 827 lần/clip): ffmpeg `-xerror -err_detect explode`
giải mã **không lỗi**, PSNR-Y trung bình 39–53 dB (khung xấu nhất 35,7–48 dB), tập
carrier tính lại từ stego **bằng** tập của cover. I_PCM tổng hợp: ffmpeg giải ra
đúng từng mẫu. Baseline/CAVLC, 4:4:4, High10, interlaced bị từ chối có thông báo.

**Bền vững trước đầu vào xấu** (`test_cabac_robustness.py`, 24 test, ~17 s):
SPS 513 × 1, 1 × 513, 512 × 512, 65 536², (2^32 − 1)² bị từ chối với thông báo
"pinned limit" (không treo, không ngoại lệ lạ); 512 × 272 (= 139 264 MB) và các
cỡ thường được nhận; các trường định cỡ vòng đọc bị kiểm miền; lát 396 MB với
SPS 22 × 9 dừng đúng; NAL vượt cỡ bị chặn ở `split_annexb`/`decode_slice`;
11 kiểu cắt cụt/rác trên lát IDR và 200 đột biến bit ngẫu nhiên (seed cố
định) chỉ sinh `ValueError` — 110 bị bộ giải mã từ chối, 90 giải mã được rồi
bị từ chối ở bước chính tắc/phong bì, 0 ngoại lệ khác (xem mục 9).

**Pipeline đầu-cuối** (`test_cabac_pipeline.py`, 12 test, `video_pipeline`
thật, registry ký + pins):

| Lượt | Clip | Kết quả |
|---|---|---|
| TOY, registered, ZKBC v1 (chunk 300 B), Main all-intra, 10 khung/đoạn | foreman 30f | HỢP LỆ; 3 896 carrier, 2 đoạn; PSNR-Y 55,5 dB (xấu nhất 48,0); nhúng 15 s |
| TOY, in-band, ZKBC v2 thích nghi, High (8×8) | foreman 30f | HỢP LỆ; 1 chunk 733 B; PSNR-Y 46,3 dB (xấu nhất 43,1) |
| TOY, registered, GOP 8 High **có B-frame**, `idr-carriers-inter-raw-v1` | foreman 48f | HỢP LỆ; 42 lát P/B + SPS/PPS/SEI **nguyên byte**; carrier chỉ trong khung IDR |
| **bdlop-open-128-v3, registered**, thích nghi, 100 khung/đoạn | foreman 300f High | HỢP LỆ; phong bì 8 741 B trong 1 đoạn (70 208 carrier); PSNR-Y 45,8 dB (xấu nhất 39,5); nhúng 142 s, kiểm 88 s |
| **bdlop-open-128-v3, in-band**, thích nghi | foreman 300f High | HỢP LỆ; phong bì 16 421 B trong 2 đoạn (11 871 + 4 550 B, 131 928 carrier); PSNR-Y 47,8 dB (xấu nhất 38,5); nhúng 338 s, kiểm 129 s |

Tấn công đều **bị từ chối**: đổi dấu một hệ số ±1 không phải carrier (stream vẫn
hợp lệ, chính tắc) ở cả TOY lẫn sản xuất; lát IDR không chính tắc (set một
`rbsp_alignment_zero_bit` — đúng kiểu flush libx264); lật một bit trong lát P;
phát lại phiên đã tiêu thụ (`SessionChallengeStore`). Carrier bộ kiểm tra tính
lại = carrier bộ nhúng (vị trí, positions_hash, digest). Profile all-intra từ
chối stream GOP.

## 8. Hiệu năng

Python thuần, không tối ưu: giải mã ~70–85 ms, mã hoá ~90–105 ms mỗi lát IDR CIF
ở QP 18–22 (container 4 lát: ~50 ms/lát); QP 4 (hệ số rất lớn) ~0,85 s / 1,0 s.
Mỗi đoạn mang carrier được phân tích: (bộ nhúng) giải mã + mã hoá + tự kiểm
(giải mã lại, kiểm chính tắc); (bộ kiểm tra) giải mã + kiểm chính tắc + mã hoá
bản chuẩn hoá để băm.

## 9. Giới hạn an toàn (chống DoS) và quy ước lỗi

Bộ giải mã viết bằng Python thuần, nên một dòng bit **bị chế tác** vài byte
không được phép bắt nó chạy hàng triệu macroblock hoặc làm bộ kiểm tra sập vì
một ngoại lệ lạ. Các cận sau được **ghim** trong mã (`src/bitstream/cabac/headers.py`
và `src/transport/cabac_sync.py`); vượt cận → `ValueError`, pipeline trả
`valid=False`:

| Đại lượng | Cận ghim | Nơi kiểm tra |
|---|---|---|
| `pic_width_in_mbs` | ≤ 512 (8192 / 16) | `parse_sps` → `require_picture_geometry` |
| `pic_height_in_map_units` | ≤ 512 | như trên |
| Số macroblock mỗi khung | ≤ 139 264 (MaxFS của Level 6.2, Bảng A-1) | như trên; `_walk` kiểm lại khi giải mã/mã hoá lát |
| Số macroblock giải mã mỗi NAL | ≤ số MB của khung (dừng tại `addr ≥ mbs_per_picture`) | `slice._walk` |
| Kích thước một NAL | ≤ 64 MiB | `split_annexb`, `decode_slice` → `require_nal_size` |
| `log2_max_frame_num_minus4`, `log2_max_pic_order_cnt_lsb_minus4` | ≤ 12 (7.4.2.1.1) | `parse_sps` |
| `num_ref_frames_in_pic_order_cnt_cycle` | ≤ 255 | `parse_sps` |
| Số macroblock mỗi khung (transport) | ≤ 2^24 | `inspect_cabac_segment` |

Cận 2^24 của transport độc lập với cận của parser: vị trí carrier
`slot × MB/khung + mbAddr` được đóng gói int64 (`struct.pack(">qqq")`, cả ở
`core.carrier_order`), nên tích này phải nằm xa dưới 2^63 với mọi đoạn mà khung
Annex B có thể chứa.

**Quy ước lỗi.** Mọi điểm vào của transport mà pipeline gọi
(`inspect_cabac_segment`, `segment_capacity_bits`, `derive_*`, `embed_*`,
`extract_*`, cùng `_analyze`/`_embed_segment`/`_extract_segment` bên trong) được
bọc bởi `_reject_malformed`: `struct.error`, `IndexError`, `KeyError`,
`OverflowError`, `ZeroDivisionError` và `CabacError` phát sinh từ đầu vào xấu
được đổi thành `ValueError("malformed CABAC stream: …")` (giữ nguyên nhân qua
`__cause__`). `UnsupportedStream` (một `ValueError`) và `RuntimeError` của
bước tự kiểm đi qua nguyên vẹn. `video_pipeline.verify_video_proof` bắt
`(ValueError, RuntimeError, OSError, SubprocessError)` và trả `valid=False`;
nội dung video **không bao giờ** làm nó sập.

Kiểm chứng (`test_cabac_robustness.py`): SPS khai báo khung quá cỡ (kể cả
2^32 − 1 × 2^32 − 1, giá trị ue(v) lớn nhất) bị từ chối ở parser lẫn qua
transport; lát 396 MB với SPS 22 × 9 dừng đúng sau 198 MB; lát bị cắt
cụt/toàn 0/toàn 1/ngẫu nhiên và **200 đột biến bit ngẫu nhiên** trên NAL IDR
thật chỉ sinh `ValueError` (hoặc giải mã được rồi bị từ chối ở bước chính
tắc/phong bì), không bao giờ ngoại lệ khác.

## 10. Giới hạn đã biết

* Không xen kẽ, 4:2:2/4:4:4, >8 bit (từ chối rõ ràng).
* Stego luôn khác cover ở byte cuối mọi lát IDR của đoạn mang carrier (do chuẩn
  hoá flush) — vô hại cho giải mã, nhưng là một "dấu vết" cấu trúc mà bộ dò có
  thể học (lát kết thúc kiểu 9.3.4 thay vì kiểu libx264). Bộ mã hoá khác libx264
  có thể đã dùng EncodeFlush chuẩn.
* Thay đổi hệ số IDR làm khung P/B tham chiếu trôi nhẹ (như đường CAVLC GOP > 1).
* Lát P/B không được giải mã nên không thể làm carrier.
* Python thuần, không constant-time (không ảnh hưởng an toàn vì carrier là dữ
  liệu công khai trong video).
