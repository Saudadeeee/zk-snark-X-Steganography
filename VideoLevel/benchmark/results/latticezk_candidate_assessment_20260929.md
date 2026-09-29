# LatticeZK candidate assessment (2026-09-29)

## Decision

Do not integrate or build `yarongvili1/latticezk` as the application's lattice-ZK backend in its current form. It is a useful research reference, but it does not currently provide the verifier-pinned video/payload relation, security evidence, or an in-video proof layout this project requires. This is a source/API and capacity assessment; no third-party code was cloned, built, or executed.

## Candidate and protocol fit

The [upstream README](https://github.com/yarongvili1/latticezk#latticezk) labels the repository experimental research code. It implements the Baum et al. arithmetic-circuit protocol over `Z_(2^w)` for `w` in `{8,16,32}`, advertises CPU AVX/OpenMP and optional CUDA, and says its [tests](https://github.com/yarongvili1/latticezk#running-tests) cover only some CPU matrix operations. Its example uses `lambda=80` and reports 1.3 seconds single-threaded / 0.6 seconds multi-threaded on an i7-10875H. These are upstream demo times, not measurements on this project or proof-generation times for a video relation.

Source review found that the default proof carries dimensions and matrices `A,T,W,C,Z`; verification checks an algebraic identity and norm bound, while challenge `C` is hash-derived from the transcript. The current API constructs the verifier from proof-carried parameters rather than resolving a project-pinned relation and policy. It has no application interface that pins a canonical video commitment, payload-commitment opening, codec policy, and carrier-selection profile independently at the verifier. Those bindings cannot be assumed merely because the underlying work is described as an arithmetic-circuit protocol.

The cited [Baum et al. CRYPTO 2018 paper](https://www.iacr.org/archive/crypto2018/10993459/10993459.pdf) gives an interactive honest-verifier argument over a prime field. Its guarantees do not automatically establish soundness, knowledge soundness, or zero knowledge for this repository's `Z_(2^w)` adaptation and hash-derived non-interactive challenge. The repository provides neither a concrete security estimate for that adaptation nor an application-level protocol audit.

This candidate is not blocked by AVX-512 on the current host: its CPU defaults target native/SSE/AES/FMA and do not require AVX-512. That only addresses portability; it does not establish application relation or proof suitability.

## Capacity comparison

The current Akiyo measurement in [`sec2_capacity_data.json`](sec2_capacity_data.json) reports 1,232 operating bits and 2,000 patchable-usable bits. The candidate default dimensions (`r=100`, `v=l=3000`, `n=100`) carry matrices with approximately 1.21 million scalar entries across `A,T,W,C,Z`. A compact 32-bit/scalar encoding would therefore be a **derived estimate** of 38,720,000 bits (about 4.84 MB): 31,429 times the operating capacity and 19,360 times the patchable capacity. If `C` were omitted because the verifier regenerates it, the remaining 29,120,000-bit estimate is 23,636 / 14,560 times those respective capacities. Naive 64-bit encoding doubles the size. These are estimates from dimensions, not measured serialized proof sizes; the candidate supplies no wire serializer or proof-size measurement. Akiyo is one measured carrier, not a universal upper bound for all videos.

Separately, [Practical Lattice-Based Zero-Knowledge Proofs](https://eprint.iacr.org/2020/1183.pdf) reports approximately-128-bit-parameterized proof sizes of 11.0 KB for 32-bit integer addition and 14.5 KB for 32-bit integer multiplication. These narrow relations are not the application's video/payload binding, but already exceed Akiyo's operating capacity by about 73x and 96x respectively. Its reported proof timings are medians of 500 runs on a 3.5 GHz Skylake and are not directly comparable to this host or the full video pipeline.

## Consequence and next gate

Reject this candidate for integration, not because its CPU demo cannot run, but because its current API does not bind the required application statement and its demonstrated default proof layout cannot fit the measured carrier. Do not hide proof fields in a sidecar, substitute ML-DSA, or treat a transcript hash as a ZKP to bypass these gaps.

Reconsider only after a design specifies a verifier-pinned relation and canonical video commitment, provides an independently reviewed security argument for the actual non-interactive instantiation, and produces a measured serialized proof that fits an explicitly benchmarked carrier.
