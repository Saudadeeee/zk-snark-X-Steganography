# Đánh giá nội bộ: knowledge soundness và hợp thành Fiat–Shamir-with-aborts của chứng minh nhị phân và chứng minh khoảng payload

Người đánh giá đóng vai một nhà mật mã lưới bên ngoài, theo lối đối kháng. Phạm vi gồm
`docs/paper/sections/binary_proof.tex` (`thm:bin-rbr`, `lem:bin-consistent`, `thm:bin-ks`,
`thm:bin-zk`, `thm:pay`, đoạn "Chứng minh không tương tác", danh sách khoảng trống sau
`thm:bin-ks`), các quy ước của `security.tex` / `security_appendix.tex` (`lem:invertible`,
`def:relaxed`, `lem:hvzk`, `lem:sim`, `thm:se`, `thm:binding`, `lem:fork`),
`docs/PROOF_NHI_PHAN_VA_KHOANG.md` (Phần I §4, Phần II §4, Phần II §7), `QUESTIONS.md`
Q2/Q4/Q11/Q16, cùng mã `binary_proof.py`, `payload_range_proof.py`, `opening_proof.py`,
`params.py`. Bộ tham số sản xuất: `bdlop-open-128-v3` (n = 7, λ = 7, k = 15),
`bdlop-binary-128-v3`, `bdlop-payload-range-128-v2`. Chỉ đọc mã; các kiểm tra nhỏ chạy trên
bộ toy và tính số liệu trên bộ sản xuất (tổng < 2 s).

## Tóm tắt kết luận

1. **Không tìm thấy lỗ hổng nghiêm trọng (Critical/High) nào trong mã.** Thứ tự băm trong mã
   khớp với thứ tự mà chứng minh giả định. Mọi phần tử bản ghi mà một thách thức phụ thuộc vào
   đều được băm trước thách thức đó. Giải mã là chính tắc: độ dài chính xác, padding bằng
   không, mọi giá trị nằm dưới biên, `ct(h_t) = 0` theo cấu trúc. Sau các phép thử lật bit,
   proof ngẫu nhiên có trường hợp lệ, đổi `L`, đổi statement và kiểu sai, `verify` của cả hai
   chứng minh đều trả về `False` và không bao giờ ném ngoại lệ. Tôi không dựng được tấn công
   malleability hay thay statement nào.
2. **Lập luận plurality/forking cho các vòng thống kê trong `thm:bin-ks` là đúng** về cấu trúc.
   Chuỗi bất đẳng thức `P² − Σ p_m² ≥ (P − p_{m*})²` → Jensen → Cauchy–Schwarz cho đúng
   `√((Q+1)α_i)`. Phần phụ thuộc vào AFK22 cũng hợp lệ, với điều kiện viết rõ một bước còn thiếu
   (F5, G-ii) và sửa một hằng số.
3. **Có ba vấn đề cấp Medium ở mức phát biểu và chứng minh, không phải ở mã:**
   - (F1) `thm:bin-rbr` tự nó không được chứng minh. Bước "cố định các thông điệp trích xuất
     được" chính là khoảng trống mà `thm:bin-ks` phải lấp bằng plurality. Cận phát biểu cho
     prover tương tác cũng thiếu các số hạng M-SIS.
   - (F2) Giả thiết "C không có phần mở nới lỏng nào với thông điệp nhị phân", và cách nói
     "thông điệp nới lỏng duy nhất", là **rỗng**. Theo phép đếm, với bộ v3 hầu như mọi `C` đều có
     phần mở nới lỏng tới *mọi* thông điệp. Mệnh đề "Cụ thể…" của `thm:bin-ks` và các câu
     "soundness cho statement sai" trong tài liệu thiết kế vì thế không có nội dung. Khẳng định
     có nghĩa là knowledge soundness cộng với binding.
   - (F3) Π_pay được mang in-band (`video_proof.py:381–384`, `413–416`), nên đối thủ của trò
     chơi SE nhìn thấy các range proof trung thực. Bài báo chỉ có knowledge soundness độc lập
     (`thm:bin-ks`) mà không có phiên bản simulation-extractable như `thm:se` đã có cho chứng
     minh mở.
4. Một số số liệu sai hoặc cũ. Sai số theo vòng là tổng `≈ 2^-149.0`, không phải
   `≤ 2^-149.99`. Bài báo vẫn dùng số của v2/v1. Hai chú thích trong mã nêu xác suất chấp nhận
   và xác suất toàn-abort sai cho bộ sản xuất. Có ba điểm nhỏ trong `thm:bin-zk`.
5. Về bốn khoảng trống mà bài báo tự liệt kê: (i) không phải lỗ hổng, là chi phí cố hữu, loại
   (c); (ii) sửa được, loại (b), cần viết rõ bước "đầu vào của H4 xác định tiền tố"; (iii) thực
   chất đã được quy ước `G` của `security.tex` giải quyết, loại (b), nhưng phải mở rộng cho
   `_expand` (F6); (iv) là giới hạn đã tuyên bố, loại (c).

## Bảng phát hiện

