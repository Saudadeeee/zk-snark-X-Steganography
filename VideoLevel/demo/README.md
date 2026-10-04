# Demo hệ thống trên terminal

## Một lệnh chạy toàn bộ quy trình

Demo chỉ có **một entry point**: [`terminal_demo.py`](terminal_demo.py). Chạy tại thư mục `VideoLevel`:

```powershell
py -3.12 demo/terminal_demo.py
```

Chọn video trong menu, nhập message, rồi nhấn Enter để đi qua từng bước.
Các phép encode, parse, sinh proof, nhúng, giải mã, verify, HTTP job và WebSocket đều chạy thật.
Không dùng dữ liệu giả để vẽ ASCII hoặc thay thế Groth16 bằng một giá trị boolean có sẵn.

Máy mới cần Python 3.12 với dependencies của project (`requirements.txt`, gồm FastAPI/httpx),
CMake/compiler C++20, Node/npm, Circom 2, FFmpeg có libx264 và ffprobe trên PATH.
Chuẩn bị native và circuit một lần:

```powershell
py -3.12 demo/terminal_demo.py --setup
```

`--setup` build Release hai target `zkstego_blind_bits` và `zkstego_inspect`, chạy `npm ci`,
tải bộ Powers of Tau Hermez power 16 (~75 MB, kiểm tra BLAKE2b theo tài liệu snarkjs) rồi chạy
`py -3.12 -m src.zk_setup`: compile `camera_video.circom`, Phase 2 gồm 2 lượt đóng góp + beacon
công khai, `snarkjs zkey verify`. Cả hai lượt chạy trên một máy nên đây là nghi thức **demo**, không
phải trusted ceremony cho triển khai. Khóa đã có được giữ nguyên.

### Ví dụ

```powershell
py -3.12 demo/terminal_demo.py --auto --message "mot demo"
py -3.12 demo/terminal_demo.py --auto --input data/raw/foreman_cif.y4m --message "Xin chào ZK video"
py -3.12 demo/terminal_demo.py --auto --gop 12 --frames 48 --message "GOP experiment"
py -3.12 demo/terminal_demo.py --auto --brief --no-service --message "nhanh"
py -3.12 demo/terminal_demo.py --auto --frames 40 --max-bits-per-idr 64 --message "cap 64"
py -3.12 demo/terminal_demo.py --rows 32 --all-maps
```

### Tham số

| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `--auto` | tắt | Không dừng chờ Enter; tự chọn video đầu tiên trong menu |
| `--brief` | tắt | Bỏ các bước giải thích sâu (FFmpeg/x264, NAL/EPB, `trace_headers`, giải phẫu block, vị trí bit) |
| `--no-service` | tắt | Bỏ hai bước dịch vụ native: HTTP jobs và WebSocket stream |
| `--frames N` | 8 | Số frame tối đa encode (1..120) |
| `--gop N` | 1 | Khoảng IDR (1..120); GOP>1 có P frame, chỉ IDR mang bit |
| `--qp N` | 22 | QP của libx264 (1..51) |
| `--max-bits-per-idr N` | 64 | Số bit tối đa mỗi IDR segment (1..100000). Nếu **không truyền** và clip quá ngắn, demo tự nâng lên giá trị nhỏ nhất đủ capacity và in lý do; nếu truyền mà thiếu capacity thì dừng |
| `--setup` | tắt | Build native + chạy setup Groth16 của `camera_video` (DEMO) nếu thiếu |
| `--input PATH` | menu | Video đầu vào (Y4M hoặc H.264...) |
| `--message TEXT` | hỏi/`--auto`: "Xin chao ZK video" | Message UTF-8, 1..3963 bytes |
| `--rows N` | 16 | Số dòng preview NAL / segment / schedule (1..256) |
| `--all-maps` | tắt | In bản đồ macroblock cho mọi IDR thay vì IDR đầu tiên |

Mọi input, kể cả H.264, được encode lại về Baseline/CAVLC/yuv420p, ≤640×480, một slice/frame,
không B frame. Đây là chuẩn hóa đầu vào của demo, không phải khẳng định core hỗ trợ mọi video/profile.

### Giao thức kênh: segment protocol v3

Demo dùng **đúng giao thức của dịch vụ native**. Mỗi IDR là một *segment* (SPS/PPS đang hiệu lực +
IDR đó). Khung kênh `[0x03][len BE16][payload]` (không MAC) được whitening rồi chia theo thứ tự:
segment `s` mang tối đa `min(max_bits_per_idr, số candidate của s)` bit tiếp theo, chọn theo
`HMAC-SHA256(schedule_key, ID trong segment)`. Capacity = Σ min(cap, candidates). Payload cần
`(136 + message bytes) × 8` bit, nên clip ngắn cần cap lớn hơn 64 hoặc nhiều IDR hơn
(ví dụ foreman QP 22 ≈ 450 candidate/IDR: `--gop 12 --frames 24` chỉ có 2 IDR ≈ 900 bit, không đủ;
`--frames 48` thì đủ). Khi thiếu, demo dừng với thông báo rõ: tăng `--frames`, giảm `--gop`,
tăng `--max-bits-per-idr` hoặc rút ngắn message.

