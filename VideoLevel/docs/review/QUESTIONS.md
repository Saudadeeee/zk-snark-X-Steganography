# Các câu hỏi mở dành cho người đánh giá

Các câu hỏi được xếp hạng theo mức độ lập luận an toàn sẽ đổ vỡ nếu câu trả
lời là "không". Mỗi câu hỏi nêu tên tuyên bố mà nó liên quan, dùng các nhãn
của `docs/paper/sections/security.tex` và `security_appendix.tex`, cùng mã
nguồn mà nó phụ thuộc vào. Số dòng ứng với commit `18c5123`. "Quan điểm của
chúng tôi" đánh dấu điều mà các tác giả hiện tin là đúng, để người đánh giá
có thể xác nhận hoặc bác bỏ nhanh.

---

## Hạng 1: các định lý chính phụ thuộc vào những điều này

### Q1. Mô phỏng aborting prover trong classical ROM (Bổ đề `lem:sim`, hybrid G3)

Simulator không bao giờ tái tạo các truy vấn random-oracle của những lần thử
bị rejected. Lập luận gồm hai phần: (a) việc chấp nhận *hoàn toàn* độc lập với
witness và với `c` (Bổ đề `lem:hvzk`); (b) mọi điểm truy vấn ẩn đều chứa
`w = B1·y` với min-entropy ít nhất `η = nN·log2(2B+1) ≈ 27 647` bit, bởi vì
`B1 = [I_n | B1']`. Tổn thất (loss) trên mỗi proof là
`2(Q_H+Q_P)2^-256 + (A_max+1)(Q_H+(A_max+1)Q_P)2^-η`.

- Điều này có tránh đúng cái lỗ hổng trong các chứng minh CMA-to-NMA trước đây
  của Fiat–Shamir with aborts — lỗ hổng mà Barbosa et al. (CRYPTO 2023) đã phát
  hiện và Devevey et al. đã phân tích — hay không? Cụ thể, liệu việc thay
  challenge của một lần thử bị rejected bằng một `h_i` đều (uniform) mà không
  bao giờ được ghi vào `H_fs` có hợp lệ (sound) hay không, khi mà `y_i` đến từ
  một hedged stream chứ không phải từ coin tươi (fresh coins) (G1–G2)?
- Cận min-entropy cho một mask *với điều kiện bị rejection* có đúng không? Bài
  báo dùng `η_y − log2(1/(1−p_acc))`, điều này cần `η_y − 0.35 ≥ η`.
- Quan điểm của chúng tôi: đúng trong classical ROM. Tính chất exact-uniformity
  là thứ làm cho trường hợp này đơn giản hơn trường hợp Gaussian.
- Mã: `opening_proof.py:77–136`, `sampling.py:60–66`.

### Q2. Soundness của relaxed-opening tại cận ℓ∞ 8κB (Định lý `thm:binding`, `thm:se`)

Hai transcript được trích xuất cho ra `(r̄, f)` với `‖r̄‖∞ ≤ 2B` và `f ∈ C̄`.
Binding chống lại hai relaxed opening cần M-SIS cho `B1` với
`‖x‖∞ ≤ β = 8κB = 62 885 280 ≈ 2^25.91`, tức khoảng `q/17`. Constructor cưỡng
chế `2β < q` (`params.py:66–68`).

- `‖f'r̄ − f r̄'‖∞ ≤ ‖f'‖₁‖r̄‖∞ + ‖f‖₁‖r̄'‖∞ = 8κB` có phải là cận đúng để
  ước lượng không, và `2β < q` có phải là điều kiện phụ (side condition) đúng
  không? (Nó làm cho `x ≢ 0 mod q` tương đương với `x ≠ 0` trên ℤ.)
