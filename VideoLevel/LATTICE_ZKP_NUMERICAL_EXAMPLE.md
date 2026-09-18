# Ví dụ số và toán học của lattice ZKP cho video

## Phạm vi và cảnh báo

Tài liệu này mô tả thiết kế mục tiêu: prover chỉ gửi một file H.264, proof được
nhúng trực tiếp vào carrier CAVLC, và verifier xác nhận video do holder của
witness đã đăng ký tạo ra, đồng thời không bị người không có witness sửa sau đó.

Ví dụ số dùng q = 97 và ma trận hai chiều để có thể tính tay. Nó không an
toàn, không phải parameter LaZer, và không phải backend đang chạy trong API
công khai. Parameter production phải được sinh từ relation đã review và được
phân tích an ninh.

Proof xác thực holder của witness đã ủy quyền video. Nó không chứng minh cảnh
quay là sự thật vật lý, camera không bị xâm nhập, hay sender không chủ ý dựng
video giả.

## 1. Mục tiêu mật mã

Verifier đã pin một public credential C ở pha setup. Prover giữ witness bí mật
(s, e). Mỗi video tạo một statement X chứa hash canonical video, sequence và
policy codec.

~~~
Chứng minh knowledge của (s, e) sao cho:

    C = A*s + e mod q

và transcript proof được bind vào X.
~~~

- A: ma trận công khai.
- C: public commitment hoặc credential của prover.
- s, e: vector bí mật và ngắn.
- q: modulus.
- X: byte string canonical mô tả chính video này.

Không cần device_id nếu chỉ có một prover: verifier pin trực tiếp C. Với nhiều
prover, verifier có thể lookup C theo fingerprint, hoặc prover chứng minh
membership ẩn danh trong registry mà không lộ danh tính.

## 2. Nền tảng toán học lattice

### 2.1 Số nguyên modulo q

Z_q là tập số nguyên tính modulo q:

~~~
Z_q = {0, 1, ..., q - 1}
~~~

Ví dụ với q = 97:

~~~
-9 mod 97 = 88
151 mod 97 = 54
~~~

Khi đo độ dài, implementation dùng đại diện centered. Ví dụ 88 mod 97 được
xem là -9, không phải một hệ số lớn 88.

### 2.2 Vector ngắn và norm

Với vector v = (v_1, ..., v_d):

~~~
||v||_infinity = max_i |v_i|
||v||_2        = sqrt(sum_i v_i^2)
~~~

Witness phải ngắn:

~~~
||s||_infinity <= B_s
||e||_infinity <= B_e
~~~

Không chỉ cần tìm một nghiệm modulo q; cần tìm nghiệm ngắn. Điều kiện
shortness này liên hệ relation với bài toán lattice hoặc q-ary lattice coset.

### 2.3 Ring và module trong parameter thật

Ví dụ tay dùng vector số nguyên. Hệ LaZer hoặc ML-DSA ở thực tế thường dùng
vector polynomial trong ring:

~~~
R_q = Z_q[X] / (X^n + 1)
~~~

Một polynomial là:

~~~
f(X) = f_0 + f_1*X + ... + f_(n-1)*X^(n-1)
~~~

Mọi hệ số tính modulo q và X^n = -1. Một module vector R_q^k gồm k
polynomial; mỗi polynomial có n hệ số. Phép nhân polynomial được tăng tốc bằng
NTT. Parameter q thường phải phù hợp với NTT cần dùng, ví dụ có điều kiện chia
hết phù hợp giữa q - 1 và một bội của n.

## 3. Cần những tham số nào và lấy từ đâu

Không được tự chọn parameter theo từng video.

| Nhóm | Ví dụ | Nguồn đúng |
|---|---|---|
| Algebra | n, q, module rank, matrix size | Parameter set LaZer sinh từ relation và security target |
| Witness | B_s, B_e, short distribution | Relation specification và security analysis |
| Proof | mask distribution, B_z, rejection rate | LaZer code generator và ZK analysis |
| Challenge | challenge space, số round | Protocol parameter đã review |
| Hash | SHAKE/SHA3, domain label | Protocol specification versioned |
| Video | carrier rule, max edits, canonicalization | Policy hash do verifier pin |
| Credential | A, C, witness s,e | Enrollment và CSPRNG hoặc secure hardware |

### 3.1 Parameter set LaZer

Trước khi có video, cần định nghĩa relation và norm bounds. LaZer dùng
specification/code generator để tạo parameter tối ưu cho proof. Artifact phải
được hash và pin:

~~~
relation_id
parameter_set_hash
constraint_module_hash
verifier_key_hash, nếu protocol cần verifier key
security target
~~~

Video không được tự chọn parameter set hoặc registry root. Verifier chỉ dùng
artifact đã cài hoặc pin qua setup.

### 3.2 Tạo credential của prover

Ở enrollment:

~~~
seed_A <- CSPRNG
A      = Expand(seed_A)
s, e   <- ShortDistribution(B_s, B_e)
C      = A*s + e mod q
~~~

