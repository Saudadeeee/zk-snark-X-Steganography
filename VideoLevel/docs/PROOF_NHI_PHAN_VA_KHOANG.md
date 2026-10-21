# Chứng minh nhị phân và chứng minh khoảng payload cho cam kết BDLOP

Tài liệu này gộp hai chứng minh tùy chọn trên cùng vành và cùng cam kết nền với
đặc tả opening (`docs/LATTICE_ZK_BDLOP_SPEC.md`): **chứng minh message nhị phân**
(roadmap B2) và **chứng minh khoảng payload** gắn chứng minh nhị phân vào payload
(stream C3). Cả hai đều là mã nghiên cứu chưa audit, không constant time, và
không đổi gì trong các bộ tham số nền, các chứng minh opening/equality, hay các
định dạng envelope. Phần tổng quan lý thuyết ở `docs/handoff/03_ly_thuyet.md`;
đây là tham chiếu kỹ thuật sâu hơn.

---

## Phần I — Chứng minh message nhị phân (roadmap B2)

Trạng thái: cài đặt là `src/lattice_zk/binary_proof.py` (bộ tham số
`bdlop-binary-128-v2` và `bdlop-binary-toy-v1`), test trong
`src/runtest/test_latticezk_binary_proof.py`, bản nháp định lý trong
`docs/paper/sections/binary_proof.tex` (chưa nối vào `main.tex`).
Mã nghiên cứu chưa audit; không constant time.

### 1. Cái gì được chứng minh

Statement: bytes `x` và một cam kết `C = (t1, t2) = Com(m; r)` tạo bởi
`bdlop.commit` dưới bộ nền không đổi `bdlop-open-128-v2`. Chứng minh cho thấy
tri thức về một relaxed opening của `C` mà message `m̄` của nó có mọi hệ số
trong `{0, 1}`, tức `C` giấu một chuỗi 256-bit (`encode_bits` / `decode_bits`,
32 byte, bit quan trọng nhất trước).

`C` là một cam kết nền thường, nên các chứng minh opening, equality và disclosure
áp dụng cho nó không đổi (test
`test_binary_commitment_stays_compatible_with_the_base_proofs`). Không gì trong
`bdlop-open-128-v2`, khóa của nó, các chứng minh của nó hay các định dạng
envelope thay đổi.

### 2. Quyết định thiết kế

#### 2.1 Vì sao không dùng ALS20 / ENS20 như đã công bố

ALS20 (Attema–Lyubashevsky–Seiler, CRYPTO 2020) chứng minh tích mức-vành
`m·(m − 1) = 0` trong `R_q`. Trong một vành tách thành `l` nhân tử, điều đó chỉ
làm mỗi slot CRT của `m` nằm trong `{0, 1}`, nên nó mã hóa `l` bit mỗi đa thức;
các *hệ số* nhị phân cần message ở các slot NTT của một vành tách hoàn toàn (hoặc
gần hoàn toàn) (ENS20, BLS19). Với `q ≡ 5 (mod 8)` vành của ta có hai slot: 2 bit
mỗi đa thức. Các lựa chọn đã cân nhắc:

- **(a) Modulus tách hoàn toàn mới** (`q ≡ 1 mod 2N`). Bị loại: khi đó các hiệu
  challenge không còn được bảo đảm khả nghịch, nên extraction chứng minh opening
  của đặc tả (§4.3) hỏng; product proof có lỗi theo-slot ≈ `1/q` và cần
  automorphism amplification của ALS20; binding/hiding sẽ cần một lượt estimator
  mới; cam kết sẽ không còn là một cam kết `bdlop-open-128-v2`.
- **(b) Mã hóa NTT-slot trên vành của ta.** Bất khả: hai slot.
- **(c) Đã chọn.** Giữ vành và cam kết nền; chứng minh quan hệ theo-hệ-số bằng
  linearization hằng-số/automorphism của LNP22 (Lyubashevsky–Nguyen–Plançon,
  CRYPTO 2022) và một chứng minh bậc-hai (product) kiểu ALS20. Vành của ta là
  trường hợp thuận lợi cho phần product: vì `c − c'` khả nghịch với các challenge
  phân biệt, một đa thức bậc-2 khác không trên `R_q` triệt tiêu trên nhiều nhất
  `2` challenge mỗi thành phần CRT, và `c ↦ c mod φ` đơn ánh trên tập challenge,
  nên vòng product có lỗi `2/|C| = 2^-256`. Cấu trúc dưới đây là instantiation
  của riêng ta về các kỹ thuật này; nó không sao chép từ bài báo nào, và chưa
  được các tác giả của chúng rà soát.

#### 2.2 Vì sao các "lift" phụ trợ là cần thiết

