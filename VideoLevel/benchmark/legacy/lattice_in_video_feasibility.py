"""Compare a serialized proof artifact with measured H.264 carrier capacity.

This is a size gate only: it does not validate that an artifact is a ZKP,
secure, or bound to the video. Capacity must come from the exact asset and
embedding policy being evaluated, not a stale project-wide maximum.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class CapacityAssessment:
    proof_bytes: int
    framing_bytes: int
    capacity_bits: int
    required_bits: int
    remaining_bits: int
    shortfall_bits: int
    required_to_capacity_ratio: float | None
    fits: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _measurement(name: str, value: int, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def assess_capacity(
    *, proof_bytes: int, capacity_bits: int, framing_bytes: int = 0
) -> CapacityAssessment:
    """Return whether proof plus framing fits a measured bit-level capacity."""
    proof_bytes = _measurement("proof_bytes", proof_bytes, minimum=1)
    capacity_bits = _measurement("capacity_bits", capacity_bits, minimum=0)
    framing_bytes = _measurement("framing_bytes", framing_bytes, minimum=0)

    required_bits = (proof_bytes + framing_bytes) * 8
    fits = required_bits <= capacity_bits
    return CapacityAssessment(
        proof_bytes=proof_bytes,
        framing_bytes=framing_bytes,
        capacity_bits=capacity_bits,
        required_bits=required_bits,
        remaining_bits=max(0, capacity_bits - required_bits),
        shortfall_bits=max(0, required_bits - capacity_bits),
        required_to_capacity_ratio=(
            round(required_bits / capacity_bits, 6) if capacity_bits else None
        ),
        fits=fits,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check whether an exact serialized proof artifact plus framing fits "
            "a measured H.264 carrier capacity. This does not verify the proof."
        )
    )
    parser.add_argument("--proof-artifact", required=True, type=Path)
    parser.add_argument(
        "--capacity-bits",
        required=True,
        type=int,
        help="quality-validated carrier capacity for this exact video/configuration",
    )
    parser.add_argument("--framing-bytes", type=int, default=0)
    args = parser.parse_args(argv)

    try:
        proof_bytes = len(args.proof_artifact.read_bytes())
        result = assess_capacity(
            proof_bytes=proof_bytes,
            capacity_bits=args.capacity_bits,
            framing_bytes=args.framing_bytes,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))

    print(json.dumps(result.to_dict(), sort_keys=True, indent=2))
    return 0 if result.fits else 3


if __name__ == "__main__":
    raise SystemExit(main())
