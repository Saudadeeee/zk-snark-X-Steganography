"""
locked_operating_contract.py - Centralized helper for the current strongest operating contract.

This module defines the best currently-supported benchmark-grade operating
contract: locked SEC1 operating positions on a selected all-intra asset.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ._common import OUTPUT_DIR, SEQUENCES, load_sec1_meta, load_sec1_positions


LOCKED_SECRET_KEY = bytes(range(32))
LOCKED_CHAOS_KEY = b"sec1_benchmark_chaos_v1"
LOCKED_MESSAGE = b"ZK-bench-v1.0!"

DEFAULT_PREFERRED_SEQUENCES = [
    "akiyo_q22_g1",
    "coastguard_q22_g1",
    "deadline_q22_g1",
    "coastguard_q22_g1_1000f",
    "coastguard_q22_g1_3000f",
    "foreman_q22_g1",
]


@dataclass
class LockedOperatingContract:
    sequence_name: str
    video_path: str
    stego_path: str
    positions: list[tuple[int, int, int]]
    bits_required: int
    bits_embedded: int | None
    validation_mode: str | None
    secret_key: bytes = LOCKED_SECRET_KEY
    chaos_key: bytes = LOCKED_CHAOS_KEY
    message: bytes = LOCKED_MESSAGE


def load_best_locked_operating_contract(
    *,
    required_bits: int = 1232,
    preferred_sequences: list[str] | None = None,
) -> LockedOperatingContract | None:
    seqs = preferred_sequences or DEFAULT_PREFERRED_SEQUENCES
    for seq_name in seqs:
        video_path = SEQUENCES.get(seq_name)
        if video_path is None:
            continue
        stego_path = OUTPUT_DIR / f"sec1_stego_{seq_name}.h264"
        positions = load_sec1_positions(seq_name, validated_pool=False)
        meta = load_sec1_meta(seq_name) or {}
        if meta.get("verify_valid") is not True or meta.get("verify_message_match") is not True:
            continue
        bits_required_now = int(meta.get("bits_required") or len(positions))
        if not positions or not stego_path.exists():
            continue
        if bits_required_now < required_bits:
            continue
        return LockedOperatingContract(
            sequence_name=seq_name,
            video_path=str(video_path),
            stego_path=str(stego_path),
            positions=positions,
            bits_required=bits_required_now,
            bits_embedded=int(meta.get("bits_embedded")) if meta.get("bits_embedded") is not None else None,
            validation_mode=str(meta.get("validation_mode")) if meta.get("validation_mode") is not None else None,
        )
    return None
