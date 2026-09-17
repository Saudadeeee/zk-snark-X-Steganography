# Post-quantum video-ZKP completion plan

## Target claim

The eventual system shall prove, without revealing a payload or placement seed,
knowledge of a witness satisfying a **reviewed lattice relation** bound to:

```text
session_id || payload_commitment || cover_hash || stego_hash ||
positions_hash || embedding/codec policy
```

It shall not claim that a proof verifies all H.264 encoder arithmetic unless a
separate, explicitly implemented codec relation is included. ML-DSA authenticates
the control plane; ML-KEM establishes transport secrets; neither is called a ZKP.

`src/video_zkp_contract.py` now canonicalizes this public statement. It is the
single byte-level contract that a LaZer prover and verifier must consume.

## Architecture

```text
sender secret / registered public statement
          │ witness
          ▼
LaZer prover ── proof envelope ──► authenticated control sidecar
          │                              │
          │ statement_id                 │ ML-DSA signature
          ▼                              ▼
direct CAVLC video ◄── session reference ─ verifier + LaZer verifier
```

The video carries only a compact pre-embedding session reference. After the
stego bitstream and positions are final, the proof sidecar binds their hashes to
that session. This removes the proof/stego-hash circular dependency.

## Phases and non-negotiable gates

| Phase | Deliverable | Acceptance gate | Status |
|---|---|---|---|
| 0 | Claim/threat-model freeze | No use of “ZKP” for an ML-DSA receipt | Done |
| 1 | Canonical public statement | Mutation tests cover all six bindings | Done |
| 2 | Reproducible LaZer target | Pinned source, Linux x86-64 AES+AVX-512F host, demo prove+verify transcript retained | Pending hardware |
| 3 | Reviewed relation | Public registered statement, witness bounds, zero-knowledge/soundness parameters, domain separation reviewed by lattice cryptographer | Not started |
| 4 | Proof envelope | Versioned binary format, session binding, ML-DSA manifest binding, tamper and replay tests | Not started |
| 5 | Native video integration | Patched x264 direct-CAVLC encode → FFmpeg decode → extract → LaZer verify fixture | Not started |
| 6 | Streaming evaluation | p50/p95/p99 latency, bitrate/BER, packet loss/re-encode tests on live transport | Not started |
| 7 | Research evaluation | Multi-dataset/QP/GOP study, modern steganalysis, public baselines, artifact reproduction | Not started |
| 8 | External review | Cryptographic protocol review plus native codec/security review | Not started |

## Relation-design decision required before Phase 3

The proof must use an **independently known public statement**. A sidecar signer
choosing both a statement and witness proves nothing useful. The recommended
first relation is a registered-device lattice commitment: the verifier has a
registered commitment/public relation key, while the prover proves knowledge of
its short opening and binds the canonical video statement through the proof
transcript. A separate issuer/policy credential is needed if the claim is
authorization rather than device possession.

Do not implement a hash circuit or an “all CAVLC coefficients changed correctly”
relation until its witness, cost and threat model are specified. The first is a
general PQ proof-system task; the second is a large codec-verification task and
is incompatible with a real-time claim unless independently benchmarked.

## Immediate execution instructions

1. Provision a Linux x86-64 host whose Docker-visible CPU flags include
   `avx512f` and `aes`.
2. Run `python -m src.lazer_backend`; it must return `"ready": true`.
3. Build and run the pinned LaZer demo as documented in `lazer/README.md`.
4. Save the prover/verifier output, CPU model, compiler/Sage versions and image
   digest as a test fixture.
5. Only then implement Phase 3 against the exact LaZer API and generated
   relation parameters—not the disabled in-tree prototype.

## Publication gates

- **Q2-ready systems paper:** phases 0–2, 4–7, with a narrow
  PQ-authenticated-steganography claim; a lattice ZKP is not required.
- **Q1 PQ-video-ZKP claim:** all phases, a novel/reviewed relation, soundness
  and zero-knowledge analysis, independent cryptographic review, and a broad
  video/steganalysis/realtime evaluation.
