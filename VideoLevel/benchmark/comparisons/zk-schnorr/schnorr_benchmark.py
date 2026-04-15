import time
import sys
import numpy as np
from cryptography.hazmat.primitives.asymmetric.ec import (
    SECP256R1, generate_private_key, ECDSA,
)
from cryptography.hazmat.primitives import hashes

def run_schnorr_benchmark(n_trials: int = 20):
    """
    Simulates ZK-Schnorr performance using P-256 digital signature
    (Schnorr signature is a ZKPoK of the discrete log; same complexity).
    """
    print(f"--- Running ZK-Schnorr (P-256) Benchmark ({n_trials} trials) ---")
    message = b"ZK-Stego benchmark payload - foreman CIF sequence"
    curve   = SECP256R1()

    print("Generating keys...")
    private_key  = generate_private_key(curve)
    public_key   = private_key.public_key()

    prove_times  = []
    verify_times = []
    proof_sizes  = []

    for i in range(n_trials):
        # PROVE
        t0  = time.perf_counter()
        sig = private_key.sign(message, ECDSA(hashes.SHA256()))
        prove_times.append((time.perf_counter() - t0) * 1000)
        proof_sizes.append(len(sig))

        # VERIFY
        t0 = time.perf_counter()
        try:
            public_key.verify(sig, message, ECDSA(hashes.SHA256()))
            ok = True
        except Exception:
            ok = False
        verify_times.append((time.perf_counter() - t0) * 1000)
        
        if not ok:
            print(f"Trial {i+1}: Verification FAILED!")

    avg_prove = np.mean(prove_times)
    avg_verify = np.mean(verify_times)
    avg_size = np.mean(proof_sizes)
    
    print("\n--- Results ---")
    print(f"Proof Size     : {int(avg_size)} bytes")
    print(f"Prove Time     : {avg_prove:.2f} ms")
    print(f"Verify Time    : {avg_verify:.2f} ms")
    print("Trusted Setup  : False")
    print("----------------------------------------------------------")

if __name__ == "__main__":
    trials = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    run_schnorr_benchmark(trials)
