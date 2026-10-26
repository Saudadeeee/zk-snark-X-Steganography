# Tổng quan hệ thống

Mục đích: giải thích bài toán, hệ thống làm gì end-to-end, hai chế độ, ý nghĩa "xác minh mù từ video", phạm vi, và "là gì / không là gì".
cập nhật: 2026-10-22

## 1. Bài toán

Cần gắn một **bằng chứng zero-knowledge hậu lượng tử** vào bên trong một video
H.264 sao cho:

- người xác minh chỉ cần **chính file video stego** (không cần video gốc,
  không cần sidecar, không cần bí mật của người tạo) để kiểm tra bằng chứng;
- việc giấu không làm hỏng cú pháp H.264 (video vẫn giải mã bình thường);
- bằng chứng ràng buộc vào nội dung video đã chuẩn hóa, nên sửa khung hình hay
  thay bằng chứng đều bị từ chối.

Đây là bài toán **tính toàn vẹn / nguồn gốc ẩn của video** dựa trên ZK mạng
(lattice), với mục tiêu an toàn trước máy tính lượng tử.

## 2. Hệ thống làm gì (end-to-end)

Nhúng (embed):

1. Phân tích video gốc tìm các vị trí hệ số CAVLC an toàn để làm **carrier**.
2. Dựng **statement** (phát biểu) từ cấu hình đã pin của người xác minh + các
   giá trị tính lại được từ luồng H.264 (digest video chuẩn hóa, danh sách
   carrier, thách thức phiên...).
3. Tạo cam kết **BDLOP** và **bằng chứng opening** (Fiat–Shamir-with-aborts)
   gói thành một **envelope**.
4. Chia envelope thành các **ZKBC chunk** trên các đoạn (segment) 100 khung,
   rồi vá bitstream ở đúng các carrier để sinh video stego.

Xác minh (verify) — chỉ từ video stego:

1. Trích envelope một cách **mù** (blind) bằng cách suy lại danh sách carrier
   từ chính luồng stego.
2. Kiểm tra khung chunk đúng là **chunking chuẩn** của envelope (fix D1).
3. Dựng lại statement từ cấu hình pin + các giá trị tính lại từ video.
4. Kiểm tra bằng chứng opening của BDLOP đối với statement đó.
5. **Tiêu thụ** thách thức phiên một lần (chống phát lại).

## 3. Hai chế độ

- **Registered (đăng ký)**: chứng minh biết opening của một **cam kết credential
  đã được ghim trong registry** do issuer ký (ML-DSA-65). Video chỉ mang
  **bằng chứng** (envelope registered, 8741 B với `bdlop-open-128-v3`). Chỉ người giữ credential mới tạo
  được bằng chứng. Có thể gắn thêm **holder id** để chữ ký issuer phủ luôn
  "cam kết này thuộc về người `h`".
- **In-band (trong luồng)**: cam kết một **payload ẩn** (tối đa **766 byte**)
  và chứng minh biết opening của nó. Video mang **cả cam kết lẫn bằng chứng**
  (envelope in-band, 16421 B; cộng 46 673 B nếu đính kèm payload range proof
  `--payload-range-bytes`). Payload vẫn ẩn, và có thể **tiết lộ
  (disclosure)** về sau cho một bên nhất định mà không lộ randomness.

Hai chế độ dùng chung lõi BDLOP; khác nhau ở chỗ cam kết được ghim bên ngoài
(registered) hay mang trong envelope (in-band). Cờ chọn là
`CarrierProfile.registered` (xem `02_kien_truc.md`).

## 4. "Xác minh mù từ video" nghĩa là gì

Người xác minh **không** cần:

- video gốc (cover);
- sidecar hay metadata ngoài luồng;
- bí mật của người tạo (randomness của cam kết, khóa credential riêng).

Người xác minh **cần**:

- cấu hình đã pin: registry (gốc + epoch), parameter set, codec policy, carrier
  profile; với registered thì cần credential công khai (và holder id nếu có);
- **khóa đồng bộ carrier** (sync key): hoặc bí mật chia sẻ (giữ tính không phát
  hiện được), hoặc suy từ cấu hình công khai `--public-carrier-order` (ai có
  registry cũng xác minh được, đánh đổi tính ẩn);
- một **kho thách thức phiên** (session store) để tiêu thụ thách thức một lần.

Verifier tự **tính lại** mọi trường của statement từ luồng H.264 nhận được rồi
so khớp; nó không đọc giá trị statement nào từ phần do người tạo kiểm soát.

## 5. Phạm vi

- Codec: **H.264 Baseline, CAVLC** (không CABAC).
- Cấu trúc khung: **all-intra** (mặc định, mọi slice là IDR) và **GOP > 1**
  (carrier chỉ trong IDR slice; P-slice và non-IDR I-slice được ràng buộc dạng
  raw RBSP) — xem `docs/GOP_HD_SUPPORT.md`.
- Carrier: **magnitude-LSB ổn định** (mặc định, hợp đồng
  `stable-carriers-video-only-v1`), **T1 sign** (`t1-sign-video-only-v2`),
  **syndrome-trellis-coded / STC** (`adaptive-stc-magnitude-video-only-v1`,
  opt-in).
- Độ phân giải: CIF/4CIF đã đo; 720p/1080p mới chạy trên encode tổng hợp
  (sweep HD còn hoãn).

## 6. Là gì / không là gì (trung thực)

**Là:**

- một **nguyên mẫu nghiên cứu** tự hiện thực từ bài báo đã công bố (BDLOP,
  SCN 2018), chạy end-to-end và xác minh được từ video stego;
- hậu lượng tử ở mức "plausibly post-quantum" (xem `03_ly_thuyet.md` §mô hình).

**Không là:**

- **không** được kiểm toán độc lập; **không** constant-time (số nguyên lớn
  Python + vòng lặp rejection phụ thuộc dữ liệu → có kênh thời gian);
- **không** bền vững trước mã hóa lại / transcoding: carrier nằm ở mức hệ số
  CAVLC, nên re-encode gần như chắc chắn phá bằng chứng;
- **không** chứng minh payload là "đúng sự thật", không chứng minh có camera
  thật quay, không chứng minh encoder H.264 chạy đúng;
- ở chế độ in-band, **không** xác thực danh tính người tạo (chỉ ràng buộc một
  cam kết, không ràng buộc một con người).

> Lưu ý quan trọng về phiên bản: parameter set **sản xuất hiện tại là
> `bdlop-open-128-v3`** (`BDLOP_OPEN_128 = BDLOP_OPEN_128_V3` trong
> `src/lattice_zk/params.py`, từ 2026-10-26; n = 7 để binding lượng tử 156 bit).
> `-v2` và `-v1` vẫn được định nghĩa (video/registry cũ verify dưới bộ của
> chúng). Codec policy **v2 là mặc định** cho profile mới. Nhiều số học máy và
> một số bảng kết quả vẫn là của v1/v2 — xem `05_ket_qua.md`. Hai tính năng mới:
> đính kèm payload range proof vào envelope in-band và phiên offline theo epoch
> beacon (SPEC §3.7).