| ID | Mức độ | Vị trí | Mô tả | Đề xuất sửa cụ thể |
|---|---|---|---|---|
| F1 | Medium | `binary_proof.tex:162–200` (`thm:bin-rbr`); `PROOF_NHI_PHAN_VA_KHOANG.md:119–128` | Định lý khẳng định một cận `ε_rbr` cho *mọi* prover tương tác, "mà không tìm được nghiệm M-SIS". Chứng minh mở đầu bằng "Cố định các thông điệp trích xuất được; chúng được xác định bởi C và D sai khác M-SIS". Nhưng thông điệp nới lỏng chỉ bị ràng buộc *tính toán*, và chỉ được trích *sau* thách thức (bằng rewinding). Lập luận "m̄ cố định trước γ nên `Pr = q^-k`" vì thế không áp dụng trực tiếp được. Đây đúng là khó khăn mà `thm:bin-ks` (dòng 277–302) giải quyết bằng plurality, và cái giá là các số hạng `√((Q+1)α_i)`. Theo phát biểu hiện tại, `thm:bin-rbr` không có chứng minh và có cận quá mạnh. Cụm "xác suất chấp nhận mà không tìm được nghiệm M-SIS" cũng không được định nghĩa (ai tìm, trong thời gian nào). | Viết lại `thm:bin-rbr` thành một **bổ đề chuỗi tất định** cộng với các cận theo vòng cho thông điệp cố định: "(a) Với *mọi* vector thông điệp `s̄` (của C, D) và mọi giá trị thách thức, nếu `m̄` không nhị phân và không vòng nào trong ba vòng đầu là *xấu* đối với `s̄` thì `P(s̄) ≠ 0`. (b) Với `s̄` cố định trước thách thức vòng i, sự kiện xấu có xác suất `≤ ε_i`. (c) Nếu `P(s̄) ≠ 0` thì tối đa 2 thách thức `c` được chấp nhận, nếu không thì `lem:bin-consistent` cho một nghiệm M-SIS." Bỏ mọi khẳng định xác suất đối với prover tùy ý ra khỏi định lý này; khẳng định đó chỉ thuộc về `thm:bin-ks`. Nếu muốn giữ một phát biểu tương tác thì phải lặp lại lập luận plurality ở mỗi vòng, và cận khi đó là `Σ_i ε_i + Σ_i √α_i + β`. |
| F2 | Medium | `binary_proof.tex:164–165` ("m̄ duy nhất theo thm:binding"), `234–237` (mệnh đề "Cụ thể, nếu C không có phần mở nới lỏng nào với một thông điệp nhị phân…"), `388–390` (`thm:pay`); `PROOF…md:119–121`, `131–136`, `386–395`, `397–406`; `QUESTIONS.md:232–246` | Binding của phần mở nới lỏng chỉ là *tính toán*, và về mặt thông tin thì các phần mở với mọi thông điệp đều tồn tại. Với v3, `r̄ ∈ [−2B, 2B]^{kN}` có `15·256·log₂(4B+1) ≈ 72 960` bit entropy, trong khi ràng buộc `B1 r̄ = f t1`, `⟨b2, r̄⟩ = f(t2 − m)` chỉ có `8·256·30 = 61 440` bit. Vậy với mỗi `f ∈ C̄` và *mỗi* `m` (nhị phân hay không), một `C` điển hình có khoảng `2^11 520` phần mở nới lỏng tới `m`. Hệ quả: giả thiết "C không có phần mở nới lỏng với thông điệp nhị phân" (tương ứng "Enc(p)") hầu như không bao giờ đúng, nên mệnh đề "Cụ thể…" là rỗng. Cụm "statement sai" và câu "forge một tuyên bố nhị phân với xác suất ≤ (Q_H+1)·2^-150" trong tài liệu thiết kế không có nghĩa. Mệnh đề chính của `thm:bin-ks` (trích được một phần mở nới lỏng nhị phân) thì vẫn đúng và có ý nghĩa. | (1) Xóa mệnh đề "Cụ thể…" (dòng 234–237) và câu tương ứng trong `thm:pay`. (2) Thêm một hệ quả soundness *tính toán* có nghĩa: "Nếu `C = Com(m; r)` do bên thách thức sinh ra với `m` không nhị phân (tương ứng `m ≠ Enc(p)` với mọi p), hoặc nếu đối thủ còn xuất một phần mở (trung thực hoặc nới lỏng) của C tới một `m` như vậy, thì `ε ≤ [cận của thm:bin-ks] + Adv^MSIS`", bằng `thm:binding` với chuẩn `2κ + 2B` (một trung thực, một nới lỏng) hoặc `8κB`. (3) Sửa "duy nhất theo thm:binding" thành "duy nhất trừ khi tìm được một nghiệm M-SIS (thm:binding)". (4) Trong `PROOF…md` §4 (cả hai phần) và Q16, thay "statement sai / forge" bằng "trích xuất được phần mở nhị phân, hoặc phá binding". |
| F3 | Medium | `binary_proof.tex:220–304` (`thm:bin-ks`), `383–392` (`thm:pay`); `video_proof.py:381–384`, `413–416`; so sánh `security.tex:284–309` (`thm:se`) | Range proof được nhúng trong envelope in-band, nên oracle `O_Emb` cho đối thủ thấy các Π_pay trung thực trên `(x_i, L, C_i)`. `thm:bin-ks` là knowledge soundness *độc lập*: đối thủ không có oracle chứng minh. Hai điều chưa được chứng minh. (a) Trường hợp điểm đã lập trình: đối thủ dùng lại đầu vào H4 của một proof trung thực. (b) Lập luận plurality khi tiền tố `(x, C, D, h)` và các truy vấn H1–H3 do simulator thực hiện, không phải do đối thủ. Lời khẳng định trong `PROOF…md` Phần II §1 rằng "một disclosure sau chỉ có thể lộ p' = p" vì thế chưa được phủ trong mô hình SE. | Thêm một định lý `thm:pay-se` theo khuôn `thm:se`: (1) thay các proof trung thực bằng simulator của `thm:bin-zk`, với chi phí `Q_P·Adv^MLWE_aux + ε_zk` (xem F7); (2) điểm H4 đã lập trình: cùng đầu vào H4 thì cùng `s3, t_G, w, w', v`, do đó (trừ va chạm) cùng `x, C, D, h` và cùng `c`. Khi đó hoặc `(z, z')` trùng (proof trùng, nên `∉ L` sai), hoặc `B1(z* − z) = 0` / `B1'(z'* − z') = 0`, cho một nghiệm M-SIS chuẩn `≤ 2B`; (3) AFK22 không rewind tại điểm đã lập trình; (4) trong plurality, chỉ số j chạy trên các truy vấn H_i của *cả* đối thủ lẫn simulator (thừa số `Q + Q_P + 1`). Nếu tiền tố là của một proof trung thực, `D` là đều theo hybrid M-LWE, và thông điệp trích được vẫn bị ràng buộc qua `t1'`, nên lập luận không đổi. |
| F4 | Low | `binary_proof.tex:173`, `237`; `PROOF…md:132`, `406`; `QUESTIONS.md:244`; `binary_proof.py:185–187` (`soundness_bits` lấy max) | `ε_rbr = q^-k + q^-k' + q^-N/2 + 2/\|C\|` với `q^-5 ≈ 2^-150.0` hai lần. Tính lại: tổng `= 2^-149.0000002`, không phải `≤ 2^-149.99`. Con số 149.99 là số hạng lớn nhất. | Sửa thành "`ε_rbr ≈ 2^-149.0` (số hạng lớn nhất `2^-149.99`)". Trong mã nên đặt `soundness_bits = −log2(Σ 2^v)`. Ngưỡng 128 không bị ảnh hưởng. |
| F5 | Low | `binary_proof.tex:251–255`, `257–270`, `229–230` | Số hạng thứ tự/va chạm `Q²/2^256` chỉ tính cho lần chạy đầu. Có ba chỗ thiếu: (a) trong các lần chạy rewind của AFK22 (kỳ vọng `3 + 2Q`) và hai lần chạy E của F_i, đối thủ có thể xuất một `(x', C', D', h') ≠ (x, C, D, h)` có cùng `s3`. Đầu vào H4 chỉ chứa `s3` chứ không chứa tiền tố, nên mỗi lần chạy thêm `≤ Q·2^-256`, tổng cộng khoảng `(3+2Q)·Q·2^-256`; (b) va chạm đầu ra giữa các truy vấn H_i, `≤ Q²/2^257`; (c) "WLOG thêm mỗi oracle một truy vấn" cho `Q + 4`, không phải `Q + 1`. Chỉ là hằng số, nhưng bước (a) chính là điều kiện để "phát biểu" Σ-protocol trong AFK22 được xác định bởi đầu vào H4 (xem G-ii). | Thay `Q²/2^256` bằng một cận viết rõ, ví dụ `(4Q + 8)·(Q + 4)·2^-256`, và thêm một câu: "trừ va chạm trên toàn bộ các lần chạy của E và F_i, `s3` xác định duy nhất `(x, C, D, h)`, nên ba bản ghi của AFK22 có cùng tiền tố". Không cần sửa mã. Băm trực tiếp `(x, C, D, h)` vào H4 sẽ bỏ được bước này, nhưng không bắt buộc. |
| F6 | Low | `binary_proof.tex:203–218` ("…xác suất tối đa ε_i trên câu trả lời"), `316–318` (gap iii); `binary_proof.py:367–368`, `payload_range_proof.py:369–370` (`_expand`); `security.tex:119–132` | Câu trả lời của H_i là một seed 256 bit. `γ, ρ, μ, ρ^L, α` là `Expand(_EXPAND_DOMAIN ‖ seed)`, một XOF dùng *chung* domain cho cả ba vòng; còn `c = SampleInBall(XOF(seed))`. Với một seed đều, `Pr[α xấu] ≤ q^-N/2 = 2^-3840` chỉ đúng nếu mô hình `Expand` như RO và seed mới. Đối thủ có thể đã truy vấn `Expand` tại seed đó, mỗi truy vấn với xác suất `≤ Q_X/2^256`. Vì vậy ε_3 thực tế là `≈ 2^-256`, và mọi ε_i cần cộng thêm `Q_X·2^-256`. Quy ước của `security.tex` (G là RO đều trên đầu vào mới) giải quyết gap (iii) cho `c`, nhưng danh sách oracle ở đó không nhắc tới các phép mở rộng của chứng minh nhị phân và khoảng. AFK22 cũng cần các `c` đôi một khác nhau từ các seed khác nhau: va chạm `G(s) = G(s')` trong các lần chạy của E có xác suất khoảng `(3+2Q)²/\|C\| + (3+2Q)·Q·2^-256`. | Thêm `_EXPAND_DOMAIN` của hai chứng minh vào danh sách RO của `security.tex` và tham chiếu quy ước `G`. Sửa câu "xác suất tối đa ε_i trên câu trả lời" thành "`ε_i + Q·2^-256`, mô hình hóa `Expand`, `G` như RO". Ghi ε_3 thực tế là `2^-256`. Đóng gap (iii) bằng cách tham chiếu quy ước đã có, thay vì gọi đó là một giả định riêng. |
| F7 | Low | `binary_proof.tex:322–344` (`thm:bin-zk`), `246–249` | (a) Cận ghi "`Adv^MLWE_aux` … cho bất kỳ số chứng minh nào". Mỗi proof có một `r'` mới, nên hybrid M-LWE chạy theo từng proof, và cận phải là `Q_P·Adv^MLWE_aux` (hoặc dựa trên một giả định M-LWE nhiều-bí-mật cho cùng ma trận). (b) Phát biểu nói "lập trình RO tại bốn điểm", nhưng đoạn chứng minh ở dòng 246–249 nói chỉ lập trình H4, còn γ, ρ, μ, α lấy bằng truy vấn thường. Hai chỗ mâu thuẫn nhau. (c) Phát biểu không nhắc tới các hybrid khóa hedged (G1/G2 của `lem:sim`). | Sửa thành `Q_P·Adv^MLWE_aux + ε_zk(Q_P, Q_H)` với `ε_zk` của `lem:sim`, trong đó `A_max = 16 384` (nhị phân) hoặc `2^17` (khoảng), η lấy qua `w`. Sửa "bốn điểm" thành "một điểm (H4) mỗi chứng minh". |
| F8 | Low | `binary_proof.tex:6–7`, `111–112`, `121–123`, `173`, `409–431`; `PROOF…md:172–200`, `427–438`; `binary_proof.py:71–74`; `payload_range_proof.py:76–78`; `security.tex:44`, `58` | Số liệu vẫn là của `bdlop-binary-128-v2` và `bdlop-payload-range-128-v1` (nền v2, n = 6). Các giá trị sản xuất, tính bằng chính mã: **binary-v3**: 45 134 B, `p_acc = 0.00885`, `(1−p)^16384 = 2^-210.05`, M-SIS phụ trợ `7×25`, 18 mẫu M-LWE. **payload-range-v2**: 46 670 B (L ≤ 32) đến 74 318 B (L = 128), `p_acc = 0.00786 … 0.000937`, toàn-abort `2^-1492.4` / `2^-177.2`. Hai chú thích trong mã sai: `binary_proof.py:71–74` ghi "0.0142 … 2^-338", sai cho cả v2 (0.0112, 2^-266.4) lẫn v3. `payload_range_proof.py:76–78` ghi "0.0100 / 0.0012, dưới 2^-225", chỉ đúng cho v1 (v2: 2^-177). | Cập nhật bài báo và tài liệu thiết kế sang các bộ sản xuất (hoặc ghi rõ "số liệu cho v2, bộ sản xuất là v3: …"), tham chiếu `bdlop_binary_128_v3.estimate.json` và `bdlop_payload_range_128_v2_l{1,4}.estimate.json`. Sửa hai chú thích, ví dụ: "p_acc ≈ 0.0088 (v3); 16 384 lần thử toàn-abort ≈ 2^-210" và "≈ 0.0079 (ℓ = 1) / 0.00094 (ℓ = 4) cho v2; 2^17 lần thử: ≤ 2^-177". |
| F9 | Low | `PROOF…md:131–136` | Câu "Round-by-round soundness ε_rbr cho Fiat–Shamir soundness ≤ (Q_H+1)·ε_rbr (Canetti et al. STOC 2019; AFK TCC 2022)" áp sai định lý. RBR soundness của CCHLRR19 cần một hàm trạng thái "doomed" được định nghĩa *thông tin-lý thuyết*, còn ở đây trạng thái được định nghĩa qua thông điệp chỉ bị ràng buộc tính toán (xem F2). Đoạn ngay sau đó (dòng 141–150) mô tả đúng cận của `thm:bin-ks`. | Xóa câu trích CCHLRR19 và chỉ dẫn tới `thm:bin-ks`. Nói rõ phần `(Q+1)·ε_rbr` cộng với `Σ√((Q+1)α_i) + β` mới là cận. |
| F10 | Note | `binary_proof.tex:292–302` | Có hai chi tiết reduction của F_i chưa được viết ra. (a) F_i phải cấy thể hiện M-SIS vào *một* trong hai khóa `B1` hoặc `B1'` (lập trình điểm mở rộng khóa như phụ lục), nên `α_i ≤ Adv^MSIS(B1) + Adv^MSIS(B1')` sau một lần đoán. Với Π_pay có tới 4 khóa phụ trợ (mỗi ℓ một khóa), nên thêm một thừa số đoán ≤ 4, hoặc dùng `L` do đối thủ chọn. (b) F_i có thời gian chạy kỳ vọng khoảng `2(3 + 2Q)` lần chạy A; phép rút gọn cần nêu điều này khi chuyển sang ước lượng cụ thể. | Thêm một câu cho mỗi ý. Không thay đổi kết luận. |
| F11 | Note | `payload_range_proof.py:173–175`, `731–736` | `verify(..., length=np.int64(5), ...)` trả về `False`, vì `layout` chỉ nhận `int` thuần. Điều này an toàn (từ chối), nhưng một bên gọi truyền số nguyên numpy sẽ thấy proof hợp lệ bị từ chối mà không có thông báo. | Ghi vào docstring, hoặc chấp nhận `numbers.Integral` (vẫn loại `bool`). Không liên quan tới an toàn. |
| G-i | Note (gap i, loại c) | `binary_proof.tex:310–313` | Các số hạng `√((Q+1)α_i)` là tổn thất forking cố hữu, cùng loại với `lem:fork`. Đây không phải một lỗ hổng, nhưng để đạt `t/ε ≥ 2^128` cần `α_i ≲ ε²/(Q+1)`. | Giữ nguyên, ghi cùng chú thích định lượng như sau `thm:se` (`Q = 2^64` thì `ε ≲ 2^-32`). |
| G-ii | Note (gap ii, loại b) | `binary_proof.tex:313–316`, `257–270` | Theo tôi, AFK22 (Attema–Fehr–Klooß, TCC 2022; bản J. Cryptology 2023, kết quả cho Σ-protocol k-out-of-N special-sound) áp dụng được: H1–H3 được coi là một phần đồng xu của A (lấy mẫu lười, nhất quán qua các lần rewind), "phát biểu" là `pre`, quan hệ là "phần mở nới lỏng với `P_pre(s̄) = 0` HOẶC nghiệm M-SIS". Điều còn thiếu là đầu vào H4 chỉ chứa `s3`, không chứa `pre`. Cần viết bước "s3 xác định pre trừ va chạm trên mọi lần chạy" (F5-a). Cần đối chiếu từng dòng rằng định nghĩa của AFK22 cho phép phát biểu thích nghi được băm vào đầu vào oracle thách thức (tôi tin là có, nhưng chưa đối chiếu nguyên văn). | Viết bước F5-a vào chứng minh. Trích dẫn chính xác định lý của AFK22 (số định lý, phiên bản JoC). |
| G-iii | Note (gap iii, loại b) | `binary_proof.tex:316–318` | Gap này đã được giải quyết bởi quy ước `G: {0,1}^256 → C`, đều trên đầu vào mới, của `security.tex:122–127`. `\|C\| = 2^257.01 > 2^256` không gây vấn đề khi `c = G(seed)` với G là RO. | Xem F6: thay "giả định" bằng tham chiếu, cộng thêm số hạng va chạm của G. |
| G-iv | Note (gap iv, loại c) | `binary_proof.tex:319`, `425` | Chỉ có ROM cổ điển. Một bản QROM cần kỹ thuật measure-and-reprogram đa vòng (Don–Fehr–Majenz–Schaffner) cùng một thay thế cho plurality/rewinding. | Để ngỏ, như đã tuyên bố. |

