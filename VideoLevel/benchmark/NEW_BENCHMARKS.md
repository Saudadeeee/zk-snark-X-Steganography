# Benchmark suite

One command runs every measurement and writes **one report**:

```powershell
py -3.12 -m benchmark.run_new_suite
```

| Output | Content |
|---|---|
| `results/benchmark_report_new.pdf` | The single human-readable report (Vietnamese): verdicts, key findings, information coverage, environment, conversion, capacity, performance, image quality, sign statistics, end-to-end timing, attack matrix, Groth16 vs PLONK, crypto primitives, recorded camera runs, limits |
| `results/media_new/<run-id>/video_pipeline_new.json` | Every media case (27 = 9 clips × 3 resolutions) |
| `results/media_new/<run-id>/quality_per_frame_new.csv` | PSNR-Y/SSIM of every frame |
| `results/e2e_new.json` | Host facts, end-to-end stage timing, attack matrix |
| `results/zkp_new.json`, `results/security_new.json` | Proof systems and crypto primitives |
| `results/conversion_manifest_new.json`, `results/converted_h264_new/` | Full-duration Y4M → H.264 conversions |
| `results/realtime_camera_runs_*.json` | Physical-camera runs (recorded separately, see below) |

The report is rebuilt from those records alone: `py -3.12 -m benchmark.reports_new`.
Encoded/stego `.h264` files of a media run stay local (git-ignored). Analysis
helpers are unit-tested in `benchmark/test_benchmark_analysis_new.py` (Phase 9).

## Requirements

`data/raw/*.y4m` (only `foreman_cif.y4m` is tracked; the recorded run used nine
CIF clips: akiyo, city, coastguard, container, deadline, football, foreman,
foreman_cif_300f, hall_monitor), a native Release build (`zkstego_blind_bits`,
`zkstego_inspect`), `circuits/build` (Groth16 keys, wasm) and FFmpeg on PATH.
A fresh clone with one clip produces 3 media cases instead of 27.

## What each part measures

**Media matrix** (`media_benchmark_new.py`). Every clip is encoded with libx264
Baseline/CAVLC, QP 22, all-intra, no B-frames, one thread, one slice per IDR,
first 30 frames at 352×288, 640×480 and 1280×960 (the larger two are scaled from
CIF: scaling evidence, not native high-resolution scenes). Each case uses a fresh
32-byte key, proves `SHA256(SHA256(message) ‖ secret)` with Groth16 and embeds
`pack(message, 129-byte proof)` with the protocol defaults (v3 frame, 64 bits per
IDR). A case passes only if the native capacity scan, native embed, FFmpeg strict
decode (`-xerror`), blind extraction of the exact payload, mandatory Groth16
verify of the extracted proof, wrong-key rejection all succeed **and** no sign
changed outside the keyed schedule (checked position by position with
`zkstego_inspect --segments`).

**End-to-end** (`e2e_benchmark_new.py`). Five full runs on a 300-frame CIF clip:
prove → embed → strict decode → extract → Groth16 verify, each with a new key and
message, plus host facts (CPU, cores, RAM, OS, FFmpeg/Node/snarkjs versions,
commit, native binary hashes). The attack matrix feeds edited streams and
mismatched payloads through the HTTP verify-job decision.

**Proof systems** (`zkp_benchmark_new.py`). Groth16 and PLONK on the same R1CS
and witness, with a positive and a tampered-public-input verify each. PLONK uses
a locally generated 2^18 Powers-of-Tau and its setup is timed separately. The
suite runs Groth16 five times and PLONK once (one PLONK proof takes ~14 min and
~20 GB RAM on this circuit; the PLONK proving key is ~22 GB on disk).

**Crypto primitives** (`crypto_benchmark_new.py`). Real `cryptography` calls for
HMAC-SHA-256, Ed25519, RSA-PSS, AES-256-GCM, ChaCha20-Poly1305, RSA-OAEP+AES-GCM,
X25519+HKDF+ChaCha20-Poly1305 and an encrypt-then-sign composition. Their
properties are not equivalent; none is presented as formal signcryption. The
HMAC row is the full 32-byte primitive; since protocol v3 the native frame has no MAC.

## Recorded run (2026-10-04, i7-12700H, Windows 11, channel protocol v3)

Media run `20261004T124108Z_792a81`, E2E `e2e_new.json`, ZKP `zkp_new.json`:

- **Functional:** conversion 9/9, media 27/27, E2E 5/5, attacks 10/10 as
  expected; zero signs changed outside the schedule in every case.
- **Payload:** 201 B (4 B length + 68 B message + 129 B proof) → v3 frame of
  204 B = 1,632 bits → 26 IDRs at 64 bits each (v2 needed 1,760 bits / 28 IDRs
  with its 16-byte HMAC tag); about half of the scheduled signs actually flip
  (whitened bits).
- **Native cost scales with parsed IDRs.** Median capacity scan per IDR: 48 ms
  (352×288), 172 ms (640×480), 666 ms (1280×960); median embed per carrying IDR:
  56 / 194 / 791 ms. The embed parses only the IDRs that carry bits and copies
  the rest. This, not Groth16, bounds per-frame realtime processing.
- **Groth16 (E2E median):** prove 3.14 s, verify 0.91 s (both include Node.js
  start-up); native embed 0.51 s and extract 0.52 s for 300 CIF frames. ZKP
  suite: Groth16 prove 3.5–3.9 s, PLONK prove 1,496 s on the same R1CS.
- **Quality:** lowest cover→stego PSNR-Y per case 44.89–55.79 dB, 0/27 below the
  40 dB reference; 26/30 frames change in every case.
- **Size:** stego − cover is 0 B except one case (+1 B): flipping a sign can add or
  remove an emulation-prevention byte; the CAVLC code length never changes.
- **Sign statistics:** |z| ≤ 0.25 for the share of negative trailing ones — not
  distinguishable at the 5 % level (first-order indicator only).
- **Attacks:** a wrong key, a dropped IDR and a re-encode find no frame
  (`payload_not_found`); a flipped scheduled sign, a swapped message and a proof
  made with another secret are rejected by Groth16 (`proof_invalid`). Accepted
  by design (known limits): a flipped unscheduled sign, truncation after the
  payload, and replaying the payload into another video with the same key.

## Physical camera

Set `ZK_STEGO_CAMERA_NAME` to a DirectShow device and run
`py -3.12 -m benchmark.realtime_camera_recorder --duration 60`; records are
appended to `results/realtime_camera_runs_*.json` only after strict decode,
frame-count, proof, key-rejection and stream-completion gates pass. The recorded
runs (2026-09-24) used protocol v1 before the 2026-10-02 native speed-up. Runs
before 24 used FFmpeg's default CFR synchronisation (duplicated frames), so their
~30 FPS is not acquisition FPS; run 24 (`fps_mode passthrough`) measured
**7.608 FPS**, which fails the 30-FPS gate. Details:
[`doc/realtime_cavlc_theory_and_implementation.md`](../doc/realtime_cavlc_theory_and_implementation.md).

## Not measured

Machine-learning steganalysis, comparison with other video steganography
methods, edge devices, CABAC or P/B-frame carriers. Further like-for-like proof
systems (Halo2, RISC Zero, Bulletproofs R1CS) would need a Rust toolchain, which
this host does not have; literature or legacy simulated values must not stand in
for them. The legacy SEC1–SEC10 drivers and their outputs are in git history
only and are not current evidence.
