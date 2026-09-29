# Blind video-only extraction recheck (2026-09-29)

## Result

The current stable-carrier channel successfully carried and recovered an
8-byte test payload from an H.264 video using only the stego video, verifier
sync key, and pinned `BlindOperatingContract`. The payload was not a ZK proof;
this validates only the carrier/framing/extraction component.

## Reproduction and automated test evidence

Executed:

```powershell
py -3.12 -m pytest -q `
  src/runtest/test_video_only_blind_sync_integration.py `
  src/runtest/test_blind_payload_envelope.py `
  src/runtest/test_video_zkp_contract.py
```

Result: **13 passed in 108.81 s**. The real-video integration test embeds a
framed payload into `data/encoded/foreman_cif_g8_300f_b800k.h264`, emits only
the H.264 file in its output directory, re-derives carriers from the stego
video, extracts the payload, compares fast-path and direct CAVLC extraction,
and checks that cover/stego carrier-normalized digests match. The test's
temporary output is deleted on completion.

## Retained artifact

An additional run retained a video-only artifact under
`benchmark/results/video_only_blind_payload_diagnostic_20260929/`:

| Field | Observed value |
|---|---:|
| Cover | `data/encoded/foreman_cif_g8_300f_b800k.h264` |
| Cover / output size | 2,989,523 / 2,989,523 bytes |
| Embedded payload | `5a17c09e31b46d82` (8 bytes; not a proof) |
| Framed envelope | 22 bytes |
| Carriers used | 176 |
| Blind extraction time | 14.254 s (single run) |
| Extraction equality | pass |
| Carrier-normalized digest equality | pass |
| FFmpeg decode | exit 0, no diagnostics |
| Output SHA-256 | `f79840c8ff915cb45913b2184705f91c1460619c7e12dfea66f6e4c46201d8e4` |

The machine-readable observations are in `run_metrics.json`; the retained video
is `stego_payload_only.h264`. The embed wall time was not captured in this
retained-artifact run, so no embed-time claim is made. The 14.254 s extraction
measurement is a single diagnostic observation, not a benchmark distribution
or a realtime result.

## Truncation negative probe

The retained H.264 artifact was copied to a temporary file after removing its
last half (1,494,761 bytes retained), then passed to
`extract_blind_video_payload()` with the same sync key and contract. The real
extractor rejected it with `ValueError: blind payload magic mismatch`; it did
not return an accepted payload. This behavior is now also asserted in
`src/runtest/test_video_only_blind_sync_integration.py` against a freshly
generated real-video stego fixture. Recheck command:

```powershell
py -3.12 -m pytest -q `
  src/runtest/test_video_only_blind_sync_integration.py::test_stego_video_alone_rederives_carriers_and_extracts_payload
```

The first recheck passed in 114.86 s. After extending this integration case to
also exercise policy-pinned statement context, the latest command completed
with **1 passed in 181.84 s**. It covers one truncation mode, not every possible
bitstream mutation or a truncated ZK proof envelope; the fixture payload is
ordinary data, not a proof.

The extended real-video case also creates a signed registry descriptor whose
policy pins the complete carrier-profile hash, constructs the statement from
the real video digest and independently derived positions, and calls
`verify_video_zkp_context_binding_video_only()` with the verifier's expected
session challenge. This helper independently derives the carrier order and
checks the registered policy, positions hash, and normalized video digest.
The test uses a fresh temporary video that is deleted afterwards; it does not
retain a second output artifact. The statement helper still does not verify a
ZK proof or open the payload commitment.

The unit contract suite also passed: **9/9** via
`py -3.12 -m src.runtest.test_video_zkp_contract`.

## Scope and remaining gates

This result does **not** prove that the bytes are a lattice ZK proof, does not
test proof verification, does not bind this artifact to an application
statement, and does not establish security against a knowledgeable attacker.
It is not a PSNR/SSIM or broad codec robustness benchmark. A production
acceptance run still needs a reviewed ZK backend, a serialized full proof that
fits the fixed envelope, video-derived verifier statement construction,
negative proof/video tampering tests, quality measurements, and independent
verification from the extracted bytes.

## Verifier-context re-review

After aligning the carrier-profile descriptor with the actual conditional
ordering-key derivation and `ChaosTransformer` behavior, the contract suite was
rerun and passed **9/9**. A regression check first reproduced that an
unregistered policy caused video carrier derivation to run; after the fix, the
test confirms registry/policy binding is rejected before video analysis.
The video-only helper explicitly pins the CIF macroblock grouping constant
used for ordering.

The real-video integration test was rerun after these changes:

```text
py -3.12 -m pytest -q src/runtest/test_video_only_blind_sync_integration.py::test_stego_video_alone_rederives_carriers_and_extracts_payload
1 passed in 152.02s
```

Independent Python review found no new bypass in these helper files and
confirmed both earlier findings are resolved. This remains context-binding
evidence only: the helper has no persistent challenge-consumption state, so
the API/caller must issue unique challenges and reject reuse. No lattice ZK
proof is generated or verified by this test.
