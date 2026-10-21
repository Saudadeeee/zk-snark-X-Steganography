# Lattice ZKP cho VideoLevel: hướng đi, kế hoạch, trạng thái

Cập nhật: 2026-10-12. Nhánh `feature/lattice-pq-stack`.

## 1. Quyết định

Backend lattice ZK của hệ thống là **cam kết BDLOP + chứng minh tri thức về
opening theo Fiat-Shamir-with-aborts**, tự cài đặt từ giao thức đã công bố
(Baum, Damgård, Lyubashevsky, Oechsner, Peikert, SCN 2018, ePrint 2016/997),
mã nằm ở `src/lattice_zk/`.

Lý do chọn (chi tiết từng ứng viên: `docs/LATTICE_BACKEND_SURVEY.md`):

| Ứng viên đã thử | Vì sao không dùng được |
|---|---|
| LaZer | Cần Linux + AVX-512; máy i7-12700H không có |
| LNP22 (thư viện Go) | Verifier chấp nhận witness ngoài biên |
| ISW21 | Designated-verifier; giả thiết knowledge bị tấn công lượng tử; proof 21 KB |
| LaBRADOR, RoKoko | Không có zero-knowledge |
| Ringo-SNARK | Proof ~1.65 MB |
| ePrint 2025/2099 | Chưa có mã hoàn chỉnh |
| SIS prototype trong `lattice_pq.py` | Statement do prover tự chọn; JSON 131 KB |

BDLOP opening proof là giao thức Σ ba bước, đủ nhỏ để tự cài và tự kiểm, chạy
thuần Python trên Windows, proof cố định 7.5 KB, có định lý trong bài gốc. Nó
cũng là nền của các chứng minh chính xác hơn (ALS20, ENS20, LNP22), nên mở
đường cho bước mở rộng.

## 2. Giao thức

Vành `R_q = Z_q[X]/(X^N+1)`, `q ≡ 5 (mod 8)` nguyên tố (X^N+1 tách đúng 2 nhân
tử, mọi hiệu challenge đều khả nghịch — Lyubashevsky-Seiler 2018, Cor. 1.2).

```text
Khóa công khai (sinh từ setup seed):  B1 = [I_n | B1'],  b2 = [0 | 1 | b2']
Commit(m; r):   t1 = B1·r,   t2 = <b2, r> + m        r tam phân trong R^k
Prove:          y ← đều trong [-γ+1, γ]^k,  w = B1·y
                seed = SHAKE256(domain ‖ parameter_id ‖ len ‖ statement ‖ (t1,t2) ‖ w)
                c = SampleInBall(seed)  (κ hệ số ±1),  z = y + c·r
                hủy và thử lại nếu ‖z‖∞ > γ − κ − 1
Proof:          (seed, z)
Verify:         ‖z‖∞ trong biên;  w' = B1·z − c·t1;  seed == H(..., w')
```

Khác bài gốc ở một điểm: mặt nạ Gauss được thay bằng mặt nạ đều kiểu ML-DSA
(số học nguyên chính xác, không cần sampler Gauss). Biên chuẩn của nghiệm
M-SIS vì thế được tính lại theo chuẩn vô cùng: `8·κ·(γ−κ−1)`.

`statement` là mã hóa cố định độ rộng của các giá trị verifier tự có hoặc tự
suy ra từ video: relation_id, parameter_id, registry root/epoch, session
challenge, codec policy, carrier profile, số carrier, positions_hash,
video_commitment (H.264 đã chuẩn hóa carrier). Payload không bao giờ xuất hiện
trong video; chỉ có cam kết và proof.

Envelope in-band, kích thước cố định theo bộ tham số. Có hai chế độ:

```text
in-band     "ZKLB" | version | parameter_id[32] | session_challenge[32] | commitment | proof
registered  "ZKLR" | version | parameter_id[32] | session_challenge[32] | proof
```

- **in-band**: mỗi video một cam kết mới cho payload riêng. Chứng minh "người
  tạo video biết payload ẩn này"; không xác thực danh tính.
- **registered**: cam kết là *credential* của người giữ, được issuer ký vào
  registry (hash của nó nằm trong relation descriptor). Video chỉ mang proof.
  Chỉ người biết opening mới tạo được proof, nên proof xác thực người giữ
  credential cho đúng video và phiên này mà không lộ nội dung credential.

Ngoài ra có `equality_proof.py`: chứng minh hai cam kết (ví dụ cam kết trong
video và credential trong registry) giấu cùng một message. Đây là chứng minh
quan hệ tuyến tính của BDLOP, kích thước bằng hai opening proof.

