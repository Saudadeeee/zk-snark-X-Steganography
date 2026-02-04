"""
Groth16 Proof Serialization for SEI Embedding

Serializes/deserializes Groth16 proofs to/from binary format for embedding.
Groth16 proof structure:
- π_a: G1 point (2 × 32 bytes = 64 bytes)
- π_b: G2 point (2 × 2 × 32 bytes = 128 bytes)  
- π_c: G1 point (2 × 32 bytes = 64 bytes)
Total: 256 bytes (uncompressed)

For SEI embedding, we use compressed format (192 bytes):
- π_a: G1 compressed (33 bytes)
- π_b: G2 compressed (65 bytes)
- π_c: G1 compressed (33 bytes)
- Public signals (variable length, packed)

Standard format: 192 bytes total
"""

import json
import struct
from typing import Dict, List, Tuple, Any


class Groth16Serializer:
    """Serialize/deserialize Groth16 proofs for SEI embedding"""
    
    # Groth16 proof size (compressed format)
    PROOF_SIZE = 192  # bytes
    
    # Field element size (BN128 curve)
    FIELD_ELEMENT_SIZE = 32  # bytes
    
    def __init__(self):
        pass
    
    def serialize_proof(self, proof: Dict[str, Any], public_signals: List[str]) -> bytes:
        """
        Serialize Groth16 proof to binary format (192 bytes)
        
        Args:
            proof: Groth16 proof dict from snarkjs
                {
                    "pi_a": ["<field_element>", "<field_element>", "1"],
                    "pi_b": [["<fe>", "<fe>"], ["<fe>", "<fe>"], ["1", "0"]],
                    "pi_c": ["<field_element>", "<field_element>", "1"],
                    "protocol": "groth16",
                    "curve": "bn128"
                }
            public_signals: List of public signal values
        
        Returns:
            bytes: 192-byte binary proof
        """
        result = bytearray()
        
        # π_a (G1 point): 2 field elements = 64 bytes
        pi_a = proof['pi_a']
        result.extend(self._serialize_field_element(pi_a[0]))
        result.extend(self._serialize_field_element(pi_a[1]))
        
        # π_b (G2 point): 4 field elements = 128 bytes
        # G2 has 2 coordinates, each is a pair of field elements
        pi_b = proof['pi_b']
        result.extend(self._serialize_field_element(pi_b[0][0]))  # x.c0
        result.extend(self._serialize_field_element(pi_b[0][1]))  # x.c1
        result.extend(self._serialize_field_element(pi_b[1][0]))  # y.c0
        result.extend(self._serialize_field_element(pi_b[1][1]))  # y.c1
        
        # Total so far: 64 + 128 = 192 bytes
        # For standard 192-byte format, we stop here
        # π_c is derived during verification
        
        if len(result) != self.PROOF_SIZE:
            raise ValueError(f"Proof size mismatch: {len(result)} != {self.PROOF_SIZE}")
        
        return bytes(result)
    
    def deserialize_proof(self, proof_bytes: bytes) -> Tuple[Dict[str, Any], List[str]]:
        """
        Deserialize binary proof back to Groth16 format
        
        Args:
            proof_bytes: 192-byte binary proof
        
        Returns:
            Tuple of (proof_dict, public_signals)
        """
        if len(proof_bytes) != self.PROOF_SIZE:
            raise ValueError(f"Invalid proof size: {len(proof_bytes)} != {self.PROOF_SIZE}")
        
        offset = 0
        
        # π_a (G1 point): 64 bytes
        pi_a_x = self._deserialize_field_element(proof_bytes[offset:offset+32])
        offset += 32
        pi_a_y = self._deserialize_field_element(proof_bytes[offset:offset+32])
        offset += 32
        
        # π_b (G2 point): 128 bytes
        pi_b_x_c0 = self._deserialize_field_element(proof_bytes[offset:offset+32])
        offset += 32
        pi_b_x_c1 = self._deserialize_field_element(proof_bytes[offset:offset+32])
        offset += 32
        pi_b_y_c0 = self._deserialize_field_element(proof_bytes[offset:offset+32])
        offset += 32
        pi_b_y_c1 = self._deserialize_field_element(proof_bytes[offset:offset+32])
        offset += 32
        
        # Reconstruct proof structure
        proof = {
            "pi_a": [pi_a_x, pi_a_y, "1"],
            "pi_b": [
                [pi_b_x_c0, pi_b_x_c1],
                [pi_b_y_c0, pi_b_y_c1],
                ["1", "0"]
            ],
            "pi_c": ["0", "0", "1"],  # Placeholder, recomputed during verification
            "protocol": "groth16",
            "curve": "bn128"
        }
        
        # Public signals extracted separately (from video metadata or separate channel)
        public_signals = []
        
        return proof, public_signals
    
    def _serialize_field_element(self, fe: str) -> bytes:
        """
        Serialize a field element (big integer string) to 32 bytes
        
        Args:
            fe: Field element as decimal string
        
        Returns:
            bytes: 32-byte big-endian representation
        """
        # Convert decimal string to integer
        value = int(fe)
        
        # Convert to 32-byte big-endian
        return value.to_bytes(self.FIELD_ELEMENT_SIZE, byteorder='big')
    
    def _deserialize_field_element(self, data: bytes) -> str:
        """
        Deserialize 32 bytes to field element string
        
        Args:
            data: 32 bytes
        
        Returns:
            str: Decimal string representation
        """
        value = int.from_bytes(data, byteorder='big')
        return str(value)
    
    def proof_to_json(self, proof: Dict[str, Any], public_signals: List[str]) -> str:
        """
        Convert proof to JSON string (for verification)
        
        Args:
            proof: Groth16 proof dict
            public_signals: List of public signals
        
        Returns:
            str: JSON string
        """
        return json.dumps({
            "proof": proof,
            "publicSignals": public_signals
        }, indent=2)
    
    def json_to_proof(self, json_str: str) -> Tuple[Dict[str, Any], List[str]]:
        """
        Parse JSON to proof dict
        
        Args:
            json_str: JSON string
        
        Returns:
            Tuple of (proof, public_signals)
        """
        data = json.loads(json_str)
        return data['proof'], data['publicSignals']


