# Chứng minh video BDLOP: đặc tả giao thức và lập luận bảo mật

Phiên bản 1 (`bdlop-open-v1`), cài đặt trong `src/lattice_zk/`. Tài liệu này
đặc tả chính xác các thuật toán mà mã chạy và lập luận từng tính chất bảo mật
dựa trên các kết quả đã công bố. Nó được viết để giao thức có thể được cài đặt
lại và đối chiếu với các vector known-answer trong
`research/bdlop_params/kat_v3.json` (bộ sản xuất `bdlop-open-128-v3`;
`kat_v2.json` và `kat_v1.json` ghim các bộ cũ hơn `-v2`, `-v1`).

Cấu trúc là cam kết và chứng minh opening của Baum, Damgård, Lyubashevsky,
Oechsner và Peikert (SCN 2018, ePrint 2016/997), với ba khác biệt có chủ đích
liệt kê ở Mục 6. Phần cài đặt chưa được audit và không phải constant time.

## 1. Ký hiệu

- `R = Z[X]/(X^N + 1)`, `R_q = R / qR`, `N` là lũy thừa của hai.
- `q` nguyên tố với `q ≡ 5 (mod 8)`. Khi đó `X^N + 1` tách thành đúng hai đa
  thức bất khả quy bậc `N/2` modulo `q`, và mọi `y ∈ R_q` khác không với
  `‖y‖∞ < q^{1/2}/√2` đều khả nghịch (Lyubashevsky–Seiler, EUROCRYPT 2018,
  Hệ quả 1.2 với `k = 2`).
- `n`: hạng M-SIS, `λ`: hạng M-LWE, một đa thức message, `k = n + λ + 1`.
- `S_1`: các đa thức có hệ số trong `{-1, 0, 1}`.
- `C = {c ∈ R : ‖c‖∞ = 1, ‖c‖₁ = κ}`, tập challenge, `|C| = binom(N, κ)·2^κ`.
- `γ`: chặn mặt nạ (lũy thừa của hai); `B = γ − κ − 1`: chặn đáp ứng.
- `H`: SHAKE-256 với các domain tag cho dưới đây; mọi số nguyên big-endian.

## 2. Tham số

| | `bdlop-open-128-v3` (sản xuất) | `bdlop-open-128-v2` (cũ) |
|---|---|---|
| `N`, `q` | 256, `2^30 − 35` | như v3 |
| `n`, `λ`, `k` | 7, 7, 15 | 6, 7, 14 |
| `κ`, `γ`, `B` | 60, `2^17`, `2^17 − 61` | như v3 |
| `|C|` | `2^257` | `2^257` |
| Cam kết | `(n+1)·N·30` bit = 7 680 byte | 6 720 byte |
| Chứng minh opening | `32 + k·N·18` bit = 8 672 byte | 8 096 byte |
| Equality proof | `32 + 2·k·N·18` bit = 17 312 byte | 16 160 byte |
| Xác suất chấp nhận mỗi lần thử | `((2B+1)/(2γ))^{kN} ≈ 0.170` | ≈ 0.191 |

Bộ v3 (2026-10-26) chỉ nâng hạng M-SIS `n` từ 6 lên 7 so với v2, để binding
vượt 128 bit lượng tử; mọi thứ khác giữ nguyên. Video, registry và statement
tạo dưới v2 vẫn verify dưới v2 (`parameter_id` khác nhau); mã giữ cả ba bộ.

`parameter_id = SHA3-256("zkstego/lattice-zk/bdlop-open/v1/parameters\0" ‖
len(name) ‖ name ‖ N ‖ q ‖ n ‖ λ ‖ κ ‖ γ ‖ setup_seed)` ghim mọi giá trị.

Bảo mật cụ thể, từ `research/bdlop_params/estimate.py` với mô hình
security-estimates của CRYSTALS (commit `75c26949`), chi phí core-SVP:

| Bài toán (v3) | Instance | Block size | Cổ điển | Lượng tử |
|---|---|---|---|---|
| M-SIS (binding) | `B1 ∈ R_q^{n×k}`, chặn `ℓ∞` `8κB ≈ 2^25.9` | 589 | **172** | **156** |
| M-LWE (hiding), primal | hạng `λ`, `n+1 = 8` mẫu, secret và error tam phân | 580 | 169 | 153 |
| M-LWE, dual hybrid (lattice-estimator `e4333d9`) | như trên | 564 / 567 | **164** | **150** |

