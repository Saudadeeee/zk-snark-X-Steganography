# Carrier và chunking thích ứng của transport lattice-ZK

Tài liệu này gộp hai phần của lớp transport blind: **carrier thích ứng theo chi
phí** (mã hóa STC trên carrier magnitude, roadmap B1) và **chunking thích ứng
theo dung lượng** (ZKBC v2, stream C1). Lớp proof/statement không đổi; phần tổng
quan hệ thống và lý thuyết nằm ở `docs/handoff/` (`03_ly_thuyet.md`,
`02_kien_truc.md`), còn đặc tả statement/digest ở `docs/LATTICE_ZK_BDLOP_SPEC.md`
— đây là tài liệu tham chiếu kỹ thuật sâu hơn, không lặp lại các phần đó.

---

## Phần I — Carrier thích ứng theo chi phí (roadmap B1)

Trạng thái: cài đặt sau một carrier contract mới,
`AdaptiveOperatingContract` (`version = "adaptive-stc-magnitude-video-only-v1"`,
`src/transport/blind_sync.py`), với mã và mô hình chi phí trong
`src/core/adaptive_carriers.py`. Các contract đã có không đổi: serialization
`dataclasses.asdict`, carrier profile id và byte stego ra của chúng giống hệt
commit `18c5123` (ghim bởi test).

### Cái gì đổi và cái gì không

**Tập carrier là như nhau** với contract magnitude ổn định
(`stable-carriers-video-only-v1`): trong mỗi block luma 4x4 patchable, hệ số AC
tái-dẫn-xuất-được đầu tiên với `|level| >= 4` mà không phải trailing one; LSB của
`|level|` của nó là bit carrier. Tập đó, và thứ tự của nó dưới keyed chaos
shuffle, chỉ phụ thuộc `|level| >> 1`, mẫu zero và các kiểm tra patchability
CAVLC, không cái nào bị một thay đổi LSB làm đổi, nên extractor tính lại nó từ
video stego đúng như trước.

Cái đổi là **ánh xạ từ bit envelope sang bit carrier**:

| | trực tiếp (hiện tại) | thích ứng (B1) |
|---|---|---|
| carrier mỗi segment | một mỗi bit envelope (prefix của keyed order) | **mọi** carrier ổn định của segment |
| bit carrier | = bit envelope | tự do; envelope là *syndrome* `H y` |
| thay đổi | khoảng một mỗi hai bit, ở carrier ngẫu nhiên | nghiệm chi phí tối thiểu Viterbi của `H y = m` |
| extractor cần | khóa, contract | khóa, contract (tham số code nằm trong đó) |

Lớp proof/statement không bị chạm. Statement gắn `carrier_count`,
`positions_hash` và video digest đã chuẩn hóa carrier; với contract thích ứng,
các cái này phủ mọi carrier của code, vốn cố định trước khi proof tồn tại (một
placeholder cùng độ dài cố định `m`, tập carrier bất biến cố định `n`). Các
trường thêm của contract đổi carrier profile id, nên một video thích ứng chỉ
verify được dưới một registry entry tạo cho profile thích ứng.

### Mã hóa: syndrome-trellis codes

Mỗi segment 100 khung, envelope (header 14 byte + body) được mã hóa bằng hai STC
độc lập (Filler, Judas, Fridrich, *Minimizing additive distortion in
steganography using syndrome-trellis codes*, IEEE TIFS 2011):

* **header**: `header_carriers_per_bit x 112` carrier đầu theo keyed order mang
  112 bit header (mặc định 1, tức 112 carrier ở rate 1, nên contract không cần
  nhiều carrier hơn nhúng trực tiếp; ~56 thay đổi của header không đáng kể so với
  body);
* **body**: mọi `n_b` carrier còn lại mang `m_b` bit body, rate `m_b / n_b`.
  Extractor giải mã header, học độ dài envelope từ đó, và do đó biết `m_b`; `n_b`
  là số carrier bất biến.

Ma trận parity-check là ma trận STC banded chuẩn dựng từ một submatrix công khai
`h x w` (`h = stc_constraint_height = 10`, các cột dẫn xuất từ SHA-256 của một
chuỗi domain, bit thấp nhất và cao nhất được set để mọi bit message tới được);
độ rộng mỗi bit message là `floor((j+1) n / m) - floor(j n / m)`. Trích là một
lượt XOR duy nhất; nhúng là một tìm kiếm Viterbi trên `2^h` trạng thái (numpy,
khoảng 1 s và 50 MB cho 50 k carrier). Với chi phí đều, nó đạt 0.27 thay đổi
mỗi bit ở rate 0.6 (chặn 0.25, trực tiếp 0.5).