- Góc nhìn ℓ2 là rỗng (vacuous): `√(kN)·β ≈ 2^31.75 > q`, nên `q·e1` đã thỏa
  cận ℓ2 (lattice-estimator báo cáo "trivially easy"). Do đó an toàn hoàn toàn
  dựa vào ℓ∞ M-SIS với một cận lớn. Các mô hình chi phí (cost model) ℓ∞
  (CRYSTALS `SIS_linf_cost` và lattice-estimator `SIS.lattice`, norm=∞) có đủ
  chính xác khi gần `q` đến vậy không? Có tấn công nào khai thác `β/q ≈ 1/17`,
  ví dụ nhiều tọa độ gần `±q/2` hoặc mẹo ζ zeroing các tọa độ, hay không? Điểm
  tối ưu của estimator đã chọn ζ = 0.
- Cận có thể siết chặt hơn không? Ví dụ, trích xuất với một hiệu challenge cố
  định, hoặc dùng cấu trúc `r̄ = z − z'` (cả hai đều trong `[−B, B]`). Quan điểm
  của chúng tôi: 8κB là một trường hợp xấu nhất (worst case) đúng nhưng lỏng
  (loose).
- Số liệu: β = 480, 140 / 127 bit (core-SVP classical/quantum) từ cả hai
  estimator. Xem `research/bdlop_params/CROSSCHECK.md`.

### Q3. Tính khả nghịch của các hiệu challenge với q ≡ 5 mod 8 (Bổ đề `lem:invertible`)

Bài báo trích dẫn Lyubashevsky–Seiler (EUROCRYPT 2018), Hệ quả 1.2 với
k = 2: mọi `y` khác không với `‖y‖∞ < √(q/2) ≈ 23 170` đều khả nghịch, và
`‖f‖∞ ≤ 2` với `f ∈ C̄`.

- Xin xác nhận rằng các giả thiết thỏa: q nguyên tố, q ≡ 5 (mod 8), N = 256.
  Khi đó `X^N+1 = (X^{N/2} − ρ)(X^{N/2} + ρ)` với `ρ² ≡ −1`, cả hai nhân tử
  đều bất khả quy (cấp của q modulo 2N là N/2).
- Kiểm tra sơ cấp cho k = 2, mà chúng tôi tin là đủ: viết
  `f = a(X) + X^{N/2}·b(X)`. Khi đó `f ≡ a ± ρb` trong mỗi nhân tử. Vì mỗi
  nhân tử là bất khả quy, `f` là non-unit chỉ khi `a_i ≡ ∓ρ b_i` với mọi i.
  Điều đó cho `a_i² + b_i² ≡ 0 (mod q)` với `0 < a_i² + b_i² ≤ 8 < q`, là điều
  không thể xảy ra. Lập luận này có kín kẽ (airtight) không?
- Mã: `ring.py:42–57` (kiểm tra modulus, `√−1`), `params.py:63–65` (constructor
  kiểm tra `2√2 < √q`), `ring.py:106–114` (`is_invertible`, chỉ dùng trong
  test).

### Q4. Tổn thất extraction và ý nghĩa của "knowledge soundness" (Định lý `thm:se`, Bổ đề `lem:fork`)

Cận này có tổn thất căn bậc hai (square-root loss) thường thấy của general
forking lemma: với `Q_H = 2^64`, một xác suất extraction là `2^-128` chỉ cho
`ε ≲ 2^-32`.

- Định lý có đáng phát biểu ở dạng này không, hay tuyên bố chính nên đi theo
  hướng SelfTargetMSIS chặt (tight) (Kiltz–Lyubashevsky–Schaffner 2018)? Cái
  giá phải trả là một giả định phi tiêu chuẩn (non-standard) mà ở đây không có
  ước lượng riêng.
- Extractor chỉ xuất ra một opening *relaxed*. Message được trích xuất
  `m̄ = t2 − f⁻¹⟨b2, r̄⟩` không nhất thiết nằm trong ảnh (image) của payload
  encoder (`codec.py:49–60`). Gọi tính chất này là "knowledge soundness ràng
  buộc với statement" có chính xác không, khi mà statement chỉ ràng buộc với
  "một message nào đó" mà một disclosure về sau phải khớp? (Đã được giải quyết
  một phần kể từ đó: payload range proof tùy chọn, Q16, cho thấy message được
  trích xuất là `encode_payload(p)` cho một độ dài công khai `L`.)
