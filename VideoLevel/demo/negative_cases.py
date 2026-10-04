"""Rejection cases for terminal_demo.py, all on the native segment protocol.

Each case builds a real file or input and asserts the specific reason it is
rejected: Groth16 (changed message, invalid proof, one flipped message carrier
bit), the demo wrapper (missing proof), the native frame header check (wrong key).
Protocol v3 frames carry no MAC, so the proof is what catches a changed payload.
"""
from __future__ import annotations

from pathlib import Path

import deep_trace
from native_io import inspect_segments, native_embed, native_extract, verify_groth16

# Native messages raised when no v3 frame is found under a key (see cavlc_stream.cpp).
FRAME_NOT_FOUND_MARKERS = (
    "cavlc stream version is invalid",
    "cavlc stream length exceeds configured maximum",
    "cavlc frame version is invalid",
    "cavlc frame length is invalid",
    "ended before payload was complete",
    "blind schedule capacity is insufficient",
)
FRAME_HEADER_BYTES, LENGTH_PREFIX_BYTES = 3, 4


def is_frame_not_found(stderr_text: str) -> bool:
    lowered = stderr_text.lower()
    return "error:" in lowered and any(marker in lowered for marker in FRAME_NOT_FOUND_MARKERS)


def run_all(session, tools, bridge, source: Path, stego: Path, after: dict, key: bytes,
            message: bytes, proof: dict, plan) -> None:
    session.stage("Cac ca bac bo that va pham vi bao ve")
    bad_message = bytes([message[0] ^ 1]) + message[1:]
    session.check("doi message -> Groth16 false", not verify_groth16(
        session, proof, bridge._build_public_signals(bad_message, key), "reject_changed_message"))
    _invalid_and_missing_proof(session, tools, bridge, source, key, message, proof, plan)
    session.say("Native chi tim khung v3 (version + do dai, khong MAC); demo wrapper bat buoc unpack + verify Groth16 truoc accept.")
    wrong_key = bytes([key[0] ^ 1]) + key[1:]
    result = native_extract(session, tools, stego, wrong_key, plan.max_bits, "reject_wrong_key", allow_failure=True)
    error = result.stderr.decode("utf-8", errors="replace")
    session.check("sai shared key -> native reject", result.returncode == 2 and is_frame_not_found(error))
    session.say("  " + error.strip())
    session.say("  Sai key -> lich segment khac + keystream khac -> header version ngau nhien -> reject.")
    _flip_one_carrier_bit(session, tools, bridge, stego, after, key, message, plan)
    session.say("Ket luan pham vi: payload duoc Groth16 kiem tra. Video integrity va camera origin CHUA duoc circuit rang buoc.")
    session.say("Khong duoc suy ra 'proof true => moi pixel/P frame cua video la nguyen ban'.")
    session.report["verdict"] = True
    session.report["coverage"] = {"payload_mac": False, "mandatory_groth16": True,
                                  "whole_video_integrity": False, "camera_origin": False}


def _invalid_and_missing_proof(session, tools, bridge, source: Path, key: bytes, message: bytes, proof: dict,
                               plan) -> None:
    from src.zk_proof import bytes_to_proof, pack, proof_to_bytes, unpack

    changed_proof = dict(proof)
    changed_proof["pi_a"] = list(proof["pi_c"])
    bad_proof_video = session.folder / "invalid_proof.h264"
    native_embed(session, tools, source, bad_proof_video, key, pack(message, proof_to_bytes(changed_proof)),
                 plan.max_bits, "embed_invalid_proof")
    extracted = native_extract(session, tools, bad_proof_video, key, plan.max_bits, "extract_invalid_proof")
    bad_message, bad_proof = unpack(bytes.fromhex(extracted.stdout.decode().strip()))
    session.check("khung dung nhung proof sai -> Groth16 false", not verify_groth16(
        session, bytes_to_proof(bad_proof), bridge._build_public_signals(bad_message, key), "reject_changed_proof"))
    proofless_video = session.folder / "missing_proof.h264"
    proofless_payload = len(message).to_bytes(LENGTH_PREFIX_BYTES, "big") + message
    native_embed(session, tools, source, proofless_video, key, proofless_payload, plan.max_bits, "embed_missing_proof")
    extracted = native_extract(session, tools, proofless_video, key, plan.max_bits, "extract_missing_proof")
    missing_rejected = False
    try:
        unpack(bytes.fromhex(extracted.stdout.decode().strip()))
    except ValueError:
        missing_rejected = True
    session.check("khung dung nhung thieu proof -> wrapper reject", missing_rejected)