## 3. Tham số `bdlop-open-128-v1`

| | |
|---|---|
| N, q | 256, 2^30 − 35 |
| n (M-SIS), λ (M-LWE), k | 6, 6, 13 |
| κ, γ | 60, 2^17 |
| Không gian challenge | 2^257 |
| Cam kết / proof | 6720 B / 7520 B |
| Envelope in-band / registered | 14 309 B / 7589 B |
| Equality proof | 15 008 B |
| Xác suất chấp nhận mỗi lần thử | 0.215 |
| M-SIS binding (ℓ∞, biên 2^25.9) | 140 bit cổ điển / 127 bit lượng tử (core-SVP) |
| M-LWE hiding | 135 / 123 bit (dual hybrid, lattice-estimator; primal 138 / 125) |
| Payload tối đa | 766 byte |
| Prove / verify (Python, i7-12700H) | ~0.11 s / ~0.02 s |

Ước lượng: `research/bdlop_params/estimate.py`, mô hình
`pq-crystals/security-estimates@75c2694` (bộ script của Dilithium/Kyber).
Kết quả lưu ở `research/bdlop_params/bdlop_open_128.estimate.json`.

## 4. Điều được và không được tuyên bố

Được:

- Người tạo video biết opening của cam kết nằm trong video, và proof gắn với
  đúng video (đã chuẩn hóa carrier), phiên, registry và chính sách này.
- Payload được giấu (hiding dưới M-LWE); cam kết ràng buộc (binding dưới M-SIS
  với relaxed opening). Có thể công bố payload sau cho bên được phép bằng
  proof zero-knowledge (`create_disclosure` / `verify_disclosure_proof`),
  không giao randomness `r`.
- Knowledge soundness và zero-knowledge trong mô hình random oracle cổ điển;
  "plausibly post-quantum", tham số chọn theo tấn công lattice tốt nhất đã biết.

Không được:

- Không nói "QROM-secure" hay "provably quantum-secure".
- Soundness là *relaxed*: extractor thu được `(r̄, f)` với `B1·r̄ = f·t1`,
  không phải opening tam phân chính xác.
- Proof không nói payload đúng sự thật, không chứng minh nguồn gốc camera,
  không chứng minh bộ mã hóa H.264 chạy đúng.
- Ở chế độ in-band, proof mở một cam kết *mới* nên không xác thực danh tính:
  ai có session challenge cũng tạo được. Cần danh tính thì dùng chế độ
  registered.
- Session challenge là công khai; bên thứ ba cầm challenge có thể dùng nó
  trước. Phát challenge qua kênh đã xác thực nếu điều đó quan trọng.
- Mã chưa được audit, không constant-time.

## 5. Kế hoạch và trạng thái

Mỗi bước chỉ sang bước sau khi cổng kiểm thử của nó qua.

| # | Bước | Cổng kiểm thử | Trạng thái |
|---|---|---|---|
| 1 | Vành R_q, sampler SHAKE | `test_latticezk_ring.py` (13) | Xong |
| 2 | Cam kết BDLOP, opening proof, codec | `test_latticezk_bdlop.py` (28) | Xong |
| 3 | Chọn tham số + ước lượng bảo mật | script ước lượng, JSON kết quả | Xong |
| 4 | Statement gắn video + envelope cố định (2 chế độ) | `test_latticezk_video_proof.py` (19) | Xong |
| 5 | Pipeline video: registry pin, session một lần, embed/extract blind | `test_latticezk_video_pipeline.py` (12, kênh giả) | Xong |
| 6 | Equality proof (quan hệ tuyến tính) | `test_latticezk_equality.py` (9) | Xong |
| 7 | Review bảo mật độc lập + sửa | không còn lỗi CRITICAL/HIGH; các điểm MEDIUM/LOW đã sửa | Xong |
| 8 | E2E trên H.264 thật | `benchmark/latticezk_video_e2e.py`: verify từ video, replay bị từ chối, tamper bị từ chối | Xong, 1 clip (mục 7) |
| 9 | Benchmark mật mã | `benchmark/latticezk_crypto_bench.py` | Xong (mục 7) |
| 10 | Linkage proof: hai video, hoặc video và credential, giấu cùng payload | `test_latticezk_linkage.py` (5); có trong E2E in-band | Xong |
| 11 | CLI tách vai issuer / holder / verifier | `test_latticezk_cli.py` (3) | Xong |
| 12 | Chất lượng theo frame (`benchmark/latticezk_quality.py`) | số đo ở mục 7 | Xong |
| 13 | Benchmark nhiều clip/QP, steganalysis | bảng số tái lập được | Mới 2 clip; steganalysis chưa làm |
| 14 | Product proof ALS20 (payload nhị phân / range) | test riêng | Chưa làm; xem ghi chú dưới |
| 15 | Test vector KAT cố định byte | `test_latticezk_kat.py` (5), `research/bdlop_params/kat_v1.json` | Xong |
| 16 | Đặc tả giao thức + lập luận bảo mật (tiếng Anh, cho bài báo) | `docs/LATTICE_ZK_BDLOP_SPEC.md` | Xong |
| 17 | Steganalysis nhắm đúng miền carrier (PoV trên LSB độ lớn) | `benchmark/latticezk_steganalysis.py` | Xong cho bộ dò cổ điển; chưa có bộ dò học máy |
| 18 | Đưa test backend vào `run_all.py` | Phase 34–41 | Xong |