Với `σ(X) = X^-1` ta có `ct(σ(a)·b) = <a, b>`, và bất kỳ dạng bậc-hai nào mà một
honest verifier tới được từ một đa thức đã cam kết `m` bằng các phép vành, `σ` và
`ct` đều là `m^T T_w m` với `T_w` negacyclic Toeplitz. Đường chéo của nó là
`w_0·I`, nên nó chỉ bao giờ thấy `Σ m_j^2`, không bao giờ một dạng đường chéo
ngẫu nhiên `Σ γ_j m_j^2`. Tính nhị phân của mọi `N` hệ số cần các dạng đường chéo
ngẫu nhiên, nên prover phải cam kết `u_i = σ(γ_i ∘ m)` sau khi `γ_i` đã biết và
chứng minh tính nhất quán (tuyến tính trên Z_q, không phải trên R_q) của `u_i`
với `m`.

#### 2.3 Vì sao một cam kết phụ trợ mới

Nếu các lift được cam kết với randomness nền `r` (các slot BDLOP thêm), hai chứng
minh cho một cam kết sẽ công bố `t_u − t'_u = σ((γ − γ') ∘ m)` và lộ `m`. Do đó
mỗi chứng minh tạo một cam kết mới `D = Com_aux(u, g, G; r')` dưới khóa riêng của
nó (phân tách domain với khóa nền), và product proof dùng các masked opening của
cả `C` và `D` với một challenge, như equality proof làm. `C` có thể được chứng
minh nhị phân bao nhiêu lần tùy ý.

### 3. Giao thức (`binary_proof._prove`, `_recomputed_seed`)

`k` = số lần lặp lift, `k'` = số lần lặp kiểm (5 và 5 trong sản xuất);
`J` = đa thức toàn-một; mọi seed là đầu ra SHAKE-256 32 byte, mỗi cái phân tách
domain và móc xích với seed trước.

1. `γ_1..γ_k ← H_lift(pid, x, C)` (đều trong `Z_q^N`).
2. Prover: `u_i = σ(γ_i ∘ m)`, `g_t` đều với `ct(g_t) = 0`, `r'` tam phân mới;
   gửi `D = (B1' r', <b_{u_i}, r'> + u_i, <b_{g_t}, r'> + g_t)`.
3. `ρ_{t,i} ∈ Z_q^N, μ_{t,i} ∈ Z_q ← H_check(seed, D)`. Với
   `R_{t,i} = σ(γ_i ∘ σ(ρ_{t,i}))` prover gửi
   `h_t = g_t + Σ_i [σ(ρ_{t,i}) u_i − R_{t,i} m + μ_{t,i} u_i (m − J)]`
   không có hệ số hằng của nó (ngầm 0). Kiểm
   `ct(h_t) − ct(g_t) = Σ_i <ρ_{t,i}, Δ_i> + μ_{t,i} Q_i` với
   `Δ_i = u_i − σ(γ_i ∘ m)`, `Q_i = ct(u_i (m − J))`, và
   `Q_i = <γ_i, m ∘ (m − 1)>` khi `Δ_i = 0`
   (`test_check_polynomial_constant_term_is_the_random_functional_of_the_error`).
4. `α_t ∈ R_q ← H_combine(seed, h)`; `P = Σ_t α_t (g_t + E_t − h_t)`, một quan hệ
   bậc-hai `ψ·m + L(m, u, g) − H = 0` với `ψ = Σ_i β_i u_i`.
5. Mỗi lần thử: mặt nạ `y, y'`; với `a_j = <b_j, y or y'>` prover cam kết rác
   `G = −(ψ a_m + a_ψ m + L(a))` trong slot `G` của `D`, và băm
   `t_G, w = B1 y, w' = B1' y', v = a_ψ a_m + a_G` vào
   `c = SampleInBall(H_c(seed, t_G, w, w', v))`; đáp
   `z = y + c r`, `z' = y' + c r'`, khởi động lại trừ khi cả hai trong `[−B, B]`.
6. Verifier: tính lại mọi seed, `w = B1 z − c t1`, `w' = B1' z' − c t1'`, các
   masked opening `f_j = c t_j − <b_j, z>`, và
   `v = f_ψ f_m + c (L(f) − c H) − f_G`, và so seed cuối. Trung thực thì
   `v = c^2 P + Γ0 + a_G` với `P = 0`.

Giải mã nghiêm ngặt: độ dài chính xác, mọi hệ số đóng gói trong biên, zero
padding, `ct(h_t) = 0` theo cấu trúc, chỉ cam kết canonical. Randomness được
hedged (`opening_proof.hedged_mask_key` trên entropy, statement, `parameter_id`
nhị phân, cam kết, message và `r`), nên ngay cả một seed known-answer tường minh
cũng không bao giờ tái dùng `r'` dưới hai khóa phụ trợ.

### 4. Soundness

Các lỗi theo-từng-vòng của giao thức tương tác, cho một statement mà message
(relaxed-opening) đã cam kết không nhị phân, giả sử không tìm được nghiệm M-SIS
cho khóa nền hay khóa phụ trợ:

| Vòng | Sự kiện xấu | Lỗi |
|---|---|---|
| lift (`γ`) | mọi `<γ_i, m̄ ∘ (m̄ − 1)> = 0` | `q^-k = 2^-150` |
| check (`ρ, μ`) | `φ_t(e) = −ct(ḡ_t)` cho mọi `t`, lỗi `e ≠ 0` cố định trước `ρ` | `q^-k' = 2^-150` |
| combine (`α`) | `Σ α_t P̄_t = 0` với một `P̄_t ≠ 0` nào đó | `q^-N/2 = 2^-3840` |
| challenge (`c`) | `c` là một nghiệm của `c^2 P̄ + c X + Y` với `P̄ ≠ 0` | `2/|C| = 2^-256` |

Các mặt nạ `g_t` phải được cam kết trước `ρ`, và `D` sau `γ`; `h` trước `α`;
`t_G, w, w', v` trước `c` — phần cài đặt băm đúng thứ tự này. Round-by-round
soundness `ε_rbr = 2^-149.99` cho Fiat–Shamir soundness `≤ (Q_H + 1)·ε_rbr`
trước `Q_H` truy vấn băm (Canetti et al., STOC 2019; Attema–Fehr–Klooß,
TCC 2022): một kẻ tấn công làm `Q_H` truy vấn giả mạo một tuyên bố nhị phân với
xác suất nhiều nhất `(Q_H + 1)·2^-150`, khoảng 150 bit theo thước đo
work-over-advantage (chứng minh opening nền có 256). Tri thức về relaxed opening
được trích bằng forking vòng cuối đúng như đặc tả §4.3 (ba transcript được chấp
nhận với các hiệu challenge khả nghịch theo cặp ghim `P̄ = 0`, như trong equality
proof).

Hợp thành Fiat–Shamir-with-aborts đa vòng nay được viết ra (bài báo, Định lý
`thm:bin-ks`): các abort chỉ lặp vòng cuối, nên một lần thử bị loại chỉ là một
truy vấn `H_4` bị bỏ; extractor chỉ fork `H_4` (trường hợp Σ-protocol của AFK22,
kỳ vọng `3 + 2Q` lượt chạy, lỗi `(Q + 1)·2/|C|`); và ba vòng thống kê được chặn
đối với các message bị ràng buộc *tính toán* bằng một lập luận
plurality/forking, cho `(Q + 1)·ε_i + sqrt((Q + 1)·α_i)` mỗi vòng với `α_i` là
xác suất thành công của một finder M-SIS tường minh. Tổng:
`ε ≤ (Q + 1)·ε_rbr + Σ_i sqrt((Q + 1)·α_i) + β + Q²·2^-256`. Các khoảng trống
còn lại được liệt kê sau định lý (các số hạng M-SIS không chặt, prefix adaptive
trong AFK22, `SampleInBall` mô hình hóa là đều, chỉ ROM cổ điển).

Tính nhất quán của masked opening: từ hai transcript `y* = z − c r̄/f̄` là như
nhau cho mọi `c` được chấp nhận trừ khi `f̄(z − z'') − (c − c'')r̄` là một nghiệm
M-SIS khác không có norm `≤ 8κB` (chặn của đặc tả §4.4), cho `B1` và cho `B1'`.

`bdlop-binary-toy-v1` (`k = k' = 2`, `q ≈ 2^20`) có soundness 40-bit và chỉ dùng
cho test (`require_production_strength` từ chối nó).

### 5. Zero knowledge (phác thảo)

Các `(z, z')` được chấp nhận đều trên `[−B, B]` độc lập với `(r, r')` (lập luận
uniform-masking của đặc tả §4.2 trên `kN + k_aux N` hệ số). Các hybrid: (1) lấy
mẫu `z, z'` đều và lập trình bốn điểm random-oracle (message đầu có min-entropy
qua `w`, `w'`); (2) thay mọi hàng của `D` và `t_G` bằng đều dưới M-LWE cho khóa
phụ trợ với secret/error `r'` — message `G` của `t_G` là một hàm chỉ của các giá
trị công khai và witness (lập luận ALS20), nên reduction tính được nó; (3) khi đó
`g_t` chỉ xuất hiện trong `h_t`, vốn đều trên `{ct = 0}`. `w, w', v` được xác
định bởi các phương trình verification. `C` được giấu như trước (đặc tả §4.5).
`r` chỉ được tái dùng qua các chứng minh thông qua `z` đã rejection-sample, như
với chứng minh opening; `r'` là mới cho mỗi chứng minh.

### 6. Kích thước và thời gian (sản xuất, `bdlop-binary-128-v2`)

| Phần | Byte |
|---|---|
| Cam kết statement `C` (nền không đổi) | 6 720 |
| Cam kết phụ trợ `t1'`, `t_u`, `t_g` (16 poly × 960) | 15 360 |
| Mặt nạ `h` (5 × 255 hệ số × 30 bit) | 4 782 |
| Rác `t_G` | 960 |
| Seed challenge | 32 |
| Đáp ứng `z, z'` (38 poly × 256 × 18 bit) | 21 888 |
| **Tổng proof** | **43 022** |