def _pick_carrier(data: bytes, after: dict, plan, message_bytes: int):
    """First scheduled message-bit carrier whose byte flip keeps the EBSP framing unchanged.

    Both the old and new byte are >= 0x04: zero runs stay the same, no 00 00 0x
    (x <= 3) pattern appears or disappears, so no emulation-prevention byte or
    start code is created or destroyed and RBSP offsets of every other bit hold.
    """
    first = (FRAME_HEADER_BYTES + LENGTH_PREFIX_BYTES) * 8
    last = first + message_bytes * 8
    for placement in plan.placements:
        if not first <= placement.frame_bit_index < last:
            continue
        nal_row = after["nals"][placement.candidate.nal_index]
        offset, _ = deep_trace.file_offset_of_rbsp_bit(data, nal_row, placement.candidate.rbsp_bit_offset)
        mask = 1 << (7 - placement.candidate.rbsp_bit_offset % 8)
        if data[offset] >= 4 and data[offset] ^ mask >= 4:
            return placement, offset, mask
    raise RuntimeError("Khong tim duoc carrier message co the lat ma khong doi emulation prevention")


def _flip_one_carrier_bit(session, tools, bridge, stego: Path, after: dict, key: bytes, message: bytes,
                          plan) -> None:
    from src.zk_proof import bytes_to_proof, unpack

    message_bytes = len(message)
    data = stego.read_bytes()
    placement, offset, mask = _pick_carrier(data, after, plan, message_bytes)
    tampered = session.folder / "tampered_carrier.h264"
    patched = bytearray(data)
    patched[offset] ^= mask
    tampered.write_bytes(bytes(patched))
    session.say(f"Lat 1 carrier: frame bit {placement.frame_bit_index} ({deep_trace.frame_field(placement.frame_bit_index, message_bytes)}),"
                f" segment {placement.segment}, NAL {placement.candidate.nal_index} RBSP bit {placement.candidate.rbsp_bit_offset}")
    session.say(f"  -> byte file {offset}: {data[offset]:02x} -> {patched[offset]:02x}"
                " (ca hai >= 0x04: khong tao/mat emulation-prevention, offset cac bit khac giu nguyen)")
    before_segments = inspect_segments(session, tools.inspect, stego, plan.max_bits, "segments_stego_for_tamper")
    after_segments = inspect_segments(session, tools.inspect, tampered, plan.max_bits, "segments_tampered")
    changed = [(row["segment"], a["id"]) for row, row_t in zip(before_segments["segments"], after_segments["segments"])
               for a, b in zip(row["candidates"], row_t["candidates"]) if a != b]
    expected = (placement.segment, placement.candidate.identity.serialize().decode())
    session.check("parser native: dung 1 sign bit da lap lich bi doi, cu phap giu nguyen",
                  changed == [expected] and len(before_segments["segments"]) == len(after_segments["segments"]))
    decode = session.run("decode_tampered", ["ffmpeg", "-v", "error", "-xerror", "-nostdin", "-i", tampered,
                                             "-f", "null", "-"], allow_failure=True)
    session.check("FFmpeg van decode stream bi lat (loi chi nam o payload)", decode.returncode == 0)
    result = native_extract(session, tools, tampered, key, plan.max_bits, "flipped_carrier", allow_failure=True)
    session.check("lat 1 bit message carrier -> native van trich duoc (khung v3 khong co MAC)", result.returncode == 0)
    altered_message, altered_proof = unpack(bytes.fromhex(result.stdout.decode().strip()))
    session.check("message trich ra da bi doi dung 1 bit", altered_message != message
                  and sum(bin(a ^ b).count("1") for a, b in zip(altered_message, message)) == 1)
    session.check("lat 1 bit message carrier -> Groth16 false", not verify_groth16(
        session, bytes_to_proof(altered_proof), bridge._build_public_signals(altered_message, key), "reject_carrier_flip"))
    session.say("  Kenh chi giau va dinh vi payload; proof Groth16 moi la thu bat duoc message bi sua.")

