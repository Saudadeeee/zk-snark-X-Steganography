"""
blind_partial_payload_contract.py - Structured blind partial-payload diagnostic.

This benchmark moves beyond generic prefix probing and uses a payload layout
closer to the real blob structure:

  [4-byte message length][message bytes][proof-prefix bytes]

The current blind coding stack uses:
  - repeated blind header positions for the 4-byte length
  - repeated blind body positions for message + proof-prefix bytes

It does not claim full proof recovery. It measures whether a structured partial
payload can already survive blind embed/extract with heavy redundancy.
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

CACHE_KEY = "blind_partial_payload_contract"
SECRET_KEY = b"zk_mv_stego_2026_secret_key!!!!!"
MESSAGE = b"Hello ZK-Stego"
HEADER_BITS = 32
HEADER_REDUNDANCY = 4
BODY_REDUNDANCY = 8


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


def _permute_bytes_by_stride(data: bytes, stride: int) -> tuple[bytes, list[int]]:
    if stride <= 1 or len(data) <= 1:
        order = list(range(len(data)))
        return data, order
    order = list(range(0, len(data), stride))
    for offset in range(1, stride):
        order.extend(range(offset, len(data), stride))
    return bytes(data[idx] for idx in order), order


def _invert_byte_permutation(permuted: bytes, order: list[int]) -> bytes:
    restored = bytearray(len(order))
    for src_idx, dst_idx in enumerate(order):
        if src_idx < len(permuted):
            restored[dst_idx] = permuted[src_idx]
    return bytes(restored)


def _fast_mode_enabled() -> bool:
    return os.environ.get("BLIND_PARTIAL_FAST", "0") == "1" or "--fast" in sys.argv


def _proof_prefix_lengths() -> list[int]:
    override = os.environ.get("BLIND_PARTIAL_PREFIX_BYTES")
    if override:
        vals = []
        for part in override.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                val = int(part)
            except ValueError:
                continue
            if val > 0:
                vals.append(val)
        if vals:
            return vals
    if _fast_mode_enabled():
        return [16, 24]
    return [16, 24, 32]


def _coding_modes() -> list[str]:
    override = os.environ.get("BLIND_PARTIAL_MODES")
    if override:
        modes = [part.strip() for part in override.split(",") if part.strip()]
    if modes:
        return modes
    return ["baseline"]


def _parse_tail_triplicate_mode(mode: str) -> int | None:
    prefix = "proof_tail_triplicate"
    if not mode.startswith(prefix):
        return None
    suffix = mode[len(prefix):]
    if not suffix:
        return 16
    try:
        value = int(suffix)
    except ValueError:
        return None
    return value if value > 0 else None


def _parse_hotspot_triplicate_mode(mode: str) -> tuple[int, int] | None:
    prefix = "proof_hotspot_triplicate"
    if not mode.startswith(prefix):
        return None
    suffix = mode[len(prefix):]
    if not suffix:
        return (80, 8)
    parts = [part for part in suffix.split("_") if part]
    if len(parts) != 2:
        return None
    try:
        start = int(parts[0])
        length = int(parts[1])
    except ValueError:
        return None
    if start < 0 or length <= 0:
        return None
    return (start, length)


def _encode_body(mode: str, message: bytes, proof_prefix: bytes) -> tuple[list[int], dict]:
    message_bits = _bytes_to_bits(message)
    proof_bits = _bytes_to_bits(proof_prefix)

    if mode == "baseline":
        combined = message + proof_prefix
        return _repeat_bits(_bytes_to_bits(combined), BODY_REDUNDANCY), {
            "mode": mode,
            "proof_copy_count": 1,
            "message_bits": len(message_bits),
            "proof_bits": len(proof_bits),
        }

    if mode == "proof_triplicate":
        combined = message + proof_prefix + proof_prefix + proof_prefix
        return _repeat_bits(_bytes_to_bits(combined), BODY_REDUNDANCY), {
            "mode": mode,
            "proof_copy_count": 3,
            "message_bits": len(message_bits),
            "proof_bits": len(proof_bits),
        }

    if mode == "proof_interleaved":
        encoded_message = _repeat_bits(message_bits, BODY_REDUNDANCY)
        proof_groups = [[bit] * BODY_REDUNDANCY for bit in proof_bits]
        encoded_proof = _interleave_groups(proof_groups)
        return encoded_message + encoded_proof, {
            "mode": mode,
            "proof_copy_count": 1,
            "message_bits": len(message_bits),
            "proof_bits": len(proof_bits),
            "proof_group_width": BODY_REDUNDANCY,
        }

    if mode == "proof_byte_stride4":
        permuted_proof, order = _permute_bytes_by_stride(proof_prefix, 4)
        combined = message + permuted_proof
        return _repeat_bits(_bytes_to_bits(combined), BODY_REDUNDANCY), {
            "mode": mode,
            "proof_copy_count": 1,
            "message_bits": len(message_bits),
            "proof_bits": len(proof_bits),
            "byte_order": order,
        }

    tail_trip_len = _parse_tail_triplicate_mode(mode)
    if tail_trip_len is not None:
        tail_len = min(tail_trip_len, len(proof_prefix))
        tail = proof_prefix[-tail_len:]
        combined = message + proof_prefix + tail + tail
        return _repeat_bits(_bytes_to_bits(combined), BODY_REDUNDANCY), {
            "mode": mode,
            "proof_copy_count": 1,
            "message_bits": len(message_bits),
            "proof_bits": len(proof_bits),
            "tail_len": tail_len,
        }

    hotspot = _parse_hotspot_triplicate_mode(mode)
    if hotspot is not None:
        start, length = hotspot
        start = min(start, len(proof_prefix))
        hotspot_bytes = proof_prefix[start : start + length]
        combined = message + proof_prefix + hotspot_bytes + hotspot_bytes
        return _repeat_bits(_bytes_to_bits(combined), BODY_REDUNDANCY), {
            "mode": mode,
            "proof_copy_count": 1,
            "message_bits": len(message_bits),
            "proof_bits": len(proof_bits),
            "hotspot_start": start,
            "hotspot_len": len(hotspot_bytes),
        }

    raise ValueError(f"Unknown blind partial mode: {mode}")


def _decode_body(mode_meta: dict, extracted_body_bits: list[int], message_len: int, proof_prefix_len: int) -> tuple[bytes, bytes]:
    message_bits_len = int(mode_meta["message_bits"])
    proof_bits_len = int(mode_meta["proof_bits"])
    mode = str(mode_meta["mode"])

    if mode in {"baseline", "proof_triplicate"}:
        body_decoded_bits = _majority_vote(extracted_body_bits, BODY_REDUNDANCY)[: message_bits_len + proof_bits_len * int(mode_meta["proof_copy_count"])]
        body_decoded = _bits_to_bytes(body_decoded_bits)
        decoded_message = body_decoded[:message_len]
        decoded_stream = body_decoded[message_len:]
        proof_copy_count = int(mode_meta["proof_copy_count"])
        if proof_copy_count == 1:
            decoded_proof = decoded_stream[:proof_prefix_len]
        else:
            copies = [
                decoded_stream[i * proof_prefix_len : (i + 1) * proof_prefix_len]
                for i in range(proof_copy_count)
            ]
            voted = bytearray()
            for idx in range(proof_prefix_len):
                values = [copy[idx] for copy in copies if idx < len(copy)]
                counts: dict[int, int] = {}
                for value in values:
                    counts[value] = counts.get(value, 0) + 1
                voted.append(max(counts.items(), key=lambda item: item[1])[0] if counts else 0)
            decoded_proof = bytes(voted)
        return decoded_message, decoded_proof

    if mode == "proof_interleaved":
        encoded_message_bits = extracted_body_bits[: message_bits_len * BODY_REDUNDANCY]
        encoded_proof_bits = extracted_body_bits[message_bits_len * BODY_REDUNDANCY : message_bits_len * BODY_REDUNDANCY + proof_bits_len * BODY_REDUNDANCY]
        decoded_message_bits = _majority_vote(encoded_message_bits, BODY_REDUNDANCY)[:message_bits_len]
        proof_groups = _deinterleave_groups(encoded_proof_bits, int(mode_meta["proof_group_width"]), proof_bits_len)
        decoded_proof_bits = [1 if sum(group) > len(group) / 2 else 0 for group in proof_groups]
        return (
            _bits_to_bytes(decoded_message_bits)[:message_len],
            _bits_to_bytes(decoded_proof_bits)[:proof_prefix_len],
        )

    if mode == "proof_byte_stride4":
        body_decoded_bits = _majority_vote(extracted_body_bits, BODY_REDUNDANCY)[: message_bits_len + proof_bits_len]
        body_decoded = _bits_to_bytes(body_decoded_bits)
        decoded_message = body_decoded[:message_len]
        permuted_proof = body_decoded[message_len : message_len + proof_prefix_len]
        decoded_proof = _invert_byte_permutation(permuted_proof, list(mode_meta["byte_order"]))
        return decoded_message, decoded_proof

    if _parse_tail_triplicate_mode(mode) is not None:
        tail_len = int(mode_meta["tail_len"])
        total_bits = message_bits_len + proof_bits_len + (tail_len * 8 * 2)
        body_decoded_bits = _majority_vote(extracted_body_bits, BODY_REDUNDANCY)[:total_bits]
        body_decoded = _bits_to_bytes(body_decoded_bits)
        decoded_message = body_decoded[:message_len]
        main_proof = bytearray(body_decoded[message_len : message_len + proof_prefix_len])
        tail_copy_1 = body_decoded[message_len + proof_prefix_len : message_len + proof_prefix_len + tail_len]
        tail_copy_2 = body_decoded[
            message_len + proof_prefix_len + tail_len : message_len + proof_prefix_len + (2 * tail_len)
        ]
        start = max(0, proof_prefix_len - tail_len)
        for idx in range(tail_len):
            pos = start + idx
            values = []
            if pos < len(main_proof):
                values.append(main_proof[pos])
            if idx < len(tail_copy_1):
                values.append(tail_copy_1[idx])
            if idx < len(tail_copy_2):
                values.append(tail_copy_2[idx])
            counts: dict[int, int] = {}
            for value in values:
                counts[value] = counts.get(value, 0) + 1
            if counts:
                main_proof[pos] = max(counts.items(), key=lambda item: item[1])[0]
        return decoded_message, bytes(main_proof)

    hotspot = _parse_hotspot_triplicate_mode(mode)
    if hotspot is not None:
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

    raise ValueError(f"Unknown blind partial mode: {mode}")


def collect_data(force: bool = False) -> dict:
    cached = cache_load(CACHE_KEY)
    if cached and not force:
        rows = cached.get("rows") if isinstance(cached, dict) else None
        if isinstance(rows, list) and all(isinstance(row, dict) and "proof_prefix_bytes" in row for row in rows):
            print("  [cache hit] blind partial payload contract")
            return cached
        print("  [cache stale] blind partial payload contract")

    seq_name = "coastguard_q22_g1"
    video_path = str(SEQUENCES[seq_name])
    header_source_bits = _bytes_to_bits(len(MESSAGE).to_bytes(4, "big"))

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

    for proof_prefix_bytes in _proof_prefix_lengths():
        proof_prefix = bytes([i % 256 for i in range(proof_prefix_bytes)])
        for mode in _coding_modes():
            encoded_body_bits, mode_meta = _encode_body(mode, MESSAGE, proof_prefix)

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
            out_path = Path("data/output") / f"_blind_partial_payload_{proof_prefix_bytes}b_{mode}.h264"
            row = {
                "mode": mode,
                "proof_prefix_bytes": proof_prefix_bytes,
                "header_success": False,
                "message_success": False,
                "proof_prefix_bytes_matched": 0,
                "proof_prefix_bits_matched": 0,
                "proof_prefix_bits_total": proof_prefix_bytes * 8,
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
                header_voted = _majority_vote(extracted_bits[: len(repeated_header_bits)], HEADER_REDUNDANCY)
                header_len = int.from_bytes(_bits_to_bytes(header_voted[:HEADER_BITS])[:4], "big")
                row["header_success"] = header_len == len(MESSAGE)

                decoded_message, decoded_proof_prefix = _decode_body(
                    mode_meta,
                    extracted_bits[len(repeated_header_bits) : len(repeated_header_bits) + len(encoded_body_bits)],
                    len(MESSAGE),
                    proof_prefix_bytes,
                )
                row["message_success"] = decoded_message == MESSAGE

                matched_prefix_bytes = sum(
                    1 for a, b in zip(proof_prefix, decoded_proof_prefix) if a == b
                )
                mismatch_indices = [
                    idx for idx, (a, b) in enumerate(zip(proof_prefix, decoded_proof_prefix)) if a != b
                ]
                matched_prefix_bits = sum(
                    1 for a, b in zip(_bytes_to_bits(proof_prefix), _bytes_to_bits(decoded_proof_prefix)) if a == b
                )
                row.update(
                    {
                        "bits_embedded": bits_embedded,
                        "proof_prefix_bytes_matched": matched_prefix_bytes,
                        "proof_prefix_bits_matched": matched_prefix_bits,
                        "proof_prefix_bit_match_ratio": matched_prefix_bits / max(1, proof_prefix_bytes * 8),
                        "proof_prefix_mismatch_indices": mismatch_indices,
                        "partial_contract_success": row["header_success"]
                        and row["message_success"]
                        and matched_prefix_bytes == proof_prefix_bytes,
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
    print("\n=== Blind Partial Payload Contract ===")
    data = collect_data(force=force)
    for row in data["rows"]:
        print(
            f"  proof_prefix={row['proof_prefix_bytes']}B "
            f"header={row['header_success']} message={row['message_success']} "
            f"proof_match={row['proof_prefix_bytes_matched']}/{row['proof_prefix_bytes']}B "
            f"partial_contract={row['partial_contract_success']} "
            f"mismatch_idx={row['proof_prefix_mismatch_indices'][:4]}"
        )
    print(f"  [saved] {(RESULTS_DIR / f'{CACHE_KEY}.json').name}")
    return data


if __name__ == "__main__":
    run(force="--force" in sys.argv)
