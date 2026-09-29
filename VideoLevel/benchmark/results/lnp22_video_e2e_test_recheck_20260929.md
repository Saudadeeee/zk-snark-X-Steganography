# LNP22 video-E2E harness test recheck (2026-09-29)

## Execution

Command:

```text
py -3.12 -m pytest -q src/runtest/test_lnp22_video_e2e.py
30 passed in 13.77s
```

The suite covers the experimental envelope codec, statement/context binding,
truncation and tamper rejection, test doubles around blind extraction/verifier
routing, and a real Go LNP22 proof/verify helper round-trip. It is a unit and
component-integration run. It did not embed a proof in a video during this
execution, and most extraction-path tests use a stubbed extractor.

## Security scope: explicitly not an accepted ZKP result

`benchmark/lnp22_context_probe/README.md` records that its fixed relation is a
random short linear relation, not the payload-commitment-opening relation.
`TestCompactFixedRelationDoesNotProvePayloadCommitmentOpening` demonstrates
that an accepted proof can be produced under distinct payload-commitment
context values using the same pre-provisioned relation witness: the context is
bound to the transcript, but the base relation does not prove that the
commitment opens to the embedded payload.

The same README records an upstream verifier issue: the honest prover rejects
an out-of-bound witness, but the verifier does not check the proof response
norm. The response norm is computed and discarded. Consequently this probe is
not approved for quadratic/norm-constrained application proofs without an
upstream fix and independent cryptographic review. These tests characterize
behavior; they do not override those flaws.

## Related full-video artifact (separate run)

The README records a separate 2026-09-28 experimental Coastguard run with a
9,227-byte LNPF-v2 proof in a 10,446-byte in-band envelope, strict decoding,
video-only extraction and `valid: true`. It took 16,931.57 seconds for 3,000
frames and reached 3,664.95 MB peak process-tree RSS. A separate verifier run
reported 5.309 ms cryptographic verification after extraction. These results
are for the flawed/unregistered LNP22 transport probe, not for the LaZer
Toolkit, not proof of the target payload-opening relation, and not a realtime
performance result. Refer to the original artifacts named in
`benchmark/lnp22_context_probe/README.md` for that run.

## Conclusion

The video transport harness has real development evidence, and the focused
probe tests pass. The required reviewed lattice proof relation remains
unimplemented; this test result must not be reported as completion of the
system goal.
