# Checklist dành cho người đánh giá

Đánh dấu từng mục dựa trên mã tại commit `18c5123`. Các đường dẫn tương đối so
với `VideoLevel/src/`. "Test" nêu tên test kiểm nghiệm mục đó, nếu có.

## 1. Tham số (`lattice_zk/params.py`)

- [ ] q = 2^30 − 35 là nguyên tố và q ≡ 5 (mod 8). Được kiểm tra bởi
      `ring.validate_modulus` (`ring.py:42–47`, Miller–Rabin với 12 base cố
      định, tất định (deterministic) dưới 3.3·10^24). Test:
      `test_latticezk_ring.py::test_toy_modulus_satisfies_two_factor_splitting_condition`,
      `::test_modulus_validation_rejects_composites_and_out_of_range_values`.
- [ ] `2√2 < √q` (tính khả nghịch của `C̄`, `params.py:63–65`) và
      `2·8κB < q` (norm binding không wrap, `params.py:66–68`). Test:
      `test_latticezk_bdlop.py::test_parameters_reject_unsound_choices`.
- [ ] `B = γ − κ − 1` (`params.py:80–83`), shift bound κ (`:75–78`).
      `acceptance_probability = ((2B+1)/2γ)^{kN}` (`:118–122`) bằng 0.1912.
      Test: `::test_response_bound_leaves_exactly_the_shift_margin`,
      `::test_abort_rate_matches_the_parameter_estimate`.
- [ ] Challenge space `log2 C(256,60) + 60 = 257.01` bit (`:114–116`).
      `require_production_strength` cần ≥ 256 (`:141–144`). Lưu ý: điều này
      chỉ được cưỡng chế trong `pins_from_registry` (QUESTIONS Q12).
- [ ] `parameter_id` hash mọi trường làm thay đổi relation, với các độ rộng cố
      định và setup seed (`:124–139`). Test:
      `::test_parameter_id_pins_every_field`.
- [ ] Các ước lượng an toàn khớp với các instance trong các chứng minh: M-SIS
      trên `B1 ∈ R_q^{n×k}`, ℓ∞ ≤ 8κB; M-LWE rank λ với n+1 sample. Xem
      `research/bdlop_params/CROSSCHECK.md`.

## 2. Các phân phối sampling (`lattice_zk/sampling.py`)

- [ ] `_rejection_sample` (`:39–47`) mask xuống `bits` bit và giữ các giá trị
      `< bound`. Nó không bao giờ rút gọn theo modulo của bound. Mỗi lần gọi
      đọc `count − accepted + 16` lần rút (draw) và **loại bỏ phần đuôi không
      dùng**. Điều này không thay đổi tính đều, nhưng một hiện thực độc lập
      phải sao chép đúng cách tiêu thụ stream để tái tạo các KAT.
- [ ] Các key polynomial phân bố đều trên [0, q) từ các lần rút 30-bit
      (`:50–51`), với tỉ lệ chấp nhận khoảng 0.99999997.
- [ ] Commitment randomness là ternary đều, từ các lần rút 2-bit nhỏ hơn 3
      (`:54–57`). Test: `test_latticezk_ring.py::test_ternary_vector_is_balanced`.
- [ ] Các mask phân bố đều trên [−γ+1, γ] dưới dạng `γ − u` với `u` là một lần
      rút 18-bit nhỏ hơn `2γ = 2^18` (`:60–66`), nên không lần rút nào bị
      rejected. Test: `::test_mask_vector_covers_exact_interval`.
- [ ] Các challenge (`:69–81`): weight-many sign bit, rồi một phép xáo trộn
      (shuffle) Fisher–Yates trên các vị trí N−κ … N−1, mỗi index được rút bằng
      rejection chính xác nhỏ hơn `index+1`. Đây là SampleInBall của ML-DSA và
      cho một phân phối đều trên `C`. Tag: `zkstego/lattice-zk/challenge-poly/v1\0`.
      Test: `::test_challenge_has_fixed_weight_and_depends_on_seed`,
      `::test_full_weight_challenge_has_no_zero_coefficient`.
