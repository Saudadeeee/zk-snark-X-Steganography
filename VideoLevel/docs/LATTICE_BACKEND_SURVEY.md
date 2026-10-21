# Lattice ZK backend survey (2026-09-27 to 2026-10-12)

Why the system implements BDLOP itself instead of adopting an existing
lattice proof system. Each candidate was checked against four gates:

1. **Zero knowledge** in the construction and code actually used.
2. **Application relation**: the verifier-pinned video/session/payload
   statement can be expressed and bound into the transcript.
3. **Runnable here**: complete prove/verify on Windows x86-64 without AVX-512
   (Intel i7-12700H), or in a Linux container on it.
4. **Fits the carrier**: proof plus framing fits measured, quality-validated
   CAVLC capacity (tens of KB on 1 000–3 000-frame CIF clips).

The detailed per-candidate notes (source pins, commands, logs) were consolidated
into this file on 2026-10-19; the originals remain in git history up to commit
`07c02d9`.

| Candidate | Source | Decisive finding | Gate failed |
|---|---|---|---|
| LaZer | lazer-crypto/lazer, pinned `10eafec` | Requires Linux x86-64 with AVX-512 and AES; the host CPU has AVX2 only; preflight (`src/legacy/lazer_backend.py`) fails closed | 3 |
| LaZer Toolkit (ZK LaBRADOR) | ePrint 2026/1289 | Has a ZK variant, but the only ZK statement in source is a Merkle-membership example; not built here; same AVX-512 requirement | 2, 3 |
| LNP22 (Go, KarpelesLab/lnp22 v0.1.1) | KarpelesLab/lnp22 v0.1.1 (local context-binding probe removed in the Oct 2026 cleanup; in git history) | Verifier accepts a proof for `s[0]=2` with `Beta=1` and a non-bit payload-opening witness (the probe's dependency-assessment test); exact bounds are not enforced | 1/soundness |
| ISW21 lattice-zksnark | `48cb4cd` (local R1CS opening smoke test removed in the Oct 2026 cleanup; in git history) | Built and ran (toy 32-byte relation, 23 907-byte envelope carried through H.264). Designated verifier; its knowledge-based linear-only LWE assumption is broken by quantum oblivious sampling (LUNA; ePrint 2024/030); statistical ZK only 2^-40; upstream needed two local bug fixes | 1 (assumption), 4 at 300 frames |
| ePrint 2025/2099 (DV zkSNARK from MSIS) | crypolover1998/LatticeBased-Dv-zkSNARK `9bc41a6` | Strongest theorem (adaptive knowledge soundness in ROM), but code predates the paper and simulates only `lambda=1` without accept/reject; 20.75 KB proof, 1.3 GB CRS | 3 |
| LUNA | ePrint 2022/1690, yassimert/LUNA | Repository implements only the HGSW encryption component, not the prover/verifier; soundness non-adaptive | 3 |
| LaBRADOR (C, Rust ports, Lazarus) | ePrint 2022/1341 | Paper disables ZK in its size results (masking shim left for later); C code needs AVX-512; Rust R1CS reductions incomplete | 1, 3 |
| RoKoko | ePrint 2026/575 | Knowledge soundness only; final folded witness is verifier-readable; relies on vanishing-SIS; 112 KB proof | 1, 4 |
| SALSAA | ePrint 2025/2124 | Paper proves correctness and knowledge soundness only; prover sends the final folded witness in the clear; 979 KB proof (73 KB folding only) | 1, 4 |
| Symphony | ASIACRYPT 2026 | Framework only; concrete instantiation left to future work; SNARK definition has no ZK property | 1, 3 |
| LatticeFold | ePrint 2024/257, NethermindEth/latticefold `15cc045` | Folding scheme, proof-of-concept code, not a standalone ZK prover/verifier | 1, 3 |
| Jolt + Akita | a16z/jolt | Akita PCS backend is clear-only (no ZK); 65–80 KB reported | 1, 4 |
| Ringo-SNARK / Buckler | sp301415/ringo-snark | Ran a payload-opening-shaped probe; binary proof about 1.65 MB | 4 |
| latticezk (yarongvili1) | Baum et al. CRYPTO 2018 over `Z_(2^w)` | Experimental; interactive HVZK argument whose guarantees do not carry over directly to the FS variant used; default dimensions far exceed capacity | 2, 4 |
| Practical sublinear R1CS (ePrint 2022/1048) | paper only | ZK with a Fiat–Shamir variant, but no implementation; 10.79 MB at 2^24 constraints | 3, 4 |
| In-tree SIS prototype (`src/registry/lattice_pq.py`) | this repository | Statement chosen by the prover; 131 692-byte JSON proof; kept only as a fail-closed regression fixture | 2, 4 |

## Conclusion

No available implementation passed all four gates. The relation the system
needs (knowledge of an opening of one lattice commitment, bound to a
verifier-built statement) is small enough that the published BDLOP opening
proof covers it directly. Implementing it from the paper gave:

- zero knowledge and knowledge soundness arguable from published theorems
  (`docs/LATTICE_ZK_BDLOP_SPEC.md`, Section 4);
- portable pure-Python code that runs on the target host;
- a 7 520-byte proof (`bdlop-open-128-v1`; 8 096 bytes with v2) that has been carried through H.264 and verified from the
  video alone (`docs/LATTICE_ZK_BDLOP_PLAN.md`, Section 7).

The cost is that the code is self-implemented and unaudited, and soundness is
relaxed rather than exact.
