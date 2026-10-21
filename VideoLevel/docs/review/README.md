# Gói đánh giá mật mã bên ngoài: chứng minh video BDLOP

Gói này dành cho một nhà mật mã lattice đánh giá phần zero-knowledge của hệ
thống trong vài giờ. Nó trỏ tới đặc tả, các chứng minh an toàn, mã nguồn hiện
thực hóa từng giả định, cùng các test và known-answer vectors (KATs) kiểm tra
chúng.

Mọi đường dẫn đều tương đối so với `VideoLevel/`. Mọi dải dòng (line range)
đều tham chiếu tới commit `18c5123` (nhánh `feature/lattice-pq-stack`). Phần
an toàn của bài báo trích dẫn số dòng tại một commit cũ hơn (`ea96d60`). Khi
hai nguồn này không khớp, hãy dùng các dải dòng trong gói này.

## Hệ thống làm gì

Một video H.264 mang một envelope kích thước cố định trong các carrier hệ số
CAVLC. Envelope chứa một BDLOP commitment `t` (Baum et al., SCN 2018) cho một
payload tối đa 766 byte. Nó cũng chứa một proof of knowledge kiểu
Fiat–Shamir-with-aborts về một opening của `t`. Proof được ràng buộc với một
statement 274 byte. Verifier tính lại statement từ các pin của chính nó và từ
video nhận được: registry root và epoch, một session challenge, các vị trí
carrier, và một digest của bitstream đã được carrier-normalized. Ở chế độ
registered, commitment là một credential được pin bởi một registry ký bằng
ML-DSA-65, và video chỉ mang proof. Một equality proof giữa hai commitment
được dùng cho linkage và disclosure.

Bộ tham số `bdlop-open-128-v2`: N = 256, q = 2^30 − 35 (q ≡ 5 mod 8),
n = 6, λ = 7, k = 14, κ = 60, γ = 2^17, B = γ − κ − 1. Các mask phân bố đều
trên [−γ+1, γ]. Đây là uniform masking kiểu ML-DSA, không phải Gaussian
masking của BDLOP. Tại commit `18c5123`, bộ production là `bdlop-open-128-v1`
(λ = 6, k = 13); nó đã được thay thế vì tấn công dual-hybrid của
lattice-estimator đưa độ M-LWE hiding của nó xuống chỉ còn 135 / 123 bit
(v2: 164 / 150). Cả hai bộ vẫn được định nghĩa trong `params.py`, với các KAT
`kat_v1.json` và `kat_v2.json`.

## Phạm vi: những gì cần đánh giá

Xếp hạng theo mức độ các tuyên bố an toàn phụ thuộc vào nó:

1. **Opening proof** (`src/lattice_zk/opening_proof.py`): transcript
   Fiat–Shamir, điều kiện rejection, suy dẫn hedged mask, và verification.
2. **Tham số và ước lượng** (`src/lattice_zk/params.py`,
   `research/bdlop_params/`): cận ℓ∞ 8κB của M-SIS, instance M-LWE, challenge
   space, và tính khả nghịch (invertibility) của các hiệu challenge.
3. **Equality proof** (`src/lattice_zk/equality_proof.py`): soundness của việc
   trích xuất (extraction) common-challenge, disclosure với zero-randomness, và
   giới hạn số lần thử (attempt cap).
4. **Sampler và ring** (`src/lattice_zk/sampling.py`, `ring.py`,
   `codec.py`): tính đều (uniformity) chính xác, SampleInBall, và các mã hóa
   canonical.
5. **Ràng buộc statement và envelope** (`src/lattice_zk/video_proof.py`, và
   đường dẫn verification của `src/lattice_zk/video_pipeline.py`): liệu verifier
   có lấy bất kỳ trường statement nào từ prover hay không.
6. **Mô hình an toàn và các chứng minh** (`docs/paper/sections/security.tex`,
   `security_appendix.tex`): các định nghĩa game, mô phỏng ROM của aborting
   prover, forking, và ánh xạ M-LWE hiding.