- Trường hợp programmed-point trong Định lý `thm:se` (một adversary tái sử dụng
  `(x_i, t_i, w_i)` với một `z` mới) có bao quát cả một `z` bị mauled với cùng
  seed không? Bài báo biến trường hợp này thành một lời giải M-SIS có norm ≤ 2B.

### Q5. Instance M-LWE hiding và leakage qua các proof (Định lý `thm:hiding`, Bổ đề `lem:mlwe-instance`)

Hiding ánh xạ `Com(m; r)` thành một mẫu M-LWE hạng (rank) λ = 7 với n+1 = 7
ring sample: `A ∈ R_q^{7×7}`, secret và error ternary đều. Khi làm phẳng
(flattened), đây là LWE với n = 1792, m = 1792, q = 2^30−35 và σ = √(2/3).

- Ánh xạ `(t1 − B'_{1,2}(t2 − m), t2 − m) = A·r3 + (r1, r2)` có phải là song
  ánh (bijection) với m cố định không, và `A` có đều không? Quan điểm của chúng
  tôi: có. D11 đã sửa một lỗi gõ (typo) trong đặc tả.
- Ước lượng (xem CROSSCHECK.md). Primal uSVP: β = 580, 169 / 153 bit.
  **Dual-hybrid trong mô hình "rough" của lattice-estimator: β = 564, 2^164.9
  classical, và β = 567, 2^150.3 quantum.** Con số này thấp hơn 169 / 153 bit
  của các script primal/dual của CRYSTALS và chính là mức 164 / 150 được tuyên
  bố. (Với `bdlop-open-128-v1`, λ = 6, cùng tấn công đó cho 2^135.2 / 2^123.3,
  đó là lý do λ được nâng lên 7.) ~164 bit có phải là con số tiêu đề (headline)
  đúng không? Liệu một tấn công hybrid lên một secret ternary đều, chỉ với 1792
  sample, có nên được coi là nằm ngoài phạm vi estimator bao quát không?
- Leakage. Các registered credential được chứng minh nhiều lần với cùng `r`.
  Mỗi `z` được chấp nhận đều phân bố chính xác đều trên `[−B, B]^{kN}`, độc lập
  với `r`. Có output nào khác phụ thuộc vào `r` không? Các ứng viên: số lần thử
  (attempt count), vốn độc lập với witness; timing (CHECKLIST §7); và hedged
  mask key (Q7). Có cái nào trong số này cho một "hint" M-LWE không?

### Q6. Zero knowledge từ rejection sampling với các mask đều (Bổ đề `lem:hvzk`)

Các mask phân bố đều trên `[−γ+1, γ]`, vốn bất đối xứng. Một response được
chấp nhận khi và chỉ khi `‖z‖∞ ≤ B = γ − κ − 1`. Vì `‖c·r‖∞ ≤ κ`, mỗi
`z_i ∈ [−B, B]` tương ứng với đúng một giá trị mask trong `[−γ+1, γ−1]`.

- Xin xác nhận rằng việc chấp nhận là chính xác
  `p_acc = ((2B+1)/2γ)^{kN} ≈ 0.1912` với mọi witness và challenge, và rằng
  `z` được chấp nhận là chính xác đều trên `Z`. Cũng xin xác nhận rằng
  `B = γ − κ − 1` là cận lớn nhất giữ được tính chất này.
- Mask sampler rút các giá trị 18-bit nhỏ hơn `2γ = 2^18`, nên hoàn toàn không
  có rejection nào (`sampling.py:60–66`). Vậy tuyên bố exact-uniformity có miễn
  nhiễm với sampler bias không?