Chấp nhận mỗi lần thử `((2B+1)/2γ)^{38·256} = 0.0112` (trung bình 89 lần thử;
cap 16 384, xác suất toàn-abort `2^-266`). Thời gian đo (trung vị của 20 lượt,
máy chung): xem `benchmark/results/q2/binary_proof_bench.json` và Mục 9 (đo với
`bdlop-binary-128-v1`; chưa đo lại dưới v2).

Số học dùng `fast_ring.py`: tích negacyclic chính xác qua các tích ma trận
float64 trên limb 15-bit (mọi tổng riêng là số nguyên dưới `2^53`, nên kết quả
BLAS chính xác và độc lập thứ tự), kiểm với `ring.poly_mul` trong các test.

### 7. Bảo mật cụ thể của khóa phụ trợ

Cùng `q, N, n = 6, λ = 7, κ, γ` và cùng chặn M-SIS `8κB ≈ 2^25.9` như nền; ma
trận M-SIS phụ trợ là `n × 24` (nền: `n × 14`) và instance M-LWE phụ trợ có
`n + 11 = 17` mẫu vành (nền: 7). Ước lượng CRYSTALS đã ghim
(`research/bdlop_params/bdlop_binary_128_v2.estimate.json`) cho cùng mức như bộ
nền: M-SIS β = 480 (140 / 127 bit), primal M-LWE β = 580 (169 / 153 bit), dual
β = 578. Các lý do:

- M-LWE: các mẫu thêm không giúp vượt tối ưu, nên 7 và 17 mẫu vành có sẵn cho
  cùng block size. (Với `bdlop-binary-128-v1` một script ADPS16 riêng cho 473 so
  với ước lượng nền đã ghim 474.)
- M-SIS: chiều tấn công tối ưu `sqrt(nN ln q / ln δ_480) ≈ 3 022` dưới cả hai độ
  rộng (3 584 và 6 144), nên các cột thêm không hạ block size 480.

`python research/bdlop_params/estimate.py --estimator <security-estimates>
--parameter-set BINARY_128` chạy mô hình đã ghim trên instance phụ trợ và sinh ra
file đó.

### 8. Tương thích với envelope

- Tương thích: cam kết statement là một cam kết `bdlop-open-128-v2`; các chứng
  minh hiện có, disclosure và registry descriptor làm việc trên nó không đổi.
- Không tự động: các cam kết payload hôm nay mã hóa `len ‖ payload` với ba byte
  mỗi hệ số (`codec.encode_payload`), vốn *không* nhị phân; chứng minh nhị phân
  áp dụng cho các cam kết của `encode_bits(chuỗi 32-byte)` (ví dụ một digest hoặc
  một credential secret 256-bit).
- Một proof 43.0 KB khoảng 2.9× envelope in-band (14 885 byte); mang nó in-band
  cần một phiên bản envelope mới và dung lượng carrier đo bởi sweep Q2. Ngoài băng
  (chế độ registered, hoặc kèm một disclosure) không cần đổi định dạng. Người
  tích hợp quyết định.
- Đã cài đặt từ đó: `payload_range_proof.py` (Phần II) chứng minh rằng một cam
  kết payload có sẵn giấu `encode_payload(p)` cho một độ dài công khai `L ≤ 128`,
  bằng cách cam kết các bit payload trong cam kết phụ trợ và thêm liên kết
  Z_q-tuyến tính `m = e_L + A β` như một số hạng nữa của các check functional
  (44 558 B cho `L ≤ 32`). Một range proof của cả 256 hệ số bằng 24 bit-plane sẽ
  tốn `24·(1 + k)` đa thức phụ trợ (256 526 B, chấp nhận `8·10^-10`) và vẫn bất
  khả thi.

### 9. Kết quả đo

Đo với `bdlop-binary-128-v1` (chưa đo lại dưới v2).
`benchmark/results/q2/binary_proof_bench.json`: 20 lượt, message, randomness và
entropy mới mỗi lượt, laptop Intel Family 6 Model 154 chạy một benchmark khác
cùng lúc, Python 3.12, một luồng.

| | trung vị | mean | min | p90 | max |
|---|---|---|---|---|---|
| prove (ms) | 2 208 | 3 011 | 456 | 9 490 | 11 342 |
| verify (ms) | 71.7 | 73.3 | 68.7 | 76.9 | 96.5 |
| lần thử | 62.5 | 84.5 | | | 322 (kỳ vọng 70.5) |

Thời gian prover bị chi phối bởi số lần thử hình học (khoảng 30 ms mỗi lần). Test:
45 trong `test_latticezk_binary_proof.py` (khoảng 8 s, gồm một KAT proof cỡ sản
xuất), độ phủ dòng 100 % của `binary_proof.py` và của `fast_ring.py`.

