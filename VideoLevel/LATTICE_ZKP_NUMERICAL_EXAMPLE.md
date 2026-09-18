# Numerical example of a lattice zero knowledge video proof

This document is a hand-calculated teaching example. Its tiny numbers are
insecure and must never be used as cryptographic parameters. It shows the
shape of a non-interactive lattice proof that could bind a video to a prover's
registered public credential.

## Goal

The verifier has a public commitment `C` pinned during setup. The prover has a
private short witness `(s, e)`. For a canonical video hash `H_video`, the
prover creates one proof `pi` that establishes both:

1. the prover knows a short witness satisfying `C = A*s + e (mod q)`; and
2. the proof transcript is bound to that exact video hash and policy.

The video contains the proof directly in reserved direct-CAVLC carriers. It
does not require a video-sidecar file. A sender label such as `device_id` is
optional: with one fixed prover, the verifier can pin `C` directly.

## 1. Enrolment values

Use the deliberately small modulus:

```text
q = 97
```

The public matrix is:

```text
    [12  7]
A = [     ]
    [ 5 19]
```

The prover keeps these short vectors secret:

```text
    [ 2]       [1]
s = [  ]   e = [ ]
    [-1]       [0]
```

It creates the public commitment:

```text
C = A*s + e mod 97
```

The calculation is:

```text
A*s = [12*2 +  7*(-1)] = [17]
      [ 5*2 + 19*(-1)]   [-9]

C = [17] + [1] = [18]
    [-9]   [0]   [-9] = [18] mod 97
                              [88]
```

The verifier pins `A` and:

```text
    [18]
C = [88]
```

The relation is lattice-based because, at real parameter sizes, finding a
short witness `(s, e)` from only `(A, C)` is a hard module-lattice problem.
The set of modular solutions defines a q-ary lattice/coset; the required
witness is distinguished by being short.

## 2. Bind the proof to a video

The encoder reserves a deterministic CAVLC carrier region for the proof. It
replaces that region with a fixed canonical pattern before hashing, which
avoids the circular dependency of a proof being stored in the video it binds.

```text
V_canonical = video with every proof carrier set to its canonical value
H_video     = SHA3-256(V_canonical)
```

For this example, let the other public context be:

```text
H_video  = 9f31...c8aa
sequence = 42
policy   = h264-baseline-cavlc / direct-carrier-v1
```

The public statement is a canonical encoding:

```text
X = Encode(C || H_video || sequence || policy)
```

In a real deployment, `X` also includes the protocol version, relation and
parameter-set hashes, registry root/epoch when applicable, and session data.

## 3. Create a masked commitment

For this one proof, the prover samples new random masks:

```text
     [ 4]        [-2]
y_s = [-3]  y_e = [ 3]
```

It computes:

```text
w = A*y_s + y_e mod 97
```

```text
A*y_s = [12*4 +  7*(-3)] = [ 27]
        [ 5*4 + 19*(-3)]   [-37]

w = [ 27] + [-2] = [ 25]
    [-37]   [ 3]   [-34] = [25] mod 97
                                [63]
```

So the first public proof commitment is:

```text
    [25]
w = [63]
```

The mask makes `w` independent of the witness for this demonstration.

## 4. Derive a non-interactive challenge

No verifier message is needed. Both parties derive the challenge with
Fiat-Shamir from the complete public statement and commitment:

```text
c = HashToChallenge(
      "zkstego-lattice-v1" || X || w
    )
```

For a hand calculation, assume the challenge sampler outputs:

```text
c = 3
```

In a real lattice proof, this is a hash-derived sparse polynomial or vector,
not a prover-selected small integer.

## 5. Create the responses

The prover computes:

```text
z_s = y_s + c*s
z_e = y_e + c*e
```

```text
z_s = [ 4] + 3*[ 2] = [10]
      [-3]     [-1]   [-6]

z_e = [-2] + 3*[1] = [1]
      [ 3]     [0]   [3]
```

An illustrative proof envelope would therefore look like:

```json
{
  "version": "zkstego-lattice-demo-v1",
  "statement_hash": "hash(C || H_video || sequence || policy)",
  "commitment_w": [25, 63],
  "response_s": [10, -6],
  "response_e": [1, 3]
}
```

LaZer uses a binary proof format with parameter-specific commitments,
responses, challenge material, hints, and compression. The JSON above is only
the logical shape of a proof, not a LaZer serialization.

## 6. Verify the proof

The verifier extracts `pi` from video, canonicalizes the proof region, and
recomputes `H_video` and then `c`. It checks:

```text
A*z_s + z_e = w + c*C mod 97
```

Left side:

```text
A*z_s = [12*10 +  7*(-6)] = [ 78]
        [ 5*10 + 19*(-6)]   [-64]

A*z_s + z_e = [ 78] + [1] = [ 79]
                [-64]   [3]   [-61] = [79] mod 97
                                             [36]
```

Right side:

```text
w + c*C = [25] + 3*[18] = [ 79]
          [63]     [88]   [327] = [79] mod 97
                                      [36]
```

The two sides match:

```text
[79]   [79]
[36] = [36]
```

This follows algebraically:

```text
A*z_s + z_e
= A*(y_s + c*s) + (y_e + c*e)
= (A*y_s + y_e) + c*(A*s + e)
= w + c*C
```

The verifier additionally checks the response norm bounds. This small example
can use a teaching-only bound such as `abs(z_i) <= 10`; real bounds and their
security analysis are selected by the proof system parameter generator.

## 7. What happens after video tampering

If an attacker modifies a non-proof portion of the video, `H_video` changes.
The verifier derives a different challenge, for example `c' = 2`, and expects:

```text
w + 2*C = [61, 45] mod 97
```

The old proof responses still satisfy the equation only for `c = 3`, yielding
`[79, 36]`. Verification fails. The attacker cannot generate compatible new
responses without the private witness `(s, e)`.

## 8. Where zero knowledge comes from

The verifier sees `w`, `z_s`, and `z_e`, but not `s`, `e`, `y_s`, or `y_e`.
The responses have the form:

```text
z = y + c*witness
```

At production parameters, masks are sampled from an appropriate wide
distribution. Rejection sampling and norm bounds prevent the observable
response distribution from leaking the short witness. The toy values above do
not provide this guarantee and must not be treated as a secure protocol.

## 9. Relation to the project

The current public API intentionally rejects the experimental in-tree
`lattice_zkp` backend. The project has a canonical video statement contract
and a signed relation registry, but it does not yet have this reviewed LaZer
relation, a production proof envelope, direct-CAVLC proof embedding, or an
end-to-end proof fixture.

The in-tree research prototype currently uses values such as `q = 8,380,417`,
a `64 x 128` matrix, and 128 rounds. These are not approved production
parameters for the video relation. LaZer must generate and evaluate the
parameters from the exact relation and norm bounds, followed by cryptographic
review.

For the intended one-video deployment, the final proof statement should bind
at least the public credential `C`, canonical video hash, policy hash, session
identifier, and a monotonic sequence or chain hash. The sequence/chain is
needed to detect replay of an otherwise authentic older video.
