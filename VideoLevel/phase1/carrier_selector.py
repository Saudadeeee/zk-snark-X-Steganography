"""
Chaos-based Carrier Selection
==============================

Sử dụng chaos maps để chọn MV positions để nhúng payload.
Đảm bảo embedder và extractor dùng cùng seed → cùng carrier sequence.

Chaos Maps:
1. Logistic Map: x_{n+1} = r * x_n * (1 - x_n)
2. Arnold Cat Map: 2D chaotic transformation

Features:
- Deterministic (same seed → same sequence)
- Pseudo-random distribution
- High sensitivity to initial conditions
"""

import numpy as np
from typing import List, Tuple
from dataclasses import dataclass


@dataclass
class MVCandidate:
    """Motion vector candidate for embedding"""
    frame_idx: int
    mv_index: int  # Index in frame's MV list
    mb_x: int
    mb_y: int
    mvx: int
    mvy: int
    magnitude: float
    priority: float = 0.0  # Higher = better candidate


class ChaosMap:
    """Chaos-based pseudo-random generator"""
    
    def __init__(self, seed: int, map_type: str = 'logistic'):
        """
        Initialize chaos map
        
        Args:
            seed: Integer seed (0 - 2^32)
            map_type: 'logistic' or 'arnold'
        """
        self.seed = seed
        self.map_type = map_type
        
        # Normalize seed to [0, 1)
        self.x = (seed % 10000) / 10000.0
        
        # Logistic map parameter (3.57 < r < 4.0 for chaos)
        self.r = 3.9
    
    def next(self) -> float:
        """Generate next value in [0, 1)"""
        if self.map_type == 'logistic':
            self.x = self.r * self.x * (1 - self.x)
            return self.x
        else:
            raise NotImplementedError(f"Map type {self.map_type} not implemented")
    
    def next_int(self, max_val: int) -> int:
        """Generate integer in [0, max_val)"""
        return int(self.next() * max_val)


class CarrierSelector:
    """Select MV positions for embedding using chaos-based selection"""
    
    def __init__(self, 
                 seed: int,
                 min_magnitude: float = 2.0,  # Stable under ±1 modification
                 max_magnitude: float = 50.0,
                 embedding_rate: float = 0.1,
                 prefer_component: str = 'mvx'):
        """
        Initialize carrier selector
        
        Args:
            seed: Chaos map seed (shared secret)
            min_magnitude: Minimum MV magnitude (>=2.0 for stability)
            max_magnitude: Maximum MV magnitude to consider
            embedding_rate: Fraction of MVs to use (0.0 - 1.0)
            prefer_component: 'mvx', 'mvy', or 'both'
        """
        self.seed = seed
        self.chaos = ChaosMap(seed)
        self.min_magnitude = min_magnitude
        self.max_magnitude = max_magnitude
        self.embedding_rate = embedding_rate
        self.prefer_component = prefer_component
    
    def select_carriers(self, 
                       mv_data: List[dict],
                       required_bits: int) -> List[MVCandidate]:
        """
        Select carrier MVs for embedding
        
        Args:
            mv_data: List of MV dicts from h264_parser
            required_bits: Number of bits to embed
            
        Returns:
            List of selected MV candidates (sorted by frame_idx)
        """
        # Filter eligible MVs
        candidates = []
        
        for idx, mv in enumerate(mv_data):
            magnitude = np.sqrt(mv['mvx']**2 + mv['mvy']**2)
            
            # Filter by magnitude
            if magnitude < self.min_magnitude or magnitude > self.max_magnitude:
                continue
            
            # Filter by frame type (only P-frames)
            if mv['frame_type'] != 'P':
                continue
            
            # Create candidate
            candidate = MVCandidate(
                frame_idx=mv['frame_idx'],
                mv_index=idx,
                mb_x=mv['mb_x'],
                mb_y=mv['mb_y'],
                mvx=mv['mvx'],
                mvy=mv['mvy'],
                magnitude=magnitude
            )
            
            # Calculate priority (higher magnitude = more stable)
            candidate.priority = magnitude
            
            candidates.append(candidate)
        
        print(f"[INFO] Found {len(candidates)} eligible MVs (magnitude {self.min_magnitude}-{self.max_magnitude})")
        
        # Select subset using chaos-based shuffling
        selected = self._chaos_select(candidates, required_bits)
        
        print(f"[INFO] Selected {len(selected)} carriers for {required_bits} bits")
        
        return selected
    
    def _chaos_select(self, 
                     candidates: List[MVCandidate],
                     required_bits: int) -> List[MVCandidate]:
        """
        Select carriers using chaos map
        
        Strategy:
        1. Sort candidates by priority (magnitude)
        2. Use chaos map to generate permutation
        3. Select top N candidates from shuffled list
        """
        if len(candidates) == 0:
            return []
        
        # Calculate how many MVs needed
        # Each MV can carry 1 bit (mvx or mvy LSB)
        needed_mvs = required_bits
        
        # Limit by embedding rate
        max_allowed = int(len(candidates) * self.embedding_rate)
        needed_mvs = min(needed_mvs, max_allowed)
        
        if needed_mvs > len(candidates):
            print(f"[WARNING] Not enough carriers: need {needed_mvs}, have {len(candidates)}")
            return candidates
        
        # Chaos-based permutation
        indices = list(range(len(candidates)))
        
        # Fisher-Yates shuffle with chaos map
        chaos_perm = ChaosMap(self.seed)
        for i in range(len(indices) - 1, 0, -1):
            j = chaos_perm.next_int(i + 1)
            indices[i], indices[j] = indices[j], indices[i]
        
        # Select first N from shuffled list
        selected_indices = sorted(indices[:needed_mvs])
        
        selected = [candidates[i] for i in selected_indices]
        
        # Sort by frame_idx for sequential embedding
        selected.sort(key=lambda x: (x.frame_idx, x.mv_index))
        
        return selected