Các mất mát trong reduction bị bỏ qua, giống như với ML-DSA. Mức hiding được
tuyên bố là con số dual-hybrid thấp hơn. Đối chiếu độc lập bằng
lattice-estimator (`research/bdlop_params/lattice_estimator_crosscheck_v3.json`,
`CROSSCHECK.md`): M-SIS 171,99 / 156,09, M-LWE primal 169,4 / 153,7, dual
hybrid 164,9 / 150,3 bit — khớp với CRYSTALS; dưới mô hình MATZOV mọi tấn công
đều trên 189 bit. Bộ `-v2` (n = 6) có binding 140 / 127 bit — 127 hơi dưới
128, lý do ra đời v3; bộ `-v1` (λ = 6) chỉ 135 / 123 bit cho M-LWE dual hybrid,
lý do v2 nâng λ lên 7.

## 3. Thuật toán

### 3.1 Khóa công khai

`B1 = [I_n | B1']` với `B1' ∈ R_q^{n×(λ+1)}`, `b2 = [0^n | 1 | b2']` với
`b2' ∈ R_q^{1×λ}`. Cả hai được trải bằng rejection sampling từ
`H("zkstego/lattice-zk/bdlop-open/v1/key\0" ‖ parameter_id)`. Không có
trapdoor và không có trusted setup.

### 3.2 Commit

Payload đầu vào `p` với `|p| ≤ N·⌊(log₂q − 1)/8⌋ − 2` byte. Mã hóa
`len(p) (2 byte) ‖ p ‖ 0…` thành `N` hệ số, mỗi hệ số ba byte; cách mã hóa này
đơn ánh và ảnh của nó được kiểm khi decode. Lấy mẫu `r ← S_1^k` và xuất
`t1 = B1·r`, `t2 = ⟨b2, r⟩ + m`.

Một đối tượng `Commitment` là canonical theo cấu trúc (D8): nó mang theo bộ
tham số của mình, và constructor của nó từ chối mọi thứ trừ mảng số nguyên có
shape `(n, N)` và `(N,)` với mọi hệ số trong `[0, q)`; nó lưu các bản sao
`int64` chỉ đọc. `from_bytes`, `commit` và `dataclasses.replace` đều đi qua
constructor đó. Verifier vẫn kiểm lại mọi cam kết nhận được
(`require_commitment`, `is_canonical`), nên một đối tượng dựng vòng qua
constructor cũng bị từ chối.

### 3.3 Prove (opening)

Đầu vào statement bytes `x`, cam kết `t = (t1, t2)`, witness `r`.

1. Kiểm `‖r‖∞ ≤ 1` và `B1·r = t1`; nếu không thì từ chối.
2. `K = SHA3-256("zkstego/lattice-zk/hedged-mask-key/v2\0" ‖ len(P) ‖ P ‖
   len(pid) ‖ pid ‖ entropy ‖ len(x) ‖ x ‖ len(t) ‖ t ‖ len(r) ‖ r)` (hedged,
   phân tách domain; D7), với nhãn giao thức `P = "bdlop-open"`
   (`"bdlop-equal"` cho 3.5, `"bdlop-binary"` cho binary proof) và
   `pid = parameter_id`. Chỉ `bdlop-open-128-v1` giữ `K` không gắn tag cũ
   `K = SHA3-256(entropy ‖ len(x) ‖ x ‖ …)` cho opening và equality proof của
   nó, nên `kat_v1.json` không đổi; `kat_v2.json` và KAT binary được sinh lại
   cho khóa đã gắn tag. `K` chỉ seed cho mặt nạ của prover: verifier không bao
   giờ tính lại nó, nên chứng minh từ cách dẫn xuất nào cũng verify được.
3. Với lần thử `i = 1, 2, …` (tối đa 512):
   - `y ← [−γ+1, γ]^{kN}` từ `H(mask-domain ‖ K ‖ i)`;
   - `w = B1·y`;
   - `seed = H(fs-domain ‖ parameter_id ‖ len(x) ‖ x ‖ t ‖ w)`, 32 byte;
   - `c = SampleInBall(seed)` (Fisher–Yates kiểu ML-DSA trên đầu ra SHAKE, trọng số `κ`);
   - `z = y + c·r`; nếu `‖z‖∞ ≤ B` thì xuất `π = seed ‖ Pack(z + B)`.

Không gì từ một lần thử bị loại rời khỏi prover.

### 3.4 Verify (opening)

Từ chối trừ khi `|π|` đúng chính xác, mọi giá trị đóng gói nằm trong `[0, 2B]`
và các bit padding bằng không. Tính lại `c` từ `seed`, `w' = B1·z − c·t1`, và
chấp nhận khi và chỉ khi `seed = H(fs-domain ‖ parameter_id ‖ len(x) ‖ x ‖ t ‖ w')`.

Độ mạnh sản xuất (Q12): mọi verifier mức ứng dụng
(`verify_video_proof`, `verify_envelope`, `verify_registered_envelope`,
`verify_disclosure_proof`, `verify_commitment_disclosure`, `verify_linkage`,
và `pins_from_registry`) ném `ValueError` cho một bộ tham số có không gian
challenge dưới `2^256` trừ khi caller truyền
`allow_toy_parameters=True`. Các nguyên thủy chứng minh của 3.4 và 3.5 vẫn là
các khối xây dựng không phụ thuộc tham số.

