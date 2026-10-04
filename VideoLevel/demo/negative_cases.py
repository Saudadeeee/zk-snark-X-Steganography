"""Rejection cases for terminal_demo.py, all on the native segment protocol.

Each case builds a real file or input and asserts the specific reason it is
rejected. The camera proof catches a changed message, an invalid or foreign
proof, a flipped message carrier bit, a flipped sign that carries nothing, a cut
video and the same payload replayed into another video (the digest changes); the
demo wrapper refuses a payload without a proof; the native frame header check
refuses a wrong stego key. Protocol v3 frames carry no MAC.
"""
from __future__ import annotations

from pathlib import Path

import deep_trace
from native_io import inspect_segments, native_embed, native_extract

from src.camera_proof import frame_bits_for_message, verify_payload
from src.camera_registry import CameraRegistry, camera_public_key, new_camera_secret
from src.zk_proof import PAYLOAD_HEADER_BYTES, pack_payload, proof_to_bytes, unpack_payload
from src.video_binding import MODE_VIDEO, native_video_digest

# Native messages raised when no v3 frame is found under a key (see cavlc_stream.cpp).
FRAME_NOT_FOUND_MARKERS = (
    "cavlc stream version is invalid",
    "cavlc stream length exceeds configured maximum",
    "cavlc frame version is invalid",
    "cavlc frame length is invalid",
    "ended before payload was complete",
    "blind schedule capacity is insufficient",
)
FRAME_HEADER_BYTES = 3


def is_frame_not_found(stderr_text: str) -> bool:
    lowered = stderr_text.lower()
    return "error:" in lowered and any(marker in lowered for marker in FRAME_NOT_FOUND_MARKERS)


def _verdict(tools, bridge, camera, payload: bytes, video: Path, key: bytes, max_bits: int):
    return verify_payload(bridge, camera.registry.root, payload, native_cli=tools.native, stego=video,
                          stego_key=key, max_bits_per_idr=max_bits)


def run_all(session, tools, bridge, camera, source: Path, stego: Path, after: dict, key: bytes,
            message: bytes, proof: dict, plan) -> None:
    session.stage("Cac ca bac bo that va pham vi bao ve")
    proof_bytes = proof_to_bytes(proof)
    bad_message = bytes([message[0] ^ 1]) + message[1:]
    verdict = _verdict(tools, bridge, camera, pack_payload(MODE_VIDEO, bad_message, proof_bytes), stego, key,
                       plan.max_bits)
    session.check("doi message, giu proof -> Groth16 tu choi", not verdict.valid and verdict.reason == "proof_invalid")
    _invalid_and_missing_proof(session, tools, bridge, camera, source, key, message, proof, plan)
    session.say("Native chi tim khung v3 (version + do dai, khong MAC); demo wrapper bat buoc verify Groth16 truoc accept.")
    wrong_key = bytes([key[0] ^ 1]) + key[1:]
    result = native_extract(session, tools, stego, wrong_key, plan.max_bits, "reject_wrong_key", allow_failure=True)
    error = result.stderr.decode("utf-8", errors="replace")
    session.check("sai stego key -> native reject", result.returncode == 2 and is_frame_not_found(error))
    session.say("  " + error.strip())
    session.say("  Sai key -> lich segment khac + keystream khac -> header version ngau nhien -> reject.")
    _flip_one_carrier_bit(session, tools, bridge, camera, stego, after, key, message, plan)
    _flip_non_carrier_sign(session, tools, bridge, camera, stego, after, key, message, plan)
    _cut_last_frame(session, tools, bridge, camera, stego, after, key, plan)
    _replay_into_other_video(session, tools, bridge, camera, key, message, proof, plan)
    _unregistered_camera(session, tools, bridge, camera, stego, key, message, plan)
    session.say("Ket luan pham vi: proof chung minh MOT camera trong so dang ky (root) xac nhan DUNG video nay")
    session.say("(moi bit; bit carrier duoc bao ve qua payload) va message; verifier khong biet camera nao, khong can secret camera.")
    session.say("Chua chung minh: camera that su quay canh do (vd. quay lai man hinh), va setup Groth16 la DEMO.")
    session.report["verdict"] = True
    session.report["coverage"] = {"payload_mac": False, "mandatory_groth16": True, "whole_video_integrity": True,
                                  "camera_registry_membership": True, "camera_identity_hidden": True}