Vì sao điều này tương thích với một blind extractor và các envelope cố định,
trái với kỳ vọng ban đầu trong roadmap: extractor không bao giờ cần chi phí hay
cover; nó chỉ cần `(n, m, h)`, đều tính-lại-được, và keyed carrier order nó vốn
dẫn xuất. Các carrier "ướt" không cần vì mọi carrier ổn định đều sửa được theo
cấu trúc.

### Mô hình chi phí

`texture-magnitude-v1`, mỗi carrier `i` trong macroblock `M`:

```
rho_i = 1 / ( q_i * (1 + T_M / 32) )
q_i   = |level_i| >> 1                         (>= 2)
T_M   = tổng trên 16 block luma của M, các vị trí AC, của (|c| >> 1) + [c != 0]
```

* `q_i`: một thay đổi +-1 của một level lớn thì tương đối nhỏ hơn, dịch
  histogram độ lớn theo-vị-trí ít hơn (số đếm phẳng hơn ở đó; các bin trên 15
  được gộp trong bộ dò) và cho một residual miền-pixel nhỏ hơn so với nội dung;
* `T_M`: các thay đổi giấu tốt hơn trong các macroblock nhiều kết cấu (lập luận
  content-adaptivity thường thấy của HUGO/WOW/UNIWARD), điều mà các đặc trưng
  pixel kiểu SRM thấy.

Mọi đầu vào đều bất biến theo carrier, nên chi phí tính-lại-được từ video stego
(đã test: vector chi phí giống hệt từ cover và stego); STC extractor không dùng
chúng, nhưng điều này giữ cửa mở cho các biến thể wet-paper hoặc ngưỡng mà
extractor phải biết cách chọn.

### Contract

```python
AdaptiveOperatingContract(            # src/transport/blind_sync.py
    version="adaptive-stc-magnitude-video-only-v1",
    stable_carriers_only=True, require_bitstream_patchable=True,
    max_modifications_per_block=1, patchability_headroom=64,
    carrier_coding="stc", stc_constraint_height=10,
    header_carriers_per_bit=1,        # header code rate 1: cùng dung lượng với trực tiếp
    cost_model="uniform",             # hoặc "texture-magnitude-v1"
)
```

`benchmark/latticezk_video_e2e.py --carrier adaptive` (chi phí uniform) và
`--carrier adaptive-texture` (chi phí texture/magnitude) chọn nó. Với
`header_carriers_per_bit=1` contract vừa đúng các segment mà contract magnitude
trực tiếp vừa (segment đầu của coastguard có 31 404 carrier cho 30 696 bit
envelope). Các cài đặt không hỗ trợ (carrier sign-bit, hơn một carrier mỗi
block, cap theo IDR, bộ lọc vùng dưới, coding hoặc cost model lạ, height ngoài
1..12) bị từ chối.

### Kết quả

Thiết lập: envelope BDLOP registered (7 589 B, `bdlop-open-128-v1`; chưa đo lại
dưới v2), `--chunk-bytes 3800`, hai segment 100 khung mỗi clip, các cắt CIF QP 22
all-intra của 200 khung đầu của container, coastguard và deadline (city và hall
không vừa envelope trong 200 khung với cả hai contract). Bộ dò và đặc trưng là
của `latticezk_ml_steganalysis` (kẻ tấn công huấn luyện trên đúng các cặp
cover/stego từ cùng bộ mã hóa và biết khung nào mang bit); 600 cặp khung mỗi chế
độ, leave-one-clip-out (LOCO, 3 fold 200 cặp) và một paired half split.

#### Mô phỏng dùng để chọn mô hình chi phí

`benchmark/latticezk_adaptive_sim.py` (carrier ổn định thật, chỉ miền hệ số,
bitstream không dựng lại; `benchmark/results/q2/adaptive_sim.json`):

| Quy tắc | Thay đổi (container / coastguard / deadline) | LOCO FLD P_E (hệ số) |
|---|---|---|
| trực tiếp (hiện tại) | 30 503 / 30 575 / 30 542 | 0.394 |
| STC, chi phí uniform | 16 123 / 22 633 / 16 709 | **0.444** |
| STC, magnitude `1/q` | 18 194 / 23 310 / 18 530 | 0.426 |
| STC, texture `1/(1+T/32)` | 17 388 / 23 075 / 18 018 | 0.428 |
| STC, texture-magnitude-v1 | 19 005 / 23 787 / 19 322 | 0.423 |
| STC, `1/q^2`, `1/(q^2 (1+T/32))`, `1/k` | 21 344 / ... | 0.430, 0.433, 0.439 |

