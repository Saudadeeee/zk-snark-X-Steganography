"""
Hybrid ZK-SNARK Steganography: PNG Chunk + Chaos-based LSB Embedding
Combines robust PNG chunk metadata with chaos-based position generation
"""

import json
import hashlib
import struct
import zlib
import numpy as np
from PIL import Image
from typing import Dict, Any, Optional, Tuple, List
import time

from .chaos_embedding import ChaosProofArtifact, generate_chaos_key_from_secret

class HybridProofArtifact:
    """Hybrid PNG Chunk + Chaos LSB steganography"""
    
    def __init__(self):
        self.chunk_type = b'zkPF'  # PNG chunk for metadata
        self.chaos_artifact = ChaosProofArtifact()
        
    def embed_hybrid_proof(
        self,
        cover_image_path: str,
        stego_image_path: str,
        proof_json: Dict[str, Any],
        public_json: Dict[str, Any],
        secret_key: str,
        x0: Optional[int] = None,
        y0: Optional[int] = None
    ) -> bool:
        """
        Embed ZK proof using hybrid approach:
        1. PNG chunk stores: initial position + chaos parameters + public inputs
        2. Chaos LSB stores: actual ZK proof data
        """
        try:
            # Load cover image
            cover_img = Image.open(cover_image_path)
            cover_array = np.array(cover_img)
            
            # Generate chaos parameters
            chaos_key = generate_chaos_key_from_secret(secret_key)
            
            # Use center of image as default initial position
            if x0 is None:
                x0 = cover_array.shape[1] // 2
            if y0 is None:
                y0 = cover_array.shape[0] // 2
                
            # Serialize proof for embedding
            proof_bytes = json.dumps(proof_json, separators=(',', ':')).encode('utf-8')
            
            # Embed proof using chaos positioning
            stego_array, chaos_metadata = self.chaos_artifact.embed_proof_chaos(
                cover_array, proof_bytes, x0, y0, chaos_key
            )
            
            # Add exact byte length to metadata
            chaos_metadata["proof_byte_length"] = len(proof_bytes)
            
            # Create PNG chunk metadata
            image_hash = self._calculate_image_hash(cover_image_path)
            
            chunk_metadata = {
                "chaos": chaos_metadata,
                "public": self._optimize_public_inputs(public_json, image_hash),
                "meta": {
                    "vk_id": "chaos_zk_stego_20241011",
                    "version": "1.0",
                    "domain": "chaos_steganography",
                    "algorithm": "hybrid_png_chaos"
                },
                "timestamp": int(time.time())
            }
            
            # Save stego image with PNG chunk
            stego_img = Image.fromarray(stego_array.astype(np.uint8))
            stego_img.save(stego_image_path)
            
            # Embed metadata in PNG chunk
            return self._embed_metadata_chunk(stego_image_path, chunk_metadata)
            
        except Exception as e:
            print(f"Error in hybrid embedding: {e}")
            return False
    
    def extract_hybrid_proof(self, stego_image_path: str) -> Optional[Dict[str, Any]]:
        """
        Extract ZK proof using hybrid approach:
        1. Extract metadata from PNG chunk
        2. Extract proof data using chaos positioning
        """
        try:
            # Extract metadata from PNG chunk
            metadata = self._extract_metadata_chunk(stego_image_path)
            if not metadata:
                return None
                
            # Load stego image
            stego_img = Image.open(stego_image_path)
            stego_array = np.array(stego_img)
            
            # Extract proof using chaos positioning
            proof_bytes = self.chaos_artifact.extract_proof_chaos(
                stego_array, metadata["chaos"]
            )
            
            # Truncate to exact original length if available
            if "proof_byte_length" in metadata["chaos"]:
                original_length = metadata["chaos"]["proof_byte_length"]
                proof_bytes = proof_bytes[:original_length]
            
            # Deserialize proof
            proof_json = json.loads(proof_bytes.decode('utf-8'))
            
            return {
                "proof": proof_json,
                "public": metadata["public"],
                "meta": metadata["meta"],
                "chaos": metadata["chaos"],
                "timestamp": metadata["timestamp"]
            }
            
        except Exception as e:
            print(f"Error in hybrid extraction: {e}")
            return None
    
    def _calculate_image_hash(self, image_path: str) -> str:
        """Calculate SHA256 hash of image"""
        with open(image_path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    
    def _optimize_public_inputs(self, public_json: Dict[str, Any], image_hash: str) -> Dict[str, Any]:
        """Create optimized public inputs for ZK verification"""
        chaos_positions = public_json.get('positions', [])
        
        # Create Merkle root of positions (simplified)
        positions_str = ','.join([f"{x},{y}" for x, y in chaos_positions])
        commitment_root = hashlib.sha256(positions_str.encode()).hexdigest()[:16]
        
        return {
            "image_hash": image_hash,
            "commitment_root": commitment_root,
            "proof_length": public_json.get('proof_length', 0),
            "timestamp": int(time.time())
        }
    
    def _embed_metadata_chunk(self, png_path: str, metadata: Dict[str, Any]) -> bool:
        """Embed metadata in PNG chunk"""
        try:
            # Read PNG file
            with open(png_path, 'rb') as f:
                png_data = f.read()
            
            # Serialize metadata
            metadata_json = json.dumps(metadata, separators=(',', ':'))
            metadata_bytes = metadata_json.encode('utf-8')
            
            # Find IEND chunk
            iend_pos = png_data.rfind(b'IEND')
            if iend_pos == -1:
                return False
                
            iend_chunk_start = iend_pos - 4
            
            # Create chunk
            chunk_length = struct.pack('>I', len(metadata_bytes))
            chunk_type = self.chunk_type
            chunk_crc = struct.pack('>I', zlib.crc32(chunk_type + metadata_bytes) & 0xffffffff)
            
            full_chunk = chunk_length + chunk_type + metadata_bytes + chunk_crc
            
            # Insert chunk
            new_png = png_data[:iend_chunk_start] + full_chunk + png_data[iend_chunk_start:]
            
            # Write back
            with open(png_path, 'wb') as f:
                f.write(new_png)
                
            return True
            
        except Exception as e:
            print(f"Error embedding PNG chunk: {e}")
            return False
    
    def _extract_metadata_chunk(self, png_path: str) -> Optional[Dict[str, Any]]:
        """Extract metadata from PNG chunk"""
        try:
            with open(png_path, 'rb') as f:
                png_data = f.read()
            
            # Parse chunks
            pos = 8  # Skip PNG signature
            
            while pos < len(png_data):
                if pos + 8 > len(png_data):
                    break
                    
                chunk_length = struct.unpack('>I', png_data[pos:pos+4])[0]
                chunk_type = png_data[pos+4:pos+8]
                
                if chunk_type == self.chunk_type:
                    data_start = pos + 8
                    data_end = data_start + chunk_length
                    
                    if data_end + 4 <= len(png_data):
                        chunk_data = png_data[data_start:data_end]
                        
                        # Verify CRC
                        expected_crc = struct.unpack('>I', png_data[data_end:data_end+4])[0]
                        actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xffffffff
                        
                        if expected_crc == actual_crc:
                            metadata_json = chunk_data.decode('utf-8')
                            return json.loads(metadata_json)
                
                pos += 8 + chunk_length + 4
                
                if chunk_type == b'IEND':
                    break
            
            return None
            
        except Exception as e:
            print(f"Error extracting PNG chunk: {e}")
            return None

# High-level API functions
def embed_chaos_proof(
    cover_image_path: str,
    stego_image_path: str,
    proof_json_path: str,
    public_json_path: str,
    secret_key: str,
    x0: Optional[int] = None,
    y0: Optional[int] = None
) -> bool:
    """High-level function to embed proof using hybrid chaos approach"""
    
    # Load proof files
    with open(proof_json_path, 'r') as f:
        proof_json = json.load(f)
        
    with open(public_json_path, 'r') as f:
        public_json = json.load(f)
    
    # Create hybrid artifact
    hybrid = HybridProofArtifact()
    
    return hybrid.embed_hybrid_proof(
        cover_image_path, stego_image_path, 
        proof_json, public_json, secret_key, x0, y0
    )

def extract_chaos_proof(stego_image_path: str) -> Optional[Dict[str, Any]]:
    """High-level function to extract proof using hybrid chaos approach"""
    hybrid = HybridProofArtifact()
    return hybrid.extract_hybrid_proof(stego_image_path)

def verify_chaos_stego(stego_image_path: str) -> bool:
    """Single-command verification for chaos-based steganography"""
    artifact = extract_chaos_proof(stego_image_path)
    if not artifact:
        return False
        
    # Verify artifact structure
    required_fields = ['proof', 'chaos']
    return all(field in artifact for field in required_fields)

if __name__ == "__main__":
    print("Hybrid ZK-SNARK Chaos Steganography")
    print("Usage:")
    print("  python3 hybrid_proof_artifact.py embed <cover.png> <stego.png> <proof.json> <public.json> <secret>")
    print("  python3 hybrid_proof_artifact.py extract <stego.png>")
    print("  python3 hybrid_proof_artifact.py verify <stego.png>")