## Điều đã kiểm và không tìm thấy vấn đề

**Thứ tự băm và tách miền (nhiệm vụ 1).**
- Chứng minh nhị phân (`binary_proof.py:513–551` cho prover, `630–667` cho verifier):
  `s1 = H_lift(pid, u64(|x|)‖x, enc(C))`, rồi `γ`; `s2 = H_check(s1, enc(t1', t_u, t_g))`, rồi
  `ρ, μ`; `s3 = H_combine(s2, enc(h không ct))`, rồi `α`;
  `seed = H_c(s3, enc(t_G), w, w', v)`, rồi `c`. Mỗi sự kiện xấu chỉ phụ thuộc vào những gì đã
  được băm trước thách thức tương ứng: `m̄` qua `C` trước γ; `ū, ḡ` (gồm `δ_t = ct(ḡ_t)`) qua
  `D` trước ρ; `h` trước α; `t_G, w, w', v` trước c. Mọi trường ngoài `x` có độ dài cố định
  theo `pid`, nên đầu vào băm giải mã được duy nhất.
- Chứng minh khoảng (`payload_range_proof.py:537–574`, `680–717`): `D_0 = (t1', t_β)` và
  `u32(L)` nằm trong `H_lift`; `D_1 = (t_u, t_g)` nằm trong `H_check`; `ρ^L` được rút cùng
  `ρ, μ` sau khi `C` và `D_0` đã được băm, đúng như phần chứng minh khoảng cần.
