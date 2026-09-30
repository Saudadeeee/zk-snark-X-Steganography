# Target relation for an in-video lattice ZK proof (draft v0.1)

## Status and scope

This document corrects the *target* application relation. It is a design
specification only: the current repository does not implement this relation,
does not generate or verify a lattice-ZK proof for it, and must not advertise
this draft as a security proof. A proof backend, concrete commitment
parameters, constraint encoding, independent cryptographic review, and
video-only end-to-end test are still required.

The relation below proves knowledge of a hidden payload opening bound to one
canonicalized H.264 video, session challenge, carrier schedule, and codec
policy. It does **not**, by itself, prove that the payload is true, that the
video came from a camera, or that a hidden payload describes what the video
depicts. Such application semantics must be a verifier-pinned predicate in a
versioned registry relation, and that predicate must be included in the
proved relation rather than merely named in the transcript.

## Canonical public instance

The verifier obtains its trust roots and suite configuration from local
configuration/registry, never from prover-chosen proof fields. It parses the
in-band envelope and independently derives the rest from the received video.

Let the public instance be:

```text
X = (
  protocol_version,
  relation_id,
  parameter_id,
  registry_root,
  registry_epoch,
  session_challenge,
  codec_policy_id,
  carrier_profile_id,
  payload_length,
  carrier_count,
  positions_hash,
  video_commitment,
  payload_commitment
)
```

Requirements:

- `protocol_version`, `relation_id`, `parameter_id`, codec policy, carrier
  profile, registry root and minimum epoch are verifier-pinned. The verifier
  rejects an unknown or revoked value.
- `session_challenge` is a fresh 32-byte verifier-issued challenge for an
  online session, or a registry-issued one-time token for an offline workflow.
  A prover-generated nonce alone does not prevent replay. Offline verification
  needs state to record used tokens if replay rejection is required.
- `codec_policy_id` fixes H.264 Baseline, CAVLC, supported NAL/frame policy,
  and all accepted syntax restrictions. `carrier_profile_id` fixes the
  deterministic eligibility, ordering, mutation, extraction and
  normalization algorithms, including their versions. This draft's carrier
  profile is the sign-only `t1_sign_flip` strategy: exactly one payload bit per
  carrier, a one-bit coefficient sign change, and no other coefficient
  mutation. Other strategies require a distinct version/profile and separate
  normalization tests.
- `carrier_count` is fixed by the registered wire-size profile, not selected
  by the prover. If the selected proof cannot fit that profile, embedding
  fails before proof generation or output publication.
- `positions_hash` hashes the canonical ordered positions independently
  reconstructed by the verifier from the video and pinned carrier profile.
  It is not trusted from a manifest or sidecar.
- `video_commitment` is recomputed from the video as described below. A raw
  `cover_hash` is not used: blind verification has no original cover video to
  compare against.
- `payload_commitment` is the public lattice commitment in the envelope and
  proof statement. It is not accepted as meaningful solely because the prover
  included it; the ZK relation must prove its opening and any registry-pinned
  application predicate.

For v0.1, canonical encoding of `X` is fixed-width concatenation in the order
shown above: `protocol_version` is `uint16_be`; each of `relation_id`,
`parameter_id`, `registry_root`, `session_challenge`, `codec_policy_id`,
`carrier_profile_id`, `positions_hash`, and `video_commitment` is exactly 32
raw bytes; `registry_epoch` is `uint64_be`; `payload_length` is `uint32_be`;
`carrier_count` is `uint64_be`; `payload_commitment` has the fixed byte length
registered by `parameter_id`. Hex strings in JSON are display encodings only;
the proof transcript consumes the raw bytes. Reject overflow, truncation,
unknown IDs, and non-canonical encodings.

The statement ID is:

```text
statement_id = SHA3-256(
  "zkstego/video-zk/statement/v1\0" || CanonicalEncode(X)
)
```

