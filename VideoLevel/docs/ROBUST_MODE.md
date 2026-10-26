# Chế độ bền (robust, bán-mong-manh) — sống qua nén lại

Cập nhật: 2026-10-26 (bản 2: thêm ràng buộc màu, giới hạn tài nguyên, vệ sinh
ffmpeg). Mã: `src/robust/`. Kiểm thử: `src/runtest/test_robust_*.py`.
Đo đạc: `benchmark/robust_transcode.py` → `benchmark/results/robust/`.

## 1. Vì sao cần, và khác chế độ chính thế nào

Chế độ chính (`src/lattice_zk/video_pipeline.py`) ràng buộc **đúng từng bit**
của bitstream H.264 CAVLC: chỉ một lần nén lại (đăng mạng xã hội, chuyển mã)
là con dấu mất. Chế độ bền mang **cùng phong bì BDLOP** (cùng bộ tham số, cùng
sổ đăng ký có chữ ký, cùng pin của người kiểm tra, cùng kho phiên dùng-một-lần)
nhưng:

| | Chế độ chính (mong manh) | Chế độ bền (bán-mong-manh) |
|---|---|---|
| Nơi giấu | hệ số CAVLC trong bitstream | ảnh **đã giải mã** (độ sáng) |
| Đầu vào | H.264 Baseline CAVLC | mọi thứ ffmpeg giải được (CAVLC, **CABAC**, HEVC, Y4M…) |
| Sống qua nén lại | không | có, cùng độ phân giải (x264/x265 CRF ≤ 23; Main CABAC trừ in-band trên cảnh tĩnh — mục 9) |
| Toàn vẹn | chính xác từng bit | **trong dung sai** của một dấu vân nội dung (độ sáng mọi khung + màu của khung lấy mẫu) |
| Chất lượng stego | ~40–43 dB | ~34,6–36,9 dB (đánh đổi để bền) |

Đây là **xác thực bán-mong-manh**, không phải toàn vẹn chính xác: chỉnh sửa
nhỏ hơn dung sai được chấp nhận (mục 7, mục 8).

## 2. Luồng

**Nhúng** (`embed_robust_proof`):
0. Kiểm tra đường dẫn ra: phải **chưa tồn tại** và khác cover (kiểm tra trước
   khi tính chứng minh; không bao giờ ghi đè).
1. Giải mã cover thành các mặt phẳng yuv420p 8-bit (`decode.py`), trong ngân
   sách giải mã (mục 11).
2. Tính **dấu vân nội dung**: độ sáng của mọi khung và màu (U, V) của các khung
   lấy mẫu (`features.py`, mục 5).
3. Từ số khung và độ phân giải, lập **kế hoạch kênh** (`channel_plan`): bố cục
   carrier, độ dài thông điệp, tỉ lệ mã. Không vừa thì từ chối ("clip quá ngắn").
4. Dựng statement (dùng lại `video_proof.build_statement`):
   `video_commitment = H(dấu vân)`, `positions_hash = H(bố cục, tỉ lệ mã, độ dài)`,
   `carrier_count = số slot`, `codec_policy_id = id chính sách robust`,
   `carrier_profile_id = id hồ sơ robust`.
5. Tạo phong bì (in-band hoặc registered) bằng đúng mã của chế độ chính.
6. Thông điệp = `"ZKRM" ‖ phiên bản ‖ độ dài ‖ phong bì ‖ dấu vân ‖ CRC-32`
   → mã chập → rải lặp theo hoán vị khoá → QIM vào ảnh → mã hoá lại bằng
   x264 (mặc định CRF 12, High profile, CABAC).

**Kiểm tra** (`verify_robust_proof`, mù, chỉ từ file nhận được + pin):
1. Kiểm tra cấu hình (tham số đủ mạnh, pin khớp hồ sơ, credential, quan hệ).
   Cấu hình sai → `ValueError` trước khi đọc video.
2. Giải mã (trong ngân sách, có timeout) → giá trị mềm → gộp các khung trong
   nhóm → gộp các bản lặp → Viterbi → CRC → tách phong bì và dấu vân.
3. **Kiểm tra cấu trúc khung**: mã hoá lại codeword đã sửa, so với từng khung;
   khung nào sai > 42 % bit là khung bị bỏ/đổi chỗ/thay → từ chối.
4. **So dấu vân** mang theo với dấu vân tính lại từ video nhận được, theo dung
   sai ghim: trước hết ô độ sáng, rồi ô màu → từ chối kèm danh sách ô lệch
   (`flagged_cells`: khung, hàng, cột, lệch; `flagged_chroma_cells`: khung,
   mặt phẳng 0 = U / 1 = V, hàng, cột, lệch).