### Các bước

| # | Bước | Nội dung chính |
|---|---|---|
| 1 | Preflight | Công cụ, artifact circuit, phạm vi giao thức segment |
| 2 | Video | Y4M header, ffprobe, lệnh FFmpeg encode |
| 3* | Bên trong FFmpeg/libx264 | Demuxer → decoder → filtergraph → libx264 → muxer, thống kê x264, frame chưa nén (ASCII + ma trận 16×16), PSNR do nén |
| 4 | Parser native | `zkstego_inspect <video>`: NAL, IDR slice, candidates từng IDR |
| 5* | NAL/EBSP/RBSP | Header NAL theo bit, EPB, SEI của x264, SPS/PPS/slice header do `trace_headers` giải, đối chiếu với parser native |
| 6 | Capacity | Số bit khung của payload, chọn cap bit/IDR |
| 7 | Camera + hash video + ZKP | Sổ đăng ký 4 camera (cây Merkle Poseidon, root công khai); **mở đường Merkle đủ 16 tầng** từ pk tới root; hash video của cover (chỉ các bit dấu sẽ mang khung, theo lịch của stego key, bị đặt về 0); *bảng từng NAL: EBSP/RBSP, số bit carrier bị xóa, SHA256(rbsp'), Python tính lại digest = native*; binding, 3 public input, witness, proof A/B/C, dạng nén 129 B |
| 8 | Payload + lịch | HKDF subkeys, khung v3 (không MAC), whitening; `zkstego_inspect --segments`; **bảng phân bổ: IDR nào mang khoảng frame bit nào**; preview lịch (ID trong segment, vị trí file, score, bit cũ/mới) |
| 9 | Nhúng | `embed-stream-auth-stdin`; đối chiếu từng candidate, bản đồ MB, hệ số trước/sau |
| 10 | Decode | Frame ASCII trước/sau, bản đồ chênh lệch Y, pixel 4×4, PSNR Y/U/V |
| 11* | Giải phẫu một khối | Bit → CAVLC → hệ số → giải lượng tử → biến đổi ngược → dự đoán intra → pixel, khớp FFmpeg từng mẫu; chiều thuận (DCT nguyên + lượng tử) |
| 12* | Bit nằm ở đâu | Segment → hạng HMAC trong segment → chỉ số frame bit → trường payload → byte trong file (tính cả EPB) |
| 13 | Verifier | `extract-stream-auth` chỉ với stego + stego key; hash video tính lại từ stego = hash cover; **Groth16 bắt buộc** với root sổ đăng ký (không cần secret camera) rồi mới trả message; lịch tái tạo từ stego khớp |
| 14 | Ca bác bỏ | Message sai; proof sai/thiếu dù khung đúng; sai key (header khung sai); lật **một** sign bit carrier → native vẫn trích được message đã đổi 1 bit, **Groth16 từ chối**; lật một bit dấu **không** mang khung trong cùng IDR → payload không đổi nhưng digest đổi → từ chối; cắt frame cuối; **replay**: nhúng nguyên payload đã được chấp nhận vào clip khác → trích được nhưng từ chối; camera ngoài sổ đăng ký (proof đúng với cây của nó, sai với root tin cậy) |
| 15† | HTTP jobs | `create_native_app` thật (TestClient, token ≥32 ký tự, sổ đăng ký của demo): embed → stego trùng CLI; extract → payload (`verified: false`); verify → `succeeded` + message + `video_bound`; verify sai key → `rejected`; in trạng thái và độ trễ |
| 16† | WebSocket | Gửi `source.h264` theo chunk 16 KiB qua `/api/v1/stream`; stego trả về trùng CLI, decode được, extract (CLI và WebSocket) ra đúng payload; metrics native |
| 17 | Tổng kết | Timing, capacity, số PASS (60/60 với cấu hình mặc định), phạm vi bảo vệ |

`*` bỏ qua với `--brief`; `†` bỏ qua với `--no-service`. Số thứ tự thực tế giảm tương ứng.
Mọi giá trị tự tính lại được đối chiếu với FFmpeg, parser native hoặc dịch vụ và in `[PASS]`/`[FAIL]`;
một `[FAIL]` dừng demo với exit code 1.

Giải thích lý thuyết: [doc/he_thong_hoat_dong.md](../doc/he_thong_hoat_dong.md), mục 2–7 và 15.
Công cụ native: `zkstego_inspect <video>` (JSON schema 1), `--macroblock <NAL> <MB>`,
`--summary`, `--segments <MAX_BITS>` (JSON `segments-1`).

### Module trong `demo/`

| File | Vai trò |
|---|---|
| `terminal_demo.py` | Entry point và các bước chính |
| `native_io.py` | Gọi `zkstego_blind_bits` / `zkstego_inspect` / snarkjs verify, có log từng subprocess |
| `segment_plan.py` | Chọn cap, ánh xạ ID segment ↔ ID file, bảng phân bổ |
| `deep_trace.py`, `h264_explain.py` | Giải thích sâu FFmpeg/H.264 (được kiểm bởi `src/runtest/test_demo_h264_explain.py`) |
| `negative_cases.py` | Các ca bác bỏ |
| `service_steps.py` | HTTP jobs và WebSocket stream qua app native |

### Artifact và cách đọc kết quả

Mỗi lần chạy tạo thư mục riêng `demo/runs/terminal_<time>_<random>/`:

- `transcript.txt`, `report.json`: thuyết minh và kết quả (`status`, `checks`, timing, capacity, PSNR).
- `source.h264`, `stego.h264`, `tampered_carrier.h264`, `invalid_proof.h264`, `missing_proof.h264`.
- `http_stego.h264`, `ws_stego.h264`, `service_work/`: đầu ra của dịch vụ.
- `trace_before.json`, `trace_after.json`: toàn bộ NAL, slice, candidate, sign bit và hệ số.
- `segments_before.json`, `segments_after.json`: input lịch theo segment (`segments-1`).
- `schedule.json`: mọi vị trí được dùng: segment, frame bit, ID trong segment, ID file, score, bit trước/đích, flip.
- `proof.json`, `proof.bin`, `public_signals.json`: proof và 3 public input; `camera_registry.json`: sổ đăng ký của demo.
- `before.yuv`, `after.yuv`, `frame_*_{before,after,delta}.pgm`: pixel thực để xem ngoài terminal.
- `*.stdout`, `*.stderr`: log từng subprocess, kể cả các ca reject.

PSNR đo **source H.264 sau encode so với stego**. `null` trong PSNR JSON nghĩa là không có sai khác.
Timing có startup process; trace/ASCII là chi phí minh họa, không phải throughput production.
Một lần chạy chưa đủ để kết luận benchmark. Exit code `0` = mọi kiểm tra PASS, `1` = lỗi/kiểm tra
thất bại, `130` = người dùng ngắt. Smoke test: `py -3.12 src/runtest/test_demo_smoke.py`
(Phase 12 trong `src/runtest/run_all.py`, không thuộc `--quick`).

### Luồng source

```text
terminal_demo.py
  +-- FFmpeg: input -> source.h264
  +-- src/camera_registry.py + video_binding.py: so dang ky, hash video cover, binding
  +-- src/zk_proof.py + camera_video.circom: camera secret + duong Merkle -> proof
  +-- zkstego_inspect: NAL/MB/candidates/coefficients; --segments: input lịch theo IDR
  +-- src/native_blind_contract.py: segment_schedule/HKDF/whitening đúng ABI native
  +-- zkstego_blind_bits embed-stream-auth-stdin: nhúng theo segment
  +-- FFmpeg: decode và so sánh pixel
  +-- zkstego_blind_bits extract-stream-auth: blind extraction (kiểm header khung v3)
  +-- src/camera_proof.verify_payload: hash video stego + snarkjs verify voi root -> message hoặc lỗi
  +-- src/api/native_handlers.create_native_app: /api/v1/jobs/{embed,extract,verify}, /api/v1/stream
```

### Bảo mật và giới hạn

Stego key và secret camera được tạo mới cho mỗi lần demo; secret camera được in để học về private
input. Transcript che secret và subkey; shell recording/chuyển hướng stdout vẫn có thể ghi chúng. Key luôn đi qua stdin của
tiến trình native, không qua argv hay file. Không dùng secret/token demo cho triển khai.

Native CLI chỉ kiểm header khung (version, độ dài); khung v3 không có MAC. Quy tắc **proof bắt buộc** được demo thực thi ngay sau
extract/unpack; job `/api/v1/jobs/verify` của dịch vụ cũng blind-extract rồi verify Groth16 phía server.
Circuit chứng minh: Poseidon(secret camera) là một lá của cây sổ đăng ký có root công khai, và proof
gắn với binding = SHA256(hash video ‖ SHA256(message)). Nên proof hợp lệ nghĩa là **một camera
đã đăng ký xác nhận đúng video và message này**, không lộ camera nào. Chưa chứng minh camera thực sự
quay cảnh đó, và setup Groth16 Phase 2 là demo.

Hệ số residual lượng tử trong ma trận **không phải pixel**. Đổi dấu ±1 có thể gây sai khác ở block
khác qua prediction/deblock và lan sang P frame tham chiếu. Chỉ hỗ trợ Baseline, CAVLC, progressive,
4:2:0 và chỉ nhúng vào IDR. Camera vật lý không nằm trong demo (xem `test_native_camera_http.py`).
