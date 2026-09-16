"""Low-distortion binary matrix embedding over pre-validated carriers.

This module intentionally does *not* decide whether an H.264 coefficient is
safe to patch.  ``CAVLCSafetyFilter`` remains the single authority for that.
It applies the (7,3) Hamming syndrome code only after the caller has supplied
such safe carriers.  Seven carrier bits convey three payload bits and require
at most one carrier flip per group, rather than the expected 3.5 flips for
direct replacement.

It is a conservative stepping stone toward syndrome-trellis coding, not a
claim to be a general STC implementation.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Sequence


MATRIX_EMBEDDING_STRATEGY = "cost_guided_hamming_7_3"
"""Authenticated manifest label for the controlled low-distortion mode."""

HammingPosition = tuple[int, int, int]
_CIF_MB_COUNT = 396


def matrix_carrier_bit_count(payload_bit_count: int) -> int:
    """Return the number of carriers needed to convey ``payload_bit_count``."""
    if payload_bit_count < 0:
        raise ValueError("payload_bit_count must be non-negative")
    return ((payload_bit_count + 2) // 3) * 7


def matrix_payload_capacity_bits(carrier_bit_count: int) -> int:
    """Return payload capacity of a carrier sequence, ignoring incomplete groups."""
    if carrier_bit_count < 0:
        raise ValueError("carrier_bit_count must be non-negative")
    return (carrier_bit_count // 7) * 3


def _bits_to_int(bits: Sequence[int]) -> int:
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def _int_to_bits(value: int, width: int) -> list[int]:
    return [(value >> shift) & 1 for shift in range(width - 1, -1, -1)]


def bytes_to_bits(data: bytes, bit_count: int) -> list[int]:
    """Decode exactly ``bit_count`` big-endian bits from a byte sequence."""
    if bit_count < 0 or len(data) * 8 < bit_count:
        raise ValueError("byte sequence is shorter than requested bit count")
    return [
        (data[index // 8] >> (7 - (index % 8))) & 1
        for index in range(bit_count)
    ]


def bits_to_bytes(bits: Sequence[int]) -> bytes:
    """Encode big-endian bits, padding only the final partial byte with zeros."""
    if any(bit not in (0, 1) for bit in bits):
        raise ValueError("bits must be 0 or 1")
    padded = list(bits) + [0] * ((8 - len(bits) % 8) % 8)
    return bytes(
        sum(padded[offset + shift] << (7 - shift) for shift in range(8))
        for offset in range(0, len(padded), 8)
    )


def hamming73_syndrome(carriers: Sequence[int]) -> int:
    """Return the three-bit Hamming syndrome of exactly seven carrier bits."""
    if len(carriers) != 7:
        raise ValueError("Hamming (7,3) requires exactly seven carriers")
    syndrome = 0
    for index, bit in enumerate(carriers, start=1):
        if bit not in (0, 1):
            raise ValueError("carrier bits must be 0 or 1")
        if bit:
            syndrome ^= index
    return syndrome


def embed_hamming73(
    cover_carriers: Sequence[int], payload_bits: Sequence[int]
) -> tuple[list[int], int, list[int]]:
    """Embed payload bits, returning (stego carriers, embedded bits, flips).

    ``flips`` contains zero-based carrier indexes.  It contains no more than
    one index per seven-carrier group.  An incomplete final payload triplet is
    zero-padded internally and must be truncated by the decoder using the
    authenticated payload bit count.
    """
    if any(bit not in (0, 1) for bit in cover_carriers):
        raise ValueError("cover carriers must be 0 or 1")
    if any(bit not in (0, 1) for bit in payload_bits):
        raise ValueError("payload bits must be 0 or 1")

    group_count = min((len(payload_bits) + 2) // 3, len(cover_carriers) // 7)
    embedded_bits = min(len(payload_bits), group_count * 3)
    used_carriers = group_count * 7
    stego = list(cover_carriers[:used_carriers])
    flips: list[int] = []

    for group_index in range(group_count):
        payload_offset = group_index * 3
        target_triplet = list(payload_bits[payload_offset:payload_offset + 3])
        target_triplet += [0] * (3 - len(target_triplet))
        target = _bits_to_int(target_triplet)
        carrier_offset = group_index * 7
        current = hamming73_syndrome(stego[carrier_offset:carrier_offset + 7])
        delta = current ^ target
        if delta:
            flip_index = carrier_offset + delta - 1
            stego[flip_index] ^= 1
            flips.append(flip_index)

    return stego, embedded_bits, flips


def extract_hamming73(stego_carriers: Sequence[int], payload_bit_count: int) -> list[int]:
    """Recover exactly ``payload_bit_count`` bits from syndrome-coded carriers."""
    required_carriers = matrix_carrier_bit_count(payload_bit_count)
    if len(stego_carriers) < required_carriers:
        raise ValueError("insufficient matrix carriers for requested payload")
    result: list[int] = []
    for offset in range(0, required_carriers, 7):
        result.extend(_int_to_bits(hamming73_syndrome(stego_carriers[offset:offset + 7]), 3))
    return result[:payload_bit_count]


def _position_cost(position: HammingPosition, coefficients: dict[tuple[int, int], list[int]]) -> float:
    """Deterministic perceptual proxy used only after syntax safety is proven.

    Lower cost favors high-frequency, larger-magnitude residual coefficients.
    T1 sign carriers are retained but made relatively expensive because changing
    +1 to -1 changes the reconstructed residual by two units.
    """
    mb, block, encoded_index = position
    coeff_index = encoded_index if encoded_index >= 0 else ~encoded_index
    coeffs = coefficients.get((mb, block), [])
    magnitude = abs(coeffs[coeff_index]) if 0 <= coeff_index < len(coeffs) else 1
    frequency_cost = max(0, 15 - coeff_index) * 0.5
    magnitude_cost = 1.0 / max(magnitude, 1)
    sign_cost = 1.5 if encoded_index < 0 else 0.0
    return 1.0 + frequency_cost + magnitude_cost + sign_cost


def rank_positions_cost_guided(
    positions: Iterable[HammingPosition],
    coefficient_blocks: Iterable[tuple[int, int, list[int]]],
    cif_mb_count: int = _CIF_MB_COUNT,
) -> list[HammingPosition]:
    """Rank safe positions by cost while preserving strict IDR-frame fairness.

    Each frame is cost-sorted independently; one candidate from every frame is
    emitted in turn.  Therefore a textured frame cannot consume the entire
    payload merely because it offers more low-cost candidates.
    """
    if cif_mb_count <= 0:
        raise ValueError("cif_mb_count must be positive")
    coeff_map = {(int(mb), int(block)): list(values) for mb, block, values in coefficient_blocks}
    by_frame: dict[int, list[tuple[float, int, HammingPosition]]] = defaultdict(list)
    for sequence, raw_position in enumerate(positions):
        position = tuple(int(value) for value in raw_position)
        if len(position) != 3:
            raise ValueError("each carrier position must contain three integers")
        by_frame[position[0] // cif_mb_count].append((_position_cost(position, coeff_map), sequence, position))

    for frame_positions in by_frame.values():
        frame_positions.sort(key=lambda item: (item[0], item[1]))

    ordered_frames = sorted(by_frame)
    result: list[HammingPosition] = []
    offsets = {frame: 0 for frame in ordered_frames}
    while True:
        progressed = False
        for frame in ordered_frames:
            offset = offsets[frame]
            frame_positions = by_frame[frame]
            if offset < len(frame_positions):
                result.append(frame_positions[offset][2])
                offsets[frame] += 1
                progressed = True
        if not progressed:
            return result
