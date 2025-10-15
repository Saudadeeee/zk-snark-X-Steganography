
import os
import json
import subprocess
import tempfile
import hashlib
import time
import numpy as np
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from PIL import Image

class ZKProofGenerator:
    """ZK-SNARK proof generation and verification system"""
    
    def __init__(self, project_root: Optional[str] = None):
        if project_root is None:
            # Auto-detect project root
            current_file = Path(__file__).resolve()
            self.project_root = current_file.parent.parent.parent
        else:
            self.project_root = Path(project_root)
            
        self.circuit_dir = self.project_root / "circuits"
        self.artifacts_dir = self.project_root / "artifacts"
        self.build_dir = self.circuit_dir / "compiled" / "build"
        
        # Key files
        self.circuit_wasm = self.build_dir / "chaos_zk_stego_js" / "chaos_zk_stego.wasm"
        self.witness_gen = self.build_dir / "chaos_zk_stego_js" / "generate_witness.js"
        self.ptau_file = self.artifacts_dir / "keys" / "pot12_final.ptau"
        
        # Generated files (will be created during process)
        self.circuit_zkey = self.build_dir / "chaos_zk_stego.zkey"
        self.verification_key = self.build_dir / "verification_key.json"
        
    def _run_command(self, cmd: List[str], cwd: Optional[Path] = None) -> Tuple[bool, str, str]:
        """Run command and return success, stdout, stderr"""
        try:
            result = subprocess.run(
                cmd, 
                cwd=cwd or self.build_dir,
                capture_output=True, 
                text=True, 
                timeout=60
            )
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", "Command timed out"
        except Exception as e:
            return False, "", str(e)
    
    def setup_trusted_setup(self) -> bool:
        """Setup trusted setup if not already done"""
        if self.circuit_zkey.exists() and self.verification_key.exists():
            print("SUCCESS Trusted setup already completed")
            return True
            
        print("STARTING Starting trusted setup...")
        
        r1cs_file = self.build_dir / "chaos_zk_stego.r1cs"
        if not r1cs_file.exists():
            print(f"ERROR R1CS file not found: {r1cs_file}")
            return False
            
        if not self.ptau_file.exists():
            print(f"ERROR Powers of Tau not found: {self.ptau_file}")
            print("INFO Download with: wget https://hermez.s3-eu-west-1.amazonaws.com/powersOfTau28_hez_final_12.ptau")
            return False
        
        setup_cmd = [
            "npx", "snarkjs", "groth16", "setup",
            str(r1cs_file),
            str(self.ptau_file), 
            str(self.circuit_zkey)
        ]
        
        success, stdout, stderr = self._run_command(setup_cmd)
        if not success:
            print(f"ERROR: Groth16 setup failed: {stderr}")
            return False
            
        export_vk_cmd = [
            "npx", "snarkjs", "zkey", "export", "verificationkey",
            str(self.circuit_zkey), str(self.verification_key)
        ]
        
        success, stdout, stderr = self._run_command(export_vk_cmd)
        if not success:
            print(f"ERROR: Verification key export failed: {stderr}")
            return False
            
        print("Trusted setup completed successfully")
        return True
    
    def create_witness_input(self, 
                           image_hash: str,
                           commitment_root: str, 
                           proof_length: int,
                           timestamp: int,
                           x0: int, y0: int,
                           chaos_key: str,
                           proof_bits: List[int],
                           positions: List[Tuple[int, int]]) -> Dict[str, Any]:
        """Create witness input matching circuit interface"""
        
        proof_bits_padded = proof_bits[:32] + [0] * (32 - len(proof_bits))
        positions_padded = positions[:16] + [(0, 0)] * (16 - len(positions))
        
        witness_input = {
            "imageHash": str(int(image_hash, 16) if isinstance(image_hash, str) else image_hash),
            "commitmentRoot": str(int(commitment_root, 16) if isinstance(commitment_root, str) else commitment_root),
            "proofLength": str(proof_length),
            "timestamp": str(timestamp),
            "x0": str(x0),
            "y0": str(y0), 
            "chaosKey": str(int(chaos_key, 16) if isinstance(chaos_key, str) else chaos_key),
            "proofBits": [str(bit) for bit in proof_bits_padded],
            "positions": [[str(pos[0]), str(pos[1])] for pos in positions_padded]
        }
        
        return witness_input
    
    def generate_witness(self, witness_input: Dict[str, Any]) -> Optional[Path]:
        """Generate witness file from input"""
        
        if not self.circuit_wasm.exists():
            print(f"ERROR: WASM file not found: {self.circuit_wasm}")
            return None
            
        if not self.witness_gen.exists():
            print(f"ERROR: Witness generator not found: {self.witness_gen}")
            return None
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(witness_input, f, indent=2)
            input_file = Path(f.name)
        
        witness_file = self.build_dir / f"witness_{int(time.time())}.wtns"
        
        witness_cmd = [
            "node", str(self.witness_gen),
            str(self.circuit_wasm),
            str(input_file),
            str(witness_file)
        ]
        
        success, stdout, stderr = self._run_command(witness_cmd)
        
        input_file.unlink()
        
        if not success:
            print(f"ERROR: Witness generation failed: {stderr}")
            return None
            
        print(f"Witness generated: {witness_file}")
        return witness_file
    
    def generate_proof(self, witness_file: Path) -> Optional[Tuple[Dict[str, Any], List[str]]]:
        """Generate ZK proof from witness"""
        
        if not self.circuit_zkey.exists():
            print("ERROR: Circuit key not found. Run setup_trusted_setup() first.")
            return None
            
        proof_file = self.build_dir / f"proof_{int(time.time())}.json"
        public_file = self.build_dir / f"public_{int(time.time())}.json"
        
        prove_cmd = [
            "npx", "snarkjs", "groth16", "prove",
            str(self.circuit_zkey),
            str(witness_file),
            str(proof_file),
            str(public_file)
        ]
        
        success, stdout, stderr = self._run_command(prove_cmd)
        if not success:
            print(f"ERROR: Proof generation failed: {stderr}")
            return None
        
        try:
            with open(proof_file, 'r') as f:
                proof = json.load(f)
            with open(public_file, 'r') as f:
                public_inputs = json.load(f)
                
            proof_file.unlink()
            public_file.unlink()
            witness_file.unlink()
            
            print("ZK proof generated successfully")
            return proof, public_inputs
            
        except Exception as e:
            print(f"ERROR: Failed to read proof files: {e}")
            return None
    
    def verify_proof(self, proof: Dict[str, Any], public_inputs: List[str]) -> bool:
        """Verify ZK proof"""
        
        if not self.verification_key.exists():
            print("ERROR: Verification key not found. Run setup_trusted_setup() first.")
            return False
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(proof, f)
            proof_file = Path(f.name)
            
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(public_inputs, f)
            public_file = Path(f.name)
        
        verify_cmd = [
            "npx", "snarkjs", "groth16", "verify",
            str(self.verification_key),
            str(public_file),
            str(proof_file)
        ]
        
        success, stdout, stderr = self._run_command(verify_cmd)
        
        proof_file.unlink()
        public_file.unlink()
        
        if success and "OK" in stdout:
            print("SUCCESS Proof verification PASSED")
            return True
        else:
            print(f"ERROR Proof verification FAILED: {stderr}")
            return False
    
    def extract_chaos_parameters(self, image_array: np.ndarray, message: str) -> Dict[str, Any]:
        """Extract chaos parameters from image and message for ZK proof"""
        
        height, width = image_array.shape[:2]
        
        if len(image_array.shape) == 3:
            gray = np.mean(image_array, axis=2).astype(np.uint8)
        else:
            gray = image_array
            
        grad_x = np.abs(np.diff(gray, axis=1))
        grad_y = np.abs(np.diff(gray, axis=0))
        
        grad_x = np.pad(grad_x, ((0, 0), (0, 1)), mode='edge')
        grad_y = np.pad(grad_y, ((0, 1), (0, 0)), mode='edge')
        
        gradient_mag = grad_x + grad_y
        
        max_pos = np.unravel_index(np.argmax(gradient_mag), gradient_mag.shape)
        x0, y0 = int(max_pos[1]), int(max_pos[0])
        
        chaos_key = hashlib.sha256(message.encode()).hexdigest()
        
        image_hash = hashlib.sha256(image_array.tobytes()).hexdigest()
        
        message_bytes = message.encode('utf-8')
        proof_bits = []
        for byte in message_bytes:
            for i in range(8):
                proof_bits.append((byte >> i) & 1)
        
        positions = []
        curr_x, curr_y = x0, y0
        for i in range(16):
            positions.append((curr_x % width, curr_y % height))
            new_x = (2 * curr_x + curr_y) % width
            new_y = (curr_x + curr_y) % height
            curr_x, curr_y = new_x, new_y
        
        position_data = json.dumps(positions, sort_keys=True)
        commitment_root = hashlib.sha256(position_data.encode()).hexdigest()
        
        return {
            "x0": x0,
            "y0": y0,
            "chaos_key": chaos_key,
            "image_hash": image_hash,
            "commitment_root": commitment_root,
            "proof_bits": proof_bits,
            "positions": positions,
            "proof_length": len(proof_bits),
            "timestamp": int(time.time())
        }
    
    def generate_complete_proof(self, image_array: np.ndarray, message: str) -> Optional[Dict[str, Any]]:
        """Complete workflow: extract parameters, generate witness, create proof"""
        print("Starting complete ZK proof generation...")
        
        if not self.setup_trusted_setup():
            return None
        
        print("Extracting chaos parameters...")
        chaos_params = self.extract_chaos_parameters(image_array, message)
        
        print("Creating witness input...")
        witness_input = self.create_witness_input(
            image_hash=chaos_params["image_hash"],
            commitment_root=chaos_params["commitment_root"],
            proof_length=chaos_params["proof_length"],
            timestamp=chaos_params["timestamp"],
            x0=chaos_params["x0"],
            y0=chaos_params["y0"],
            chaos_key=chaos_params["chaos_key"],
            proof_bits=chaos_params["proof_bits"],
            positions=chaos_params["positions"]
        )
        
        print("Generating witness...")
        witness_file = self.generate_witness(witness_input)
        if not witness_file:
            return None
        
        print("Generating ZK proof...")
        proof_result = self.generate_proof(witness_file)
        if not proof_result:
            return None
        
        proof, public_inputs = proof_result
        
        print("Verifying generated proof...")
        if not self.verify_proof(proof, public_inputs):
            return None
        
        return {
            "proof": proof,
            "public_inputs": public_inputs,
            "chaos_parameters": chaos_params,
            "witness_input": witness_input,
            "generation_timestamp": int(time.time()),
            "message_hash": hashlib.sha256(message.encode()).hexdigest(),
            "verification_status": "VALID"
        }


def add_zk_proof_methods():
    """Add ZK proof methods to HybridProofArtifact class"""
    
    def generate_proof(self, image_array: np.ndarray, message: str) -> Optional[Dict[str, Any]]:
        """Generate ZK proof for steganographic embedding"""
        zk_generator = ZKProofGenerator()
        return zk_generator.generate_complete_proof(image_array, message)
    
    def verify_proof(self, proof_package: Dict[str, Any]) -> bool:
        """Verify ZK proof package"""
        zk_generator = ZKProofGenerator()
        return zk_generator.verify_proof(
            proof_package["proof"], 
            proof_package["public_inputs"]
        )
    
    try:
        from zk_stego.hybrid_proof_artifact import HybridProofArtifact
        HybridProofArtifact.generate_proof_old = generate_proof
        HybridProofArtifact.verify_proof_old = verify_proof
        print("ZK proof methods added to HybridProofArtifact")
    except ImportError:
        pass


if __name__ == "__main__":
    add_zk_proof_methods()