### 10. Câu hỏi mở cho một nhà mật mã ngoài

1. Kiểm phân tích round-by-round (Mục 4), đặc biệt rằng các mặt nạ `g_t` cam kết
   sau `γ` nhưng trước `ρ` không thể khai thác, và rằng `ct(h_t) = 0` qua cách mã
   hóa tương đương một kiểm tra tường minh.
2. Kiểm hợp thành Fiat–Shamir-with-aborts đa vòng, nay viết ra như Định lý
   `thm:bin-ks` (các abort chỉ khởi động lại vòng cuối với các seed trước cố
   định; extraction fork chỉ băm cuối; các vòng thống kê bằng một lập luận
   plurality với một số hạng M-SIS căn bậc hai).
3. Xác nhận các ước lượng M-SIS/M-LWE phụ trợ với estimator đã ghim.
4. `k = k' = 5` cho `2^-150` mỗi vòng. Khớp không gian challenge `2^-256` sẽ cần
   `k = k' = 9` (khoảng +12 KB).
5. Liệu có một cấu trúc nhỏ hơn trên một vành hai-slot (một đa thức lift mỗi lần
   lặp có vẻ cần thiết theo lập luận Toeplitz của 2.2, nhưng các mặt nạ `g_t` và
   `h_t` có thể chia sẻ).

---

## Phần II — Chứng minh khoảng payload: gắn chứng minh nhị phân vào payload (stream C3)

Trạng thái: cài đặt là `src/lattice_zk/payload_range_proof.py` (bộ tham số
`bdlop-payload-range-128-v1` trên `bdlop-open-128-v2`, và
`bdlop-payload-range-toy-v1` cho test), test trong
`src/runtest/test_latticezk_payload_range_proof.py`, định lý trong
`docs/paper/sections/binary_proof.tex` (`sec:payload-range`, `thm:pay`), benchmark
`benchmark/latticezk_payload_range_proof_bench.py` →
`benchmark/results/q2/payload_range_proof_bench.json`. Mã nghiên cứu chưa audit;
không constant time. Không gì trong các bộ tham số nền, các chứng minh opening,
equality và nhị phân, hay các định dạng envelope thay đổi.

### 1. Cái gì được chứng minh

Đầu vào công khai: bytes statement `x`, một độ dài payload **công khai** `L`
(`0 ≤ L ≤ 128`), và một cam kết `C = (t1, t2)` tạo bởi `bdlop.commit` dưới
`bdlop-open-128-v2`, ví dụ cam kết của một envelope in-band
(`linkage.envelope_commitment`) hoặc của một credential registered.

Chứng minh cho thấy tri thức (relaxed, xem dưới) về một opening của `C` mà
message đúng bằng

```text
m = codec.encode_payload(p)   cho một p ∈ {0,1}^{8L} nào đó
```

Tương đương:

- mọi hệ số của `m` nằm trong `[0, 2^24)` và là đóng gói 3-byte của các byte có
  khung `len(p) ‖ p`, tức một range proof 24-bit chính xác trên các hệ số
  payload, buộc vào payload bằng một phân rã bit;
- hệ số 0 mang trường độ dài `L`;
- mọi hệ số từ `⌈(L + 2)/3⌉` trở đi bằng không, nên `decode_payload(m)` thành
  công và trả về một payload `L`-byte.

Chứng minh lộ `L` và không gì khác về `p` (zero knowledge như chứng minh nhị
phân). Vì cam kết nền là binding theo relaxed opening, một disclosure sau
(`video_proof.create_commitment_disclosure`, một equality proof đối với
`Com(encode(p'); 0)`) chỉ có thể lộ `p' = p`.

Chính xác (Định lý `thm:pay` với `thm:bin-ks`): một extractor rewind chỉ truy vấn
oracle cuối xuất ra một relaxed opening `(r̄, f̄)` của `C`, `f̄ ∈ C̄`,
`‖r̄‖∞ ≤ 2B`, mà message `m̄ = t2 − f̄⁻¹⟨b2, r̄⟩` bằng `encode_payload(p)` cho một
`p` `L`-byte nào đó, hoặc một nghiệm M-SIS của `ℓ∞ ≤ 8κB` cho `B1` hoặc `B1'`
phụ trợ.

Không chứng minh: bất cứ điều gì về *giá trị* của `p` (rằng nó là một digest,
một credential, hay nằm trong một khoảng số); một độ dài ẩn; payload trên 128
byte. Xem Mục 7.

### 2. Các lựa chọn đã cân nhắc

Chứng minh nhị phân (`bdlop-binary-128-v2`, 43 022 B) cho thấy một cam kết giấu
một chuỗi 256-bit, nhưng các cam kết payload in-band dùng mã hóa 24-bit của
`codec.encode_payload`, nên nó không nói gì về payload.