5. Dựng statement, kiểm chứng minh, tiêu thụ phiên (chống phát lại).

**Mọi thứ suy ra từ video nhận được đều "fail closed"**: bất kỳ ngoại lệ nào
khi giải mã hay phân tích (ffmpeg lỗi hoặc quá timeout, clip vượt ngân sách,
`MemoryError`, `KeyError`/`IndexError`/`struct.error`/`ZeroDivisionError`… từ
dữ liệu dị dạng) đều trở thành `valid=False` với lý do, không bao giờ ném ra
khỏi `verify_robust_proof`. Chỉ lỗi cấu hình của người kiểm tra (và lỗi I/O
của kho phiên) mới ném ngoại lệ.

Kết quả gồm cả bản đồ định vị: ô vân lệch (`flagged_cells`,
`flagged_chroma_cells`) và cửa sổ 32×32 có watermark bị phá cục bộ
(`damaged_windows`, chỉ để tham khảo; đuôi nhị thức tính bằng numpy, không
cần scipy).

## 3. Kênh mang (watermark)

- **QIM có dither** trên **10 hệ số DCT tần thấp** của khối độ sáng **16×16**:
  (0,1) (1,0) (1,1) (0,2) (2,0) (1,2) (2,1) (2,2) (0,3) (3,0).
- Bit `b` dời hệ số `c` về điểm gần nhất của `Δ·(Z + d + b/2)`, `d` là dither.
- **Nhóm thời gian T = 3**: ba khung liên tiếp mang cùng bit; dither không đổi
  theo thời gian. Lý do: bộ mã liên khung (skip/sao chép khối từ khung trước)
  khi đó sao chép đúng bit.
- Hoán vị slot và dither sinh từ **SHAKE-256(sync key, bố cục)** — tái lập trên
  mọi máy (không phụ thuộc bộ sinh số ngẫu nhiên của numpy).
- Hàm cơ sở AC có tổng bằng 0 trên khối, nên nhúng **không đổi trung bình**
  của khối 16×16 → không đổi dấu vân (ô 64×64 là hợp của khối 16×16).
- Bước Δ: **64** cho registered, **80** cho in-band (`RobustProfile.recommended`).

**Vì sao chọn như vậy (đo trên 40–60 khung, BER thô sau nén lại):**

| Carrier | Container CRF 23 | Foreman CRF 23 | Ghi chú |
|---|---|---|---|
| 8×8 trung tần, Δ=32 | 35 % | 17 % | mã hoá stego CRF 16 |
| 16×16 3 hệ số thấp, Δ=64 | 20 % | 7,6 % | mỗi khung bit khác nhau |
| 16×16 5 hệ số, Δ=64, T=4 | 9 % | 1,7 % | thêm nhóm thời gian |
| **16×16 10 hệ số, Δ=64, T=3, stego CRF 12** | **5,3 %** | **0,8 %** | chọn |

Đo 300 khung, BER theo slot sau gộp nhóm (Δ=64 / 72 / 80):

| Tấn công | Container | Akiyo | Foreman |
|---|---|---|---|
| x264 CRF 18 | 0,6 / 0,3 / 0,1 % | 0,1 / 0,0 / 0,0 % | 0,0 % |
| x264 CRF 23 | 5,0 / 3,3 / 2,3 % | 2,9 / 1,7 / 1,0 % | 0,9 / 0,4 / 0,2 % |
| x264 Main CRF 23 | 7,6 / 5,5 / 4,0 % | 6,1 / 4,1 / 2,6 % | 1,8 / 1,0 / 0,6 % |
| x265 CRF 23 | 1,2 / 0,6 / 0,2 % | 1,0 / 0,4 / 0,1 % | 0,1 / 0,0 / 0,0 % |
| x264 CRF 28 | 18,9 / 15,4 / 12,7 % | 16,9 / 13,4 / 10,4 % | 6,8 / 5,0 / 3,7 % |

PSNR stego so với cover (300 khung): Δ=64 → 36,3–36,8 dB; Δ=72 → 35,4–35,8 dB;
Δ=80 → 34,6–34,9 dB.

## 4. Mã sửa lỗi

- Mã chập **K = 7** có đuôi 6 bit 0, giải **Viterbi mềm**: tỉ lệ **1/3**
  (đa thức 133/171/165) nếu vừa dung lượng, không thì **1/2** (171/133);
  phần dung lượng còn lại lặp codeword (gộp mềm). Việc chọn tỉ lệ là hàm tất
  định của độ dài thông điệp và dung lượng, nên người kiểm tra tự suy ra.
