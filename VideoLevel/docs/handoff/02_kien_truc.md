# Kiến trúc và luồng dữ liệu

Mục đích: mô tả pipeline nhúng và pipeline xác minh theo từng bước với module/hàm chính xác, kèm bản đồ thành phần và lý do di dời module không đổi định danh.
cập nhật: 2026-10-22

Mọi đường dẫn dưới đây tương đối với `VideoLevel/`. Điểm vào cấp cao của lõi
nằm trong `src/lattice_zk/video_pipeline.py`.

## 1. Pipeline NHÚNG (embed)

Điểm vào: `video_pipeline.embed_video_proof(...)`. CLI `embed` →
`cli._embed` → `pipeline.pins_from_registry` rồi `pipeline.embed_video_proof`.

1. **Kiểm tra chế độ / tham số** — đúng một trong hai: payload (in-band) hoặc
   credential (registered).
2. **Chọn transport** — cố định `blind_sync_streaming` hoặc thích nghi
   `blind_sync_adaptive`, theo `profile.chunk_plan`.
3. **Dựng envelope giữ-chỗ (placeholder)** cùng độ dài — `video_proof.placeholder_envelope(...)` —
   để cố định bố cục carrier *trước khi* có bằng chứng.
4. **Phân tích carrier / dẫn ngữ cảnh** — `channel.derive_chunked_video_context(...)`
   (hoặc `derive_adaptive_video_context`). Bước này chia segment, chạy kiểm tra
   GOP (`_inspect_segments`), tính `canonical_video_sha256`
   (`transport/video_canonicalization.py`) và `positions_hash`
   (`core/carrier_gate.hash_positions`), trả về `global_positions`.
5. **Dựng statement** — `video_proof.build_statement(params, pins, session_challenge,
   carrier_count, positions_hash, canonical_video_sha256)` → đối tượng
   `VideoStatement`.
6. **Tạo bằng chứng / envelope** —
   - in-band: `video_proof.create_envelope(...)` → `codec.encode_payload` →
     `bdlop.commit` → `opening_proof.prove(...)` → đóng gói `ZKLB`;
   - registered: `video_proof.create_registered_envelope(...)` →
     `opening_proof.prove(...)` → envelope chỉ-bằng-chứng `ZKLR`.
7. **Kiểm tra bất biến bố cục** — bằng chứng không được làm đổi khung chunk
   (độ dài envelope = độ dài placeholder).
8. **Vá bitstream / xuất stego** — `channel.embed_chunked_video_payload(...)`
   (vá ở mức hệ số qua `core/stego.py` `PayloadEmbedder` /
   `BitstreamReconstructor`).
9. **Trả về** `EmbedResult(statement_id, opening, envelope_bytes, carriers_used,
   segments_used, ...)`.

## 2. Pipeline XÁC MINH (verify)

Điểm vào: `video_pipeline.verify_video_proof(...)`. CLI `verify` →
`cli._verify` → mở `SessionChallengeStore` → `pipeline.verify_video_proof(...)`.

1. **Cổng cấu hình verifier (trước khi đọc video)** —
   `_require_verifier_configuration(...)`: ép production strength, đúng một
   trong `session_store`/`expected_session`, credential canonical, và
   `pins.relation_id == relation_id(params, profile, credential, holder_id)`,
   `pins.codec_policy_id == codec_policy_id(profile.codec_policy)`. Sai cấu hình
   → `ValueError`; nội dung video chỉ bao giờ cho `valid=False`.
2. **Trích carrier mù** — `channel.extract_chunked_video_payload(video_path, sync_key,
   contract, ...)`. Chạy lại chia segment + kiểm tra GOP, tính lại
   `positions_hash` và `canonical_video_sha256`, trả về `chunks` như trích được.
3. **Đọc trường phiên in-band (chưa tin)** — `video_proof.envelope_session(...)`
   chỉ kiểm magic/version/param-id.
4. **Kiểm khung chunk chuẩn** — yêu cầu `extracted.chunks == canonical_chunks`
   (fix D1), nếu không: từ chối "carrier framing is not the canonical chunking".
5. **Dựng lại statement** — `build_statement(...)` từ `global_positions`,
   `positions_hash`, `canonical_video_sha256` mà verifier tính lại.
6. **Kiểm bằng chứng** — `verify_envelope` (in-band) /
   `verify_registered_envelope` (registered) → kết ở
   `opening_proof.verify(params, statement.to_bytes(), commitment, proof)`.
7. **Tiêu thụ phiên** — stateless: `check(expected_session)`; một-lần:
   `session_store.verify_and_consume(..., context_binding=session_binding(params, pins), ...)`.
8. **Trả về** `VerifyResult(True, "ok", statement_id, carriers_used, payload)`
   hoặc chuỗi lý do từ chối.

## 3. Thành phần (component map)

