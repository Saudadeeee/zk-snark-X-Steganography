"""
Phase 2: ZK-SNARK Proof Integration
====================================

Integrate ImageLevel ZK-SNARK system with VideoLevel MV embedding.

Workflow:
1. Generate ZK proof for message (using ImageLevel/Circom)
2. Serialize proof to bytes (~256 bytes Groth16)
3. Embed proof into video MVs (using Phase 1 pipeline)
4. Extract and verify proof from stego video

Components:
- zk_proof_wrapper.py:    Generate/verify Groth16 proofs
- video_prover.py:        Embed ZK proof into video
- video_verifier.py:      Extract and verify proof from video
- quality_metrics.py:     PSNR, SSIM, VMAF assessment
"""

import json
import sys
import subprocess
import os
from pathlib import Path
from typing import Dict, Tuple, Optional, Any
import hashlib

# Add ImageLevel to path for ZK-SNARK utilities
IMAGE_LEVEL_PATH = Path(__file__).parent.parent.parent.parent / "ImageLevel"
sys.path.insert(0, str(IMAGE_LEVEL_PATH / "src"))


class ZKProofWrapper:
    """
    Wrapper for ZK-SNARK proof generation and verification
    Uses Circom circuits from ImageLevel
    """
    
    def __init__(self, circuit_dir: Optional[str] = None):
        """
        Initialize ZK proof wrapper
        
        Args:
            circuit_dir: Path to circuit build directory
                        Default: ImageLevel/circuits/compiled/build/
        """
        if circuit_dir is None:
            self.circuit_dir = IMAGE_LEVEL_PATH / "circuits" / "compiled" / "build"
        else:
            self.circuit_dir = Path(circuit_dir)
        
        # Circuit files
        self.wasm = self.circuit_dir / "chaos_zk_stego_js" / "chaos_zk_stego.wasm"
        self.zkey = self.circuit_dir / "chaos_zk_stego.zkey"
        self.vkey = self.circuit_dir / "chaos_zk_stego_verification_key.json"
        
        # Verify files exist
        if not self.wasm.exists():
            raise FileNotFoundError(f"WASM file not found: {self.wasm}")
        if not self.zkey.exists():
            raise FileNotFoundError(f"Proving key not found: {self.zkey}")
        if not self.vkey.exists():
            raise FileNotFoundError(f"Verification key not found: {self.vkey}")
        
        print(f"[ZK] Initialized with circuit: {self.circuit_dir}")
    
    def generate_proof(self,
                      message: str,
                      chaos_key: str,
                      video_hash: str) -> Dict[str, Any]:
        """
        Generate ZK-SNARK proof for message embedding
        
        Args:
            message: Secret message to embed
            chaos_key: Secret chaos key for embedding positions
            video_hash: Public hash of cover video (for binding)
            
        Returns:
            {
                'proof': Groth16 proof object,
                'public_signals': Public inputs,
                'proof_bytes': Serialized proof (~256 bytes)
            }
        """
        print(f"\n{'='*60}")
        print("ZK PROOF GENERATION")
        print(f"{'='*60}")
        
        # Prepare witness input
        witness_input = self._prepare_witness(message, chaos_key, video_hash)
        
        print(f"[1] Witness input prepared:")
        print(f"    Message length: {len(message)} chars")
        print(f"    Chaos key: {chaos_key[:10]}...")
        print(f"    Video hash: {video_hash[:16]}...")
        
        # Generate witness
        witness_file = Path("temp_witness.json")
        with open(witness_file, 'w') as f:
            json.dump(witness_input, f)
        
        # Call snarkjs to generate proof
        try:
            # Generate witness
            print(f"\n[2] Generating witness...")
            witness_result = subprocess.run([
                'node',
                str(self.wasm.parent / 'generate_witness.js'),
                str(self.wasm),
                str(witness_file),
                'witness.wtns'
            ], capture_output=True, text=True, check=True)
            
            # Generate proof
            print(f"[3] Generating Groth16 proof...")
            # Use snarkjs.cmd on Windows
            snarkjs_cmd = 'snarkjs.cmd' if os.name == 'nt' else 'snarkjs'
            proof_result = subprocess.run([
                snarkjs_cmd,
                'groth16',
                'prove',
                str(self.zkey),
                'witness.wtns',
                'proof.json',
                'public.json'
            ], capture_output=True, text=True, check=True)
            
            # Read proof and public signals
            with open('proof.json', 'r') as f:
                proof = json.load(f)
            
            with open('public.json', 'r') as f:
                public_signals = json.load(f)
            
            # Serialize proof to bytes
            proof_bytes = self._serialize_proof(proof, public_signals)
            
            print(f"[4] Proof generated:")
            print(f"    Proof size: {len(proof_bytes)} bytes")
            print(f"    Public signals: {len(public_signals)} elements")
            
            # Cleanup
            for f in [witness_file, 'witness.wtns', 'proof.json', 'public.json']:
                if Path(f).exists():
                    Path(f).unlink()
            
            return {
                'proof': proof,
                'public_signals': public_signals,
                'proof_bytes': proof_bytes,
                'proof_size': len(proof_bytes)
            }
            
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Proof generation failed: {e}")
            print(f"STDOUT: {e.stdout}")
            print(f"STDERR: {e.stderr}")
            raise
    
    def verify_proof(self, proof_bytes: bytes) -> Tuple[bool, Dict]:
        """
        Verify ZK-SNARK proof
        
        Args:
            proof_bytes: Serialized proof bytes
            
        Returns:
            (valid, proof_data) tuple
        """
        print(f"\n{'='*60}")
        print("ZK PROOF VERIFICATION")
        print(f"{'='*60}")
        
        # Deserialize proof
        proof, public_signals = self._deserialize_proof(proof_bytes)
        
        print(f"[1] Proof deserialized:")
        print(f"    Size: {len(proof_bytes)} bytes")
        print(f"    Public signals: {len(public_signals)} elements")
        
        # Save to temp files
        with open('temp_proof.json', 'w') as f:
            json.dump(proof, f)
        
        with open('temp_public.json', 'w') as f:
            json.dump(public_signals, f)
        
        # Verify with snarkjs
        try:
            print(f"[2] Verifying with snarkjs...")
            snarkjs_cmd = 'snarkjs.cmd' if os.name == 'nt' else 'snarkjs'
            result = subprocess.run([
                snarkjs_cmd,
                'groth16',
                'verify',
                str(self.vkey),
                'temp_public.json',
                'temp_proof.json'
            ], capture_output=True, text=True, check=True)
            
            valid = 'OK' in result.stdout
            
            print(f"[3] Verification result: {'VALID' if valid else 'INVALID'}")
            
            # Cleanup
            for f in ['temp_proof.json', 'temp_public.json']:
                if Path(f).exists():
                    Path(f).unlink()
            
            return valid, {
                'proof': proof,
                'public_signals': public_signals
            }
            
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Verification failed: {e}")
            return False, {}
    
    def _prepare_witness(self, message: str, chaos_key: str, video_hash: str) -> Dict:
        """
        Prepare witness input for ImageLevel circuit (chaos_zk_stego.circom)
        
        Circuit expects:
        - commitmentRoot: Merkle root of positions
        - proofLength: Length of proof
        - timestamp: Unix timestamp
        - x0, y0: Initial chaos coordinates
        - chaosKey: Chaos key as integer
        - proofBits[32]: Message bits (32 bits)
        - positions[16][2]: Embedding positions
        - imageHash: Hash of cover (video in our case)
        """
        import time
        
        # Convert message to bits (truncate to 32 bits for circuit)
        message_hash = hashlib.sha256(message.encode()).digest()
        proof_bits = []
        for byte in message_hash[:4]:  # 4 bytes = 32 bits
            for i in range(8):
                proof_bits.append((byte >> i) & 1)
        
        # Generate chaos key integer
        chaos_hash = hashlib.sha256(chaos_key.encode()).digest()
        chaos_key_int = int.from_bytes(chaos_hash[:8], 'big') % (2**254)
        
        # Video hash as field element
        video_hash_bytes = hashlib.sha256(video_hash.encode()).digest()
        image_hash_single = int.from_bytes(video_hash_bytes[:31], 'big') % (2**254)
        
        # Generate dummy positions (for circuit, not used in video embedding)
        positions = []
        for i in range(16):
            x = (i * 17 + 5) % 256
            y = (i * 23 + 7) % 256
            positions.append([str(x), str(y)])
        
        # Calculate commitment root (Poseidon hash of positions)
        # For now, use simple hash
        commitment_data = str(positions).encode()
        commitment_hash = hashlib.sha256(commitment_data).digest()
        commitment_root = int.from_bytes(commitment_hash[:31], 'big') % (2**254)
        
        # Prepare witness matching ImageLevel circuit
        witness = {
            "commitmentRoot": str(commitment_root),
            "proofLength": str(32),
            "timestamp": str(int(time.time())),
            "x0": str(0),
            "y0": str(0),
            "chaosKey": str(chaos_key_int),
            "proofBits": [str(bit) for bit in proof_bits],
            "positions": positions,
            "imageHash": str(image_hash_single)
        }
        
        return witness
    
    def _serialize_proof(self, proof: Dict, public_signals: list) -> bytes:
        """
        Serialize Groth16 proof to compact bytes
        
        Groth16 proof structure:
        - pi_a: [2 field elements]
        - pi_b: [[2,2] field elements]
        - pi_c: [2 field elements]
        - Total: ~256 bytes for BN254 curve
        """
        # Simple JSON serialization for now
        # In production: use more compact binary format
        proof_obj = {
            'proof': proof,
            'public': public_signals
        }
        
        return json.dumps(proof_obj).encode('utf-8')
    
    def _deserialize_proof(self, proof_bytes: bytes) -> Tuple[Dict, list]:
        """Deserialize proof from bytes (supports JSON and Binary)"""
        try:
            # Try JSON first
            proof_obj = json.loads(proof_bytes.decode('utf-8'))
            return proof_obj['proof'], proof_obj['public']
        except (UnicodeDecodeError, json.JSONDecodeError):
            # Try binary
            try:
                from .proof_serializer import ProofSerializer
                serializer = ProofSerializer()
                return serializer.deserialize(proof_bytes)
            except Exception as e:
                raise ValueError(f"Failed to deserialize binary proof: {e}")