Ghi chú về tốc độ: embed/verify 12–55 phút là do bộ phân tích CAVLC thuần
Python. Đường native (x264 fork) nhúng *trong lúc mã hóa*, nên giá trị số hóa
chuẩn của video thay đổi theo chính các bit proof (dự đoán intra lan truyền);
statement không thể gắn với video mà không có quan hệ mức codec. Vì vậy backend
giữ đường vá bitstream sau mã hóa. Tăng tốc là việc tối ưu bộ phân tích, không
phải đổi transport.

Ghi chú bước 14: vành hiện tại chỉ tách X^N+1 thành 2 nhân tử (điều kiện để
hiệu challenge khả nghịch). Product proof trên vành này chứng minh tích của
*phần tử vành*, không phải tích theo từng hệ số, nên không cho ra "mỗi bit
payload là 0/1". Muốn chứng minh nhị phân theo hệ số phải chuyển sang biến thể
fully-splitting của ALS20/ENS20 (NTT slot + tự đẳng cấu Galois, lặp nhiều
lần), tức là một bộ tham số và một giao thức khác. Đó là hướng mở rộng, không
phải việc thêm vài hàm.

API công khai của backend là `src.lattice_zk` (`embed_video_proof`,
`verify_video_proof`). Cờ `proof_backend="lattice_zkp"` cũ trong `embed()` vẫn
đóng: nó chỉ prototype SIS cũ và đường sidecar, không phải backend này.

Điểm review đã sửa: prover kiểm tra witness trước khi chứng minh; mặt nạ được
dẫn xuất từ entropy + statement + cam kết + witness (không tái dùng mặt nạ);
khóa cache chỉ đọc; `verify_video_proof` trả về từ chối thay vì ném lỗi khi
transport hỏng; `pins_from_registry` bắt buộc `minimum_epoch` và từ chối bộ
tham số toy; test biên chấp nhận và test phân phối đều của `z` được siết lại.

## 6. Hướng cho đồ án / bài báo

Đóng góp có thể bảo vệ:

1. Proof hậu lượng tử **nằm trong chính bitstream H.264 CAVLC**, không sidecar,
   không SEI; verifier chỉ cần video và cấu hình đã pin.
2. Cam kết video không vòng lặp: chuẩn hóa carrier để proof gắn với video mà
   không phụ thuộc chính các bit của nó.
3. Đo đạc ngân sách dung lượng/chất lượng cho một proof lattice cỡ 14 KB, so
   với Groth16 129 byte.

Công trình gần nhất cần trích: ZK-WAGON (2025, zk-SNARK giấu trong ảnh bằng
LSB), Eva (S&P 2025, proof cho video H.264, ngoài băng), VerITAS, PhotoProof,
ZK-IMG, Adelsbach-Sadeghi (IH 2001). Chưa tìm thấy công trình nào ghép lattice
ZK với nhúng in-band miền codec; đây là kết quả của một lượt tìm kiếm ngắn,
cần rà soát lại trước khi viết "first".

Nơi nộp thực tế: JISA, Multimedia Tools and Applications, IEEE Access, Signal
Processing: Image Communication, IH&MMSec. TIFS/TCSVT đòi phần mật mã và
steganalysis chặt hơn nhiều.

Reviewer sẽ hỏi:

- "Sao không dùng ML-DSA-44 (2420 byte)?" — Trả lời: chữ ký không giấu payload
  và không chứng minh được gì về nó; cam kết thì mở rộng được sang quan hệ
  tuyến tính và product proof. Bước 7 là thứ biến câu trả lời này thành kết
  quả đo được, nên làm trước khi nộp.
- Steganalysis với payload 14 KB — cần chạy bộ dò (bước 8).
- Bảng tham số kèm commit của estimator, phát biểu ROM/QROM rõ ràng, test
  vector và negative test, mã công khai.

Trích thêm cho phần mật mã: Lyubashevsky 2009/2012 (Fiat-Shamir with aborts),
Barbosa et al. 2023 và Devevey et al. 2023 (lỗ hổng chứng minh FS-with-aborts
và cách sửa), Don et al. 2019 (FS trong QROM), ALS20/ENS20 (cùng họ cam kết).

## 7. Kết quả đo

### Smoke E2E trên H.264 thật (tham số toy, 2026-10-12)

`coastguard_cif_q22_g1.h264` (300 frame), envelope 733 byte trong 6160 carrier
của 1 segment. Verify chỉ từ video: đạt. Replay cùng session: bị từ chối. Lật
một bit giữa file: bị từ chối. Payload không xuất hiện trong file đầu ra.
Embed 338 s, verify 145 s (gần như toàn bộ là phân tích CAVLC bằng Python,
không phải mật mã). Báo cáo:
`benchmark/results/latticezk_video_e2e_toy_20261012.json`.

Lượt này xác nhận đường truyền thật và việc hai phía suy ra cùng statement;
tham số toy không có giá trị bảo mật.

### E2E tham số production (`bdlop-open-128-v1`, 2026-10-12)

Cover: `coastguard_cif_q22_g1_3000f.h264` (CIF, 3000 frame, all-intra, QP 22).
Segment 100 frame, chunk 1250 byte, contract `stable-carriers-video-only-v1`.

| | registered | in-band |
|---|---|---|
| Envelope trong video | 7 589 B | 14 309 B |
| Carrier dùng | 62 784 | 118 024 |
| Segment mang payload | 7 / 30 | 12 / 30 |
| Verify chỉ từ video | đạt | đạt |
| Replay cùng session | bị từ chối | bị từ chối |
| Lật 1 bit giữa file | bị từ chối | bị từ chối |
| Payload có trong file ra | không | không |
| PSNR toàn video so với cover | 53.37 dB | 50.94 dB |
| SSIM toàn video | 0.999957 | 0.999918 |
| Embed (chọn carrier + nhúng) | 2 164 s | 3 216 s |
| Verify (trích blind + kiểm proof) | 740 s | 1 245 s |

Báo cáo: `benchmark/results/latticezk_video_e2e_{registered,inband}_coastguard3000f_20261012.json`.

Ghi chú khi đọc số:

- PSNR/SSIM ở bảng trên tính trên cả 3000 frame. Đo theo frame (luma, so với
  cover đã nén, `benchmark/latticezk_quality.py`):

  | | registered | in-band |
  |---|---|---|
  | Frame bị sửa | 694 / 3000 | 1200 / 3000 |
  | PSNR luma, chỉ frame bị sửa | 45.26 dB | 45.20 dB |
  | PSNR luma, frame tệ nhất | 35.66 dB | 34.75 dB |
  | PSNR luma, mọi frame | 51.61 dB | 49.17 dB |
- Thời gian embed/verify là của bộ phân tích CAVLC thuần Python (hai lượt chạy
  song song trên cùng máy), không phải của phần mật mã.
- Mới có một clip. Dung lượng carrier phụ thuộc nội dung: profile stable trên
  Foreman CIF 300 frame chỉ có khoảng 2 900 carrier, không đủ cho envelope này.
- Chưa có steganalysis.

### Clip thứ hai (registered, `deadline_cif_q22_g1_1000f.h264`)

Envelope 7 589 B trong 62 784 carrier, 7 / 10 segment. Verify chỉ từ video:
đạt; replay và lật bit: bị từ chối. 684 / 1000 frame bị sửa; PSNR luma các
frame bị sửa 44.99 dB, frame tệ nhất 34.19 dB, mọi frame 46.64 dB; SSIM toàn
video 0.999835. Embed 1 793 s, verify 1 261 s. Báo cáo:
`benchmark/results/latticezk_video_e2e_registered_deadline1000f_20261012.json`.

### Steganalysis (300 frame đầu của Coastguard, 2026-10-19)