seed_A và C là công khai. s,e là witness private và cần ở secure element, TPM,
TEE hoặc kho khóa bảo vệ. Không dùng trực tiếp ML-DSA private key làm witness;
credential ZK nên tách khỏi signing key control-plane.

### 3.3 Giá trị mới ở mỗi proof

Mỗi video cần mask mới, lấy từ CSPRNG:

~~~
y_s, y_e <- MaskDistribution
~~~

Không được tái sử dụng mask. Video cũng cần sequence, timestamp đáng tin cậy
hoặc chain hash để phát hiện replay của một video cũ nhưng vẫn hợp lệ.

## 4. Canonical video hash

Proof nằm trong video, nhưng proof phải bind video. Hash trực tiếp file cuối
cùng sẽ tạo vòng lặp vì ghi proof làm video thay đổi.

Gọi P là tập carrier dành riêng cho proof. Định nghĩa:

~~~
Can_P(V): thay mọi carrier thuộc P bằng giá trị chuẩn cố định
V_canonical = Can_P(V_stego)
H_video     = SHA3-256(V_canonical)
~~~

Toàn bộ vùng proof phải có format, length và padding xác định. Thay đổi proof
làm parse hoặc verify fail; thay đổi phần video ngoài vùng proof làm H_video
đổi. Tập P phải tái tạo được từ policy và stego bitstream, không phụ thuộc
sidecar ngoài video.

Statement canonical nên là:

~~~
X = CanonicalEncode(
      protocol_version,
      relation_id,
      parameter_set_hash,
      C,
      H_video,
      policy_hash,
      session_id,
      sequence,
      previous_segment_hash
    )
~~~

previous_segment_hash hữu ích cho stream để chống cắt ghép hoặc đảo thứ tự.
Với video độc lập, sequence và replay database ở verifier có thể đủ.

## 5. Luồng sinh proof không tương tác

Đây là cấu trúc Sigma/Fiat-Shamir minh họa. API, compression và proof system
LaZer thực tế có thể khác, nên không được tự triển khai theo công thức này.

### 5.1 Commitment mask

Prover lấy mask mới:

~~~
y_s <- D_mask_s
y_e <- D_mask_e
w   = A*y_s + y_e mod q
~~~

w là commitment công khai trong proof, không trực tiếp tiết lộ s,e.

### 5.2 Challenge Fiat-Shamir

Verifier không gửi challenge. Cả hai phía tính cùng challenge:

~~~
c = SampleChallenge(
      SHAKE256(
        "zkstego/lattice-video-proof/v1" || X || Encode(w)
      )
    )
~~~

Nếu video, policy hoặc parameter set đổi, X đổi, nên c đổi. Challenge thật là
sparse polynomial hoặc vector từ SHAKE/SHA3, không phải số nhỏ do prover chọn.

### 5.3 Response và rejection sampling

~~~
z_s = y_s + c*s
z_e = y_e + c*e
~~~

Prover chỉ xuất proof nếu:

~~~
||z_s||_infinity <= B_zs
||z_e||_infinity <= B_ze
~~~

Nếu fail, bỏ mask và lấy mask mới. Rejection sampling giúp phân bố response
không làm lộ sự dịch chuyển do witness tạo ra. Distribution, bound và xác
suất reject là security parameter, không được chọn bằng trực giác.

### 5.4 Dạng proof envelope

Về logic:

~~~
pi = Encode(
       proof_version,
       parameter_set_id,
       commitment data,
       response data,
       hint/compression data
     )
~~~

Challenge có thể không cần lưu vì verifier tái tạo từ transcript. Format thực
phải do LaZer relation/serializer đã review định nghĩa, không phải JSON tự
thiết kế.

## 6. Luồng verifier

Verifier trích pi từ video, canonicalize video, tính H_video, dựng X, tái tạo
challenge, kiểm tra format và norm, rồi kiểm tra:

~~~
A*z_s + z_e = w + c*C mod q
~~~

Lý do phương trình đúng:

~~~
A*z_s + z_e
= A*(y_s + c*s) + (y_e + c*e)
= (A*y_s + y_e) + c*(A*s + e)
= w + c*C
~~~

Proof system production phải thỏa ba tính chất:

- Completeness: prover trung thực có witness hợp lệ sẽ pass.
- Knowledge soundness: không biết witness thì không tạo proof hợp lệ cho
  statement mới với xác suất đáng kể.
- Zero knowledge: proof không tiết lộ witness ngoài việc witness tồn tại.

## 7. Ví dụ tính tay hoàn chỉnh

### 7.1 Parameter và witness

~~~
q = 97

    [12  7]
A = [     ]
    [ 5 19]

    [ 2]       [1]
s = [  ]   e = [ ]
    [-1]       [0]
~~~

Tạo credential công khai:

~~~
A*s = [12*2 +  7*(-1)] = [ 17]
      [ 5*2 + 19*(-1)]   [ -9]

C = A*s + e = [17] + [1] = [18]
                [-9]   [0]   [-9]

    [18]
C = [88] mod 97
~~~

Verifier pin A,C; prover giữ s,e.

### 7.2 Statement video

~~~
H_video  = 9f31...c8aa
sequence = 42
policy   = h264-baseline-cavlc/direct-carrier-v1

