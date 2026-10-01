#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ! -x "$1" ]]; then
    echo "usage: $0 /path/to/isw21_r1cs_opening_smoke" >&2
    exit 2
fi

binary=$1
expected_context=913ae120775802b46ca91108d2334f8029f163059a4418ce7d26b0520f8bd731
other_context=003ae120775802b46ca91108d2334f8029f163059a4418ce7d26b0520f8bd731
test_dir=$(mktemp -d "${TMPDIR:-/tmp}/isw21-split-process.XXXXXX")
trap 'rm -rf -- "$test_dir"' EXIT

"$binary" \
    --export-verifier-key "$test_dir/verifier.key" \
    --export-extracted-proof "$test_dir/proof.bin" \
    >"$test_dir/prover.log" 2>&1

grep -q 'SPLIT_PROCESS_EXPORT=PASS' "$test_dir/prover.log"
grep -q 'LATTICE_SNARK_HONEST_VERIFY=PASS' "$test_dir/prover.log"
[[ "$(stat -c '%a' "$test_dir/verifier.key")" == 600 ]]

"$binary" \
    --verify-extracted-proof "$test_dir/proof.bin" \
    --verifier-key "$test_dir/verifier.key" \
    --expected-context-hex "$expected_context" \
    >"$test_dir/verifier.log" 2>&1
grep -q 'SEPARATE_PROCESS_LATTICE_VERIFY=PASS' "$test_dir/verifier.log"

if "$binary" --verify-extracted-proof "$test_dir/proof.bin" \
    --verifier-key "$test_dir/verifier.key" \
    --expected-context-hex "$other_context" \
    >"$test_dir/replay.log" 2>&1; then
    echo "old proof unexpectedly accepted for another verifier session" >&2
    exit 7
fi
grep -q 'proof context does not match verifier session' "$test_dir/replay.log"

"$binary" --prover-context-hex "$other_context" \
    --export-verifier-key "$test_dir/other-verifier.key" \
    --export-extracted-proof "$test_dir/other-proof.bin" \
    >"$test_dir/other-prover.log" 2>&1
"$binary" --verify-extracted-proof "$test_dir/other-proof.bin" \
    --verifier-key "$test_dir/other-verifier.key" \
    --expected-context-hex "$other_context" \
    >"$test_dir/other-verifier.log" 2>&1
grep -q 'SEPARATE_PROCESS_LATTICE_VERIFY=PASS' "$test_dir/other-verifier.log"
if "$binary" --verify-extracted-proof "$test_dir/other-proof.bin" \
    --verifier-key "$test_dir/verifier.key" \
    --expected-context-hex "$other_context" \
    >"$test_dir/wrong-key.log" 2>&1; then
    echo "proof unexpectedly accepted under a different setup key" >&2
    exit 10
fi
if "$binary" --verify-extracted-proof "$test_dir/other-proof.bin" \
    --verifier-key "$test_dir/other-verifier.key" \
    --expected-context-hex "$expected_context" \
    >"$test_dir/reverse-replay.log" 2>&1; then
    echo "new proof unexpectedly accepted for the old verifier session" >&2
    exit 9
fi

if "$binary" --verify-extracted-proof "$test_dir/proof.bin" \
    --verifier-key "$test_dir/verifier.key" \
    >"$test_dir/missing-session.log" 2>&1; then
    echo "verifier unexpectedly accepted a missing session context" >&2
    exit 8
fi

cp "$test_dir/proof.bin" "$test_dir/tampered-response.bin"
response_byte=$(od -An -tu1 -j 2576 -N 1 "$test_dir/proof.bin" | tr -d '[:space:]')
printf -v response_byte_hex '\\x%02x' "$((response_byte ^ 1))"
printf '%b' "$response_byte_hex" | dd of="$test_dir/tampered-response.bin" \
    bs=1 seek=2576 count=1 conv=notrunc status=none
if "$binary" --verify-extracted-proof "$test_dir/tampered-response.bin" \
    --verifier-key "$test_dir/verifier.key" \
    --expected-context-hex "$expected_context" >"$test_dir/tampered.log" 2>&1; then
    echo "tampered proof response unexpectedly accepted" >&2
    exit 3
fi

cp "$test_dir/proof.bin" "$test_dir/wrong-context.bin"
dd if=/dev/zero of="$test_dir/wrong-context.bin" \
    bs=1 seek=12 count=1 conv=notrunc status=none
if "$binary" --verify-extracted-proof "$test_dir/wrong-context.bin" \
    --verifier-key "$test_dir/verifier.key" \
    --expected-context-hex "$other_context" >"$test_dir/context.log" 2>&1; then
    echo "proof under wrong context unexpectedly accepted" >&2
    exit 4
fi

head -c 128 "$test_dir/proof.bin" >"$test_dir/truncated-proof.bin"
if "$binary" --verify-extracted-proof "$test_dir/truncated-proof.bin" \
    --verifier-key "$test_dir/verifier.key" \
    --expected-context-hex "$expected_context" >"$test_dir/truncated-proof.log" 2>&1; then
    echo "truncated proof unexpectedly accepted" >&2
    exit 5
fi

head -c 128 "$test_dir/verifier.key" >"$test_dir/truncated-key.bin"
if "$binary" --verify-extracted-proof "$test_dir/proof.bin" \
    --verifier-key "$test_dir/truncated-key.bin" \
    --expected-context-hex "$expected_context" >"$test_dir/truncated-key.log" 2>&1; then
    echo "truncated verifier key unexpectedly accepted" >&2
    exit 6
fi

echo "SEPARATE_PROCESS_HONEST_VERIFY=PASS"
echo "REPLAY_WRONG_SESSION=REJECTED"
echo "SECOND_SESSION_PROOF=PASS"
echo "WRONG_SETUP_KEY=REJECTED"
echo "MISSING_SESSION_CONTEXT=REJECTED"
echo "TAMPERED_RESPONSE=REJECTED"
echo "WRONG_CONTEXT=REJECTED"
echo "TRUNCATED_PROOF=REJECTED"
echo "TRUNCATED_VERIFIER_KEY=REJECTED"
echo "VERIFIER_KEY_MODE=600"
