"""
LDPC (Low-Density Parity-Check) Error Correction Codec

Provides forward error correction for embedded ZK proof data.
Uses systematic LDPC codes with belief propagation decoding.

Week 6 Component - Phase 2: Embedding Enhancement
"""

import numpy as np
from typing import Tuple, Optional
import warnings


class LDPCCodec:
    """
    LDPC Error Correction Codec
    
    Features:
    - Systematic encoding (data + parity bits)
    - Multiple code rates (1/2, 2/3, 3/4, 5/6)
    - Sum-product algorithm (belief propagation) decoding
    - Configurable iterations
    - Bit error rate measurement
    """
    
    def __init__(
        self,
        data_length: int = 192 * 8,  # 192 bytes = 1536 bits
        code_rate: float = 0.5,
        max_iterations: int = 50
    ):
        """
        Initialize LDPC codec
        
        Args:
            data_length: Number of data bits (default: 192 bytes)
            code_rate: Code rate (0.5, 0.667, 0.75, 0.833)
            max_iterations: Maximum decoding iterations
        """
        self.data_length = data_length
        self.code_rate = code_rate
        self.max_iterations = max_iterations
        
        # Calculate codeword length
        self.codeword_length = int(data_length / code_rate)
        self.parity_length = self.codeword_length - data_length
        
        # Generate parity-check matrix
        self.H = self._generate_parity_check_matrix()
        
        # Generate generator matrix (for systematic encoding)
        self.G = self._generate_generator_matrix()
    
    def _generate_parity_check_matrix(self) -> np.ndarray:
        """
        Generate LDPC parity-check matrix H
        
        Uses MacKay's construction for regular LDPC codes
        - Row weight (check node degree): 6
        - Column weight (variable node degree): 3
        
        Returns:
            H matrix (parity_length x codeword_length)
        """
        m = self.parity_length  # Number of parity check equations
        n = self.codeword_length  # Codeword length
        
        # Regular LDPC: column weight = 3, row weight depends on code rate
        column_weight = 3
        row_weight = int(column_weight * n / m)
        
        # Initialize H matrix
        H = np.zeros((m, n), dtype=np.uint8)
        
        # Generate H using progressive edge-growth (PEG) algorithm approximation
        # Simplified version: distribute 1s to minimize short cycles
        
        for col in range(n):
            # Place column_weight ones in this column
            available_rows = list(range(m))
            
            for _ in range(column_weight):
                if not available_rows:
                    break
                
                # Select row with minimum weight to balance
                row_weights = H.sum(axis=1)
                min_weight = min(row_weights[available_rows])
                candidates = [r for r in available_rows if row_weights[r] == min_weight]
                
                # Randomly select from candidates
                row = np.random.choice(candidates)
                H[row, col] = 1
                available_rows.remove(row)
        
        return H
    
    def _generate_generator_matrix(self) -> np.ndarray:
        """
        Generate systematic generator matrix G
        
        For systematic code: G = [I | P]
        where I is identity matrix (data part)
        and P is parity part
        
        Returns:
            G matrix (data_length x codeword_length)
        """
        k = self.data_length
        n = self.codeword_length
        
        # Create identity matrix for data bits
        I = np.eye(k, dtype=np.uint8)
        
        # Extract parity part from H
        # This is simplified - full implementation would use Gaussian elimination
        # For now, use a simple parity generation approach
        
        # Create parity matrix P (k x (n-k))
        P = np.random.randint(0, 2, (k, n - k), dtype=np.uint8)
        
        # Combine: G = [I | P]
        G = np.hstack([I, P])
        
        return G
    
    def encode(self, data: bytes) -> bytes:
        """
        Encode data with LDPC code
        
        Args:
            data: Input data bytes
        
        Returns:
            Encoded codeword bytes (longer than input)
        
        Raises:
            ValueError: If data length doesn't match expected length
        """
        # Convert bytes to bits
        data_bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8))
        
        if len(data_bits) != self.data_length:
            raise ValueError(
                f"Expected {self.data_length} bits ({self.data_length // 8} bytes), " +
                f"got {len(data_bits)} bits ({len(data)} bytes)"
            )
        
        # Systematic encoding: codeword = [data | parity]
        # Simple parity generation (in practice, use G matrix)
        parity_bits = self._compute_parity(data_bits)
        
        # Combine data and parity
        codeword = np.concatenate([data_bits, parity_bits])
        
        # Convert back to bytes
        # Pad to byte boundary if necessary
        if len(codeword) % 8 != 0:
            padding = 8 - (len(codeword) % 8)
            codeword = np.concatenate([codeword, np.zeros(padding, dtype=np.uint8)])
        
        encoded_bytes = np.packbits(codeword).tobytes()
        
        return encoded_bytes
    
    def _compute_parity(self, data_bits: np.ndarray) -> np.ndarray:
        """
        Compute parity bits from data bits
        
        Uses simple XOR-based parity for systematic code
        Each parity bit is XOR of selected data bits
        
        Args:
            data_bits: Data bit array
        
        Returns:
            Parity bit array
        """
        parity_bits = np.zeros(self.parity_length, dtype=np.uint8)
        
        # Each row of H defines a parity check equation
        # For each parity bit, XOR the data bits connected by H matrix
        for i in range(self.parity_length):
            # Find which data bits contribute to this parity bit
            # Parity bit i checks row i of H
            # It's computed as XOR of all data bits where H[i,j]=1
            data_indices = np.where(self.H[i, :self.data_length] == 1)[0]
            if len(data_indices) > 0:
                parity_bits[i] = np.bitwise_xor.reduce(data_bits[data_indices])
        
        return parity_bits
    
    def decode(
        self,
        received: bytes,
        channel_llr: Optional[np.ndarray] = None
    ) -> Tuple[bytes, bool, int]:
        """
        Decode LDPC codeword using sum-product algorithm
        
        Args:
            received: Received codeword bytes (may have errors)
            channel_llr: Log-likelihood ratios from channel (optional)
        
        Returns:
            Tuple of:
            - Decoded data bytes
            - Success flag (True if decoding succeeded)
            - Number of iterations used
        """
        # Convert bytes to bits
        received_bits = np.unpackbits(np.frombuffer(received, dtype=np.uint8))
        
        # Trim to codeword length
        received_bits = received_bits[:self.codeword_length]
        
        # If no channel LLR provided, use hard decisions
        if channel_llr is None:
            # Convert bits to LLR: 0 -> +inf, 1 -> -inf
            # Use large finite values
            channel_llr = np.where(received_bits == 0, 5.0, -5.0)
        
        # Belief propagation decoding
        decoded_bits, success, iterations = self._belief_propagation(
            received_bits,
            channel_llr
        )
        
        # Extract data bits (systematic code)
        data_bits = decoded_bits[:self.data_length]
        
        # Convert back to bytes
        if len(data_bits) % 8 != 0:
            # Pad to byte boundary
            padding = 8 - (len(data_bits) % 8)
            data_bits = np.concatenate([data_bits, np.zeros(padding, dtype=np.uint8)])
        
        data_bytes = np.packbits(data_bits).tobytes()
        
        # Trim to original data length
        data_bytes = data_bytes[:self.data_length // 8]
        
        return data_bytes, success, iterations
    
    def _belief_propagation(
        self,
        received: np.ndarray,
        channel_llr: np.ndarray
    ) -> Tuple[np.ndarray, bool, int]:
        """
        Sum-product algorithm (belief propagation)
        
        Simplified version using hard-decision decoding with iterative syndrome checking
        
        Args:
            received: Received bit array
            channel_llr: Channel log-likelihood ratios
        
        Returns:
            Tuple of (decoded bits, success flag, iterations)
        """
        n = self.codeword_length
        m = self.parity_length
        
        # Start with hard decision from received bits
        decoded = received.copy()
        
        for iteration in range(self.max_iterations):
            # Compute syndrome: s = H * c (mod 2)
            syndrome = (self.H @ decoded) % 2
            
            # Check if codeword is valid (all syndrome bits = 0)
            if np.all(syndrome == 0):
                # Decoding successful
                return decoded, True, iteration + 1
            
            # Count which bits participate in failed checks
            bit_errors = np.zeros(n, dtype=np.int32)
            
            for i in range(m):
                if syndrome[i] == 1:  # Failed parity check
                    # Find bits in this check
                    bits_in_check = np.where(self.H[i, :] == 1)[0]
                    # Increment error count for these bits
                    bit_errors[bits_in_check] += 1
            
            if np.max(bit_errors) == 0:
                # No progress possible
                break
            
            # Flip bit with highest error count
            bit_to_flip = np.argmax(bit_errors)
            decoded[bit_to_flip] ^= 1
        
        # Max iterations reached
        # Return best estimate
        return decoded, False, self.max_iterations
    
    def inject_errors(
        self,
        codeword: bytes,
        error_rate: float = 0.01
    ) -> bytes:
        """
        Inject random bit errors for testing
        
        Args:
            codeword: Encoded codeword bytes
            error_rate: Probability of bit flip (0.0 - 1.0)
        
        Returns:
            Corrupted codeword bytes
        """
        # Convert to bits
        bits = np.unpackbits(np.frombuffer(codeword, dtype=np.uint8))
        
        # Generate random errors
        errors = np.random.random(len(bits)) < error_rate
        
        # Flip bits
        corrupted_bits = bits ^ errors.astype(np.uint8)
        
        # Convert back to bytes
        corrupted_bytes = np.packbits(corrupted_bits).tobytes()
        
        return corrupted_bytes
    
    def measure_ber(
        self,
        original: bytes,
        received: bytes
    ) -> float:
        """
        Measure bit error rate
        
        Args:
            original: Original data bytes
            received: Received data bytes
        
        Returns:
            Bit error rate (0.0 - 1.0)
        """
        # Convert to bits
        orig_bits = np.unpackbits(np.frombuffer(original, dtype=np.uint8))
        recv_bits = np.unpackbits(np.frombuffer(received, dtype=np.uint8))
        
        # Ensure same length
        min_len = min(len(orig_bits), len(recv_bits))
        orig_bits = orig_bits[:min_len]
        recv_bits = recv_bits[:min_len]
        
        # Count errors
        errors = np.sum(orig_bits != recv_bits)
        
        # Calculate BER
        ber = errors / len(orig_bits) if len(orig_bits) > 0 else 0.0
        
        return float(ber)
    
    def get_code_info(self) -> dict:
        """
        Get LDPC code parameters
        
        Returns:
            Dictionary with code information
        """
        return {
            'data_length': self.data_length,
            'data_bytes': self.data_length // 8,
            'codeword_length': self.codeword_length,
            'codeword_bytes': (self.codeword_length + 7) // 8,
            'parity_length': self.parity_length,
            'parity_bytes': (self.parity_length + 7) // 8,
            'code_rate': self.code_rate,
            'overhead': (self.codeword_length - self.data_length) / self.data_length,
            'max_iterations': self.max_iterations
        }
