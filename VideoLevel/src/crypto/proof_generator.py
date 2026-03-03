"""
Real Groth16 ZK-SNARK Proof Generator using snarkjs

This module implements actual ZK-SNARK proofs using snarkjs CLI,
replacing the mock implementation with real cryptographic proofs.
"""

import json
import hashlib
import subprocess
import tempfile
import time
import os
from typing import Dict, Any, Optional
from pathlib import Path


class GrothProofGenerator:
    """
    Real Groth16 proof generator using snarkjs
    
    Requires:
    - Node.js and npm installed
    - snarkjs: npm install -g snarkjs
    - circomlib: npm install circomlib
    """
    
    def __init__(self, circuit_dir: Optional[Path] = None):
        """
        Initialize proof generator
        
        Args:
            circuit_dir: Directory containing circom circuits and keys
        """
        # Add Node.js to PATH if not already there
        nodejs_path = r"C:\Program Files\nodejs"
        if nodejs_path not in os.environ.get("PATH", ""):
            os.environ["PATH"] = nodejs_path + os.pathsep + os.environ.get("PATH", "")
        
        self.circuit_dir = Path(circuit_dir) if circuit_dir else Path(__file__).parent.parent.parent.parent / "circuits"
        self.circuit_file = self.circuit_dir / "payload_verify.circom"
        self.build_dir = self.circuit_dir / "build"
        self.build_dir.mkdir(parents=True, exist_ok=True)
        
        # Check if setup has been run
        self.proving_key = self.build_dir / "proving_key.zkey"
        self.verification_key = self.build_dir / "verification_key.json"
        self.setup_complete = self.proving_key.exists() and self.verification_key.exists()
        
        if not self.setup_complete:
            print(f"⚠️  Warning: Trusted setup not complete. Run setup_circuit() first.")
    
    def setup_circuit(self, force: bool = False) -> bool:
        """
        Compile circuit and run trusted setup
        
        Args:
            force: Force recompile even if files exist
        
        Returns:
            True if setup successful
        """
        print(f"\n{'='*70}")
        print(f"GROTH16 TRUSTED SETUP")
        print(f"{'='*70}")
        
        if self.setup_complete and not force:
            print("✓ Setup already complete")
            return True
        
        try:
            print(f"\n[1/5] Compiling circuit...")
            r1cs_file = self.build_dir / "circuit.r1cs"
            wasm_dir = self.build_dir / "circuit_js"
            sym_file = self.build_dir / "circuit.sym"
            
            # Check if circom is in current directory
            circom_exe = Path("circom.exe")
            if circom_exe.exists():
                circom_cmd = str(circom_exe.absolute())
            else:
                circom_cmd = "circom"
            
            compile_cmd = [
                circom_cmd,
                str(self.circuit_file),
                "--r1cs",
                "--wasm",
                "--sym",
                "-o", str(self.build_dir),
                "-l", str(self.circuit_dir / "node_modules")
            ]
            
            result = subprocess.run(compile_cmd, capture_output=True, text=True, check=True)
            print(f"    ✓ Circuit compiled: {r1cs_file.name}")
            
            print(f"\n[2/5] Generating powers of tau (this may take a while)...")
            ptau_file = self.build_dir / "pot12_final.ptau"
            
            if not ptau_file.exists():
                # Start a new powers of tau ceremony
                subprocess.run([
                    "snarkjs", "powersoftau", "new", "bn128", "12",
                    str(self.build_dir / "pot12_0000.ptau")
                ], check=True, capture_output=True, shell=True)
                
                # Contribute to the ceremony
                subprocess.run([
                    "snarkjs", "powersoftau", "contribute",
                    str(self.build_dir / "pot12_0000.ptau"),
                    str(self.build_dir / "pot12_0001.ptau"),
                    "--name=FirstContribution", "-v"
                ], input=b"random entropy\n", check=True, capture_output=True, shell=True)
                
                # Prepare phase 2
                subprocess.run([
                    "snarkjs", "powersoftau", "prepare", "phase2",
                    str(self.build_dir / "pot12_0001.ptau"),
                    str(ptau_file)
                ], check=True, capture_output=True, shell=True)
                
                # Cleanup intermediate files
                (self.build_dir / "pot12_0000.ptau").unlink(missing_ok=True)
                (self.build_dir / "pot12_0001.ptau").unlink(missing_ok=True)
            
            print(f"    ✓ Powers of tau ready")
            
            # Step 3: Generate zkey
            print(f"\n[3/5] Generating proving key...")
            zkey_0 = self.build_dir / "circuit_0000.zkey"
            
            subprocess.run([
                "snarkjs", "groth16", "setup",
                str(r1cs_file),
                str(ptau_file),
                str(zkey_0)
            ], check=True, capture_output=True, shell=True)
            
            # Contribute to phase 2
            subprocess.run([
                "snarkjs", "zkey", "contribute",
                str(zkey_0),
                str(self.proving_key),
                "--name=Contribution1", "-v"
            ], input=b"random entropy\n", check=True, capture_output=True, shell=True)
            
            zkey_0.unlink(missing_ok=True)
            print(f"    ✓ Proving key: {self.proving_key.name}")
            
            # Step 4: Export verification key
            print(f"\n[4/5] Exporting verification key...")
            subprocess.run([
                "snarkjs", "zkey", "export", "verificationkey",
                str(self.proving_key),
                str(self.verification_key)
            ], check=True, capture_output=True, shell=True)
            print(f"    ✓ Verification key: {self.verification_key.name}")
            
            # Step 5: Verify setup
            print(f"\n[5/5] Verifying setup...")
            with open(self.verification_key, 'r') as f:
                vk = json.load(f)
                print(f"    ✓ Protocol: {vk['protocol']}")
                print(f"    ✓ Curve: {vk['curve']}")
            
            self.setup_complete = True
            print(f"\n{'='*70}")
            print(f"✓ SETUP COMPLETE")
            print(f"{'='*70}\n")
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"\n✗ Setup failed: {e}")
            print(f"  stdout: {e.stdout}")
            print(f"  stderr: {e.stderr}")
            return False
        except Exception as e:
            print(f"\n✗ Setup error: {e}")
            return False
    
    def generate_proof(self, payload: bytes, secret: str, use_binary: bool = True) -> Dict[str, Any]:
        """
        Generate real Groth16 proof for payload
        
        Args:
            payload: Data being embedded
            secret: Secret key for proof generation
            use_binary: If True, return binary serialized proof (default: True)
                       If False, return full JSON proof object
        
        Returns:
            Proof object with real Groth16 proof (binary or JSON format)
        """
        if not self.setup_complete:
            raise RuntimeError("Circuit setup not complete. Run setup_circuit() first.")
        
        # Use default secret if not provided
        if secret is None:
            secret = "default_zk_secret_2026"
        
        # Calculate payload hash
        payload_hash = hashlib.sha256(payload).digest()
        
        # Calculate commitment: SHA256(payload_hash || secret)
        hasher = hashlib.sha256()
        hasher.update(payload_hash)
        hasher.update(secret.encode('utf-8')[:32].ljust(32, b'\x00'))
        commitment = hasher.digest()
        
        # Convert to bit arrays
        payload_hash_bits = self._bytes_to_bits(payload_hash)
        commitment_bits = self._bytes_to_bits(commitment)
        secret_bits = self._bytes_to_bits(secret.encode('utf-8')[:32].ljust(32, b'\x00'))
        
        # Create witness input
        witness_input = {
            "payload_hash": payload_hash_bits,
            "commitment": commitment_bits,
            "payload_length": len(payload),
            "secret": secret_bits
        }
        
        # Generate witness and proof
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            
            # Write input
            input_file = tmpdir_path / "input.json"
            with open(input_file, 'w') as f:
                json.dump(witness_input, f)
            
            # Generate witness
            witness_file = tmpdir_path / "witness.wtns"
            wasm_file = self.build_dir / "payload_verify_js" / "payload_verify.wasm"
            
            subprocess.run([
                "node",
                str(self.build_dir / "payload_verify_js" / "generate_witness.js"),
                str(wasm_file),
                str(input_file),
                str(witness_file)
            ], check=True, capture_output=True, shell=True)
            
            # Generate proof
            proof_file = tmpdir_path / "proof.json"
            public_file = tmpdir_path / "public.json"
            
            subprocess.run([
                "snarkjs", "groth16", "prove",
                str(self.proving_key),
                str(witness_file),
                str(proof_file),
                str(public_file)
            ], check=True, capture_output=True, shell=True)
            
            # Read proof
            with open(proof_file, 'r') as f:
                proof = json.load(f)
            
            with open(public_file, 'r') as f:
                public_inputs = json.load(f)
        
        proof_obj = {
            "version": "2.0",
            "algorithm": "groth16-snarkjs",
            "timestamp": int(time.time()),
            "commitment": commitment.hex(),
            "proof": proof,
            "public_inputs": {
                "payload_hash": payload_hash.hex(),
                "payload_length": len(payload),
                "commitment": commitment.hex(),
                "public_signals": public_inputs
            },
            "metadata": {
                "generator": "zk-mv-stego-snarkjs",
                "curve": "bn128",
                "security_level": 128,
                "circuit": "payload_verify"
            }
        }
        
        # Binary serialization with options
        if use_binary:
            from .proof_serializer import ProofSerializer
            
            # Use compact format (336 bytes: header + commitment + π_A + π_B + π_C + signals_hash)
            # Public signals can be recomputed from payload during verification
            binary_proof = ProofSerializer.serialize(proof_obj)
            
            return {
                "format": "binary_compact",
                "proof_data": binary_proof,
                "size_bytes": len(binary_proof),
                "commitment": commitment.hex(),
                "payload_length": len(payload),
                "timestamp": proof_obj["timestamp"],
                "note": "Compact binary Groth16 proof (336 bytes)"
            }
        
        return proof_obj
    
    def verify_proof(self, proof_obj: Dict[str, Any], payload: bytes) -> bool:
        """
        Verify real Groth16 proof using snarkjs
        
        Args:
            proof_obj: Proof object from generate_proof()
            payload: Extracted payload data
        
        Returns:
            True if proof is valid
        """
        if not self.setup_complete:
            raise RuntimeError("Circuit setup not complete.")
        
        # Verify payload hash matches
        expected_hash = proof_obj["public_inputs"]["payload_hash"]
        actual_hash = hashlib.sha256(payload).hexdigest()
        
        if expected_hash != actual_hash:
            print("✗ Payload hash mismatch")
            return False
        
        # Verify payload length
        expected_length = proof_obj["public_inputs"]["payload_length"]
        if len(payload) != expected_length:
            print("✗ Payload length mismatch")
            return False
        
        # Verify Groth16 proof using snarkjs
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            
            # Write proof and public inputs
            proof_file = tmpdir_path / "proof.json"
            public_file = tmpdir_path / "public.json"
            
            with open(proof_file, 'w') as f:
                json.dump(proof_obj["proof"], f)
            
            with open(public_file, 'w') as f:
                json.dump(proof_obj["public_inputs"]["public_signals"], f)
            
            # Verify using snarkjs
            try:
                result = subprocess.run([
                    "snarkjs", "groth16", "verify",
                    str(self.verification_key),
                    str(public_file),
                    str(proof_file)
                ], check=True, capture_output=True, text=True, shell=True)
                
                # Check output for "OK"
                return "OK" in result.stdout
                
            except subprocess.CalledProcessError:
                return False
    
    def serialize_proof(self, proof_obj: Dict[str, Any]) -> bytes:
        """Serialize proof to bytes"""
        json_str = json.dumps(proof_obj, separators=(',', ':'))
        return json_str.encode('utf-8')
    
    def deserialize_proof(self, proof_bytes: bytes) -> Dict[str, Any]:
        """Deserialize proof from bytes"""
        json_str = proof_bytes.decode('utf-8')
        return json.loads(json_str)
    
    def _bytes_to_bits(self, data: bytes) -> list:
        """Convert bytes to bit array"""
        bits = []
        for byte in data:
            for i in range(7, -1, -1):
                bits.append((byte >> i) & 1)
        return bits
    
    def _bits_to_bytes(self, bits: list) -> bytes:
        """Convert bit array to bytes"""
        byte_array = []
        for i in range(0, len(bits), 8):
            byte = 0
            for j in range(8):
                if i + j < len(bits):
                    byte |= bits[i + j] << (7 - j)
            byte_array.append(byte)
        return bytes(byte_array)


