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
32-byte stego key; one camera of an 8-camera Poseidon registry proves (Groth16,
`circuits/camera_video.circom`) that it is registered and binds the cover's video
digest and the message; the 201-byte payload `[0x01][mode][len][message][129-byte
proof]` is embedded with the protocol defaults (v3 frame, 64 bits per IDR). A case
passes only if the native capacity scan, native embed, FFmpeg strict decode
(`-xerror`), blind extraction of the exact payload, a **video-bound** proof that
verifies against the registry root with the digest recomputed from the stego file,
wrong-key rejection all succeed **and** no sign changed outside the keyed schedule
(checked position by position with `zkstego_inspect --segments`).

**End-to-end** (`e2e_benchmark_new.py`). Five full runs on a 300-frame CIF clip:
cover digest → prove → embed → strict decode → extract → verify (stego digest +
Groth16), each with a new key and message, plus host facts (CPU, cores, RAM, OS,
FFmpeg/Node/snarkjs versions, commit, native binary hashes). The 11-case attack
matrix feeds edited streams and mismatched payloads through the HTTP verify-job
decision.

**Proof systems** (`zkp_benchmark_new.py`). Groth16 and PLONK on the same
`camera_video` R1CS (8,737 constraints, 3 public inputs) and witness, with a
positive and a tampered-public-input verify each. PLONK uses the public Hermez
Powers of Tau (2^16) as its universal SRS; its setup is timed separately.

**Crypto primitives** (`crypto_benchmark_new.py`). Real `cryptography` calls for
HMAC-SHA-256, Ed25519, RSA-PSS, AES-256-GCM, ChaCha20-Poly1305, RSA-OAEP+AES-GCM,
X25519+HKDF+ChaCha20-Poly1305 and an encrypt-then-sign composition. Their
properties are not equivalent; none is presented as formal signcryption. The
HMAC row is the full 32-byte primitive; since protocol v3 the native frame has no MAC.

## Recorded run (2026-10-04, i7-12700H, Windows 11, protocol v3 + camera proof)

Media run `20261004T142448Z_1db00a`, E2E `e2e_new.json`, ZKP `zkp_new.json`:

- **Functional:** conversion 9/9, media 27/27 (every proof video-bound), E2E 5/5,
  attacks 11/11 as expected; zero signs changed outside the schedule.
- **Payload:** 201 B (4 B header + 68 B message + 129 B proof) → 1,632 frame bits →
  26 IDRs at 64 bits each; about half of the scheduled signs actually flip.
- **Camera proof (E2E median, 300 CIF frames):** cover digest 0.51 s, Groth16
  prove 1.77 s, embed 0.50 s, extract 0.54 s, verify (stego digest + Groth16)
  1.45 s. ZKP suite: Groth16 prove 1.52–1.60 s / verify 0.91–1.01 s, proof 129 B;
  PLONK prove 21.5–23.3 s / verify 0.90–0.94 s, proof ~2.25 KB JSON, setup 3.2 s.
  The previous SHA-256 circuit (63,321 constraints) needed 3.5–4.4 s to prove.
- **Native cost scales with parsed IDRs.** Median capacity scan per IDR: 52 ms
  (352×288), 220 ms (640×480), 770 ms (1280×960); embed per carrying IDR 61 / 245 /
  891 ms. The video digest parses the same 26 carrier IDRs (1.6 / 6.4 / 22.6 s at the
  three sizes), so parsing, not Groth16, bounds throughput.
- **Quality:** lowest cover→stego PSNR-Y per case 44.03–58.68 dB, 0/27 below the
  40 dB reference; 26/30 frames change in every case; stego size equals cover size.
- **Sign statistics:** |z| ≤ 0.22 for the share of negative trailing ones.
- **Attacks (all rejected except the untouched baseline):** wrong stego key, a
  dropped IDR and a re-encode find no frame; a flipped scheduled sign gives a
  malformed or invalid proof; a flipped non-carrier sign in a carrier IDR, a flipped
  sign in a later frame, truncation, a swapped message, a camera outside the trusted
  registry and the payload replayed into another video all fail Groth16
  (`proof_invalid`).

## Distortion model (2026-10-05)