- Các domain tag (`…/bdlop-binary/v1/…\0`, `…/bdlop-payload-range/v1/…\0`,
  `…/bdlop-open/v1/…\0`, `…/challenge-poly/v1\0`, hedged `…/hedged-mask-key/v2\0`) đôi một
  không-tiền-tố. `_EXPAND_DOMAIN` khác nhau giữa hai chứng minh.
- Đã kiểm lại đại số: `ct(σ(ρ)u − Rm) = ⟨ρ, u − σ(γ∘m)⟩`; liên kết `link_bits = σ(Aᵀρ^L)`
  (`payload_range_proof.py:408–411`) và `ct(E_t) = ⟨ρ^L, m − Aβ − e_L⟩`; khử `Γ1` trong phương
  trình kiểm chứng (`v = c²P + a_ψ a_m + a_G`); `P = Σ_t α_t(g_t + E_t − h_t)` khớp với
  `coef`, `coef_m`, `−βJ` của `_combination`.

**Các sự kiện xấu là đầy đủ (nhiệm vụ 1).** Các thao tác tôi đã xét: `ct(ḡ_t) ≠ 0` (đã nằm
trong `δ_t`); dùng `h_t` để triệt tiêu mọi hệ số không hằng của `P̄_t` (khi đó `P̄_t` là một
hằng số khác không, khác không ở cả hai slot CRT, vẫn bị vòng α bắt); chọn `C`, `x` thích nghi
(nằm trong `(Q+1)ε_1`); `t1'` gửi sau γ (vòng lift chỉ phụ thuộc `m̄`); `t_G` gửi sau α (bị
ràng buộc qua `t1'`); các bit đệm của `β` sau `8L` (chỉ bị chứng minh là nhị phân, không ảnh
hưởng `m`). Tôi không tìm thấy hành động nào nằm ngoài bảng ngoài những điểm mô hình hóa nêu
trong F5/F6.

