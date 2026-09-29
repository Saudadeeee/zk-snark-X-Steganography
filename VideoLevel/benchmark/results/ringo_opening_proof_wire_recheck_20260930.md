# Ringo opening proof wire-format recheck (2026-09-30)

## Scope

Measured a complete serialized Buckler proof for the existing 32-byte payload
opening research circuit. The isolated `proof_codec.go` probe provides strict
JSON and schema-pinned binary codecs; neither is the application ZKP backend or
a production proof format.

Command, from `benchmark/ringo_application_probe`:

```powershell
go test -run '^TestOpeningRelationAndCapacityProbe$' -count=1 -v .
```

## Observed run

- Compile: 26.46 ms
- Prove: 300.89 ms
- Verify: 126.79 ms
- JSON encode: 65.21 ms
- JSON decode: 145.78 ms
- Binary encode: 46.21 ms
- Binary decode: 100.02 ms
- Verify after decoding the serialized proof: accepted
- Complete JSON proof: **2,710,137 bytes**
- Gzip JSON at `BestCompression`: **1,281,918 bytes**
- Schema-pinned binary proof: **1,653,727 bytes**
- `JindoParams.Size()/8` estimate printed by the probe: **550,249 bytes**
- JSON / estimate: **4.92x**
- Binary / estimate: **3.00x**
- Test process reported 5.01 s for the test and 6.33 s package time.

This is one local run. The proof is randomized, so its JSON length changes
slightly between runs; preceding runs produced 2,710,348, 2,710,642,
2,710,535, 2,710,571, and 2,710,141 bytes. The gzip measurement comes from the
last proof sample; it reduced that JSON by about 52.7%. Binary field encoding
is about 64.7% of JSON size and 29.0% larger than gzip in this run. Both
compressed representations remain far above the 10,779-byte carrier budget.
The ratio is approximately 4.9x for JSON and 3.0x for binary versus the
Jindo estimate. The codecs reject empty,
truncated, whitespace-altered, extra-value, empty-proof and otherwise
non-canonical JSON encodings. The application verifier wrapper also converts
dependency panics on malformed proof shapes into rejection errors.
The existing circuit controls also rejected changed context, changed public
commitment, non-Boolean bits, nonzero payload tail, and randomness outside the
configured bound.

## Interpretation and limits

The earlier 550,249-byte figure was an estimate, not an encoded proof size.
The uncompressed JSON artifact is about 251 times and the schema-pinned binary
artifact about 153 times the 10,779-byte carrier budget reported for the
earlier Coastguard transport; gzip was about 119 times that budget. None of
these representations fits that carrier. This says nothing universal about
longer or higher-capacity videos.

There is also a raw-capacity upper bound from the retained 3,000-frame
`coastguard_cif_q22_g1_3000f.h264` scan:
`benchmark/results/streaming_raw_capacity_coastguard_3000f_20260927.json`
records 4,332,560 raw-safe bits, or 541,570 bytes, before patchability,
blind-extraction and quality losses. The binary proof plus the 16-byte carrier
framing is 1,653,743 bytes, **3.05 times even that raw upper bound**. Thus this
exact 3,000-frame cover cannot carry the current Ringo proof format even if
every raw-safe coefficient were patchable. This is an upper-bound comparison;
no new video scan or embedding was needed for that conclusion.

No video embedding/extraction was run with this proof. Memory and repeated-run
latency distributions were not measured. The relation, CRS, Ringo implementation
and parameters remain research-only; the proof codec and this test do not
establish independent cryptographic security review or production suitability.