- **CRC-32** trên toàn thông điệp.
- **Không dùng Reed–Solomon ngoài**: mô phỏng trên độ tin cậy kênh đo thật cho
  thấy chi phí 14 % của RS(255,223) buộc phong bì registered xuống tỉ lệ 1/2 và
  làm *giảm* tỉ lệ giải được; với in-band thì không còn vừa 300 khung CIF.

Ngân sách 300 khung CIF (tham số `bdlop-open-128-v3`, dung lượng 396 000 slot,
blob dấu vân bản 2 = độ sáng 6 750 B + màu 563 B + header 34 B):

| | phong bì | dấu vân | thông điệp | mã | bit mã | lặp |
|---|---|---|---|---|---|---|
| registered | 8 741 B | 7 347 B | 16 105 B | 1/3 | 386 538 | 1,024× |
| in-band | 16 421 B | 7 347 B | 23 785 B | 1/2 | 380 572 | 1,041× |

(Bản 1 chỉ độ sáng: 6 771 B, lặp 1,06× / 1,07×. Phần màu được chọn thưa — mỗi
khung thứ 6 — chính là để phong bì registered **giữ được tỉ lệ 1/3** ở 300 khung
CIF; lấy mẫu mỗi khung thứ 3 sẽ cần 399 714 bit > 396 000.)

## 5. Dấu vân nội dung

- **Độ sáng**: mỗi khung chia ô **64×64** (ô biên có thể khuyết), lấy trung
  bình, lượng tử bước **4** (6 bit/ô), **mọi khung**. CIF: 30 ô/khung,
  6 750 B/300 khung.
- **Màu** (mới, bản 2): trên **mỗi khung thứ 6** (khung 0, 6, 12, …;
  `chroma_every = 6`), hai mặt phẳng U và V chia ô **64×64 mẫu màu** (= 128×128
  điểm ảnh độ sáng ở 4:2:0; `chroma_block = 64`), lấy trung bình, lượng tử
  bước **8** (5 bit/ô; `chroma_step = 8`). CIF: 3×3 ô/mặt phẳng = 18 ô/khung
  lấy mẫu, 50 khung lấy mẫu/300 khung → 563 B. Watermark chỉ chạm độ sáng nên
  phần màu của cover và stego giống hệt nhau. `chroma_every = 0` tắt phần màu
  (chỉ độ sáng) — hồ sơ khi đó có `profile_id` khác.
- Blob bản 2: `"ZKRF" ‖ 2 ‖ rộng ‖ cao ‖ số khung ‖ ô ‖ bước ‖ bit ‖ số ô/khung
  ‖ ô màu ‖ bước màu ‖ chu kỳ lấy mẫu ‖ bit màu ‖ số ô màu/khung lấy mẫu ‖ số
  khung lấy mẫu ‖ giá trị độ sáng ‖ giá trị màu (U rồi V)`. Hình học
  (rộng/cao/số khung) nằm trong blob nên đổi độ phân giải hay số khung đều bị
  phát hiện. Blob bản 1 (chỉ độ sáng) bị từ chối ("version unsupported").
- **Không va chạm giữa bản 1 và bản 2**: chuỗi chính sách đổi thành
  `…/fingerprint-cell-mean-v2-luma-chroma` (đổi `codec_policy_id`), và mô tả hồ
  sơ gồm toàn bộ đặc tả màu + dung sai màu (đổi `profile_id`, do đó đổi
  `policy_hash`, `relation_id` và khoá đồng bộ công khai). Pin cũ không bao giờ
  khớp hồ sơ mới và ngược lại.

## 6. Ràng buộc vào chứng minh

Statement băm vào thử thách Fiat–Shamir gồm: digest của **blob dấu vân mang
theo**, digest của **bố cục kênh** (khung, kích thước, Δ, hệ số, khối, nhóm, tỉ
lệ mã, độ dài), id chính sách robust, id hồ sơ (gồm mọi dung sai), sổ đăng ký,
phiên. Vì vậy kẻ tấn công không thể sửa dấu vân mang theo hay dung sai mà chứng
minh vẫn hợp lệ; tính đúng đắn (soundness) và không tiết lộ (zero-knowledge) của
chứng minh không đổi so với chế độ chính.

## 7. Quy tắc quyết định và dung sai (ghim trong hồ sơ)

Độ sáng (đơn vị = bước 4 mức):
- `hard_delta = 3`: một ô lệch ≥ 3 bước (≈ 10–12 mức sáng trung bình) → từ chối.
- `drift_delta = 2`, `max_drift_fraction = 0,002`: quá 0,2 % số ô lệch ≥ 2 bước → từ chối.

