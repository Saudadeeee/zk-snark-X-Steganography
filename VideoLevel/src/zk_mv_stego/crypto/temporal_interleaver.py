"""
Temporal Interleaver for ZK-SNARK Video Steganography v3.0

Distributes LDPC-encoded payload across multiple video frames using a recurrent strategy
where each frame's embedding depends on the previous frame's hash. This provides:
1. Temporal spreading to avoid burst errors
2. Security through frame-dependency
3. Robustness to frame loss (LDPC can recover)

Week 8 Implementation - Phase 3
"""

import numpy as np
import hashlib
from typing import List, Tuple, Optional


class TemporalInterleaver:
    """
    Temporal interleaver that distributes payload across multiple frames
    
    Features:
    - Chunks payload into n equal-sized pieces
    - Pseudo-random permutation for security
    - Recurrent frame dependency (frame n+1 depends on frame n hash)
    - Robust to missing frames (LDPC recovery)
    
    Example:
        >>> interleaver = TemporalInterleaver(num_frames=10)
        >>> chunks, indices = interleaver.interleave(ldpc_data)
        >>> # Embed chunks[i] in frame i
        >>> recovered = interleaver.deinterleave(extracted_chunks, indices)
    """
    
    def __init__(self, num_frames: int = 10, secret_seed: Optional[bytes] = None):
        """
        Initialize temporal interleaver
        
        Args:
            num_frames: Number of frames to distribute payload across (default: 10)
            secret_seed: Seed for PRNG (from ZK secret). If None, uses default seed
        
        Raises:
            ValueError: If num_frames < 2
        """
        if num_frames < 2:
            raise ValueError(f"num_frames must be >= 2, got {num_frames}")
        
        self.num_frames = num_frames
        
        # Initialize PRNG with secret seed
        if secret_seed is None:
            seed_int = 42  # Default seed for deterministic testing
        else:
            # Use first 4 bytes of seed as integer
            seed_int = int.from_bytes(secret_seed[:4], byteorder='big')
        
        self.rng = np.random.RandomState(seed_int)
        self.permutation_indices: Optional[List[int]] = None
        self.chunk_sizes: Optional[List[int]] = None  # Store for recovery
    
    def interleave(self, payload: bytes) -> Tuple[List[bytes], List[int]]:
        """
        Distribute payload across n frames with pseudo-random permutation
        
        Algorithm:
        1. Split payload into n equal-sized chunks
        2. Apply pseudo-random permutation to chunk order
        3. Return permuted chunks and permutation indices
        
        Args:
            payload: LDPC-encoded data to distribute (e.g., 384 bytes)
        
        Returns:
            Tuple of:
            - chunks: List of n byte chunks (permuted)
            - indices: Permutation indices for deinterleaving
        
        Raises:
            ValueError: If payload is empty
        
        Example:
            >>> payload = b"A" * 100
            >>> chunks, indices = interleaver.interleave(payload)
            >>> len(chunks)  # num_frames
            10
            >>> sum(len(c) for c in chunks)  # Total bytes preserved
            100
        """
        if not payload:
            raise ValueError("Payload cannot be empty")
        
        payload_len = len(payload)
        
        # Calculate chunk size (distribute evenly)
        base_chunk_size = payload_len // self.num_frames
        remainder = payload_len % self.num_frames
        
        # Split into chunks (first 'remainder' chunks get +1 byte)
        chunks = []
        offset = 0
        
        for i in range(self.num_frames):
            # First 'remainder' chunks are 1 byte larger
            chunk_size = base_chunk_size + (1 if i < remainder else 0)
            chunk = payload[offset:offset + chunk_size]
            chunks.append(chunk)
            offset += chunk_size
        
        # Generate pseudo-random permutation
        indices = list(range(self.num_frames))
        self.rng.shuffle(indices)
        
        # Store for reconstruction
        self.permutation_indices = indices.copy()
        self.chunk_sizes = [len(c) for c in chunks]  # Store exact sizes
        
        # Apply permutation to chunks
        permuted_chunks = [chunks[i] for i in indices]
        
        return permuted_chunks, indices
    
    def deinterleave(self, chunks: List[bytes], indices: List[int]) -> bytes:
        """
        Reconstruct payload from distributed chunks
        
        Algorithm:
        1. Reverse permutation using stored indices
        2. Handle missing chunks (fill with zeros for LDPC recovery)
        3. Concatenate chunks to restore original payload
        
        Args:
            chunks: List of extracted chunks (may have Nones for missing frames)
            indices: Permutation indices from interleave()
        
        Returns:
            Reconstructed payload bytes
        
        Raises:
            ValueError: If indices length doesn't match num_frames
        
        Example:
            >>> # Simulate missing frame 3
            >>> chunks[3] = None
            >>> recovered = interleaver.deinterleave(chunks, indices)
            >>> # LDPC will recover the missing chunk
        """
        if len(indices) != self.num_frames:
            raise ValueError(f"Expected {self.num_frames} indices, got {len(indices)}")
        
        # Restore original order
        ordered_chunks = [None] * self.num_frames
        
        for perm_idx, orig_idx in enumerate(indices):
            if perm_idx < len(chunks) and chunks[perm_idx] is not None:
                ordered_chunks[orig_idx] = chunks[perm_idx]
        
        # Handle missing chunks (fill with zeros using stored chunk sizes)
        if self.chunk_sizes is None:
            # Fallback: compute average from available chunks
            available_chunks = [c for c in chunks if c is not None]
            if available_chunks:
                avg_chunk_size = sum(len(c) for c in available_chunks) // len(available_chunks)
            else:
                avg_chunk_size = 40  # Default
            chunk_sizes_to_use = [avg_chunk_size] * self.num_frames
        else:
            chunk_sizes_to_use = self.chunk_sizes
        
        for i in range(self.num_frames):
            if ordered_chunks[i] is None:
                # Use exact original chunk size
                ordered_chunks[i] = b'\x00' * chunk_sizes_to_use[i]
        
        # Concatenate all chunks
        return b''.join(ordered_chunks)
    
    def compute_frame_dependency(self, frame_idx: int, prev_hash: bytes) -> int:
        """
        Compute embedding position based on previous frame (recurrent strategy)
        
        This creates a chain of dependencies where frame n+1 depends on frame n's hash,
        making it impossible to extract payload without processing frames in order.
        
        Algorithm:
        1. Hash previous frame's data
        2. Convert hash to integer
        3. Use modulo to get macroblock starting index
        
        Args:
            frame_idx: Current frame index (0-based)
            prev_hash: Hash of previous frame's embedded data
        
        Returns:
            Starting macroblock index for embedding (0-99)
        
        Example:
            >>> # Frame 0
            >>> start_mb = interleaver.compute_frame_dependency(0, b"initial_seed")
            >>> # Frame 1 depends on Frame 0's hash
            >>> hash_0 = hashlib.sha256(chunks[0]).digest()
            >>> start_mb = interleaver.compute_frame_dependency(1, hash_0)
        """
        if frame_idx == 0:
            # First frame uses initial seed
            seed = prev_hash
        else:
            # Subsequent frames use hash of previous data
            seed = prev_hash
        
        # Hash to get deterministic pseudo-random position
        hash_val = int.from_bytes(hashlib.sha256(seed).digest()[:4], byteorder='big')
        
        # Return macroblock index (0-99 for typical video)
        return hash_val % 100
    
    def get_frame_chain(self, chunks: List[bytes], initial_seed: bytes) -> List[Tuple[int, bytes]]:
        """
        Generate full frame dependency chain
        
        Creates a recurrent sequence where each frame's position depends on all
        previous frames, providing strong security against partial extraction.
        
        Args:
            chunks: List of payload chunks to embed
            initial_seed: Initial hash/seed for frame 0
        
        Returns:
            List of (macroblock_start_index, frame_hash) tuples for each frame
        
        Example:
            >>> chain = interleaver.get_frame_chain(chunks, b"secret_seed")
            >>> for frame_idx, (mb_start, frame_hash) in enumerate(chain):
            ...     print(f"Frame {frame_idx}: embed at MB {mb_start}")
        """
        chain = []
        prev_hash = initial_seed
        
        for frame_idx, chunk in enumerate(chunks):
            # Compute starting position based on previous hash
            mb_start = self.compute_frame_dependency(frame_idx, prev_hash)
            
            # Hash current chunk for next frame
            current_hash = hashlib.sha256(chunk).digest()
            
            chain.append((mb_start, current_hash))
            
            # Update prev_hash for next iteration (cumulative hash)
            prev_hash = hashlib.sha256(prev_hash + current_hash).digest()
        
        return chain
    
    def validate_chunk_sizes(self, chunks: List[bytes]) -> bool:
        """
        Validate that chunks have reasonable sizes
        
        Args:
            chunks: List of chunks to validate
        
        Returns:
            True if all chunks are valid size
        """
        if not chunks:
            return False
        
        chunk_sizes = [len(c) for c in chunks if c is not None]
        if not chunk_sizes:
            return False
        
        # Check that sizes are relatively uniform (within 2 bytes)
        max_size = max(chunk_sizes)
        min_size = min(chunk_sizes)
        
        return (max_size - min_size) <= 2
    
    def get_config(self) -> dict:
        """
        Get interleaver configuration
        
        Returns:
            Configuration dictionary
        """
        return {
            'num_frames': self.num_frames,
            'permutation_indices': self.permutation_indices,
            'random_seed': self.rng.get_state()[1][0]  # Get seed from state
        }
    
    def reset(self):
        """
        Reset interleaver state (clear permutation cache)
        """
        self.permutation_indices = None
        self.chunk_sizes = None


