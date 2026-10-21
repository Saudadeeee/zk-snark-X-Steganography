# Lý thuyết

Mục đích: tóm tắt nền tảng mật mã của hệ thống và liên kết tới đặc tả/chứng minh chính thức; không lặp lại chứng minh.
cập nhật: 2026-10-22

Tài liệu chính thức: `docs/LATTICE_ZK_BDLOP_SPEC.md` (đặc tả + lập luận bảo
mật), `docs/paper/sections/security.tex` và `security_appendix.tex` (mô hình,
định lý, chứng minh), `docs/review/{CLAIMS,QUESTIONS,CHECKLIST}.md` (đối chiếu
claim↔code↔test, câu hỏi mở cho reviewer). Phần dưới chỉ tóm tắt và dẫn chiếu.

## 1. Cam kết BDLOP trên `R_q`

- Vành `R = Z[X]/(X^N+1)`, `R_q = R/qR`; `q` nguyên tố, `q ≡ 5 (mod 8)` để
  `X^N+1` tách thành đúng hai nhân tử bậc `N/2` và mọi `y` nhỏ (`‖y‖∞ < √(q/2)`)
  khả nghịch (Lyubashevsky–Seiler).
- Cam kết của Baum–Damgård–Lyubashevsky–Oechsner–Peikert (SCN 2018,
  ePrint 2016/997): khóa `B1 = [I_n | B1']`, `b2 = [0^n | 1 | b2']` nở từ
  `parameter_id` (không trapdoor, không trusted setup). Cam kết của message `m`:
  `t1 = B1·r`, `t2 = ⟨b2, r⟩ + m` với randomness ternary `r ← S_1^k`,
  `k = n + λ + 1`.
- Code: `src/lattice_zk/bdlop.py`, `ring.py`/`fast_ring.py`, `sampling.py`.

## 2. Bằng chứng opening — Fiat–Shamir-with-aborts

- Σ-protocol chứng minh biết opening của cam kết, chuyển non-interactive bằng
  Fiat–Shamir. Masking **đồng đều** kiểu ML-DSA (thay Gaussian của bài gốc):
  `y ← [−γ+1, γ]^{kN}`, thách thức `c = SampleInBall(seed)` trọng số `κ`, đáp
  `z = y + c·r`, **chấp nhận iff `‖z‖∞ ≤ B = γ − κ − 1`** (rejection sampling /
  "with aborts"). Không gì từ lần thử bị loại rời khỏi prover.
- Xác suất chấp nhận mỗi lần ≈ **0.191**; kỳ vọng số lần ≈ 5.23 (đo 4.68 với v1;
  **v2 cần đo lại**). Cap 512 lần → xác suất fail `< 2^{-156}`.
- Code: `opening_proof.py` (`prove`, `verify`), seed Fiat–Shamir hút
  `statement.to_bytes()`. Chi tiết: SPEC §3.3–3.4, §4.1–4.2.

## 3. Relaxed opening và chặn binding `8κB` (ℓ∞)

- Hai transcript chấp nhận cùng `(w)` khác thách thức cho `(r̄, f)` với
  `f = c − c'` (`‖f‖∞ ≤ 2`, khả nghịch) và `‖r̄‖∞ ≤ 2B`: một **relaxed opening**,
  định nghĩa message `m̄ = t2 − f⁻¹⟨b2, r̄⟩`.
- **Binding** đối với relaxed opening quy về **M-SIS** cho `B1` với nghiệm chuẩn
  `ℓ∞ ≤ 8κB ≈ 2^25.9` (`params.binding_norm_bound = 8·κ·B`). Constructor
  `BdlopParams` từ chối mọi set có `2·8κB ≥ q`. Lưu ý: view ℓ2 là vô nghĩa
  (`√(kN)·β > q`), nên an toàn **chỉ** dựa trên M-SIS theo ℓ∞ với chặn lớn
  (`β/q ≈ 1/17`) — đây là câu hỏi mở Q2 cho reviewer.
- SPEC §4.3–4.4; `docs/review/QUESTIONS.md` Q2, Q4.

## 4. Hiding — M-LWE

- Với mỗi `m` cố định, `(t1, t2)` ánh xạ song ánh công khai sang một mẫu M-LWE
  rank `λ`, `n+1` ring samples, bí mật/nhiễu ternary. Hiding quy về M-LWE.
- SPEC §4.5; QUESTIONS Q5.

## 5. Equality / linkage và disclosure

- **Equality proof** (`equality_proof.py`): chứng minh hai cam kết `t_a, t_b`
  giấu **cùng** message (dùng chung `f`). Cap 4096 lần (fix D4) → fail
  `≈ 2^{-220}`. Kích thước equality proof (v2): **16 160 byte**.
- **Linkage** (`linkage.py`): liên kết hai cam kết video, hoặc một cam kết video
  với một credential, cùng giấu một payload.
- **Disclosure** (SPEC §3.7): tiết lộ payload `p` của cam kết `t` cho một người
  nhận, bằng equality proof giữa `t` và `Com(encode(p); 0) = (0, encode(p))`,
  ràng buộc vào `statement_id` + `nonce` người nhận chọn — **không lộ
  randomness `r`**. Kích thước: `39 + |p| + 16 160` byte. Disclosure có thể
  chuyển nhượng cho bên thứ ba tin nonce tươi.

