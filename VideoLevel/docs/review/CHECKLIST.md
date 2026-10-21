# Reviewer checklist

Tick each item against the code at commit `18c5123`. Paths are relative to
`VideoLevel/src/`. "Test" names the test that exercises the item, if one
exists.

## 1. Parameters (`lattice_zk/params.py`)

- [ ] q = 2^30 − 35 is prime and q ≡ 5 (mod 8). Checked by
      `ring.validate_modulus` (`ring.py:42–47`, Miller–Rabin with 12 fixed
      bases, deterministic below 3.3·10^24). Test:
      `test_latticezk_ring.py::test_toy_modulus_satisfies_two_factor_splitting_condition`,
      `::test_modulus_validation_rejects_composites_and_out_of_range_values`.
- [ ] `2√2 < √q` (invertibility of `C̄`, `params.py:63–65`) and
      `2·8κB < q` (binding norm does not wrap, `params.py:66–68`). Test:
      `test_latticezk_bdlop.py::test_parameters_reject_unsound_choices`.
- [ ] `B = γ − κ − 1` (`params.py:80–83`), shift bound κ (`:75–78`).
      `acceptance_probability = ((2B+1)/2γ)^{kN}` (`:118–122`) equals 0.1912.
      Test: `::test_response_bound_leaves_exactly_the_shift_margin`,
      `::test_abort_rate_matches_the_parameter_estimate`.
- [ ] Challenge space `log2 C(256,60) + 60 = 257.01` bits (`:114–116`).
      `require_production_strength` needs ≥ 256 (`:141–144`). Note: this is
      enforced only in `pins_from_registry` (QUESTIONS Q12).
- [ ] `parameter_id` hashes every field that changes the relation, with fixed
      widths and the setup seed (`:124–139`). Test:
      `::test_parameter_id_pins_every_field`.
- [ ] Security estimates match the instances in the proofs: M-SIS on
      `B1 ∈ R_q^{n×k}`, ℓ∞ ≤ 8κB; M-LWE rank λ with n+1 samples. See
      `research/bdlop_params/CROSSCHECK.md`.

## 2. Sampling distributions (`lattice_zk/sampling.py`)

- [ ] `_rejection_sample` (`:39–47`) masks to `bits` bits and keeps values
      `< bound`. It never reduces modulo the bound. Each call reads
      `count − accepted + 16` draws and **discards the unused tail**. This
      does not change uniformity, but an independent implementation must copy
      the exact stream consumption to reproduce the KATs.
- [ ] Key polynomials are uniform on [0, q) from 30-bit draws (`:50–51`),
      with acceptance about 0.99999997.
- [ ] Commitment randomness is uniform ternary, from 2-bit draws below 3
      (`:54–57`). Test: `test_latticezk_ring.py::test_ternary_vector_is_balanced`.
- [ ] Masks are uniform on [−γ+1, γ] as `γ − u` with `u` an 18-bit draw
      below `2γ = 2^18` (`:60–66`), so no draw is ever rejected. Test:
      `::test_mask_vector_covers_exact_interval`.
- [ ] Challenges (`:69–81`): weight-many sign bits, then a Fisher–Yates
      shuffle over positions N−κ … N−1, each index drawn by exact rejection
      below `index+1`. This is ML-DSA SampleInBall and gives a uniform
      distribution on `C`. Tag: `zkstego/lattice-zk/challenge-poly/v1\0`.
      Tests: `::test_challenge_has_fixed_weight_and_depends_on_seed`,
      `::test_full_weight_challenge_has_no_zero_coefficient`.
- [ ] `XofStream.read` (`:22–29`) recomputes a longer SHAKE-256 output from
      the start. Correctness relies on SHAKE prefix consistency. Test:
      `::test_xof_stream_is_deterministic_and_prefix_stable`.
- [ ] Fresh entropy comes from `os.urandom(32)`: commitment randomness
      (`bdlop.py:126–132`) and prover entropy (`opening_proof.py:54–60`). The
      session challenge uses `secrets.token_bytes(32)` (`zkp_sessions.py:133`).

## 3. Ring arithmetic (`lattice_zk/ring.py`)

- [ ] `poly_mul` (`:76–91`) is the exact negacyclic product by Kronecker
      substitution. The limb width `(N·(q−1)^2).bit_length()//8 + 1` bytes
      leaves no carry between limbs, and `wide[i] − wide[i+N] mod q`
      implements `X^N = −1`. Tests: `::test_poly_mul_matches_negacyclic_schoolbook`,
      `::test_poly_mul_handles_large_modulus_without_overflow`,
      `::test_x_to_the_n_is_minus_one`.
- [ ] `center` maps to [−(q−1)/2, (q−1)/2] (`:60–63`). The prover recovers
      the integer `c·r` exactly because `κ < q/2` (`opening_proof.py:106–107`).