| Lựa chọn | Statement | Kích thước (sản xuất) | Chấp nhận / lần thử | Phán quyết |
|---|---|---|---|---|
| (a-full) phân rã bit-plane `m = Σ_{j<24} 2^j b_j` của cả 256 hệ số, mọi `b_j` nhị phân | mọi hệ số trong `[0, 2^24)` (không phải ảnh encoder đầy đủ: độ dài và zero padding không kiểm) | 256 526 B (ℓ = 24, 177 response poly) | 8.2·10⁻¹⁰ (≈1.2·10⁹ lần thử) | bất khả thi ở chặn mặt nạ đã ghim `γ = 2^17`; cần chặn mặt nạ phụ trợ lớn hơn và một ước lượng M-SIS mới |
| (a-full, chứng minh độc lập) 24 cam kết nhị phân + 24 chứng minh nhị phân + một chứng minh tuyến tính trên 25 cam kết | như trên | ≈1.4 MB | riêng chứng minh tuyến tính chấp nhận với `0.191^25 ≈ 10⁻¹⁸` | bất khả thi |
| **(a′) đã chọn**: chỉ các bit của payload (công khai `L`), liên kết `m = e_L + A β` gấp vào vòng check của chứng minh nhị phân | `m = encode_payload(p)`, `|p| = L` (ảnh encoder đầy đủ) | 44 558 B cho `L ≤ 32`, +9 216 B mỗi 32 B nữa (72 206 B ở 128) | 0.0100 (ℓ = 1) … 0.0012 (ℓ = 4) | **đã cài đặt** |
| (b) envelope nhị phân từ đầu: `Com(encode_bits(p))`, chứng minh nhị phân hiện có mỗi 32 B | `C` giấu một chuỗi 32-byte | 6 720 + 43 022 = 49 742 B mỗi 32 B | 0.0112 | hoạt động không cần chứng minh mới, nhưng cần một phiên bản envelope mới và một mã hóa disclosure mới; ℓ chứng minh độc lập cho payload dài hơn |

Lựa chọn (a′) tốn 1 536 B nhiều hơn chứng minh nhị phân và, khác (b), áp dụng cho
cam kết payload *hiện có*: không định dạng envelope mới, các chứng minh disclosure
và linkage hiện có áp dụng không đổi, và chứng minh có thể được sinh ngoài băng
cho một video đã nhúng trước đó. Tính cả cam kết, (a′) là 6 720 + 44 558 = 51 278
B so với 49 742 B cho (b), nên hai cái trong 3 %. Lựa chọn (b) không cần mã mới
(nó là `binary_proof.prove(BINARY_128, x, Com(encode_bits(p)), …)`) và do đó
không được cài lại; các kích thước của nó trong benchmark JSON.

Vì sao (a′) rẻ hơn (a-full) nhiều: tính nhị phân của một đa thức tốn `k` đa thức
lift (Phần I §2.2, lập luận Toeplitz), nên chi phí scale theo số *đa thức bit*.
Một payload ngắn có `8L` bit payload, lấp `⌈8L/256⌉` đa thức, trong khi 24
bit-plane của một vector hệ số đầy đủ luôn cần 24. Các hệ số zero và trường độ
dài là công-khai-affine và không tốn gì: chúng là một phần của liên kết
`m − A β − e_L = 0`.

### 3. Giao thức (`payload_range_proof._prove`, `_recomputed_seed`)

Ký hiệu như Phần I §3; `k = k' = 5`.

- **Ánh xạ mã hóa.** `encode_payload(p) = e_L + A β(p)`, `e_L = encode_payload(0^L)`
  (chỉ hệ số 0 khác không: `256 L`), `β(p)` các bit của `p` (MSB trước) trong
  `ℓ = max(1, ⌈8L/N⌉)` đa thức nhị phân `β_j`, và `A` ánh xạ công khai gửi bit
  payload `s` tới hệ số `⌊(2 + ⌊s/8⌋)/3⌋` với trọng số
  `2^{8(2 − (2+⌊s/8⌋) mod 3) + 7 − s mod 8}` (`payload_encoding`, `decompose`,
  `recompose`; kiểm với `codec` cho mọi độ dài trong các test).
1. `r'` tam phân mới (hedged từ entropy, `x`, `pid`, `L`, `C`, `m`, `r` và các
   bit). `D_0 = (t1' = B1' r', t_{β_j} = ⟨b_{β_j}, r'⟩ + β_j)`.
2. `γ_{j,i} ← H_lift(pid, x, L, C, D_0)` cho `j < ℓ`, `i < k`.
3. `D_1 = (t_{u_{j,i}} = ⟨b_u, r'⟩ + σ(γ_{j,i} ∘ β_j), t_{g_t} = ⟨b_g, r'⟩ + g_t)`
   với `ct(g_t) = 0`; cùng `r'`, các hàng mới của cùng khóa phụ trợ.
