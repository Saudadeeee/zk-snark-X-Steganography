"""
Data Interleaver for Burst Error Distribution

Implements block and convolutional interleaving to spread burst errors
across multiple LDPC codewords, improving overall error correction capability.

Week 7 Component - Phase 2: Embedding Enhancement
"""

import numpy as np
from typing import Tuple, Optional, Literal


class DataInterleaver:
    """
    Data Interleaver for Error Distribution
    
    Features:
    - Block interleaving (matrix-based permutation)
    - Convolutional interleaving (delay-based)
    - Configurable block size and depth
    - Byte and bit-level operations
    - De-interleaving support
    """
    
    def __init__(
        self,
        method: Literal['block', 'convolutional'] = 'block',
        block_size: int = 16,
        depth: int = 8
    ):
        """
        Initialize Data Interleaver
        
        Args:
            method: Interleaving method ('block' or 'convolutional')
            block_size: Block size for interleaving (bytes)
            depth: Interleaving depth (number of blocks or delay lines)
        """
        if method not in ['block', 'convolutional']:
            raise ValueError(f"Invalid method: {method}. Must be 'block' or 'convolutional'")
        
        if block_size < 1:
            raise ValueError(f"block_size must be >= 1, got {block_size}")
        
        if depth < 1:
            raise ValueError(f"depth must be >= 1, got {depth}")
        
        self.method = method
        self.block_size = block_size
        self.depth = depth
        
        # For convolutional interleaving
        if method == 'convolutional':
            # Initialize separate delay lines for interleave and deinterleave
            # This is necessary because they use different delay patterns
            self.interleave_delay_lines = [[] for _ in range(depth)]
            self.deinterleave_delay_lines = [[] for _ in range(depth)]
    
    def interleave(self, data: bytes) -> bytes:
        """
        Interleave data using configured method
        
        Args:
            data: Input data bytes
        
        Returns:
            Interleaved data bytes
        """
        if self.method == 'block':
            return self._block_interleave(data)
        else:  # convolutional
            return self._convolutional_interleave(data)
    
    def deinterleave(self, data: bytes) -> bytes:
        """
        De-interleave data (reverse operation)
        
        Args:
            data: Interleaved data bytes
        
        Returns:
            Original data bytes
        """
        if self.method == 'block':
            return self._block_deinterleave(data)
        else:  # convolutional
            return self._convolutional_deinterleave(data)
    
    def _block_interleave(self, data: bytes) -> bytes:
        """
        Block interleaving using matrix permutation
        
        Algorithm:
        1. Store original length (4 bytes)
        2. Arrange data in matrix (depth × block_size)
        3. Write row-by-row, read column-by-column
        4. Distributes burst errors across different codewords
        
        Args:
            data: Input data
        
        Returns:
            Interleaved data with prepended length header
        """
        data_array = np.frombuffer(data, dtype=np.uint8)
        original_length = len(data_array)
        
        # Calculate required padding
        matrix_size = self.depth * self.block_size
        padding_needed = (matrix_size - (len(data_array) % matrix_size)) % matrix_size
        
        # Pad if necessary
        if padding_needed > 0:
            data_array = np.concatenate([data_array, np.zeros(padding_needed, dtype=np.uint8)])
        
        # Reshape into blocks
        num_matrices = len(data_array) // matrix_size
        interleaved = np.zeros_like(data_array)
        
        for i in range(num_matrices):
            start_idx = i * matrix_size
            end_idx = start_idx + matrix_size
            
            # Extract block
            block = data_array[start_idx:end_idx]
            
            # Reshape to matrix (write row-by-row)
            matrix = block.reshape(self.depth, self.block_size)
            
            # Transpose and flatten (read column-by-column)
            interleaved_block = matrix.T.flatten()
            
            # Store interleaved block
            interleaved[start_idx:end_idx] = interleaved_block
        
        # Prepend original length (4 bytes, little-endian)
        length_bytes = original_length.to_bytes(4, byteorder='little')
        
        return length_bytes + interleaved.tobytes()
    
    def _block_deinterleave(self, data: bytes) -> bytes:
        """
        Block de-interleaving (inverse operation)
        
        Algorithm:
        1. Extract original length (4 bytes)
        2. Arrange data in matrix (block_size × depth)
        3. Write row-by-row, read column-by-column
        4. Restores original data order
        5. Trim to original length
        
        Args:
            data: Interleaved data with length header
        
        Returns:
            Original data
        """
        # Extract original length from header
        original_length = int.from_bytes(data[:4], byteorder='little')
        data_array = np.frombuffer(data[4:], dtype=np.uint8)
        
        # Calculate matrix size
        matrix_size = self.depth * self.block_size
        
        # Reshape into blocks
        num_matrices = len(data_array) // matrix_size
        deinterleaved = np.zeros_like(data_array)
        
        for i in range(num_matrices):
            start_idx = i * matrix_size
            end_idx = start_idx + matrix_size
            
            # Extract interleaved block
            block = data_array[start_idx:end_idx]
            
            # Reshape to matrix (write row-by-row)
            matrix = block.reshape(self.block_size, self.depth)
            
            # Transpose and flatten (read column-by-column)
            deinterleaved_block = matrix.T.flatten()
            
            # Store deinterleaved block
            deinterleaved[start_idx:end_idx] = deinterleaved_block
        
        # Trim to original length
        result = deinterleaved[:original_length]
        
        return result.tobytes()
        result = deinterleaved[:len(data)]
        
        return result.tobytes()
    
    def _convolutional_interleave(self, data: bytes) -> bytes:
        """
        Convolutional interleaving using delay lines
        
        Algorithm:
        1. Store original length (4 bytes)
        2. Each input byte goes to ONE delay line in round-robin fashion
        3. Line 0 has delay 0*B, Line 1 has delay 1*B, ..., Line (depth-1) has delay (depth-1)*B
        4. Output is taken from delay lines in same round-robin order
        
        Args:
            data: Input data
        
        Returns:
            Interleaved data with length header
        """
        data_array = np.frombuffer(data, dtype=np.uint8)
        original_length = len(data_array)
        interleaved = []
        
        # Process each input byte
        for idx, byte_val in enumerate(data_array):
            # Determine which delay line (round-robin)
            line_idx = idx % self.depth
            
            # Add to delay line
            self.interleave_delay_lines[line_idx].append(byte_val)
            
            # Check if we can output from this line
            delay_amount = line_idx * self.block_size
            if len(self.interleave_delay_lines[line_idx]) > delay_amount:
                output_byte = self.interleave_delay_lines[line_idx].pop(0)
                interleaved.append(output_byte)
        
        # Flush remaining data from all delay lines (in order)
        for line_idx in range(self.depth):
            while len(self.interleave_delay_lines[line_idx]) > 0:
                output_byte = self.interleave_delay_lines[line_idx].pop(0)
                interleaved.append(output_byte)
        
        # Convert to bytes
        result = np.array(interleaved, dtype=np.uint8)
        
        # Prepend original length (4 bytes, little-endian)
        length_bytes = original_length.to_bytes(4, byteorder='little')
        
        return length_bytes + result.tobytes()
    
    def _convolutional_deinterleave(self, data: bytes) -> bytes:
        """
        Convolutional de-interleaving (inverse operation)
        
        Algorithm:
        1. Extract original length (4 bytes)
        2. Each input byte goes to ONE delay line in round-robin fashion
        3. Use REVERSE delays: Line 0 has delay (depth-1)*B, Line 1 has (depth-2)*B, ...
        4. This undoes the interleaving effect
        
        Args:
            data: Interleaved data with length header
        
        Returns:
            Original data
        """
        # Extract original length from header
        original_length = int.from_bytes(data[:4], byteorder='little')
        data_array = np.frombuffer(data[4:], dtype=np.uint8)
        deinterleaved = []
        
        # Process each input byte
        for idx, byte_val in enumerate(data_array):
            # Determine which delay line (round-robin)
            line_idx = idx % self.depth
            
            # Add to delay line
            self.deinterleave_delay_lines[line_idx].append(byte_val)
            
            # Check if we can output from this line (REVERSE delay)
            delay_amount = (self.depth - 1 - line_idx) * self.block_size
            if len(self.deinterleave_delay_lines[line_idx]) > delay_amount:
                output_byte = self.deinterleave_delay_lines[line_idx].pop(0)
                deinterleaved.append(output_byte)
        
        # Flush remaining data from all delay lines (in order)
        for line_idx in range(self.depth):
            while len(self.deinterleave_delay_lines[line_idx]) > 0:
                output_byte = self.deinterleave_delay_lines[line_idx].pop(0)
                deinterleaved.append(output_byte)
        
        # Convert to bytes and trim to original length
        result = np.array(deinterleaved[:original_length], dtype=np.uint8)
        
        return result.tobytes()
    
    def reset_state(self):
        """
        Reset convolutional interleaver state (clear delay lines)
        """
        if self.method == 'convolutional':
            self.interleave_delay_lines = [[] for _ in range(self.depth)]
            self.deinterleave_delay_lines = [[] for _ in range(self.depth)]
    
    def get_config(self) -> dict:
        """
        Get interleaver configuration
        
        Returns:
            Configuration dictionary
        """
        config = {
            'method': self.method,
            'block_size': self.block_size,
            'depth': self.depth,
            'interleaving_span': self.block_size * self.depth,
            'max_burst_protection': self.block_size if self.method == 'block' else self.block_size * self.depth
        }
        
        if self.method == 'convolutional':
            config['total_delay'] = sum(i * self.block_size for i in range(self.depth))
        
        return config
    
    def simulate_burst_error(
        self,
        data: bytes,
        burst_position: int,
        burst_length: int
    ) -> bytes:
        """
        Simulate burst error in data (for testing)
        
        Args:
            data: Original data
            burst_position: Starting position of burst
            burst_length: Length of burst error in bytes
        
        Returns:
            Data with burst error injected
        """
        data_array = bytearray(data)
        
        # Ensure burst doesn't exceed data length
        end_pos = min(burst_position + burst_length, len(data_array))
        
        # Flip all bits in burst region
        for i in range(burst_position, end_pos):
            data_array[i] ^= 0xFF
        
        return bytes(data_array)
    
    def measure_burst_distribution(
        self,
        original: bytes,
        corrupted: bytes,
        window_size: int = 16
    ) -> dict:
        """
        Measure how burst errors are distributed after interleaving
        
        Args:
            original: Original data
            corrupted: Corrupted data
            window_size: Size of window to check for consecutive errors
        
        Returns:
            Distribution statistics
        """
        orig_array = np.frombuffer(original, dtype=np.uint8)
        corr_array = np.frombuffer(corrupted, dtype=np.uint8)
        
        # Find error positions
        errors = orig_array != corr_array
        error_positions = np.where(errors)[0]
        
        if len(error_positions) == 0:
            return {
                'total_errors': 0,
                'max_consecutive': 0,
                'avg_spacing': 0,
                'burst_windows': 0
            }
        
        # Calculate consecutive errors
        max_consecutive = 1
        current_consecutive = 1
        
        for i in range(1, len(error_positions)):
            if error_positions[i] == error_positions[i-1] + 1:
                current_consecutive += 1
                max_consecutive = max(max_consecutive, current_consecutive)
            else:
                current_consecutive = 1
        
        # Calculate average spacing
        if len(error_positions) > 1:
            spacings = np.diff(error_positions)
            avg_spacing = float(np.mean(spacings))
        else:
            avg_spacing = 0
        
        # Count burst windows
        burst_windows = 0
        for i in range(len(orig_array) - window_size + 1):
            window_errors = np.sum(errors[i:i+window_size])
            if window_errors > window_size / 2:  # More than 50% errors
                burst_windows += 1
        
        return {
            'total_errors': int(np.sum(errors)),
            'max_consecutive': max_consecutive,
            'avg_spacing': avg_spacing,
            'burst_windows': burst_windows,
            'error_rate': float(np.sum(errors)) / len(orig_array)
        }