Mọi chi phí theo nội dung mua "chỗ tốt hơn" của nó bằng 10-35 % thay đổi nhiều
hơn, và trước các bộ dò này số thay đổi chiếm ưu thế. Do đó `uniform` là mặc
định; `texture-magnitude-v1` vẫn có sẵn và được đo thật.

#### E2E thật (`benchmark/results/q2/adaptive_e2e.json`)

Cả chín lượt verify từ video stego một mình (`verify_reason: ok`).

| Clip | Chế độ | Carrier | Hệ số đổi | Thay đổi / bit | PSNR (dB) | Khung tệ nhất (dB) | Embed / verify (s) |
|---|---|---|---|---|---|---|---|
| container | trực tiếp | 61 304 | 30 491 | 0.502 | 44.03 | 34.35 | 179 / 80 |
| container | STC uniform | 101 439 | **16 167** | 0.266 | **45.83** | 36.51 | 179 / 83 |
| container | STC texture | 101 439 | 19 125 | 0.315 | 45.85 | 35.65 | 187 / 80 |
| coastguard | trực tiếp | 61 304 | 30 673 | 0.505 | 41.85 | 32.65 | 227 / 104 |
| coastguard | STC uniform | 71 303 | **22 618** | 0.373 | **43.22** | 33.93 | 226 / 104 |
| coastguard | STC texture | 71 303 | 23 777 | 0.392 | 42.92 | 33.32 | 232 / 104 |
| deadline | trực tiếp | 61 304 | 30 531 | 0.503 | 39.43 | 28.74 | 184 / 84 |
| deadline | STC uniform | 95 332 | **16 750** | 0.276 | **41.82** | 32.48 | 231 / 101 |
| deadline | STC texture | 95 332 | 19 304 | 0.318 | 40.34 | 29.41 | 204 / 83 |

PSNR là trung bình giải mã toàn video (mọi 200 khung đều bị sửa trong mỗi lượt).
Steganalysis học máy, P_E (cao hơn là tốt hơn cho người nhúng); dòng "tệ nhất"
là nhỏ nhất trên sáu tổ hợp bộ dò/đặc trưng:

| Giao thức | Bộ dò / đặc trưng | trực tiếp | STC uniform | STC texture |
|---|---|---|---|---|
| LOCO | FLD, hệ số (340) | 0.406 | **0.431** | 0.404 |
| LOCO | FLD, pixel SRM-lite (500) | 0.412 | **0.450** | 0.443 |
| LOCO | FLD, kết hợp | 0.407 | **0.438** | 0.428 |
| LOCO | tệ nhất | 0.406 | **0.431** | 0.404 |
| paired split | FLD, hệ số | 0.352 | **0.392** | 0.393 |
| paired split | FLD, kết hợp | 0.323 | **0.388** | 0.353 |
| paired split | tệ nhất | 0.323 | **0.388** | 0.353 |

LOCO theo fold (coastguard / container / deadline), FLD trên đặc trưng hệ số:
trực tiếp 0.380 / 0.435 / 0.403, STC uniform 0.405 / 0.445 / 0.443; trên đặc
trưng kết hợp 0.433 / 0.415 / 0.373 so với 0.460 / 0.435 / 0.420. STC chi phí
uniform dẫn trước ở mọi fold và bộ đặc trưng.

CNN (`latticezk_cnn_steganalysis`, set `b1_magnitude` / `b1_adaptive`, GPU, cùng
600 cặp khung; `benchmark/results/q2/adaptive_cnn_*.json`):

| Giao thức | trực tiếp frame P_E (AUC) | STC uniform frame P_E (AUC) |
|---|---|---|
| LOCO | 0.457 (0.536) | 0.471 (0.511) |
| paired split | 0.463 (0.530) | 0.463 (0.533) |

CNN gần ngẫu nhiên ở cả hai, như nó đã vậy trên carrier magnitude
(`docs/CNN_STEGANALYSIS.md`), nên nó không cho khác biệt đo được nào; các bộ dò
dựa trên đặc trưng vẫn là cái ràng buộc.

#### Đọc các con số

* Lợi ích là thật nhưng vừa phải: P_E LOCO tệ nhất 0.406 -> 0.431 và P_E paired
  0.323 -> 0.388 ở cùng payload, với 26-47 % thay đổi ít hơn và +1.4 đến +2.4 dB
  PSNR. Với 200 cặp test mỗi fold, sai số chuẩn của P_E một fold khoảng 0.03, nên
  từng fold riêng không có ý nghĩa; tính nhất quán qua mọi fold và bộ đặc trưng
  là bằng chứng.