- [ ] `XofStream.read` (`:22–29`) tính lại một output SHAKE-256 dài hơn từ
      đầu. Tính đúng đắn dựa vào tính nhất quán prefix (prefix consistency) của
      SHAKE. Test: `::test_xof_stream_is_deterministic_and_prefix_stable`.
- [ ] Entropy tươi đến từ `os.urandom(32)`: commitment randomness
      (`bdlop.py:126–132`) và entropy của prover (`opening_proof.py:54–60`).
      Session challenge dùng `secrets.token_bytes(32)` (`zkp_sessions.py:133`).

## 3. Số học trên ring (`lattice_zk/ring.py`)

- [ ] `poly_mul` (`:76–91`) là tích negacyclic chính xác bằng phép thế
      Kronecker. Độ rộng limb `(N·(q−1)^2).bit_length()//8 + 1` byte không để
      lại carry giữa các limb, và `wide[i] − wide[i+N] mod q` hiện thực
      `X^N = −1`. Test: `::test_poly_mul_matches_negacyclic_schoolbook`,
      `::test_poly_mul_handles_large_modulus_without_overflow`,
      `::test_x_to_the_n_is_minus_one`.
- [ ] `center` ánh xạ vào [−(q−1)/2, (q−1)/2] (`:60–63`). Prover khôi phục số
      nguyên `c·r` một cách chính xác vì `κ < q/2` (`opening_proof.py:106–107`).
- [ ] `is_invertible` (`:106–114`) kiểm tra cả hai thành phần CRT. Nó chỉ đúng
      vì `X^{N/2} ± √−1` là bất khả quy (q ≡ 5 mod 8; QUESTIONS
      Q3). Verification không bao giờ gọi nó.

## 4. Các cận và điều kiện rejection

- [ ] Opening prover: abort khi và chỉ khi `max |z_i| > B` (`opening_proof.py:108–109`).
      Đây là phép kiểm tra rejection duy nhất, và nó độc lập với witness
      (Bổ đề `lem:hvzk`). Test:
      `test_latticezk_bdlop.py::test_respond_accepts_exactly_the_response_range`,
      `::test_accepted_response_coordinate_is_uniform_for_any_witness`,
      `::test_accepted_responses_are_in_range_and_witness_independent`.
- [ ] Equality prover: chấp nhận khi và chỉ khi *cả hai* response đều trong
      dải (`equality_proof.py:144`). Cap 4096 (`:50`); xác suất thất bại khoảng
      2^-220 (`:54–64`). Test:
      `test_latticezk_equality.py::test_equality_prover_cap_gives_negligible_completeness_error`,
      `::test_shared_opening_cap_would_not_have_sufficed_for_production`.
- [ ] Opening cap 512 (`opening_proof.py:33`); xác suất thất bại 2^-156.7.
      Cạn cap sẽ raise và không bao giờ xuất ra một transcript bị rejected
      (`:136`). Test: `test_latticezk_bdlop.py::test_provers_fail_closed_when_every_attempt_aborts`.
- [ ] Kiểm tra dải ở verifier: `unpack_uints(..., bound = 2B+1)` từ chối bất
      kỳ giá trị packed nào vượt 2B, nên `z ∈ [−B, B]` (`opening_proof.py:155–162`,
      `equality_proof.py:175–181`). Không cần phép kiểm tra norm nào khác.
- [ ] Prover từ chối các witness non-ternary (`bdlop.py:50–56`) và các witness
      không open `t1` (`opening_proof.py:124–125`). Equality prover cũng kiểm
      tra rằng message gap bằng không
      (`equality_proof.py:89–106`). Test:
      `::test_prover_refuses_a_non_ternary_witness`,
      `::test_prover_refuses_randomness_that_does_not_open_the_commitment`,
      `test_latticezk_equality.py::test_different_messages_cannot_be_proved_equal`.

## 5. Các encoding (`lattice_zk/codec.py`, `bdlop.py`, `video_proof.py`)

- [ ] `pack_uints` / `unpack_uints` (`codec.py:10–33`): độ rộng bit cố định,
      MSB trước, độ dài chính xác, zero padding, các giá trị nhỏ hơn bound.
      Proof packing không có bit padding ở tham số production
      (`3584 · 18 bits = 8064 bytes`). Test:
      `test_latticezk_bdlop.py::test_pack_uints_round_trip_and_canonical_rejection`,
      `::test_random_packed_fields_round_trip_and_decode_canonically`.