The hash is an identifier/transcript input, not a proof and not a substitute
for the verifier checking every field against its own trust configuration.

## Non-circular video commitment and blind carrier framing

The registered envelope profile has a fixed maximum byte length for a given
`parameter_id`; any unused proof bytes are canonical zero padding and are
included in that fixed length. The verifier scans the H.264 bitstream using
the pinned profile, extracts the fixed-size envelope from the deterministic
ordered carrier prefix, and rejects missing/duplicate/invalid carriers,
unsupported syntax, or insufficient capacity. No manifest is needed to find
the proof or its carrier positions. For this sign-only profile,
`carrier_count = 8 * envelope_length_bytes`; `P` consists of exactly that many
ordered sign carriers.

For the sign-flip carrier profile, each selected carrier is an already-existing
CAVLC-safe trailing-one sign whose coefficient magnitude remains one; only
its sign encodes the bit. Let `P` be the deterministic ordered list of all
carriers reserved by the fixed-size envelope. Define:

```text
Normalize(S, P):
  parse H.264 Baseline/CAVLC stream S without re-encoding;
  preserve all non-carrier NAL/RBSP syntax and residual coefficients;
  replace each carrier sign with its canonical positive sign;
  serialize affected residual blocks with the versioned canonical block form;
  reject if any P entry is absent, ambiguous, or not eligible.

positions_hash = SHA-256(
  "zkstego/video-zk/carriers/v1\0" || uint64_be(|P|) ||
  for each (macroblock, block, coefficient) in P order:
    int64_be(macroblock) || int64_be(block) || int64_be(coefficient)
)

canonical_digest = SHA-256(
  "zkstego/canonical-h264-carrier-normalization/v1\0" ||
  CanonicalHashV1NALStream(S, P)
)
video_commitment = SHA-256(
  "zkstego/video-zk/video-commitment/v1\0" || raw_bytes(canonical_digest)
)
```

`CanonicalHashV1NALStream` is a streaming byte encoding, so a full normalized
video need not be allocated:

1. For every NAL in order, append `"NAL" || 0x00 || uint64_be(nal_index) ||
   uint8(nal_unit_type) || uint8(forbidden_zero_bit) || uint8(nal_ref_idc) ||
   uint8(start_code_size)`.
2. For each non-IDR NAL, append `"RAW" || 0x00 || uint64_be(rbsp_byte_length) ||
   rbsp_bytes` exactly.
3. For each IDR NAL without carrier blocks, use the same `RAW` record. For an
   IDR with carriers, preserve all RBSP syntax outside affected CAVLC block
   codewords. Encode each unchanged bit segment as
   `"BITS" || 0x00 || uint64_be(bit_length) || pack_bits_msb_first(segment)`; the
   final byte is zero-padded and the exact `bit_length` disambiguates padding.
4. At each affected block boundary, append
   `"BLOCK" || 0x00 || uint64_be(macroblock) || uint32_be(block) ||
   uint32_be(coefficient_count) || int64_be(level[0]) || ...` for the complete
   coefficient vector after canonicalizing all carriers in that block. For a
   sign carrier, require `abs(level)==1` and canonicalize it to `+1`. For a
   magnitude-LSB carrier, canonicalize the magnitude to the next even value
   (using magnitude 2 when the value is +1 or -1) and preserve sign. Any invalid,
   duplicate, missing, multiply mapped, or out-of-range carrier rejects.
5. After the last affected block, encode the remaining RBSP syntax bits as a
   `BITS` record.

The current `src/video_canonicalization.py` implements this v1 stream for a
caller-supplied position list. The target adds the outer `video_commitment`
domain and requires the verifier to derive `P` itself. `P` and its fixed count
are chosen from the registered profile before proof creation, so normalization
does not depend on proof bit values; this breaks the apparent video-hash/proof
cycle. The verifier recomputes both hashes from the received video. This binds
the proof to normalized H.264 syntax, not to pixels after arbitrary
re-encoding. Remux/transcode robustness is not promised unless separately
specified and measured.