* Lợi ích scale theo carrier dư: coastguard (rate 0.86 bit mỗi carrier) tiết
  kiệm 26 % thay đổi, container và deadline (rate 0.6-0.65) 45-47 %. Nhiều khung
  hơn mỗi envelope (mật độ thấp hơn) sẽ giúp STC nhiều hơn nhúng trực tiếp, vì
  STC dùng mọi carrier thay vì một prefix.
* Chi phí texture/magnitude không giúp: nó dời thay đổi tới các level lớn trong
  các macroblock nhiều kết cấu nhưng cần 5-18 % nhiều hơn, và các bộ dò này chủ
  yếu nhạy với số đếm. Một mô hình chi phí có ích sẽ phải học đối với bộ dò, hoặc
  dùng thông tin phía cover (dưới đây).

### Giới hạn

* Kênh chọn lựa: mô hình chi phí chỉ dùng dữ liệu bất biến theo carrier, nên kẻ
  tấn công cũng tính lại nó từ video stego (steganalysis có nhận thức kênh chọn
  lựa). Điều này vô nghĩa với mô hình `uniform` đã ship, và keyed carrier order
  vẫn giấu một carrier thuộc cột syndrome nào. Vì trích STC không bao giờ cần
  chi phí, một mô hình tương lai có thể dùng dữ liệu chỉ-cover (ví dụ kết cấu
  pixel đã giải mã trước khi nhúng) mà kẻ tấn công chỉ ước lượng được.
* Cùng carrier: thay đổi vẫn là LSB replacement của `|level|`; matching +-1 sẽ
  đổi `|level| >> 1` và phá tái-dẫn-xuất carrier. STC hạ số thay đổi, không phải
  tính bất đối xứng của mỗi thay đổi.
* Mong manh: mọi carrier của segment nay vào code, nên một carrier hỏng ở bất kỳ
  đâu trong một segment có thể phá envelope của segment đó (trước đây, chỉ prefix
  quan trọng). Các kiểm tra toàn vẹn của proof không đổi; đây là về độ bền, điều
  lược đồ không bao giờ tuyên bố.
* Chi phí: khoảng 50 MB và 1 s mỗi segment 50 k-carrier cho Viterbi (`h = 10`);
  thời gian embed và verify end-to-end trong 5 % của nhúng trực tiếp trừ deadline
  (+25 % embed, +20 % verify; mỗi cái một lượt).
* Cỡ bằng chứng: 3 clip x 200 khung, một khóa mỗi lượt, chỉ CIF QP 22. Hành vi
  4CIF và clip dài chưa đo.

### Test

`src/runtest/test_adaptive_carriers.py` (53 test): round trip STC qua các height
1-10 và rate 1 đến 0.3, tối ưu brute-force trên một instance nhỏ, bám chi phí,
tham số xác định công khai, đầu vào sai; bất biến chi phí dưới mọi toggle carrier
tùy ý (toy và video thật); validation contract và từ chối cài đặt không hỗ trợ;
profile id của các contract trực tiếp ghim theo giá trị 18c5123 của chúng; trích
envelope đã mã hóa, payload rỗng, phát hiện tamper header/body, fail-closed khi
thiếu carrier và không đủ dung lượng; round trip thích ứng video thật (vị trí và
chi phí tính lại từ stego bằng của người nhúng), context segment hóa == trích,
và stego giống hệt từng byte cho các contract magnitude và T1 trực tiếp so với
các digest ghi với 18c5123.

### Tái lập

```bash
# cắt 200 khung (all-intra, nên cắt nào cũng chính xác); tương tự cho coastguard, deadline
ffmpeg -i data/encoded/container_cif_q22_g1.h264 -frames:v 200 -c copy tmp/b1/cuts/container_200.h264
export ZKSTEGO_ANALYSIS_WORKERS=2
python -m benchmark.latticezk_adaptive_sim --videos tmp/b1/cuts/{container,coastguard,deadline}_200.h264 \
    --work tmp/b1/sim --output benchmark/results/q2/adaptive_sim.json          # ~25 phút
python -m benchmark.latticezk_adaptive_e2e --covers tmp/b1/cuts/{container,coastguard,deadline}_200.h264 \
    --work tmp/b1/work --output benchmark/results/q2/adaptive_e2e.json          # ~75 phút, tuần tự
python -m benchmark.latticezk_cnn_steganalysis --encoded-dir tmp/b1/cuts --stego-dir tmp/b1/work \
    --reports-dir tmp/b1/work --cache-dir tmp/b1/cnn_cache train --set b1_adaptive --protocol loco \
    --output benchmark/results/q2/adaptive_cnn_adaptive_loco.json             # ~5 phút trên RTX 3060
```

Một tiến trình E2E CIF được quan sát ở khoảng 0.65 GB resident.

---

## Phần II — Chunking thích ứng theo dung lượng (stream C1, ZKBC v2)

