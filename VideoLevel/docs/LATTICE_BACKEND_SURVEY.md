# Khảo sát backend lattice ZK (2026-09-27 đến 2026-10-12)

Vì sao hệ thống tự cài đặt BDLOP thay vì dùng một hệ chứng minh lattice đã có.
Mỗi ứng viên được kiểm theo bốn cổng:

1. **Zero knowledge** trong cấu trúc và mã thực sự được dùng.
2. **Quan hệ ứng dụng**: statement video/phiên/payload do verifier ghim có thể
   biểu diễn và gắn vào transcript.
3. **Chạy được ở đây**: prove/verify hoàn chỉnh trên Windows x86-64 không có
   AVX-512 (Intel i7-12700H), hoặc trong một container Linux trên đó.
4. **Vừa carrier**: proof cộng framing vừa dung lượng CAVLC đã đo, đã được xác
   minh chất lượng (hàng chục KB trên các clip CIF 1 000–3 000 khung).

Các ghi chú chi tiết theo từng ứng viên (source pin, lệnh, log) được gộp vào
file này ngày 2026-10-19; bản gốc còn trong git history đến commit `07c02d9`.

| Ứng viên | Nguồn | Phát hiện quyết định | Cổng thất bại |
|---|---|---|---|
| LaZer | lazer-crypto/lazer, pin `10eafec` | Cần Linux x86-64 với AVX-512 và AES; CPU host chỉ có AVX2; preflight (`src/legacy/lazer_backend.py`) fail closed | 3 |
| LaZer Toolkit (ZK LaBRADOR) | ePrint 2026/1289 | Có biến thể ZK, nhưng statement ZK duy nhất trong source là ví dụ Merkle-membership; không build ở đây; cùng yêu cầu AVX-512 | 2, 3 |
| LNP22 (Go, KarpelesLab/lnp22 v0.1.1) | KarpelesLab/lnp22 v0.1.1 (probe context-binding cục bộ gỡ trong đợt dọn dẹp 10/2026; trong git history) | Verifier chấp nhận một proof cho `s[0]=2` với `Beta=1` và một witness payload-opening không-bit (test đánh giá phụ thuộc của probe); các biên chính xác không được thực thi | 1/soundness |
| ISW21 lattice-zksnark | `48cb4cd` (smoke test R1CS opening cục bộ gỡ trong đợt dọn dẹp 10/2026; trong git history) | Build và chạy được (quan hệ toy 32-byte, envelope 23 907 byte mang qua H.264). Designated verifier; giả thiết LWE knowledge-based linear-only bị phá bởi quantum oblivious sampling (LUNA; ePrint 2024/030); ZK thống kê chỉ 2^-40; upstream cần hai bản vá lỗi cục bộ | 1 (giả thiết), 4 ở 300 khung |
| ePrint 2025/2099 (DV zkSNARK từ MSIS) | crypolover1998/LatticeBased-Dv-zkSNARK `9bc41a6` | Định lý mạnh nhất (adaptive knowledge soundness trong ROM), nhưng mã có trước bài báo và chỉ mô phỏng `lambda=1` không có accept/reject; proof 20.75 KB, CRS 1.3 GB | 3 |
| LUNA | ePrint 2022/1690, yassimert/LUNA | Repo chỉ cài thành phần mã hóa HGSW, không phải prover/verifier; soundness non-adaptive | 3 |
| LaBRADOR (C, các port Rust, Lazarus) | ePrint 2022/1341 | Bài báo tắt ZK trong kết quả kích thước (shim masking để sau); mã C cần AVX-512; các reduction R1CS Rust chưa hoàn chỉnh | 1, 3 |
| RoKoko | ePrint 2026/575 | Chỉ knowledge soundness; witness gập cuối verifier đọc được; dựa vào vanishing-SIS; proof 112 KB | 1, 4 |
| SALSAA | ePrint 2025/2124 | Bài báo chỉ chứng minh correctness và knowledge soundness; prover gửi witness gập cuối ở dạng rõ; proof 979 KB (73 KB chỉ riêng folding) | 1, 4 |
| Symphony | ASIACRYPT 2026 | Chỉ framework; instantiation cụ thể để tương lai; định nghĩa SNARK không có tính chất ZK | 1, 3 |
| LatticeFold | ePrint 2024/257, NethermindEth/latticefold `15cc045` | Lược đồ folding, mã proof-of-concept, không phải prover/verifier ZK độc lập | 1, 3 |
| Jolt + Akita | a16z/jolt | Backend PCS Akita chỉ-rõ (không ZK); báo cáo 65–80 KB | 1, 4 |
| Ringo-SNARK / Buckler | sp301415/ringo-snark | Chạy một probe hình-payload-opening; binary proof khoảng 1.65 MB | 4 |
| latticezk (yarongvili1) | Baum et al. CRYPTO 2018 trên `Z_(2^w)` | Thực nghiệm; lập luận HVZK tương tác mà bảo đảm không chuyển trực tiếp sang biến thể FS được dùng; chiều mặc định vượt xa dung lượng | 2, 4 |
| R1CS sublinear thực dụng (ePrint 2022/1048) | chỉ bài báo | ZK với một biến thể Fiat–Shamir, nhưng không có cài đặt; 10.79 MB ở 2^24 ràng buộc | 3, 4 |
| Prototype SIS trong cây (`src/registry/lattice_pq.py`) | repo này | Statement do prover chọn; proof JSON 131 692 byte; chỉ giữ làm fixture regression fail-closed | 2, 4 |

## Kết luận

Không có cài đặt sẵn nào vượt cả bốn cổng. Quan hệ mà hệ thống cần (tri thức về
một opening của một cam kết lattice, gắn với một statement do verifier dựng) đủ
nhỏ để chứng minh opening BDLOP đã công bố phủ nó trực tiếp. Cài đặt nó từ bài
báo cho:

- zero knowledge và knowledge soundness lập luận được từ các định lý đã công bố
  (`docs/LATTICE_ZK_BDLOP_SPEC.md`, Mục 4);
- mã Python thuần, di động, chạy trên host mục tiêu;
- một proof 7 520 byte (`bdlop-open-128-v1`; 8 096 byte với v2) đã được mang qua
  H.264 và verify chỉ từ video (`docs/LATTICE_ZK_BDLOP_PLAN.md`, Mục 7).

Cái giá là mã tự cài đặt và chưa audit, và soundness là relaxed thay vì chính
xác.