### 3.5 Equality proof

Với `t_a = Com(m; r_a)` và `t_b = Com(m; r_b)`, prover lấy mẫu `y_a, y_b`,
gửi `w_a = B1·y_a`, `w_b = B1·y_b`, `u = ⟨b2, y_a − y_b⟩` qua hàm băm, và đáp
`z_a = y_a + c·r_a`, `z_b = y_b + c·r_b`, hủy trừ khi cả hai trong biên.
Verifier tính lại `w_a, w_b` như ở 3.4 và
`u' = ⟨b2, z_a − z_b⟩ − c·(t2_a − t2_b)`. Prover có trần riêng 4 096
lần thử (`equality_proof.MAX_ATTEMPTS`; xem 4.1). Một trong hai witness có thể
là vector toàn không, vốn là tam phân: `Com(m; 0) = (0, m)` là cam kết công
khai dùng cho disclosure (3.7).

### 3.6 Statement video

Statement Fiat–Shamir `x` là mã hóa cố định độ rộng

```text
u16 version ‖ relation_id ‖ parameter_id ‖ registry_root ‖ u64 registry_epoch ‖
session_challenge ‖ codec_policy_id ‖ carrier_profile_id ‖ u64 carrier_count ‖
positions_hash ‖ video_commitment
```

với mọi digest 32 byte. Verifier dựng nó chỉ từ cấu hình đã ghim của mình
(relation, registry root và epoch, codec policy, carrier profile) và từ các
giá trị nó tính lại từ luồng H.264 nhận được: danh sách carrier (do đó
`carrier_count` và `positions_hash`) và
`video_commitment = SHA-256("zkstego/video-zk/video-commitment/v1\0" ‖ D)`.
`D` được tính trên luồng đã tách bằng `ffmpeg -c:v copy -f segment` thành các
segment gồm `frames_per_segment` khung:
`D = SHA-256("zkstego/canonical-h264-segmented/v1\0" ‖ u32 F ‖ u32 L ‖
(u32 i ‖ u32 frames_i ‖ d_i)_{i<L})`. Với một segment mang các chunk envelope,
`d_i` là SHA-256 của một serialization có gắn tag, phân tách độ dài, của các
NAL unit đã parse (các trường header, RBSP của những NAL unit không có carrier,
và với các IDR NAL unit mang carrier là các bit RBSP giữa các block carrier cho
đến stop bit, mỗi block carrier được thay bằng vector hệ số của nó trong đó mọi
carrier được chuẩn hóa); với các segment khác `d_i` là SHA-256 của file
segment. Vì `D` chuẩn hóa đúng các vị trí mang envelope, chứng minh có thể gắn
video mà không phụ thuộc chính các bit của nó. Những gì `D` không gắn được liệt
kê ở phần bảo mật của bài báo (`docs/paper/sections/security.tex`, integrity
limits).

**Codec policy v2 (D5).** Định nghĩa trên là codec policy
`h264-baseline-cavlc/canonical-h264-carrier-normalized-sha256-v1`; nó được giữ
nguyên từng byte (identifier, profile id, `D`) cho các video đã có. Một carrier
profile có thể chọn
`CODEC_POLICY_V2 = "…-sha256-v2/full-rbsp/tagged-raw-segments/segmentation=annexb-access-unit-exact-partition-v1"`;
nó được thêm vào mô tả profile dưới dạng `"codec_policy"`, nên profile id, policy
hash, relation id và statement của nó khác với v1. Dưới v2:

- (a) một segment không có carrier có
  `d_i = SHA-256("zkstego/canonical-h264-raw-segment/v2\0" ‖ u64 len ‖ bytes)`,
  và `D = SHA-256("zkstego/canonical-h264-segmented/v2\0" ‖ u16 len ‖ rule ‖
  u32 F ‖ u32 L ‖ u32 C ‖ (u32 i ‖ u32 frames_i ‖ u8 kind_i ‖ d_i)_{i<L})`,
  trong đó `C` segment đầu mang chunk (`kind = 1`) và phần còn lại là raw
  (`kind = 0`);
- (b) một IDR NAL unit mang carrier được băm trên toàn bộ RBSP của nó, trước đó
  là độ dài byte của nó, nên các bit không sau stop bit (và mọi byte không được
  thêm) đều bị gắn; v1 dừng ở stop bit;