Trạng thái: contract transport opt-in. `CarrierProfile(..., chunk_plan=AdaptiveChunkPlan(...))`
trong `src/lattice_zk/video_pipeline.py` chuyển một profile sang nó. Các profile
không có plan dùng transport ZKBC v1 cố định cũ. Profile id, policy hash, public
sync key, chunk byte v1 và segmented digest v1 của chúng giống như ở commit
`10bce11`: bảng baseline 98 mục được ghim bởi
`test_existing_profiles_and_v1_framing_are_byte_identical` trong
`src/runtest/test_adaptive_chunking.py`.

| file | vai trò |
|---|---|
| `src/transport/adaptive_chunks.py` | plan (`AdaptiveChunkPlan`, `plan_layout`), framing ZKBC v2, canonical check |
| `src/transport/blind_sync_adaptive.py` | transport: dung lượng theo segment, context, embed, blind extract |
| `src/lattice_zk/video_pipeline.py` | `CarrierProfile.chunk_plan`, profile id, verifier canonical check |
| `benchmark/latticezk_video_e2e.py --adaptive-chunks` | lượt chạy end-to-end thật |
| `benchmark/latticezk_adaptive_chunk_plan.py` | dry run lập kế hoạch dung lượng trên các scan |

### Vấn đề

Transport cố định tách envelope (8 165 B registered hoặc 14 885 B in-band với
`bdlop-open-128-v2`) thành các chunk một kích thước đã ghim duy nhất,
`profile.chunk_bytes`. Chunk *i* vào segment 100-khung *i*, nên segment nhỏ nhất
phải mang một chunk sẽ cap kích thước mọi chunk. Một segment dung lượng thấp
không thể bỏ qua. Verifier re-chunk envelope dưới kích thước đã ghim và đòi byte
bằng nhau (fix D1), nên người nhúng cũng không có chỗ để thích ứng.

### Định dạng

Mỗi carrier segment vẫn giữ một envelope blind-channel thường (ZKVP, 14 B:
magic, version, kind, length, CRC-32). Payload của nó là một chunk ZKBC v2:

```text
offset size field          value (mọi thứ cố định bởi plan)
0      4    magic          "ZKBC"
4      1    version        2
5      2    chunk_index    0, 1, 2, ... (không khoảng trống)
7      2    segment_index  segment transport mang chunk này
9      4    total_size     độ dài payload (envelope)
13     4    offset         byte offset của chunk này trong payload
17     4    total_crc      CRC-32 của toàn payload
21     -    part           payload[offset : offset + size]
```

Framing tốn 35 B mỗi carrier segment, so với 37 B cho v1 (14 + 23). Header không
có trường đếm chunk và không có trường kích thước chunk. Độ dài part đến từ độ
dài ZKVP và phải bằng kích thước đã lập kế hoạch. Số đếm là số chunk mà plan sinh
ra. Một reader v1 từ chối chunk v2 (byte version), và chiều ngược lại cũng vậy.

### Plan

`AdaptiveChunkPlan` (frozen, mọi trường là số nguyên, tất cả trong profile id):

| trường | mặc định | ý nghĩa |
|---|---|---|
| `version` | `zkbc-v2-greedy-fill-v1` | id thuật toán |
| `min_chunk_bytes` | 256 | segment có chunk dùng được nhỏ hơn thì bị bỏ qua |
| `reserve_bits` | 0 | carrier để không dùng mỗi segment |
| `fill_permille` | 1000 | phần carrier của mỗi segment được phép dùng (mật độ) |
| `max_chunk_bytes` | 65 535 | cap mỗi segment |

Với một segment có `C` bit dung lượng:

```text
usable_bits  = C * fill_permille // 1000 - reserve_bits
usable_bytes = usable_bits // 8 - 35            (ZKVP + ZKBC v2 framing)
chunk_cap    = 0 if usable_bytes < min_chunk_bytes else min(usable_bytes, max_chunk_bytes)
```

`plan_layout(P, capacities, plan)` duyệt các segment theo thứ tự. Một segment với
`chunk_cap = 0` bị bỏ qua. Ngược lại nó lấy `min(remaining, chunk_cap)` byte.
Việc duyệt dừng khi payload được đặt xong, và ném nếu video hết segment trước.
Lấp greedy là tối ưu cho span: mọi plan khả thi đã đặt nhiều nhất bằng greedy ở
mỗi chỉ số segment, nên greedy kết thúc ở segment sớm nhất có thể. Điều đó giữ số
segment verifier phải phân tích thấp nhất có thể.

