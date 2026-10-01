# Lattice ZK Prototype: Blind H.264 Capacity Check (2026-10-01)

## Purpose

Measure whether the repository's existing research-only `LatticeZkProof`
artifact can fit in the current no-sidecar blind CAVLC channel on a real
H.264 video. This is a capacity feasibility check, not evidence that the
prototype is a secure application ZK system.

## Environment and input

- OS: Windows 11 Pro, build `10.0.26100`
- CPU: 12th Gen Intel Core i7-12700H
- RAM: 23.63 GiB installed; process RSS was not measured
- Python: 3.12.10
- Input: `data/encoded/foreman_cif_g8_300f_b800k.h264`
- Stream: H.264 Constrained Baseline, 352x288 (CIF), 20 fps
- Clip: 300 decoded frames; elementary H.264 has no reported duration/PTS.
  `ffprobe` reported nominal `r_frame_rate=20/1`, guessed
  `avg_frame_rate=25/1`; blind analysis found 39 IDR frames
- Carrier policy: stable candidates, sign-bit carriers, patchability required,
  one modification per block, patchability headroom 64

## Measured proof and carrier sizes

The prototype generated and locally verified a `LatticeZkProof` for the test
message `payload for H264 test` and a 32-byte test witness key:

- Canonical JSON proof: **131,692 bytes**
- Self-framed blind envelope: **131,706 bytes** (header + CRC: 14 bytes)
- Required carrier capacity: **1,053,648 bits**
- Proof create + JSON serialization: **365.54 ms** in one run
- Prototype verification: returned `True`; verification time was not timed

The same video's blind analysis reported:

- Raw safe positions: **101,842 bits**
- Stable candidate count before final intersection: **5,028**
- Patchable stable carriers actually selected: **2,941 bits**
- IDR count: **39**

The proof needs about **10.35x** the raw-safe capacity and **358.3x** the
currently selected stable/patchable carrier count. At the measured operating
point, the framed proof cannot be carried in this clip.

## Real embed attempt

`embed_blind_video_payload` was called with the serialized proof bytes and
the input video above. The call ran the real H.264 analysis/position derivation
and rejected the payload:

```text
insufficient stable patchable capacity: need 1053648 carriers, got 2941
```

The measured capacity/embed attempt took **83.65 s**. The requested output
file did **not** exist after rejection. This exceeds the nominal 12–15 s frame
budget implied by the reported 20–25 fps rates (about **5.6–7.0x** slower),
although the elementary stream has no timestamps from which to establish exact
playback duration. RSS and decode quality were not measured because no stego
video was produced.

## Reproduction outline

```python
proof = LatticeZkProof.create(b"payload for H264 test", b"K" * 32)
proof_bytes = json.dumps(
    proof.to_dict(), sort_keys=True, separators=(",", ":")
).encode()

embed_blind_video_payload(
    "data/encoded/foreman_cif_g8_300f_b800k.h264",
    temporary_output_path,
    proof_bytes,
    b"K" * 32,
    BlindOperatingContract(
        version="stable-carriers-video-only-v1",
        signbit_only=True,
        require_bitstream_patchable=True,
        patchability_headroom=64,
        max_modifications_per_block=1,
        stable_carriers_only=True,
    ),
)
```

The capacity call used `derive_blind_positions_operating_contract` with the
same contract and a requested count of `10**9`; it returned all **2,941**
available positions. The real embed attempt used a temporary output directory
and cleaned it after confirming no output was created.

## Interpretation and limitations

`LatticeZkProof` is explicitly experimental and disabled in the public video
API. This result does not authorize enabling it: its relation is a prototype
bounded-SIS preimage, not the reviewed application relation tying payload
opening, session, video context, and the exact residual carrier transcript.
The video channel also rejected it at measured capacity even before any
cryptographic certification, full verifier API, multi-video benchmark, or
re-encoding/quality test. A smaller, externally reviewed proof construction
or a substantially larger carrier budget is needed; do not infer this system
is usable for in-band ZK proof transport or realtime from this experiment.