**`lem:bin-consistent`.** Chặn `8κB` đúng:
`‖f̄(z_c − z_c'')‖ ≤ 2κ·2B` và `‖(c − c'')r̄‖ ≤ 2κ·2B`. Nghiệm khác không trên ℤ được bảo
đảm vì `2·8κB < q` (`params.py:67`). Phần "trừ tại (c, c') và (c', c'')" cần cả ba hiệu thách
thức khả nghịch, và `lem:invertible` cho điều đó với `q ≡ 5 (mod 8)` (tính lại:
`q mod 8 = 5`).

**Plurality (nhiệm vụ 2).** `m*` là hàm của tiền tố, nên độc lập với `γ^(j)`. Các sự kiện
"lần chạy đầu dùng truy vấn j" rời nhau theo j. Chuỗi `α_i ≥ Σ_j E[(P_j − p*_j)²] ≥
(Σ_j E[P_j − p*_j])²/(Q+1)` là đúng. Hai phần mở nới lỏng của cùng `t1` (hoặc `t1'`) với thông
điệp khác nhau cho `f̄'r̄ − f̄r̄' ≠ 0` có chuẩn `≤ 8κB`. Lời gọi lại "chạy lại E từ truy vấn j"
hợp lệ vì AFK22 chỉ bắt đầu rewind sau truy vấn H4 then chốt.