**Dung lượng** (`blind_sync_adaptive.segment_capacity_bits`) là số carrier ổn
định, đã kiểm patchability của operating contract,
`len(derive_blind_positions_operating_contract(segment, key, ∞, contract))`.
Dưới các contract trực tiếp (magnitude LSB, T1 sign) một carrier giữ một bit
envelope. Dưới các contract STC (`AdaptiveOperatingContract`) dung lượng là
`available − 112·header_carriers_per_bit + 112`, đúng là điều kiện của
`coded_carrier_layout`. Số đếm không phụ thuộc sync key, vì khóa chỉ hoán vị tập.
Mặc định `header_carriers_per_bit = 1` cho cùng dung lượng với contract trực
tiếp.

### Gắn (binding)

* **Profile id**: khi có một plan, mô tả carrier-profile bỏ `chunk_bytes` và thêm
  `chunk_plan` (descriptor của plan). Do đó mọi tham số plan đổi `profile_id`,
  policy hash, relation id, pins và session binding. `chunk_bytes` phải giữ ở mặc
  định khi có plan, nên hai id không thể mô tả cùng transport.
* **Video digest**: với các profile thích ứng, `D` dùng domain riêng:
  ```text
  D = SHA-256("zkstego/canonical-h264-segmented-adaptive/v1\0" ‖ plan_id ‖
              u32 F ‖ u32 P ‖ u32 L ‖
              (u32 i ‖ u32 frames_i ‖ u8 role_i ‖ u64 capacity_i ‖ u32 chunk_i ‖ d_i)_{i<L})
  ```
  Các vai trò là `0` không dùng (sau payload), `1` bị bỏ qua (đã phân tích, dưới
  ngưỡng) và `2` carrier. Như trước, `d_i` là digest đã chuẩn hóa carrier cho các
  carrier segment và SHA-256 file cho mọi segment khác, nên các segment bị bỏ qua
  được gắn từng byte. Statement phủ `D`, nên nó phủ cả dung lượng, vai trò và
  kích thước chunk. `plan_id = SHA-256("zkstego/adaptive-chunk-plan/v1\0" ‖ JSON(plan))`.

### Vì sao nó là blind

Extractor tính lại dung lượng của mỗi segment từ video stego. Dung lượng của một
carrier segment không đổi khi nhúng:

* một carrier magnitude là LSB của một hệ số AC `|level| ≥ 4` không-trailing-one,
  và lật nó giữ `|level| ≥ 4`, mẫu zero, các trailing one và tổng hệ số, do đó nC
  và mọi độ dài CAVLC (`src/core/stego.py`, kiểm tra bất biến độ dài bit);
* việc chọn carrier trong một block được làm đối xứng dưới phép lật bởi
  `select_rederivable_stable_candidate`: một ứng viên sớm hơn bị từ chối nếu nó
  an toàn trước hoặc sau phép lật được chọn, và phép lật là nghịch đảo của chính
  nó;
* các lật dấu trailing-one giữ cấu trúc trailing-one, và STC ghi lại cùng tập
  carrier;
* các segment bị bỏ qua và không dùng là bản sao giống hệt từng byte.

Vậy tập ổn định của mỗi segment, và cùng với nó là số đếm của nó, như nhau trong
cover và stego. Trích blind đã có vốn dựa vào điều này, vì keyed order là một
shuffle của cả tập. Với cùng dung lượng, cùng plan đã ghim và kích thước envelope
đã ghim (`envelope_size(params)`), verifier dẫn ra cùng layout. Đã kiểm thực
nghiệm: trong test fixture 30-khung (magnitude và STC) và trong E2E dưới đây, các
dung lượng, layout, `positions_hash` và `D` tính lại từ video stego bằng những
cái dẫn từ cover. Nếu bất biến này từng thất bại, verification sẽ fail closed (từ
chối sai), không bao giờ chấp nhận.

### Vì sao nó là canonical (D1 vẫn cố định)

Mọi trường header và mọi độ dài chunk là một hàm của plan, các dung lượng và
payload. Transport kiểm mỗi chunk theo plan tăng dần trong khi trích, và tính lại
toàn bộ layout ở cuối. Pipeline rồi tự tính lại
`pack_adaptive_chunks(payload, plan_layout(len(payload), capacities, plan))` và
đòi byte bằng nhau với các chunk đã trích. Các dung lượng phải kết thúc ở segment
hoàn tất payload, và một layout được báo phải bằng cái tính lại. Test từ chối mỗi
cái sau:

| tấn công | test |
|---|---|
| bất kỳ trường header +1 (chunk/segment index, total, offset, CRC) | `test_any_rewritten_header_field_is_rejected`, `test_pipeline_rejects_rewritten_chunk_headers` |
| re-chunk tự nhất quán của cùng envelope | `test_rechunked_reordered_truncated_or_extended_sets_are_rejected`, `test_pipeline_rejects_rechunked_truncated_or_extended_envelopes` |
| chunk bị sắp lại, bỏ, trùng, cắt, kéo dài | như trên |
| sai khớp plan embedder/verifier | `test_embedder_verifier_plan_mismatch_is_rejected`, `test_extractor_rejects_chunks_that_deviate_from_the_plan` |
| dung lượng transport không khớp video, hoặc thừa | `test_capacity_reports_that_disagree_with_the_video_are_rejected` |
| chunk khai một segment khác, chunk ngắn, kích thước payload khác | `test_extractor_rejects_chunks_that_deviate_from_the_plan` |

### Codec policy v2, STC và GOP > 1

* **Codec policy v2** (D5, `CarrierProfile.codec_policy`) ghép với một plan. Mô
  tả profile mang cả `"codec_policy"` và `"chunk_plan"`. Transport nhận
  `digest_policy`, thực thi phân hoạch access-unit đã ghim, áp các digest v2 đã
  chuẩn hóa carrier và raw-segment, và chuyển digest gộp sang domain
  `zkstego/canonical-h264-segmented-adaptive/v2`, cái cũng gắn
  `SEGMENTATION_RULE_V2` (`test_plan_and_codec_policy_v2_are_bound_together`).
  E2E CIF dưới đây chạy dưới v1.
* **STC**: `segment_capacity_bits` tính cho header code, và các đường embed và
  extract theo segment là của `blind_sync`, không đổi. Test fixture chạy trên cả
  carrier magnitude và STC.
* **GOP > 1**: `gop_policy` của profile được truyền qua. Mọi segment được kiểm
  (`_inspect_segments`), và vị trí được toàn cục hóa theo các slice đã mã hóa,
  như trong transport cố định (`test_gop_segments_offset_positions_by_coded_slices`).

### Kết quả

#### E2E thật (CIF, envelope registered `bdlop-open-128-v2`)

Báo cáo: `benchmark/results/q2/adaptive_chunk_e2e_uneven_cif_q22_reg.json`.

Cắt là 300 khung CIF, QP 22, all-intra Baseline, dựng sao cho dung lượng không
đều giữa các segment: 100 khung mỗi cái của coastguard, akiyo và container.

```text
ffmpeg -i coastguard_cif.y4m -i akiyo_cif.y4m -i container_cif.y4m -filter_complex \
  "[0:v]trim=end_frame=100,setpts=PTS-STARTPTS[a];[1:v]trim=end_frame=100,setpts=PTS-STARTPTS[b];\
   [2:v]trim=end_frame=100,setpts=PTS-STARTPTS[c];[a][b][c]concat=n=3:v=1[v]" -map "[v]" \
  -c:v libx264 -profile:v baseline -g 1 -bf 0 -qp 22 -f h264 tmp/uneven_cif_q22_g1_300f.h264
python -m benchmark.latticezk_video_e2e --video tmp/uneven_cif_q22_g1_300f.h264 \
  --output tmp/adaptive_e2e/uneven_stego.h264 \
  --report benchmark/results/q2/adaptive_chunk_e2e_uneven_cif_q22_reg.json \
  --registered --carrier magnitude --adaptive-chunks --min-chunk-bytes 2048
```

| mục | giá trị |
|---|---|
| envelope | 8 165 B registered, `bdlop-open-128-v2` |
| dung lượng segment (cover = tính lại từ stego) | 31 404 / 10 501 / 50 757 bit |
| layout | segment 0: 3 890 B (lấp trong 4 bit), segment 1: **bỏ qua** (1 277 B dùng được < 2 048), segment 2: 4 275 B |
| ZKBC v1 cố định, kích thước chunk nào | không vừa (segment 1 cap một chunk ở 1 275 B, nên cần 7 segment) |
| slice IDR đổi | 200 trên 300; 100 slice của segment 1 giống hệt từng byte |
| verification blind chỉ từ video | **valid** (`ok`), 217 s; embed 500 s |
| replay phiên đã tiêu thụ | từ chối |
| tamper một-bit (giữa file) | từ chối |
| tamper một-bit trong segment bị bỏ qua | từ chối |
| verification dưới plan khác (`min_chunk_bytes` 1 024, registry riêng) | từ chối (segment 1 khi đó phải mang một chunk: "blind payload magic mismatch") |
| chất lượng giải mã | PSNR 44.08 dB, SSIM 0.9996 |
| RSS đỉnh | 1.33 GB (`ZKSTEGO_ANALYSIS_WORKERS=2`) |