def test_zk_proof():
    """Test ZK proof generation and verification"""
    print("Testing ZK Proof Generation/Verification")
    print("=" * 80)
    
    try:
        wrapper = ZKProofWrapper()
        
        # Test data
        message = "Secret message for video steganography"
        chaos_key = "my_secret_chaos_key_12345"
        video_hash = "foreman_cif_h264_video_hash"
        
        # Generate proof
        proof_data = wrapper.generate_proof(message, chaos_key, video_hash)
        
        print(f"\n{'='*60}")
        print("PROOF GENERATION SUCCESS")
        print(f"{'='*60}")
        print(f"Proof size: {proof_data['proof_size']} bytes")
        
        # Verify proof
        valid, verified_data = wrapper.verify_proof(proof_data['proof_bytes'])
        
        print(f"\n{'='*60}")
        print("VERIFICATION SUCCESS" if valid else "VERIFICATION FAILED")
        print(f"{'='*60}")
        print(f"Valid: {valid}")
        
    except FileNotFoundError as e:
        print(f"\n[ERROR] Circuit files not found: {e}")
        print("[INFO] Make sure ImageLevel circuits are compiled")
        print("[INFO] Run: cd ImageLevel && npm install && npm run build:circuit")
    except Exception as e:
        print(f"\n[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    test_zk_proof()
