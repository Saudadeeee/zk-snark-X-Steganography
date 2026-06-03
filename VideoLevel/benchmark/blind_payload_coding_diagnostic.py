"""
blind_payload_coding_diagnostic.py - Compare stronger blind payload coding schemes.

This benchmark stays below full proof-verification scope. It asks a narrower
question: given the current blind candidate universe, which lightweight coding
scheme gets closest to a usable payload prefix?
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark._common import RESULTS_DIR, SEQUENCES, cache_load, cache_save, load_or_build_benchmark_analysis
from src.blind_sync import derive_blind_body_positions, derive_blind_header_positions
from src.bitstream.bitstream_ops import BitstreamReconstructor
from src.core.pipeline import extract_bits_direct
from src.core.stego import PayloadEmbedder

CACHE_KEY = "blind_payload_coding_diagnostic"
SECRET_KEY = b"zk_mv_stego_2026_secret_key!!!!!"
MESSAGE = b"Hello ZK-Stego"
HEADER_BITS = 32
HEADER_REDUNDANCY = 4
BODY_SCHEMES = ("repeat4", "repeat8", "repeat4_interleaved")


def _bits_to_bytes(bits: list[int]) -> bytes:
    padded = list(bits)
    while len(padded) % 8:
        padded.append(0)
    out = bytearray()
    for i in range(0, len(padded), 8):
        byte = 0
        for bit in padded[i:i + 8]:
            byte = (byte << 1) | int(bit)
        out.append(byte)
    return bytes(out)


def _bytes_to_bits(data: bytes) -> list[int]:
    bits: list[int] = []
    for byte in data:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    return bits


def _majority_vote(bits: list[int], redundancy: int) -> list[int]:
    out: list[int] = []
    for i in range(0, len(bits), redundancy):
        chunk = bits[i:i + redundancy]
        out.append(1 if sum(chunk) > len(chunk) / 2 else 0)
    return out


def _repeat_bits(bits: list[int], redundancy: int) -> list[int]:
    repeated: list[int] = []
    for bit in bits:
        repeated.extend([bit] * redundancy)
    return repeated


def _interleave_groups(groups: list[list[int]]) -> list[int]:
    if not groups:
        return []
    width = len(groups[0])
    out: list[int] = []
    for col in range(width):
        for group in groups:
            out.append(group[col])
    return out


def _deinterleave_groups(bits: list[int], width: int, group_count: int) -> list[list[int]]:
    groups = [[0] * width for _ in range(group_count)]
    cursor = 0
    for col in range(width):
        for row in range(group_count):
            if cursor >= len(bits):
                break
            groups[row][col] = bits[cursor]
            cursor += 1
    return groups


def _encode_body(bits: list[int], scheme: str) -> tuple[list[int], dict]:
    if scheme == "repeat4":
        return _repeat_bits(bits, 4), {"kind": "repeat", "redundancy": 4}
    if scheme == "repeat8":
        return _repeat_bits(bits, 8), {"kind": "repeat", "redundancy": 8}
    if scheme == "repeat4_interleaved":
        groups = [[bit] * 4 for bit in bits]
        return _interleave_groups(groups), {"kind": "repeat_interleaved", "redundancy": 4, "group_width": 4}
    raise ValueError(f"Unknown body scheme: {scheme}")


def _decode_body(bits: list[int], body_bit_count: int, decode_meta: dict) -> list[int]:
    kind = decode_meta["kind"]
    redundancy = int(decode_meta["redundancy"])
    if kind == "repeat":
        return _majority_vote(bits[: body_bit_count * redundancy], redundancy)[:body_bit_count]
    if kind == "repeat_interleaved":
        width = int(decode_meta["group_width"])
        groups = _deinterleave_groups(bits[: body_bit_count * width], width, body_bit_count)
        return [1 if sum(group) > len(group) / 2 else 0 for group in groups]
    raise ValueError(f"Unknown decode kind: {kind}")


def _fast_mode_enabled() -> bool:
    return os.environ.get("BLIND_PAYLOAD_FAST", "0") == "1" or "--fast" in sys.argv


def _selected_body_bits() -> int:
    override = os.environ.get("BLIND_PAYLOAD_BODY_BITS")
    if override:
        try:
            value = int(override)
            if value > 0:
                return value
        except ValueError:
            pass
    return 64 if _fast_mode_enabled() else 128


def _selected_body_schemes() -> tuple[str, ...]:
    override = os.environ.get("BLIND_PAYLOAD_SCHEMES")
    if override:
        requested = tuple(part.strip() for part in override.split(",") if part.strip())
        if requested:
            return requested
    if _fast_mode_enabled():
        return ("repeat4", "repeat8")
    return BODY_SCHEMES


def collect_data(force: bool = False) -> dict:
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        rows = cached.get("rows") if isinstance(cached, dict) else None
        if isinstance(rows, list) and all(isinstance(row, dict) and "scheme" in row for row in rows):
            print("  [cache hit] blind payload coding diagnostic")
            return cached
        print("  [cache stale] blind payload coding diagnostic")
    if cached and not force:
        pass

    seq_name = "coastguard_q22_g1"
    video_path = str(SEQUENCES[seq_name])

    synthetic_proof_prefix = bytes([i % 256 for i in range(32)])
    blob = len(MESSAGE).to_bytes(4, "big") + MESSAGE + synthetic_proof_prefix
    blob_bits = _bytes_to_bits(blob)
    header_source_bits = blob_bits[:HEADER_BITS]
    available_body_bits = max(0, len(blob_bits) - HEADER_BITS)
    body_source_bits = blob_bits[HEADER_BITS : HEADER_BITS + min(_selected_body_bits(), available_body_bits)]

    (
        coefficients,
        frame_verified_data,
        nC_map,
        nal_length_map,
        t1_override_map,
        _safe_positions,
    ) = load_or_build_benchmark_analysis(video_path, force=force)

    repeated_header_bits = _repeat_bits(header_source_bits, HEADER_REDUNDANCY)
    rows = []

    for scheme in _selected_body_schemes():
        encoded_body_bits, decode_meta = _encode_body(body_source_bits, scheme)
        header_positions, _ = derive_blind_header_positions(
            video_path,
            SECRET_KEY,
            header_bits=len(repeated_header_bits),
            use_analysis_cache=True,
        )
        body_positions, _ = derive_blind_body_positions(
            video_path,
            SECRET_KEY,
            body_bits=len(encoded_body_bits),
            header_positions=header_positions,
            use_analysis_cache=True,
        )
        positions = header_positions + body_positions
        payload_bits = repeated_header_bits + encoded_body_bits
        payload = _bits_to_bytes(payload_bits)
        out_path = Path("data/output") / f"_blind_payload_{scheme}_{len(body_source_bits)}b.h264"
        row = {
            "scheme": scheme,
            "body_bits_configured": len(body_source_bits),
            "header_success": False,
            "body_bits_probed": len(body_source_bits),
            "body_bits_matched": 0,
            "body_match_ratio": 0.0,
            "full_prefix_success": False,
        }
        try:
            embedder = PayloadEmbedder(max_modifications_per_block=1)
            modified, bits_embedded = embedder.embed_payload(
                coefficients,
                payload,
                nC_map=nC_map,
                nal_length_map=nal_length_map,
                t1_override_map=t1_override_map,
                frame_verified_data=frame_verified_data,
                pre_validated_positions=positions,
            )
            rec = BitstreamReconstructor()
            rec.reconstruct_video(
                video_path,
                modified,
                str(out_path),
                max_slices=None,
                frame_verified_data=frame_verified_data,
            )
            _, stego_fvd, stego_nC, _, _, _ = load_or_build_benchmark_analysis(str(out_path), force=True)
            derived_header, _ = derive_blind_header_positions(
                str(out_path),
                SECRET_KEY,
                header_bits=len(repeated_header_bits),
                use_analysis_cache=True,
            )
            derived_body, _ = derive_blind_body_positions(
                str(out_path),
                SECRET_KEY,
                body_bits=len(encoded_body_bits),
                header_positions=derived_header,
                use_analysis_cache=True,
            )
            derived_positions = derived_header + derived_body
            blob_out = extract_bits_direct(
                str(out_path),
                derived_positions,
                stego_fvd,
                stego_nC,
                len(payload_bits),
                max_modifications_per_block=1,
            )
            out_bits = _bytes_to_bits(blob_out)[: len(payload_bits)]

            header_voted = _majority_vote(out_bits[: len(repeated_header_bits)], HEADER_REDUNDANCY)
            header_ok = int.from_bytes(_bits_to_bytes(header_voted[:HEADER_BITS])[:4], "big") == len(MESSAGE)
            decoded_body = _decode_body(
                out_bits[len(repeated_header_bits) : len(repeated_header_bits) + len(encoded_body_bits)],
                len(body_source_bits),
                decode_meta,
            )
            body_matches = sum(1 for a, b in zip(body_source_bits, decoded_body[: len(body_source_bits)]) if a == b)

            row.update(
                {
                    "bits_embedded": bits_embedded,
                    "header_success": header_ok,
                    "body_bits_matched": body_matches,
                    "body_match_ratio": body_matches / max(1, len(body_source_bits)),
                    "full_prefix_success": header_ok and body_matches == len(body_source_bits),
                }
            )
        finally:
            for path in (
                out_path,
                Path(f"{out_path}.positions.json"),
                Path(f"{out_path}.meta.json"),
                Path(f"{out_path}.manifest.json"),
            ):
                if path.exists():
                    path.unlink()
        rows.append(row)

    data = {"sequence": seq_name, "rows": rows}
    cache_save(CACHE_KEY, data)
    return data


def run(force: bool = False) -> dict:
    print("\n=== Blind Payload Coding Diagnostic ===")
    data = collect_data(force=force)
    for row in data["rows"]:
        print(
            f"  scheme={row['scheme']} header={row['header_success']} "
            f"body_match={row['body_bits_matched']}/{row['body_bits_probed']} "
            f"full_prefix={row['full_prefix_success']}"
        )
    print(f"  [saved] {(RESULTS_DIR / f'{CACHE_KEY}.json').name}")
    return data


if __name__ == "__main__":
    run(force="--force" in sys.argv)
