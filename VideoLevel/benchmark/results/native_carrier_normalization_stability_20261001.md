# Native CAVLC carrier stability probe (2026-10-01)

## Question

Can the existing x264 direct-CAVLC encoder produce a preliminary video with
placeholder payload bits, then produce the same normalized-video digest and
carrier positions after replacing the payload with a different equal-length
value during a second encode? This matters because the intended proof statement
must be formed before embedding, while the verifier sees only the final video.

## Controlled experiment

The patched x264 at commit `0480cb05fa188d37ae87e8f4fd8f1aea3711f7ee`
encoded the same `data/raw/akiyo_cif.y4m` cover three times with the same
native-adapter settings: 300 frames, 352x288, 8-bit H.264 Constrained
Baseline, CRF 23, one thread, IDR until the 120-bit `ZKVP` envelope was fully
embedded. Runs A and A-repeat embedded application byte `a5`; run B embedded
`5a`. Both envelopes have 15 bytes and 120 bits, including header and CRC32.
The script `benchmark/native_carrier_normalization_probe.py` blindly recovered
the payload and ordered positions from each video, then called the existing
`canonical_video_sha256` implementation on those recovered positions. It did
not use encoder-side position metadata.

| Run | App byte | H.264 bytes | Raw SHA-256 | Carrier count | Position hash | Canonical video SHA-256 |
| --- | --- | ---: | --- | ---: | --- | --- |
| A | `a5` | 718,868 | `a72c308fcefbeee75fd54a1e1eb53f42f801ba664b03710ba01cfe06ce38931e` | 120 | `5e9c0dddc04efbb3b0910903b9c1b4f81c1968f6cc25dfb38ae824f7a4b9a77b` | `f84932d134ca87a1071811f61672eb636540318e039d04b44c7bf1656a41ecc7` |
| A-repeat | `a5` | 718,868 | `a72c308fcefbeee75fd54a1e1eb53f42f801ba664b03710ba01cfe06ce38931e` | 120 | same as A | same as A |
| B | `5a` | 718,829 | `7ef2087eb0f65265696797f63634e93c983548072d8d2755e860a1d6ee98b0ff` | 120 | `857caace904e100f457fdaec1ab582d4e0f8a57c7bd2168a01cbe11f73713812` | `e3ced230e52bbde37ed56d6158ef1244239ec5c40811c5380657f7ef74ea70b2` |

The two `a5` encodes were byte-for-byte identical. Changing only the
equal-length application byte changed the ordered carrier list from index 97
(zero based) and changed the normalized digest. This is a measured counterexample
to using the current *second complete x264 encode* as a drop-in way to insert a
proof after computing its video context from a placeholder encode. The result
does not prove that all covers or encodes diverge, but one counterexample is
enough to reject that method as a general invariant.

There is a second, source-visible issue even when carrier positions remain
stable: the native hook increases the absolute coefficient magnitude by one
on a parity mismatch. The legacy `even_down` normalizer rounds a
magnitude-LSB carrier **down** to even. A source odd magnitude such as 5 can be
written as 6 for a zero bit, and those values normalize to 4 and 6
respectively. That legacy normalizer does not erase every native carrier
mutation. This remains a limitation of the original encoder-inserted payload
profile.

## Post-encode patch experiment

The project `BitstreamReconstructor` was first asked to replace the 120-bit
`a5` envelope in run A with the equal-length `5a` envelope. Twenty-four CAVLC
blocks needed a changed parity. Its fixed-length patcher applied only one;
23 were skipped, mostly because modified codewords changed length by one bit.
The resulting file still decoded 300 frames but blind extraction failed its
CRC32 check. This measured failure explains why the existing patcher cannot
simply finalize an arbitrary proof after encoding.

The separate research script `benchmark/native_variable_length_patch_probe.py`
then replaced whole CAVLC codewords and repacked RBSP trailing alignment. An
initial version imitated the encoder's always-increase rule: it recovered
`5a` blindly and kept the carrier positions, but the old normalized digest
changed from `f84932d1...6a41ecc7` to `b01ef112...87ae6a64`.

The current prototype uses a **new, explicitly named**
`native_odd_anchor_v1` profile. It groups eligible magnitudes into disjoint
pairs `(5,6), (7,8), ...`; both values normalize to the odd member. A
post-encode parity change stays within that pair: odd to even increases
magnitude by one; even to odd decreases magnitude by one. This profile has a
separate hash domain and rejects magnitudes below five. It does not silently
change the legacy `even_down` profile.

| Gate on Akiyo run A, post-encode `a5` → `5a` | Observed |
| --- | --- |
| CAVLC blocks changed | 24 blocks in 2 IDR NALs |
| Individual codeword length change | −1 to +1 bit |
| Output H.264 | 718,868 bytes; SHA-256 `eb0983e229fa25ae9cca5f2823ef8f95a353b3ef3d5fc98f49674c9930cf05b5` |
| Blind payload | `5a`, exact match; 120 carrier positions unchanged |
| `native_odd_anchor_v1` normalized digest, before and after | `7ffe2d497dceb7204a3ee59f813856d331f7bfe7515131e5a4ac6cbe3bb6ec86` in both videos |
| Decoder check | `ffprobe`: Constrained Baseline, 352x288, 300 frames; FFmpeg decoded with exit 0 and no error output |
| Canonicalization unit tests | 12/12 passed, including pair, eligibility, and overlapping-frame-range checks |

This is evidence that a two-phase path can preserve a normalized-video digest
for one small native clip. It is not yet a protocol guarantee: the prototype
is Python, uses internal CAVLC encoding functions, and has only been tested
with a 15-byte transport envelope. It needs strict fail-closed validation,
more video/bit-pattern cases, target relation integration, and proof-sized
capacity/time measurements. The final verifier must pin the new carrier
profile; a `ZKVP` CRC32 header alone does not identify or authenticate it.

The generated videos were kept in the system temporary directory
`zkstego-native-normalization-20261001`, outside Git. This probe is a
diagnostic, not a security or realtime benchmark.