| Gói | Vai trò |
|---|---|
| `src/lattice_zk/` | Lõi mật mã: `params`, `ring`/`fast_ring`, `sampling`, `bdlop` (cam kết), `opening_proof`, `equality_proof`, `linkage`, `binary_proof`, `payload_range_proof`, `codec` (mã payload), `video_proof` (statement + envelope + disclosure), `video_pipeline` (điều phối embed/verify), `cli` (CLI tách vai trò) |
| `src/transport/` | Vận chuyển mù: `blind_sync*` (đồng bộ carrier, trích mù), `blind_payload_chunks` (khung ZKBC v1), `adaptive_chunks` (ZKBC v2), `gop_policy` (chính sách GOP), `video_canonicalization` (digest D5) |
| `src/registry/` | `zkp_registry` (registry quan hệ ký ML-DSA), `zkp_sessions` (kho thách thức một-lần, SQLite), `zkp_session_http` (front-end HTTP), `lattice_pq` (`LatticeSigner` ML-DSA-65; cũng chứa SIS prototype chỉ-nghiên-cứu, tách khỏi đường video) |
| `src/core/` | Phân tích carrier và vá CAVLC: `adaptive_carriers`, `analysis_cache`, `carrier_gate`, `carrier_order`, `chaos`, `matrix_embedding`, `parallel_analysis`, `pipeline`, `stego` |
| `src/bitstream/` | Phân tích/ghi H.264 / CAVLC: `h264`, `cavlc`, `bitstream_io`, `bitstream_ops`, `rbsp_patch` |
| `src/legacy/` | Hệ cũ trước lattice-ZK (embed/verify sidecar, cầu Groth16, trust/provenance, realtime) — không nằm trên đường chạy hiện tại |

## 4. Định danh và ràng buộc statement

- **Statement** (`VideoStatement`) là chuỗi cố định-chiều rộng gồm: `version`,
  `relation_id`, `parameter_id`, `registry_root`, `registry_epoch`,
  `session_challenge`, `codec_policy_id`, `carrier_profile_id`, `carrier_count`,
  `positions_hash`, `video_commitment` (mỗi digest 32 byte). `statement_id =
  SHA3-256(domain ‖ to_bytes())`. Chuỗi này được "hút" vào hàm băm Fiat–Shamir
  của `opening_proof`, nên bằng chứng chỉ hợp lệ với đúng statement + cam kết.
- **Profile id / relation id**: `CarrierProfile.profile_id`, `codec_policy_id`,
  `policy_hash`, `relation_id`, `parameter_id`, `AdaptiveChunkPlan.plan_id`,
  `holder_id_digest` đều được băm từ **hằng số domain cố định + JSON chuẩn tắc
  (`sort_keys`, không khoảng trắng) / `struct` cố định-chiều rộng của các giá
  trị đã pin**.
- **Vì sao di dời module không đổi định danh**: không định danh nào băm đường
  dẫn module Python hay `__qualname__`/`__module__`. Chúng chỉ phụ thuộc giá trị
  dữ liệu (ví dụ `dataclasses.asdict` của hợp đồng carrier serialize giá trị
  trường, không serialize vị trí lớp). Do đó đợt dọn dẹp 10/2026 (đưa module vào
  `src/transport/`, `src/registry/`, `src/legacy/`) **không** đổi bất kỳ id,
  hash, hay KAT nào; các test byte-identity vẫn xanh (bản đồ di dời/xóa đầy đủ
  trong git history của đợt dọn dẹp 10/2026).

## 5. Khung chunk, GOP, digest, registry (tham chiếu nhanh)

- Khung chunk cố định **ZKBC v1**: `transport/blind_payload_chunks.py`
  (`CHUNK_MAGIC=b"ZKBC"`). Thích nghi **ZKBC v2**: `transport/adaptive_chunks.py`
  (`"zkbc-v2-greedy-fill-v1"`), opt-in qua `profile.chunk_plan`.
- **GOP policy**: `transport/gop_policy.py` — `all-intra` (mặc định) hoặc
  `idr-carriers-inter-raw-v1` (GOP > 1).
- **Digest chuẩn hóa (D5)**: `transport/video_canonicalization.py` —
  `DIGEST_V1` / `DIGEST_V2` (codec policy v2, hardened, opt-in).
- **Registry**: `registry/zkp_registry.py` (`SignedZkpRelationRegistry`);
  ký bằng `registry/lattice_pq.LatticeSigner` (ML-DSA-65). Ghim quan hệ:
  `pins_from_registry` kiểm chữ ký, sàn epoch, đúng một quan hệ khớp, rồi
  resolve gốc + epoch.
- **Phiên một-lần**: `registry/zkp_sessions.SessionChallengeStore` — `issue`
  (sinh 32 byte từ `secrets`, chỉ lưu digest), `verify_and_consume` (tiêu thụ
  nguyên tử một lần qua `UPDATE ... WHERE consumed_at IS NULL`).
