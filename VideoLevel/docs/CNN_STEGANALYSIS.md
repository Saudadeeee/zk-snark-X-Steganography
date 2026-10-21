# Steganalysis CNN cho video stego lattice-ZK (roadmap A6)

Nghiên cứu này thêm một bộ dò học sâu, một CNN miền không gian huấn luyện trên
GPU, bên cạnh các FLD ensemble dựa trên đặc trưng trong
`benchmark/latticezk_ml_steganalysis.py` (kết quả trong
`benchmark/results/q2/ml_eval.json` và `carrier_compare.md`).
Mã: `benchmark/latticezk_cnn_steganalysis.py`. Test:
`src/runtest/test_latticezk_cnn_steganalysis.py`. Kết quả thô:
`benchmark/results/q2/cnn_*.json`.

## Tóm tắt

| Carrier (cùng payload) | Giao thức | CNN P_E (crop-mean) | CNN AUC | CNN P_E (full-frame) | FLD P_E tốt nhất, cùng giao thức |
|---|---|---|---|---|---|
| magnitude LSB, 5 clip | leave-one-clip-out | **0.466** | 0.529 | 0.466 | 0.399 (hệ số), 0.458 (pixel) |
| magnitude LSB, 5 clip | paired half split | **0.474 / 0.464** | 0.528 / 0.549 | 0.477 / 0.468 | 0.357 (kết hợp), 0.410 (pixel) |
| T1 sign, spread, 4 clip | leave-one-clip-out | **0.273 / 0.278** | 0.766 / 0.754 | 0.194 / 0.212 | 0.401 (kết hợp), 0.404 (pixel) |
| T1 sign, spread, 4 clip | paired half split | **0.168 / 0.142** | 0.906 / 0.932 | 0.116 / 0.105 | 0.317 (kết hợp), 0.344 (pixel) |

`a / b` = seed 20261021 / seed 20261022 (khởi tạo và chia tách độc lập).
P_E = min trên các ngưỡng của (P_FA + P_MD) / 2; 0.5 là ngẫu nhiên.

* **Carrier magnitude (mặc định):** CNN giữ ở mức ngẫu nhiên (P_E 0.46–0.47,
  AUC 0.53–0.55). Nó kém hơn FLD miền hệ số (0.399 LOCO), vốn vẫn là bộ dò mạnh
  nhất ta có cho carrier này. Không bộ dò nào xuống dưới P_E 0.35 trên từng khung.
* **Carrier T1-sign, cùng payload và khung:** CNN tìm ra nó. P_E theo khung là
  0.27 leave-one-clip-out (0.19–0.21 với logit full-frame) và 0.14–0.17 trên
  paired split. Theo từng clip, container (0.09) và coastguard (0.19) bị phát
  hiện rõ, trong khi city và hall giữ gần 0.40. Điều này mạnh hơn hẳn các FLD
  ensemble (0.40 LOCO). CNN cho thấy steganalysis miền pixel có thể thấy carrier
  T1-sign, điều mà các đặc trưng làm tay bỏ lỡ.
* **Biên (margin):** nhân đôi thay đổi của carrier magnitude (`--amplify 2`, một
  proxy tổng hợp) đã cho P_E 0.18 khi CNN được huấn luyện trên đó. Do đó carrier
  mặc định không cách xa ngưỡng phát hiện của CNN.

## Dữ liệu

| Set | Case (`tmp/q2/<case>.h264`) | Cover (`data/encoded`) | Cặp khung bị sửa |
|---|---|---|---|
| magnitude | container/coastguard/city/hall `_cif_q22_reg`, `deadline_cif_q22_reg` | `*_cif_q22_g1.h264`, `deadline_cif_q22_g1_1000f.h264` | 200 + 200 + 300 + 300 + 700 = 1700 |
| t1_spread | container/coastguard/city/hall `_cif_q22_reg_t1_spread` | cùng cover | 200 + 200 + 300 + 300 = 1000 |

* Mỗi case mang cùng envelope 7589 byte (`bdlop-open-128-v1`) trong cùng các
  segment (2 hoặc 3 segment 100 khung). Do đó set magnitude và T1-spread có cùng
  payload và cùng mật độ, chỉ khác ở carrier. Mọi luồng là CIF 352x288,
  all-intra (GOP 1), QP 22.