## 6. Binary proof và payload range proof (tùy chọn, ngoài băng)

Hai bằng chứng tùy chọn trên cùng vành, **không** đổi gì trong đặc tả opening;
hiện gửi **ngoài băng (out-of-band)**:

- **Binary proof** (`binary_proof.py`, `docs/BINARY_PROOF_DESIGN.md`): chứng minh
  một cam kết nền giấu một chuỗi nhị phân 256-bit. Đo (v1 base): **41 870 byte**,
  verify ~**72 ms**, soundness **150 bit** (`binary_proof_bench.json`, 20 lượt).
- **Payload range proof** (`payload_range_proof.py`,
  `docs/PAYLOAD_RANGE_PROOF.md`): chứng minh một cam kết payload (của §3.2) giấu
  `encode_payload(p)` cho **độ dài công khai `L ≤ 128` byte** (lộ `L`). Đo
  (v2 base): **44 558 B (L≤32)**, 53 774 B (L=64), 62 990 B (L=96),
  72 206 B (L=128); verify ~228 ms (L=32); soundness 150 bit
  (`payload_range_proof_bench.json`, 10 lượt).
- Điểm mở: cả hai là giao thức bốn-vòng non-interactive bằng seed xâu chuỗi;
  chưa nối trực tiếp vào envelope (ngoài băng); range proof lộ `L`; phiên bản
  giấu-độ-dài hoặc range 24-bit đầy đủ **chưa có**. Xem QUESTIONS Q16, SPEC §7.

## 7. Ràng buộc statement vào video và phiên

- Statement `x` (xem `02_kien_truc.md` §4) ràng buộc: relation, registry
  gốc/epoch, codec policy, carrier profile, **session_challenge**,
  `carrier_count`, `positions_hash`, `video_commitment`. Verifier tự tính lại
  mọi trường từ luồng H.264; chỉ `N_s` (số segment/kích thước) đọc từ envelope
  và cũng nằm trong `x`.
- `video_commitment` băm trên digest `D` của video đã **chuẩn hóa carrier**:
  các vị trí carrier được chuẩn hóa về vector hệ số, phần còn lại băm nguyên, nên
  bằng chứng ràng buộc video mà không phụ thuộc chính bit của nó. **Codec policy
  v2 (fix D5, opt-in)** băm toàn bộ RBSP của NAL IDR mang carrier (kể cả bit 0
  sau stop bit), gắn tag segment raw, và ghim phân đoạn đúng theo access-unit.
- Phiên một-lần chống phát lại; stateless mode **không** chống phát lại.
- SPEC §3.6, §4.7; QUESTIONS Q11, Q13.

## 8. Chọn carrier và STC

- Carrier là các vị trí hệ số CAVLC **ổn định** (suy lại được từ stego), được
  xáo trộn theo khóa đồng bộ. Soundness và zero-knowledge **không** phụ thuộc
  khóa này; khóa chỉ quyết định tính không phát hiện được.
- **STC** (syndrome-trellis codes, carrier `adaptive-stc-magnitude-video-only-v1`,
  `src/core/adaptive_carriers.py`, `docs/ADAPTIVE_CARRIERS.md`) giảm số thay đổi
  trên mỗi bit nhúng (giảm méo) để khó bị steganalysis học máy hơn.

## 9. Mô hình bảo mật (mức cao)

- Chứng minh trong **classical ROM** dưới M-SIS, M-LWE, SHA-2/SHA3 collision,
  ML-DSA-65 EUF-CMA. **Không** có định lý QROM; từ dùng là "plausibly
  post-quantum" (SPEC §5).
- Tính chất thiết lập: HVZK của transcript chấp nhận; special/knowledge
  soundness (relaxed, có tổn thất căn bậc hai của forking lemma); binding theo
  relaxed opening; hiding M-LWE; chống phát lại (store mode); authenticity
  (registered); linkage. Toàn bộ đối chiếu claim↔code↔test trong
  `docs/review/CLAIMS.md`.

## 10. Chọn tham số (v1 vs v2, vì sao λ=7)

Parameter set sản xuất `bdlop-open-128-v2` (`src/lattice_zk/params.py`):

| | giá trị |
|---|---|
| `N`, `q` | 256, `2^30 − 35` |
| `n` (M-SIS), `λ` (M-LWE), `k` | 6, 7, 14 |
| `κ`, `γ`, `B` | 60, `2^17`, `2^17 − 61` |
| `|C|` | ≈ `2^257` |
| Commitment / opening proof / equality proof | 6 720 / 8 096 / 16 160 byte |

Mức core-SVP (classical / quantum), từ `research/bdlop_params/estimate.py` +
đối chiếu lattice-estimator (`CROSSCHECK.md`):

- **M-SIS (binding)**: 140 / 127 bit.
- **M-LWE (hiding)**: 164 / 150 bit (dual hybrid; primal 169 / 153).

**Vì sao λ=7**: set cũ `bdlop-open-128-v1` (λ=6, k=13) có cùng M-SIS nhưng M-LWE
dual-hybrid chỉ **135 / 123** bit (quantum < 128). Nâng `λ` lên 7 khôi phục biên
lượng tử cho hiding (150 bit) với chi phí envelope lớn hơn ~8 %. **M-SIS quantum
vẫn 127 < 128** — xem `06_han_che_va_huong_phat_trien.md`.
