# Dọn dẹp còn lại (từ đợt dọn dẹp 10/2026)

Mục đích: giữ lại phần việc dọn dẹp còn chờ phê duyệt và danh sách file kết quả
phải giữ. Trích từ `docs/CLEANUP_INVENTORY.md` (nay đã xóa; tài liệu đó là một
bản ghi dọn dẹp tạm thời). **Bản đồ di dời/xóa file đầy đủ nằm trong git history
của đợt dọn dẹp 10/2026.** Đây chỉ giữ hai thứ một người duy trì còn cần:
danh sách xóa còn chờ và các file kết quả phải giữ.

## 1. Xóa còn chờ (second pass)

Một quy tắc chặt hơn được yêu cầu về sau: chỉ giữ một file đã track nếu hệ thống
hiện tại, một legacy subsystem đang hoạt động và có test, hoặc provenance của
paper/kết quả cần tới nó. Các file dưới đây không đạt quy tắc đó. Chúng **chưa bị
xóa**: việc xóa bị chặn bởi kiểm tra quyền của phiên và chờ phê duyệt tường minh.
Không file nào được giữ import hay đọc chúng.

| Đường dẫn | Lý do |
|---|---|
| `benchmark/legacy/` trừ `_common`, `blind_core_trial`, `clean_artifacts`, `lattice_in_video_feasibility`, `locked_operating_contract`, `native_pipeline_matrix`, `sec4_security`, `sec5_zkp`, `streaming_capacity_scan`, `trust_corpus` (+ manifest): 31 script (SEC1-3, SEC6-10, SEC45-47, `safe_benchmark_runner`, `statistical_benchmark`, các blind diagnostic, `public_api_realization`, `validated_pool_proxy_diagnostic`, `trust_architecture_diagnostic`, `patchable_capacity_scan`, hai native probe) | không test nào chạy chúng; mười cái được giữ do một test hoặc một benchmark `latticezk_*` hiện tại import (`_common`, `sec4_security`, `sec5_zkp`) |
| `benchmark/latticezk_profile.py` | profiler một lần; không script, doc hay test nào gọi tên |
| `src/legacy/verifier_blind_keyed.py` | caller duy nhất của nó là `blind_contract_operating_point.py` |
| `src/runtest/legacy/demo_embed_verify.py` | script demo, không phải test; cần một build Groth16 |
| `src/runtest/legacy/test_native_cli_fixture.py` | test `zkstego_blind_bits`, mà không CMake target nào build; luôn bị skip |
| `legacy/docker/` (7), `legacy/ci.yml`, `.dockerignore` | image chưa test; một file CI GitHub không bao giờ chạy |
| `docs/legacy/ARTIFACT_POLICY.md`, `OPERATING_ENVELOPE.md`, `PAPER_EVIDENCE.md`, `trust_corpus_onboarding.md`, `system_video_embedding_walkthrough.tex/.pdf` | mô tả baseline tiền-lattice đã đóng băng (6-9/2026); `ARTIFACT.md`, bản ghi này và `docs/review/CLAIMS.md` phủ các bản tương đương hiện tại. Nếu luồng docs muốn danh sách supported-envelope cũ (giới hạn codec/profile/GOP/QP), lấy từ `OPERATING_ENVELOPE.md` trước khi xóa |
| `benchmark/results/` các đầu ra non-`q2` của các script trên và các diagnostic cũ: 19 ghi chú `.md`/`.txt`, 4 `ringo_*`, 2 `streaming_*_capacity_*`, `lattice_zkp_unreviewed_capacity_probe.json`, 2 tóm tắt `native_pipeline_matrix_*`, mọi PNG `sec1`-`sec7` và dữ liệu `sec2`-`sec7`, PNG `sec45`, dữ liệu `sec46`/`sec47`, `trust_architecture_diagnostic.json` | không bảng paper, doc hiện tại hay test nào trích dẫn |

## 2. Giữ có chủ đích

- `benchmark/results/q2/**`, các kết quả `latticezk_*` (hệ thống hiện tại).
- `sec1_quality_data.json` (đọc bởi `test_phase7_regression_cases`).
- `sec45_trust_evidence_data.json` và `trust_corpus_validation.json` (đọc bởi
  `src.legacy.trust.product_readiness` trong `test_future_trust_architecture`).