* Cover và stego được giải mã bằng `decode_luma_native`, cho mặt phẳng Y chính
  xác qua raw yuv420p. Một khung được giữ khi luma stego khác luma cover của nó ở
  ít nhất một pixel. Số đếm khớp với `frame_quality.frames_modified` cho mọi case
  trừ deadline: 700 khung khác về pixel, trong khi báo cáo đếm 684. Các cặp được
  cache dưới dạng uint8 trong `tmp/cnn_cache/cnn_pairs_<case>.npz`
  (gitignored; khoảng 545 MB trên đĩa, khoảng 340 MB trong RAM cho set magnitude).
* Thay đổi pixel trải ra nhưng nhỏ. Với set magnitude, 48–79 % pixel thay đổi
  (dự đoán intra mang mỗi thay đổi hệ số vào các block sau), mean |Δ| ≈ 2, MSE
  1.8–6.8. Với T1-spread, 12–17 % pixel thay đổi, MSE 0.9–2.5.
* Các con số FLD tham chiếu (`ml_eval.json`, `carrier_compare.md`, tính lại cho
  nghiên cứu này bằng `latticezk_ml_steganalysis evaluate` và tái lập đúng) dùng
  1300 cặp magnitude, vì các đặc trưng deadline chỉ phủ 3 segment. CNN dùng cả
  700 khung deadline.

## Phương pháp

**Mạng.** Một bộ dò kiểu Yedroudj-Net (163 k tham số huấn luyện được):

1. Một front end cố định gồm 30 bộ lọc thông cao SRM (bậc 1, 2 và 3,
   SQUARE 3x3/5x5, EDGE 3x3/5x5). Chúng được áp ở fp32 trên (pixel − 128) với
   các tap nguyên rồi chia cho normaliser của chúng, nên các residual chính xác
   và không bị ảnh hưởng bởi TF32 hay fp16. Đầu ra được cắt bằng TLU(3).
2. conv5x5(30), rồi ABS, BN, TLU(3); conv5x5(30), rồi BN, TLU(2), avgpool/2.
3. Hai tầng conv3x3 (32, 64), mỗi tầng theo sau là BN, ReLU và avgpool/2.
   Rồi conv3x3(128), BN, ReLU và global average pooling.
4. FC 128→128, ReLU, dropout 0.3, FC→1 logit, huấn luyện với BCE.

**Huấn luyện** (cố định cho mọi lượt; mặc định CLI):

| Cài đặt | Giá trị |
|---|---|
| Crop | ngẫu nhiên 256x256, offset trên lưới biến đổi H.264 4-pixel |
| Augmentation | một biến đổi D4 ngẫu nhiên (flip/rot90) mỗi cặp |
| Mini-batch | 16 cặp cover/stego (32 ảnh); mỗi cover và stego của nó chia sẻ crop và biến đổi |
| Optimiser | AdamW, lr 2e-4, weight decay 1e-4, cosine schedule, fp16 autocast sau lớp SRM |
| Epoch | tối đa 40, một crop mỗi cặp huấn luyện mỗi epoch |
| Payload curriculum | epoch 0–14 huấn luyện trên round(cover + α·(stego − cover)), α đi tuyến tính từ 6 về 1; từ epoch 15, α = 1 (stego thật) |
| Early stopping | P_E validation thấp nhất (phá hòa bằng loss validation), patience 10, chỉ các epoch α = 1 được chọn |
| Validation | lấy từ chính các clip huấn luyện: 20 % khung cuối của mỗi clip huấn luyện (LOCO), hoặc 20 % cặp huấn luyện ngẫu nhiên (paired split) |

Curriculum là cần thiết. Huấn luyện từ đầu ở α = 1, loss giữ ở ln 2 suốt 15+
epoch trên mọi set. Với α = 8 mạng học thay đổi ngay (test P_E 0.00–0.07 ở
α = 8), và giảm dần α chuyển các trọng số đó sang tín hiệu thật. Pixel được
khuếch đại được làm tròn thành số nguyên, nên các giá trị phân số không thể làm
lối tắt.

