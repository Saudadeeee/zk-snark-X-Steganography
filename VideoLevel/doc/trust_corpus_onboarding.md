# Upgrade-v2 Trust Corpus Onboarding

This playbook explains how to add a real external/public corpus for the
Upgrade-v2 trust evidence gate without changing the frozen H.264/CAVLC paper
baseline.

The current repository has a small external seed corpus:

- local registered corpus: `22/22` files available,
- external registered files: `2`,
- `external_public_dataset=true`,
- Section 45 `promotion_ready=true` for the seed-corpus contract,
- Section 46 `seed_surface_ready=true` but `all_product_ready=false`.

Do not treat this as broad public-dataset evidence. Broad claims require a
larger and more diverse external corpus with source, license, file metadata,
and matching SHA-256 hashes for every registered file.

## Step 1: Place The External Files

Put externally sourced evaluation files outside tracked source code. A practical
local layout is:

```text
data/external/trust_corpus/
|-- sample_001.h264
|-- sample_002.h264
`-- sample_003.h264
```

Do not commit the external videos unless their license explicitly allows it.
The manifest can be committed; the videos usually should not.

## Step 2: Register A File

Use the corpus helper to produce a ready-to-paste manifest entry:

```bash
py -3.12 -m benchmark.trust_corpus register-file ^
  --id sample-001 ^
  --path data/external/trust_corpus/sample_001.h264 ^
  --source-uri https://example.org/dataset ^
  --license CC-BY-4.0 ^
  --codec h264 ^
  --container raw_h264 ^
  --frame-count 300 ^
  --resolution 352x288 ^
  --group external_public_video ^
  --source "Example Dataset"
```

Append the generated entry to `benchmark/trust_corpus_manifest.json`.

## Step 3: Validate The Manifest

Run:

```bash
py -3.12 -m benchmark.trust_corpus
```

The validation report is written to:

```text
benchmark/results/trust_corpus_validation.json
```

Promotion remains blocked if:

- `external_public_dataset=false`,
- no external files are registered,
- an external file is missing locally,
- a SHA-256 hash does not match,
- source/license/codec/container/resolution/frame-count metadata is missing.

## Step 4: Rerun Evidence

After corpus validation is clean, rerun:

```bash
py -3.12 -m benchmark.safe_benchmark_runner --sections 44 45
```

Section 45 decides whether the evidence gates pass for the current claim scope.
Section 46 decides whether a feature may be described as product-ready.

## Step 5: Keep Claims Narrow

Even with an external corpus, claim only what was measured:

- fingerprint registry: content identity / canonical asset matching,
- watermark receipt: detector decision on the declared transform matrix,
- C2PA root: provenance anchoring, not robust watermarking,
- attestation: signed model/media bundle, not full ZKML generation proof.

Do not mix these results into the frozen fragile CAVLC embedding tables.
