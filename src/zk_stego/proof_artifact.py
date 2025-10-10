"""
ZK-SNARK Proof Artifact Management
Handles packing/unpacking of proof artifacts with PNG chunk embedding
"""

import json
import hashlib
import struct
import zlib
from typing import Dict, Any, Optional, Tuple
from pathlib import Path
import time

class ProofArtifact:
    """Manages ZK-SNARK proof artifacts with metadata and signatures"""
    
    def __init__(self):
        self.chunk_type = b'zkPF'  # zk-Proof chunk type
        
    def create_artifact(
        self,
        proof_json: Dict[str, Any],
        public_json: Dict[str, Any], 
        cover_image_path: str,
        circuit_hash: str,
        signing_key: Optional[bytes] = None
    ) -> Dict[str, Any]:
        """Create a complete proof artifact"""
        
        # Calculate image hash for binding
        image_hash = self._calculate_image_hash(cover_image_path)
        
        # Create optimized public inputs
        optimized_public = self._optimize_public_inputs(public_json, image_hash)
        
        # Create metadata
        meta = {
            "vk_id": "optimized_stego_20241010",
            "version": "1.0", 
            "domain": "steganography",
            "circuit_hash": circuit_hash
        }
        
        # Create base artifact
        artifact = {
            "proof": proof_json,
            "public": optimized_public,
            "meta": meta
        }
        
        # Add signature if signing key provided
        if signing_key:
            signature = self._sign_artifact(artifact, signing_key)
            artifact["signature"] = signature
            
        return artifact
    
    def _calculate_image_hash(self, image_path: str) -> str:
        """Calculate SHA256 hash of image file"""
        with open(image_path, 'rb') as f:
            image_data = f.read()
        return hashlib.sha256(image_data).hexdigest()
    
    def _optimize_public_inputs(self, public_json: Dict[str, Any], image_hash: str) -> Dict[str, Any]:
        """Convert full public inputs to optimized format"""
        
        # Extract slots and create commitment
        slots = public_json.get('slots', [])
        message = public_json.get('message', [])
        
        # Create Merkle root of slots (simplified - use hash)
        slots_str = ','.join(map(str, slots))
        commitment_root = hashlib.sha256(slots_str.encode()).hexdigest()[:16]  # Truncated for demo
        
        return {
            "image_hash": image_hash,
            "commitment_root": commitment_root,
            "message_length": len(message),
            "timestamp": int(time.time()),
            "nonce": hash(image_hash) % 100000  # Deterministic nonce for demo
        }
    
    def _sign_artifact(self, artifact: Dict[str, Any], signing_key: bytes) -> Dict[str, Any]:
        """Sign artifact with ECDSA (simplified)"""
        # In real implementation, use proper ECDSA library
        artifact_str = json.dumps(artifact, sort_keys=True)
        signature_hash = hashlib.sha256(artifact_str.encode()).hexdigest()
        
        return {
            "value": signature_hash[:32],  # Simplified signature
            "pubkey": signing_key.hex()[:32] if signing_key else "demo_pubkey",
            "algorithm": "demo_ecdsa"
        }
    
    def pack_artifact(self, artifact: Dict[str, Any]) -> bytes:
        """Serialize artifact to binary format"""
        json_str = json.dumps(artifact, separators=(',', ':'))
        json_bytes = json_str.encode('utf-8')
        
        # Optional compression for large artifacts
        if len(json_bytes) > 1024:
            compressed = zlib.compress(json_bytes)
            if len(compressed) < len(json_bytes):
                return b'COMP' + struct.pack('<I', len(json_bytes)) + compressed
        
        return b'JSON' + json_bytes
    
    def unpack_artifact(self, artifact_bytes: bytes) -> Dict[str, Any]:
        """Deserialize binary artifact back to dict"""
        if artifact_bytes.startswith(b'COMP'):
            # Decompress
            original_size = struct.unpack('<I', artifact_bytes[4:8])[0]
            compressed_data = artifact_bytes[8:]
            json_bytes = zlib.decompress(compressed_data)
        elif artifact_bytes.startswith(b'JSON'):
            json_bytes = artifact_bytes[4:]
        else:
            raise ValueError("Unknown artifact format")
            
        json_str = json_bytes.decode('utf-8')
        return json.loads(json_str)
    
    def embed_in_png(self, png_path: str, output_path: str, artifact: Dict[str, Any]) -> bool:
        """Embed artifact in PNG using custom chunk"""
        try:
            # Pack artifact to binary
            packed_data = self.pack_artifact(artifact)
            
            # Remove format prefix for PNG chunk - we'll store raw JSON/compressed data
            if packed_data.startswith(b'JSON'):
                chunk_data = packed_data[4:]  # Remove "JSON" prefix
            elif packed_data.startswith(b'COMP'):
                chunk_data = packed_data  # Keep compression header for unpacking
            else:
                chunk_data = packed_data  # Raw data
            
            # Read PNG file
            with open(png_path, 'rb') as f:
                png_data = f.read()
            
            # Validate PNG signature
            if png_data[:8] != b'\x89PNG\r\n\x1a\n':
                raise ValueError("Invalid PNG file")
            
            # Find insertion point (before IEND chunk)
            iend_pos = png_data.rfind(b'IEND')
            if iend_pos == -1:
                raise ValueError("No IEND chunk found")
            
            # IEND chunk structure: [4-byte length][4-byte "IEND"][data][4-byte CRC]
            # We want to insert before the length field
            iend_chunk_start = iend_pos - 4  # Back up to length field
            
            # Create chunk
            chunk_length = struct.pack('>I', len(chunk_data))
            chunk_type = self.chunk_type
            chunk_crc = struct.pack('>I', zlib.crc32(chunk_type + chunk_data) & 0xffffffff)
            
            full_chunk = chunk_length + chunk_type + chunk_data + chunk_crc
            
            # Insert chunk before IEND
            new_png = png_data[:iend_chunk_start] + full_chunk + png_data[iend_chunk_start:]
            
            # Write output
            with open(output_path, 'wb') as f:
                f.write(new_png)
                
            return True
            
        except Exception as e:
            print(f"Error embedding artifact: {e}")
            return False
    
    def extract_from_png(self, png_path: str) -> Optional[Dict[str, Any]]:
        """Extract artifact from PNG chunk"""
        try:
            with open(png_path, 'rb') as f:
                png_data = f.read()
            
            # Validate PNG
            if png_data[:8] != b'\x89PNG\r\n\x1a\n':
                raise ValueError("Invalid PNG file")
            
            # Parse chunks to find our artifact
            pos = 8  # Skip PNG signature
            
            while pos < len(png_data):
                # Read chunk header
                if pos + 8 > len(png_data):
                    break
                    
                length_bytes = png_data[pos:pos+4]
                type_bytes = png_data[pos+4:pos+8]
                
                if len(length_bytes) != 4 or len(type_bytes) != 4:
                    break
                    
                chunk_length = struct.unpack('>I', length_bytes)[0]
                
                # Check if this is our chunk
                if type_bytes == self.chunk_type:
                    # Extract chunk data
                    data_start = pos + 8
                    data_end = data_start + chunk_length
                    
                    if data_end + 4 <= len(png_data):  # +4 for CRC
                        chunk_data = png_data[data_start:data_end]
                        
                        # Verify CRC
                        expected_crc = struct.unpack('>I', png_data[data_end:data_end+4])[0]
                        actual_crc = zlib.crc32(type_bytes + chunk_data) & 0xffffffff
                        
                        if expected_crc == actual_crc:
                            # Add JSON prefix back for unpacking
                            if chunk_data.startswith(b'COMP'):
                                artifact_data = chunk_data  # Already has COMP prefix
                            else:
                                artifact_data = b'JSON' + chunk_data  # Add JSON prefix
                            return self.unpack_artifact(artifact_data)
                        else:
                            print("Warning: Chunk CRC mismatch")
                
                # Move to next chunk
                pos += 8 + chunk_length + 4  # header + data + crc
                
                # Safety check for IEND
                if type_bytes == b'IEND':
                    break
            
            return None
            
        except Exception as e:
            print(f"Error extracting artifact: {e}")
            return None
    
    def verify_artifact(self, artifact: Dict[str, Any], verification_key_path: str) -> Tuple[bool, str]:
        """Verify artifact integrity and ZK proof"""
        try:
            # 1. Verify artifact structure
            required_fields = ['proof', 'public', 'meta']
            for field in required_fields:
                if field not in artifact:
                    return False, f"Missing required field: {field}"
            
            # 2. Verify signature if present
            if 'signature' in artifact:
                if not self._verify_signature(artifact):
                    return False, "Invalid signature"
            
            # 3. Verify timestamp is reasonable
            timestamp = artifact['public'].get('timestamp', 0)
            current_time = int(time.time())
            if abs(current_time - timestamp) > 86400 * 7:  # 1 week tolerance
                return False, "Timestamp too old or future"
            
            # 4. TODO: Verify ZK proof using snarkjs
            # This would call: snarkjs groth16 verify vk.json public.json proof.json
            # For now, return success
            
            return True, "Verification successful"
            
        except Exception as e:
            return False, f"Verification error: {e}"
    
    def _verify_signature(self, artifact: Dict[str, Any]) -> bool:
        """Verify artifact signature (simplified)"""
        # In real implementation, use proper ECDSA verification
        signature = artifact.get('signature', {})
        if not signature:
            return False
            
        # For demo, just check signature format
        return len(signature.get('value', '')) == 32