**Chấm điểm.**

* Điểm khung: logit trung bình trên lưới 3x3 các crop 256x256 phủ toàn khung
  (offset {0, 16, 32} x {0, 48, 96}). Logit full-frame đơn cũng được báo. Chọn
  mô hình dùng logit validation full-frame, và với T1 điểm full-frame là tốt hơn
  trong hai cái.
* Điểm video: điểm khung trung bình trên các khung bị sửa của một video, tính
  theo từng clip (một video cover và một video stego mỗi clip) và theo từng
  segment 100 khung (34 đơn vị magnitude, 20 đơn vị T1).

**Giao thức.**

* (a, b) Leave-one-clip-out: huấn luyện trên các clip khác và test trên mọi
  khung bị sửa của clip giữ lại.
* (c) Paired half split: trong mỗi clip, một nửa ngẫu nhiên các cặp là tập test
  và phần còn lại là huấn luyện cộng validation.

Các cặp cover/stego luôn ở cùng phía một split. Kẻ tấn công mạnh: nó có đúng các
cặp từ cùng bộ mã hóa và biết khung nào mang bit.

## Kết quả

### Theo từng fold, leave-one-clip-out (seed 20261021)

| Clip giữ lại | Magnitude P_E / AUC | Magnitude FLD coeff / pixel P_E | T1-spread P_E / AUC | T1-spread full-frame P_E | T1-spread FLD kết hợp / pixel P_E |
|---|---|---|---|---|---|
| city | 0.487 / 0.503 | 0.383 / 0.488 | 0.403 / 0.600 | 0.352 | 0.457 / 0.443 |
| coastguard | 0.470 / 0.515 | 0.340 / 0.473 | 0.193 / 0.873 | 0.130 | 0.398 / 0.390 |
| container | 0.448 / 0.549 | 0.385 / 0.448 | 0.090 / 0.971 | 0.033 | 0.343 / 0.358 |
| deadline | 0.490 / 0.508 | 0.452 / 0.465 | n/a | n/a | n/a |
| hall | 0.437 / 0.569 | 0.435 / 0.417 | 0.405 / 0.621 | 0.262 | 0.407 / 0.425 |
| **mean** | **0.466 / 0.529** | 0.399 / 0.458 | **0.273 / 0.766** | **0.194** | 0.401 / 0.404 |

T1-spread LOCO với seed 20261022 cho P_E theo fold 0.398 / 0.193 / 0.085 / 0.435
(mean 0.278, AUC 0.754, full-frame P_E 0.212). Mẫu hình theo clip lặp lại.

### Paired half split, theo clip (P_E; seed 1 / seed 2)

| Clip | Magnitude | T1-spread |
|---|---|---|
| city | 0.470 / 0.467 | 0.217 / 0.193 |
| coastguard | 0.455 / 0.450 | 0.010 / 0.000 |
| container | 0.460 / 0.430 | 0.075 / 0.065 |
| deadline | 0.481 / 0.473 | n/a |
| hall | 0.420 / 0.387 | 0.190 / 0.200 |
| all clips | 0.474 / 0.464 | 0.168 / 0.142 |

### Quyết định ở mức video

| Set / giao thức | Video stego điểm cao hơn cover của nó | Video clip, P_E / AUC gộp | Segment 100 khung, P_E / AUC gộp | AUC segment trong mỗi fold |
|---|---|---|---|---|
| magnitude LOCO | 5/5 | 0.40 / 0.60 | 0.41 / 0.54 | 0.56, 0.75, 0.75, 0.57, 0.78 |
| magnitude paired (s1 / s2) | 5/5, 5/5 | 0.30 / 0.64, 0.20 / 0.76 | 0.41 / 0.58, 0.35 / 0.65 | n/a |
| T1-spread LOCO (s1 / s2) | 4/4, 4/4 | 0.375 / 0.625, 0.25 / 0.75 | 0.40 / 0.59, 0.25 / 0.70 | 0.78, 1, 1, 0.78 / 0.67, 1, 1, 1 |
| T1-spread paired (s1 / s2) | 4/4, 4/4 | 0.00 / 1.00, 0.00 / 1.00 | 0.00 / 1.00, 0.00 / 1.00 | n/a |

