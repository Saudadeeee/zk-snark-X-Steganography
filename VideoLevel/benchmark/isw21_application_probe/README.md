# ISW21 fixed-payload commitment circuit attempt

This isolated probe drafts an R1CS relation using the pinned ISW21 research
proof-of-concept. **The source currently does not compile against the pinned
backend; no application proof was generated or verified.** It is not wired to
the application API and is not an accepted backend.

The intended relation is:

~~~text
domain = zero_pad_32("zkstego/payload/sha256/v1")
0 <= payload < 2^256
opening is 32 private bytes
commitment = SHA-256(domain || opening || payload)
~~~

Payload and opening are private witness values; the 256-bit digest is the
public statement. This fixed-length candidate omits video/session context,
variable-length encoding, registry pinning, and a production commitment API.
It uses SHA-256 whereas the current in-tree v2 contract uses SHA3-256; it does
not change the production protocol.

The proposed circuit uses two SHA-256 compression gadgets for the 96-byte
preimage, including final padding and the 768-bit message length. Its source
intends to compare the gadget to OpenSSL, check valid/invalid witnesses, and
run ISW21 prove/verify. None of these checks has run because compilation has
not succeeded.

## Reproduce the current compile failure

The audit container is `zkstego-isw21-audit-20260928`, with source pinned at
`48cb4cd4635f5b6e7e9354b7d4b12e9647c4331e` and built under `/tmp/isw21`.
From the project root:

~~~powershell
docker cp benchmark/isw21_application_probe/payload_sha256_r1cs.cpp zkstego-isw21-audit-20260928:/tmp/isw21/lwe/tests/SNARK/
docker cp benchmark/isw21_application_probe/field-zero-compat.patch zkstego-isw21-audit-20260928:/tmp/field-zero-compat.patch
docker cp benchmark/isw21_application_probe/sha256-extension-compat.patch zkstego-isw21-audit-20260928:/tmp/sha256-extension-compat.patch
docker exec zkstego-isw21-audit-20260928 sh -lc 'cd /tmp/isw21/depends/libsnark && patch -p1 < /tmp/field-zero-compat.patch && patch -p1 < /tmp/sha256-extension-compat.patch'
docker exec zkstego-isw21-audit-20260928 sh -lc 'cd /tmp/isw21 && g++ -std=c++17 -DNDEBUG -Wall -Wextra -Wfatal-errors -pthread -maes -msse2 -msse3 -mpopcnt -O2 -march=native -mtune=native -I/tmp/isw21 -I/tmp/isw21/depends/libsnark -I/tmp/isw21/depends/libsnark/depends/libff -I/tmp/isw21/depends/libsnark/depends/libfqfft -I/tmp/isw21/depends/libsnark/depends/libff/libff/.. lwe/tests/SNARK/payload_sha256_r1cs.cpp -o /tmp/isw21/build/lwe/bin/payload_sha256_r1cs /tmp/isw21/build/lwe/liblwe_interface.a /tmp/isw21/build/depends/libsnark/libsnark/libsnark.a /tmp/isw21/build/depends/libsnark/depends/libff/libff/libff.a /usr/lib/x86_64-linux-gnu/libgmp.so /usr/lib/x86_64-linux-gnu/libgmpxx.so -lcrypto /tmp/isw21/build/depends/libzm.a'
~~~

Compilation then fails in libsnark's SHA-256 gadget path: `pb_linear_combination_array`
requires `FieldT::num_limbs` and `.as_bigint()`, which ISW21's
`Extension<Fp2_b19>` does not expose. A compatibility adapter was attempted,
but cannot be applied generically: the same `Extension` template is instantiated
over a custom `Field` type that has no compatible integer representation.
Therefore no runtime log, proof, or performance result exists for this circuit.
Do not describe this as a passing or benchmarked prototype. The clean
compiler-only capture is
`benchmark/results/isw21_payload_sha256_r1cs_compile_20260929_raw.txt`
(SHA-256 `C6187B6D6DF188A1FFEDC3BB1DA17B8DA5B9A70A991090E44B45F882F7E3ED8C`);
it records `compile_exit=1`.

There is a more fundamental issue than compilation: the selected field's
characteristic is `p = 2^19 - 1 = 524287` (`B19Fp2ParamsBase::p_int`). The
generic libsnark SHA gadget packs 32-bit SHA words into a single
`FieldT` (`packing_gadget`, `lastbits_gadget`, and `pb_packing_sum`). Even
though `FieldT` is an extension, these packed sums use powers of two times the
field identity, so they stay in the prime subfield of size `p`; they cannot
injectively encode 32-bit words. For example, the 19-bit all-ones value
`524287` and zero map to the same element because `2^19 = 1 (mod p)`. Thus
adding `as_bigint()`/`num_limbs` compatibility would not make these 32-bit
packing constraints sound. This upstream gadget must not be used for the
application relation over this field. A viable experiment needs an audited
bit-only SHA-256 circuit that constrains 32-bit arithmetic with boolean bits
and carry constraints, without packing full words into one field element, or a
different lattice proof backend with an appropriately sized field and reviewed
gadgets. Neither alternative is implemented or tested here.

## Security and acceptance boundary

The upstream ISW21 README identifies its implementation as a research
proof-of-concept, not production software. Its verification key contains a
secret LWE key (designated-verifier model). Even if this relation compiles, it
would not yet serialize proof/key artifacts, bind video/session/carrier
context, integrate with CAVLC, or independently establish soundness or
zero-knowledge security. A future successful run would only be evidence for
the tested relation and implementation, not full system acceptance.