Cả hai bit tamper rơi vào dữ liệu residual CAVLC, nên parser nghiêm từ chối
chúng ("untrusted CAVLC parse offsets"). Một thay đổi vào một segment bị bỏ qua
mà vẫn parse được thì bị bắt bởi `d_i` mức-byte của nó
(`test_non_carrier_change_or_other_session_is_rejected` trên kênh stand-in).
Plan mặc định (`min_chunk_bytes` 256) sẽ dùng cả ba segment ở đây
(3 890 + 1 277 + 2 998 B). Ngưỡng 2 048 B được chọn để kích hoạt việc bỏ qua.

#### Dry run lập kế hoạch dung lượng trên các scan 4CIF

`python -m benchmark.latticezk_adaptive_chunk_plan --output benchmark/results/q2/adaptive_chunk_plan_4cif.json`
(plan mặc định, `fill_permille = density`). "sweep" là quy tắc chunk cố định của
sweep, cỡ chunk ở 97 % segment đã scan nhỏ nhất. "best uniform" là một tìm kiếm
vét cạn trên mọi kích thước chunk cố định.

| case | đã scan | sweep | best uniform | thích ứng, v2 (8 165 B) | thích ứng, v1 (7 589 B) |
|---|---|---|---|---|---|
| crew4cif_q22_reg | 6/6 | no | no | **không vừa**: 7 757 B dùng được trong 600 khung, thiếu 408 B | vừa, segment 0–5 |
| soccer4cif_q22_reg | 3/6 | no | yes | **vừa, segment 0–1** (4 784 + 3 381 B) | vừa, segment 0–1 |
| crew4cif_q22_reg_d50 | 6/6 | no | no | không vừa (nửa của 7 757 B) | không vừa |
| crew4cif_q22_reg_d25 | 6/6 | no | no | không vừa | không vừa |
| soccer4cif_q22_reg_d50 | 3/6 | no | no | chưa xác định: cần thêm 2 828 B từ 3 segment chưa scan | chưa xác định (2 252 B) |
| soccer4cif_q22_reg_d25 | 3/6 | no | no | chưa xác định: cần thêm 5 532 B | chưa xác định (4 956 B) |
| crew4cif_q18_reg (tham chiếu) | 6/6 | yes | yes | vừa, segment 0–1 | vừa |
| city4cif_q22_reg (tham chiếu) | 3/6 | yes | yes | vừa, segment 0 | vừa |
| harbour4cif_q22_reg (tham chiếu) | 3/6 | yes | yes | vừa, segment 0–1 | vừa |

Đọc:

* **soccer Q22** nay vừa trong 200 khung. Quy tắc uniform thất bại chỉ vì segment
  2 đã scan giữ 3 501 bit. Một chunk cố định chính xác (4 782 B) cũng sẽ vừa,
  nhưng plan thích ứng không cần lựa chọn kích thước phụ thuộc scan.
* **crew Q22**: tuyên bố "tổng dung lượng đủ" không đúng cho envelope sản xuất.
  Sáu segment cộng lại 63 756 bit = 7 969 B, dưới envelope 8 165 B ngay cả trước
  framing. Không cách chunking nào vừa nó vào 600 khung này; cái này cần nhiều
  carrier hơn (một carrier khác, QP thấp hơn, hoặc một clip dài hơn). Với
  envelope v1 7 589 B, cái mà scan dung lượng gốc được cỡ cho, plan thích ứng vừa
  dùng cả sáu segment, và không kích thước chunk cố định nào vừa.
* **crew d50/d25** dùng nửa hoặc một phần tư của một dung lượng vốn đã không đủ,
  nên bất khả. **soccer d50/d25** phụ thuộc ba segment chưa bao giờ được scan.
  Scan chúng không được làm ở đây, vì đó là một workload 4CIF trên máy chung.

### Giới hạn

* Bất biến dung lượng là một tính chất của các quy tắc carrier ổn định, không của
  plan. Một contract không có carrier bất biến không dùng được transport này (nó
  đòi `stable_carriers_only` và kiểm patchability).
* Verifier phân tích mọi segment tới carrier cuối, kể cả các segment bị bỏ qua,
  nên bỏ qua tiết kiệm các thay đổi nhúng nhưng không tiết kiệm thời gian
  verifier.
* Plan greedy dồn các thay đổi vào các segment đầu, đến mật độ đầy ở đó.
  `fill_permille`, `reserve_bits` và `max_chunk_bytes` trải chúng ra, đổi lại
  nhiều segment hơn.
* Plan cố định mỗi profile. Đổi ngưỡng hoặc mật độ nghĩa là một relation mới
  trong registry.
* Các giới hạn là 65 535 segment, 65 535 chunk và payload tới 16 MiB. Kích thước
  chunk bị chặn bởi `max_chunk_bytes` (≤ 16 MiB).