- [ ] `is_invertible` (`:106–114`) tests both CRT components. It is correct
      only because `X^{N/2} ± √−1` are irreducible (q ≡ 5 mod 8; QUESTIONS
      Q3). Verification never calls it.

## 4. Bounds and rejection conditions

- [ ] Opening prover: abort iff `max |z_i| > B` (`opening_proof.py:108–109`).
      This is the only rejection test, and it is witness-independent
      (Lemma `lem:hvzk`). Tests:
      `test_latticezk_bdlop.py::test_respond_accepts_exactly_the_response_range`,
      `::test_accepted_response_coordinate_is_uniform_for_any_witness`,
      `::test_accepted_responses_are_in_range_and_witness_independent`.
- [ ] Equality prover: accept iff *both* responses are in range
      (`equality_proof.py:144`). Cap 4096 (`:50`); failure probability about
      2^-220 (`:54–64`). Tests:
      `test_latticezk_equality.py::test_equality_prover_cap_gives_negligible_completeness_error`,
      `::test_shared_opening_cap_would_not_have_sufficed_for_production`.
- [ ] Opening cap 512 (`opening_proof.py:33`); failure probability 2^-156.7.
      Exhausting the cap raises and never outputs a rejected transcript
      (`:136`). Test: `test_latticezk_bdlop.py::test_provers_fail_closed_when_every_attempt_aborts`.
- [ ] Verifier range check: `unpack_uints(..., bound = 2B+1)` rejects any
      packed value above 2B, so `z ∈ [−B, B]` (`opening_proof.py:155–162`,
      `equality_proof.py:175–181`). No other norm check is needed.
- [ ] The prover refuses non-ternary witnesses (`bdlop.py:50–56`) and
      witnesses that do not open `t1` (`opening_proof.py:124–125`). The
      equality prover also checks that the message gap is zero
      (`equality_proof.py:89–106`). Tests:
      `::test_prover_refuses_a_non_ternary_witness`,
      `::test_prover_refuses_randomness_that_does_not_open_the_commitment`,
      `test_latticezk_equality.py::test_different_messages_cannot_be_proved_equal`.

## 5. Encodings (`lattice_zk/codec.py`, `bdlop.py`, `video_proof.py`)

- [ ] `pack_uints` / `unpack_uints` (`codec.py:10–33`): fixed bit width, MSB
      first, exact length, zero padding, values below the bound. Proof
      packing has no padding bits at production parameters
      (`3584 · 18 bits = 8064 bytes`). Tests:
      `test_latticezk_bdlop.py::test_pack_uints_round_trip_and_canonical_rejection`,
      `::test_random_packed_fields_round_trip_and_decode_canonically`.
- [ ] Commitments are canonical: shape and every coefficient in [0, q) are
      checked on construction from bytes and at every prover/verifier entry
      (`bdlop.py:40–47, 76–108`; `opening_proof.py:63–74`). Test:
      `::test_non_canonical_commitments_are_refused_everywhere`.
- [ ] Payload encoding is injective (2-byte length, 3 bytes per
      coefficient, at most 766 bytes), and the decoder accepts exactly the
      encoder's image (`codec.py:36–60`). Tests:
      `::test_payload_encoding_is_injective_and_bounded`,
      `::test_decodable_messages_are_exactly_the_encoder_image`.
- [ ] The statement is fixed-width (274 bytes) with the session field at
      bytes 106–137 (`video_proof.py:89–98`). Every digest field is checked
      to be 32 bytes and every integer to be u64 (`:54–87`). Test:
      `test_latticezk_video_proof.py::test_statement_encoding_is_fixed_width_and_injective_per_field`.
- [ ] Envelopes have an exact length, magic and version, a pinned `pid` with
      constant-time comparison, and a canonical commitment
      (`video_proof.py:171–182, 263–273`). The session field must equal the
      statement's (`:223, 286`). Tests: `::test_envelope_rejects_tampering_and_malformed_framing`,
      `::test_envelope_kinds_are_not_interchangeable`,
      `::test_random_garbage_never_decodes_as_an_envelope`.
- [ ] The carrier framing must be the canonical chunking of the envelope
      under the pinned chunk size (D1 fix, `video_pipeline.py:359–367`).
      Tests: `test_latticezk_video_pipeline.py::test_rewritten_single_chunk_header_is_rejected`,
      `::test_rechunked_multi_chunk_envelope_is_rejected`.

## 6. Fiat–Shamir transcript and domain separation

- [ ] Opening: `SHAKE-256(tag ‖ pid ‖ u64(|x|) ‖ x ‖ enc(t1,t2) ‖ w as >u8)`,
      32-byte output (`opening_proof.py:43–51`). `w` is recomputed by the
      verifier as `B1·z − c·t1 mod q` (`:167`).
