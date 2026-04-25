"""
chaos.py — Chaos Math transforms for secure steganography.

Implements two layers of cryptographic obfuscation:

1. Arnold Cat Map (payload scrambling):
   - Transforms payload bits into an M×M matrix and applies K iterations
     of the Arnold Cat Map (K derived from secret_key).
   - Produces a bit-level permutation that is visually indistinguishable
     from white noise, resisting chi-square and RS steganalysis.

2. Logistic Map (position shuffling):
   - Generates a pseudo-random sequence via x_{n+1} = r * x_n * (1 - x_n)
     with seed derived from secret_key.
   - Sorts safe embedding positions by this sequence, distributing them
     non-linearly across the frame — no adjacent-block clustering.

Both transforms are deterministic and key-bound: only the holder of
secret_key can recover the correct permutation for embedding/extraction.

Public API:
    ChaosTransformer(secret_key)
        .scramble(blob)                         → (scrambled_bytes, original_bit_count)
        .unscramble(scrambled_blob, orig_bits)  → bytes
        .shuffle_positions(positions)           → list
        .padded_bit_count(original_bit_count)   → int  (static helper)
"""

import hashlib
import math
from typing import List, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Internal bit ↔ bytes helpers
# ---------------------------------------------------------------------------

def _bytes_to_bits(data: bytes) -> List[int]:
    bits = []
    for byte in data:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    return bits


def _bits_to_bytes(bits: List[int]) -> bytes:
    # Pad to byte boundary with zeros
    pad = (-len(bits)) % 8
    padded = bits + [0] * pad
    result = bytearray()
    for i in range(0, len(padded), 8):
        val = 0
        for b in padded[i:i + 8]:
            val = (val << 1) | b
        result.append(val)
    return bytes(result)


# ---------------------------------------------------------------------------
# ChaosTransformer
# ---------------------------------------------------------------------------

