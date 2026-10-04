# Hệ thống ZK-Stego VideoLevel hoạt động như thế nào

Tài liệu này mô tả toàn bộ đường đi của dữ liệu trong VideoLevel: từ một file video
chưa nén, qua FFmpeg/libx264, cấu trúc bitstream H.264, kênh nhúng trên dấu hệ số
CAVLC, khung kênh, proof Groth16, đến trích xuất mù và xác minh. Mỗi phần
chỉ ra file mã nguồn tương ứng và cách quan sát bước đó bằng demo.

Cập nhật: 2026-10-04 (giao thức kênh v3: bỏ thẻ HMAC trong khung). Phạm vi: mã nguồn trên nhánh `main` tại thời điểm viết.

## Mục lục

1. [Bức tranh tổng thể](#1-bức-tranh-tổng-thể)
2. [FFmpeg và libx264: từ frame chưa nén đến file H.264](#2-ffmpeg-và-libx264-từ-frame-chưa-nén-đến-file-h264)
3. [Cấu trúc file H.264 Annex-B](#3-cấu-trúc-file-h264-annex-b)
4. [Slice, macroblock và block](#4-slice-macroblock-và-block)
5. [Dự đoán intra, biến đổi và lượng tử hóa](#5-dự-đoán-intra-biến-đổi-và-lượng-tử-hóa)
6. [Mã hóa entropy CAVLC](#6-mã-hóa-entropy-cavlc)
7. [Kênh nhúng: dấu của hệ số trailing-one](#7-kênh-nhúng-dấu-của-hệ-số-trailing-one)
8. [Lịch nhúng có khóa (keyed schedule)](#8-lịch-nhúng-có-khóa-keyed-schedule)
9. [Khung kênh và trích xuất mù](#9-khung-kênh-và-trích-xuất-mù)
10. [Payload và proof Groth16 (camera trong sổ đăng ký + ràng buộc video)](#10-payload-và-proof-groth16-camera-trong-sổ-đăng-ký--ràng-buộc-video)
11. [Luồng đầu-cuối và giao diện dòng lệnh native](#11-luồng-đầu-cuối-và-giao-diện-dòng-lệnh-native)
12. [Dịch vụ HTTP/WebSocket](#12-dịch-vụ-httpwebsocket)
13. [Bộ lập lịch realtime](#13-bộ-lập-lịch-realtime)
14. [Một lõi media (nhánh Python cũ đã gỡ)](#14-một-lõi-media-nhánh-python-cũ-đã-gỡ)
15. [Demo và cách đọc kết quả debug](#15-demo-và-cách-đọc-kết-quả-debug)
16. [Kiểm thử và tái lập](#16-kiểm-thử-và-tái-lập)
17. [Bảo mật, giới hạn và việc còn mở](#17-bảo-mật-giới-hạn-và-việc-còn-mở)
18. [Thuật ngữ](#18-thuật-ngữ)
19. [Bản đồ mã nguồn](#19-bản-đồ-mã-nguồn)

---

## 1. Bức tranh tổng thể

```text
 video gốc (.y4m / camera)
        |
        v
 FFmpeg + libx264  --(Baseline, CAVLC, 1 slice/frame, không B-frame)-->  source.h264
                                                                              |
 camera (secret s, pk trong sổ đăng ký) + message + hash video cover   |
        |                                                                     |
        v                                                                     v
 circom/snarkjs Groth16 --> proof 129 byte                      parser CAVLC native (C++)
        |                                                      liệt kê ứng viên = dấu trailing-one
        v                                                                     |
 payload = [0x01][mode][len 2B][message][proof 129B]                         |
        |                                                                     |
        v                                                                     v
 khung kênh v3 = [0x03][len 2B][payload]  --XOR keystream--> lịch nhúng HMAC theo khóa
                                                                              |
                                                                              v
                                                         lật dấu tại các vị trí đã chọn -> stego.h264
                                                                              |
 ============================== phía nhận =====================================|
                                                                              v
                                                    parser native + cùng khóa -> cùng lịch
                                                                              |
                                                     đọc bit, kiểm version/độ dài, lấy payload
                                                                              |
                                   unpack -> hash video nhận được -> snarkjs verify với root -> message
```

Ba lớp có trách nhiệm tách biệt:

| Lớp | Thực hiện ở | Bảo đảm |
|---|---|---|
| Media | `native/src/cavlc_stream.cpp` | Bitstream sau khi nhúng vẫn hợp lệ, độ dài mã không đổi, decoder chuẩn giải được |
| Kênh giấu tin | `native/src/cavlc_stream.cpp`, `src/native_blind_contract.py` | Chỉ người có khóa tìm được vị trí và đọc được khung; kênh không có MAC nên không tự phát hiện bit bị sửa |
| Proof | `src/zk_proof.py`, `src/camera_proof.py`, `circuits/camera_video.circom` | Camera trong sổ đăng ký xác nhận đúng video (hash toàn file, trừ bit carrier) và message; lớp duy nhất xác thực payload |

Chỉ có **một lõi media là native C++**; Python điều phối proof, đóng gói, dịch vụ và demo.
Nhánh Python cũ đã được gỡ ngày 2026-10-03 (mục 14).

---

## 2. FFmpeg và libx264: từ frame chưa nén đến file H.264

### 2.1. FFmpeg là gì trong hệ thống này

`ffmpeg` là chương trình điều phối các thư viện `libavformat` (container),
`libavcodec` (codec), `libavfilter` (bộ lọc) và `libswscale` (đổi kích thước,
định dạng điểm ảnh). Một lệnh encode tạo ra chuỗi thành phần, mỗi thành phần chạy
trong một thread riêng và trao đổi packet hoặc frame qua hàng đợi:

```text
demuxer (yuv4mpegpipe) -> decoder (rawvideo) -> filtergraph (scale, setsar) -> encoder (libx264) -> muxer (h264)
     đọc container           tách frame thô          đổi kích thước/SAR          nén H.264            ghi Annex-B
```

Lệnh demo (`demo/terminal_demo.py`, hàm `video_prepare`):

```text
ffmpeg -loglevel verbose -i input.y4m -map 0:v:0 -an -frames:v 8
       -vf scale=w='min(640,iw)':h='min(480,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1
       -c:v libx264 -profile:v baseline -pix_fmt yuv420p -qp 22 -g 1 -bf 0 -threads 1
       -x264-params cabac=0:keyint=1:min-keyint=1:scenecut=0:bframes=0:slices=1:threads=1
       -f h264 source.h264
```

| Tham số | Lý do |
|---|---|
| `-profile:v baseline`, `cabac=0` | Parser native chỉ hỗ trợ CAVLC (Baseline). CABAC không có kênh dấu độc lập như vậy |
| `-g 1` / `keyint=1` | Mọi frame là IDR. Chỉ IDR mang dữ liệu nhúng; GOP>1 vẫn chạy được nhưng P-frame không có ứng viên |
| `slices=1`, `threads=1` | Parser native chỉ nhận một slice mỗi frame, bắt đầu ở MB 0 |
| `-bf 0` | Không B-frame; thứ tự giải mã trùng thứ tự hiển thị |
| `-qp 22` | Lượng tử cố định (CQP). x264 tự hạ QP của I-frame theo `ip_ratio=1.40`: 22 − 6·log2(1.4) ≈ **19** |

### 2.2. Bên trong libx264 với mỗi frame

libx264 không in log từng bước, nhưng thứ tự xử lý với một I-frame như sau:

1. Chia frame thành macroblock (MB) 16×16 mẫu luma (cộng 2 khối 8×8 chroma).
2. Với từng MB, thử các mode Intra16x16 (4 mode) và Intra4x4 (9 mode cho mỗi khối 4×4),
   chọn mode có chi phí tỉ lệ–méo (RD cost) thấp nhất.
3. Dự đoán từ các mẫu **đã tái tạo** của MB bên trái/trên; residual = gốc − dự đoán.
4. Biến đổi nguyên 4×4 (xấp xỉ DCT), lượng tử hóa theo QP. x264 thêm dead-zone,
   trellis (`trellis=1`) và psy-RD nên mức lượng tử không hoàn toàn theo công thức giáo khoa.
5. Quét zig-zag, mã hóa entropy CAVLC.
6. Tái tạo (giải lượng tử, biến đổi ngược, cộng dự đoán) để làm tham chiếu cho MB sau,
   rồi áp deblocking filter cho cả frame.
7. Đóng gói slice thành NAL, chèn emulation-prevention byte, thêm SPS/PPS/SEI.

Sau khi encode, libx264 in thống kê nội bộ (thấy được với `-loglevel verbose`). Ví dụ
thật từ một lần chạy demo với `data/raw/foreman_cif.y4m`, 8 frame:

```text
frame I:8     Avg QP:19.00  size:  9487        <- 8 frame I, QP trung bình 19, ~9.5 KB/frame
mb I  I16..4: 74.7%  0.0% 25.3%                 <- 74.7% MB là I16x16, 0% I8x8 (không có ở Baseline), 25.3% I4x4
coded y,uvDC,uvAC intra: 15.2% 30.9% 26.2%      <- tỉ lệ khối có hệ số khác 0
i16 v,h,dc,p: 89%  7%  4%  0%                   <- phân bố mode Intra16x16
i4 v,h,dc,ddl,ddr,vr,hd,vl,hu: 48% 25% 18% ...  <- phân bố 9 mode Intra4x4
```

libx264 còn ghi toàn bộ cấu hình của nó vào một NAL SEI loại `user_data_unregistered`,
ví dụ `cabac=0 ref=1 deblock=1:0:0 ... trellis=1 ... deadzone=21,11 ... rc=cqp qp=22 ip_ratio=1.40 aq=0`.
Demo giải mã và in chuỗi này (mục 3.4).

### 2.3. Công cụ để nhìn vào bên trong FFmpeg

| Cần xem | Lệnh | Demo dùng ở |
|---|---|---|
| Từng thành phần của pipeline encode | `ffmpeg -loglevel verbose ...` | `deep_trace.ffmpeg_pipeline` |
| Mọi trường của SPS/PPS/SEI/slice header, kèm vị trí bit | `ffmpeg -i x.h264 -c:v copy -bsf:v trace_headers -f null -` | `deep_trace.library_header_trace` |
| Loại từng MB mà decoder giải ra | `ffmpeg -debug mb_type -i x.h264 -f null -` | `deep_trace.decoder_mb_maps` |
| QP từng MB | `ffmpeg -debug qp -i x.h264 -f null -` | `deep_trace.decoder_mb_maps` |
| Ảnh tái tạo **trước** deblocking | `ffmpeg -skip_loop_filter all -i x.h264 -f rawvideo out.yuv` | `deep_trace.block_anatomy` |
| Thông tin frame/packet | `ffprobe -show_frames -show_packets x.h264` | (thủ công) |

`trace_headers` dùng thư viện CBS (coded bitstream) của libavcodec, độc lập với parser
native; vì vậy demo dùng nó để đối chiếu. Lưu ý `-debug mb_type/qp` in một bản đồ cho
mỗi lần decoder giải một frame, kể cả lần giải thử khi dò định dạng và các thread khác;
demo tách đúng một access unit (SPS+PPS+IDR) rồi giải bằng một thread để có đúng một bản đồ.

### 2.4. Định dạng video thô

`.y4m` (YUV4MPEG2) gồm một dòng header ASCII, ví dụ
`YUV4MPEG2 W352 H288 F10:1 Ip A1:1 C420jpeg`, rồi lặp lại `FRAME\n` + dữ liệu frame.
Với 4:2:0, một frame W×H gồm plane Y (W·H byte), U và V (mỗi plane W/2·H/2 byte):
352×288 → 101 376 + 25 344 + 25 344 = 152 064 byte, cộng 6 byte marker = 152 070 byte.

Mất mát do nén (không phải do nhúng) được demo đo bằng PSNR-Y giữa frame libx264 nhận
(`encoder_input.yuv`) và frame giải ra từ `source.h264`.

---

## 3. Cấu trúc file H.264 Annex-B

### 3.1. Start code và NAL unit

File `.h264` thô là chuỗi NAL unit, mỗi NAL bắt đầu bằng start code `00 00 01` hoặc
`00 00 00 01`. Byte đầu tiên sau start code là **NAL header**:

```text
 bit:   7        6 5         4 3 2 1 0
      forbidden  nal_ref_idc nal_unit_type
```

| `nal_unit_type` | Ý nghĩa |
|---|---|
| 7 | SPS – tham số chuỗi (profile, level, kích thước theo MB, kiểu POC...) |
| 8 | PPS – tham số ảnh (entropy coding, QP khởi đầu, có điều khiển deblocking...) |
| 6 | SEI – thông tin bổ sung (x264 ghi cấu hình encoder ở đây) |
| 5 | Slice IDR – frame tham chiếu tức thời, nơi chứa dữ liệu nhúng |
| 1 | Slice không phải IDR (P-frame khi GOP>1) |

Ví dụ thật (bảng NAL đầu của `source.h264` trong demo):

```text
 NAL   offset start     header   F NRI type  loại          EBSP    RBSP EPB
   0        0 00000001 01100111  0  3     7  SPS              21      20  1
   1       26 00000001 01101000  0  3     8  PPS               4       4  0
   2       35 00 00 01 00000110  0  0     6  SEI             568     568  0
   3      607 00 00 01 01100101  0  3     5  slice IDR      8797    8797  0
```

### 3.2. EBSP, RBSP và emulation-prevention byte

Bên trong NAL, chuỗi `00 00 00`, `00 00 01`, `00 00 02`, `00 00 03` không được xuất hiện,
nếu không decoder sẽ nhầm thành start code. Encoder chèn byte `03` sau mỗi cặp `00 00`
đứng trước byte ≤ 3. Payload có byte chèn gọi là **EBSP**; bỏ các byte đó thu được
**RBSP** (raw byte sequence payload). Mọi offset bit trong parser đều tính trên RBSP.

Ví dụ thật trong SPS: `04 40 00 00 03 00 40 00` → RBSP `04 40 00 00 00 40 00`.

Hệ quả cho việc nhúng: lật một bit trong RBSP có thể tạo hoặc xóa một mẫu `00 00 0x`,
nên khi ghi lại NAL, EPB được tính lại. Độ dài **bit RBSP** không đổi, nhưng độ dài
**byte EBSP** có thể lệch vài byte.

### 3.3. Exp-Golomb

Phần lớn trường header dùng mã Exp-Golomb:

- `ue(v)`: đếm k số 0 đứng đầu, bỏ bit `1`, đọc k bit hậu tố; giá trị = 2^k − 1 + hậu tố.
  `1` → 0, `010` → 1, `011` → 2, `00111` → 6.
- `se(v)`: từ codeNum của `ue`: lẻ → dương `(c+1)/2`, chẵn → âm `−c/2`.
  Ví dụ `slice_qp_delta`: `00111` → codeNum 6 → −3.
- `me(v)`: codeNum `ue` tra bảng 9-4 để ra `coded_block_pattern` (ví dụ codeNum 0 → CBP 47 với intra).

### 3.4. SPS, PPS, slice header (giá trị thật)

Trích từ `trace_headers` của FFmpeg trên clip demo (vị trí bit tính từ đầu NAL, kể cả
8 bit NAL header):

```text
SPS  bit 8   profile_idc                      01000010 = 66 (Baseline)
     bit 39  pic_width_in_mbs_minus1         000010110 = 21  -> 22 MB = 352 px
     bit 48  pic_height_in_map_units_minus1  000010010 = 17  -> 18 MB = 288 px
     bit 57  frame_mbs_only_flag                     1 = 1   (progressive)
PPS  bit 10  entropy_coding_mode_flag                0 = 0   (CAVLC)
     bit 18  pic_init_qp_minus26               0001001 = -4  -> pic_init_qp 22
     bit 26  chroma_qp_index_offset              00101 = -2
     bit 31  deblocking_filter_control_present_flag  1 = 1
IDR  bit 8   first_mb_in_slice                       1 = 0
     bit 9   slice_type                        0001000 = 7   (I, mọi slice trong ảnh cùng loại)
     bit 24  slice_qp_delta                      00111 = -3  -> QP slice = 22 - 3 = 19
     bit 29  disable_deblocking_filter_idc           1 = 0   (deblocking bật)
```

Slice header kết thúc ở bit 32 của NAL, tức bit 24 của RBSP; parser native báo
`data_bit_offset = 24`. Demo kiểm tra hai con số này khớp nhau.

---

## 4. Slice, macroblock và block

### 4.1. Slice data

Sau slice header là chuỗi macroblock theo thứ tự quét raster (trái → phải, trên → dưới),
kết thúc bằng `rbsp_stop_one_bit` = 1 và các bit 0 căn byte. Frame 352×288 có
22 × 18 = 396 MB.

### 4.2. Header của một MB trong I-slice

```text
mb_type                          ue(v)   0 = I_NxN (I4x4), 1..24 = I_16x16, 25 = I_PCM
nếu I4x4:
  16 lần: prev_intra4x4_pred_mode_flag  u(1)
          rem_intra4x4_pred_mode         u(3)   (chỉ khi flag = 0)
intra_chroma_pred_mode           ue(v)   0 DC, 1 Horizontal, 2 Vertical, 3 Plane
coded_block_pattern              me(v)   chỉ với I4x4; I16x16 suy CBP từ mb_type
mb_qp_delta                      se(v)   khi CBP > 0 hoặc với I16x16
```

Với I16x16, `mb_type` mã hóa cả mode dự đoán 16×16 (`(mb_type−1) % 4`), CBP chroma
(`((mb_type−1)/4) % 3`) và CBP luma (15 nếu `mb_type ≥ 13`).

`coded_block_pattern` (CBP): 4 bit thấp cho 4 khối luma 8×8 (bit = 1 → khối 8×8 đó có
residual), 2 bit cao cho chroma (0: không, 1: chỉ DC, 2: DC + AC).

**QP của từng MB**: `QP_Y = (QP_trước + mb_qp_delta + 52) mod 52`, bắt đầu từ QP slice.
Với CQP và `aq=0`, mọi `mb_qp_delta` = 0 nên QP mọi MB = 19 (demo đối chiếu với bản đồ
QP do decoder FFmpeg in ra, 396/396 khớp).

Ví dụ thật, header MB 280 (đọc lại từng bit bởi `demo/h264_explain.py`):

```text
 bit    len chuỗi bit  phần tử = giá trị
 48847   1  1          mb_type = 0                         (I4x4)
 48848   1  1          prev_intra4x4_pred_mode_flag[0] = 1
 48850   1  0          prev_intra4x4_pred_mode_flag[2] = 0
 48851   3  001        rem_intra4x4_pred_mode[2] = 1
 ...
 48888   1  1          intra_chroma_pred_mode = 0
 48889   1  1          coded_block_pattern = 47            (me: codeNum 0; luma 1111, chroma 2)
 48890   1  1          mb_qp_delta = 0
```

### 4.3. Khối 4×4 và thứ tự giải mã

Một MB I4x4 có 16 khối luma 4×4, đánh số `luma4x4BlkIdx` theo zig-zag của khối 8×8:

```text
 0  1 |  4  5
 2  3 |  6  7
------+------
 8  9 | 12 13
10 11 | 14 15
```

Vị trí (x, y) tính theo đơn vị 4 mẫu: `x = (idx/4 % 2)·2 + idx % 2`, `y = (idx/8)·2 + (idx/2) % 2`.

Residual của MB gồm các loại khối: `LumaDC` (chỉ I16x16, 16 hệ số DC qua Hadamard),
`Luma4x4` (16 hệ số; với I16x16 là 15 hệ số AC), `ChromaDC` (2×2 cho mỗi plane U/V) và
`ChromaAC` (15 hệ số mỗi khối, 8 khối).

---

## 5. Dự đoán intra, biến đổi và lượng tử hóa

### 5.1. Mode Intra4x4 của mỗi khối

Mode của khối không được ghi trực tiếp. Decoder suy ra (mục 8.3.1.1 của chuẩn):

1. Lấy mode của khối bên trái A và khối bên trên B (có thể ở MB lân cận).
2. Nếu A hoặc B không tồn tại → mode dự đoán = 2 (DC). Nếu MB lân cận là I16x16 → coi mode = 2.
3. Ngược lại mode dự đoán = min(A, B).
4. Nếu `prev_intra4x4_pred_mode_flag = 1` → dùng mode dự đoán; ngược lại
   mode = `rem` nếu `rem < dự đoán`, ngược lại `rem + 1`.

9 mode: 0 Vertical, 1 Horizontal, 2 DC, 3 Diagonal_Down_Left, 4 Diagonal_Down_Right,
5 Vertical_Right, 6 Horizontal_Down, 7 Vertical_Left, 8 Horizontal_Up. Mỗi mode là một
công thức trên 13 mẫu lân cận: `p[−1,−1]`, hàng trên `p[0..7,−1]` (4 mẫu bên phải là khối
C trên-phải; nếu C chưa giải mã thì lặp lại `p[3,−1]`), cột trái `p[−1,0..3]`.

**Quan trọng**: dự đoán intra dùng mẫu **trước** deblocking. Vì vậy demo giải mã bằng
`-skip_loop_filter all` để có đúng các mẫu đó và tái tạo pixel chính xác đến từng giá trị.

### 5.2. Biến đổi nguyên 4×4 (chiều encoder)

Residual 4×4 `X` được biến đổi bằng ma trận nguyên `Cf`:

```text
      | 1  1  1  1 |
Cf =  | 2  1 -1 -2 |        W = Cf · X · Cf^T
      | 1 -1 -1  1 |
      | 1 -2  2 -1 |
```

Đây là xấp xỉ nguyên của DCT; phần chuẩn hóa (scaling) được gộp vào lượng tử hóa.

### 5.3. Lượng tử hóa (chiều encoder, giáo khoa)

`|Z| = (|W| · MF(QP%6, i, j) + f) >> qbits`, với `qbits = 15 + QP/6`,
`f = 2^qbits / 3` cho intra. `MF` phụ thuộc vị trí theo tính chẵn lẻ (i, j):

| QP%6 | (chẵn, chẵn) | (lẻ, lẻ) | còn lại |
|---|---|---|---|
| 0 | 13107 | 5243 | 8066 |
| 1 | 11916 | 4660 | 7490 |
| 2 | 10082 | 4194 | 6554 |
| 3 | 9362 | 3647 | 5825 |
| 4 | 8192 | 3355 | 5243 |
| 5 | 7282 | 2893 | 4559 |

x264 dùng thêm dead-zone, trellis và psy-RD nên mức thật trong bitstream có thể khác
công thức này. Demo in cả hai và đếm số vị trí trùng; **giá trị trong bitstream mới là sự thật**.

### 5.4. Giải lượng tử và biến đổi ngược (chiều decoder, chuẩn bắt buộc)

Giải lượng tử (8.5.12.1), với Baseline dùng ma trận scaling phẳng:

```text
LevelScale(m, i, j) = 16 · normAdjust(m, i, j)
normAdjust(m): (chẵn,chẵn) | (lẻ,lẻ) | còn lại  = (10,16,13) (11,18,14) (13,20,16) (14,23,18) (16,25,20) (18,29,23)

QP >= 24: d = (c · LevelScale) << (QP/6 − 4)
QP <  24: d = (c · LevelScale + 2^(3 − QP/6)) >> (4 − QP/6)
```

Biến đổi ngược (8.5.12.2): áp biến đổi 1 chiều lên từng **hàng** rồi từng **cột**:

```text
e0 = d0 + d2        e1 = d0 − d2
e2 = (d1 >> 1) − d3 e3 = d1 + (d3 >> 1)
f  = [e0 + e3, e1 + e2, e1 − e2, e0 − e3]
r  = (h + 32) >> 6                      (h = kết quả sau hai chiều)
pixel = clip(0..255, dự đoán + r)
```

### 5.5. Ví dụ thật, đi hết một khối

Lấy từ một lần chạy `terminal_demo.py`: frame #6, MB 280, khối `luma4x4BlkIdx` 2, pixel (256, 196).

```text
Mode: A = MB 279 (mode 2), B = khối 0 cùng MB (mode 2) -> dự đoán 2; rem = 1 < 2 -> mode 1 Horizontal
Hệ số (scan zig-zag) trước nhúng: [2, -1, 0, ...]      -> -1 là trailing-one
Ma trận c:        [[2,-1,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]]
QP 19: LevelScale hàng đầu [176, 224, 176, 224]; d = (c·LS + 1) >> 1
d trước:          [[176,-112,0,0], 0...]      d sau (dấu lật): [[176,112,0,0], 0...]
Sau biến đổi hàng: [64, 120, 232, 288] (hàng 0); sau cột: lặp lại cho 4 hàng
residual trước:   [1, 2, 4, 5] mỗi hàng       residual sau: [5, 4, 2, 1] mỗi hàng
Dự đoán Horizontal: cột trái p[-1,0..3] = 83 -> mọi mẫu = 83
Tái tạo trước:    83 + [1,2,4,5] = [84, 85, 87, 88] mỗi hàng   (khớp FFmpeg từng mẫu)
Chiều encoder: X gốc hàng [85,85,87,87]; e = X - 83 = [2,2,4,4]; W hàng 0 = [48,-24,0,8]
               lượng tử giáo khoa -> [[2,-1,0,0],...]  (khớp 16/16 với bitstream)
```

Sau khi nhúng, pixel đổi `[6, 4, 0, −2]` mỗi hàng = Δdự đoán `[2, 2, 2, 2]` + Δresidual
`[4, 2, −2, −4]`. Δdự đoán khác 0 vì cột mẫu bên trái (thuộc MB 279) đã đổi do một lần
lật dấu giải mã trước đó: ảnh hưởng **lan truyền** qua dự đoán intra.

---

## 6. Mã hóa entropy CAVLC

Mỗi khối residual được mã thành 5 loại phần tử, đúng thứ tự (mục 9.2):

| Phần tử | Nội dung |
|---|---|
| `coeff_token` | Cặp (TotalCoeff, TrailingOnes): số hệ số khác 0 và số hệ số ±1 ở cuối (tối đa 3). Bảng VLC chọn theo nC |
| `trailing_ones_sign_flag` | Mỗi trailing-one 1 bit dấu: 0 → +1, 1 → −1. **Đây là kênh nhúng** |
| `level` | Các hệ số còn lại, giải theo thứ tự **ngược** scan; `level_prefix` (đếm số 0) + `level_suffix` (độ dài thích nghi `suffixLength`) |
| `total_zeros` | Tổng số 0 đứng trước hệ số khác 0 cuối cùng (bỏ qua nếu TotalCoeff = số hệ số tối đa) |
| `run_before` | Số 0 ngay trước mỗi hệ số, tra bảng theo `zerosLeft` |

**nC** = trung bình TotalCoeff của khối bên trái (nA) và bên trên (nB), làm tròn lên;
nếu chỉ có một bên thì lấy bên đó; không có bên nào thì 0. ChromaDC dùng nC = −1.
Bảng coeff_token: 0 ≤ nC < 2, 2 ≤ nC < 4, 4 ≤ nC < 8, và nC ≥ 8 dùng mã cố định 6 bit
`xxxxyy` = (TotalCoeff−1, TrailingOnes), `000011` nghĩa là không có hệ số.

Ví dụ thật từ demo (khối có nC = 4, bảng 4 ≤ nC < 8):

```text
 bit    len chuỗi bit  phần tử = giá trị
 34636   4  1110       coeff_token = (1, 1)            TotalCoeff 1, TrailingOnes 1
 34640   1  1          trailing_ones_sign_flag[0] = 1  -> hệ số -1   <== BIT NHÚNG
 34641   3  011        total_zeros = 1
sau khi nhúng: bit 34640 = 0 -> hệ số +1; mọi bit khác giữ nguyên
```

Python (`demo/h264_explain.py`) đọc lại độc lập từng phần tử, và kiểm tra rằng việc đọc
dừng đúng ở bit kết thúc do parser native báo, với cùng các giá trị level và dấu.

---

## 7. Kênh nhúng: dấu của hệ số trailing-one

### 7.1. Vì sao chọn dấu trailing-one

Lật bit `trailing_ones_sign_flag`:

- **Không đổi độ dài mã**: chỉ 1 bit cố định thay giá trị; mọi phần tử sau giữ nguyên vị trí.
- **Không đổi ngữ cảnh**: TotalCoeff, TrailingOnes không đổi nên nC của các khối sau, bảng
  VLC được chọn và toàn bộ cú pháp phía sau giữ nguyên. Bitstream vẫn hợp lệ.
- **Thay đổi pixel nhỏ**: một hệ số đổi từ ±1 sang ∓1 (Δ = ±2 ở mức lượng tử).

### 7.2. Ứng viên

`collect_cavlc_trailing_one_sign_candidates` (native) lấy **một ứng viên mỗi khối**:
dấu trailing-one **đầu tiên** của khối, thuộc mọi loại khối (LumaDC, Luma4x4, ChromaDC,
ChromaAC) trong các slice IDR. Mỗi ứng viên có định danh:

```text
nal_index : macroblock_address : category : block_index : rbsp_bit_offset
ví dụ "24:326:1:6:67801"   (category 1 = Luma4x4)
```

Dung lượng của một clip = số ứng viên. Ví dụ clip demo 8 frame CIF, QP 22, GOP 1 có
3 660 ứng viên; một message 19 byte cần 1 368 bit (khung 171 byte), dùng khoảng 37%.

### 7.3. Tác động lên ảnh

Đổi một hệ số → giải lượng tử → biến đổi ngược ra một residual 4×4 thay đổi
(xem ví dụ mục 5.5) → các khối giải mã sau dùng mẫu này để dự đoán nên sai khác lan
truyền trong frame → deblocking làm mịn biên → với GOP>1, P-frame tham chiếu frame
này cũng bị ảnh hưởng. Demo đo PSNR từng plane Y/U/V và in bản đồ |ΔY|.

---

## 8. Lịch nhúng có khóa (keyed schedule)

Vị trí nhận từng bit không cố định mà do khóa quyết định, để chỉ người có khóa đọc được.
Mỗi vai trò dùng một khóa con riêng, sinh bằng HKDF-SHA256 (RFC 5869) từ khóa giấu tin
32 byte. Từ giao thức v3 (2026-10-04) chỉ còn hai khóa con; nhãn HKDF giữ nguyên như v2 nên
lịch và dòng làm trắng không đổi:

```text
PRK           = HMAC-SHA256( key = "zkstego-cavlc-v2-salt", msg = secret )        (HKDF-Extract)
schedule_key  = HKDF-Expand( PRK, "zkstego/cavlc/v2/schedule",  32 )
whitening_key = HKDF-Expand( PRK, "zkstego/cavlc/v2/whitening", 32 )

score(candidate) = HMAC-SHA256( schedule_key , định danh ASCII của ứng viên )
Sắp xếp ứng viên tăng dần theo (score, định danh); lấy N ứng viên đầu.
Bit thứ i của khung (MSB trước) gán cho ứng viên thứ i, SAU KHI làm trắng (mục 9.1):
bit nhúng 0 -> dấu +, 1 -> dấu −.
```

Lộ một khóa con (ví dụ khóa lịch) không làm lộ secret hay khóa con còn lại. Ở đây HMAC chỉ
đóng vai hàm giả ngẫu nhiên có khóa (chọn vị trí, sinh dòng làm trắng), không còn dùng để xác thực.

Native: `score_keyed_cavlc_sign_candidate`, `select_keyed_cavlc_sign_candidates`;
Python tham chiếu: `src/native_blind_contract.py` (cùng ABI, có test vector chéo ngôn ngữ).

Chỉ có một giao thức, **theo đoạn** (segment), dùng chung cho file, job HTTP và luồng live:
mỗi đoạn = SPS+PPS+1 IDR; mỗi đoạn nhúng tối đa `max_bits_per_IDR` bit (N = min(giới hạn,
số ứng viên của đoạn), chọn theo lịch HMAC của đoạn đó); khung trải qua nhiều IDR liên tiếp,
chỉ số bit khung đếm liên tục qua các đoạn. Định danh ứng viên tính theo đầu vào của đoạn
(SPS+PPS+IDR), không theo vị trí trong file. `zkstego_inspect --segments` liệt kê ứng viên
từng đoạn và `src.native_blind_contract.segment_schedule` tái tạo đúng lịch của encoder.

Bên nhận phải dùng cùng `max_bits_per_IDR`, nếu không lịch lệch và trích sai.

---

## 9. Khung kênh và trích xuất mù

### 9.1. Khung

```text
[version = 0x03 : 1 byte][payload_len : 2 byte big-endian][payload]          (không có MAC)

Làm trắng (whitening):
keystream    = HMAC-SHA256(whitening_key, uint64_be(0)) ‖ HMAC-SHA256(whitening_key, uint64_be(1)) ‖ ...
bit_nhúng[i] = bit_khung[i] XOR bit_keystream[i]      (i đánh số trên toàn khung, kể cả khi trải nhiều IDR)
```

Không làm trắng thì byte version cố định, trường độ dài nhỏ và cấu trúc proof làm thống kê
dấu tại các vị trí được chọn bị lệch. Sau khi XOR với dòng khóa giả ngẫu nhiên, các bit
nhúng phân bố như ngẫu nhiên đối với người không có khóa.

Payload tối đa 4096 byte ở các lệnh stdin (giới hạn cấu hình); định dạng cho phép tới 65 535.

**Vì sao bỏ thẻ HMAC (v3).** Ở v2 khung mang thêm 16 byte `HMAC(frame_key, header ‖ payload)`.
Khi Groth16 verify đã là bắt buộc, thẻ này trùng việc: sửa message thì proof sai, sửa proof thì
proof không hợp lệ, proof tạo bằng secret khác cũng bị từ chối. Bỏ thẻ tiết kiệm 128 bit
(2 IDR ở 64 bit/IDR). Khóa sai vẫn bị loại rẻ ở bước kiểm header (xem 9.2) hoặc khi giải nén
proof; phần còn sót bị Groth16 từ chối. Hệ quả: kênh không còn tự phát hiện bit payload bị
sửa, nên **chỉ job verify** (Groth16) mới xác thực payload; lệnh/job extract trả payload kèm
`"verified": false`. v3 không đọc được stego v2 (byte version khác) và ngược lại.

### 9.2. Trích xuất mù

"Mù" nghĩa là bên nhận **không cần video gốc** và không cần file phụ (sidecar):

1. Parse lại các IDR của video stego, liệt kê ứng viên (giống hệt phía gửi vì lật dấu
   không đổi cấu trúc).
2. Dùng cùng secret sinh lại các khóa con, tính score, sắp xếp, đọc bit tại các vị trí đã chọn.
3. Bỏ làm trắng 24 bit đầu → kiểm version = 3 và độ dài ≤ giới hạn → biết tổng số bit cần đọc.
   Sai khóa thì byte version sau khi bỏ làm trắng gần như ngẫu nhiên nên bị từ chối ngay
   (lọt qua cả version lẫn độ dài với xác suất cỡ 1/256 × giới hạn/65 536).
4. Đọc đủ khung và bỏ làm trắng → payload. Payload này **chưa được xác thực**: bên gọi phải
   unpack và verify Groth16 (job verify của dịch vụ làm việc này).

Thông báo lỗi native tương ứng (mọi trường hợp đều thoát mã 2):

| Thông báo | Khi nào |
|---|---|
| `CAVLC frame/stream version is invalid` | Byte đầu (sau khi bỏ làm trắng) khác `0x03` (thường do sai khóa, hoặc stego v2) |
| `CAVLC frame/stream length exceeds configured maximum`, `CAVLC frame length is invalid` | Trường độ dài vượt giới hạn hoặc không khớp |
| `blind schedule capacity is insufficient` | Lịch cần nhiều bit hơn số ứng viên của đoạn |
| `IDR stream ended before payload was complete`, `... ended before payload capacity was met`, `CAVLC stream is incomplete` | Chế độ theo đoạn: hết video trước khi đọc đủ khung |

Tìm thấy khung chỉ có nghĩa là có dữ liệu ở đúng vị trí theo khóa; **không** chứng minh payload
nguyên vẹn. Việc đó thuộc về proof Groth16 (mục 10).

---

## 10. Payload và proof Groth16 (camera trong sổ đăng ký + ràng buộc video)

Từ 2026-10-04 proof chứng minh: **"một camera nằm trong sổ đăng ký (gốc Merkle công khai)
xác nhận đúng video này và message này"**, mà bên kiểm chứng không cần secret của camera và
không biết camera nào. Hai khóa được tách hẳn:

| Khóa | Ai giữ | Dùng để |
|---|---|---|
| Khóa giấu tin K (32 byte) | Người gửi và bên kiểm chứng | Chọn vị trí nhúng và làm trắng bit (mục 8, 9) |
| Secret camera s (phần tử trường BN254) | Chỉ camera | Tạo proof; sổ đăng ký chỉ lưu pk = Poseidon(s) |

### 10.1. Sổ đăng ký camera

`src/camera_registry.py`: cây Merkle nhị phân độ sâu 16 (tối đa 65 536 camera), nút
`Poseidon(trái, phải)`, lá trống = 0, lá i = `pk_i = Poseidon(s_i)`. Poseidon cài bằng Python
(`src/poseidon.py`, hằng số của circomlib) và đã được đối chiếu với vector chuẩn của
circomlibjs và với witness của chính mạch. Bên kiểm chứng chỉ tin **gốc** (root) của cây.

### 10.2. Hash video và binding

`zkstego_blind_bits video-digest` (bản tham chiếu: `src/video_binding.py`):

```text
frame_bits = 8 × (3 + kích thước payload)                 (biết trước khi tạo proof)
carrier    = đúng frame_bits vị trí dấu mà lịch HMAC theo khóa giấu tin sẽ ghi khung vào
             (mỗi IDR: min(cap, ứng viên) vị trí đầu của lịch, cho tới hết khung)
digest     = SHA256("zkstego/video-digest/v1" ‖ u32(frame_bits) ‖ u32(cap) ‖
                    với mọi NAL theo thứ tự: u32(1 + len(rbsp')) ‖ header ‖ rbsp')
rbsp'      = RBSP của NAL (đã bỏ EPB), CHỈ các bit carrier được đặt về 0
binding    = SHA256("zkstego/proof-binding/v1" ‖ mode ‖ digest ‖ SHA256(message))
bindingHi, bindingLo = hai nửa 128 bit của binding  (public input của mạch)
```

Nhúng chỉ đổi đúng các bit carrier (và có thể thêm/bớt byte EPB, không ảnh hưởng RBSP), nên
**digest của cover = digest của stego**. Mọi thay đổi khác — video khác, cắt hay thêm frame,
sửa một bit ở frame sau, lật một bit dấu không mang khung, mã hóa lại — làm digest đổi và proof
không còn đúng. Lật một bit carrier thì digest giữ nguyên nhưng payload trích ra đổi, nên proof
cũng bị từ chối. Vị trí carrier phụ thuộc khóa giấu tin; bên kiểm chứng vốn đã có khóa này để trích. Chế độ `mode = 1`
(chỉ ràng buộc message, digest = 0) dành cho luồng live, vì khi nhúng proof thì phần còn lại
của video chưa tồn tại; job verify từ chối chế độ này trừ khi bật
`ZK_STEGO_ALLOW_MESSAGE_ONLY_PROOFS=1`.

### 10.3. Mạch `circuits/camera_video.circom`

```text
private: secret s; siblings[16]; pathIndices[16]
public : root, bindingHi, bindingLo
ràng buộc: pk = Poseidon(s); đường Merkle (pathIndices là bit) từ pk dẫn tới root;
           bindingHi, bindingLo nằm trong R1CS (bình phương) để gắn vào proof
```

8 737 constraint, 3 public input (mạch SHA-256 cũ: 63 321 constraint, 513 public input).
Proof tạo cho một binding (video + message) hay một root khác đều không verify được.

### 10.4. Payload

```text
[format 0x01][mode 1B][message_length BE16][message][proof nén 129B]
```

Khung kênh thêm 3 byte, nên message tối đa 4096 − 4 − 129 = 3963 byte.

### 10.5. Groth16, nén proof và setup

`src/zk_proof.py` (`CameraProofBridge`) gọi snarkjs: witness bằng WASM của mạch, rồi
`groth16 prove` với `camera_video.zkey`. Proof gồm A ∈ G1, B ∈ G2, C ∈ G1 trên BN254, nén
còn 129 byte (tọa độ x của A, B (2 phần tử Fp2), C, mỗi phần 32 byte, cộng 1 byte cờ y).
`bytes_to_proof` kiểm tra tọa độ < p và điểm nằm trên đường cong. Xác minh chỉ chấp nhận khi
`snarkjs groth16 verify` **thoát mã 0 và in `OK!`**.

Setup (`py -3.12 -m src.zk_setup`): Phase 1 là Powers of Tau công khai của Hermez (2^16);
Phase 2 gồm 2 lượt đóng góp (entropy qua stdin), một beacon ngẫu nhiên công khai, rồi
`snarkjs zkey verify`; transcript ở `circuits/build/camera_video_setup.json`. Vì cả hai lượt
chạy trên một máy nên đây là nghi thức **demo**; triển khai thật cần nhiều bên độc lập (chỉ
cần một bên trung thực là khóa an toàn).

Luồng: phía gửi tính digest của cover → binding → proof → payload → nhúng
(`src/camera_proof.build_payload`); phía nhận trích → tính digest của file nhận được →
binding → verify với root tin cậy (`src/camera_proof.verify_payload`, job verify).

### 10.6. Proof chứng minh gì, không chứng minh gì

- Chứng minh: một camera có khóa trong sổ đăng ký đã xác nhận đúng video (mọi bit, các bit carrier
  được bảo vệ gián tiếp qua payload) và message; không lộ camera nào; bên kiểm chứng không làm giả
  được proof.
- Không chứng minh: camera thật sự quay cảnh đó (ví dụ quay lại màn hình); setup Groth16 Phase 2
  là demo (beacon cục bộ, không phải beacon công khai).

---

## 11. Luồng đầu-cuối và giao diện dòng lệnh native

### 11.1. Gửi

1. Encode video về Baseline/CAVLC (mục 2).
2. `src.camera_proof.build_payload(bridge, registry, camera_secret, message, native_cli=..., cover=...)`:
   `video-digest` của cover → binding → Groth16 proof → `pack_payload` (payload).
4. `zkstego_blind_bits embed-stream-auth-stdin in.h264 out.h264 <max_bits_per_IDR>`,
   stdin: dòng 1 = khóa 64 ký tự hex, dòng 2 = payload hex.

### 11.2. Nhận

1. `zkstego_blind_bits extract-stream-auth stego.h264 - <max_payload> <max_bits_per_IDR>`,
   stdin: khóa hex. stdout: payload hex (chưa xác thực; verify Groth16 ở bước sau).
2. `src.camera_proof.verify_payload(bridge, root, payload, native_cli=..., stego=...)`: `unpack_payload`
   → `bytes_to_proof` → `video-digest` của chính file nhận được → binding → Groth16 verify với
   root tin cậy → chỉ khi đúng (và `video_bound`) mới dùng message. Không cần secret camera.

### 11.3. Các lệnh của `zkstego_blind_bits`

| Lệnh | Mục đích |
|---|---|
| `embed-stream-auth-stdin`, `extract-stream-auth` | Khung kênh v3 (hậu tố `-auth` nghĩa là "có khóa"; khung không có MAC), lịch theo đoạn IDR, đọc/ghi file |
| `video-digest` | Hash ràng buộc video (stego key qua stdin để xác định bit carrier); cover và stego cho cùng giá trị |
| `measure-live-capacity-stdin` | Đọc Annex-B từ stdin, in JSON dung lượng ứng viên |
| `embed-live-auth-stdin`, `extract-live-auth-stdin` | Như chế độ đoạn nhưng video vào/ra qua stdin/stdout (dùng cho WebSocket) |

Khóa không bao giờ đi qua tham số dòng lệnh. Mã thoát 2 = mọi lỗi (sai khóa, lỗi parse, lỗi I/O).
Công cụ soi duy nhất: `zkstego_inspect` — mặc định xuất JSON NAL/slice/ứng viên;
`--summary` in tóm tắt dễ đọc; `--macroblock NAL MB` xuất toàn bộ header MB của slice và
từng phần tử CAVLC của một MB; `--segments MAX_BITS` liệt kê ứng viên theo đoạn.

---

## 12. Dịch vụ HTTP/WebSocket

Một ứng dụng: `src.api.native_handlers:create_native_app` dựng trên lõi job dùng chung
`src.api.app.create_app` (xác thực, giới hạn, hàng đợi, lưu trữ job).

| Endpoint | Mô tả |
|---|---|
| `GET /health` | Công khai |
| `POST /api/v1/jobs/embed` | Upload `.h264` + `message_b64` + `secret_key_b64` → job id |
| `POST /api/v1/jobs/extract` | Upload stego + khóa → job id (native) |
| `POST /api/v1/jobs/verify` | Trích mù → unpack → hash video của file tải lên → **Groth16 verify bắt buộc** với root của sổ đăng ký (`ZK_STEGO_CAMERA_REGISTRY`). `succeeded` kèm message và `video_bound` chỉ khi proof đúng; ngược lại `rejected` với lý do `payload_not_found` / `malformed_proof_payload` / `video_binding_required` / `video_digest_unavailable` / `proof_invalid`; lỗi hạ tầng (thiếu sổ đăng ký, khóa, Node.js) → `failed` |
| `GET /api/v1/jobs/{id}` | Trạng thái job |
| `GET /api/v1/jobs/{id}/artifact` | Tải kết quả **một lần**, hết hạn sau 10 phút |
| `WS /api/v1/stream` | Khung JSON start, rồi các chunk Annex-B nhị phân |

Trạng thái job: `queued`, `running`, `succeeded`, `rejected` (job verify có proof
không hợp lệ — không được coi là thành công), `failed`.

Bảo vệ: Bearer token (`ZK_STEGO_API_TOKEN`, bắt buộc, tối thiểu 32 ký tự) được kiểm
**trước khi đọc body**, kể cả khi chạy sau proxy với `--root-path`; 10 lần xác thực sai
từ một IP trong 60 s → `429` kèm `Retry-After` (cả HTTP lẫn WebSocket);
tối đa 4 upload đồng thời; giới hạn kích thước và thời gian upload
(`ZK_STEGO_API_UPLOAD_TIMEOUT_SECONDS`, mặc định 120 s); hàng đợi job có giới
hạn (mặc định 1 worker + 2 chờ); WebSocket bị từ chối trước khi accept nếu thiếu token,
đóng sau `ZK_STEGO_STREAM_IDLE_TIMEOUT_SECONDS` (15 s) không có dữ liệu; job đã xong
bị xóa sau `ZK_STEGO_API_JOB_RETENTION_SECONDS` (24 h); `/docs` chỉ bật khi `ZK_STEGO_API_DOCS=1`.
Tiến trình native được gọi không qua shell, có timeout, stderr được đọc liên tục.

---

## 13. Bộ lập lịch realtime

`src/realtime_cavlc.py` (`RealtimeCAVLCScheduler`) mô phỏng việc xử lý từng đoạn IDR:
hàng đợi có giới hạn theo số đoạn và số byte (bỏ đoạn cũ nhất khi đầy), epoch tăng đơn
điệu, cache proof tối đa 4 epoch. Báo cáo gồm số đoạn bị bỏ, số đoạn lỗi
(`failed_segments`), p95 thời gian patch, p95 độ trễ đầu-cuối từ lúc nhận đoạn và p95
thời gian tạo proof. `accepted` chỉ đúng khi không có đoạn lỗi và p95 trong ngân sách
của một frame. Kết quả đo camera thật hiện **chưa** đạt cổng 30 FPS (xem `README.md`).

---

## 14. Một lõi media (nhánh Python cũ đã gỡ)

Trước 2026-10-03 repository có thêm một pipeline Python song song (`src/embedder.py`,
`src/verifier*.py`, `src/core/`, `src/bitstream/`, benchmark SEC1–SEC10): parser CAVLC
bằng Python, bộ lọc vị trí, chaos map, file phụ `positions.json`. Nó chậm, cần file phụ
hoặc video gốc và trùng chức năng với lõi native, nên đã bị gỡ (khoảng 18 000 dòng, vẫn
xem được trong lịch sử git). Thứ còn lại từ nó: các bảng VLC chuẩn (`src/h264_tables.py`,
dùng cho phần giải thích của demo), schema manifest có chữ ký (`src/manifest.py`) và
chứng chỉ khóa có hạn (`src/key_policy.py`).

---

## 15. Demo và cách đọc kết quả debug

### 15.1. `demo/terminal_demo.py`

```powershell
py -3.12 demo/terminal_demo.py --auto --message "Xin chao"          # đầy đủ, có giải thích sâu
py -3.12 demo/terminal_demo.py --auto --brief --no-service          # bỏ giải thích sâu và bước HTTP/WebSocket
py -3.12 demo/terminal_demo.py --auto --frames 48 --gop 12          # có P-frame
py -3.12 demo/terminal_demo.py --setup                              # build native + setup Groth16 cục bộ
```

Các bước (số thứ tự in trên terminal):

| Bước | Nội dung | Kiểm tra tự động |
|---|---|---|
| Preflight | Công cụ, artifact mạch, phạm vi demo | Thiếu gì thì dừng |
| Chọn video, encode | Header Y4M, lệnh FFmpeg | — |
| Bên trong FFmpeg/libx264 | Từng thành phần pipeline từ log verbose; thống kê x264; ASCII và số của frame chưa nén; PSNR do nén | — |
| Parser native | Bảng NAL, slice IDR, số ứng viên mỗi IDR | — |
| Cắt NAL, EBSP→RBSP, header qua FFmpeg | Byte NAL header theo bit, ví dụ EPB, chuỗi cấu hình x264 trong SEI, toàn bộ SPS/PPS/slice header do `trace_headers` giải | độ rộng, QP, vị trí bắt đầu slice data khớp native |
| Camera + hash video + proof | Sổ đăng ký 4 camera, mở đường Merkle 16 tầng từ pk tới root; bảng từng NAL của hash video (EBSP/RBSP, số bit carrier bị xóa, SHA256(rbsp′)); binding, witness, proof JSON, cấu trúc 129 byte | Poseidon từng tầng ra đúng root; digest Python = digest native |
| Dung lượng theo đoạn, lịch | Dẫn xuất khóa HKDF (giá trị khóa con chỉ hiện trên terminal), khung v3, giới hạn bit/IDR, bảng IDR nào mang khoảng bit khung nào, score HMAC, bit khung ⊕ keystream = bit nhúng, bit cũ/mới | lịch Python (`segment_schedule`) khớp encoder native |
| Nhúng native | Bản đồ MB, khối ví dụ trước/sau | danh tính ứng viên, bit, metadata không đổi |
| FFmpeg decode | ASCII trước/sau, bản đồ ΔY, PSNR Y/U/V | số frame, ánh xạ 1 slice/frame |
| Giải phẫu một khối | Xem 15.2 | khớp FFmpeg và native ở từng bước |
| Bit nhúng nằm ở đâu | Định danh ứng viên, score HMAC, thứ hạng → chỉ số bit trong khung → trường mang bit (version/độ dài/header payload/message/A.x/B.x/C.x/cờ dấu) → byte RBSP → byte EBSP (đếm EPB) → offset trong file, hex trước/sau, vị trí MB trên frame ASCII | bit trong file source khớp trace; bit trong stego = bit khung XOR bit keystream |
| Verifier | Trích xuất mù, kiểm header khung, hash video tính lại từ stego, Groth16 bắt buộc với root sổ đăng ký; bên nhận tự dựng lại cùng lịch | digest stego = digest cover, proof hợp lệ, message khớp |
| Ca từ chối | Đổi message, proof sai, thiếu proof, sai khóa, lật một bit carrier ngay trong byte file, lật một bit dấu không mang khung (payload giữ nguyên, digest đổi), cắt frame cuối, replay nguyên payload sang clip khác, camera ngoài sổ đăng ký | đều bị từ chối đúng lý do |
| Job HTTP | Embed (output trùng từng byte với CLI), extract, verify → `succeeded`; verify sai khóa → `rejected`; trạng thái và độ trễ | khớp payload và message |
| Luồng WebSocket | Gửi Annex-B theo chunk, nhận stego, giải mã và trích lại | stego trùng CLI, payload khớp |

### 15.2. Phần "Giải phẫu một khối"

| Mục | Hiển thị | Đối chiếu với |
|---|---|---|
| [0] | Bản đồ loại MB và QP toàn frame | decoder FFmpeg (`-debug mb_type`, `-debug qp`) |
| [a] | Header MB đọc lại từng bit | giá trị parser native |
| [b] | Mode Intra4x4 của 16 khối và cách suy ra mode của khối được chọn | (dùng ở [g]) |
| [c] | Từng phần tử CAVLC của khối, trước và sau nhúng, đánh dấu bit nhúng | level/dấu của native, bit kết thúc |
| [d] | Thứ tự zig-zag, ma trận hệ số trước/sau/Δ | — |
| [e] | Chuỗi tính QP, LevelScale, hệ số giải lượng tử | — |
| [f] | Biến đổi ngược: sau hàng, sau cột, residual; Δresidual | — |
| [g] | Mẫu lân cận chưa deblock, ma trận dự đoán, tái tạo | **từng mẫu** ảnh FFmpeg `-skip_loop_filter all`, cả trước và sau nhúng |
| [h] | Ảnh hưởng của deblocking | ảnh FFmpeg bình thường |
| [i] | Chiều encoder: ảnh gốc → residual → W → lượng tử giáo khoa | số vị trí trùng với bitstream |
| [j] | 16×16 mẫu của MB, đánh dấu khối | — |

Mọi kiểm tra in `[PASS]`/`[FAIL]`; một `[FAIL]` dừng demo với mã thoát 1.

### 15.3. Artifact trong `demo/runs/terminal_<thời gian>_<ngẫu nhiên>/`

| File | Nội dung |
|---|---|
| `transcript.txt`, `report.json` | Toàn bộ thuyết minh (secret bị che), kết quả kiểm tra, thời gian |
| `encode.stderr` | Log verbose đầy đủ của FFmpeg/libx264 |
| `encoder_input.yuv`, `source_decoded.yuv` | Frame libx264 nhận và frame giải ra từ `source.h264` |
| `nal_anatomy.json` | Mọi NAL: offset, start code, header, vị trí EPB |
| `ffmpeg_trace_headers.txt` | Toàn bộ output `trace_headers` |
| `access_unit_nal<N>.h264`, `ffmpeg_debug_*.stderr` | Access unit đã tách và bản đồ MB của decoder |
| `trace_before.json`, `trace_after.json` | Mọi NAL, slice, ứng viên, bit dấu, hệ số |
| `mb_detail_before.json`, `mb_detail_after.json` | Header mọi MB của slice và từng phần tử CAVLC của MB ví dụ |
| `nodeblock_before.yuv`, `nodeblock_after.yuv`, `before.yuv`, `after.yuv` | Ảnh giải mã chưa/đã deblock |
| `schedule.json`, `proof.json`, `proof.bin`, `public_signals.json` | Lịch nhúng và proof |
| `*.stdout`, `*.stderr` | Log từng tiến trình con |

### 15.4. Một demo duy nhất

Bộ script demo theo từng bước (`00_prepare.py` … `14_summary.py`) đã được gộp vào
`terminal_demo.py` ngày 2026-10-03. Mã demo được chia theo trách nhiệm: `terminal_demo.py`
(luồng chính), `deep_trace.py` và `h264_explain.py` (giải thích sâu), `segment_plan.py`
(dung lượng và lịch theo đoạn), `negative_cases.py` (ca từ chối), `service_steps.py`
(HTTP/WebSocket), `native_io.py` (gọi công cụ native). Cờ đầy đủ: `demo/README.md`.

---

## 16. Kiểm thử và tái lập

```powershell
py -3.12 -m pip install -r requirements.txt
cd circuits; npm ci; cd ..
cmake --build native/build --config Release
py -3.12 src/runtest/prepare_fixtures.py          # tạo lại data/encoded/*.h264 từ data/raw
py -3.12 src/runtest/run_all.py                    # toàn bộ phase
py -3.12 src/runtest/run_all.py --quick            # phase nhanh
ctest --test-dir native/build -C Release --output-on-failure
```

| Phase | Nội dung |
|---|---|
| Phase | File | Nội dung |
|---|---|---|
| 1 | `test_zk_proof.py` | Proof Groth16: định dạng, nén, verify, fail-closed |
| 2 | `test_native_blind_contract.py` | C++ và Python khớp HKDF, lịch, khung, làm trắng, lịch theo đoạn |
| 3 | `test_native_cli_fixture.py` | CLI nhúng/trích trên fixture 300 frame, decode nghiêm ngặt, sai khóa |
| 4 | `test_h264_tables.py` | Bảng VLC CAVLC (prefix-free, Kraft, giá trị chuẩn) |
| 5 | `test_service_api.py` | Lõi job, xác thực trước body, giới hạn thử sai, lưu trữ, job verify, hạn khóa |
| 6 | `test_native_http_channel.py` | Job HTTP và luồng WebSocket qua Uvicorn thật |
| 7 | `test_manifest_security.py` | Ký manifest, ràng buộc positions/stego |
| 8 | `test_realtime_scheduler.py` | Bộ lập lịch realtime |
| 9 | `test_benchmark_recorder.py` | Kiểm tra fail-closed của bộ ghi benchmark camera và các hàm phân tích benchmark |
| 10 | `test_trust_interfaces.py` | Giao diện trust thử nghiệm (provenance, C2PA, attestation) |
| 11 | `test_demo_h264_explain.py` | Toán giải thích của demo khớp native và pixel FFmpeg |
| 12 | `test_demo_smoke.py` | Toàn bộ demo chạy không có `[FAIL]` |
| H1 | `test_native_camera_http.py` | Camera thật (`--hardware`) |

Mã thoát `run_all`: 0 = tất cả qua, 1 = có lỗi, 2 = có ca bị bỏ qua (chưa đủ bằng chứng).

---

## 17. Bảo mật, giới hạn và việc còn mở

- Kênh native tách khóa con bằng HKDF và làm trắng bit; từ v3 khung không còn MAC nên mọi
  xác thực payload dựa vào proof camera (mục 10).
- Proof ràng buộc toàn bộ video; các bit carrier được bảo vệ qua payload (đổi chúng làm payload
  đổi). Hash phụ thuộc khóa giấu tin nên chỉ người có khóa mới kiểm chứng được.
- Luồng live chỉ ràng buộc được message (mode 1). Groth16 Phase 2 là nghi thức demo trên một
  máy. Proof không chứng minh camera thật sự quay cảnh đó.
- Parser native chỉ nhận Baseline, CAVLC, progressive, 4:2:0, một slice/frame bắt đầu
  ở MB 0, không I_PCM, không nhiều SPS/PPS khác id.
- Realtime chưa đạt yêu cầu trên camera thật; chưa có kết quả trên thiết bị edge.

Kế hoạch xử lý các điểm trên: `future_plan.md`.

---

## 18. Thuật ngữ

| Thuật ngữ | Nghĩa |
|---|---|
| Annex-B | Định dạng luồng H.264 dùng start code để phân tách NAL |
| NAL | Network Abstraction Layer unit, đơn vị dữ liệu H.264 |
| EBSP / RBSP | Payload có / không có emulation-prevention byte |
| EPB | Emulation-prevention byte `0x03` |
| SPS / PPS | Tập tham số chuỗi / ảnh |
| IDR | Ảnh giải mã tức thời, không tham chiếu ảnh trước |
| MB | Macroblock 16×16 |
| CBP | Coded block pattern |
| QP | Tham số lượng tử |
| CAVLC | Context-adaptive variable-length coding |
| nC | Ngữ cảnh chọn bảng coeff_token |
| Trailing one | Hệ số ±1 ở cuối scan, tối đa 3 mỗi khối |
| Deblocking | Bộ lọc làm mịn biên khối, áp sau tái tạo |
| HMAC | Mã xác thực thông điệp dựa trên hàm băm |
| Groth16 | Hệ chứng minh không tiết lộ (zk-SNARK) với proof hằng kích thước |
| Trích xuất mù | Lấy dữ liệu không cần video gốc hay file phụ |

---

## 19. Bản đồ mã nguồn

| Đường dẫn | Vai trò |
|---|---|
| `native/include/zkstego/cavlc_stream.hpp`, `native/src/cavlc_stream.cpp` | Parser H.264/CAVLC, ứng viên, lịch HMAC, khung, encoder/decoder theo đoạn |
| `native/tools/blind_bits.cpp` | CLI nhúng/trích |
| `native/tools/inspect.cpp` | Công cụ soi duy nhất `zkstego_inspect` (JSON, `--summary`, `--macroblock`, `--segments`) |
| `native/tests/cavlc_stream_tests.cpp` | CTest native |
| `src/native_blind_contract.py` | Hợp đồng lịch/khung bằng Python (tham chiếu) |
| `src/zk_proof.py`, `src/camera_proof.py`, `circuits/camera_video.circom` | Payload, proof camera (sổ đăng ký + ràng buộc video), nén, xác minh |
| `src/camera_registry.py`, `src/poseidon.py`, `src/video_binding.py`, `src/zk_setup.py` | Sổ đăng ký Merkle Poseidon, hash video + binding, setup Groth16 |
| `src/api/app.py`, `src/api/native_handlers.py` | Lõi job dùng chung + dịch vụ native HTTP/WebSocket (embed, extract, verify) |
| `src/realtime_cavlc.py` | Bộ lập lịch realtime |
| `src/h264_tables.py` | Bảng VLC CAVLC chuẩn (cho phần giải thích của demo) |
| `src/manifest.py`, `src/key_policy.py`, `src/trust/` | Manifest có chữ ký, chứng chỉ khóa có hạn, giao diện trust thử nghiệm |
| `demo/` | Demo duy nhất: `terminal_demo.py` và các module `deep_trace`, `h264_explain`, `segment_plan`, `negative_cases`, `service_steps`, `native_io` |
| `src/runtest/` | Bộ test (`run_all.py`) và `prepare_fixtures.py` |
| `benchmark/` | Benchmark; một lệnh `run_new_suite` ghi một báo cáo duy nhất `results/benchmark_report_new.pdf` |
| `doc/realtime_cavlc_theory_and_implementation.md` | Lý thuyết và hợp đồng realtime chi tiết |
| `doc/completion_plan.md` | Kiểm toán bằng chứng và cổng nghiệm thu |
| `future_plan.md` | Kế hoạch phiên bản tiếp theo |