def _invalid_and_missing_proof(session, tools, bridge, camera, source: Path, key: bytes, message: bytes,
                               proof: dict, plan) -> None:
    changed_proof = dict(proof)
    changed_proof["pi_a"] = list(proof["pi_c"])
    bad_proof_video = session.folder / "invalid_proof.h264"
    native_embed(session, tools, source, bad_proof_video, key,
                 pack_payload(MODE_VIDEO, message, proof_to_bytes(changed_proof)), plan.max_bits, "embed_invalid_proof")
    extracted = native_extract(session, tools, bad_proof_video, key, plan.max_bits, "extract_invalid_proof")
    verdict = _verdict(tools, bridge, camera, bytes.fromhex(extracted.stdout.decode().strip()), bad_proof_video,
                       key, plan.max_bits)
    session.check("khung dung nhung proof sai -> Groth16 tu choi", not verdict.valid and verdict.reason == "proof_invalid")
    proofless_video = session.folder / "missing_proof.h264"
    proofless_payload = bytes((1, MODE_VIDEO)) + len(message).to_bytes(2, "big") + message
    native_embed(session, tools, source, proofless_video, key, proofless_payload, plan.max_bits, "embed_missing_proof")
    extracted = native_extract(session, tools, proofless_video, key, plan.max_bits, "extract_missing_proof")
    verdict = _verdict(tools, bridge, camera, bytes.fromhex(extracted.stdout.decode().strip()), proofless_video,
                       key, plan.max_bits)
    session.check("khung dung nhung thieu proof -> wrapper reject",
                  not verdict.valid and verdict.reason == "malformed_proof_payload")


def _pick_carrier(data: bytes, after: dict, plan, message_bytes: int):
    """First scheduled message-bit carrier whose byte flip keeps the EBSP framing unchanged.

    Both the old and new byte are >= 0x04: zero runs stay the same, no 00 00 0x
    (x <= 3) pattern appears or disappears, so no emulation-prevention byte or
    start code is created or destroyed and RBSP offsets of every other bit hold.
    """
    first = (FRAME_HEADER_BYTES + PAYLOAD_HEADER_BYTES) * 8
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


def _flip_one_carrier_bit(session, tools, bridge, camera, stego: Path, after: dict, key: bytes, message: bytes,
                          plan) -> None:
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
    altered = bytes.fromhex(result.stdout.decode().strip())
    altered_message = unpack_payload(altered).message
    session.check("message trich ra da bi doi dung 1 bit", altered_message != message
                  and sum(bin(a ^ b).count("1") for a, b in zip(altered_message, message)) == 1)
    verdict = _verdict(tools, bridge, camera, altered, tampered, key, plan.max_bits)
    session.check("lat 1 bit message carrier -> Groth16 tu choi", not verdict.valid and verdict.reason == "proof_invalid")
    session.say("  Bit bi lat la bit carrier nen digest khong doi; chinh message doi lam binding doi.")


def _safe_flip(data: bytes, nal_row: dict, rbsp_bit: int) -> tuple[int, int] | None:
    """(file offset, mask) of an RBSP bit whose flip keeps every EPB/start code, else None."""
    offset, _ = deep_trace.file_offset_of_rbsp_bit(data, nal_row, rbsp_bit)
    mask = 1 << (7 - rbsp_bit % 8)
    return (offset, mask) if data[offset] >= 4 and data[offset] ^ mask >= 4 else None


def _flip_non_carrier_sign(session, tools, bridge, camera, stego: Path, after: dict, key: bytes, message: bytes,
                           plan) -> None:
    """Flip a trailing-one sign in a carrier IDR that the keyed schedule did NOT select."""
    carriers = {(p.candidate.nal_index, p.candidate.rbsp_bit_offset) for p in plan.placements}
    carrier_nal = plan.placements[0].candidate.nal_index
    nal_row = after["nals"][carrier_nal]
    data = stego.read_bytes()
    for row in after["candidates"]:
        nal, rbsp_bit = row["id"][0], row["id"][4]
        if nal == carrier_nal and (nal, rbsp_bit) not in carriers and (flip := _safe_flip(data, nal_row, rbsp_bit)):
            break
    else:
        raise RuntimeError("Khong tim duoc bit dau ngoai lich co the lat an toan")
    offset, mask = flip
    tampered = session.folder / "tampered_non_carrier.h264"
    patched = bytearray(data)
    patched[offset] ^= mask
    tampered.write_bytes(bytes(patched))
    session.say(f"Lat 1 bit dau KHONG mang khung: ung vien {':'.join(map(str, row['id']))} (cung IDR NAL {carrier_nal}"
                f" voi khung), byte file {offset}: {data[offset]:02x} -> {patched[offset]:02x}")
    result = native_extract(session, tools, tampered, key, plan.max_bits, "extract_non_carrier")
    extracted = bytes.fromhex(result.stdout.decode().strip())
    session.check("lat bit ngoai lich -> payload trich ra KHONG doi", unpack_payload(extracted).message == message)
    digest = native_video_digest(tools.native, tampered, key, frame_bits_for_message(len(message)), plan.max_bits)
    session.say(f"  digest video bi sua = {digest.hex()}")
    session.say(f"  digest da ky        = {camera.video_digest.hex()}")
    session.check("lat bit ngoai lich -> digest doi", digest != camera.video_digest)
    verdict = _verdict(tools, bridge, camera, extracted, tampered, key, plan.max_bits)
    session.check("lat bit ngoai lich -> Groth16 tu choi (binding khong khop)",
                  not verdict.valid and verdict.reason == "proof_invalid")