**Liên kết và các hàng tăng dần (nhiệm vụ 3).** Mọi thông điệp hàng là
`s̄_j = t'_j − ⟨b'_j, f̄⁻¹r̄'⟩`, tức là hàm của duy nhất `f̄⁻¹r̄'`, và đại lượng này duy nhất trừ
khi `B1'(f̄₂r̄₁ − f̄₁r̄₂) = 0` cho một nghiệm M-SIS. Vậy binding *mọi* hàng, kể cả các hàng thêm
sau thách thức (`t_u`, `t_g`, `t_G`), là hệ quả của binding nới lỏng của `t1'` với cùng thể hiện
M-SIS và cùng chuẩn. Hiding không bị ảnh hưởng: vector mặt nạ `(B1'r', ⟨b'_j, r'⟩)_j` được cố
định và giả ngẫu nhiên (M-LWE, bí mật hạng λ, `n + slots` mẫu) độc lập với thông điệp, nên việc
thêm thông điệp một cách thích nghi chỉ là one-time pad. `z'` được lấy mẫu loại bỏ độc lập với
`r'`, còn `t_G` dùng `⟨b'_G, r'⟩` đúng một lần (chỉ lần thử được chấp nhận được công bố). Kết
luận cuối "`m̄ = Aβ̄ + e_L` trên ℤ" đúng vì các bit nằm ở vị trí rời nhau, mỗi hệ số
`< 2^24 < q = 2^30 − 35`.

**Abort và số hạng thứ tự (nhiệm vụ 4).** Chỉ vòng cuối lặp lại; `D`, `h`, `s1..s3` cố định
(`binary_proof.py:541–558`, `payload_range_proof.py:563–581`). Một lần thử bị loại không được
công bố. Xác suất chấp nhận bằng đúng `((2B+1)/2γ)^{(k+k_aux)N}` độc lập với `(r, r', c)`
(`‖cr'‖∞ ≤ κ`, `r'` tam phân), nên số lần thử và việc chạm ngưỡng không rò rỉ gì về các vòng
trước. Mỗi truy vấn H4 bị ẩn chứa `w` có min-entropy `η` như trong `lem:sim`. Việc chỉ lặp vòng
cuối không ảnh hưởng tới rewinding: AFK22 chỉ quan tâm tới truy vấn H4 then chốt của đầu ra, và
các lần thử bị loại của một prover gian lận chỉ là các truy vấn được đếm trong Q. Số hạng
`Q²·2^-256` đúng về bản chất, chỉ thiếu hằng số (F5).

