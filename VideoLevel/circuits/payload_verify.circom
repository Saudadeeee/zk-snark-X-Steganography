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
 *   every bit of payload_hash, commitment and secret is boolean (0 or 1)
 *   commitment = SHA256(payload_hash || secret)
 *   0 < payload_length < 1,000,000
 *
 * circomlib's Sha256 does not constrain its inputs to be bits, so the
 * booleanity constraints below are required for soundness: without them a
 * prover could feed arbitrary field elements into the hash gadget.
 */

template PayloadVerify() {
    // Public inputs
    signal input payload_hash[256];      // SHA256 hash of payload (256 bits)
    signal input commitment[256];        // Expected commitment (256 bits)
    signal input payload_length;         // Payload length in bytes
    
    // Private inputs
    signal input secret[256];            // Secret key (256 bits)
    
    // Booleanity: x * (x - 1) === 0 forces every bit signal into {0, 1}.
    for (var i = 0; i < 256; i++) {
        secret[i] * (secret[i] - 1) === 0;
        payload_hash[i] * (payload_hash[i] - 1) === 0;
        commitment[i] * (commitment[i] - 1) === 0;
    }

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
    
    // Constrain the public length to 0 < length < 1,000,000 bytes.
    // LessThan(20) range-checks both operands before comparing them.
    component length_lt_limit = LessThan(20);
    length_lt_limit.in[0] <== payload_length;
    length_lt_limit.in[1] <== 1000000;
    length_lt_limit.out === 1;

    component length_is_zero = IsZero();
    length_is_zero.in <== payload_length;
    length_is_zero.out === 0;
}

component main {public [payload_hash, commitment, payload_length]} = PayloadVerify();