Màu (đơn vị = bước 8 mức, chỉ trên khung lấy mẫu):
- `chroma_hard_delta = 2`: một ô màu lệch ≥ 2 bước (≈ 12–16 mức U/V trung bình) → từ chối.
- `chroma_drift_delta = 1`, `chroma_max_drift_fraction = 0,25`: quá 25 % số ô màu
  lệch ≥ 1 bước → từ chối (bắt được dịch màu toàn cục cỡ 8 mức).

Khung:
- `max_frame_ber = 0,42`: khung có > 42 % bit sai so với codeword → từ chối
  (khung bị đổi chỗ/thay mang bit của vị trí khác → ~50 %).

Hiệu chỉnh độ sáng: trên các lần nén lại sạch được chấp nhận (mục 9), ô lệch
tối đa là 1 bước, không ô nào lệch 2; BER khung sạch lớn nhất đo được là 0,18
(Container CRF 23 / Akiyo Main CABAC) — xa ngưỡng 0,42. Khung đổi chỗ đo được
0,48–0,51. Ô 48×48 dán vào lệch 4–8 bước — vượt `hard_delta` rõ.

Hiệu chỉnh màu (60 khung đầu của Container và Foreman, hồ sơ registered Δ=64,
stego CRF 12 rồi nén lại; 180 ô màu/clip; `scratchpad/calibrate_chroma.py`,
số liệu 2026-10-26):

| Trường hợp | Container: lệch max / % ô ≥ 1 | Foreman: lệch max / % ô ≥ 1 | Kết quả |
|---|---|---|---|
| stego, nén lại CRF 12 (đối chứng) | 0 / 0 % | 0 / 0 % | chấp nhận |
| x264 CRF 23 | 0 / 0 % | 0 / 0 % | chấp nhận |
| x264 Main CABAC CRF 23 | 0 / 0 % | 1 / 1,7 % | chấp nhận |
| x265 CRF 23 | 0 / 0 % | 0 / 0 % | chấp nhận |
| x264 CRF 28 | 0 / 0 % | 1 / 5,0 % | dấu vân đạt (Container rớt ở CRC như trước) |
| V +16 trên một ô 128×128 của khung 12 (khung lấy mẫu) | 2 / 0,6 % | 2 / 0,6 % | **từ chối**, ô (12, V, 0, 0) |
| U ±16 toàn cục mọi khung | 2 / 50 % | 2 / 50 % | **từ chối** (90/180 ô) |
| U +12 toàn cục | 2 / 50 % | 2 / 50 % | **từ chối** |
| U +8 toàn cục | 1 / 50 % | 1 / 50 % | **từ chối** (quy tắc trôi 25 %) |
| V +16 trên nửa ô (64×128) khung 12 | 1 / 0,6 % | 1 / 0,6 % | chấp nhận (giới hạn) |
| V +16 trên ¼ ô khung 12 | 0 / 0 % | 1 / 0,6 % | chấp nhận (giới hạn) |
| U +16 chỉ trên khung 13 (không lấy mẫu) | 0 / 0 % | 0 / 0 % | chấp nhận (giới hạn) |

Nén lại sạch: lệch màu tối đa **1** bước, tỉ lệ ô trôi tối đa **5 %** (CRF 28)
và **1,7 %** (CRF 23) → ngưỡng cứng 2 và ngưỡng trôi 25 % có biên ≥ 5×. Dịch
16 mức trên nguyên một ô lấy mẫu lệch đúng 2 bước (16/8) nên luôn bị bắt.

## 8. Lập luận an toàn và giới hạn

Giữ nguyên từ chế độ chính: không giả được chứng minh khi không có bí mật
(M-SIS), không lộ bí mật (M-LWE), chống phát lại (phiên dùng một lần), cấu hình
sai bị từ chối ồn ào.

Giới hạn — phải nói thẳng:
1. **Bán-mong-manh**: chỉnh sửa giữ mọi ô 64×64 trong dung sai (ví dụ thay một
   vùng bằng nội dung có cùng độ sáng trung bình, hay sửa nhỏ dưới ~8 mức) **được
   chấp nhận**. Bản đồ `damaged_windows` có thể chỉ ra vùng watermark bị phá
   nhưng không quyết định hợp lệ (vùng phẳng sau CRF cao cũng có thể bị phá).