- (c) cách segment hóa được ghim: các segment phải đúng là phân hoạch
  access-unit của đầu vào (segment `k` bắt đầu ở byte đầu tiên của start code mở
  access unit `k·F`, H.264 7.4.1.2.3), kiểm từng byte sau khi ffmpeg đã tách
  luồng. Khi đó `D` chỉ là hàm của các byte đầu vào; một bản ffmpeg cắt ở chỗ
  khác sẽ fail closed thay vì âm thầm đổi phạm vi được băm. Bản thân phiên bản
  ffmpeg không được băm: điều đó sẽ khiến verification phụ thuộc vào cài đặt của
  verifier mà không gắn thêm gì mà kiểm tra phân hoạch chưa gắn;
- ngoài ra, các byte không dẫn đầu của một segment carrier trước start code đầu
  tiên được đếm, các NAL unit của nó phải escape canonical, và các loại NAL unit
  mà parser không mô hình hóa bị từ chối.

Carrier profile cũng cố định một GOP policy (`src/transport/gop_policy.py`),
kiểm trên mọi segment trước khi phân tích: `all-intra` (mặc định; mọi slice đã
mã hóa đều là IDR) hoặc `idr-carriers-inter-raw-v1` (GOP > 1: carrier chỉ trong
slice IDR, các slice P và I không IDR được băm raw RBSP trong `d_i`, mỗi segment
bắt đầu bằng IDR). Cả hai đều đòi emulation prevention canonical, nên RBSP bằng
nhau là NAL byte bằng nhau. Một policy không mặc định được thêm vào mô tả
carrier-profile dưới dạng `"gop_policy"`; các identifier profile all-intra không
đổi. Xem `docs/GOP_HD_SUPPORT.md`.

Một trường profile opt-in `chunk_plan` thay thế `chunk_bytes` cố định bằng một
kế hoạch thích ứng theo dung lượng (ZKBC v2): kích thước chunk theo dung lượng
carrier tính-lại-được của mỗi segment, các segment dung lượng thấp bị bỏ qua,
kế hoạch thay `"chunk_bytes"` bằng `"chunk_plan"` trong mô tả profile, và `D`
dùng domain `zkstego/canonical-h264-segmented-adaptive/v1` với vai trò, dung
lượng và kích thước chunk theo từng segment. Xem `docs/CARRIERS_VA_CHUNKING.md`.

### 3.7 Envelope

```text
in-band             "ZKLB" ‖ 0x01 ‖ parameter_id ‖ session_challenge ‖ t ‖ π
registered          "ZKLR" ‖ 0x01 ‖ parameter_id ‖ session_challenge ‖ π
in-band + đính kèm  "ZKLB" ‖ 0x02 ‖ parameter_id ‖ session_challenge ‖ t ‖ π ‖ 0x01 ‖ u16 L ‖ π_range
```

**Đính kèm range proof (phiên bản 2).** Một carrier profile in-band có thể
ghim một độ dài payload `L` (`CarrierProfile.payload_range_length`; CLI
`--payload-range-bytes L`). Khi đó envelope mang thêm payload range proof
`π_range` (`src/lattice_zk/payload_range_proof.py`, bộ
`bdlop-payload-range-128-v2` trên nền v3) cho statement
`"zkstego/lattice-zk/envelope-attachment/payload-range/v1\0" ‖ x` — chính
statement video `x`, nên không chuyển được sang video hay phiên khác. Verifier
biết `L` từ profile (nó nằm trong `carrier_profile_id`), từ chối mọi envelope
có phiên bản, loại đính kèm hay `L` khác, và chỉ chấp nhận khi cả `π` lẫn
`π_range` verify. `L` công khai; holder giấu độ dài thật bằng cách đệm tới một
lớp độ dài (`pad_payload`: `p ‖ 0x80 ‖ 0x00…`, CLI đệm tự động). Kích thước
`π_range` (bộ sản xuất): 46 670 byte cho `L ≤ 32`, 74 318 byte cho `L = 128`;
envelope in-band đính kèm `L = 32`: 63 094 byte. Chứng minh `L = 32` mất
≈ 6 s, `L = 128` ≈ 3 phút (766 lần thử); verify ≈ 0,3 s.

Các vị trí carrier được sắp bằng một keyed shuffle. Với một khóa stego bí mật
chia sẻ với verifier, kênh vẫn không phát hiện được với bất kỳ ai không có
khóa; với khóa dẫn xuất từ cấu hình công khai
(`public_sync_key = SHA-256(domain ‖ parameter_id ‖ carrier_profile_id)`,
CLI `--public-carrier-order`) bất kỳ ai giữ registry đều verify được, đổi lại
mất tính không phát hiện được. Soundness và zero knowledge của chứng minh không
phụ thuộc khóa này.

Ở chế độ registered, `t` là một cam kết credential mà các byte của nó được băm
vào relation descriptor do issuer ký (ML-DSA-65) vào registry. Session
challenge là một giá trị 32 byte do verifier phát và tiêu thụ một lần, nguyên
tử, sau khi verification thành công.