- Test chi-square `test_accepted_response_coordinate_is_uniform_for_any_witness`
  chỉ kiểm tra các phân phối biên (marginal) trên một bộ tham số rất nhỏ. Người
  đánh giá có muốn một kiểm tra thực nghiệm mạnh hơn không?

---

## Hạng 2: các lựa chọn thiết kế có thể thay đổi tham số hoặc câu chữ

### Q7. Suy dẫn hedged mask và domain separation của nó (D7, open)

`K = SHA3-256(e ‖ u64(|x|) ‖ x ‖ u64(|t|) ‖ t ‖ u64(|r|) ‖ r)`, với 32
byte entropy `e` (`opening_proof.py:77–90`). Các mask là
`y_i = SHAKE-256("…/bdlop-open/v1/mask\0" ‖ K ‖ u32(i))`. Equality proof
dùng mask tag riêng của nó nhưng cùng cách dựng `K`, trên cả hai commitment
và cả hai witness (`equality_proof.py:124–131`).

- Đầu vào SHA3-256 không có domain tag. Việc tách biệt nó khỏi các lần dùng
  SHA3-256 khác (có tag) dựa vào việc `e` là đều. Có nên thêm một tag không?
  Điều này thay đổi các KAT. Cách xử lý ROM đối với `H_hg` trong G1 có còn đúng
  khi `e` đến từ một RNG yếu không?
- Việc ràng buộc `K` với `(x, t, r)` có đủ để chống lại các tấn công fault và
  nonce-reuse kiểu "cùng mask, hai challenge" không? Opening proof và equality
  proof không bao giờ dùng chung `K`, vì đầu vào và mask tag của chúng khác
  nhau.

### Q8. Equality proof: việc chấp nhận, attempt cap và biến thể disclosure (Bổ đề `lem:eq-ss`, Định lý `thm:link`; D4 đã sửa)

Một lần thử được chấp nhận với xác suất `p_acc² ≈ 0.0463`. Cap là 4096, cho
một xác suất thất bại khoảng `2^-279` (`equality_proof.py:46–64`).

- Một cap lớn hơn có "miễn phí" đối với zero knowledge không? `A_max` chỉ đi
  vào `ε_zk` thông qua các số hạng `2^-η`. Quan điểm của chúng tôi: có.
- Disclosure chứng minh đẳng thức giữa `t` và `Com(enc(p); 0) = (0, enc(p))`
  với witness `r_b = 0`, nên `z_b = y_b`. Simulator cho witness suy biến
  (degenerate) này có còn đúng không? Extraction có thực sự buộc `r̄_b = 0` trừ
  khi M-SIS bị phá không (phụ lục, "Disclosure by proof")?
- Announcement `u = ⟨b2, y_a − y_b⟩` tiết lộ một tổ hợp tuyến tính của các
  mask. Min-entropy chỉ qua `w_a` có đủ cho lập luận hidden-query không?

### Q9. Một commitment key toàn cục duy nhất (D9, open)

`ck` được mở rộng bằng SHAKE-256 từ `parameter_id`, vốn cố định và công khai
(`bdlop.py:111–123`). Mọi người dùng và mọi registry đều dùng chung một ma
trận M-SIS và một ma trận M-LWE.

- Một lần lattice reduction (một lần duy nhất) với chi phí khoảng 2^140 chống
  lại `[I | B1']` sẽ phá binding cho mọi commitment từng được tạo. Multi-target
  hiding mất một thừa số Q trong Bổ đề `lem:row`. Key có nên là per registry
  hoặc per issuer không, ví dụ suy dẫn từ registry root? Phát biểu
  concrete-security có chấp nhận được với một key duy nhất không?
- Một key suy dẫn từ dữ liệu công khai trong ROM ("nothing up my sleeve") có
  phải là một mô hình thỏa đáng cho một key đều trong các reduction không? Phụ
  lục program điểm key-expansion trước khi adversary bắt đầu.

