"""Gates every carrier passes around a bitstream patch.

Shared by the blind transport (``src.transport``) and the legacy one-shot
embedder (``src.legacy.embedder``); moved here unchanged so the current
system does not import the legacy package:

* :func:`prune_patchable_positions` keeps only carriers whose 4x4 block the
  CAVLC patcher can rewrite in place;
* :func:`strict_validate_h264_decode` fails unless FFmpeg decodes the whole
  patched stream without an H.264 error;
* :func:`hash_positions` is the canonical SHA-256 of the applied positions
  (identical bytes to the former ``src.manifest.hash_positions``,
  which ``src.legacy.manifest`` still re-exports).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from bisect import bisect_right
from typing import Any, Sequence

from ..bitstream.bitstream_ops import BitstreamPatcher
from ..exceptions import UnsupportedStreamError


def canonical_json_bytes(data: dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def hash_positions(positions: Sequence[Sequence[int]]) -> str:
    """Hash normalized embedding positions so their sidecar is authenticated."""
    normalized: list[list[int]] = []
    for position in positions:
        if len(position) != 3:
            raise ValueError("each embedding position must contain exactly three integers")
        if any(not isinstance(value, int) or isinstance(value, bool) for value in position):
            raise ValueError("each embedding position must contain exactly three integers")
        normalized.append(list(position))
    return hashlib.sha256(canonical_json_bytes({"positions": normalized})).hexdigest()


def strict_validate_h264_decode(video_path: str) -> None:
    """Fail unless FFmpeg decodes the complete video without H.264 errors."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg is required to validate reconstructed H.264 output")

    result = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-v", "error",
            "-xerror",
            "-err_detect", "explode",
            "-i", video_path,
            "-map", "0:v:0",
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or result.stderr.strip():
        raise UnsupportedStreamError(
            "Reconstructed stego video failed strict H.264 decode",
            decode_exit_code=result.returncode,
            decoder_diagnostics=result.stderr[-2000:],
        )


def prune_patchable_positions(
    safe_positions: list[tuple[int, int, int]],
    frame_verified_data: dict,
    required_bits: int,
    max_modifications_per_block: int = 1,
) -> list[tuple[int, int, int]]:
    """
    Keep only positions whose blocks are bitstream-patchable.

    This validates candidate blocks lazily and stops once enough positions
    have been retained for the payload.
    """
    patcher = BitstreamPatcher()
    idr_offsets = sorted(frame_verified_data)
    retained: list[tuple[int, int, int]] = []
    idr_context: dict[int, tuple[dict, dict, bytes]] = {}

    for idr_off, (g_off, _g_blk, nal_rbsp) in frame_verified_data.items():
        local_offsets = {
            (gmb - idr_off, gblk): od
            for (gmb, gblk), od in g_off.items()
            if gblk < 16 and od.get("bit_length") not in (None, 0)
        }
        end_to_block = {
            od["end_bit"]: ((gmb - idr_off, gblk), od)
            for (gmb, gblk), od in g_off.items()
            if gblk < 16 and "end_bit" in od
        }
        idr_context[idr_off] = (local_offsets, end_to_block, nal_rbsp)

    def block_is_patchable(mb: int, blk: int) -> bool:
        idr_index = bisect_right(idr_offsets, mb) - 1
        if idr_index < 0:
            return False
        idr_off = idr_offsets[idr_index]
        local_offsets, end_to_block, nal_rbsp = idr_context.get(idr_off, ({}, {}, b""))
        local_key = (mb - idr_off, blk)
        match = patcher.validate_block_patchability(
            nal_rbsp,
            local_key,
            local_offsets.get(local_key, {}),
            end_to_block,
        )
        if match is None:
            return False
        # Validation may recover the only nC that reproduces the source codeword
        # even when the trace parser's provisional neighbor estimate is wrong.
        # The reconstruction patcher intentionally trusts this stored nC and
        # does not scan alternatives, so propagate the validated value into the
        # shared frame offset record before the carrier is accepted.
        validated_offset = local_offsets.get(local_key)
        if validated_offset is not None:
            validated_offset["nC"] = match[0]
            validated_offset["validated_nC"] = match[0]
        return True

    if max_modifications_per_block == 1:
        seen_blocks: set[tuple[int, int]] = set()
        for pos in safe_positions:
            normalized = (int(pos[0]), int(pos[1]), int(pos[2]))
            key = normalized[:2]
            if key in seen_blocks:
                continue
            seen_blocks.add(key)
            if not block_is_patchable(*key):
                continue
            retained.append(normalized)
            if len(retained) >= required_bits:
                break
        return retained

    block_order: list[tuple[int, int]] = []
    block_to_positions: dict[tuple[int, int], list[tuple[int, int, int]]] = {}
    for pos in safe_positions:
        normalized = (int(pos[0]), int(pos[1]), int(pos[2]))
        key = normalized[:2]
        positions = block_to_positions.get(key)
        if positions is None:
            positions = []
            block_to_positions[key] = positions
            block_order.append(key)
        if len(positions) < max_modifications_per_block:
            positions.append(normalized)

    for mb, blk in block_order:
        if not block_is_patchable(mb, blk):
            continue
        for pos in block_to_positions[(mb, blk)]:
            retained.append(pos)
            if len(retained) >= required_bits:
                break
        if len(retained) >= required_bits:
            break

    return retained