X = Encode(C || H_video || sequence || policy)
~~~

### 7.3 Commitment

~~~
     [ 4]        [-2]
y_s = [-3]  y_e = [ 3]
~~~

~~~
A*y_s = [12*4 +  7*(-3)] = [ 27]
        [ 5*4 + 19*(-3)]   [-37]

w = A*y_s + y_e = [ 27] + [-2] = [ 25]
                      [-37]   [ 3]   [-34]

    [25]
w = [63] mod 97
~~~

### 7.4 Challenge và response

Giả sử hash transcript trả về challenge minh họa c = 3:

~~~
z_s = y_s + c*s = [ 4] + 3*[ 2] = [10]
                    [-3]     [-1]   [-6]

z_e = y_e + c*e = [-2] + 3*[1] = [1]
                    [ 3]     [0]   [3]
~~~

Dạng logic của proof:

~~~json
{
  "version": "zkstego-lattice-demo-v1",
  "statement_hash": "hash(C || H_video || sequence || policy)",
  "commitment_w": [25, 63],
  "response_s": [10, -6],
  "response_e": [1, 3]
}
~~~

Đây không phải binary format LaZer.

### 7.5 Verifier kiểm tra

Vế trái:

~~~
A*z_s = [12*10 +  7*(-6)] = [ 78]
        [ 5*10 + 19*(-6)]   [-64]

A*z_s + z_e = [ 78] + [1] = [ 79]
                [-64]   [3]   [-61]

             = [79]
               [36] mod 97
~~~

Vế phải:

~~~
w + c*C = [25] + 3*[18] = [ 79]
          [63]     [88]   [327]

        = [79]
          [36] mod 97
~~~

Hai vế bằng nhau nên proof pass.

### 7.6 Khi video bị sửa

Sửa phần ngoài vùng proof làm H_video đổi, nên challenge đổi. Nếu challenge
mới là c' = 2 thì verifier đòi:

~~~
w + 2*C = [25, 63] + 2*[18, 88]
          = [61, 45] mod 97
~~~

Response cũ chỉ cho [79, 36], nên proof fail. Attacker cần s,e để tạo response
tương ứng với challenge mới.

## 8. Ví dụ tay khác production thế nào

| Nội dung | Ví dụ | Production mục tiêu |
|---|---|---|
| Modulus | q = 97 | Parameter review chọn q theo security và arithmetic |
| Không gian | Vector 2 chiều | Module vector gồm polynomial trong R_q |
| Challenge | Số 3 | Sparse polynomial/vector từ SHAKE/SHA3 |
| Mask | Số viết tay | Distribution định nghĩa chính thức |
| Zero knowledge | Không có bảo đảm | Rejection sampling và security analysis |
| Proof format | JSON | Binary envelope có compression/versioning |
| Runtime | Tính tay | Native NTT và SIMD/AVX-512 nếu LaZer yêu cầu |

Prototype bị khóa trong source có các hằng nghiên cứu như q = 8,380,417,
matrix 64 x 128 và 128 rounds. Đây không phải parameter đã phê duyệt cho
relation video.

## 9. Mapping vào pipeline video

### Setup một lần

~~~
1. Review relation và bounds.
2. Sinh LaZer parameter artifact, hash mọi artifact.
3. Tạo credential (A, C, s, e).
4. Pin C, relation hash, parameter hash, policy hash ở verifier.
5. Đặt chính sách sequence/replay.
~~~

### Mỗi video hoặc GOP/segment

~~~
1. Native encoder fork quantize/encode CAVLC.
2. Xác định carrier proof tái tạo được.
3. Canonicalize carrier và tính H_video.
4. Dựng X.
5. LaZer prover sinh pi từ X, witness và entropy mới.
6. Nhúng pi trực tiếp trước inverse transform/reconstruction.
7. Gửi một file video.
~~~

### Verifier

~~~
1. Trích proof envelope.
2. Kiểm tra framing/version/length/padding.
3. Dựng lại carrier và H_video.
4. Dùng parameter đã pin, không tin parameter do video chọn.
5. Verify proof và kiểm tra sequence/replay.
~~~

Với realtime, proof theo GOP/segment thường thực tế hơn proof theo frame.
Bind sequence và hash segment trước để tạo chain chống cắt ghép hoặc đảo thứ tự.

## 10. Trạng thái hiện tại của repository

Repository đã có canonical statement, policy hash, relation registry được ký và
hardware gate cho LaZer. Nó chưa có relation LaZer cho C + H_video, witness
credential production, binary proof serializer, direct-CAVLC proof embedding,
hoặc E2E fixture trên host AVX-512F.

Public API cố ý từ chối proof_backend="lattice_zkp", để prototype nghiên cứu
không bị gọi nhầm là proof hậu lượng tử đã review.

Tài liệu liên quan:

- [Kế hoạch PQ video ZKP](PQ_VIDEO_ZKP_PLAN.md)
- [Lattice PQ path hiện tại](LATTICE_PQ.md)
- [LaZer upstream](https://github.com/lazer-crypto/lazer)
