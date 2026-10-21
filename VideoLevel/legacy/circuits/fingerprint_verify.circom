pragma circom 2.0.0;

include "node_modules/circomlib/circuits/comparators.circom";
include "node_modules/circomlib/circuits/poseidon.circom";

template FingerprintVerify(bit_count, chunk_count) {
    signal input query_bits[bit_count];
    signal input record_bits[bit_count];
    signal input record_chunks[chunk_count];
    signal input threshold;

    signal output matched;
    signal output registry_commitment;

    signal diff[bit_count];
    signal partial[bit_count + 1];

    partial[0] <== 0;
    for (var i = 0; i < bit_count; i++) {
        query_bits[i] * (query_bits[i] - 1) === 0;
        record_bits[i] * (record_bits[i] - 1) === 0;
        diff[i] <== query_bits[i] + record_bits[i] - 2 * query_bits[i] * record_bits[i];
        partial[i + 1] <== partial[i] + diff[i];
    }

    for (var c = 0; c < chunk_count; c++) {
        var packed = 0;
        for (var j = 0; j < 8; j++) {
            packed += record_bits[c * 8 + j] * (1 << j);
        }
        record_chunks[c] === packed;
    }

    component commitment = Poseidon(chunk_count);
    for (var c = 0; c < chunk_count; c++) {
        commitment.inputs[c] <== record_chunks[c];
    }
    registry_commitment <== commitment.out;

    component le = LessEqThan(8);
    le.in[0] <== partial[bit_count];
    le.in[1] <== threshold;
    matched <== le.out;
}

component main {public [query_bits, threshold]} = FingerprintVerify(64, 8);
