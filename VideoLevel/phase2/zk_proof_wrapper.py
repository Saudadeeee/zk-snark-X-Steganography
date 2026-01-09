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
from pathlib import Path
from typing import Dict, Tuple, Optional, Any
import hashlib

# Add ImageLevel to path for ZK-SNARK utilities
IMAGE_LEVEL_PATH = Path(__file__).parent.parent.parent / "ImageLevel"
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
            proof_result = subprocess.run([
                'snarkjs',
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
            result = subprocess.run([
                'snarkjs',
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
        Prepare witness input for circuit
        
        Circuit expects:
        - message_hash: Hash of message (public)
        - chaos_params: Chaos parameters (private)
        - video_hash: Hash of video (public)
        """
        # Hash message
        message_hash = int(hashlib.sha256(message.encode()).hexdigest()[:16], 16)
        
        # Hash chaos key
        chaos_hash = int(hashlib.sha256(chaos_key.encode()).hexdigest()[:16], 16)
        
        # Hash video
        video_hash_int = int(hashlib.sha256(video_hash.encode()).hexdigest()[:16], 16)
        
        # Prepare witness (adapt to your circuit)
        witness = {
            "message_hash": str(message_hash % (2**64)),  # Field element
            "chaos_seed": str(chaos_hash % (2**64)),
            "video_hash": str(video_hash_int % (2**64)),
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
        """Deserialize proof from bytes"""
        proof_obj = json.loads(proof_bytes.decode('utf-8'))
        return proof_obj['proof'], proof_obj['public']


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