### Q10. Fiat–Shamir trong QROM (Mục `sec:sec-qrom`; không tuyên bố định lý nào)

Mọi định lý đều ở classical-ROM. Bài báo nói "plausibly post-quantum" và trích
dẫn Barbosa et al. (QROM CMA-to-NMA cho Fiat–Shamir with aborts), Don et al.
2019 và Liu–Zhandry 2019.

- Các kết quả measure-and-reprogram của Don et al. có áp dụng được cho một
  Σ-protocol với relaxed special soundness và một aborting prover không? Nếu
  có, nên trích dẫn mức loss nào? "plausibly post-quantum" có phải là cách diễn
  đạt trung thực không, hay nên yếu hơn?
- Challenge seed có 256 bit và `|C| = 2^257`. Điều đó có đủ để chống lại tìm
  kiếm kiểu Grover trong cận soundness QROM không? Quan điểm của chúng tôi: có,
  đủ cho mức an toàn 128-bit quantum.

### Q11. Statement binding và tính duy nhất của các encoding (Định lý `thm:se`, các mục phụ lục 1, 2, 5)

Opening proof hash
`SHAKE-256(tag ‖ pid ‖ u64(|x|) ‖ x ‖ enc(t) ‖ enc(w))`. Chỉ `x` được
length-prefix; `t` (6 720 byte) và `w` (n·N từ (word) 64-bit big-endian) có
độ dài cố định bởi `pid` (`opening_proof.py:43–51`). Statement là một chuỗi
độ rộng cố định 274 byte (`video_proof.py:89–98`).

- Transcript có đơn ánh không? Nó có bao gồm mọi thứ mà statement của extractor
  cần không? Nó hash `t1` và `t2`, nhưng không hash chính `ck`, cái mà `pid`
  xác định.
- Verifier chỉ lấy `N_s` từ envelope, và `N_s` là một phần của `x`. Nó đọc
  mọi trường statement khác từ các pin của chính nó và từ
  `Read(vid*)` (`video_pipeline.py:369–389`). Xin kiểm tra xem có đường dẫn nào
  mà một giá trị do prover kiểm soát đi vào `x` mà không được xác minh không.
- Các domain tag (key, randomness, Fiat–Shamir và mask cho opening và equality,
  challenge-poly; mỗi tag kết thúc bằng NUL byte duy nhất của nó) có prefix-free
  trên *tất cả* các lần dùng SHAKE-256 không, bao gồm cả các seed `XofStream`?
- Payload encoding có độ dài 2 byte và 3 byte mỗi hệ số (`codec.py:36–60`).
  Decoder "exact image" có đủ cho tuyên bố disclosure `enc(p) = m̄` không?

### Q16. Binary và payload range proof: Fiat–Shamir with aborts và liên kết tới payload (Định lý `thm:bin-ks`, `thm:pay`)

Binary proof (`binary_proof.py`) và payload range proof
(`payload_range_proof.py`, `docs/PROOF_NHI_PHAN_VA_KHOANG.md`) là các giao thức
bốn vòng (four-round) được biến thành non-interactive bằng các seed xâu chuỗi
(chained); chỉ vòng cuối lặp lại khi abort. Payload range proof cho thấy rằng
một payload commitment đang tồn tại che giấu (hides) `encode_payload(p)` cho
một độ dài công khai `L ≤ 128`.

- Định lý `thm:bin-ks` (knowledge soundness) cho extractor xác suất thành công ít
  nhất `ε − (Q+1)·ε_rbr − Σ_i sqrt((Q+1)·α_i) − β − δ_coll`, với
  `δ_coll = 13·(Q+4)²·2^-256` (thứ tự seed, seed không mới đối với `Expand`/`G`,
  và việc `s3` xác định tiền tố trên mọi lần chạy tua lại); soundness có nghĩa đi
  qua binding (Hệ quả `cor:bin-sound`), vì hầu như mọi `C` có relaxed opening tới
  mọi message: extractor Σ-protocol
  của AFK22 chỉ fork challenge oracle, và mỗi vòng thống kê (statistical round)
  (lift, check, combine) được chặn so với các message bị ràng buộc về mặt tính
  toán (computationally bound) bằng một lập luận đa số (plurality) cộng với một
  forking M-SIS finder. Bước plurality có đúng không, và AFK22 có bao quát một
  prefix mà adversary chọn thông qua ba oracle khác không?