Các câu hỏi cụ thể nằm trong [QUESTIONS.md](QUESTIONS.md). Mỗi định lý được
ánh xạ tới mã nguồn và test trong [CLAIMS.md](CLAIMS.md). Dùng
[CHECKLIST.md](CHECKLIST.md) trong khi đọc mã.

## Ngoài phạm vi

- Tính không phát hiện được (undetectability) về mặt steganography và kênh
  carrier CAVLC
  (`src/transport/blind_sync_streaming.py`, `src/transport/video_canonicalization.py`). Coi
  `Place`, `Canon`, `Write` và `Read` là các hàm tất định cho trước.
  Lỗi transport chỉ dẫn đến rejection.
- Hiện thực ML-DSA-65 (wheel `pqcrypto` 1.0.0). Nó được giả định là
  EUF-CMA.
- Các side channel. Đây là một hiện thực nghiên cứu thuần Python/NumPy và
  **không phải constant time** (xem CHECKLIST.md §7).
- Các đường dẫn Groth16/LaZer cũ (`lazer/`, `circuits/`, bộ registry
  `lazer-v1`) và dự án ImageLevel.
- Các con số về chất lượng video, dung lượng (capacity) và benchmark.

## Ước lượng thời gian

| Phần | Thời gian |
|---|---|
| Đọc đặc tả và phần an toàn | 1.5 h |
| Mã lõi (`params`, `sampling`, `ring`, `bdlop`, `opening_proof`, `equality_proof`, `codec`, khoảng 900 dòng) | 1.5 h |
| Statement, envelope và đường dẫn verification (`video_proof`, `video_pipeline` dòng 300–402) | 0.5 h |
| Ước lượng tham số và đối chiếu chéo (cross-check) | 0.5 h |
| **Tổng** | **khoảng 4 h** (2 h chỉ cho mục 1–3 của phạm vi) |

## Cách chạy

Chạy mọi thứ từ `VideoLevel/` với Python 3.12, `numpy`,
`pqcrypto==1.0.0` và `pytest` (`pip install -r requirements.txt`). Không cần
ffmpeg: các test pipeline dùng một fake transport trong bộ nhớ.

| Nội dung | Lệnh | Kỳ vọng (commit `18c5123`, Windows 11, CPython 3.12) |
|---|---|---|
| Toàn bộ test lattice-ZK | `python -B -m pytest -p no:cacheprovider -q src/runtest/test_latticezk_*.py` | `209 passed, 1 skipped` trong khoảng 50 s. Mục skip là một test file-mode POSIX trên Windows. |
| Chỉ phần lõi mật mã | `python -B -m pytest -p no:cacheprovider -q src/runtest/test_latticezk_ring.py src/runtest/test_latticezk_bdlop.py src/runtest/test_latticezk_equality.py src/runtest/test_latticezk_kat.py src/runtest/test_latticezk_linkage.py src/runtest/test_latticezk_video_proof.py` | tất cả đều pass |
| Tái tạo và so sánh KAT | `python -B research/bdlop_params/kat.py --parameter-set BDLOP_OPEN_128_V2 > /tmp/kat.json && diff /tmp/kat.json research/bdlop_params/kat_v2.json` (và `BDLOP_OPEN_128_V1` so với `kat_v1.json`) | không có diff (`kat.py` không có cờ `--check`; `test_latticezk_kat.py` thực hiện cùng phép so sánh) |
| Session store và chunk framing | `python -B -m pytest -p no:cacheprovider -q src/runtest/test_zkp_sessions.py src/runtest/test_blind_payload_chunks.py` | `22 passed` |
| Registry (test kiểu script) | `python -B src/runtest/test_zkp_registry.py` | `7/7 passed` |
| Ước lượng core-SVP (script CRYSTALS) | `git clone https://github.com/pq-crystals/security-estimates && git -C security-estimates checkout 75c26949 && python research/bdlop_params/estimate.py --estimator security-estimates` | tái tạo `research/bdlop_params/bdlop_open_128_v2.estimate.json` (với `--parameter-set BDLOP_OPEN_128_V1`: `bdlop_open_128.estimate.json`) |
| Đối chiếu chéo với lattice-estimator (Sage) | xem `research/bdlop_params/CROSSCHECK.md` | `research/bdlop_params/lattice_estimator_crosscheck_v2.json` (v1: `lattice_estimator_crosscheck.json`) |