The low-level carrier-normalized digest helper still accepts caller-supplied
`P`. A separate `verify_video_zkp_context_binding_video_only()` helper now
derives `P` from the video using verifier-provided stable-carrier config and a
seed deterministically derived from the verifier-pinned session challenge.
The statement policy can carry a `carrier_profile_hash`; it commits to every
`BlindOperatingContract` field that affects candidate filtering/order, the
required carrier bit count, and the seed/ordering algorithms. The helper
rejects a missing/mismatching profile hash, wrong session challenge,
insufficient capacity, position-hash mismatch, registry mismatch, or video
digest mismatch before returning context success. The legacy helper which
accepts explicit positions is not the video-only acceptance path.

This wrapper is not yet connected to `verifier_blind.py` or a proof backend;
the currently exposed near-blind verifier still uses a signed manifest and
positions sidecar. `required_bits` and the carrier contract must be supplied
from trusted verifier configuration (for example a fixed registered envelope
profile), not copied from an untrusted sidecar. A 300-frame Foreman integration
test exercises real carrier derivation, registry binding, and canonical video
hashing through the new helper, but it does not create or verify a ZK proof.

## Payload commitment and exact base relation

To avoid putting a general hash-preimage circuit inside the proof, the target
uses a concrete lattice vector commitment. A registered parameter set defines
prime modulus `q`, dimensions, public matrices `A`, `B_ctx`, `B_msg`, encoding,
and norm bounds. These public values are generated from a pinned setup seed
using domain-separated SHAKE and are part of `parameter_id`; there is no
prover-selected matrix or modulus.

Encode the public context as a canonical vector over `Z_q`:

```text
ctx = CanonicalEncode(
  "zkstego/video-zk/payload-context/v1\0",
  protocol_version, relation_id, parameter_id, registry_root, registry_epoch,
  session_challenge, codec_policy_id, carrier_profile_id, carrier_count,
  positions_hash, payload_length, video_commitment
)
```

`ctx` uses the same fixed-width encodings as `X`; the leading literal is
`"zkstego/video-zk/payload-context/v1" || 0x00`. The exact v0.1 context order is
`protocol_version, relation_id, parameter_id, registry_root, registry_epoch,
session_challenge, codec_policy_id, carrier_profile_id, carrier_count,
positions_hash, payload_length, video_commitment`.

The prover's private witness is:

```text
w = (payload, r)
```

where `payload` is exactly `payload_length` bytes and `r` is a bounded lattice
randomness vector. The public commitment is:

```text
payload_commitment = A*r + B_ctx*Encode(ctx) + B_msg*Encode(payload) (mod q)
```

The public `B_ctx*Encode(ctx)` offset does **not** by itself bind a proof to
`ctx`: anyone can replace `(ctx, C)` with
`(ctx', C - B_ctx*Encode(ctx) + B_ctx*Encode(ctx'))`. A backend that proves only
the reduced equation `C - B_ctx*Encode(ctx) = A*r + B_msg*Encode(payload)`
and hashes only that reduced instance can accept the *same proof* for both
pairs. The complete canonical `X`, including `ctx` and the original `C`, must
be bound into the proof transcript before the first challenge, with a security
argument for the resulting Fiat-Shamir transform. An alternative
context-derived matrix design needs its own commitment/security analysis and
does not automatically implement this v0.1 relation. The isolated Go
`payload_opening_probe` exposed this recentering failure in a regression test
and then changed its experimental matrix derivation to depend on the context
digest; that test result is not a proof of non-malleability.

The target lattice commitment *shape* is an equation, not yet a selected
parameterized scheme. A concrete instantiation must still fix the ring/field,
matrix dimensions and distributions, parameter derivation, payload encoding,
and all bounds; until then the vector equation is not a deployable commitment.
The exact base relation `R_open(X; payload, r)` is true
iff all of the following hold:

1. Every field in `X` is canonical and accepted by the verifier-pinned
   relation/parameter/policy registry.
2. `payload_length` is within the registered suite's range;
   `payload` has exactly that many bytes and one canonical encoding (each byte
   is constrained to `[0,255]`, not merely interpreted modulo `q`).
3. `r` satisfies the parameter set's required norm/range bounds.
4. The commitment equation above holds coefficient-for-coefficient in `Z_q`.

An honest prover rejecting an out-of-range witness does not establish items
2-3: the **verifier** must reject every proof of a statement with no valid
bounded opening under the claimed knowledge-soundness model. The pinned Go
LNP22 `VerifyLinear` fails this exact-bound gate in a reproducible assessment:
with `Beta=1`, a canonical serialized proof for the equation `s[0]=2` verifies
although no in-bound witness exists. The payload-opening probe also accepts a
transcript constructed from a non-bit witness. Therefore that 8,203-byte
probe is not an implementation of `R_open`, regardless of its positive
functional tests or whether it fits a video's carrier budget. See
`benchmark/lnp22_context_probe/lnp22_dependency_assessment_test.go`.

Before proof verification, the verifier must independently derive the
carrier list from the received H.264 stream and require the resulting
`positions_hash` and `video_commitment` to equal the public inputs in `X`.
This is public statement construction, not a hidden-witness circuit check.
The selected proof backend then verifies `R_open` for that exact `X`.

The actual proof must establish knowledge soundness for this relation and
zero-knowledge for `payload` and `r`, under a specifically named lattice
assumption and concrete reviewed parameters. The equations here alone provide
neither property. Parameter derivation, commitment hiding/binding, shortness,
transcript construction, Fiat-Shamir security model, serialization and the
chosen proof system all require independent review.

### Application predicates

`R_open` only proves knowledge of an opening to the context-bound commitment.
If the system is meant to prove a further statement—e.g. a registered
authorization, a camera attestation, a property of private metadata, or a
relationship between metadata and video—then the registry entry must name a
fixed predicate `F_relation_id(payload, video_commitment, public_policy)` and
the full relation is:

```text
R_relation_id(X; payload, r) =
    R_open(X; payload, r)
    AND F_relation_id(payload, video_commitment, public_policy)
```

The verifier selects `relation_id` and its predicate from a pinned signed
registry. A prover-provided identifier cannot define or replace the predicate.
Until a concrete `F_relation_id` is agreed and implemented, the only permitted
claim is “knowledge of a payload opening bound to this normalized video and
policy”; do not claim camera provenance or truth of the payload.

## Proof envelope and verification contract

The fixed-size in-band envelope is canonically encoded as:

```text
magic[8] || format_version[u16] || parameter_id[32] ||
session_challenge[32] || payload_length[u32] ||
payload_commitment[fixed suite length] || proof_length[u32] ||
proof_bytes[proof_length] || zero_padding[registered remainder]
```

All integers are unsigned big-endian. The selected `parameter_id` fixes
`proof_length` and total envelope length; mismatches fail closed. The verifier
performs, in order: (1) H.264/policy checks and blind carrier discovery,
(2) envelope parsing and canonical-padding checks, (3) statement/context
recomputation from video and verifier configuration, (4) registry/epoch/replay
checks, and (5) independent lattice proof verification of `R_relation_id`.
Any sidecar may contain diagnostics but never the sole copy of proof bytes,
statement inputs, carrier positions or trust data required for acceptance.

## Security claims and explicit limits

- **Soundness / knowledge soundness:** conditional on the selected lattice
  argument's reviewed theorem and parameter estimate, correct statement
  construction, commitment binding, and proof verifier. No current project
  implementation satisfies these conditions.
- **Zero knowledge:** conditional on the selected argument's reviewed ZK
  theorem and implementation. A digital signature, payload hash, signed
  receipt, or statement helper is not a ZK proof.