Carrier của profile stable là LSB độ lớn của một hệ số AC `|level| ≥ 4` trên
mỗi block luma (không phải dấu T1). 300 frame đầu chứa 3 segment mang payload,
khoảng 27 000 bit carrier. So với đúng cover (mô hình tấn công mạnh nhất:
kẻ tấn công có bản gốc để đối chiếu thống kê):

| Bộ dò | registered | in-band | Ý nghĩa |
|---|---|---|---|
| Westfeld PoV trên độ lớn, cover | χ² 61 745, P(embed) 0.0 | như trái | mốc |
| Westfeld PoV trên độ lớn, stego | χ² 61 130, P(embed) 0.0 | χ² 61 204, P(embed) 0.0 | không phát hiện |
| Histogram độ lớn, 2 mẫu so cover | p = 1.0 | p = 1.0 | không phát hiện |
| Dấu T1 (đối chứng) | trùng khít | trùng khít | miền này không bị sửa |
| SPA trên luma | 0.39370 → 0.39374 | 0.39370 → 0.39372 | thay đổi không đáng kể |

Báo cáo: `benchmark/results/latticezk_steganalysis_{reg128,inband128}_coastguard300f_20261019.json`.

Giới hạn của kết quả này:

- Chỉ là bộ dò thống kê cổ điển. Chưa thử steganalysis học máy (ví dụ đặc
  trưng rich-model + ensemble, hoặc CNN) — reviewer ở TIFS/IH&MMSec sẽ đòi.
- RS trả về delta 0 cho cả cover lẫn stego trên nội dung này, nên không có
  giá trị phân biệt; không nên dùng nó làm bằng chứng.
- χ² PoV của stego giảm nhẹ so với cover (khoảng 1%), đúng hướng mà nhúng LSB
  gây ra; ở tỉ lệ nhúng cao hơn tín hiệu này có thể đủ để phát hiện.

### Benchmark mật mã

`benchmark/results/latticezk_crypto_bench_20261012.json`, 50 lượt, máy rảnh,
i7-12700H, Python thuần một luồng:

| Thao tác | Trung vị | p95 |
|---|---|---|
| Commit | 21 ms | 23 ms |
| Prove (opening) | 120 ms | 302 ms |
| Verify (opening) | 22 ms | 23 ms |
| Prove (equality) | 0.97 s | 3.65 s |
| Verify (equality) | 46 ms | 50 ms |

Số lần thử trung bình: 4.68 (lý thuyết 4.65) cho opening, 26 (lý thuyết 21.6)
cho equality.

So kích thước: Groth16 129 B; ML-DSA-44 2 420 B; ML-DSA-65 3 309 B; opening
proof 7 520 B; cam kết 6 720 B.

## 8. Cách chạy

Khóa đồng bộ carrier dùng chung giữa holder và verifier, đặt qua biến môi
trường `ZKSTEGO_LATTICEZK_SYNC_KEY_HEX` (hex, tối thiểu 16 byte).

```bash
# issuer
python -m src.lattice_zk.cli issuer-keygen --public issuer.pub --private issuer.key
# holder (chế độ registered): tạo credential, gửi phần public cho issuer
python -m src.lattice_zk.cli credential-new --payload-file device.bin \
    --public holder.pub.json --private holder.key.json
# issuer ký registry (bỏ --credential để dùng chế độ in-band)
python -m src.lattice_zk.cli registry-sign --issuer-private issuer.key --epoch 1 \
    --credential holder.pub.json --out registry.json
# verifier phát challenge một lần
python -m src.lattice_zk.cli session-issue --database sessions.sqlite3 \
    --registry registry.json --issuer-public issuer.pub --minimum-epoch 1 \
    --credential holder.pub.json
# holder nhúng proof vào video
python -m src.lattice_zk.cli embed --video cover.h264 --output stego.h264 \
    --session <challenge-hex> --credential-private holder.key.json \
    --registry registry.json --issuer-public issuer.pub --minimum-epoch 1
# verifier kiểm tra chỉ từ video
python -m src.lattice_zk.cli verify --video stego.h264 --database sessions.sqlite3 \
    --registry registry.json --issuer-public issuer.pub --minimum-epoch 1 \
    --credential holder.pub.json
```

Chế độ in-band: bỏ mọi `--credential*`, thêm `--payload-file` và
`--opening-out` ở lệnh `embed`.

Gắn danh tính holder: thêm `--holder-id <id>` vào `registry-sign` và vào mọi
lệnh resolve pins (`session-issue`, `embed`, `verify`). Công bố payload cho
một bên nhận:

```bash
# verifier giữ envelope đã kiểm (chỉ in-band)
python -m src.lattice_zk.cli verify ... --envelope-out envelope.bin
# holder tạo disclosure với nonce do bên nhận chọn (randomness không rời holder)
python -m src.lattice_zk.cli disclose --opening opening.json \
    --statement-id <statement-id-hex> --nonce <nonce-hex> --out disclosure.bin
# bên nhận kiểm (--credential holder.pub.json cho credential đã đăng ký)
python -m src.lattice_zk.cli disclosure-verify --envelope envelope.bin \
    --statement-id <statement-id-hex> --nonce <nonce-hex> --disclosure disclosure.bin
```

Chạy lại toàn bộ test của backend:

```bash
python -m pytest -q src/runtest/test_latticezk_ring.py src/runtest/test_latticezk_bdlop.py \
    src/runtest/test_latticezk_video_proof.py src/runtest/test_latticezk_video_pipeline.py \
    src/runtest/test_latticezk_equality.py src/runtest/test_latticezk_linkage.py \
    src/runtest/test_latticezk_cli.py
```

## 9. Đợt Q2 (bắt đầu 2026-10-19)

Mục tiêu: đủ bằng chứng cho một bài Q2 (JISA / MTAP / IEEE Access /
Signal Processing: Image Communication).

| # | Việc | Công cụ | Trạng thái |
|---|---|---|---|
| Q2.1 | Quét dung lượng carrier trên các chuỗi CIF chuẩn | `benchmark/latticezk_capacity_scan.py` | Đang chạy |
| Q2.2 | E2E trên nhiều clip/QP/độ phân giải (CIF + 4CIF Xiph), chunk size theo dung lượng đo được | `benchmark/latticezk_q2_sweep.py`, `benchmark/latticezk_q2_cases.json` | Đang chuẩn bị |
| Q2.3 | Steganalysis học máy (đặc trưng miền hệ số + SRM rút gọn; logistic, FLD ensemble; leave-one-clip-out) | `benchmark/latticezk_ml_steganalysis.py` | Code + test xong (5/5) |
| Q2.4 | So sánh baseline: Groth16, ML-DSA-44/65 đo trên máy này; ISW21 lấy số đã ghi | `benchmark/latticezk_baselines.py` | Xong |
| Q2.5 | Tổng hợp bảng/hình cho bài báo | `benchmark/latticezk_q2_report.py` → `docs/paper/tables`, `docs/paper/figures` | Xong (chạy lại khi có số mới) |
| Q2.6 | Bản thảo bài báo | `docs/paper/main.tex`, `references.bib` | Khung + các phần không phụ thuộc số đo |

Phát hiện khi quét dung lượng: giới hạn trước đây không nằm ở clip mà ở chunk
1 250 byte. Dung lượng thật của segment 100 frame đầu (CIF, QP 22) là 10.5 kbit
(Akiyo) đến 50.8 kbit (Container), nên nhiều clip 300 frame chứa được envelope
registered (61 kbit) nếu tăng chunk size.

Lưu ý: `coastguard_cif_q22_g1_3000f.h264` được tạo bằng cách lặp chuỗi gốc 300
frame; phải ghi rõ trong bài nếu dùng số đo trên nó.

### Lỗi sửa trong đợt Q2 (2026-10-19)

- **Mất dung lượng ở độ phân giải khác CIF.** `CAVLCSafetyFilter.get_safe_positions`
  ánh xạ macroblock sang IDR frame bằng số macroblock của CIF (396). Ở 4CIF
  (1 584 MB/frame) chỉ 396 MB đầu mỗi frame được xác minh, phần còn lại bị coi
  là không patchable (fail-closed nên không sai dữ liệu, nhưng mất khoảng 90%
  dung lượng). Sửa trong `src/core/analysis_cache.py`: truyền số MB/frame lấy
  từ SPS. 10 frame City 4CIF: 1 010 → 11 067 carrier; CIF không đổi. Test:
  `test_non_cif_carrier_capacity.py`.
- **Giải mã luma bị scale về CIF** trong `_common.decode_luma_frames`; các script
  steganalysis lattice-ZK giờ dùng `decode_luma_native` (mặt phẳng Y gốc).

### Steganalysis học máy và quy tắc sửa hệ số (2026-10-19)

5 clip CIF 300 frame thật (Container, Coastguard, City, Hall, Deadline), 1 300
cặp frame bị sửa, `benchmark/results/q2/ml_eval.json`:

| Giao thức | Đặc trưng / bộ dò tốt nhất | P_E | AUC |
|---|---|---|---|
| Leave-one-clip-out | miền hệ số, FLD ensemble | 0.398 | 0.627 |
| Paired, cùng clip | kết hợp, FLD ensemble | 0.368 | 0.683 |
| Leave-one-clip-out | chỉ miền pixel | 0.454 | 0.538 |

Kết luận: phát hiện được ở mức vừa phải theo từng frame bằng đặc trưng nhắm
vào miền hệ số; miền pixel gần như không. Gộp nhiều frame của cùng video sẽ
tăng khả năng phát hiện — phải ghi rõ trong bài.

Mô phỏng hai quy tắc sửa trên cùng vị trí và mật độ
(`benchmark/results/q2/embedding_rule_sim.json`): LSB replacement P_E 0.319,
LSB matching P_E 0.267. LSB matching **dễ bị phát hiện hơn**, nên giữ quy tắc
hiện tại. Mô phỏng bỏ qua bộ lọc patchability nên phát hiện dễ hơn thực tế
(0.32 so với 0.40); chỉ dùng để so sánh tương đối.

### So sánh carrier: lật dấu T1 và magnitude-LSB (mô phỏng, 2026-10-19)

Cùng 5 clip CIF, cùng số bit như E2E thật, bộ dò FLD ensemble trên đặc trưng
độ lớn + dấu theo vị trí, leave-one-clip-out
(`benchmark/results/q2/embedding_t1_vs_magnitude_sim.json`,
`embedding_density_sim.json`):

| Quy tắc | P_E | AUC |
|---|---|---|
| Lật dấu T1 (T1 tần số cao nhất mỗi block) | 0.475 | 0.513 |
| Magnitude-LSB replacement | 0.316 | 0.741 |
| Magnitude-LSB matching | 0.260 | 0.803 |
| Magnitude-LSB, 50% / 25% / 10% mật độ | 0.395 / 0.443 / 0.466 | 0.63 / 0.57 / 0.53 |

Mô phỏng chỉ đo thống kê, không đo PSNR, lỗi giải mã hay tốc độ; E2E thật
của carrier T1 (contract `t1-sign-video-only-v1`) đang chạy.

### Cải tiến ngày 2026-10-20

- **Tham số mật độ nhúng** (`density` trong sweep): chunk = mật độ × dung lượng
  đo được, envelope tự trải ra nhiều frame hơn. Thí nghiệm 4CIF ở 100 / 50 /
  25 % xếp hàng; tổng hợp bằng `benchmark/latticezk_density_report.py`.
- **Chế độ thứ tự carrier công khai** (`public_sync_key`, CLI
  `--public-carrier-order`): không cần khóa stego bí mật, ai có registry cũng
  verify được, đổi lại mất tính khó phát hiện. Soundness và ZK không phụ thuộc
  khóa này.
- **So sánh carrier thật** (`benchmark/latticezk_carrier_compare.py`): lật dấu T1
  dồn vào 100 frame dễ bị phát hiện hơn rõ (P_E pixel 0.29 so với 0.44); đang
  chạy thêm biến thể T1 cùng mật độ.
- Sửa: chunk tự chọn vượt trần 65 535 B của định dạng chunk.
- Bài báo: viết phần Evaluation và Discussion bằng số đo thật.
- Test backend: 115 pass.

### Kết quả so sánh carrier trên video thật (2026-10-20)

4 clip CIF QP22 (City, Coastguard, Container, Hall), registered, 12 lượt E2E đều
verify đạt. `benchmark/results/q2/carrier_compare.md`.

| | Magnitude-LSB | T1 cùng số frame | T1 dồn 100 frame |
|---|---|---|---|
| Dung lượng (kbit / 100 frame) | 22–48 | 468–550 | 468–550 |
| PSNR luma frame bị sửa | 40.0–45.4 dB | **43.3–48.8 dB** | 41.0–44.1 dB |
| PSNR frame tệ nhất | 32.7–38.8 dB | **38.5–44.6 dB** | 36.8–40.7 dB |
| SSIM toàn video | **0.9991–0.9998** | 0.9975–0.9994 | 0.9978–0.9994 |
| Embed / verify | **580–903 / 182–286 s** | 1 275–2 329 / 788–2 395 s | 857–1 338 / 519–816 s |
| ML LOCO, miền hệ số (P_E) | 0.386 | **0.471** | 0.446 |
| ML LOCO, miền pixel | **0.456** | 0.404 | 0.310 |
| ML LOCO, kết hợp | **0.416** | 0.401 | 0.314 |
| ML cùng clip, kết hợp | **0.339** | 0.317 | 0.193 |
| Test dấu theo vị trí (cổ điển) | p = 1.0 | p ≥ 0.98 | Hall p = 0.001 (bị phát hiện) |

