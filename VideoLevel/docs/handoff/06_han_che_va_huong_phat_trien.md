# Giới hạn và hướng phát triển

Mục đích: liệt kê trung thực các giới hạn và việc còn lại, kèm nơi mỗi mục được xử lý/theo dõi.
cập nhật: 2026-10-22

Theo dõi chính: `docs/ROADMAP.md` (giai đoạn A → Q2, giai đoạn B → Q1) và
`docs/review/QUESTIONS.md` (câu hỏi mở cho reviewer mật mã).

## 1. Giới hạn mật mã

| Giới hạn | Mô tả | Theo dõi ở |
|---|---|---|
| **M-SIS quantum 127 < 128** | Binding quantum core-SVP là 127 bit, ngay dưới 128. Classical 140 bit ổn. | QUESTIONS Q2, Q15; cân nhắc nâng rank M-SIS (xem §3) |
| **Soundness là "relaxed"** | Extractor chỉ cho relaxed opening (`‖r̄‖∞ ≤ 2B`), binding theo relaxed opening với chặn ℓ∞ lớn `8κB` (`β/q ≈ 1/17`); view ℓ2 vô nghĩa. | SPEC §4.3–4.4; QUESTIONS Q2, Q4 |
| **FS-with-aborts chưa chứng minh đầy đủ** | Mô phỏng prover-aborting trong classical ROM dựa trên lập luận min-entropy; cần reviewer xác nhận không vướng lỗi mà Barbosa et al. (2023) chỉ ra. Không có định lý QROM ("plausibly post-quantum"). | SPEC §4.2, §5; QUESTIONS Q1, Q10 |
| **Một khóa cam kết toàn cục** | `ck` nở từ `parameter_id`, dùng chung mọi user/registry; một lần rút gọn lattice ~2^140 phá binding cho mọi cam kết. | QUESTIONS Q9 (D9, mở) |
| **Cần review mật mã bên ngoài** | Hệ tự hiện thực, chưa kiểm toán. Một bài Q1 cần chuyên gia lattice đọc lại chứng minh. | ROADMAP B4; gói review `docs/review/` |

## 2. Giới hạn hệ thống và phạm vi

- **In-band ràng buộc cam kết, không ràng buộc con người**: chế độ in-band chỉ
  chứng minh biết opening của một cam kết; nó **không** xác thực người tạo. Liên
  kết cam kết ↔ người đến từ registry (registered) + holder id, và vẫn phải tin
  issuer. (SPEC §4.8)
- **Dễ vỡ khi mã hóa lại**: carrier ở mức hệ số CAVLC; transcode/re-encode gần
  như chắc chắn phá bằng chứng. Hệ hướng tới toàn vẹn luồng bit, không chịu
  được chỉnh sửa hợp lệ.
- **Chỉ Baseline/CAVLC (không CABAC)**: chưa hỗ trợ CABAC, profile cao hơn.
- **Giới hạn dung lượng**: clip QP cao hoặc nhiều chuyển động có thể không đủ
  chứa envelope; GOP>1 giảm dung lượng mạnh (xem `05_ket_qua.md` §6).
- **Thách thức phiên tương tác (một-lần)**: chống phát lại cần verifier cấp và
  tiêu thụ thách thức qua `SessionChallengeStore`; stateless mode **không** chống
  phát lại, và **không** chế độ nào chống relay. (QUESTIONS Q13)
- **Phát hiện được bởi steganalysis học máy ở một số carrier**: magnitude khó
  phát hiện (P_E ~0.4–0.47), nhưng **t1-spread** dễ hơn (P_E ~0.27); khuếch đại
  biên độ làm lộ rõ. Số học máy hiện là **v1 và đang hoãn đo lại v2**. (ROADMAP
  §"Việc hoãn lại"; `docs/CNN_STEGANALYSIS.md`, `docs/ADAPTIVE_CARRIERS.md`)

## 3. Giới hạn kỹ thuật / chất lượng mã

- **Mặc định v1 vs v2**: một số đường/tài liệu cũ vẫn mặc định
  `bdlop-open-128-v1`; sản xuất là `bdlop-open-128-v2`. Cần thống nhất mặc định
  v2 ở mọi nơi và đo lại các số v1.
- **Python không constant-time**: số nguyên lớn Python + vòng lặp rejection phụ
  thuộc dữ liệu → có kênh thời gian. Không dùng cho môi trường cần chống kênh
  phụ. (SPEC §7)
- **Kiểm thử là "chạy đúng", chưa stress/fuzz**: bộ test xác minh tính đúng chức
  năng và đối chiếu claim↔code (`docs/review/CLAIMS.md`), nhưng chưa có
  stress/fuzz diện rộng; nhiều reduction/mô phỏng không có test thực thi
  (CLAIMS §"Gaps"). Phân phối đầu ra của simulator và tính đồng đều của
  SampleInBall/ternary sampler mới được lập luận, chưa kiểm thống kê mạnh.

## 4. Hướng phát triển (theo `docs/ROADMAP.md`)

Giai đoạn A (đủ chuẩn Q2): A0 thí nghiệm còn lại (4CIF, đường cong mật độ, ML
toàn bộ), A1 gia cố mã, A2 hiệu năng verify, A3 tái lập + CI, A4 bản thảo, A5 mô
hình + chứng minh, A6 CNN steganalysis.

Giai đoạn B (hướng Q1): **B1** embedding thích nghi theo chi phí (STC — đã có mã,
cần tăng P_E học máy), **B2** binary/payload-range proof (đã có, cần nối vào mã
hóa payload 24-bit), **B3** đánh giá rộng 720p/1080p/GOP>1, **B4** gói review mật
mã bên ngoài.

Các quyết định mở cho chủ mới được liệt kê trong `07_checklist_ban_giao.md` §4.