Cách đọc bảng này:

* "Stego cao hơn cover của nó" là so sánh theo cặp: nó cần cover, điều một warden
  thật không có. Với carrier magnitude, video stego luôn được chấm cao hơn,
  nhưng chỉ 0.001–0.06 logit. Khoảng cách giữa các clip lớn hơn nhiều (điểm
  trung bình trải từ −0.3 đến +8.7 qua các fold LOCO), nên điều này không thành
  một quyết định mà warden dùng được.
* Gộp các video LOCO qua các fold trộn các mô hình chưa hiệu chỉnh. Offset của
  mỗi fold chiếm ưu thế, đó là lý do P_E video gộp LOCO giữ ở 0.25–0.41 ngay cả
  với T1. Trong một fold, tức với một mô hình và một clip chưa thấy, các segment
  T1 tách hoàn hảo cho coastguard và container.
* Với paired split (cùng mô hình, các cảnh đã thấy), mọi clip T1 và mọi segment
  T1 được phân loại đúng. Các segment magnitude thì không (P_E 0.35–0.41).

### Biên phát hiện (khuếch đại tổng hợp)

* `--amplify 2` huấn luyện, validate và test trên round(cover + 2·(stego −
  cover)), paired split:
  * magnitude: P_E 0.183, AUC 0.904. Hall 0.000, container 0.075, deadline
    0.194, city 0.257, coastguard 0.240. P_E video và segment gộp 0.00.
  * T1-spread: P_E 0.001, AUC 0.9999.
* Các mô hình magnitude LOCO ở α = 1, chấm trên các khung test khuếch đại mà
  không huấn luyện lại, cho mean P_E 0.27 ở α = 2 và 0.18 ở α = 4 (container
  0.15/0.03, hall 0.00/0.00).
* Khuếch đại là một proxy miền pixel. Nó không phải một luồng mã hóa lại với
  payload dày hơn, nên chỉ cho thấy thay đổi không cách xa tầm với của bộ dò.

## Diễn giải

1. Với carrier magnitude-LSB mà pipeline dùng mặc định, một CNN GPU không cải
   thiện so với nghiên cứu FLD. P_E mức khung của nó 0.46–0.47 nằm trong khoảng
   FLD 0.39–0.47 và kém hơn FLD miền hệ số. Thay đổi nhỏ (≈ 2 level), tần số
   thấp và được dự đoán intra trải ra, nên nó trông như nội dung thường trong
   khung đã giải mã. Một bộ dò làm việc ở miền hệ số vẫn là công cụ tốt hơn với
   carrier này, và là cái mà một nghiên cứu mạnh hơn nên cải thiện (ví dụ một
   CNN trên các mặt phẳng hệ số 4x4).
2. Carrier T1-sign yếu hơn rõ rệt trước steganalysis pixel học máy. Cùng
   payload, cùng khung và một MSE pixel nhỏ hơn vẫn cho P_E khung 0.27 trên các
   clip chưa thấy và 0.14–0.17 trên các clip đã thấy, với quyết định segment hoàn
   hảo trên paired split. Một lật dấu của một trailing ±1 là một bước 2-level ở
   một vị trí tần số cao, loại residual tần-số-cao cục bộ mà các bộ lọc SRM bắt
   được. Nghiên cứu dựa trên đặc trưng (pixel FLD 0.40) đã đánh giá thấp điều
   này với biên rộng. Điều này ủng hộ giữ magnitude làm carrier mặc định và coi
   T1 là một chế độ dung lượng không an toàn về steganography.
3. Khả năng phát hiện phụ thuộc clip. Các cảnh tĩnh, nhiều kết cấu (container,
   coastguard) dễ nhất cho T1, trong khi city và hall kháng cự. Thí nghiệm biên
   magnitude chỉ theo hướng ngược lại: hall là clip đầu tiên trở nên dễ phát
   hiện khi thay đổi lớn lên.

## Lưu ý

