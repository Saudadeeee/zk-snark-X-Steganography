# Native Live Path

`zkstego_live` is the C17 realtime transport core. It parses H.264 Annex-B
incrementally, requires AUD-delimited access units, and provides an IDR-only
payload scheduler. It has no whole-file cache and no Python dependency.

Build and test the portable relay:

```powershell
cmake -S native -B native/build
cmake --build native/build --config Release
ctest --test-dir native/build -C Release --output-on-failure
```

`zkstego_annexb_relay` reads Annex-B from stdin and writes complete access
units to stdout. It is deliberately a transport-only relay until a native
CAVLC mutator is linked; it never pretends to hide a payload while forwarding
unmodified video.

The relay still supports an opaque, fragmented H.264 `user_data_unregistered`
SEI chunk for diagnostic/authentication interoperability:

```powershell
Get-Content input.h264 -AsByteStream | .\native\build\Release\zkstego_annexb_relay.exe --sei-payload-hex 0123456789abcdef --chunk-bytes 8 > output.h264
```

This SEI mode has no decoded-pixel quality cost and the native extractor can
recover the chunk sequence, but it is **not** the steganographic carrier and
must not be enabled for a direct-video stego deployment. It remains only as a
visible metadata diagnostic path.

## Direct-video CAVLC carrier

`zkstego_cavlc_direct` is the native carrier primitive for the actual stego
path. It embeds one payload bit in the magnitude parity of the highest-
frequency eligible AC coefficient in a 4x4 CAVLC block. The rule is deliberately
conservative:

- it never uses DC or creates/removes a non-zero coefficient;
- it accepts only original magnitudes of 4 or more, and changes a selected
  coefficient by at most one;
- it keeps the coefficient eligible after the edit, so the decoder can apply
  the identical selection rule; and
- it limits the primitive to one edit per 4x4 block. The x264 fork imposes the
  stricter realtime policy of one edit per macroblock.

The primitive is tested independently, but it is not wired into the generic
Annex-B relay: direct embedding must happen inside the encoder before reference
reconstruction. Editing an already-encoded CAVLC bitstream would let encoder
and decoder derive different reference frames and can cause inter-frame drift.

## Selected encoder: x264

The optional `zkstego_x264` target provides a native low-latency I420 encoder
adapter. Its enforced profile is x264 `ultrafast` + `zerolatency`, H.264
Baseline/CAVLC, AUD/Annex-B output, no B-frames, and a fixed keyframe interval.

Install the x264 development headers/library, then build it explicitly:

```powershell
cmake -S native -B native/build-x264 -DZKS_WITH_X264=ON
cmake --build native/build-x264 --config Release
```

The adapter is intentionally separate from the CAVLC mutator: stock libx264's
public API does not expose a residual-coefficient hook. The direct backend
therefore requires a reviewed x264 fork which applies the carrier after
quantization and before inverse transform/reconstruction, then limits its rate
to one edit per eligible I4x4 macroblock. While a direct payload remains, the
adapter forces IDR pictures; it resumes the configured GOP after the payload
is complete. This keeps the current blind extractor on IDR/CAVLC slices, but
can significantly increase bitrate and is not a realtime performance claim.
This placement keeps encoder and decoder reference frames synchronized. Do not
substitute the SEI relay for that fork.

For the optional Y4M-to-H.264 demonstration CLI, select exactly one binary
payload source. `--payload-file` avoids shell argument limits for larger proof-
sized artifacts; the CLI reads the file into memory, with a maximum length of
`INT_MAX / 8` bytes. `--payload-hex` remains convenient for small fixtures.
These options transport opaque bytes only and do not assert that they form a
valid ZK proof:

```powershell
native\build-x264\zkstego_x264_y4m.exe `
  --input-y4m data\raw\akiyo_cif.y4m `
  --output akiyo_stego.h264 `
  --payload-file proof.bin
```

Capacity failure leaves no published output. The real 33,803-byte LNP22 probe
artifact did not fit in a 300-frame Akiyo CIF run; see
[`benchmark/results/native_payload_capacity_probe_20260930.md`](../benchmark/results/native_payload_capacity_probe_20260930.md).

Because x264 is GPL-2.0-or-later (unless separately commercially licensed), a
distributed binary linked with a modified x264 must meet the applicable x264
licensing obligations.