1b. **Màu chỉ bị ràng buộc thô** (đo ở mục 7): ô 128×128, bước 8, và chỉ trên
   **mỗi khung thứ 6**. Vì thế **được chấp nhận**: đổi màu giới hạn trong các
   khung không lấy mẫu (5/6 số khung — kẻ tấn công biết hồ sơ nên biết khung
   nào), đổi màu trên dưới ~¾ diện tích một ô, hay dịch màu toàn cục dưới ~8
   mức. Bị bắt: dịch ≥ 12–16 mức trên nguyên một ô lấy mẫu, hoặc dịch ≥ 8 mức
   trên > 25 % số ô lấy mẫu (đổi màu toàn cục, đổi tông cả cảnh). Lấy mẫu thưa
   là cái giá để giữ tỉ lệ mã 1/3 (mục 4); watermark không chạm màu nên không
   có kiểm tra khung nào cho mặt phẳng màu.
2. **Đổi chỗ hai khung trong cùng nhóm 3 khung** không bị phát hiện bởi
   watermark (chúng mang cùng bit); dấu vân chỉ bắt được nếu nội dung khác.
3. **Không bền với biến đổi hình học** (đổi độ phân giải, cắt, xoay, lật):
   bị từ chối, không sống qua. Chỉ bền với nén lại **cùng độ phân giải**.
4. **CRF 28 trên cảnh tĩnh** (Container, Akiyo) và **in-band Container qua
   Main CABAC CRF 23** vượt khả năng mã sửa lỗi ở 300 khung CIF: bị từ chối
   "watermark not recoverable" (an toàn nhưng không bền). Phong bì in-band chỉ
   còn tỉ lệ 1/2 và 1,07× lặp; clip dài hơn hoặc độ phân giải cao hơn cho nhiều
   bản lặp hơn và sẽ lên được tỉ lệ 1/3.
5. **Khoá đồng bộ công khai** (`public_sync_key`): ai có pin cũng đọc được
   phong bì, và cũng **xoá/phá** được watermark (tấn công từ chối dịch vụ). Họ
   **không** giả được: chép watermark sang video khác thì dấu vân không khớp.
   Dùng khoá bí mật nếu muốn che sự tồn tại của watermark.
6. Chất lượng thấp hơn chế độ chính (~35–37 dB) và clip phải đủ dài:
   300 khung CIF là tối thiểu cho cả hai loại phong bì; clip ngắn bị từ chối
   khi nhúng ("clip quá ngắn").
7. Không chống steganalysis: QIM tần thấp với Δ lớn dễ bị phát hiện về mặt
   thống kê. Chế độ này nhắm **bền**, không nhắm **ẩn**.

## 9. Kết quả đo

Blob **bản 2** (độ sáng + màu):
`benchmark/results/robust/robust_transcode_20261026_fp2.json` — 3 clip CIF 300
khung × 2 loại phong bì, tham số `bdlop-open-128-v3`, hồ sơ `recommended`,
mã tốc độ 1/3 (registered, lặp 1,024×) / 1/2 (in-band, lặp 1,041×). Tổng:
**31/36** trường hợp nén lại được chấp nhận, **30/30** trường hợp sửa đổi bị
từ chối (5 kiểu × 6 lượt, gồm `tamper_recolour_u+16` mới), phát lại qua kho
phiên bị chặn ở cả 6 lượt. Chấp nhận: x264 CRF 18/23 và x265 CRF 23 ở mọi
lượt; Main-CABAC CRF 23 ở 5/6 (trượt: Akiyo in-band); CRF 28 chỉ trên Foreman
(trượt: Container, Akiyo — nội dung tĩnh, như bản 1). PSNR stego 36,3–36,9 dB
(registered) / 34,6–34,9 dB (in-band), SSIM 0,89–0,94. Mọi trường hợp nén lại
sạch được chấp nhận có ô vân độ sáng lệch tối đa **1** bước, ô màu lệch tối đa
**1** bước, BER khung lớn nhất **0,18** (ngưỡng 0,42).

> Bảng chi tiết dưới đây đo với blob **bản 1** (chỉ độ sáng,
> `robust_transcode_20261026.json`, 24/24 sửa đổi bị từ chối khi chưa có ca đổi
> màu). Với bản 2, kết quả theo ca giống hệt trừ hai ca sát ngưỡng đổi chỗ:
> Main-CABAC CRF 23 in-band nay **đạt** trên Container và **trượt** trên Akiyo;
> các ca CRF 28 không đổi.

Chất lượng stego (so với cover, trước nén lại của bên nhận):

| Clip | Phong bì | PSNR | SSIM | Nhúng |
|---|---|---|---|---|
| Container | registered (Δ=64, 1/3) | 36,3 dB | 0,938 | 3,8 s |
| Container | in-band (Δ=80, 1/2) | 34,6 dB | 0,914 | 4,6 s |
| Foreman | registered | 36,8 dB | 0,920 | 4,4 s |
| Foreman | in-band | 34,9 dB | 0,886 | 7,3 s |
| Akiyo | registered | 36,5 dB | 0,923 | 3,7 s |
| Akiyo | in-band | 34,7 dB | 0,893 | 3,5 s |