**Phiên offline theo epoch** (`src/registry/epoch_challenges.py`). Thay cho
phiên tương tác, issuer phát mỗi cửa sổ thời gian `W` giây một *epoch beacon*
ký ML-DSA-65: `(epoch_index = ⌊t/W⌋, W, nonce 32 byte, signer_id)`; challenge
là `SHA-256("zkstego/video-zk/epoch-challenge/v1\0" ‖ "challenge\0" ‖ u64
epoch_index ‖ u64 W ‖ nonce ‖ u16 |signer_id| ‖ signer_id)`, tính lại từ các
trường đã ký chứ không đọc từ video. Holder gắn statement vào challenge đó
(CLI `embed --epoch-beacon`); verifier (`verify_video_proof_offline`, CLI
`verify --epoch-beacon`) kiểm chữ ký issuer, đòi beacon không ở tương lai và
không cũ quá `max_age_epochs` cửa sổ (mặc định 24 × 3600 s), verify như
`expected_session`, rồi ghi `(challenge, statement_id)` vào một sổ SQLite
riêng (`OfflineReplayLedger`): cùng statement xuất hiện lần hai ở cùng
verifier là phát lại và bị từ chối. Mỗi dòng sổ giữ tới khi beacon của nó hết
hạn (`(epoch_index + max_age_epochs + 1)·W`) rồi mới bị xoá; sổ ghi cấu hình
`(W, max_age_epochs)` và từ chối mở với cấu hình khác, nên việc dọn sổ không
bao giờ chạy trước hạn beacon. Lệch giờ: beacon của cửa sổ kế tiếp được chấp
nhận sớm một cửa sổ (`skew_epochs = 1`). Sổ không chia sẻ giữa các verifier, nên
chế độ này cho *tươi mới* (không phát lại được video cũ quá cửa sổ) và *chống
phát lại theo từng verifier*; cần chống phát lại toàn cục thì dùng phiên tương
tác.

**Danh tính holder.** Issuer có thể gắn credential với một định danh holder
`h` (một chuỗi UTF-8 chuẩn hóa NFC, không rỗng, tối đa 256 byte; CLI
`--holder-id`). Tập trường registry không đổi: `verifier_key_hash` của
descriptor trở thành

```text
SHA-256(B1' ‖ b2' ‖ t ‖ SHA-256("zkstego/lattice-zk/video-pipeline/v1/holder-id\0" ‖ u16 |h| ‖ h))
```

thay vì `SHA-256(B1' ‖ b2' ‖ t)` (các block khóa dưới dạng từ 64-bit
big-endian, `t` đóng gói như trên dây); mỗi phần có độ dài cố định bởi
`parameter_id`, nên mã hóa là không nhập nhằng, và không có `h` thì descriptor
(và mọi registry đã có) không đổi. Một holder id bị từ chối với các profile
in-band. Pins chỉ resolve khi verifier cung cấp đúng `h`
(`pins_from_registry(..., holder_id=h)`), nên chữ ký của issuer phủ "cam kết `t`
thuộc về holder `h`".

**Pins và credential.** `verify_video_proof` tính lại relation id của
`(bộ tham số, carrier profile, credential, holder id)` và ném `ValueError` trừ
khi nó bằng `pins.relation_id`. Một sai khớp (pins resolve cho credential này
nhưng dùng với credential khác, pins in-band với profile registered hoặc ngược
lại, một holder id sai hoặc thiếu) là lỗi cấu hình verifier, báo trước khi video
được đọc; nội dung video chỉ bao giờ cho ra `valid = False`.

**Disclosure.** Holder tiết lộ payload `p` của một cam kết `t` cho một người
nhận mà không trao `r`:

```text
ctx         = "zkstego/lattice-zk/disclosure/v1\0" ‖ parameter_id ‖
              u64 32 ‖ statement_id ‖ u64 32 ‖ nonce
t'          = Com(encode(p); 0) = (0, encode(p))
π_eq        = equality proof (3.5) của (t, r) và (t', 0) cho statement ctx
disclosure  = "ZKLD" ‖ 0x01 ‖ parameter_id ‖ u16 |p| ‖ p ‖ π_eq
```

`statement_id` đặt tên cho những gì được tiết lộ (statement id video đã verify
cho một envelope in-band; với credential registered, bất kỳ id 32 byte nào
người nhận đặt tên, chẳng hạn relation id) và `nonce` là một giá trị 32 byte do
người nhận chọn, nên một disclosure tạo cho người nhận này hoặc video này không
verify cho người/video khác. Người nhận tính lại `t'` từ `p` và verify `π_eq`
với cam kết đã có (`verify_disclosure_proof` cho một envelope,
`verify_commitment_disclosure` cho một credential; CLI `disclose` và
`disclosure-verify`). Kích thước: 39 byte + `|p|` + 16 160 byte cho bộ sản
xuất. Chứng minh có thể chuyển nhượng: một bên thứ ba tin rằng nonce là mới
cũng được thuyết phục. `self_check_opening` (trước là `verify_disclosure`) kiểm
`(p, r)` trực tiếp và chỉ là self-check phía holder: ai được trao `r` đều chứng
minh được tri thức về opening cho các statement mới.

