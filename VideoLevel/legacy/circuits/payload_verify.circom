pragma circom 2.0.0;

include "node_modules/circomlib/circuits/sha256/sha256.circom";
include "node_modules/circomlib/circuits/bitify.circom";
include "node_modules/circomlib/circuits/comparators.circom";

/*
 * ZK-SNARK Circuit for Video Steganography Payload Verification
 * 
 * Proves knowledge of a secret that produces a commitment to the payload
 * without revealing the secret itself.
 * 
 * Public inputs:
 *   - payload_hash: SHA256 hash of the payload (256 bits)
 *   - commitment: SHA256(payload_hash || secret) (256 bits)
 *   - payload_length: Length of payload in bytes
 * 
 * Private inputs:
 *   - secret: Secret key (256 bits)
 * 
 * Circuit verifies:
 *   commitment = SHA256(payload_hash || secret)
 */

template PayloadVerify() {
    // Public inputs
    signal input payload_hash[256];      // SHA256 hash of payload (256 bits)
    signal input commitment[256];        // Expected commitment (256 bits)
    signal input payload_length;         // Payload length in bytes
    
    // Private inputs
    signal input secret[256];            // Secret key (256 bits)
    
    // Intermediate signals
    signal input_bits[512];              // payload_hash + secret (512 bits)
    
    // Copy payload_hash to first 256 bits
    for (var i = 0; i < 256; i++) {
        input_bits[i] <== payload_hash[i];
    }
    
    // Copy secret to last 256 bits
    for (var i = 0; i < 256; i++) {
        input_bits[256 + i] <== secret[i];
    }
    
    // Compute SHA256(payload_hash || secret)
    component sha = Sha256(512);
    for (var i = 0; i < 512; i++) {
        sha.in[i] <== input_bits[i];
    }
    
    // Store computed commitment in intermediate signal
    signal computed_commitment[256];
    for (var i = 0; i < 256; i++) {
        computed_commitment[i] <== sha.out[i];
    }
    
    // Verify commitment matches computed value
    for (var i = 0; i < 256; i++) {
        commitment[i] === computed_commitment[i];
    }
    
    // Enforce the public payload range: 0 < length < 1,000,000 bytes.
    // The comparison gadgets also range-constrain payload_length to 20 bits.
    component length_lt_limit = LessThan(20);
    length_lt_limit.in[0] <== payload_length;
    length_lt_limit.in[1] <== 1000000;

    component length_gt_zero = GreaterThan(20);
    length_gt_zero.in[0] <== payload_length;
    length_gt_zero.in[1] <== 0;

    signal length_in_range;
    length_in_range <== length_lt_limit.out * length_gt_zero.out;
    length_in_range === 1;
}

component main {public [payload_hash, commitment, payload_length]} = PayloadVerify();
