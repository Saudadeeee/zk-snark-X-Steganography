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

For an operational realtime in-band payload path, it can insert an opaque,
fragmented chunk in an H.264 `user_data_unregistered` SEI before every IDR:

```powershell
Get-Content input.h264 -AsByteStream | .\native\build\Release\zkstego_annexb_relay.exe --sei-payload-hex 0123456789abcdef --chunk-bytes 8 > output.h264
```

This SEI mode has no decoded-pixel quality cost and the native extractor can
recover the chunk sequence, but SEI is **not covert steganography**. It is a
deliberately visible metadata carrier for realtime authenticated transport.

## Selected encoder: x264

The optional `zkstego_x264` target provides a native low-latency I420 encoder
adapter. Its enforced profile is x264 `ultrafast` + `zerolatency`, H.264
Baseline/CAVLC, AUD/Annex-B output, no B-frames, and a fixed keyframe interval.

Install the x264 development headers/library, then build it explicitly:

```powershell
cmake -S native -B native/build-x264 -DZKS_WITH_X264=ON
cmake --build native/build-x264 --config Release
```

The adapter is intentionally separate from the CAVLC mutator: libx264's public
API does not expose a safe residual-coefficient hook. A real compressed-domain
embedding backend must be integrated into a reviewed x264 fork before the
relay is allowed to advertise stego embedding.