## 4. Lập luận bảo mật

Xuyên suốt, `‖c·v‖∞ ≤ ‖c‖₁·‖v‖∞`.

### 4.1 Completeness

`‖c·r‖∞ ≤ κ`, nên một lần thử trung thực được chấp nhận với xác suất
`((2B+1)/(2γ))^{kN}` (Mục 2), số lần thử kỳ vọng là nghịch đảo của nó (5.23
cho bộ sản xuất; đo được 4.68 qua 50 lượt với `bdlop-open-128-v1` (chưa đo
lại dưới v2)), và một `z` được chấp nhận thỏa phương trình verification vì
`t1 = B1·r`. Xác suất 512 lần thử đều hủy là `(1 − 0.191)^{512} < 2^{-156}`.
Equality proof (3.5) chấp nhận với xác suất `0.191^2 ≈ 0.037` mỗi lần thử
(trung bình 27.4 lần thử). Nó có trần riêng 4 096 lần thử, nên thất bại với
xác suất `(1 − 0.037)^{4096} ≈ 2^{-220}` (trần chung 512 dùng trước đây cho
`2^{-35}` với `bdlop-open-128-v1`). Trần lớn hơn không ảnh hưởng zero knowledge,
vì chấp nhận độc lập với witness, kể cả witness không của một disclosure.
`test_equality_prover_cap_gives_negligible_completeness_error`
kiểm chặn `< 2^{-128}` từ các tham số.

### 4.2 Honest-verifier zero knowledge của các transcript được chấp nhận

Cố định `c` và `v = c·r` với `‖v‖∞ ≤ κ`. Với mọi `z0` thỏa `‖z0‖∞ ≤ B`, mặt
nạ `y = z0 − v` nằm trong `[−B−κ, B+κ] = [−γ+1, γ−1] ⊂ [−γ+1, γ]`. Do đó mỗi
`z0` như vậy có xác suất đúng bằng `(2γ)^{−kN}`, và với điều kiện chấp nhận thì
`z` phân phối đều trên `[−B, B]^{kN}` độc lập với `r`. Một simulator lấy mẫu `z`
đều từ tập đó và `c` đều từ `C`, đặt `w = B1·z − c·t1`, và lập trình random
oracle tại `(parameter_id, x, t, w)`. Đây là lập luận của đặc tả ML-DSA
(Phụ lục B) áp dụng cho khóa BDLOP; nó yêu cầu `w` có min-entropy cao, điều này
đúng vì `B1 = [I_n | B1']` và `y` đều trên `2^{18·kN}` giá trị. Sai lệch mà
rejection sampling đưa vào random oracle, bị các phân tích trước bỏ sót, được
Barbosa và cộng sự (2023) và Devevey và cộng sự (2023) xử lý; các chứng minh
ROM đã sửa của họ áp dụng cho biến đổi này.

Test `test_accepted_response_coordinate_is_uniform_for_any_witness`
kiểm tính đều trên một bộ tham số nhỏ, và
`test_respond_accepts_exactly_the_response_range` kiểm biên chấp nhận.

### 4.3 Special soundness và knowledge soundness

Hai transcript được chấp nhận `(w, c, z)`, `(w, c', z')` với `c ≠ c'` cho
`B1·(z − z') = (c − c')·t1`. Đặt `f = c − c'` và `r̄ = z − z'`. Khi đó
`‖f‖∞ ≤ 2 < q^{1/2}/√2`, nên `f` khả nghịch trong `R_q`, và `‖r̄‖∞ ≤ 2B`.
Cặp `(r̄, f)` là một *relaxed opening*: nó định nghĩa message
`m̄ = t2 − f^{−1}·⟨b2, r̄⟩`. Forking lemma biến điều này thành knowledge
soundness của chứng minh không tương tác trong mô hình random oracle, với một
reduction không chặt. Test
`test_two_transcripts_with_one_mask_yield_a_relaxed_opening` kiểm các phương
trình này trên transcript thật.

### 4.4 Binding theo relaxed opening

