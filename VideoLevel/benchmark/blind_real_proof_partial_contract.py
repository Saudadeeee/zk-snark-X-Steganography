"""
blind_real_proof_partial_contract.py - Blind partial contract with real proof bytes.

This benchmark reuses the strongest current blind partial-payload coding idea
but replaces the synthetic proof-prefix bytes with a real serialized Groth16
proof prefix generated from the project's circuit.
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
from src.zk_proof import ZKSnarkBridge, proof_to_bytes

CACHE_KEY = "blind_real_proof_partial_contract"
SECRET_KEY = bytes(range(32))
MESSAGE = b"ZK-bench-v1.0!"
HEADER_BITS = 32
BODY_REDUNDANCY = 8
HOTSPOT_MODE = "proof_hotspot_triplicate80_8"


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


def _parse_hotspot_triplicate_mode(mode: str) -> tuple[int, int]:
    prefix = "proof_hotspot_triplicate"
    suffix = mode[len(prefix):]
    parts = [part for part in suffix.split("_") if part]
    if len(parts) != 2:
        raise ValueError(f"Bad hotspot mode: {mode}")
    return int(parts[0]), int(parts[1])


def _encode_body(message: bytes, proof_prefix: bytes) -> tuple[list[int], dict]:
    message_bits = _bytes_to_bits(message)
    proof_bits = _bytes_to_bits(proof_prefix)
    start, length = _parse_hotspot_triplicate_mode(HOTSPOT_MODE)
    start = min(start, len(proof_prefix))
    hotspot = proof_prefix[start : start + length]
    combined = message + proof_prefix + hotspot + hotspot
    return _repeat_bits(_bytes_to_bits(combined), BODY_REDUNDANCY), {
        "message_bits": len(message_bits),
        "proof_bits": len(proof_bits),
        "hotspot_start": start,
        "hotspot_len": len(hotspot),
    }


def _decode_body(mode_meta: dict, extracted_body_bits: list[int], message_len: int, proof_prefix_len: int) -> tuple[bytes, bytes]:
    message_bits_len = int(mode_meta["message_bits"])
    proof_bits_len = int(mode_meta["proof_bits"])
    hotspot_start = int(mode_meta["hotspot_start"])
    hotspot_len = int(mode_meta["hotspot_len"])
    total_bits = message_bits_len + proof_bits_len + (hotspot_len * 8 * 2)
    body_decoded_bits = _majority_vote(extracted_body_bits, BODY_REDUNDANCY)[:total_bits]
    body_decoded = _bits_to_bytes(body_decoded_bits)
    decoded_message = body_decoded[:message_len]
    main_proof = bytearray(body_decoded[message_len : message_len + proof_prefix_len])
    copy_1 = body_decoded[message_len + proof_prefix_len : message_len + proof_prefix_len + hotspot_len]
    copy_2 = body_decoded[
        message_len + proof_prefix_len + hotspot_len : message_len + proof_prefix_len + (2 * hotspot_len)
    ]
    for idx in range(hotspot_len):
        pos = hotspot_start + idx
        if pos >= len(main_proof):
            break
        values = [main_proof[pos]]
        if idx < len(copy_1):
            values.append(copy_1[idx])
        if idx < len(copy_2):
            values.append(copy_2[idx])
        counts: dict[int, int] = {}
        for value in values:
            counts[value] = counts.get(value, 0) + 1
        main_proof[pos] = max(counts.items(), key=lambda item: item[1])[0]
    return decoded_message, bytes(main_proof)


def _prefix_lengths() -> list[int]:
    override = os.environ.get("BLIND_REAL_PROOF_PREFIX_BYTES")
    if override:
        out = []
        for part in override.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                value = int(part)
            except ValueError:
                continue
            if value > 0:
                out.append(value)
        if out:
            return out
    return [96, 112, 129]


def _header_redundancy() -> int:
    override = os.environ.get("BLIND_REAL_HEADER_REDUNDANCY")
    if override:
        try:
            value = int(override)
            if value > 0:
                return value
        except ValueError:
            pass
    return 4


def _body_gap_blocks() -> int:
    override = os.environ.get("BLIND_REAL_BODY_GAP_BLOCKS")
    if override:
        try:
            value = int(override)
            if value >= 0:
                return value
        except ValueError:
            pass
    return 0


def _shift_body_positions(
    body_positions: list[tuple[int, int, int]],
    header_positions: list[tuple[int, int, int]],
    *,
    gap_blocks: int,
) -> list[tuple[int, int, int]]:
    if gap_blocks <= 0 or not header_positions:
        return list(body_positions)
    blocked: set[tuple[int, int]] = set()
    for mb, blk, _cidx in header_positions:
        for offset in range(gap_blocks + 1):
            blocked.add((int(mb), int(blk) + offset))
    filtered: list[tuple[int, int, int]] = []
    for pos in body_positions:
        key = (int(pos[0]), int(pos[1]))
        if key in blocked:
            continue
        filtered.append((int(pos[0]), int(pos[1]), int(pos[2])))
    return filtered


def collect_data(force: bool = False) -> dict:
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        rows = cached.get("rows") if isinstance(cached, dict) else None
        if isinstance(rows, list) and all(isinstance(row, dict) and "proof_prefix_bytes" in row for row in rows):
            print("  [cache hit] blind real proof partial contract")
            return cached
        print("  [cache stale] blind real proof partial contract")

    seq_name = "coastguard_q22_g1"
    video_path = str(SEQUENCES[seq_name])
    header_source_bits = _bytes_to_bits(len(MESSAGE).to_bytes(4, "big"))

    bridge = ZKSnarkBridge("circuits")
    proof_dict, _public = bridge.generate_proof_for_payload(MESSAGE, SECRET_KEY)
    real_proof_bytes = proof_to_bytes(proof_dict)

    (
        coefficients,
        frame_verified_data,
        nC_map,
        nal_length_map,
        t1_override_map,
        _safe_positions,
    ) = load_or_build_benchmark_analysis(video_path, force=force)

    header_redundancy = _header_redundancy()
    body_gap_blocks = _body_gap_blocks()
    repeated_header_bits = _repeat_bits(header_source_bits, header_redundancy)
    rows = []

    for prefix_len in _prefix_lengths():
        proof_prefix = real_proof_bytes[:prefix_len]
        encoded_body_bits, mode_meta = _encode_body(MESSAGE, proof_prefix)
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
        body_positions = _shift_body_positions(
            body_positions,
            header_positions,
            gap_blocks=body_gap_blocks,
        )
        positions = header_positions + body_positions
        payload_bits = repeated_header_bits + encoded_body_bits
        payload = _bits_to_bytes(payload_bits)
        out_path = Path("data/output") / f"_blind_real_proof_partial_{prefix_len}b_gap{body_gap_blocks}.h264"
        row = {
            "mode": HOTSPOT_MODE,
            "header_redundancy": header_redundancy,
            "body_gap_blocks": body_gap_blocks,
            "proof_prefix_bytes": prefix_len,
            "header_success": False,
            "decoded_length": None,
            "message_success": False,
            "proof_prefix_bytes_matched": 0,
            "proof_prefix_bits_matched": 0,
            "proof_prefix_bits_total": prefix_len * 8,
            "proof_prefix_mismatch_indices": [],
            "partial_contract_success": False,
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
            derived_body = _shift_body_positions(
                derived_body,
                derived_header,
                gap_blocks=body_gap_blocks,
            )
            derived_positions = derived_header + derived_body
            blob = extract_bits_direct(
                str(out_path),
                derived_positions,
                stego_fvd,
                stego_nC,
                len(payload_bits),
                max_modifications_per_block=1,
            )
            extracted_bits = _bytes_to_bits(blob)[: len(payload_bits)]
            header_voted = _majority_vote(extracted_bits[: len(repeated_header_bits)], header_redundancy)
            header_len = int.from_bytes(_bits_to_bytes(header_voted[:HEADER_BITS])[:4], "big")
            row["header_success"] = header_len == len(MESSAGE)
            row["decoded_length"] = header_len

            decoded_message, decoded_proof_prefix = _decode_body(
                mode_meta,
                extracted_bits[len(repeated_header_bits) : len(repeated_header_bits) + len(encoded_body_bits)],
                len(MESSAGE),
                prefix_len,
            )
            row["message_success"] = decoded_message == MESSAGE

            matched_prefix_bytes = sum(1 for a, b in zip(proof_prefix, decoded_proof_prefix) if a == b)
            mismatch_indices = [idx for idx, (a, b) in enumerate(zip(proof_prefix, decoded_proof_prefix)) if a != b]
            matched_prefix_bits = sum(
                1 for a, b in zip(_bytes_to_bits(proof_prefix), _bytes_to_bits(decoded_proof_prefix)) if a == b
            )
            row.update(
                {
                    "bits_embedded": bits_embedded,
                    "proof_prefix_bytes_matched": matched_prefix_bytes,
                    "proof_prefix_bits_matched": matched_prefix_bits,
                    "proof_prefix_bit_match_ratio": matched_prefix_bits / max(1, prefix_len * 8),
                    "proof_prefix_mismatch_indices": mismatch_indices,
                    "partial_contract_success": row["header_success"]
                    and row["message_success"]
                    and matched_prefix_bytes == prefix_len,
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
    print("\n=== Blind Real Proof Partial Contract ===")
    data = collect_data(force=force)
    for row in data["rows"]:
        print(
            f"  proof_prefix={row['proof_prefix_bytes']}B gap={row['body_gap_blocks']} "
            f"header={row['header_success']} len={row['decoded_length']} message={row['message_success']} "
            f"proof_match={row['proof_prefix_bytes_matched']}/{row['proof_prefix_bytes']}B "
            f"partial_contract={row['partial_contract_success']} "
            f"mismatch_idx={row['proof_prefix_mismatch_indices'][:4]}"
        )
    print(f"  [saved] {(RESULTS_DIR / f'{CACHE_KEY}.json').name}")
    return data


if __name__ == "__main__":
    run(force="--force" in sys.argv)
