pragma circom 2.1.0;

// CameraVideo: "a registered camera vouches for this video and message".
//
// Private: the camera secret s and the Merkle path of pk = Poseidon(s) in the
//          registry tree (Poseidon(2) nodes, depth DEPTH, empty leaves = 0).
// Public:  root       - registry root the verifier trusts,
//          bindingHi  - high 128 bits of SHA256(binding preimage),
//          bindingLo  - low 128 bits.
// The binding preimage covers the masked video digest and SHA256(message)
// (src/video_binding.py). The verifier never learns s or which leaf was used,
// and a proof made for one video/message does not verify for another.

include "node_modules/circomlib/circuits/poseidon.circom";

// Recomputes the root of a Poseidon Merkle tree from a leaf and its path.
// pathIndices[i] = 0 when the running node is the left child at level i.
template MerkleInclusion(DEPTH) {
    signal input leaf;
    signal input siblings[DEPTH];
    signal input pathIndices[DEPTH];
    signal output root;

    signal node[DEPTH + 1];
    signal left[DEPTH];
    signal right[DEPTH];
    component hashes[DEPTH];
    node[0] <== leaf;
    for (var i = 0; i < DEPTH; i++) {
        pathIndices[i] * (pathIndices[i] - 1) === 0;
        left[i] <== node[i] + pathIndices[i] * (siblings[i] - node[i]);
        right[i] <== siblings[i] + pathIndices[i] * (node[i] - siblings[i]);
        hashes[i] = Poseidon(2);
        hashes[i].inputs[0] <== left[i];
        hashes[i].inputs[1] <== right[i];
        node[i + 1] <== hashes[i].out;
    }
    root <== node[DEPTH];
}

template CameraVideo(DEPTH) {
    signal input secret;
    signal input siblings[DEPTH];
    signal input pathIndices[DEPTH];
    signal input root;
    signal input bindingHi;
    signal input bindingLo;

    component publicKey = Poseidon(1);
    publicKey.inputs[0] <== secret;

    component membership = MerkleInclusion(DEPTH);
    membership.leaf <== publicKey.out;
    for (var i = 0; i < DEPTH; i++) {
        membership.siblings[i] <== siblings[i];
        membership.pathIndices[i] <== pathIndices[i];
    }
    membership.root === root;

    // Public inputs that no other constraint uses are still part of the proof,
    // but squaring them ties them into the R1CS explicitly (Semaphore-style).
    signal bindingHiSquare <== bindingHi * bindingHi;
    signal bindingLoSquare <== bindingLo * bindingLo;
}

component main {public [root, bindingHi, bindingLo]} = CameraVideo(16);