# Backward compatibility: keep ZKProofGenerator as alias
ZKProofGenerator = GrothProofGenerator


def test_real_groth16():
    """Test real Groth16 implementation"""
    print("="*70)
    print("REAL GROTH16 ZK-SNARK TEST")
    print("="*70)
    
    generator = GrothProofGenerator()
    
    # Run setup if needed
    if not generator.setup_complete:
        print("\n⚠️  Running trusted setup (this may take a few minutes)...")
        if not generator.setup_circuit():
            print("✗ Setup failed!")
            return
    
    # Test data
    payload = b"Secret message to embed in video"
    secret = "my_secret_key_12345"
    
    print(f"\n[1] Generating real Groth16 proof...")
    print(f"    Payload: {len(payload)} bytes")
    print(f"    Secret: {secret}")
    
    start = time.time()
    proof_obj = generator.generate_proof(payload, secret)
    gen_time = time.time() - start
    
    print(f"\n[2] Proof generated in {gen_time:.3f}s:")
    print(f"    Algorithm: {proof_obj['algorithm']}")
    print(f"    Commitment: {proof_obj['commitment'][:32]}...")
    print(f"    Curve: {proof_obj['metadata']['curve']}")
    
    # Serialize
    proof_bytes = generator.serialize_proof(proof_obj)
    print(f"\n[3] Serialized proof: {len(proof_bytes)} bytes")
    
    # Verify
    print(f"\n[4] Verifying proof...")
    start = time.time()
    is_valid = generator.verify_proof(proof_obj, payload)
    verify_time = time.time() - start
    
    print(f"    Valid: {is_valid} (verified in {verify_time:.3f}s)")
    
    # Test with wrong payload
    print(f"\n[5] Testing with wrong payload...")
    wrong_payload = b"Wrong message"
    is_valid_wrong = generator.verify_proof(proof_obj, wrong_payload)
    print(f"    Valid: {is_valid_wrong} (should be False)")
    
    print("\n" + "="*70)
    if is_valid and not is_valid_wrong:
        print("[SUCCESS] Real Groth16 working correctly!")
    else:
        print("[FAILED] Verification issues")
    print("="*70)


if __name__ == '__main__':
    test_real_groth16()