Giả sử `(r̄, f, m)` và `(r̄', f', m')` là các relaxed opening của một cam kết
với `m ≠ m'`. Từ `f·t1 = B1·r̄` và `f'·t1 = B1·r̄'`,
`B1·x = 0` với `x = f'·r̄ − f·r̄'`. Nếu `x = 0` thì `⟨b2, x⟩ = 0`, điều này
cùng `f·t2 = ⟨b2, r̄⟩ + f·m` và `f'·t2 = ⟨b2, r̄'⟩ + f'·m'` cho
`f·f'·(m − m') = 0`, mâu thuẫn với tính khả nghịch của `f, f'`. Vậy `x ≠ 0` là
một nghiệm M-SIS cho `B1` với `‖x‖∞ ≤ 2·(2κ)·(2B) = 8κB`, chặn được ước lượng ở
Mục 2. Constructor của `BdlopParams` từ chối mọi bộ mà `2·8κB ≥ q`, nơi nghiệm
có thể wrap modulo `q`.

### 4.5 Hiding

Viết `r = (r1, r2, r3) ∈ R^n × R × R^λ` và `B1' = [B1'_2 | B1'_3]`. Khi đó
`t2 − m = r2 + b2'·r3` và `t1 − B1'_2·(t2 − m) = r1 + (B1'_3 − B1'_2·b2')·r3`.
Với mỗi `m` cố định, ánh xạ `(t1, t2) ↦ (t1 − B1'_2·(t2 − m), t2 − m)` là một
song ánh công khai, và ảnh của nó là một instance M-LWE với secret `r3` hạng
`λ`, `n + 1` mẫu vành, error tam phân `(r1, r2)` và ma trận đều
`[B1'_3 − B1'_2·b2' ; b2']`. Đây là instance được ước lượng ở Mục 2.

### 4.6 Equality proof

Hai transcript được chấp nhận với một `(w_a, w_b, u)` cho các relaxed opening
`(r̄_a, f)` và `(r̄_b, f)` với một `f` *chung*, và từ phương trình thứ ba
`f·(t2_a − t2_b) = ⟨b2, r̄_a − r̄_b⟩`. Thay vào định nghĩa message cho
`m̄_a = m̄_b`. Zero knowledge suy ra như ở 4.2, áp dụng cho cả hai đáp ứng.

### 4.7 Gắn vào video và phiên

Cả `parameter_id`, `x` và toàn bộ cam kết đều vào hàm băm trước khi `c` được
dẫn xuất. `x` được phân tách độ dài; `parameter_id`, cam kết và `w` có độ dài
cố định bởi `parameter_id`, nên đầu vào băm giải mã được duy nhất và một chứng
minh chỉ verify cho đúng statement và cam kết nó được tạo ra. Verifier không bao
giờ đọc các giá trị statement từ video: nó tính lại chúng và so session
challenge với kho của mình. Thay đổi bất kỳ cú pháp không-carrier nào mà `D`
phủ sẽ đổi `D`; thay đổi một carrier sẽ đổi envelope. Cả hai đều bị từ chối
(`test_envelope_is_rejected_under_any_other_statement`, các kiểm tra tamper
trong các lượt chạy E2E). Verifier cũng re-chunk envelope đã trích dưới
`chunk_bytes` đã ghim và từ chối trừ khi các mảnh trích ra bằng đúng mã hóa đó
từng byte, nên các bit carrier là mã hóa duy nhất của envelope. Không có kiểm
tra này, một envelope đơn chunk để trống trường header `chunk_size` 16-bit
(bất kỳ giá trị nào từ độ dài envelope đến 65 535);
`test_rewritten_single_chunk_header_is_rejected` phủ nó. Chứng minh và chặn:
`docs/paper/sections/security.tex`.

### 4.8 Chứng minh thiết lập điều gì

- **Chế độ in-band**: người tạo video này, cho phiên này, biết một opening của
  cam kết nó mang. Payload vẫn ẩn và có thể được tiết lộ sau cho một bên được
  chọn. Điều này không định danh người tạo. Disclosure (3.7) là một equality
  proof đối với `(0, encode(payload))` với randomness không: extraction cho một
  relaxed opening `(r̄', f)` của `(0, encode(p))` với `B1·r̄' = 0`, nên `r̄' = 0`
  trừ khi M-SIS bị phá và cam kết được mang giấu `p`. Randomness `r` không được
  tiết lộ, nên người nhận không chứng minh được gì về cam kết về sau.
- **Chế độ registered**: người tạo biết opening của một cam kết credential mà
  issuer đã đăng ký, nên chỉ người giữ credential mới tạo được chứng minh. Lập
  luận cần, ngoài binding, rằng một relaxed opening của một cam kết sinh trung
  thực là khó tìm (M-SIS, hoặc M-LWE khi opening tìm được là chính `r` của
  holder). Với một holder id (3.7) chữ ký của issuer cũng phủ "cam kết này thuộc
  về holder `h`", và khi đó chứng minh xác thực `h`. Không có nó, descriptor
  registered chỉ gắn cam kết và liên kết từ một cam kết tới một người đến từ
  ngoài registry đã ký. Dù cách nào, issuer được tin là đã kiểm `h` là ai.