- Liên kết `m = e_L + A β` được gộp (folded) vào các check functional với một
  `ρ^L_t` tươi, và các bit polynomial được commit trong auxiliary commitment
  *trước* lift challenge, với các lift được thêm vào sau dưới cùng randomness
  `r'`. Cả hai bước có sound không (một error vector, một functional đều; các
  hàng (row) BDLOP tăng dần (incremental) dưới một `r'`)?
- Range proof được mang in-band, nên đối thủ của trò chơi SE thấy các range proof
  trung thực. Định lý `thm:pay-se` (simulation-extractability) thay chúng bằng bộ
  mô phỏng (`Q_P·Adv^MLWE_aux + ε_zk`), biến một điểm `H_4` đã lập trình bị dùng
  lại thành một nghiệm M-SIS chuẩn `≤ 2B` cho `B1` hoặc `B1'`, và áp dụng
  `thm:bin-ks` với `Q' = Q + 7Q_P`, đếm cả các truy vấn `H_1..H_3` của bộ mô
  phỏng trong lập luận plurality. Phác thảo đó có đúng không, đặc biệt khi tiền tố
  `(x, C, D, h)` của proof giả mạo là của một proof trung thực (với `D` đều sau
  bước lai M-LWE)?
- Quan điểm của chúng tôi: đúng như đã phác thảo; sai số theo vòng là tổng
  `ε_rbr ≈ 2^-149.0` (số hạng lớn nhất `2^-149.99`, `k = k' = 5`); các số hạng
  M-SIS là non-tight giống như với opening proof (Q4). Đánh giá nội bộ:
  `docs/review/INTERNAL_REVIEW_SOUNDNESS.md`.
- Mã: `payload_range_proof.py` (`_prove`, `_recomputed_seed`,
  `_check_challenges`), `binary_proof.py`.

---

## Hạng 3: kỹ thuật và câu chữ (không dự kiến thay đổi tham số)

### Q12. Cưỡng chế production-strength chỉ tại bước pin resolution (đã giải quyết)

`require_production_strength()` (challenge space ≥ 2^256) chạy trong
`pins_from_registry` (`video_pipeline.py:192–193`). Nó không chạy trong
`verify_video_proof`, `verify_envelope` hay `opening_proof.verify`. Một caller
tự dựng `VerifierPins` bằng tay với bộ `TOY` sẽ chấp nhận các toy proof. Mọi
entry point của verifier có nên từ chối các tham số non-production không?

- **Đã giải quyết.** `video_proof.require_verifier_parameters` nay chạy đầu
  tiên trong mọi verifier ở mức ứng dụng: `verify_video_proof` (bên trong bước
  kiểm tra cấu hình, trước khi video được đọc), `verify_envelope`,
  `verify_registered_envelope`, `verify_disclosure_proof`,
  `verify_commitment_disclosure`, `linkage.verify_linkage` và
  `pins_from_registry`. Mỗi hàm raise `ValueError` cho một bộ dưới 2^256 trừ
  khi caller truyền `allow_toy_parameters=True` (chỉ test và TOY benchmark).
  Các proof primitive (`opening_proof.verify`, `equality_proof.verify`,
  `binary_proof.verify`) vẫn là các khối dựng (building block) không phụ thuộc
  tham số; không có gì trong video pipeline gọi chúng ngoại trừ thông qua các
  verifier ở trên. Test: `src/runtest/test_hardening_d5_d7_d8.py` (các TOY pin
  dựng bằng tay bị từ chối).

