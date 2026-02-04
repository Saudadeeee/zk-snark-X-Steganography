"""
Complete zkSNARK Integration Workflow

Integrates zkproof_sei_tool with real Groth16 proofs from snarkjs/circom.
Provides end-to-end workflow: proof generation → embedding → extraction → verification
"""

import os
import sys
import json
import subprocess
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple, Any

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from src.zk_mv_stego.crypto.groth16_serializer import Groth16Serializer
from src.zk_mv_stego.bitstream.zkproof_sei_handler import ZKProofSEIHandler


class ZKSnarkVideoWorkflow:
    """Complete workflow for zkSNARK proof embedding in video"""
    
    def __init__(self, circuit_dir: str = "circuits"):
        self.circuit_dir = Path(circuit_dir)
        self.build_dir = self.circuit_dir / "build"
        self.serializer = Groth16Serializer()
        self.sei_handler = ZKProofSEIHandler()
        
        # Circuit artifacts
        self.wasm_file = self.build_dir / "payload_verify_js" / "payload_verify.wasm"
        self.zkey_file = self.build_dir / "proving_key.zkey"
        self.vkey_file = self.build_dir / "verification_key.json"
        
    def check_dependencies(self) -> bool:
        """Check if snarkjs is installed"""
        try:
            result = subprocess.run(
                ['snarkjs', '--version'],
                capture_output=True,
                text=True,
                timeout=5,
                shell=True  # Windows needs shell=True for .cmd files
            )
            # snarkjs returns exit code 1 even with --version, check output instead
            if 'snarkjs' in result.stdout.lower() or 'snarkjs' in result.stderr.lower():
                # Extract version if present
                for line in (result.stdout + result.stderr).split('\n'):
                    if 'snarkjs@' in line:
                        print(f"✅ {line.strip()}")
                        return True
                print("✅ snarkjs installed")
                return True
            else:
                print("❌ snarkjs not working properly")
                return False
        except FileNotFoundError:
            print("❌ snarkjs not found. Install: npm install -g snarkjs")
            return False
        except Exception as e:
            print(f"❌ Error checking snarkjs: {e}")
            return False
    
    def check_circuit_artifacts(self) -> bool:
        """Check if circuit is compiled and keys are generated"""
        required_files = [
            self.wasm_file,
            self.zkey_file,
            self.vkey_file
        ]
        
        all_exist = True
        for file in required_files:
            if file.exists():
                print(f"✅ Found: {file.name}")
            else:
                print(f"❌ Missing: {file}")
                all_exist = False
        
        return all_exist
    
    def generate_input(self, payload_data: bytes, secret: str = None) -> Dict[str, Any]:
        """
        Generate circuit input from payload data
        
        Args:
            payload_data: The actual payload to embed (video data, message, etc.)
            secret: Secret key (256-bit hex string). If None, generates random.
        
        Returns:
            Dict with circuit inputs
        """
        # Generate payload hash (SHA256)
        payload_hash = hashlib.sha256(payload_data).digest()
        payload_hash_bits = self._bytes_to_bits(payload_hash)
        
        # Generate or use provided secret
        if secret is None:
            secret_bytes = os.urandom(32)
            secret_hex = secret_bytes.hex()
        else:
            secret_hex = secret
            secret_bytes = bytes.fromhex(secret_hex)
        
        secret_bits = self._bytes_to_bits(secret_bytes)
        
        # Compute commitment: SHA256(payload_hash || secret)
        commitment_input = payload_hash + secret_bytes
        commitment = hashlib.sha256(commitment_input).digest()
        commitment_bits = self._bytes_to_bits(commitment)
        
        # Circuit input
        circuit_input = {
            "payload_hash": payload_hash_bits,
            "commitment": commitment_bits,
            "payload_length": len(payload_data),
            "secret": secret_bits
        }
        
        return circuit_input, secret_hex
    
    def _bytes_to_bits(self, data: bytes) -> List[str]:
        """Convert bytes to bit array (as strings for JSON)"""
        bits = []
        for byte in data:
            for i in range(8):
                bits.append(str((byte >> (7 - i)) & 1))
        return bits
    
    def _bits_to_bytes(self, bits: List[str]) -> bytes:
        """Convert bit array to bytes"""
        result = bytearray()
        for i in range(0, len(bits), 8):
            byte_bits = bits[i:i+8]
            byte_val = 0
            for bit in byte_bits:
                byte_val = (byte_val << 1) | int(bit)
            result.append(byte_val)
        return bytes(result)
    
    def generate_proof(self, circuit_input: Dict[str, Any], input_file: str = None) -> Tuple[Dict, List]:
        """
        Generate Groth16 proof using snarkjs
        
        Args:
            circuit_input: Circuit input dict
            input_file: Optional path to save input JSON
        
        Returns:
            Tuple of (proof, publicSignals)
        """
        # Save input to temp file
        if input_file is None:
            input_file = "data/output/input.json"
        
        os.makedirs(os.path.dirname(input_file), exist_ok=True)
        with open(input_file, 'w') as f:
            json.dump(circuit_input, f, indent=2)
        
        print(f"\n🔐 Generating zkSNARK proof...")
        print(f"   Circuit: {self.wasm_file.name}")
        print(f"   Input: {input_file}")
        
        # Generate witness
        witness_file = "data/output/witness.wtns"
        print(f"\n[1/3] Calculating witness...")
        cmd = [
            'snarkjs', 'wtns', 'calculate',
            str(self.wasm_file),
            input_file,
            witness_file
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        if result.returncode != 0:
            raise RuntimeError(f"Witness generation failed: {result.stderr}")
        print(f"      ✅ Witness generated: {witness_file}")
        
        # Generate proof
        proof_file = "data/output/proof.json"
        public_file = "data/output/public.json"
        
        print(f"\n[2/3] Generating proof...")
        cmd = [
            'snarkjs', 'groth16', 'prove',
            str(self.zkey_file),
            witness_file,
            proof_file,
            public_file
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        if result.returncode != 0:
            raise RuntimeError(f"Proof generation failed: {result.stderr}")
        print(f"      ✅ Proof generated: {proof_file}")
        
        # Load proof
        with open(proof_file) as f:
            proof = json.load(f)
        
        with open(public_file) as f:
            public_signals = json.load(f)
        
        print(f"\n[3/3] Proof ready!")
        print(f"      Protocol: {proof.get('protocol', 'groth16')}")
        print(f"      Curve: {proof.get('curve', 'bn128')}")
        print(f"      Public signals: {len(public_signals)}")
        
        return proof, public_signals
    
    def verify_proof(self, proof: Dict, public_signals: List) -> bool:
        """
        Verify Groth16 proof using snarkjs
        
        Args:
            proof: Groth16 proof dict
            public_signals: Public signals list
        
        Returns:
            bool: True if valid
        """
        # Save to temp files
        proof_file = "data/output/verify_proof.json"
        public_file = "data/output/verify_public.json"
        
        with open(proof_file, 'w') as f:
            json.dump(proof, f)
        
        with open(public_file, 'w') as f:
            json.dump(public_signals, f)
        
        print(f"\n🔍 Verifying proof...")
        cmd = [
            'snarkjs', 'groth16', 'verify',
            str(self.vkey_file),
            public_file,
            proof_file
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        
        if result.returncode == 0 and "OK" in result.stdout:
            print("   ✅ Proof VALID")
            return True
        else:
            print(f"   ❌ Proof INVALID")
            print(f"   Output: {result.stdout}")
            return False
    
    def prover_workflow(self, video_path: str, payload_data: bytes, output_video: str) -> Dict:
        """
        Complete prover workflow: generate proof → embed in video
        
        Args:
            video_path: Input video path
            payload_data: Data to prove knowledge of
            output_video: Output video path
        
        Returns:
            Dict with workflow results
        """
        print("=" * 60)
        print("🎬 PROVER WORKFLOW: Generate + Embed")
        print("=" * 60)
        
        # Generate circuit input
        print("\n[1/5] Generating circuit input...")
        circuit_input, secret = self.generate_input(payload_data)
        print(f"      ✅ Payload hash: {hashlib.sha256(payload_data).hexdigest()[:16]}...")
        print(f"      ✅ Secret: {secret[:16]}...")
        print(f"      ✅ Payload length: {len(payload_data)} bytes")
        
        # Generate proof
        print("\n[2/5] Generating zkSNARK proof...")
        proof, public_signals = self.generate_proof(circuit_input)
        
        # Serialize proof
        print("\n[3/5] Serializing proof to binary...")
        # Store as JSON for reliability
        proof_json = json.dumps({
            'proof': proof,
            'publicSignals': public_signals
        }, separators=(',', ':'))  # Compact JSON
        
        proof_bytes = proof_json.encode('utf-8')
        
        print(f"      ✅ Serialized: {len(proof_bytes)} bytes")
        print(f"      Format: JSON (for reliability)")
        
        # Verify proof before embedding
        print("\n[4/5] Pre-verification...")
        if self.verify_proof(proof, public_signals):
            print("      ✅ Proof valid before embedding")
        else:
            raise RuntimeError("Proof verification failed!")
        
        # Embed in video
        print("\n[5/5] Embedding proof in video...")
        stats = self.sei_handler.embed_proof_in_video(
            video_path,
            proof_bytes,
            output_video
        )
        
        if stats['success']:
            print(f"      ✅ Embedded successfully")
            print(f"      Output: {output_video}")
            print(f"      Size: {stats['output_size']} bytes (+{stats['sei_size']} bytes)")
        else:
            raise RuntimeError("Embedding failed!")
        
        print("\n" + "=" * 60)
        print("✅ PROVER WORKFLOW COMPLETE")
        print("=" * 60)
        
        return {
            'success': True,
            'secret': secret,
            'proof': proof,
            'public_signals': public_signals,
            'output_video': output_video,
            'stats': stats
        }
    
    def verifier_workflow(self, video_path: str) -> Dict:
        """
        Complete verifier workflow: extract proof → verify
        
        Args:
            video_path: Video containing embedded proof
        
        Returns:
            Dict with verification results
        """
        print("=" * 60)
        print("🔍 VERIFIER WORKFLOW: Extract + Verify")
        print("=" * 60)
        
        # Extract proof
        print("\n[1/3] Extracting proof from video...")
        proof_bytes, stats = self.sei_handler.extract_proof_from_video(video_path)
        
        if proof_bytes is None:
            raise RuntimeError("Proof extraction failed!")
        
        print(f"      ✅ Extracted: {len(proof_bytes)} bytes")
        print(f"      SEI index: {stats.get('sei_index', 'unknown')}")
        
        # Deserialize proof
        print("\n[2/3] Deserializing proof...")
        
        # Decode JSON
        proof_json = proof_bytes.decode('utf-8')
        proof_data = json.loads(proof_json)
        
        proof = proof_data['proof']
        public_signals = proof_data['publicSignals']
        
        print(f"      ✅ Proof structure restored")
        print(f"      ✅ Public signals loaded: {len(public_signals)} signals")
        
        # Verify proof
        print("\n[3/3] Verifying zkSNARK proof...")
        is_valid = self.verify_proof(proof, public_signals)
        
        if is_valid:
            print("\n" + "=" * 60)
            print("✅ VERIFIER WORKFLOW COMPLETE - PROOF VALID")
            print("=" * 60)
        else:
            print("\n" + "=" * 60)
            print("❌ VERIFIER WORKFLOW FAILED - PROOF INVALID")
            print("=" * 60)
        
        return {
            'success': is_valid,
            'proof': proof,
            'public_signals': public_signals,
            'stats': stats
        }


# Command-line interface
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="zkSNARK Video Steganography - Complete Workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check setup
  python zk_snark_workflow.py check
  
  # Prover: Generate proof and embed in video
  python zk_snark_workflow.py prove \\
      -i data/raw/bus_simple.h264 \\
      -m "Secret message" \\
      -o data/output/video_with_proof.h264
  
  # Verifier: Extract and verify proof
  python zk_snark_workflow.py verify \\
      -i data/output/video_with_proof.h264
  
  # Complete workflow (prove + verify)
  python zk_snark_workflow.py workflow \\
      -i data/raw/bus_simple.h264 \\
      -m "Test payload"
        """
    )
    
    parser.add_argument('command', choices=['check', 'prove', 'verify', 'workflow'],
                        help='Command to execute')
    parser.add_argument('-i', '--input', help='Input video path')
    parser.add_argument('-m', '--message', help='Message/payload data')
    parser.add_argument('-o', '--output', help='Output video path')
    
    args = parser.parse_args()
    
    workflow = ZKSnarkVideoWorkflow()
    
    if args.command == 'check':
        print("🔍 Checking zkSNARK setup...\n")
        deps_ok = workflow.check_dependencies()
        circuit_ok = workflow.check_circuit_artifacts()
        
        if deps_ok and circuit_ok:
            print("\n✅ All checks passed! Ready to use.")
            sys.exit(0)
        else:
            print("\n❌ Setup incomplete. Please fix issues above.")
            sys.exit(1)
    
    elif args.command == 'prove':
        if not args.input or not args.message:
            print("❌ Error: --input and --message required for prove")
            sys.exit(1)
        
        output = args.output or "data/output/video_with_proof.h264"
        payload = args.message.encode('utf-8')
        
        result = workflow.prover_workflow(args.input, payload, output)
        
        print(f"\n📋 Save this secret for verification: {result['secret']}")
    
    elif args.command == 'verify':
        if not args.input:
            print("❌ Error: --input required for verify")
            sys.exit(1)
        
        result = workflow.verifier_workflow(args.input)
        
        if result['success']:
            sys.exit(0)
        else:
            sys.exit(1)
    
    elif args.command == 'workflow':
        if not args.input or not args.message:
            print("❌ Error: --input and --message required for workflow")
            sys.exit(1)
        
        output = args.output or "data/output/video_with_proof.h264"
        payload = args.message.encode('utf-8')
        
        # Prover
        prover_result = workflow.prover_workflow(args.input, payload, output)
        
        # Verifier
        verifier_result = workflow.verifier_workflow(output)
        
        if verifier_result['success']:
            print("\n🎉 COMPLETE WORKFLOW SUCCESS!")
            sys.exit(0)
        else:
            print("\n❌ Workflow failed at verification")
            sys.exit(1)