## Bản đồ tập tin (mã nguồn quan trọng về an toàn)

| Tập tin | Dòng | Chức năng |
|---|---|---|
| `src/lattice_zk/params.py` | 33–68 | `BdlopParams` và các kiểm tra trong constructor của nó: q nguyên tố ≡ 5 mod 8, `2√2 < √q` (63–65), `2·8κB < q` (66–68) |
| | 70–122 | Các đại lượng dẫn xuất: k, cận dịch (shift bound) κ, `B = γ−κ−1` (80–83), `8κB` (85–88), các kích thước, số bit của challenge-space (114–116), xác suất chấp nhận (acceptance probability) (118–122) |
| | 124–144 | `parameter_id` (SHA3-256 trên mọi trường và setup seed); `require_production_strength` (challenge space ≥ 2^256) |
| | 147–175 | Setup seed, `BDLOP_OPEN_128`, `TOY` |
| `src/lattice_zk/ring.py` | 1–9, 42–57 | Lý do của two-factor splitting; `validate_modulus`; `sqrt_minus_one` |
| | 60–103 | `center`; `poly_mul` negacyclic chính xác bằng phép thế Kronecker; `mat_vec` |
| | 106–114 | `is_invertible` (kiểm tra CRT, chỉ test dùng) |
| `src/lattice_zk/sampling.py` | 12–47 | `XofStream` SHAKE-256; `_rejection_sample` (không rút gọn theo modulo) |
| | 50–66 | R_q đều (key), ternary (randomness), mask trên [−γ+1, γ] |
| | 69–81 | `challenge_poly`: các sign bit, rồi Fisher–Yates như trong SampleInBall của ML-DSA |
| `src/lattice_zk/bdlop.py` | 24–56 | Các domain tag; kiểm tra integer/shape/reduction; kiểm tra witness ternary |
| | 59–108 | `CommitmentKey` (B1 = [I_n \| B1'], b2 = [0^n \| 1 \| b2']); (de)serialization canonical của `Commitment` |
| | 111–154 | `derive_key` (một key toàn cục từ `parameter_id`); `sample_randomness`; `commit`; `verify_opening` |
| `src/lattice_zk/opening_proof.py` | 31–51 | Các domain tag; `MAX_ATTEMPTS = 512`; hash Fiat–Shamir `H(tag‖pid‖u64(\|x\|)‖x‖enc(t)‖enc(w))` |
| | 54–90 | Entropy của prover; kiểm tra canonical-commitment; `hedged_mask_key` (SHA3-256, không có domain tag, D7) |
| | 93–136 | Một lần thử `_respond` (rejection khi và chỉ khi ‖z‖∞ > B); vòng lặp `prove_with_stats` |
| | 145–168 | `verify`: độ dài chính xác, dải packed, w' được tính lại, so sánh seed kiểu constant-time |
| `src/lattice_zk/equality_proof.py` | 44–82 | Các tag; `MAX_ATTEMPTS = 4096` (sửa D4); Fiat–Shamir trên cả hai commitment và (w_a, w_b, u) |
| | 89–149 | Kiểm tra witness (cùng message); prover với hai mask mỗi lần thử |
| | 162–193 | `verify` |
| `src/lattice_zk/codec.py` | 10–33 | Packing canonical độ rộng cố định; zero padding và kiểm tra dải |
| | 36–60 | Mã hóa payload đơn ánh (độ dài 2 byte, 3 byte mỗi hệ số) và decoder exact-image |
| `src/lattice_zk/linkage.py` | 29–64 | Hash context của linkage; equality proof giữa hai video commitment |
| `src/lattice_zk/video_proof.py` | 26–41 | Các tag và bố cục (layout) của envelope |
| | 70–102 | Mã hóa độ rộng cố định của `VideoStatement` (274 byte) và `statement_id` |
| | 126–154 | Domain separation của video-commitment; kích thước envelope; `build_statement` |
| | 157–225 | Encode/decode envelope (bố cục nghiêm ngặt, `pid` được pin, t canonical); `create_envelope`; `verify_envelope` |
| | 246–289 | Envelope registered (chỉ proof): create, parse session, verify |
| | 294–415 | Disclosure zero-knowledge: context, `Com(enc(p); 0)`, equality proof, decoding nghiêm ngặt |
| `src/lattice_zk/video_pipeline.py` | 135–213 | Relation descriptor (key, credential, digest holder-id); `pins_from_registry` (chữ ký, epoch floor, đúng một match, production strength) |
| | 216–235 | Session binding; key carrier-order công khai |
| | 250–297 | Embed: bố cục placeholder, rồi statement, rồi proof (phía prover) |
| | 300–402 | **Đường dẫn verification**: kiểm tra cấu hình bao gồm việc tính lại relation-id (D6, 300–326); extraction và re-chunking canonical (D1, 351–367); statement do verifier dựng (369–389); session `verify_and_consume` (390–397) |
| `src/registry/zkp_registry.py` | 30–101 | Tập trường của descriptor; `relation_id` = SHA-256 trên JSON canonical |
| | 104–168 | Registry đã ký: root, các byte ký, verify ML-DSA-65, `resolve` |
| | 170–220 | `verify_statement_binding`: chỉ `lazer-v1`, không được BDLOP dùng (D10) |
| `src/registry/zkp_sessions.py` | 113–155 | Digest của challenge; `issue` (32 byte mới từ `secrets`, `BEGIN IMMEDIATE`) |
| | 157–241 | `is_active`; `consume` nguyên tử (`UPDATE … WHERE consumed_at IS NULL AND expires_at > now`); `verify_and_consume` |
| `src/transport/blind_payload_chunks.py` | 10–44 | Header của chunk và `payload_chunk_count` |
| | 47–81 | `pack_payload_chunks` (verifier tính lại cái này cho D1) |
| | 84–137 | `assemble_payload_chunks` |

