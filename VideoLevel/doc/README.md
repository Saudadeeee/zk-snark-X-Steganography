# Tài liệu VideoLevel

Bắt đầu từ **[he_thong_hoat_dong.md](he_thong_hoat_dong.md)**: mô tả đầy đủ hệ thống hoạt động
thế nào, từ FFmpeg/libx264, cấu trúc H.264, CAVLC, kênh nhúng, lịch HMAC, khung kênh v3,
proof Groth16 đến dịch vụ, demo và cách đọc kết quả debug. Các ví dụ số trong đó lấy từ
một lần chạy `demo/terminal_demo.py` thật.

| Tài liệu | Nội dung | Định dạng |
|---|---|---|
| [he_thong_hoat_dong.md](he_thong_hoat_dong.md) | Hệ thống hoạt động như thế nào (bản đầy đủ, cập nhật 2026-10-02) | Markdown |
| [realtime_cavlc_theory_and_implementation.md](realtime_cavlc_theory_and_implementation.md) | Lý thuyết và hợp đồng native cho đường realtime, số đo camera | Markdown (EN) |
| [completion_plan.md](completion_plan.md) | Kiểm toán bằng chứng, cổng nghiệm thu còn mở | Markdown (EN) |
| [edge_deployment_manifest.template.yaml](edge_deployment_manifest.template.yaml) | Mẫu khai báo thiết bị edge trước khi đo | YAML |
| [system_video_embedding_walkthrough.tex](system_video_embedding_walkthrough.tex) / `.pdf` | Walkthrough hệ thống nhúng video | LaTeX/PDF |
| [zk_stego_theoretical_foundation.tex](zk_stego_theoretical_foundation.tex) | Nền tảng lý thuyết | LaTeX |
| [huong_dan_lan_theo_source_zkstego.tex](huong_dan_lan_theo_source_zkstego.tex) | Hướng dẫn lần theo mã nguồn | LaTeX |
| [review_toan_he_thong_zkstego.tex](review_toan_he_thong_zkstego.tex) | Review toàn hệ thống | LaTeX |
| [bao_cao_khoa_hoc_he_thong_zkstego_vi.tex](bao_cao_khoa_hoc_he_thong_zkstego_vi.tex) / `.pdf` | Báo cáo khoa học | LaTeX/PDF |

Các file LaTeX được viết trước đợt sửa ngày 2026-10-02 (bảng VLC Python, verify Groth16
theo mã thoát, xác thực trước khi đọc body, giới hạn native). Khi có mâu thuẫn, tin
`he_thong_hoat_dong.md` và mã nguồn.
