pragma circom 2.0.0;

include "node_modules/circomlib/circuits/comparators.circom";
include "node_modules/circomlib/circuits/poseidon.circom";

template DetectorReceipt(feature_count) {
    signal input features[feature_count];
    signal input weights[feature_count];
    signal input threshold;

    signal output accepted;
    signal output detector_commitment;

    signal score[feature_count + 1];
    component feature_bits[feature_count];
    component weight_bits[feature_count];

    score[0] <== 0;
    for (var i = 0; i < feature_count; i++) {
        feature_bits[i] = Num2Bits(16);
        weight_bits[i] = Num2Bits(16);
        feature_bits[i].in <== features[i];
        weight_bits[i].in <== weights[i];
        score[i + 1] <== score[i] + features[i] * weights[i];
    }

    component commitment = Poseidon(feature_count);
    for (var i = 0; i < feature_count; i++) {
        commitment.inputs[i] <== weights[i];
    }
    detector_commitment <== commitment.out;

    component ge = GreaterEqThan(32);
    ge.in[0] <== score[feature_count];
    ge.in[1] <== threshold;
    accepted <== ge.out;
}

component main {public [features, threshold]} = DetectorReceipt(4);