- [ ] Các commitment là canonical: shape và mọi hệ số trong [0, q) được kiểm
      tra lúc construction từ byte và tại mọi điểm vào của prover/verifier
      (`bdlop.py:40–47, 76–108`; `opening_proof.py:63–74`). Test:
      `::test_non_canonical_commitments_are_refused_everywhere`.
- [ ] Payload encoding là đơn ánh (độ dài 2 byte, 3 byte mỗi hệ số, tối đa 766
      byte), và decoder chấp nhận đúng ảnh (image) của encoder
      (`codec.py:36–60`). Test:
      `::test_payload_encoding_is_injective_and_bounded`,
      `::test_decodable_messages_are_exactly_the_encoder_image`.
- [ ] Statement có độ rộng cố định (274 byte) với trường session tại byte
      106–137 (`video_proof.py:89–98`). Mỗi trường digest được kiểm tra là 32
      byte và mỗi số nguyên là u64 (`:54–87`). Test:
      `test_latticezk_video_proof.py::test_statement_encoding_is_fixed_width_and_injective_per_field`.
- [ ] Các envelope có độ dài chính xác, magic và version, một `pid` được pin
      với so sánh kiểu constant-time, và một canonical commitment
      (`video_proof.py:171–182, 263–273`). Trường session phải bằng trường của
      statement (`:223, 286`). Test: `::test_envelope_rejects_tampering_and_malformed_framing`,
      `::test_envelope_kinds_are_not_interchangeable`,
      `::test_random_garbage_never_decodes_as_an_envelope`.
- [ ] Carrier framing phải là chunking canonical của envelope dưới kích thước
      chunk được pin (sửa D1, `video_pipeline.py:359–367`).
      Test: `test_latticezk_video_pipeline.py::test_rewritten_single_chunk_header_is_rejected`,
      `::test_rechunked_multi_chunk_envelope_is_rejected`.

## 6. Transcript Fiat–Shamir và domain separation

- [ ] Opening: `SHAKE-256(tag ‖ pid ‖ u64(|x|) ‖ x ‖ enc(t1,t2) ‖ w as >u8)`,
      output 32 byte (`opening_proof.py:43–51`). `w` được verifier tính lại là
      `B1·z − c·t1 mod q` (`:167`).
- [ ] Equality: `SHAKE-256(tag ‖ pid ‖ u64(|x|) ‖ x ‖ enc(t_a) ‖ enc(t_b) ‖ w_a ‖ w_b ‖ u)`
      (`equality_proof.py:71–82`). Verifier tính lại `u` là
      `⟨b2, z_a − z_b⟩ − c(t2_a − t2_b)` (`:186–192`).
- [ ] Việc so sánh seed dùng `hmac.compare_digest` (`opening_proof.py:168`,
      `equality_proof.py:193`).
- [ ] Tags: `…/bdlop-open/v1/{key, randomness, fiat-shamir, mask}\0`,
      `…/bdlop-equal/v1/{fiat-shamir, mask}\0`, `…/challenge-poly/v1\0`,
      `…/bdlop-open/v1/parameters\0` (SHA3-256), các tag linkage, disclosure,
      statement và video-commitment. Mỗi tag kết thúc bằng NUL byte duy nhất
      của nó.
- [ ] Hedged mask key: SHA3-256 **không có tag** (D7, open;
      `opening_proof.py:77–90`). Mask stream: `tag ‖ K ‖ u32(attempt)`. Test:
      `test_latticezk_bdlop.py::test_mask_stream_is_never_reused_across_statements_or_witnesses`,
      `::test_proving_is_deterministic_only_under_an_explicit_mask_seed`.
- [ ] Các context linkage và disclosure được length-prefix và ràng buộc với
      `pid` (`linkage.py:29–36`, `video_proof.py:302–316`). Test:
      `test_latticezk_linkage.py::test_context_encoding_is_unambiguous`,
      `test_latticezk_video_proof.py::test_disclosure_rejects_wrong_payload_context_or_envelope`.

## 7. Các lưu ý về constant-time (chưa được xử lý)

