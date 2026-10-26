# Website giải thích ZK-Video

Website tĩnh nhiều trang, tiếng Việt, giải thích toàn bộ hệ thống steganography
H.264 + bằng chứng zero-knowledge trên lattice (BDLOP) cho **người không rành
kỹ thuật**. Mỗi trang có ngôn ngữ đời thường + khối "Chi tiết kỹ thuật" mở rộng.

Cập nhật: 2026-10-26.

## Mở
Mở trực tiếp `index.html` bằng trình duyệt (double-click) là chạy được — không
cần server, không phụ thuộc internet trừ phông chữ Google (có phông dự phòng).
Hoặc chạy server tĩnh cho mượt:

    cd VideoLevel/site
    python -m http.server 8000
    # mở http://localhost:8000/

## Các trang
- `index.html` — Tổng quan: vấn đề, ý tưởng lớn, lộ trình đọc.
- `khai-niem.html` — Bốn khái niệm nền (giấu tin, commitment, zero-knowledge,
  lattice), có demo bấm thử (giấu bit, hang Ali Baba).
- `kien-truc.html` — Kiến trúc & hai luồng: nhúng và kiểm tra, từng bước có I/O.
- `thanh-phan.html` — Chín thành phần chi tiết (carrier, commitment, opening
  proof, statement, transport/chunk, GOP, codec v2, linkage/disclosure,
  proof nhị phân/khoảng).
- `che-do-vi-du.html` — Registered vs in-band + ví dụ chạy thật, số đo thật.
- `bao-mat.html` — Mô hình đe doạ, M-SIS/M-LWE, tham số v2, chống replay/tamper.
- `ket-qua.html` — Bảng 7 chế độ (số thật) + hạn chế thẳng thắn.
- `thuat-ngu.html` — Từ điển thuật ngữ sang tiếng thường.
- `assets/` — `style.css`, `site.js`, và khung ảnh thật `container/akiyo/foreman.png`.

## Khác với `webdemo/`
- `site/` (đây): **website giải thích** — để hiểu. Mở được bằng file://.
- `webdemo/`: **ứng dụng chạy thật** — để nghịch (toán lattice chạy trong trình
  duyệt, có bộ tham số sản xuất N=256).

Số liệu lấy từ bộ kiểm tra thật (`bdlop-open-128-v2`). Ví von được đơn giản hoá
có chủ đích; chi tiết hình thức ở `docs/` và `docs/paper/`.