### Q13. Ngữ nghĩa session và replay (Định lý `thm:replay`)

Chế độ store tiêu thụ (consume) `N_s` bằng một
`UPDATE … WHERE consumed_at IS NULL AND expires_at > now` có điều kiện duy
nhất bên trong `BEGIN IMMEDIATE` (`zkp_sessions.py:181–205`). Chế độ stateless
(`expected_session`) không cho bảo vệ chống replay nào, và không chế độ nào
ngăn được relaying. Đây có phải là cách phân chia các tuyên bố đúng không? Cận
precomputation `Q_H·Q_I·2^-256` cho (iii) có được phát biểu đúng không?

### Q14. Các mục tự đánh giá còn lại

- **D5** (đã giải quyết bằng một codec policy mới): phạm vi của canonical
  digest. Các mục chưa ràng buộc là các bit RBSP sau stop bit, các raw-segment
  digest không có tag, và phiên bản của segmenter. Codec policy v2
  (`CODEC_POLICY_V2`, opt-in theo từng carrier profile, các định danh
  profile/policy/relation mới) hash toàn bộ RBSP của các carrier IDR NAL unit
  kèm độ dài của nó, gắn tag cho các raw-segment digest và gắn type cho mọi
  segment digest, và pin việc phân đoạn (segmentation): các segment phải đúng
  là phân hoạch access-unit của đầu vào, kiểm tra từng byte một, nên digest
  không còn phụ thuộc vào segmenter. Phiên bản ffmpeg được cố ý không hash (nó
  sẽ ràng buộc cài đặt của verifier, chứ không phải video). Codec policy v1
  không đổi từng byte cho các video hiện có và vẫn để lại không ràng buộc các
  zero bit sau stop bit của một carrier NAL unit: một zero byte được chèn thêm
  ở đó được chấp nhận dưới v1 và bị từ chối dưới v2 thông qua transport thật
  (`test_zero_bits_after_the_stop_bit_are_accepted_by_v1_and_rejected_by_v2`).
- **D7** (đã giải quyết): hedged mask key được domain-separated bằng một tag,
  protocol label và parameter id. `bdlop-open-128-v1` giữ cách suy dẫn không
  tag, nên `kat_v1.json` không đổi; `kat_v2.json` và binary KAT đã được tái
  tạo (các commitment không đổi). Verification không bao giờ tính lại một mask;
  các proof từ cả hai cách suy dẫn đều verify được.
- **D8** (đã giải quyết): `Commitment` mang theo bộ tham số của nó và từ chối
  các hệ số non-canonical tại lúc construction, giữ các bản sao chỉ-đọc
  (read-only); các verifier vẫn kiểm tra lại các đối tượng được dựng quanh
  constructor.
- **D10** (open): `verify_statement_binding` chỉ phục vụ `lazer-v1`
  (`zkp_registry.py:170–220`). Đường dẫn BDLOP dùng `pins_from_registry`.
  Đây là vấn đề vệ sinh API (API hygiene).
- **D11** (open): đặc tả §4.2 trích dẫn một "ML-DSA specification,
  Appendix B" cho lập luận zero-knowledge. Xin xác nhận hoặc thay thế tham
  chiếu này.

### Q15. Phương pháp luận ước lượng cụ thể (concrete-estimate)

Core-SVP bỏ qua các chi phí phụ (overhead) của reduction, giống như với
ML-DSA. Mô hình chi phí MATZOV cho 194 / 190 (M-LWE primal/dual-hybrid) và 171
(M-SIS) bit. Việc báo cáo core-SVP 140/127 (M-SIS) và 164/150 (M-LWE, mức tối
thiểu dual-hybrid) có phải là quy ước đúng cho một tuyên bố 128-bit không? Con
số M-SIS quantum chỉ ngay dưới 128. Xem `research/bdlop_params/CROSSCHECK.md`.
