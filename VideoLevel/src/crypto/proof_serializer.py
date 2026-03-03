"""
Binary Serialization for Groth16 Proofs

Reduces proof size from ~3.8KB (JSON) to ~800 bytes (binary)
by using compact binary encoding instead of JSON.
"""

import struct
from typing import Dict, Any, Tuple


class ProofSerializer:
    """
    Serialize/deserialize Groth16 proofs to/from binary format
    
    Binary Format:
    - Header (16 bytes): version(4) + timestamp(8) + payload_length(4)
    - Commitment (32 bytes): SHA256 hash
    - Proof π_A (64 bytes): 2 × BN128 field elements
    - Proof π_B (128 bytes): 4 × BN128 field elements  
    - Proof π_C (64 bytes): 2 × BN128 field elements
    - Public signals hash (32 bytes): SHA256 of signals
    - Total: ~336 bytes (vs 3,822 bytes JSON)
    """
    
    VERSION = 1
    
    @staticmethod
    def serialize(proof_obj: Dict[str, Any]) -> bytes:
        """
        Convert Groth16 proof object to compact binary format
        
        Args:
            proof_obj: Proof dictionary from GrothProofGenerator
            
        Returns:
            Binary representation (~336 bytes)
        """
        import hashlib
        
        # Header: version (4) + timestamp (8) + payload_length (4)
        header = struct.pack(
            '>I Q I',
            ProofSerializer.VERSION,
            proof_obj.get('timestamp', 0),
            proof_obj.get('public_inputs', {}).get('payload_length', 0)
        )
        
        # Commitment (32 bytes)
        commitment_hex = proof_obj.get('commitment', '00' * 32)
        commitment = bytes.fromhex(commitment_hex)
        
        # Proof components - convert from decimal strings to bytes
        proof = proof_obj.get('proof', {})
        
        # π_A: [x, y, 1] → take x, y (2 field elements × 32 bytes)
        pi_a = proof.get('pi_a', ['0', '0', '1'])
        pi_a_bytes = (
            int(pi_a[0]).to_bytes(32, 'big') +
            int(pi_a[1]).to_bytes(32, 'big')
        )
        
        # π_B: [[x1, y1], [x2, y2], [1, 0]] → take x1, y1, x2, y2 (4 × 32 bytes)
        pi_b = proof.get('pi_b', [['0', '0'], ['0', '0'], ['1', '0']])
        pi_b_bytes = (
            int(pi_b[0][0]).to_bytes(32, 'big') +
            int(pi_b[0][1]).to_bytes(32, 'big') +
            int(pi_b[1][0]).to_bytes(32, 'big') +
            int(pi_b[1][1]).to_bytes(32, 'big')
        )
        
        # π_C: [x, y, 1] → take x, y (2 field elements × 32 bytes)
        pi_c = proof.get('pi_c', ['0', '0', '1'])
        pi_c_bytes = (
            int(pi_c[0]).to_bytes(32, 'big') +
            int(pi_c[1]).to_bytes(32, 'big')
        )
        
        # Public signals: hash instead of full array (32 bytes vs ~3KB)
        public_inputs = proof_obj.get('public_inputs', {})
        public_signals = public_inputs.get('public_signals', [])
        
        # Convert signals to string and hash
        signals_str = ''.join(str(s) for s in public_signals)
        signals_hash = hashlib.sha256(signals_str.encode()).digest()
        
        # Combine all components
        binary_proof = (
            header +           # 16 bytes
            commitment +       # 32 bytes
            pi_a_bytes +       # 64 bytes
            pi_b_bytes +       # 128 bytes
            pi_c_bytes +       # 64 bytes
            signals_hash       # 32 bytes
        )
        # Total: 336 bytes
        
        return binary_proof
    
    @staticmethod
    def deserialize(binary_proof: bytes) -> Dict[str, Any]:
        """
        Convert binary proof back to dictionary format
        
        Args:
            binary_proof: Binary representation
            
        Returns:
            Proof dictionary (partial - for verification)
        """
        if len(binary_proof) < 336:
            raise ValueError(f"Invalid proof size: {len(binary_proof)} bytes (expected 336)")
        
        offset = 0
        
        # Parse header
        version, timestamp, payload_length = struct.unpack('>I Q I', binary_proof[offset:offset+16])
        offset += 16
        
        if version != ProofSerializer.VERSION:
            raise ValueError(f"Unsupported proof version: {version}")
        
        # Parse commitment
        commitment = binary_proof[offset:offset+32].hex()
        offset += 32
        
        # Parse π_A
        pi_a_x = int.from_bytes(binary_proof[offset:offset+32], 'big')
        offset += 32
        pi_a_y = int.from_bytes(binary_proof[offset:offset+32], 'big')
        offset += 32
        
        # Parse π_B
        pi_b_x1 = int.from_bytes(binary_proof[offset:offset+32], 'big')
        offset += 32
        pi_b_y1 = int.from_bytes(binary_proof[offset:offset+32], 'big')
        offset += 32
        pi_b_x2 = int.from_bytes(binary_proof[offset:offset+32], 'big')
        offset += 32
        pi_b_y2 = int.from_bytes(binary_proof[offset:offset+32], 'big')
        offset += 32
        
        # Parse π_C
        pi_c_x = int.from_bytes(binary_proof[offset:offset+32], 'big')
        offset += 32
        pi_c_y = int.from_bytes(binary_proof[offset:offset+32], 'big')
        offset += 32
        
        # Parse public signals hash
        signals_hash = binary_proof[offset:offset+32].hex()
        offset += 32
        
        # Reconstruct proof object (partial)
        return {
            'version': f"{version}.0",
            'algorithm': 'groth16-snarkjs-binary',
            'timestamp': timestamp,
            'commitment': commitment,
            'proof': {
                'pi_a': [str(pi_a_x), str(pi_a_y), '1'],
                'pi_b': [
                    [str(pi_b_x1), str(pi_b_y1)],
                    [str(pi_b_x2), str(pi_b_y2)],
                    ['1', '0']
                ],
                'pi_c': [str(pi_c_x), str(pi_c_y), '1'],
                'protocol': 'groth16',
                'curve': 'bn128'
            },
            'public_inputs': {
                'payload_length': payload_length,
                'commitment': commitment,
                'public_signals_hash': signals_hash
            },
            'metadata': {
                'generator': 'zk-mv-stego-binary',
                'curve': 'bn128',
                'security_level': 128,
                'format': 'binary-v1'
            }
        }
    
    @staticmethod
    def get_size_comparison(json_proof: Dict[str, Any]) -> Dict[str, int]:
        """
        Compare JSON vs binary proof sizes
        
        Returns:
            Dictionary with size comparison
        """
        import json
        
        json_size = len(json.dumps(json_proof).encode('utf-8'))
        binary_size = len(ProofSerializer.serialize(json_proof))
        
        return {
            'json_bytes': json_size,
            'binary_bytes': binary_size,
            'savings_bytes': json_size - binary_size,
            'compression_ratio': round(binary_size / json_size * 100, 1)
        }