**Khóa mặt nạ hedged.** Π_pay băm `entropy, x, u32(L), C, m, r, bits` cùng tag giao thức và
`pid` (`payload_range_proof.py:527–530`), nên không có trường hợp tái dùng `r'` hoặc `y` cho hai
`L` có cùng ℓ. Đã thử: cùng `mask_seed`, khác `x` thì `D_0` khác nhau. Các lần thử dùng
`attempt` làm đếm trong một XOF khác domain với `r'` và `g_t`.

**Giải mã chính tắc, `verify` không ném (nhiệm vụ 5).** `codec.unpack_uints`
(`codec.py:19–33`) kiểm độ dài chính xác, padding bằng không và giá trị `< bound`. Đáp ứng có
`bound = 2B + 1`, nên `z ∈ [−B, B]` và mã hóa là duy nhất. `h_t[0] = 0` không thể mã hóa khác.
`Commitment.normalized` chỉ nhận các mảng `int64` đóng băng, đã rút gọn, đúng hình dạng. Các thử
nghiệm đã chạy (bộ toy, script ở scratchpad), tất cả đều cho `False` và không có ngoại lệ:
- proof dạng `bytearray`, statement dạng `memoryview`, commitment là `None` hoặc tuple, proof
  ngắn hoặc dài một byte, đổi statement, đổi bộ tham số, `params = None`;
- 40 phép lật bit ngẫu nhiên trong mỗi trường (aux, h, t_G, seed, z): 0 chấp nhận, 0 ngoại lệ;
  100 phép lật trong Π_pay: 0 / 0;
- 20 proof ngẫu nhiên có mọi trường trong biên (đi qua được `_parse`): 0 chấp nhận;
- giá trị đáp ứng `2^bits − 1 ≥ 2B + 1`: bị từ chối;
- Π_pay với `L ∈ {0, 4, 6, 7}` (cùng ℓ = 1), `True`, `−1`, `10^30`, `5.0`, `None`,
  `np.int64(5)`: đều cho `False`;
- dùng proof nhị phân làm proof khoảng: `False`.

Các hướng malleability đã xét mà không thành công: (a) đổi `z` mà giữ `(w, w', v)` cần
`B1Δ = 0` với `‖Δ‖ ≤ 2B`, tức một bài toán M-SIS; (b) đổi `seed` sang một seed khác có cùng `c`
thì giá trị băm tính lại vẫn chỉ bằng một seed duy nhất; (c) dùng lại proof cho `L'` cùng ℓ thì
`L` nằm trong `H_lift`; (d) dùng lại xuyên giao thức (mở, nhị phân, khoảng) thì domain và độ dài
khác nhau; (e) commitment không chính tắc thì bị loại trước khi băm.

**Tham số.** `|C| = 2^257.01`; `q ≡ 5 (mod 8)`; `8κB = 62 885 280`, `2·8κB < q`;
`payload_bytes_per_coefficient = 3`, `2^24 < q`.

## Những gì vẫn cần chuyên gia ngoài

1. **AFK22 với tiền tố thích nghi (G-ii):** đối chiếu nguyên văn định nghĩa knowledge soundness
   và định lý Σ-protocol của AFK22 (TCC 2022 / JoC 2023) để xác nhận rằng chúng phủ "phát biểu =
   `pre` được xác định qua chuỗi seed, các oracle khác coi là đồng xu của A", và rằng việc ghép
   extractor thời gian kỳ vọng của AFK22 với forking plurality (F_i chạy E hai lần từ một tiền tố
   giữa chừng) không cần thêm điều kiện nào.
2. **Phiên bản SE cho Π_pay (F3):** viết và kiểm định lý có các proof trung thực trong tầm nhìn
   của đối thủ, đặc biệt phần plurality khi tiền tố do simulator tạo.
3. **Ước lượng cụ thể cho bộ sản xuất:** M-SIS `7×25` đến `7×44` tại `ℓ∞ ≤ 8κB ≈ 2^25.9`
   (Q2: mô hình chi phí ℓ∞ khi `β/q ≈ 1/17`), M-LWE phụ trợ 18 đến 37 mẫu. Các file
   `bdlop_binary_128_v3.estimate.json`, `bdlop_payload_range_128_v2_l{1,4}.estimate.json` có
   tồn tại nhưng chưa được đánh giá này kiểm.
4. **Tổn thất căn bậc hai (G-i, Q4):** quyết định có chấp nhận cận không chặt, hay cần một
   hướng chặt hơn cho các vòng thống kê (ví dụ tăng `k = k' = 9` để các số hạng thống kê khớp
   `2^-256`; việc đó không giải quyết được phần M-SIS).
5. **QROM (G-iv):** chưa có lập luận nào.
6. **Q3 (`lem:invertible`):** xác nhận độc lập điều kiện Lyubashevsky–Seiler với `k = 2`. Tôi
   chỉ kiểm `q mod 8` và chặn `√(q/2)`.

## Đã áp dụng

Chỉ tài liệu được sửa; không file `.py` nào bị đụng tới (phần mã của F4 và F8,
tức `soundness_bits` theo tổng và các chú thích xác suất chấp nhận, do người điều
phối tự sửa). LaTeX chưa được biên dịch lại.