- **Tamper detection:** changes outside normalized carrier signs change the
  recomputed video commitment except with the selected hash's collision
  probability. Changes to carrier bits corrupt the envelope/proof and must be
  rejected. This claim depends on exact normalization and extraction code.
- **Replay:** verifier-issued challenges must be fresh and one-use. An offline
  verifier must maintain a spent-token set; a stateless verifier cannot promise
  replay prevention for an otherwise valid video.
- **Domain separation:** protocol, statement, carrier-map, video-normalization,
  payload-commitment, setup-matrix and transcript domains are distinct and
  versioned. Length-prefix every variable-sized item.
- **No provenance claim:** a context-bound commitment is not evidence that a
  sensor captured the video. Provenance requires an explicit, registry-pinned
  predicate over a camera credential/signature or trusted-device statement,
  proven inside the relation; this is not implemented here.
- **Codec/transforms:** the relation binds canonical H.264 syntax, not visual
  equivalence. Decode compatibility, remux/transcode behavior and image
  quality are separate measured properties, not consequences of ZK security.

## Current implementation gaps

The existing `src/video_zkp_contract.py` is only a statement/context helper:

- its payload commitment is a SHA3 hash and does not include the video/session
  context in the committed value;
- `embed()` can accept an explicit `zkp_session_id` challenge when emitting
  its future-ZKP statement, and rejects missing or non-32-byte challenges.
  `src/zkp_sessions.py` now provides a durable SQLite challenge store with a
  verifier-pinned 32-byte context binding, expiry checks before and after the
  caller's proof-verification callback, and atomic one-use consumption. Its
  eight unit tests cover restart-persistent replay rejection, expiry, wrong
  binding, failed proof non-consumption, and concurrent consumes. The local
  `src/zkp_session_http.py` service exposes `POST /api/v1/zkp/sessions` and
  returns a challenge with issue/expiry timestamps. It binds only to a
  loopback IP, accepts no request body, and has no proof-verification route;
  it is a development issuer, not an authenticated or production verifier.
  Start it with `python -m src.zkp_session_http --database
  ./.state/sessions.sqlite3 --context-binding-hex <64-hex-policy-digest>`;
  replace the placeholder with the verifier's pinned policy digest. The
  challenge service is not yet wired to the public video verifier. One shared
  durable database is required across workers on the same host, and a
  multi-host deployment still needs an equivalent shared transactional store;
- the separate experimental `benchmark/lnp22_context_probe/http_api.py` now
  exposes authenticated session issuance and requires the issued challenge on
  embed jobs. A video-only verify job extracts the session ID from the in-band
  envelope, verifies the research proof, and atomically consumes the challenge;
  tests cover unknown/expired challenges, failed proofs, and replay. This is
  outer session-state enforcement around the LNP22 probe, not a proof of the
  target payload-opening relation. The probe statement does not yet include
  the session store's policy-binding digest, so that server-side binding is
  not itself cryptographically asserted by this experimental proof;
- this future statement is still written to a `.pq-statement.json` sidecar,
  while the default video payload carries an ML-DSA receipt reference, not a
  ZK proof. `embed()` does not yet register/pin the carrier profile used by
  `verify_video_zkp_context_binding_video_only()`, so the generated statement
  is not currently accepted by that video-only helper;
- the statement carries the original `cover_hash`, which a blind verifier
  cannot recompute from the stego video;
- the low-level digest helper accepts externally supplied positions. A new
  video-only context wrapper independently derives them when given a
  verifier-pinned challenge and the carrier profile hash, but is not wired into
  the public blind verifier, whose current path still consumes sidecar data;
- there is no proof backend proving `R_open` or any `R_relation_id`, and the
  composed helper explicitly does not verify a proof or payload opening.

Accordingly this draft defines the intended next protocol boundary, not a
completed implementation. Before coding a backend, fix the public contract,
select concrete commitment/proof parameters, implement a fixed-size carrier
envelope with independently derived positions, and obtain independent review
of the exact relation and Fiat-Shamir instantiation.