class ChaosTransformer:
    """
    Key-based chaos transformer for steganographic payload security.

    Derives two independent sub-keys from secret_key via SHA-256:
      - arnold_k   : number of Arnold Cat Map iterations  (range [5, 100])
      - logistic_seed: initial value for the Logistic Map  (range (0.1, 0.9))

    Usage:
        ct = ChaosTransformer(secret_key)

        # Embedding side
        scrambled_bytes, orig_bits = ct.scramble(payload_blob)
        shuffled_positions = ct.shuffle_positions(safe_positions)

        # Extraction side (mirror)
        shuffled_positions = ct.shuffle_positions(safe_positions)
        payload_blob = ct.unscramble(extracted_bytes, orig_bits)
    """

    _LOGISTIC_R = 3.9999  # Chaotic regime (r > 3.57)

    def __init__(self, secret_key: bytes) -> None:
        if not isinstance(secret_key, bytes) or len(secret_key) == 0:
            raise ValueError("secret_key must be a non-empty bytes object")
        h = hashlib.sha256(b"chaos:" + secret_key).digest()
        # Arnold iteration count: [5, 100]
        self.arnold_k: int = (int.from_bytes(h[:4], "big") % 96) + 5
        # Logistic seed: strictly in (0.1, 0.9) for robust chaotic behavior
        seed_raw = int.from_bytes(h[4:8], "big") / (2 ** 32)  # [0, 1)
        self.logistic_seed: float = 0.1 + seed_raw * 0.8

    # ------------------------------------------------------------------
    # Arnold Cat Map
    # ------------------------------------------------------------------

    @staticmethod
    def _next_square(n: int) -> int:
        """Return smallest M ≥ 1 such that M² ≥ n."""
        if n <= 0:
            return 1
        m = math.isqrt(n)
        return m if m * m >= n else m + 1

    @staticmethod
    def _arnold_fwd_indices(M: int) -> Tuple[np.ndarray, np.ndarray]:
        """
        Precompute gather indices for ONE forward Arnold Cat Map step.

        Forward map:  (x, y) → (x', y') = ((2x+y) % M, (x+y) % M)
        Gather rule:  new[y', x'] = old[y_src, x_src]
                      where (y_src, x_src) = A^{-1}(y', x')
                      x_src = (x' − y') % M
                      y_src = (−x' + 2y') % M
        """
        y, x = np.meshgrid(np.arange(M, dtype=np.int64),
                           np.arange(M, dtype=np.int64), indexing="ij")
        x_src = (x - y) % M
        y_src = (-x + 2 * y) % M
        return y_src, x_src

    @staticmethod
    def _arnold_inv_indices(M: int) -> Tuple[np.ndarray, np.ndarray]:
        """
        Precompute gather indices for ONE INVERSE Arnold Cat Map step.

        Inverse map:  (x, y) → (x', y') = ((x−y) % M, (−x+2y) % M)
        Gather rule:  new[y', x'] = old[y_src, x_src]
                      where (y_src, x_src) = A(y', x')
                      x_src = (2x' + y') % M
                      y_src = (x' + y') % M
        """
        y, x = np.meshgrid(np.arange(M, dtype=np.int64),
                           np.arange(M, dtype=np.int64), indexing="ij")
        x_src = (2 * x + y) % M
        y_src = (x + y) % M
        return y_src, x_src

    def scramble(self, blob: bytes) -> Tuple[bytes, int]:
        """
        Scramble a byte string using Arnold Cat Map on its bits.

        The bits are padded to an M×M matrix (M = ⌈√L⌉), shuffled
        by arnold_k iterations of the Arnold map, then serialized back
        to bytes (with ≤7 zero bits of byte-alignment padding appended).

        Returns:
            (scrambled_bytes, original_bit_count)
            Pass original_bit_count to unscramble() for exact recovery.
        """
        bits = _bytes_to_bits(blob)
        L = len(bits)
        M = self._next_square(L)
        pad = M * M - L
        padded = bits + [0] * pad

        mat = np.array(padded, dtype=np.uint8).reshape(M, M)
        y_src, x_src = self._arnold_fwd_indices(M)
        for _ in range(self.arnold_k):
            mat = mat[y_src, x_src]

        scrambled_bits = mat.flatten().tolist()
        return _bits_to_bytes(scrambled_bits), L

    def unscramble(self, scrambled_blob: bytes, original_bit_count: int) -> bytes:
        """
        Recover original bytes by inverting the Arnold Cat Map scrambling.

        Args:
            scrambled_blob:      Output of scramble() (may have ≤7 extra
                                 byte-alignment bits that are silently ignored).
            original_bit_count:  The second value returned by scramble().

        Returns:
            Original bytes (same as the blob passed to scramble()).
        """
        L = original_bit_count
        M = self._next_square(L)
        padded_len = M * M

        bits = _bytes_to_bits(scrambled_blob)[:padded_len]
        if len(bits) < padded_len:
            bits += [0] * (padded_len - len(bits))

        mat = np.array(bits, dtype=np.uint8).reshape(M, M)
        y_src, x_src = self._arnold_inv_indices(M)
        for _ in range(self.arnold_k):
            mat = mat[y_src, x_src]

        result_bits = mat.flatten().tolist()[:L]
        return _bits_to_bytes(result_bits)

    # ------------------------------------------------------------------
    # Logistic Map position shuffling
    # ------------------------------------------------------------------

    def shuffle_positions(self, positions: list, cif_mb_count: int = 396,
                          cif_mb_width: int = 22, bottom_row_start: int = 14) -> list:
        """
        Shuffle embedding positions using the Logistic Map with temporal fairness.

        Within each IDR frame positions are sorted by (bottom-4-rows-first,
        chaotic_logistic_key).  Frames are then round-robin interleaved so that
        every frame contributes equally to the first N positions taken by the
        embedder — preventing any single frame from absorbing a disproportionate
        share of modifications.
        """
        n = len(positions)
        if n == 0:
            return []

        # Generate one logistic key per position
        x = self.logistic_seed
        r = self._LOGISTIC_R
        keys: List[float] = []
        for _ in range(n):
            x = r * x * (1 - x)
            keys.append(x)

        # Group by IDR frame index
        by_frame: dict = {}
        for i, pos in enumerate(positions):
            frame_idx = pos[0] // cif_mb_count
            if frame_idx not in by_frame:
                by_frame[frame_idx] = []
            by_frame[frame_idx].append((i, pos))

        # Within each frame: bottom 4 rows first, then chaos key for spatial distribution.
        # Chaos key randomizes within the bottom zone so consecutive frames don't cluster
        # modifications in the same columns (which would compound intra-prediction cascade).
        def _frame_key(item):
            i, pos = item
            local_mb = pos[0] % cif_mb_count
            row = local_mb // cif_mb_width
            is_upper = 0 if row >= bottom_row_start else 1  # 0 = priority rows
            return (is_upper, keys[i])

        frames_asc = sorted(by_frame.keys())
        for frm in frames_asc:
            by_frame[frm].sort(key=_frame_key)

        # Round-robin interleave across frames (equal distribution)
        result = []
        max_len = max(len(lst) for lst in by_frame.values())
        for k in range(max_len):
            for frm in frames_asc:
                if k < len(by_frame[frm]):
                    result.append(by_frame[frm][k][1])

        return result

    # ------------------------------------------------------------------
    # Static helper
    # ------------------------------------------------------------------

    @staticmethod
    def padded_bit_count(original_bit_count: int) -> int:
        """
        Return the number of bits that will be embedded when chaos is
        enabled for a payload of `original_bit_count` bits.

        This equals M² where M = ⌈√original_bit_count⌉.
        Use this to compute how many bits the extractor must read.
        """
        M = ChaosTransformer._next_square(original_bit_count)
        return M * M