- [ ] Equality: `SHAKE-256(tag ‖ pid ‖ u64(|x|) ‖ x ‖ enc(t_a) ‖ enc(t_b) ‖ w_a ‖ w_b ‖ u)`
      (`equality_proof.py:71–82`). The verifier recomputes `u` as
      `⟨b2, z_a − z_b⟩ − c(t2_a − t2_b)` (`:186–192`).
- [ ] The seed comparison uses `hmac.compare_digest` (`opening_proof.py:168`,
      `equality_proof.py:193`).
- [ ] Tags: `…/bdlop-open/v1/{key, randomness, fiat-shamir, mask}\0`,
      `…/bdlop-equal/v1/{fiat-shamir, mask}\0`, `…/challenge-poly/v1\0`,
      `…/bdlop-open/v1/parameters\0` (SHA3-256), linkage, disclosure,
      statement and video-commitment tags. Each tag ends in its only NUL byte.
- [ ] Hedged mask key: SHA3-256 **without a tag** (D7, open;
      `opening_proof.py:77–90`). Mask stream: `tag ‖ K ‖ u32(attempt)`. Tests:
      `test_latticezk_bdlop.py::test_mask_stream_is_never_reused_across_statements_or_witnesses`,
      `::test_proving_is_deterministic_only_under_an_explicit_mask_seed`.
- [ ] Linkage and disclosure contexts are length-prefixed and bound to `pid`
      (`linkage.py:29–36`, `video_proof.py:302–316`). Tests:
      `test_latticezk_linkage.py::test_context_encoding_is_unambiguous`,
      `test_latticezk_video_proof.py::test_disclosure_rejects_wrong_payload_context_or_envelope`.

## 7. Constant-time caveats (not addressed)

This is a **pure-Python/NumPy research implementation. It is not constant
time** and makes no side-channel claim (`security.tex`, adversary model).
Known variable-time code that touches secrets:

- [ ] `ring.poly_mul` uses Python big integers. Multiplication time depends
      on operand bit length, and therefore on how many leading limbs of the
      packed `r` are zero (`ring.py:66–91`). It runs on `c·r` in every
      attempt (`opening_proof.py:93–95`).
- [ ] `ring.center` and `np.abs(response).max()` (`opening_proof.py:107–109`)
      are data-dependent NumPy operations. NumPy gives no timing guarantee.
- [ ] The attempt count is observable through timing. It is
      witness-independent by Lemma `lem:hvzk`, so it leaks nothing *if* the
      sampler is exactly uniform.
- [ ] `_rejection_sample` loops are data-dependent, but only on public or
      hash-derived values (keys and challenges) or on masks, whose draws
      are never rejected.
- [ ] Secret material (`r`, masks, `K`) is never zeroized. Python cannot
      guarantee that.
- [ ] Secret files written by the CLI are owner-only on POSIX
      (`cli.py:54–59`). This is not enforced on Windows, where the test is
      skipped.

## 8. Verification path (`lattice_zk/video_pipeline.py:300–402`)

- [ ] Misconfiguration raises before the video is read. Exactly one of
      session store or expected session must be given, and the
      credential/profile combination must be consistent. The relation id is
      recomputed from `(params, profile, credential, holder_id)` and compared
      with the pins (D6 fix, `:300–326`). Test:
      `test_latticezk_video_pipeline.py::test_malformed_verifier_configuration_is_refused_loudly`.
- [ ] Every statement field except `N_s` comes from the pins or from the
      transport's recomputation (`:369–375`). `N_s` is read from the envelope
      and then checked by the store (`:390–397`) or equals `expected_session`.
- [ ] A transport exception yields `valid=False`, never an accept
      (`:351–361`). Test: `::test_transport_failures_are_reported_as_rejection`.
- [ ] Pins: ML-DSA-65 signature, epoch floor, exactly one matching
      descriptor, and production-strength parameters (`:180–213`). Tests:
      `::test_registry_pins_resolve_only_for_the_registered_configuration`,
      `::test_registry_epoch_outside_the_statement_field_is_refused`.
- [ ] Session consumption is atomic and one-use, and failed verification
      does not consume the session (`zkp_sessions.py:157–241`). Tests:
      `test_zkp_sessions.py` (12 tests, including concurrency and expiry
      during verification).

## 9. Known-answer vectors

- [ ] `research/bdlop_params/kat.py` derives everything from fixed seeds and
      pins SHA-256 digests of the key, the commitments, the opening proofs
      and the equality proofs. It covers the empty, short and maximum (766
      byte) payloads. Regenerate and diff:
      `python -B research/bdlop_params/kat.py --parameter-set BDLOP_OPEN_128_V2 | diff - research/bdlop_params/kat_v2.json`
      (and `BDLOP_OPEN_128_V1` against `kat_v1.json`).
      Test: `test_latticezk_kat.py` (3 tests, run for both sets).
- [ ] The KATs fix the exact XOF consumption (see §2). Any change to tags,
      to the hedging input (D7) or to the samplers changes them.
