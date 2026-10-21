"""Resolution-aware carrier ordering derived from the SPS picture geometry.

The original ordering (``ChaosTransformer.shuffle_positions`` and
``sort_blocks_interleaved``) assumes a CIF picture of 22 x 18 macroblocks: it
groups carriers into "frames" of 396 macroblocks and prefers rows 14-17 of a
22-macroblock-wide grid.  At 4CIF (44 x 36), 720p (80 x 45) or 1080p
(120 x 68) those groups are quarter pictures or straddle picture boundaries,
and the preferred "bottom rows" are stripes in the middle of the picture.
Correctness is unaffected (embedder and extractor compute the same order),
but intra-prediction drift is not: a changed block propagates into every
later block of its slice that predicts from it, so changes high in a slice
cost more than changes near its end.  That ordering stays as it is for the
existing contracts, whose carrier profile ids, positions and stego bytes are
pinned.

``SPS_GEOMETRY_ORDER_V1`` is the same heuristic computed on the real
geometry, selected only by contracts that name it (a new contract version,
hence a new carrier profile id):

1. candidates are put in canonical ``(mb, block, coefficient)`` order, so the
   result does not depend on how an analysis listed them;
2. they are grouped by coordinate slot ``mb // (W x H)``: one slot per coded
   slice (for one slice per picture, one per picture);
3. within a slot, carriers in the last ``priority_rows(rows)`` macroblock rows
   of the slot's carrier extent (``rows`` from its first to its last carrier
   row; 4 of 18 rows at CIF, 8 at 4CIF, 10 at 720p, 15 at 1080p, the slice
   height for multi-slice pictures) come first, every group in keyed
   pseudo-random order (SHA-256 of the ordering key and the position);
4. slots are interleaved round-robin in ascending order, so every picture
   (slice) contributes equally to any prefix.

The order is a function of the candidate set, the SPS and the key only.  The
candidate set of a stego video equals the cover's (stable carriers), so the
extractor recomputes the identical order.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from typing import Any, Iterable

SPS_GEOMETRY_ORDER_V1 = "sps-geometry-low-drift-v1"
CARRIER_ORDERS = (SPS_GEOMETRY_ORDER_V1,)
_KEY_DOMAIN = b"zkstego/carrier-order/sps-geometry-low-drift-v1\0"
# CIF heuristic: the last 4 of 18 macroblock rows (22 % of the picture).
_PRIORITY_NUMERATOR, _PRIORITY_DENOMINATOR = 2, 9


@dataclass(frozen=True)
class PictureGeometry:
    """Picture size in macroblocks (progressive Baseline: map units = MBs)."""

    width_mbs: int
    height_mbs: int

    def __post_init__(self) -> None:
        for name in ("width_mbs", "height_mbs"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")

    @property
    def mbs_per_picture(self) -> int:
        return self.width_mbs * self.height_mbs


CIF_GEOMETRY = PictureGeometry(22, 18)


def geometry_from_sps(sps: Any) -> PictureGeometry:
    """Macroblock geometry of a parsed SPS; interlaced streams are refused."""
    if sps is None:
        raise ValueError("no sequence parameter set; picture geometry is unknown")
    if not getattr(sps, "frame_mbs_only_flag", True):
        raise ValueError("interlaced H.264 (frame_mbs_only_flag=0) is not supported")
    return PictureGeometry(
        int(sps.pic_width_in_mbs_minus1) + 1, int(sps.pic_height_in_map_units_minus1) + 1
    )


def require_carrier_order(order: str) -> str:
    if order not in CARRIER_ORDERS:
        raise ValueError(f"unknown carrier order {order!r}; expected one of {CARRIER_ORDERS}")
    return order


def contract_carrier_order(contract: Any) -> str | None:
    """The contract's geometry-aware order, or ``None`` for the original CIF order."""
    order = getattr(contract, "carrier_order", None)
    return None if order is None else require_carrier_order(order)


def priority_rows(slot_rows: int) -> int:
    """Rows of a slot's low-drift zone: 2/9 of its rows rounded, at least one."""
    if slot_rows < 1:
        raise ValueError("a slot spans at least one row")
    return max(1, (_PRIORITY_NUMERATOR * slot_rows + _PRIORITY_DENOMINATOR // 2)
               // _PRIORITY_DENOMINATOR)


def _key_prefix(ordering_secret: bytes) -> bytes:
    if not isinstance(ordering_secret, bytes) or not ordering_secret:
        raise ValueError("ordering secret must be non-empty bytes")
    return _KEY_DOMAIN + struct.pack(">I", len(ordering_secret)) + ordering_secret


def _position_key(prefix: bytes, position: tuple[int, int, int]) -> bytes:
    return hashlib.sha256(prefix + struct.pack(">qqq", *position)).digest()


def order_carriers(
    positions: Iterable[tuple[int, int, int]],
    geometry: PictureGeometry,
    ordering_secret: bytes,
) -> list[tuple[int, int, int]]:
    """Keyed, geometry-aware carrier order (``SPS_GEOMETRY_ORDER_V1``)."""
    canonical = sorted((int(mb), int(block), int(index)) for mb, block, index in positions)
    if not canonical:
        return []
    prefix = _key_prefix(ordering_secret)
    per_picture, width = geometry.mbs_per_picture, geometry.width_mbs
    slots: dict[int, list[tuple[int, int, int]]] = {}
    for position in canonical:
        slots.setdefault(position[0] // per_picture, []).append(position)
    ordered_slots = []
    for slot in sorted(slots):
        members = slots[slot]
        rows = [(position[0] % per_picture) // width for position in members]
        first, last = min(rows), max(rows)
        zone_start = last - priority_rows(last - first + 1) + 1
        ranked = sorted(
            zip(rows, members),
            key=lambda item: (item[0] < zone_start, _position_key(prefix, item[1])),
        )
        ordered_slots.append([position for _row, position in ranked])
    result: list[tuple[int, int, int]] = []
    for rank in range(max(len(members) for members in ordered_slots)):
        for members in ordered_slots:
            if rank < len(members):
                result.append(members[rank])
    return result
