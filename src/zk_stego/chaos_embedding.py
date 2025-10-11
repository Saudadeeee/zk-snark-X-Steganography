"""
Chaos-based Steganography with Arnold Cat Map and Logistic Map
Generates pseudo-random positions for LSB embedding using chaotic systems
"""

import numpy as np
from typing import List, Tuple, Optional
import hashlib

class ChaosGenerator:
    """Arnold Cat Map + Logistic Map for position generation"""
    
    def __init__(self, image_width: int, image_height: int):
        self.width = image_width
        self.height = image_height
        
    def get_arnold_matrix(self) -> np.ndarray:
        """
        Return the Arnold Cat Map transformation matrix
        
        Standard Arnold Cat Map matrix: [2 1]
                                       [1 1]
        """
        return np.array([[2, 1], 
                        [1, 1]], dtype=int)
    
    def arnold_cat_map_matrix(self, x: int, y: int, iterations: int) -> Tuple[int, int]:
        """
        Arnold Cat Map using explicit matrix multiplication
        
        Transformation: [x_new]   [2 1] [x]
                       [y_new] = [1 1] [y] mod (width, height)
        """
        arnold_matrix = self.get_arnold_matrix()
        
        for _ in range(iterations):
            # Matrix multiplication
            position_vector = np.array([x, y])
            new_position = arnold_matrix @ position_vector
            
            # Apply modulo for torus topology
            x = new_position[0] % self.width
            y = new_position[1] % self.height
            
        return x, y
        
    def arnold_cat_map(self, x: int, y: int, iterations: int) -> Tuple[int, int]:
        """
        Arnold Cat Map transformation using standard matrix form:
        
        Γ([x y]) = [2 1; 1 1] * [x; y] mod N
        
        Matrix form: [x_new]   [2 1] [x]
                     [y_new] = [1 1] [y] mod (width, height)
        
        Equivalently: x_new = (2*x + y) mod width
                      y_new = (x + y) mod height
        """
        for _ in range(iterations):
            # Arnold Cat Map matrix transformation: [2 1; 1 1]
            x_new = (2 * x + y) % self.width
            y_new = (x + y) % self.height
            x, y = x_new, y_new
        return x, y
    
    def logistic_map(self, x0: float, r: float, n: int) -> List[float]:
        """Logistic Map sequence generation"""
        sequence = []
        x = x0
        for _ in range(n):
            x = r * x * (1 - x)
            sequence.append(x)
        return sequence
    
    def generate_positions(
        self, 
        x0: int, 
        y0: int, 
        chaos_key: int,
        num_positions: int
    ) -> List[Tuple[int, int]]:
        """
        Generate chaos-based embedding positions (ensuring uniqueness)
        
        Flow:
        1. Start from feature point (x0, y0) extracted from image
        2. Use Arnold Cat Map for position transformation
        3. Use Logistic Map for sequence generation
        4. Ensure position uniqueness
        """
        
        # Extract chaos parameters from key
        r = 3.7 + (chaos_key % 1000) / 10000  # Logistic parameter: 3.7-3.8
        logistic_x0 = (chaos_key % 10000) / 10000  # Initial condition: 0-1
        arnold_iterations = (chaos_key // 10000) % 10 + 1  # Arnold iterations: 1-10
        
        positions = []
        used_positions = set()
        
        # Start with feature-extracted initial position
        if (x0, y0) not in used_positions:
            positions.append((x0, y0))
            used_positions.add((x0, y0))
        
        # Generate logistic sequence (extra long to handle collisions)
        logistic_seq = self.logistic_map(logistic_x0, r, num_positions * 4)
        
        current_x, current_y = x0, y0
        logistic_idx = 0
        
        while len(positions) < num_positions and logistic_idx < len(logistic_seq) - 1:
            # Apply Arnold Cat Map
            current_x, current_y = self.arnold_cat_map(
                current_x, current_y, arnold_iterations
            )
            
            # Add logistic perturbation
            dx = int(logistic_seq[logistic_idx] * 10) - 5  # -5 to +5
            dy = int(logistic_seq[logistic_idx + 1] * 10) - 5
            logistic_idx += 2
            
            # Ensure positions stay within bounds
            final_x = (current_x + dx) % self.width
            final_y = (current_y + dy) % self.height
            
            # Only add if position is unique
            pos = (final_x, final_y)
            if pos not in used_positions:
                positions.append(pos)
                used_positions.add(pos)
            
        # If we still need more positions, use a simple fallback
        if len(positions) < num_positions:
            for y in range(self.height):
                for x in range(self.width):
                    if len(positions) >= num_positions:
                        break
                    pos = (x, y)
                    if pos not in used_positions:
                        positions.append(pos)
                        used_positions.add(pos)
                if len(positions) >= num_positions:
                    break
            
        return positions[:num_positions]
    
    def verify_chaos_sequence(
        self,
        positions: List[Tuple[int, int]],
        x0: int,
        y0: int, 
        chaos_key: int
    ) -> bool:
        """Verify that positions were generated with given parameters"""
        expected_positions = self.generate_positions(x0, y0, chaos_key, len(positions))
        return positions == expected_positions

class ChaosEmbedding:
    """LSB embedding using chaos-generated positions"""
    
    def __init__(self, image_array: np.ndarray):
        self.image = image_array.copy()
        self.height, self.width = image_array.shape[:2]
        self.chaos_gen = ChaosGenerator(self.width, self.height)
    
    def embed_bits(
        self, 
        bits: List[int], 
        x0: int, 
        y0: int, 
        chaos_key: int,
        channel: int = 0
    ) -> np.ndarray:
        """Embed bits using chaos-based positioning"""
        
        # Generate positions for embedding
        positions = self.chaos_gen.generate_positions(x0, y0, chaos_key, len(bits))
        
        # Ensure we have enough positions
        if len(positions) < len(bits):
            raise ValueError(f"Not enough positions: need {len(bits)}, got {len(positions)}")
        
        # Embed each bit at corresponding position
        for i, bit in enumerate(bits):
            x, y = positions[i]
            # Ensure position is within bounds
            if 0 <= x < self.width and 0 <= y < self.height:
                # Modify LSB of specified channel
                pixel_value = self.image[y, x, channel]
                self.image[y, x, channel] = (pixel_value & 0xFE) | (bit & 1)
            
        return self.image
    
    def extract_bits(
        self, 
        num_bits: int, 
        x0: int, 
        y0: int, 
        chaos_key: int,
        channel: int = 0
    ) -> List[int]:
        """Extract bits using chaos-based positioning"""
        
        # Generate same positions used for embedding
        positions = self.chaos_gen.generate_positions(x0, y0, chaos_key, num_bits)
        
        # Extract LSBs from each position
        bits = []
        for i in range(num_bits):
            if i < len(positions):
                x, y = positions[i]
                # Ensure position is within bounds
                if 0 <= x < self.width and 0 <= y < self.height:
                    lsb = self.image[y, x, channel] & 1
                    bits.append(lsb)
                else:
                    bits.append(0)  # Default for out-of-bounds
            else:
                bits.append(0)  # Default for missing positions
                
        return bits
    
    def calculate_capacity(self) -> int:
        """Calculate maximum embedding capacity"""
        if len(self.image.shape) == 3:
            return self.width * self.height * self.image.shape[2]
        else:
            return self.width * self.height

class ChaosProofArtifact:
    """Hybrid: PNG Chunk + Chaos-based LSB embedding"""
    
    def __init__(self):
        self.chunk_type = b'zkPF'  # zk-Proof chunk metadata
        
    def create_chaos_metadata(
        self, 
        x0: int, 
        y0: int, 
        chaos_key: int,
        proof_length: int
    ) -> dict:
        """Create metadata for PNG chunk"""
        return {
            "initial_position": {"x": x0, "y": y0},
            "chaos_key": chaos_key,
            "proof_length": proof_length,
            "algorithm": "arnold_cat_logistic",
            "version": "1.0"
        }
    
    def embed_proof_chaos(
        self,
        cover_image: np.ndarray,
        proof_data: bytes,
        x0: int,
        y0: int,
        chaos_key: int
    ) -> Tuple[np.ndarray, dict]:
        """
        Embed proof using chaos-based LSB + metadata in PNG chunk
        
        Returns:
            stego_image: Image with embedded proof
            metadata: Metadata for PNG chunk
        """
        
        # Convert proof to bits (MSB first for proper byte reconstruction)
        proof_bits = []
        for byte in proof_data:
            for i in range(7, -1, -1):  # MSB to LSB order
                proof_bits.append((byte >> i) & 1)
        
        # Create chaos embedding
        chaos_embed = ChaosEmbedding(cover_image)
        
        # Check capacity
        capacity = chaos_embed.calculate_capacity()
        if len(proof_bits) > capacity:
            raise ValueError(f"Proof too large: {len(proof_bits)} bits > {capacity} capacity")
        
        # Embed using chaos positioning
        stego_image = chaos_embed.embed_bits(proof_bits, x0, y0, chaos_key)
        
        # Create metadata for PNG chunk
        metadata = self.create_chaos_metadata(x0, y0, chaos_key, len(proof_bits))
        
        return stego_image, metadata
    
    def extract_proof_chaos(
        self,
        stego_image: np.ndarray,
        metadata: dict
    ) -> bytes:
        """Extract proof using chaos-based positioning from metadata"""
        
        # Get chaos parameters from metadata
        x0 = metadata["initial_position"]["x"]
        y0 = metadata["initial_position"]["y"]
        chaos_key = metadata["chaos_key"]
        proof_length = metadata["proof_length"]
        
        # Extract bits using chaos positioning
        chaos_extract = ChaosEmbedding(stego_image)
        proof_bits = chaos_extract.extract_bits(proof_length, x0, y0, chaos_key)
        
        # Convert bits back to bytes (MSB first reconstruction)
        proof_bytes = bytearray()
        for i in range(0, len(proof_bits), 8):
            byte = 0
            for j in range(8):
                if i + j < len(proof_bits):
                    byte |= proof_bits[i + j] << (7 - j)  # MSB to LSB reconstruction
            proof_bytes.append(byte)
        
        return bytes(proof_bytes)

# Utility functions
def generate_chaos_key_from_secret(secret: str) -> int:
    """Generate deterministic chaos key from secret string"""
    hash_obj = hashlib.sha256(secret.encode())
    return int(hash_obj.hexdigest()[:8], 16)

def validate_chaos_parameters(x0: int, y0: int, width: int, height: int) -> bool:
    """Validate initial position is within image bounds"""
    return 0 <= x0 < width and 0 <= y0 < height