Đây là một **hiện thực nghiên cứu thuần Python/NumPy. Nó không phải constant
time** và không đưa ra tuyên bố side-channel nào (`security.tex`, mô hình
adversary). Mã variable-time đã biết có chạm tới các secret:

- [ ] `ring.poly_mul` dùng số nguyên lớn (big integer) của Python. Thời gian
      nhân phụ thuộc vào độ dài bit của toán hạng, và do đó vào việc có bao
      nhiêu limb dẫn đầu (leading limb) của `r` được packed bằng không
      (`ring.py:66–91`). Nó chạy trên `c·r` trong mỗi lần thử
      (`opening_proof.py:93–95`).
- [ ] `ring.center` và `np.abs(response).max()` (`opening_proof.py:107–109`)
      là các phép toán NumPy phụ thuộc dữ liệu. NumPy không cho đảm bảo nào về
      timing.
- [ ] Số lần thử (attempt count) có thể quan sát được qua timing. Nó độc lập
      với witness theo Bổ đề `lem:hvzk`, nên nó không leak gì *nếu* sampler là
      chính xác đều.
- [ ] Các vòng lặp `_rejection_sample` phụ thuộc dữ liệu, nhưng chỉ phụ thuộc
      vào các giá trị công khai hoặc dẫn xuất từ hash (các key và challenge)
      hoặc vào các mask, mà các lần rút của chúng không bao giờ bị rejected.
- [ ] Vật liệu bí mật (`r`, các mask, `K`) không bao giờ được zeroize. Python
      không thể đảm bảo điều đó.
- [ ] Các tập tin bí mật do CLI ghi ra là owner-only trên POSIX
      (`cli.py:54–59`). Điều này không được cưỡng chế trên Windows, nơi test bị
      skip.

## 8. Đường dẫn verification (`lattice_zk/video_pipeline.py:300–402`)

- [ ] Cấu hình sai (misconfiguration) sẽ raise trước khi video được đọc. Phải
      cung cấp đúng một trong hai: session store hoặc expected session, và
      tổ hợp credential/profile phải nhất quán. Relation id được tính lại từ
      `(params, profile, credential, holder_id)` và so sánh với các pin (sửa
      D6, `:300–326`). Test:
      `test_latticezk_video_pipeline.py::test_malformed_verifier_configuration_is_refused_loudly`.
- [ ] Mọi trường statement trừ `N_s` đều đến từ các pin hoặc từ phần tính lại
      của transport (`:369–375`). `N_s` được đọc từ envelope rồi được store
      kiểm tra (`:390–397`) hoặc bằng `expected_session`.
- [ ] Một exception của transport cho `valid=False`, không bao giờ là accept
      (`:351–361`). Test: `::test_transport_failures_are_reported_as_rejection`.
- [ ] Pins: chữ ký ML-DSA-65, epoch floor, đúng một descriptor khớp, và các
      tham số production-strength (`:180–213`). Test:
      `::test_registry_pins_resolve_only_for_the_registered_configuration`,
      `::test_registry_epoch_outside_the_statement_field_is_refused`.
- [ ] Việc tiêu thụ session là nguyên tử (atomic) và dùng một lần, và
      verification thất bại không tiêu thụ session (`zkp_sessions.py:157–241`).
      Test: `test_zkp_sessions.py` (12 test, bao gồm concurrency và expiry
      trong lúc verification).

## 9. Known-answer vectors

- [ ] `research/bdlop_params/kat.py` dẫn xuất mọi thứ từ các seed cố định và
      pin các SHA-256 digest của key, các commitment, các opening proof và các
      equality proof. Nó bao quát các payload rỗng, ngắn và tối đa (766
      byte). Tái tạo và diff:
      `python -B research/bdlop_params/kat.py --parameter-set BDLOP_OPEN_128_V2 | diff - research/bdlop_params/kat_v2.json`
      (và `BDLOP_OPEN_128_V1` so với `kat_v1.json`).
      Test: `test_latticezk_kat.py` (3 test, chạy cho cả hai bộ).
- [ ] Các KAT cố định đúng cách tiêu thụ XOF (xem §2). Bất kỳ thay đổi nào đối
      với các tag, đối với đầu vào hedging (D7) hoặc đối với các sampler đều làm
      chúng thay đổi.