Quyết định: giữ magnitude-LSB làm mặc định (verify nhanh hơn 4–8 lần, kín hơn ở
miền pixel); T1 là tùy chọn (`--carrier t1`) khi cần chất lượng ảnh cao hơn và
chấp nhận chậm. Không dồn T1 vào ít frame.

### Tăng tốc phân tích carrier T1 (2026-10-21)

- `get_safe_positions(signbit_only=True)` bỏ vòng kiểm tra carrier độ lớn (kết
  quả của nó vốn bị bỏ đi với contract dấu); `analysis_cache` có profile
  `signbit-v1`; `blind_sync` dùng nó cho mọi contract `signbit_only`.
- Lật dấu một trailing one thật được chấp nhận không cần mã hóa lại block cho
  từng vị trí: `trailing_ones_sign_flag` là 1 bit thô, `coeff_token`,
  `suffixLength` và các level khác chỉ phụ thuộc số lượng T1. Kiểm tra mã hóa
  lại mỗi block vẫn giữ; khối có `t1_override` vẫn kiểm từng vị trí.
  Tùy chọn `verify_each_sign=True` giữ đường kiểm tra cũ để đối chiếu.
- Kết quả giống hệt (cả thứ tự): 113 534 vị trí / 10 frame CIF, 466 036 / 10
  frame 4CIF; nhanh hơn khoảng 2.3 lần. Test: `test_signbit_fast_analysis.py`.
- Contract T1 đổi sang `t1-sign-video-only-v2` vì thứ tự ứng viên trước khi
  xáo trộn thay đổi; video T1 v1 không trích được bằng v2.

### Sửa các lỗ hổng từ security review (2026-10-21)

Theo mục D2, D3, D4, D6 trong phụ lục đối chiếu spec–code của bài báo
(chi tiết: spec §3.5, §3.7, §4.1, §4.8).

- **D3, disclosure zero-knowledge.** `verify_disclosure(params, envelope,
  opening)` nhận cả randomness `r`, nên bên nhận có thể tự tạo proof mới cho
  cam kết đó. Thay bằng `create_disclosure` / `verify_disclosure_proof`
  (envelope) và `create_commitment_disclosure` /
  `verify_commitment_disclosure` (credential): holder công bố `p` kèm equality
  proof giữa `C` và `Com(encode(p); 0)`, gắn với ngữ cảnh
  `statement_id ‖ nonce` (có domain tag, length-prefixed; nonce 32 byte do bên
  nhận chọn). Định dạng `"ZKLD" ‖ 0x01 ‖ parameter_id ‖ u16 |p| ‖ p ‖ π_eq`
  (39 + |p| + 15 008 byte ở bộ production), không chứa `r`. Hàm cũ đổi tên
  thành `self_check_opening`, chỉ để holder tự kiểm. CLI thêm `disclose`,
  `disclosure-verify` và `verify --envelope-out`; E2E
  (`benchmark/latticezk_video_e2e.py`) dùng disclosure mới.
- **D4, completeness của equality proof.** Cap riêng 4 096 lần thử
  (`equality_proof.MAX_ATTEMPTS`), xác suất thất bại ≈ 2^-280 thay vì 2^-35;
  test kiểm cận < 2^-128 từ tham số. KAT không đổi.
- **D6, pins phải khớp credential.** `verify_video_proof` tính lại relation id
  của `(params, profile, credential, holder_id)` và ném `ValueError` nếu khác
  `pins.relation_id` (cấu hình verifier sai), kể cả khi dùng pins in-band cho
  profile registered và ngược lại.
- **D2, danh tính holder.** `relation_descriptor(..., holder_id=...)` băm
  digest có domain tag của holder id (UTF-8, NFC, 1–256 byte) vào
  `verifier_key_hash` sau credential; tập trường registry không đổi, mặc định
  `None` giữ nguyên descriptor cũ. `pins_from_registry`, `verify_video_proof`
  và CLI (`--holder-id` ở `registry-sign`, `session-issue`, `embed`, `verify`)
  nhận cùng giá trị; sai hoặc thiếu holder id thì không resolve được pins.