def create_frame_manifest(chunks: List[bytes], indices: List[int], 
                          initial_seed: bytes) -> dict:
    """
    Create a manifest describing the temporal distribution
    
    This manifest can be used to verify correct extraction order and
    to recover from partial frame loss.
    
    Args:
        chunks: List of payload chunks
        indices: Permutation indices
        initial_seed: Initial seed for frame 0
    
    Returns:
        Manifest dictionary with frame information
    
    Example:
        >>> manifest = create_frame_manifest(chunks, indices, b"seed")
        >>> print(manifest['frame_count'])
        10
    """
    manifest = {
        'frame_count': len(chunks),
        'total_bytes': sum(len(c) for c in chunks if c is not None),
        'chunk_sizes': [len(c) if c is not None else 0 for c in chunks],
        'permutation': indices,
        'initial_seed_hash': hashlib.sha256(initial_seed).hexdigest()[:16],
        'frames': []
    }
    
    # Add per-frame info
    prev_hash = initial_seed
    for i, chunk in enumerate(chunks):
        chunk_hash = hashlib.sha256(chunk).digest() if chunk else b'\x00' * 32
        frame_info = {
            'index': i,
            'size': len(chunk) if chunk else 0,
            'hash': hashlib.sha256(chunk).hexdigest()[:16] if chunk else "00" * 8,
            'mb_start': int.from_bytes(hashlib.sha256(prev_hash).digest()[:4], 'big') % 100
        }
        manifest['frames'].append(frame_info)
        prev_hash = hashlib.sha256(prev_hash + chunk_hash).digest()
    
    return manifest