* Các tập dữ liệu nhỏ (1000–1700 cặp khung từ 4–5 clip, với các khung lân cận
  tương quan mạnh), và mạng nhỏ, huấn luyện tối đa 40 epoch. Một mô hình lớp
  SRNet lớn hơn, nhiều clip hơn, hoặc một khởi tạo pretrained (ví dụ
  BOSSbase/ALASKA) có thể đẩy P_E thấp hơn. Hãy đọc các con số này như một chặn
  trên của P_E cho một kẻ tấn công mạnh-nhưng-có-giới-hạn, không phải một chứng
  minh bảo mật.
* Chỉ chạy hai seed: LOCO magnitude có một seed, và mọi giao thức chính khác có
  hai. Các seed thống nhất trong khoảng 0.03 P_E. Không cho khoảng tin cậy.
  Trong LOCO, mỗi fold là một clip.
* Siêu tham số (lr, độ dài curriculum) được chọn trong một thăm dò ngắn trên
  paired split magnitude. Do đó các con số paired-split mang một thiên lệch chọn
  lựa nhỏ. LOCO không được dùng để tinh chỉnh.
* Paired split chia sẻ các cảnh giữa huấn luyện và test (như trong giao thức
  FLD). Chỉ LOCO đo khả năng tổng quát hóa sang nội dung chưa thấy.
* Khung "bị sửa" là những khung có bất kỳ khác biệt pixel luma nào. Trên
  deadline điều này gồm 16 khung mà báo cáo e2e không đếm là bị sửa.
* Kết quả mức video gộp ít đơn vị (8–10 video clip, 20–34 segment), nên tỉ lệ
  0.00 có nghĩa "không có lỗi trong các đơn vị này", không phải một tỉ lệ lỗi đo
  được.

## Tái lập

Đường dẫn dữ liệu mặc định tới `VideoLevel/{data/encoded,tmp/q2,benchmark/results/q2}`.
Ghi đè bằng `--encoded-dir/--stego-dir/--reports-dir` khi dữ liệu nằm ở checkout
khác.

```bash
python -m benchmark.latticezk_cnn_steganalysis dataset --set magnitude
python -m benchmark.latticezk_cnn_steganalysis dataset --set t1_spread
python -m benchmark.latticezk_cnn_steganalysis train --set magnitude --protocol loco \
    --output benchmark/results/q2/cnn_magnitude_loco.json
python -m benchmark.latticezk_cnn_steganalysis train --set t1_spread --protocol loco \
    --output benchmark/results/q2/cnn_t1_spread_loco.json
python -m benchmark.latticezk_cnn_steganalysis train --set magnitude --protocol paired \
    --output benchmark/results/q2/cnn_magnitude_paired.json
python -m benchmark.latticezk_cnn_steganalysis train --set t1_spread --protocol paired \
    --output benchmark/results/q2/cnn_t1_spread_paired.json
# thí nghiệm biên / lặp lại
python -m benchmark.latticezk_cnn_steganalysis train --set magnitude --protocol paired \
    --amplify 2 --output benchmark/results/q2/cnn_magnitude_paired_margin_a2.json
python -m benchmark.latticezk_cnn_steganalysis train --set t1_spread --protocol loco \
    --seed 20261022 --output benchmark/results/q2/cnn_t1_spread_loco_seed2.json
python -m pytest src/runtest/test_latticezk_cnn_steganalysis.py -q
```

Môi trường: Python 3.12.10, torch 2.11.0+cu128 (CUDA 12.8, cuDNN 9.19),
NVIDIA RTX 3060 Laptop GPU (6 GB; đỉnh khoảng 4.3 GB dùng). Toàn bộ dataset nằm
trên GPU dưới dạng uint8. Working set host đỉnh khi huấn luyện trên set magnitude
khoảng 2.0 GB, đo bằng psutil; phần lớn là runtime CUDA/torch.

Thời gian thực tế:

| Lượt chạy | Thời gian |
|---|---|
| Magnitude LOCO (5 fold) | 27.8 phút |
| T1-spread LOCO (4 fold) | 13.2 phút |
| Magnitude paired | 3.6–4.3 phút |
| T1-spread paired | 2.6–2.9 phút |
| Giải mã dataset (cả hai set) | khoảng 1 phút |