4. `ρ_{t,(j,i)}, μ_{t,(j,i)}, ρ^L_t ← H_check(seed, D_1)`; prover gửi
   `h_t = g_t + E_t` không có hệ số hằng của nó, trong đó
   `E_t = Σ_{j,i} [σ(ρ) u − R β_j + μ u (β_j − J)] + σ(ρ^L_t) m
   − Σ_j σ(A_j^T ρ^L_t) β_j − ⟨ρ^L_t, e_L⟩`, nên
   `ct(E_t) = Σ ⟨ρ, Δ⟩ + μ Q + ⟨ρ^L_t, m − A β − e_L⟩`
   (`test_check_polynomial_constant_term_is_the_random_functional_of_the_error`,
   `test_link_functional_is_the_transpose_of_the_encoding`).
5. `α_t ← H_combine(seed, h)`: `P = Σ_j ψ_j β_j + L(m, β, u, g) − Σ_t α_t(h_t + ⟨ρ^L_t, e_L⟩)`
   với `ψ_j = Σ_i β'_{j,i} u_{j,i}`.
6. Mỗi lần thử (chỉ bước này lặp khi abort): mặt nạ `y, y'`, rác
   `G = −(Σ_j ψ_j a_{β_j} + a_{ψ_j} β_j + L(a))` cam kết trong slot `G` của `D`,
   `c = SampleInBall(H_c(seed, t_G, w, w', v))`, `v = Σ_j a_{ψ_j} a_{β_j} + a_G`;
   `z = y + c r`, `z' = y' + c r'`, khởi động lại trừ khi cả hai nằm trong
   `[−B, B]`.
7. Verifier: tính lại mọi seed và
   `v = Σ_j f_{ψ_j} f_{β_j} + c (L(f) − c H') − f_G`.

Byte proof: `Pack(D_0) ‖ Pack(D_1) ‖ Pack(h without ct) ‖ Pack(t_G) ‖ seed ‖ Pack(z, z')`.
Giải mã nghiêm ngặt (độ dài chính xác cho `L`, mọi giá trị đóng gói trong biên,
zero padding). Khóa phụ trợ trải từ `parameter_id ‖ ℓ`, nên mỗi `ℓ` có khóa
riêng, và `r'` không bao giờ tái dùng dưới hai khóa.

### 4. Soundness

Lỗi theo vòng (như chứng minh nhị phân; `L` không đổi chúng):

| Vòng | Sự kiện xấu | Lỗi |
|---|---|---|
| lift (`γ`) | một `β̄_j` nào đó không nhị phân và mọi `⟨γ_{j,i}, β̄_j ∘ (β̄_j − J)⟩ = 0` | `q^-k = 2^-150` |
| check (`ρ, μ, ρ^L`) | lỗi `e = (Δ, Q, m̄ − Aβ̄ − e_L) ≠ 0` cố định trước, và `ct(ḡ_t) + φ_t(e) = 0` cho mọi `t` | `q^-k' = 2^-150` |
| combine (`α`) | `Σ α_t P̄_t = 0` với một `P̄_t ≠ 0` nào đó | `q^-N/2 = 2^-3840` |
| challenge (`c`) | `c` một nghiệm của một bậc-hai khác không | `2/|C| = 2^-256` |

`m̄ − Aβ̄ − e_L` được cố định bởi `C` và `D_0`, cả hai băm trước `ρ^L`; nếu nó
bằng không và `β̄` nhị phân, thì `m̄ = Aβ̄ + e_L` trên số nguyên (mọi giá trị
dưới `2^24 < q`), tức `m̄ = encode_payload(p)`.

Knowledge soundness không tương tác (Định lý `thm:bin-ks`, áp dụng nguyên văn):
một kẻ thù với `Q` truy vấn oracle làm verifier chấp nhận một statement sai thành
công với xác suất nhiều nhất

```text
(Q + 1)(q^-k + q^-k' + q^-N/2 + 2/|C|) + Σ_{i=1..3} sqrt((Q + 1) α_i) + β + Q^2 2^-256
```

trong đó `α_i, β` là các xác suất mà các thuật toán forking tường minh tìm được
một nghiệm M-SIS của `ℓ∞ ≤ 8κB`. Phần thống kê là `(Q + 1)·2^-149.99`; các số
hạng M-SIS có mất mát forking căn bậc hai thường thấy (như với chứng minh
opening, Bổ đề `lem:fork`). Các abort chỉ lặp vòng cuối; extraction fork chỉ
oracle cuối (extractor Σ-protocol của AFK22, kỳ vọng `3 + 2Q` lượt chạy), và các
vòng thống kê được chặn bằng một lập luận plurality đối với các message bị ràng
buộc tính toán. Phác thảo trong `docs/paper/sections/binary_proof.tex` sau Định
lý `thm:bin-rbr`, với các khoảng trống còn lại liệt kê ở đó.

### 5. Bảo mật cụ thể của khóa phụ trợ