Các tài liệu hỗ trợ:

| Tập tin | Nội dung |
|---|---|
| `docs/LATTICE_ZK_BDLOP_SPEC.md` | Đặc tả giao thức (§3), lập luận an toàn phi hình thức (§4), các sai khác so với BDLOP (§6), các giới hạn (§7) |
| `docs/paper/sections/security.tex` | Mô hình, các game, phát biểu định lý |
| `docs/paper/sections/security_appendix.tex` | Các chứng minh đầy đủ; đối chiếu chéo đặc tả/mã; các khác biệt (discrepancies) D1–D11 |
| `docs/paper/tables/params.tex` | Bảng tham số |
| `research/bdlop_params/estimate.py`, `bdlop_open_128_v2.estimate.json` (v1: `bdlop_open_128.estimate.json`) | Ước lượng core-SVP (mô hình CRYSTALS security-estimates) |
| `research/bdlop_params/lattice_estimator_crosscheck.py`, `.json`, `CROSSCHECK.md` | Đối chiếu chéo độc lập với lattice-estimator |
| `research/bdlop_params/kat.py`, `kat_v2.json` (v1: `kat_v1.json`) | Bộ sinh KAT và các digest được pin (commitment, opening proof, equality proof, key) |

## Trạng thái của các phát hiện tự đánh giá

Phụ lục liệt kê các khác biệt D1–D11. D1–D4 và D6 đã được sửa, mỗi mục có một
negative test. D8 đã được giảm thiểu: mọi điểm vào (entry point) của verifier
đều yêu cầu một canonical commitment. **D5, D7, D9, D10 và D11 vẫn còn mở
(open).** Chúng được phát biểu lại dưới dạng câu hỏi trong QUESTIONS.md.