Nén lại (BER thô theo khung trước bộ giải mã; ✓ = chứng minh hợp lệ):

| Tấn công | Container reg / in-band | Foreman reg / in-band | Akiyo reg / in-band |
|---|---|---|---|
| x264 CRF 18 | ✓ 1,6 % / ✓ 0,6 % | ✓ 0,2 % / ✓ 0,0 % | ✓ 0,5 % / ✓ 0,1 % |
| x264 CRF 23 | ✓ 6,6 % / ✓ 3,5 % | ✓ 2,5 % / ✓ 1,0 % | ✓ 3,9 % / ✓ 1,7 % |
| x264 Main CABAC CRF 23 | ✓ 7,9 % / **✗ CRC** | ✓ 4,1 % / ✓ 1,9 % | ✓ 8,7 % / ✓ 4,4 % |
| x265 CRF 23 | ✓ 2,9 % / ✓ 1,1 % | ✓ 0,6 % / ✓ 0,1 % | ✓ 1,8 % / ✓ 0,5 % |
| x264 CRF 28 | **✗ CRC** / **✗ CRC** | ✓ 9,9 % / ✓ 6,2 % | **✗ CRC** / **✗ CRC** |

"✗ CRC" = watermark không giải được (từ chối an toàn, nhưng không bền). Năm
thất bại đều ở cảnh tĩnh (Container, Akiyo) với CRF 28, cộng in-band Container
qua Main CABAC (bit mã lặp chỉ 1,07× ở tỉ lệ 1/2). Foreman (chuyển động nhiều,
bộ mã giữ chi tiết hơn) sống qua mọi mức. PSNR sau nén lại so với cover:
33,5–37,6 dB.

Sửa đổi (mọi trường hợp từ chối, kèm định vị):

| Sửa đổi | Kết quả | Định vị |
|---|---|---|
| Dán ô 48×48 vào khung 150 | từ chối: "ô lệch 4–8 bước" | 1–2 ô vân đúng khung 150; 2–3 cửa sổ watermark |
| Bỏ 1 khung (100) | từ chối: CRC sai (lệch nhóm thời gian từ khung 100) | — |
| Đổi chỗ khung 60 ↔ 240 | từ chối: 2 khung sai ~50 % bit | đúng hai khung 60, 240 |
| Thu nhỏ còn một nửa | từ chối trước khi giải: dung lượng 99 000 slot không đủ | — |
| Dịch U +16 toàn cục (bản 2, đo 60 khung) | từ chối: "ô màu lệch 2 bước" | 50 % ô màu, mặt phẳng U |

Thời gian kiểm tra: 7–30 s/clip 300 khung CIF (giải mã ffmpeg + DCT + Viterbi
Python thuần); thu nhỏ bị từ chối trong 0,2 s.

Ghi chú về `damaged_windows`: trên nén lại sạch CRF 23 vẫn có 3–108 cửa sổ bị
đánh dấu (vùng phẳng mất bit), nên bản đồ này chỉ để tham khảo; quyết định hợp
lệ dựa vào dấu vân và kiểm tra khung.

## 10. Cách chạy

```bash
# kiểm thử (khoảng 1–2 phút)
python -m pytest -q src/runtest/test_robust_ecc.py src/runtest/test_robust_watermark.py \
  src/runtest/test_robust_pipeline.py

# benchmark đầy đủ (~30 phút; chạy tách nền)
python benchmark/robust_transcode.py --clips container_cif foreman_cif_300f akiyo_cif
```

## 11. Giới hạn tài nguyên và vệ sinh ffmpeg (`src/robust/decode.py`)

Người kiểm tra giải mã **file do người khác gửi**, nên lớp I/O được siết:

| Biện pháp | Chi tiết |
|---|---|
| Ngân sách giải mã | `MAX_LUMA_SAMPLES = 3840·2160·3000` (≈ 24,9 G mẫu độ sáng, tức 2160p × 3000 khung). `ffprobe` chạy trước; nếu `nb_frames` (mp4/mkv) hoặc `duration × r_frame_rate` (y4m) cho thấy `rộng × cao × số khung` vượt ngân sách thì **từ chối trước khi giải mã**. Luôn truyền `-frames:v (giới hạn + 1)` cho ffmpeg, nên dù container không khai số khung, bộ nhớ vẫn bị chặn ở ngân sách (+1 khung để phân biệt "vừa đủ" với "vượt"). `verify_robust_proof(..., max_luma_samples=…)` cho phép siết chặt hơn. Giải mã giữ ≈ 3 byte/mẫu độ sáng (raw 4:2:0 + các mặt phẳng), nên đây là chặn DoS chứ không phải mức "thoải mái". |
| Kiểm tra trường ffprobe | `width`, `height` phải là số nguyên chẵn trong `1..16384`; `r_frame_rate` phải khớp `n` hoặc `n/d` với `d > 0`; `duration` phải hữu hạn, không âm; `nb_frames` phải là số. Sai → `ValueError` (trong verify → `valid=False`), không còn `KeyError`/`ZeroDivisionError`. |
| Timeout | `SUBPROCESS_TIMEOUT = 600 s` cho **mọi** `subprocess.run` (ffprobe, giải mã, mã hoá); quá hạn → `subprocess.TimeoutExpired`, tiến trình con bị giết; verify trả `valid=False`. |
| Đường dẫn | Mọi đường dẫn được resolve tuyệt đối và truyền dạng `file:<tuyệt đối>`: tên bắt đầu bằng `-` không bị hiểu là tuỳ chọn, `-` không phải stdin, `concat:`/`http:`… không còn là giao thức. Thêm `-protocol_whitelist file,pipe` (vào) và `file` (ra); `-nostdin` và `stdin=DEVNULL` cho mọi tiến trình. Đã kiểm với ffmpeg 8.0.1 trên Windows (`file:D:\…` hoạt động; `concat:` bị chặn "not on whitelist"). |
| Không ghi đè | `encode()` từ chối đường dẫn ra đã tồn tại (`FileExistsError`) hoặc thư mục không có; `embed_robust_proof` kiểm tra điều này **trước** khi tính chứng minh và từ chối `output == cover`. Lưu ý `-n` của ffmpeg 8 thoát mã 0 khi file đã có, nên kiểm tra nằm ở Python; sau khi mã hoá còn kiểm tra file ra tồn tại và khác rỗng. |
| Fail closed | `verify_robust_proof` gói toàn bộ phần suy ra từ video trong một lớp bắt ngoại lệ: `MemoryError` → "exceeded available memory", `TimeoutExpired` → "ffmpeg exceeded the 600 s limit", mọi `Exception` khác → `video rejected: <kiểu>: <thông điệp>`. Phong bì dị dạng làm `verify_envelope` ném ngoại lệ cũng chỉ là từ chối. |

Bộ nhớ ở các bước sau cũng bị chặn bởi ngân sách này: hoán vị SHAKE (8 B/slot,
slot ≤ mẫu/256·10/3), giá trị mềm theo khung (8 B/vị trí ≈ 0,31 B/mẫu).

Dùng trong mã:

```python
from src.robust import pipeline as robust
profile = robust.RobustProfile.recommended(registered=True)
pins = robust.pins_from_registry(registry, issuer_pub, params, profile,
                                 minimum_epoch=1, credential=commitment)
key = robust.public_sync_key(params, profile)
robust.embed_robust_proof(cover, "stego.mp4", None, params=params, pins=pins,
    profile=profile, session_challenge=grant.challenge, sync_key=key,
    credential=credential)
result = robust.verify_robust_proof("received.mp4", params=params, pins=pins,
    profile=profile, sync_key=key, session_store=store, credential=commitment)
```

## 12. CLI (dòng lệnh)

`src/robust/cli.py` là bản song sinh robust của `src.lattice_zk.cli`: cùng kiểu
phân tách vai trò, cùng quy ước ghi file (chống ghi đè bằng `O_EXCL`), cùng mã
thoát (**0** hợp lệ / **1** `valid=false` / **2** lỗi cấu hình). Mỗi lệnh chỉ
chạm file của vai trò mình:

    issuer    issuer-keygen, registry-sign
    holder    credential-new, embed, disclose
    verifier  session-issue, verify, disclosure-verify

`issuer-keygen` và `credential-new` **dùng lại nguyên** handler của chế độ
chính (cùng `PARAMS = BDLOP_OPEN_128`), nên **khoá issuer và credential dùng
chung được** giữa hai chế độ. Nhưng mô tả quan hệ, chính sách, ràng buộc phiên
và kênh mang của robust **khác**, nên **sổ đăng ký và phiên của robust KHÔNG
dùng lẫn** với chế độ chính — CLI này giải cả ba bằng chính các hàm của
`src.robust.pipeline`.