`py -3.12 -m benchmark.distortion_experiments_new` validates the model in
`benchmark/distortion_model_new.py`: one trailing-one sign flip adds
`4 * Qstep(QP)^2 * kappa` of pixel energy (kappa in [0.925, 1.057]) times a
propagation gain G, which inverts into a per-IDR cap for a target PSNR. Results in
`results/distortion_new/` (figures: `benchmark.distortion_figures_new`, used by
`doc/paper/`):

- **B, single flips** (1,200 flips: 2 x264 presets x 3 QPs x 2 frames): for all 385
  Intra4x4 luma carriers the decoder's change of the flipped block equals the exact
  residual change; exact/model energy has median 1.012. G does not depend on QP
  (ultrafast luma mean 6.6/7.4/6.0, medium 38/33/34 at I-QP 19/25/31) and is heavy
  tailed: the top 10 % of carriers cause 80–84 % of the energy. Mean luma G: 6.6
  (ultrafast, Intra16x16 only) and 35.2 (medium, Intra4x4).
- **A, benchmark frames** (810 frames of the media run): mean G 7.7 / 17.3 / 51.4 at
  352x288 / 640x480 / 1280x960 (upscaled content propagates further). Single-flip
  gains drawn at random reproduce the CIF frame-gain distribution (median 4.17 vs
  4.00 measured); individual frames are not predictable (per-frame MAE 4–7 dB).
- **C, inverse** (foreman CIF, 30 frames, 5 keys per setting): the expected-gain cap
  puts 46–70 % of frames at or above the target (median near the target); a
  95th-percentile cap reaches 80–88 % from single-flip data and 91–92 % when the
  percentile comes from benchmark frames. Caps above the candidates per IDR
  (~650 ultrafast, ~460 medium) saturate.

## Method comparison, native HD material and steganalysis (2026-10-07)

Native 720p/1080p material: `py -3.12 -m benchmark.hd_dataset_new` fetches the first 60
frames of 19 camera-captured Xiph sequences (12 at 1080p, 7 at 720p) into the git-ignored
`data/raw_hd/` (parallel HTTP ranges; the server throttles single connections).

- **Methods** (`stego_methods_new.py`, framework `stego_embed_new.py`): ours `random`
  (keyed uniform, the deployed schedule) and `low-drift` (drift tiers, native
  `--select low-drift`), and four published trailing-one methods re-implemented inside a
  sign-only channel: Kim et al. 2007, Lin et al. 2012, Wang & Ma 2018, Liao-style 2009
  (selection and mapping rules only). `test_stego_methods_new.py` checks that every
  method embeds exactly its message bits.
- **Quality** (`stego_compare_new.py --dataset cif|hd`): x264 medium Baseline, QP
  18/22/28/34, GOP 1 and 30, 64 bits per IDR and 5% of the candidates; 768 CIF and 1,824
  HD runs in `results/stego_compare/{cif,hd}.jsonl`. Low-drift beats random by 3.3–7.2 dB
  on CIF (median 4.9) and 3.3–8.0 dB on HD (median 5.9), and the best baseline by
  3.9–9.2 dB, in every setting; no method changes the bit rate.
- **Steganalysis** (`benchmark/steganalysis/`, needs PyTorch for the CNN):
  `stego_dataset_new.py` builds 486 cover/stego pairs (6 methods × 64 bits / 5% / 20%,
  27 sources split 17/3/7 by sequence); `steganalysis.evaluate` runs CAVLC features (323-D),
  SPAM-686, SRM-lite (3,978-D) with the FLD ensemble, and a Xu-Net-style CNN. At 64 bits
  per IDR every detector is at chance for every method (P_E 0.44–0.49); at 20% P_E is
  0.17–0.42. Results: `results/stego_compare/steganalysis_*.json`.
- **Native channel parameters** (`channel_options_new.py`, 8 CIF + 19 HD covers, 108 runs):
  every run extracts the exact payload, size unchanged; low-drift +3.9 dB (CIF) / +6.6 dB
  (HD) median and +6.4 / +10.8 dB worst frame over random; per-video tokens extract and give
  the master-key digest in 27/27 videos, a foreign token fails the frame check in 25/25
  pairs, a token takes 0.07 s (CIF) / 0.7 s (1080p).
- Tables and figures for the paper: `stego_compare_report_new.py`, `paper_tables_new.py`.

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
