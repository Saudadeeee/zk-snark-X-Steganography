# Hợp đồng transport realtime (legacy)

> Tài liệu legacy mô tả subsystem tiền-lattice-ZK (đã đóng băng, vẫn được giữ và
> có test). Đường dẫn module đã cũ sau đợt dọn dẹp 10/2026: `src.realtime` nay ở
> `src.legacy.realtime`.

Repo có một lớp transport H.264 Annex-B độ trễ-có-giới-hạn trong `src.realtime`.
Đây là một nền tảng live-stream, không phải tuyên bố rằng bộ vá CAVLC Python
hiện tại có thể mã hóa video tùy ý theo thời gian thực.

## Cái chạy được bây giờ

- Parse Annex-B tăng dần qua các chunk pipe/mạng tùy ý.
- Lắp access-unit theo ranh giới AUD (`NAL type 9` bắt buộc).
- Một hàng đợi có giới hạn, bỏ các khung non-IDR cũ trước một khung IDR mới.
- Lập lịch chỉ-IDR cho các chunk payload nhỏ gọn.
- Chuyển tiếp fail-open: nếu một live mutator lỗi, access unit gốc được chuyển
  tiếp không đổi và lỗi được đếm.

Test hợp đồng chạy bằng:

```powershell
py -3.12 src/runtest/test_realtime_transport.py
```

## Profile bộ mã hóa đầu nguồn

Bên gửi live phải phát H.264 Baseline/CAVLC Annex-B với các NAL unit AUD. Một
lệnh encoder FFmpeg tiêu biểu:

```bash
ffmpeg -re -i INPUT -c:v libx264 -profile:v baseline -coder 0 \
  -x264-params "aud=1:keyint=30:min-keyint=30:scenecut=0" -f h264 pipe:1
```

Nhịp keyframe là một đánh đổi dung-lượng/độ-trễ: payload chỉ có thể được lập lịch
trên một access unit IDR hoàn chỉnh. Relay không suy ranh giới access-unit từ các
slice header một phần.

## Backend sản xuất bắt buộc

`RealtimeAnnexBRelay` nhận một callback `AccessUnitMutator`. Một backend sản xuất
phải là native (C/C++/Rust, build trên FFmpeg/libavcodec hoặc một tích hợp
encoder tương đương) và phải, cho mỗi IDR unit bị sửa:

1. giữ hợp lệ cú pháp CAVLC và NAL framing chính xác;
2. chỉ áp các ứng viên được chấp nhận bởi kiểm tra bit-length và forward-decode;
3. hoàn thành trong deadline khung đã cấu hình; nếu không, trả về access unit
   gốc;
4. phát telemetry carrier đã áp để receiver phân biệt một chunk bị bỏ với một
   nhúng hợp lệ.

Bộ tái dựng Python định-hướng-file hiện có cố ý không được cài làm callback đó:
độ trễ phân tích và tái dựng toàn-file khiến nó không an toàn để quảng bá là
realtime. Đường biên nhận/reference ML-DSA nhỏ gọn là nguồn payload phù hợp cho
scheduler live; proving Groth16 thuộc về một control plane bất đồng bộ, không
phải hot path mỗi khung.

## Đường native C trực tiếp lên video

`native/` nay gồm một carrier hệ số CAVLC trực tiếp C17. Nó đổi parity độ lớn của
một hệ số AC tần-số-cao, đã-khác-không, nhiều nhất một đơn vị. Quy tắc giữ support
khác-không và cho phép trích xác định từ luồng hệ số đã giải mã.

Relay Annex-B tổng quát vẫn chỉ-transport. Nó có thể phơi một đường chẩn đoán
SEI, nhưng SEI bị loại trừ tường minh khỏi pipeline stego trực-tiếp-lên-video.
Sửa CAVLC trực tiếp chỉ an toàn trong một encoder fork sau lượng tử hóa và trước
inverse transform/tái dựng; nếu không các khung tham chiếu có thể trôi. Bộ
adapter x264 native chọn Baseline/CAVLC riêng cho tích hợp fork đó.

## Quyết định cài đặt tiếp theo

Backend native phụ thuộc mục tiêu triển khai và transport: x86/Linux hay
Raspberry Pi, cộng RTSP/SRT/WebRTC. Các lựa chọn đó định ra API decoder, đường
tăng tốc phần cứng, và một mục tiêu độ trễ đo được; không thể chọn thay thế lẫn
nhau sau khi giao thức trên dây đã cố định.