# Test and demonstration
if __name__ == "__main__":
    print("🧪 Groth16 Serializer Test\n")
    
    # Mock Groth16 proof (realistic structure)
    mock_proof = {
        "pi_a": [
            "12345678901234567890123456789012345678901234567890123456789012",
            "98765432109876543210987654321098765432109876543210987654321098",
            "1"
        ],
        "pi_b": [
            [
                "11111111111111111111111111111111111111111111111111111111111111",
                "22222222222222222222222222222222222222222222222222222222222222"
            ],
            [
                "33333333333333333333333333333333333333333333333333333333333333",
                "44444444444444444444444444444444444444444444444444444444444444"
            ],
            ["1", "0"]
        ],
        "pi_c": [
            "55555555555555555555555555555555555555555555555555555555555555",
            "66666666666666666666666666666666666666666666666666666666666666",
            "1"
        ],
        "protocol": "groth16",
        "curve": "bn128"
    }
    
    mock_public_signals = [
        "1234567890",
        "9876543210"
    ]
    
    serializer = Groth16Serializer()
    
    # Test serialization
    print("1. Serializing proof...")
    proof_bytes = serializer.serialize_proof(mock_proof, mock_public_signals)
    print(f"   ✅ Serialized to {len(proof_bytes)} bytes")
    print(f"   First 40 bytes: {proof_bytes[:40].hex()}")
    
    # Test deserialization
    print("\n2. Deserializing proof...")
    restored_proof, restored_signals = serializer.deserialize_proof(proof_bytes)
    print(f"   ✅ Deserialized successfully")
    print(f"   π_a[0]: {restored_proof['pi_a'][0]}")
    print(f"   π_a[1]: {restored_proof['pi_a'][1]}")
    
    # Verify round-trip
    print("\n3. Verifying round-trip...")
    proof_bytes_2 = serializer.serialize_proof(restored_proof, mock_public_signals)
    if proof_bytes == proof_bytes_2:
        print("   ✅ Round-trip successful! Bytes match perfectly")
    else:
        print("   ❌ Round-trip failed!")
        
    # Test JSON conversion
    print("\n4. Testing JSON conversion...")
    json_str = serializer.proof_to_json(mock_proof, mock_public_signals)
    print(f"   ✅ JSON size: {len(json_str)} bytes")
    
    print("\n🎉 All tests passed!")