Khoá đồng bộ 32 byte (hex) nằm ở biến môi trường
`ZKSTEGO_ROBUST_SYNC_KEY_HEX`, dùng chung giữa bên nhúng và bên kiểm tra; hoặc
dùng `--public-carrier-order` để suy khoá từ hồ sơ công khai (xác minh công
khai; đánh đổi tính ẩn — mục 8, giới hạn 5). `embed` **mã hoá lại** cover nên
`--output` phải **chưa tồn tại** và khác cover.

Clip phải đủ dài để kênh mang vừa phong bì: **registered ≥ 153 khung CIF**,
**in-band ≥ 285 khung CIF** (`channel_plan`); muốn bền qua nén lại mạnh (tỉ lệ
mã 1/3) dùng ~300 khung — mục 4.

### Luồng registered đầy đủ (dán chạy được)

```bash
# 0. Khoá đồng bộ 32 byte dùng chung (bên nhúng và bên kiểm tra phải giống nhau)
export ZKSTEGO_ROBUST_SYNC_KEY_HEX=$(python -c "import os;print(os.urandom(32).hex())")

# 1. Issuer: cặp khoá ML-DSA-65
python -m src.robust.cli issuer-keygen --public issuer.pub --private issuer.key

# 2. Holder: cam kết credential (bdlop commitment + opening)
printf 'camera-7' > device.bin
python -m src.robust.cli credential-new --payload-file device.bin \
    --public cred.pub.json --private cred.key.json

# 3. Issuer: ký sổ đăng ký với MỘT quan hệ robust đã đăng ký
python -m src.robust.cli registry-sign --issuer-private issuer.key --epoch 1 \
    --credential cred.pub.json --out registry.json

# 4. Verifier: phát một thử thách phiên dùng-một-lần
python -m src.robust.cli session-issue --database sessions.sqlite3 \
    --registry registry.json --issuer-public issuer.pub --minimum-epoch 1 \
    --credential cred.pub.json
# → {"challenge": "<CH>", "expires_at": ..., "issued_at": ...}

# 5. Holder: nhúng và mã hoá lại (output phải chưa tồn tại và khác cover)
python -m src.robust.cli embed --video cover.y4m --output stego.mp4 \
    --session <CH> --credential-private cred.key.json \
    --registry registry.json --issuer-public issuer.pub --minimum-epoch 1
# → {"mode":"registered","statement_id":"<SID>","rate":2,"watermark_psnr":...}

# 6. Verifier: kiểm tra chỉ từ video nhận được (tiêu thụ phiên → chống phát lại)
python -m src.robust.cli verify --video stego.mp4 --database sessions.sqlite3 \
    --registry registry.json --issuer-public issuer.pub --minimum-epoch 1 \
    --credential cred.pub.json
# → {"valid":true,"reason":"ok","statement_id":"<SID>","bad_frames":[],
#    "damaged_windows":0,"flagged_cells":0,"flagged_chroma_cells":0,...}
```

### In-band và tiết lộ (disclosure)

```bash
# Sổ đăng ký + phiên in-band (không có --credential)
python -m src.robust.cli registry-sign --issuer-private issuer.key --epoch 1 --out registry.json
python -m src.robust.cli session-issue --database sessions.sqlite3 \
    --registry registry.json --issuer-public issuer.pub --minimum-epoch 1   # → <CH>

# Nhúng in-band: cam kết một payload, giữ opening lại
printf 'hidden record' > payload.bin
python -m src.robust.cli embed --video cover.y4m --output stego.mp4 \
    --session <CH> --payload-file payload.bin --opening-out opening.json \
    --registry registry.json --issuer-public issuer.pub --minimum-epoch 1

# Kiểm tra và giữ phong bì đã xác minh để dùng cho disclosure
python -m src.robust.cli verify --video stego.mp4 --database sessions.sqlite3 \
    --envelope-out envelope.bin \
    --registry registry.json --issuer-public issuer.pub --minimum-epoch 1   # → <SID>

# Tiết lộ payload cho một người nhận ở dạng zero-knowledge (randomness KHÔNG lộ)
python -m src.robust.cli disclose --opening opening.json \
    --statement-id <SID> --nonce $(python -c "import os;print(os.urandom(32).hex())") \
    --out disclosure.bin
python -m src.robust.cli disclosure-verify --envelope envelope.bin \
    --disclosure disclosure.bin --statement-id <SID> --nonce <cùng nonce>
# → {"valid": true, "payload_hex": "68696464656e207265636f7264"}
```

Kiểm thử CLI: `python -m pytest -q src/runtest/test_robust_cli.py` (12 test
nhanh không cần ffmpeg; 2 test đầu-cuối nhúng→kiểm có cổng
`skipif(ffmpeg)` + `needs_data`, ~40 s khi có dữ liệu).
