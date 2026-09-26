# Demo theo từng công đoạn

`demo/` được chia thành các script độc lập theo từng bước; không có script
chạy gộp toàn bộ pipeline. Mỗi bước nhận `--session`, ghi log riêng và tạo
artifact cho bước kế tiếp.

Mở PowerShell tại thư mục gốc của repository. Tạo một session mới; lệnh này in
ra duy nhất đường dẫn session để lưu vào biến:

```powershell
$session = py -3.12 demo/00_prepare.py --input data/encoded/foreman_cif_q18_g1_300f.h264 --message "ZK demo payload"
```

Sau đó chạy từng bước và quan sát log/đầu ra ngay sau mỗi lệnh:

```powershell
py -3.12 demo/01_generate_proof.py --session $session
py -3.12 demo/02_pack_payload.py --session $session
py -3.12 demo/03_read_video.py --session $session
py -3.12 demo/04_find_positions.py --session $session
py -3.12 demo/05_embed_video.py --session $session
py -3.12 demo/06_read_stego_video.py --session $session
py -3.12 demo/07_blind_extract.py --session $session
py -3.12 demo/08_unpack_payload.py --session $session
py -3.12 demo/09_verify_proof.py --session $session
py -3.12 demo/10_wrong_key_rejection.py --session $session
py -3.12 demo/11_http_transport.py --session $session
py -3.12 demo/12_websocket_e2e.py --session $session
py -3.12 demo/14_summary.py --session $session
```

Chạy một script độc lập sẽ báo artifact còn thiếu nếu bước trước chưa chạy.
Luồng `00`–`10` chứng minh luồng proof-bearing qua native CAVLC: tạo proof,
đóng gói, đọc NAL/IDR, đo và minh họa vị trí ứng viên, nhúng, đọc lại video,
blind-extract không cần video gốc, unpack, verify Groth16, rồi kiểm tra sai
khóa. `11` gửi chính payload proof của session qua HTTP embed/extract jobs.
`12` chạy thêm bộ E2E WebSocket/Uvicorn loopback. Đây là luồng trình diễn chính
của channel native. `14` tổng hợp những bước đã PASS/FAILED/NOT RUN.

## Liên hệ với source xử lý thật

- Bước 01–02 gọi [`src/zk_proof.py`](../src/zk_proof.py) và circuit
  [`circuits/payload_verify.circom`](../circuits/payload_verify.circom).
- Bước 03–04 gọi `zkstego_idr_inspect` và `measure-live-capacity-stdin` để đọc
  NAL/IDR, giải mã macroblock CAVLC, đếm candidate sign và ghi ra một địa chỉ
  candidate mẫu. Probe bit đơn chỉ là artifact chẩn đoán riêng.
- Lịch vị trí thực sự được chọn theo key trong
  `select_keyed_cavlc_sign_candidates`; `AuthenticatedCavlcStreamEncoder::process_segment`
  gọi hàm đó rồi patch sign bits trong
  [`native/src/cavlc_stream.cpp`](../native/src/cavlc_stream.cpp). Việc chọn
  chính xác diễn ra trong bước 05 nên không bị thay bằng một thuật toán Python
  mô phỏng.
- Bước 05–10 gọi `zkstego_blind_bits`; bộ trích xuất quét lại các IDR và tái tạo
  cùng lịch vị trí mà không cần video gốc. Sau đó Python unpack và xác minh
  Groth16 proof độc lập với xác thực channel.
- Bước 11 dùng native HTTP jobs với chính payload proof của session; bước 12
  kiểm tra WebSocket và Uvicorn loopback.

Nhánh Python `embed()`/`verify()` cũ độc lập với native realtime path và không
nằm trên đường dữ liệu chính. Muốn trình diễn nhánh thay thế này, chạy riêng:

```powershell
py -3.12 demo/13_python_pipeline.py --session $session
py -3.12 demo/14_summary.py --session $session
```

Nhánh này cần operating contract benchmark còn hợp lệ và có thể tốn nhiều thời
gian do phải phân tích video; nên chạy khi muốn so sánh cách Python cũ với
native, không cần chạy để chứng minh native pipeline.

Mỗi session nằm trong `demo/runs/session_<UTC timestamp>/` và không bị ghi đè.
Trong đó có file log stdout/stderr/mã thoát, proof 129 byte, payload đã đóng
gói, video stego, payload trích xuất và kết quả summary. `secret_key.bin` là
khóa ngẫu nhiên chỉ dành cho demo, được giữ trong session để chạy tuần tự các
bước; không dùng lại cho hệ thống thật hoặc commit/chia sẻ thư mục session.

## Thành phần cần có

- Python 3.12 và dependencies từ `requirements.txt`.
- Node.js, `circuits/build/payload_verify_js/payload_verify.wasm`,
  `circuits/build/proving_key.zkey`, và `circuits/build/verification_key.json`.
- Đã build `zkstego_blind_bits` và `zkstego_idr_inspect` trong `native/build/`.
- FFmpeg để thực hiện strict decode ở bước 06 (nếu thiếu bước này được đánh
  dấu SKIP).

Video mặc định là fixture all-intra đã có trong `data/encoded/`. Video khác
phải phù hợp với phần Baseline/CAVLC/IDR mà native parser hỗ trợ và có đủ
capacity; bước 04 đo trước và dừng nếu thiếu. Phần camera vật lý không tự chạy
vì cần người dùng chọn thiết bị; benchmark edge cũng không được suy ra từ demo
host này.