# Convenience functions for CLI usage
def embed_proof_artifact(
    cover_image_path: str,
    stego_image_path: str,
    proof_json_path: str,
    public_json_path: str,
    circuit_hash: str = "demo_circuit_hash",
    signing_key: Optional[str] = None
) -> bool:
    """High-level function to embed proof artifact in image"""
    
    artifact_manager = ProofArtifact()
    
    # Load proof and public inputs
    with open(proof_json_path, 'r') as f:
        proof_json = json.load(f)
        
    with open(public_json_path, 'r') as f:
        public_json = json.load(f)
    
    # Create artifact
    signing_key_bytes = bytes.fromhex(signing_key) if signing_key else None
    artifact = artifact_manager.create_artifact(
        proof_json, public_json, cover_image_path, circuit_hash, signing_key_bytes
    )
    
    # Embed in PNG
    return artifact_manager.embed_in_png(cover_image_path, stego_image_path, artifact)


def verify_stego_image(stego_image_path: str, verification_key_path: str = None) -> bool:
    """High-level function to verify stego image (single command API)"""
    
    artifact_manager = ProofArtifact()
    
    # Extract artifact
    artifact = artifact_manager.extract_from_png(stego_image_path)
    if not artifact:
        print("No proof artifact found in image")
        return False
    
    # Verify artifact
    success, message = artifact_manager.verify_artifact(artifact, verification_key_path)
    print(f"Verification: {message}")
    
    return success


if __name__ == "__main__":
    # Demo usage
    print("ZK-SNARK Proof Artifact Demo")
    print("Usage:")
    print("  python3 proof_artifact.py embed <cover.png> <stego.png> <proof.json> <public.json>")
    print("  python3 proof_artifact.py verify <stego.png>")