def _replay_into_other_video(session, tools, bridge, camera, key: bytes, message: bytes, proof: dict, plan) -> None:
    """Embed the exact accepted payload into a different video: extraction works, the binding does not."""
    command = list(session.report["encoder_command"])
    current = Path(command[command.index("-i") + 1])
    others = [path for path in sorted((Path(__file__).resolve().parents[1] / "data/raw").glob("*.y4m"))
              if path.resolve() != current.resolve()]
    other_cover = session.folder / "replay_cover.h264"
    if others:
        command[command.index("-i") + 1] = str(others[0])
        what = f"clip khac ({others[0].name})"
    else:
        command[command.index("-qp") + 1] = str(min(51, int(command[command.index("-qp") + 1]) + 6))
        what = "cung clip, encode lai QP khac"
    command[-1] = str(other_cover)
    session.run("encode_replay_cover", command)
    other_stego = session.folder / "replay_stego.h264"
    payload = pack_payload(MODE_VIDEO, message, proof_to_bytes(proof))
    session.say(f"Replay: nhung NGUYEN payload da duoc chap nhan (message + proof) vao video khac: {what}.")
    native_embed(session, tools, other_cover, other_stego, key, payload, plan.max_bits, "embed_replay")
    result = native_extract(session, tools, other_stego, key, plan.max_bits, "extract_replay")
    extracted = bytes.fromhex(result.stdout.decode().strip())
    session.check("replay: native trich duoc dung payload cu tu video moi", extracted == payload)
    digest = native_video_digest(tools.native, other_stego, key, frame_bits_for_message(len(message)), plan.max_bits)
    session.say(f"  digest video moi = {digest.hex()}")
    session.say(f"  digest trong proof = {camera.video_digest.hex()}")
    verdict = _verdict(tools, bridge, camera, extracted, other_stego, key, plan.max_bits)
    session.check("replay sang video khac -> Groth16 tu choi (proof gan voi video goc)",
                  not verdict.valid and verdict.reason == "proof_invalid")


def _cut_last_frame(session, tools, bridge, camera, stego: Path, after: dict, key: bytes, plan) -> None:
    data = stego.read_bytes()
    last = after["nals"][-1]
    cut = session.folder / "cut_last_frame.h264"
    cut.write_bytes(data[:last["offset"]])
    session.say(f"Cat NAL cuoi (type {last['type']}, {last['ebsp_bytes']} byte) khoi stego -> {cut.name}")
    result = native_extract(session, tools, cut, key, plan.max_bits, "extract_cut", allow_failure=True)
    if result.returncode != 0:
        session.check("cat frame cuoi (frame mang bit) -> native khong tim du khung", is_frame_not_found(
            result.stderr.decode("utf-8", errors="replace")))
        return
    verdict = _verdict(tools, bridge, camera, bytes.fromhex(result.stdout.decode().strip()), cut, key, plan.max_bits)
    session.check("cat frame cuoi -> digest video doi -> Groth16 tu choi",
                  not verdict.valid and verdict.reason == "proof_invalid")


def _unregistered_camera(session, tools, bridge, camera, stego: Path, key: bytes, message: bytes, plan) -> None:
    outsider_secret = new_camera_secret()
    outsider_registry = CameraRegistry([camera_public_key(outsider_secret)])
    proof = bridge.prove(outsider_secret, outsider_registry, camera.binding)
    payload = pack_payload(MODE_VIDEO, message, proof_to_bytes(proof))
    session.say("Camera NGOAI so dang ky tu dung cay rieng va tao proof hop le cho cung video + message.")
    session.check("proof cua camera ngoai so dang ky dung voi root cua chinh no",
                  bridge.verify(proof, outsider_registry.root, camera.binding))
    verdict = _verdict(tools, bridge, camera, payload, stego, key, plan.max_bits)
    session.check("camera ngoai so dang ky -> tu choi voi root tin cay",
                  not verdict.valid and verdict.reason == "proof_invalid")