- **Linkage**: hai cam kết được mang, hoặc một cam kết được mang và một
  credential, giấu cùng một payload.

Nó không thiết lập rằng payload là đúng sự thật, rằng một camera đã ghi video,
hay rằng một bộ mã hóa H.264 đã chạy đúng.

## 5. Cách diễn đạt hậu lượng tử

Các chứng minh trên ở trong mô hình random oracle cổ điển dưới M-SIS và M-LWE.
Không tuyên bố chứng minh quantum-random-oracle chặt. Cách diễn đạt phù hợp là
"plausibly post-quantum": các bài toán nền không có thuật toán lượng tử hiệu
quả nào đã biết, và các kết quả tổng quát (Don, Fehr, Majenz, Schaffner,
CRYPTO 2019; Liu–Zhandry, CRYPTO 2019) cho thấy biến đổi Fiat–Shamir bảo toàn
soundness của các giao thức như vậy trước đối thủ lượng tử với mất mát đa thức.

## 6. Khác biệt so với BDLOP và vì sao

1. **Masking đều thay vì Gauss.** Số học nguyên chính xác và một đáp ứng được
   chấp nhận đều một cách chính xác (4.2), đổi lại norm trích ra lớn hơn. Do đó
   binding được ước lượng theo `ℓ∞` với chặn `8κB` thay vì tái dùng từ bảng của
   bài báo.
2. **Fiat–Shamir với statement tường minh.** Bản gốc là một giao thức tương
   tác; ở đây challenge được dẫn xuất từ toàn bộ statement và cam kết, với dẫn
   xuất mặt nạ hedged.
3. **Tham số khác.** Bậc vành nhỏ hơn với hạng module lớn hơn, chọn bởi
   estimator để tối ưu kích thước ở mức 128 bit. Bảng tham số của chính bài báo
   không được dùng.

## 7. Giới hạn đã biết

- Soundness là relaxed (Mục 4.3); payload chỉ được gắn qua binding theo relaxed
  opening.
- Không constant time: số học số nguyên lớn của Python và các vòng rejection
  phụ thuộc dữ liệu.
- Chế độ in-band không xác thực người tạo; session challenge không bí mật, nên
  hãy phát nó qua một kênh đã xác thực nếu điều đó quan trọng.
- Chứng minh opening không nói gì về message. Hai chứng minh tùy chọn trên
  cùng vành bổ sung điều đó: chứng minh một cam kết nền giấu một chuỗi nhị phân
  256-bit (`docs/PROOF_NHI_PHAN_VA_KHOANG.md`, `src/lattice_zk/binary_proof.py`,
  45 134 byte, gửi ngoài băng), và payload range proof rằng một cam kết payload
  của 3.2 giấu `encode(p)` cho một `p` có độ dài công khai `L ≤ 128` byte
  (`src/lattice_zk/payload_range_proof.py`, 46 670 byte cho `L ≤ 32`). Cái sau
  nay **đính kèm được vào envelope in-band** (3.7, phiên bản 2) khi profile ghim
  `L`; nó vẫn lộ `L` (giấu độ dài thật bằng đệm tới lớp độ dài) và tốn 46–74 KB
  carrier. Không cung cấp range proof độ-dài-ẩn hay 24-bit đầy đủ (toàn bộ 256
  hệ số).
- Chế độ offline theo epoch (3.7) chỉ chống phát lại theo từng verifier và
  trong cửa sổ `max_age_epochs`; issuer phải phát beacon đều đặn và holder cần
  beacon hiện hành trước khi nhúng.

## 8. Tài liệu tham khảo

- C. Baum, I. Damgård, V. Lyubashevsky, S. Oechsner, C. Peikert. More
  efficient commitments from structured lattice assumptions. SCN 2018.
- V. Lyubashevsky, G. Seiler. Short, invertible elements in partially
  splitting cyclotomic rings. EUROCRYPT 2018.
- V. Lyubashevsky. Fiat–Shamir with aborts. ASIACRYPT 2009; Lattice
  signatures without trapdoors. EUROCRYPT 2012.
- L. Ducas et al. CRYSTALS-Dilithium specification, round 3 (2021).
- M. Barbosa et al. Fixing and mechanizing the security proof of Fiat–Shamir
  with aborts and Dilithium. CRYPTO 2023.
- J. Devevey, P. Fallahpour, A. Passelègue, D. Stehlé. A detailed analysis of
  Fiat–Shamir with aborts. CRYPTO 2023.
- J. Don, S. Fehr, C. Majenz, C. Schaffner. Security of the Fiat–Shamir
  transformation in the quantum random-oracle model. CRYPTO 2019.
- T. Attema, V. Lyubashevsky, G. Seiler. Practical product proofs for lattice
  commitments. CRYPTO 2020.