| ID | Trạng thái | Nơi áp dụng |
|---|---|---|
| F1 | Đã áp dụng | `binary_proof.tex`: `thm:bin-rbr` được viết lại thành chuỗi tất định (a), cận theo vòng cho thông điệp cố định (b) và 3-special-soundness của vòng cuối (c), kèm một đoạn nói rõ định lý không chặn một prover tùy ý. `PROOF…md` Phần I §4 và Phần II §4: phần dẫn của bảng sai số. |
| F2 | Đã áp dụng | `binary_proof.tex`: bỏ "duy nhất theo thm:binding" và mệnh đề "Cụ thể…" khỏi `thm:bin-ks`; thêm `cor:bin-sound` (soundness tính toán qua `thm:binding`, chuẩn `2κ+2B` / `8κB`) và đoạn đếm `72 960` so với `61 440` bit; `thm:pay` tham chiếu hệ quả. `PROOF…md` Phần I §4, Phần II §4; `QUESTIONS.md` Q16. |
| F3 | Đã áp dụng (phác thảo) | `binary_proof.tex`: thêm `thm:pay-se` cùng phác thảo chứng minh (mô phỏng, điểm `H_4` đã lập trình bị dùng lại cho M-SIS chuẩn `≤ 2B`, `Q' = Q + 7Q_P` gồm cả truy vấn của bộ mô phỏng trong plurality). `PROOF…md` Phần II §1, §4, §7 (câu hỏi 3a); `QUESTIONS.md` Q16 (câu hỏi mới). |
| F4 | Đã áp dụng phần văn bản | `binary_proof.tex` (`thm:bin-rbr`, `thm:bin-ks`, remark), `PROOF…md` (Phần I §4, §10; Phần II §4), `QUESTIONS.md` Q16: `ε_rbr ≈ 2^-149.0`, số hạng lớn nhất `2^-149.99`. |
| F5 | Đã áp dụng | `binary_proof.tex`, chứng minh `thm:bin-ks`: sự kiện `Coll`, `δ_coll = 13(Q+4)²·2^-256` thay cho `Q²/2^256`, câu "s3 xác định duy nhất tiền tố trên mọi lần chạy", và điều kiện của AFK22 được nêu rõ. |
| F6 | Đã áp dụng | `binary_proof.tex`, đoạn "Chứng minh không tương tác": mô hình hóa `Expand` và `G`, sai số combine thực tế `≈ 2^-256`, `Q` đếm cả `Expand`/`G`. `security.tex`, đoạn "Các oracle ngẫu nhiên": thêm `H_1..H_4` và `Expand` của hai chứng minh. |
| F7 | Đã áp dụng | `binary_proof.tex`, `thm:bin-zk`: `Q_P·Adv^MLWE_aux + ε_zk`, một điểm `H_4` mỗi chứng minh, bước (0) cho các hybrid khóa hedged và lần thử bị loại. `PROOF…md` Phần I §5. |
| F8 | Đã áp dụng phần văn bản | `binary_proof.tex` và `PROOF…md` (§1, §6, §7, §8, §9 Phần I; §1, §2, §5, §6 Phần II): số liệu của `bdlop-binary-128-v3` (45 134 B, 0.00885, `2^-210.05`, `7×25`, 18 mẫu), `bdlop-payload-range-128-v2` (46 670–74 318 B, 0.0079–0.00094, `2^-1492`–`2^-177`) và nền `bdlop-open-128-v3` (7 680 B / 8 672 B, M-SIS 172/156, M-LWE 169/153); số của v1/v2 giữ lại trong ngoặc. |
| F9 | Đã áp dụng | `PROOF…md` Phần I §4: bỏ việc dựa vào Canetti et al., chỉ tới `thm:bin-ks`. |
| F10 | Đã áp dụng | `binary_proof.tex`, cuối chứng minh `thm:bin-ks` (đoạn "Các phép rút gọn M-SIS": đoán khóa, thừa số tối đa 5 cho Π_pay, thời gian chạy `≈ 2(3+2Q)`); `PROOF…md` Phần II §4. |
| F8 (bổ sung) | Đã áp dụng | `security.tex` (dòng 44, bảng `tab:sec-numbers`, đoạn giả thiết) và `security_appendix.tex` (mục "Tính đầy đủ"): hằng số của bộ nền `bdlop-open-128-v3` (`n = 7`, `k = 15`, `kN = 3 840`, `p_acc = 0.1698`, trung bình 5.89 / 34.7 lần thử, toàn-abort `2^-137.5` / `2^-173.0`, `η = 32 254.81`, `3^{kN}q^{-(n+1)N} ≈ 2^-55 354`, cam kết / chứng minh 7 680 / 8 672 B, envelope 16 421 / 8 741 B, M-SIS 172/156, M-LWE 164/150). |
| F11 | Không áp dụng | Chỉ là ghi chú về mã. |
| G-i…G-iv | Giữ nguyên | Đã ghi trong danh sách khoảng trống sau `thm:bin-ks`: G-ii và G-iii được thu hẹp như trên; G-i và G-iv vẫn là các giới hạn đã tuyên bố. |

Vẫn dành cho chuyên gia ngoài: đối chiếu từng dòng với AFK22 (G-ii); kiểm
`thm:pay-se`, nay mới chỉ là một phác thảo do chính người đánh giá viết, nên cần
một người kiểm độc lập; các ước lượng cụ thể cho các thể hiện phụ trợ sản xuất;
khả năng chấp nhận tổn thất căn bậc hai; QROM; Q3.