def compress_proof(proof_obj: Dict[str, Any]) -> Tuple[bytes, Dict[str, int]]:
    """
    Compress proof using binary serialization + zlib
    
    Args:
        proof_obj: Proof dictionary from GrothProofGenerator
        
    Returns:
        Tuple of (compressed_bytes, size_stats)
    """
    import zlib
    
    # Step 1: Binary serialization
    binary_proof = ProofSerializer.serialize(proof_obj)
    
    # Step 2: zlib compression (level 9 = maximum compression)
    compressed = zlib.compress(binary_proof, level=9)
    
    # Size comparison
    import json
    json_size = len(json.dumps(proof_obj).encode('utf-8'))
    
    stats = {
        'original_json_bytes': json_size,
        'binary_bytes': len(binary_proof),
        'compressed_bytes': len(compressed),
        'total_savings': json_size - len(compressed),
        'compression_ratio': round(len(compressed) / json_size * 100, 1)
    }
    
    return compressed, stats


def decompress_proof(compressed_bytes: bytes) -> Dict[str, Any]:
    """
    Decompress and deserialize proof
    
    Args:
        compressed_bytes: Compressed binary proof
        
    Returns:
        Proof dictionary
    """
    import zlib
    
    binary_proof = zlib.decompress(compressed_bytes)
    return ProofSerializer.deserialize(binary_proof)


def serialize_with_signals(proof_obj: Dict[str, Any]) -> bytes:
    """
    Serialize proof WITH public signals (larger size but verifiable)
    
    Args:
        proof_obj: Proof dictionary from GrothProofGenerator
    
    Returns:
        Binary representation with full signals (~600-800 bytes)
    """
    # Use standard binary serialization
    binary_proof = ProofSerializer.serialize(proof_obj)
    
    # Append public signals as JSON
    import json
    public_inputs = proof_obj.get('public_inputs', {})
    public_signals = public_inputs.get('public_signals', [])
    
    # Serialize signals
    signals_json = json.dumps(public_signals).encode('utf-8')
    signals_length = len(signals_json)
    
    # Format: [binary_proof][4-byte length][signals_json]
    return binary_proof + struct.pack('>I', signals_length) + signals_json


def deserialize_with_signals(full_binary: bytes) -> Dict[str, Any]:
    """
    Deserialize proof that includes public signals
    
    Args:
        full_binary: Binary proof with appended signals
    
    Returns:
        Full proof object with public signals
    """
    import json
    
    # First 336 bytes is the standard proof
    binary_proof = full_binary[:336]
    proof_obj = ProofSerializer.deserialize(binary_proof)
    
    # Read signals length
    if len(full_binary) > 340:
        signals_length = struct.unpack('>I', full_binary[336:340])[0]
        signals_json = full_binary[340:340+signals_length]
        public_signals = json.loads(signals_json.decode('utf-8'))
        
        # Add signals to proof object
        proof_obj['public_inputs']['public_signals'] = public_signals
    
    return proof_obj


def verify_proof_integrity(proof_obj: Dict[str, Any], recomputed_signals: list) -> bool:
    """
    Verify that recomputed public signals match the stored hash
    
    Args:
        proof_obj: Deserialized proof object (may have hash only)
        recomputed_signals: Public signals recomputed from message
    
    Returns:
        True if signals match the stored hash
    """
    import hashlib
    
    # Get stored hash
    stored_hash = proof_obj.get('public_inputs', {}).get('public_signals_hash', '')
    
    # Compute hash of recomputed signals
    signals_str = ''.join(str(s) for s in recomputed_signals)
    computed_hash = hashlib.sha256(signals_str.encode()).hexdigest()
    
    return stored_hash == computed_hash