def test_chaos_map():
    """Test chaos map determinism"""
    print("Testing Chaos Map Determinism")
    print("=" * 50)
    
    # Same seed should produce same sequence
    seed = 12345
    
    chaos1 = ChaosMap(seed)
    seq1 = [chaos1.next() for _ in range(10)]
    
    chaos2 = ChaosMap(seed)
    seq2 = [chaos2.next() for _ in range(10)]
    
    print(f"Seed: {seed}")
    print(f"Sequence 1: {seq1[:5]}")
    print(f"Sequence 2: {seq2[:5]}")
    print(f"Match: {seq1 == seq2}")
    
    # Different seed should produce different sequence
    chaos3 = ChaosMap(54321)
    seq3 = [chaos3.next() for _ in range(10)]
    print(f"\nDifferent seed sequence: {seq3[:5]}")
    print(f"Different: {seq1 != seq3}")


def test_carrier_selection():
    """Test carrier selection"""
    print("\n\nTesting Carrier Selection")
    print("=" * 50)
    
    # Create fake MV data
    np.random.seed(42)
    mv_data = []
    
    for frame_idx in range(10):
        for mb_idx in range(50):
            mv_data.append({
                'frame_idx': frame_idx,
                'frame_type': 'P',
                'mb_x': mb_idx % 10,
                'mb_y': mb_idx // 10,
                'mvx': np.random.randint(-10, 10),
                'mvy': np.random.randint(-10, 10),
            })
    
    print(f"Total MVs: {len(mv_data)}")
    
    # Select carriers
    selector = CarrierSelector(seed=12345, embedding_rate=0.2)
    carriers = selector.select_carriers(mv_data, required_bits=100)
    
    print(f"Selected: {len(carriers)} carriers")
    print(f"\nFirst 5 carriers:")
    for i, c in enumerate(carriers[:5]):
        print(f"  {i}: Frame {c.frame_idx}, MB({c.mb_x},{c.mb_y}), "
              f"MV({c.mvx},{c.mvy}), mag={c.magnitude:.2f}")
    
    # Test determinism: same seed → same selection
    selector2 = CarrierSelector(seed=12345, embedding_rate=0.2)
    carriers2 = selector2.select_carriers(mv_data, required_bits=100)
    
    match = all(c1.mv_index == c2.mv_index for c1, c2 in zip(carriers, carriers2))
    print(f"\nDeterminism test: {match}")


if __name__ == '__main__':
    test_chaos_map()
    test_carrier_selection()