Mô hình CRYSTALS đã ghim (`python research/bdlop_params/estimate.py --estimator
<security-estimates> --parameter-set PAYLOAD_RANGE_128 --binary-polys ℓ`):
với `ℓ = 1` (M-SIS `6 × 25`, 18 mẫu M-LWE) và `ℓ = 4` (`6 × 43`, 36 mẫu) các
mức bằng của bộ nền: M-SIS β = 480 (140 / 127 bit), primal M-LWE β = 580
(169 / 153), dual β = 578
(`research/bdlop_params/bdlop_payload_range_128_l{1,4}.estimate.json`). Lý do là
của chứng minh nhị phân (Phần I §7): sub-dimension M-SIS tối ưu dưới mọi độ rộng
và các mẫu M-LWE thêm vượt tối ưu không giúp. Phần đối chiếu dual-hybrid của
lattice-estimator (164 / 150 bit cho bộ nền) không được chạy lại cho các instance
này.

### 6. Kích thước và thời gian (sản xuất, `bdlop-payload-range-128-v1`)

| `L` (byte) | ℓ | Byte proof | Chấp nhận | Lần thử kỳ vọng |
|---|---|---|---|---|
| 0–32 | 1 | 44 558 | 0.00996 | 100 |
| 33–64 | 2 | 53 774 | 0.00490 | 204 |
| 65–96 | 3 | 62 990 | 0.00241 | 415 |
| 97–128 | 4 | 72 206 | 0.00119 | 843 |

Các phần cho ℓ = 1: `D_0` 6 720, `D_1` 9 600, `h` 4 782, `t_G` 960, seed 32,
đáp ứng (39 poly × 256 × 18 bit) 22 464. Cap lần thử `2^17`: xác suất toàn-abort
`2^-1892` (ℓ = 1), `2^-225` (ℓ = 4).

Đo (`benchmark/results/q2/payload_range_proof_bench.json`, 10 lượt, payload/
randomness/entropy mới mỗi lượt, Python 3.12 một luồng, laptop **tải nặng bởi một
sweep benchmark chạy song song**, nên các thời gian tuyệt đối là bi quan và nhiễu;
chỉ so với chứng minh nhị phân trên cùng host):

| `L` | prove trung vị (ms) | prove mean | lần thử mean (kỳ vọng) | verify trung vị (ms) |
|---|---|---|---|---|
| 32 | 2 049 | 6 683 | 54.7 (100.4) | 228 |
| 64 | 24 120 | 32 909 | 153.5 (204.1) | 514 |

Mỗi lần thử khoảng 120 ms (ℓ = 1) và 210 ms (ℓ = 2) trên host đó; trong một so
sánh cùng-host, lần thử ℓ = 1 tốn 1.2–1.45× một lần thử chứng minh nhị phân. Thời
gian prover bị chi phối bởi số lần thử hình học.

Test: 61 trong `test_latticezk_payload_range_proof.py` (khoảng 10 s, gồm một KAT
sản xuất và một proof sản xuất ℓ = 2); độ phủ dòng của `payload_range_proof.py`
99 % (dòng bị bỏ duy nhất là một guard nhất quán nội bộ).

### 7. Câu hỏi mở cho một nhà mật mã ngoài

1. Kiểm số hạng liên kết: `ρ^L_t` được rút cùng các check challenge, sau khi `C`
   và `D_0` (cố định `m̄` và `β̄`) được băm. Gấp quan hệ Z_q-tuyến tính
   `m = Aβ + e_L` vào cùng `k'` functional với các kiểm lift-consistency có sound
   không (một vector lỗi, một functional đều)?
2. `β` được cam kết trong `D_0` trước `γ` và các lift được thêm sau dưới cùng
   `r'`. Ta lập luận rằng binding theo relaxed opening của `t1'` cố định message
   của mỗi hàng; việc dùng tăng dần một vector randomness BDLOP này có được các
   lập luận binding/hiding chuẩn phủ không?
3. Kiểm phác thảo knowledge-soundness (`thm:bin-ks`): lập luận plurality cho các
   vòng thống kê, việc dùng AFK22 với một prefix chọn adaptive, và số hạng
   seed-ordering `Q^2 2^-256`.
4. Một độ dài ẩn (`L` bí mật, `≤ 32ℓ`) sẽ cần một chứng minh rằng các byte sau
   `L` bằng không, ví dụ với một chỉ báo độ dài one-hot đã cam kết và một quan hệ
   bậc-hai nữa. Có cách rẻ hơn không?
5. Một range proof 24-bit đầy đủ của cả 256 hệ số là bất khả thi ở chặn mặt nạ đã
   ghim (Mục 2). Một chặn mặt nạ riêng, lớn hơn cho khóa phụ trợ (với một ước
   lượng M-SIS mới ở `8κB'` lớn hơn) có chấp nhận được không, hay một kỹ thuật
   khác (ví dụ một digit base nhỏ hơn, hoặc approximate range proof kiểu LNP22)
   đáng chuộng hơn?
