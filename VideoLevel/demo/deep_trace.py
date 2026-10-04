"""Deep, step-by-step trace for terminal_demo.py (enabled unless --brief).

Shows what happens inside FFmpeg/libx264 (from their own logs and bitstream
tracer), how the Annex-B file is cut into NAL units, and the full life of one
embedded 4x4 block: bits -> CAVLC syntax -> coefficients -> dequantization ->
inverse transform -> intra prediction -> pixels. Every recomputed value is
checked against FFmpeg's decoder or the native parser, so the walkthrough
cannot silently drift from what the real code does.
"""
from __future__ import annotations

import json
import math
import re
import sys
import textwrap
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

import h264_explain as hx  # noqa: E402

NAL_TYPE_NAMES = {1: "slice P/non-IDR", 5: "slice IDR", 6: "SEI", 7: "SPS", 8: "PPS", 9: "AUD"}
_TRACE_LINE = re.compile(r"\]\s+(\d+)\s+(\S+)\s+([01]+)\s+=\s+(-?\d+)")
_SECTION_LINE = re.compile(r"\[trace_headers @ [^\]]+\]\s+([A-Z][A-Za-z ]+)$")


# ------------------------------------------------------------------ helpers

def _matrix_lines(matrix: list[list], width: int = 6) -> list[str]:
    return [" ".join(f"{value:>{width}}" for value in row) for row in matrix]


def show_matrices(session, titles: list[str], matrices: list[list[list]], width: int = 6) -> None:
    """Print several 4x4 matrices side by side under their titles."""
    column = max(4 * (width + 1), *(len(title) for title in titles))
    session.say("    " + "   ".join(title.ljust(column) for title in titles))
    blocks = [_matrix_lines(m, width) for m in matrices]
    for row in range(len(blocks[0])):
        session.say("    " + "   ".join(block[row].ljust(column) for block in blocks))


def _difference(a: list[list[int]], b: list[list[int]]) -> list[list[int]]:
    return [[b[r][c] - a[r][c] for c in range(len(a[0]))] for r in range(len(a))]


def _plane_block(plane: bytes, width: int, x0: int, y0: int, size: int = 4) -> list[list[int]]:
    return [[plane[(y0 + r) * width + x0 + c] for c in range(size)] for r in range(size)]


def _luma_plane(path: Path, width: int, height: int, frame: int) -> bytes:
    frame_size = width * height * 3 // 2
    with path.open("rb") as stream:
        stream.seek(frame * frame_size)
        return stream.read(width * height)


def _decode_raw(session, label: str, video: Path, output: Path, *, no_deblock: bool,
                extra: list[str] | None = None) -> None:
    args = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-threads", "1"]
    if no_deblock:
        args += ["-skip_loop_filter", "all"]
    args += ["-i", video, *(extra or []), "-map", "0:v:0", "-pix_fmt", "yuv420p", "-f", "rawvideo", output]
    session.run(label, args)


# --------------------------------------------------------- 1. FFmpeg / x264

_FFMPEG_ROLES = (
    ("Demuxer (doc container)", lambda l: l.startswith("Input #") or "rawvideo" in l and l.startswith("  Stream #0:0: Video")
     or l.startswith("  Duration") or "[in#0" in l),
    ("Stream mapping (noi decoder -> encoder)", lambda l: l.startswith("Stream mapping") or "->" in l and "Stream #0:0" in l),
    ("Decoder rawvideo / filtergraph (scale, setsar)", lambda l: "Parsed_" in l or "graph -1" in l or "dec:rawvideo" in l),
    ("Encoder libx264", lambda l: "[libx264" in l),
    ("Muxer h264 (ghi Annex-B)", lambda l: l.startswith("Output #") or "[out#0" in l or "AVIOContext" in l),
)

_X264_STATS_HELP = {
    "frame I": "so frame I, QP trung binh, kich thuoc trung binh (byte)",
    "mb I": "ti le MB intra: I16x16 .. I8x8 (=0 o Baseline) .. I4x4",
    "coded y": "ti le block co he so khac 0: luma, chroma DC, chroma AC",
    "i16 v,h,dc,p": "phan bo mode du doan Intra16x16: Vertical, Horizontal, DC, Plane",
    "i4 v,h,dc": "phan bo 9 mode Intra4x4",
    "i8c": "phan bo mode du doan chroma",
    "kb/s": "bitrate trung binh",
}


def ffmpeg_pipeline(session, encode_stderr: str) -> None:
    """Explain the encode using FFmpeg's own verbose log (saved as encode.stderr)."""
    session.say("FFmpeg = chuong trinh dieu phoi cac thu vien libav*. Lenh encode di qua 5 thanh phan,")
    session.say("moi thanh phan chay trong thread rieng va trao doi packet/frame qua hang doi:")
    session.say("  demuxer(yuv4mpegpipe) -> decoder(rawvideo) -> filtergraph(scale,setsar) -> encoder(libx264) -> muxer(h264)")
    lines = [line.rstrip() for line in encode_stderr.splitlines() if line.strip()]
    for title, matcher in _FFMPEG_ROLES:
        picked = [line for line in lines if matcher(line) and "Starting thread" not in line
                  and "Terminating thread" not in line and "EOF" not in line
                  and not any(key in line for key in _X264_STATS_HELP)]
        session.say(f"\n  [{title}]")
        for line in picked[:12]:
            session.say("    " + line[:160])
    stats = [line for line in lines if "[libx264" in line and any(key in line for key in _X264_STATS_HELP)]
    if stats:
        session.say("\n  Thong ke noi bo do chinh libx264 in ra sau khi encode xong:")
        for line in stats:
            text = line.split("]", 1)[-1].strip()
            meaning = next((help_text for key, help_text in _X264_STATS_HELP.items() if text.startswith(key)), "")
            session.say(f"    {text:58} <- {meaning}")
    session.say("\n  Ben trong libx264 voi moi frame (khong co log tung buoc; day la thu tu xu ly):")
    for step in ("chia frame thanh MB 16x16; voi I-frame thu cac mode Intra16x16 / Intra4x4 (RD cost)",
                 "du doan tu pixel da tai tao cua MB lan can; residual = goc - du doan",
                 "bien doi nguyen 4x4 (xap xi DCT) -> luong tu hoa theo QP (deadzone/trellis)",
                 "quet zig-zag -> ma hoa CAVLC (coeff_token, dau T1, level, total_zeros, run_before)",
                 "tai tao lai (dequant + bien doi nguoc + deblocking) de lam tham chieu cho MB/frame sau",
                 "dong goi slice -> NAL, chen emulation-prevention byte, them SPS/PPS/SEI"):
        session.say(f"    - {step}")
    session.say("  QP thuc te cua I-frame thap hon -qp vi x264 dung ipratio=1.40: 22 - 6*log2(1.4) ~ 19.")


# ---------------------------------------------- 2. raw frames before encoding

def raw_input_view(session, source_input: Path, encode_command: list[str], width: int, height: int,
                   ascii_frame) -> Path:
    """Re-create exactly the frames libx264 received and show them as pixels/ASCII."""
    session.say("Video vao (vi du .y4m) chua anh CHUA NEN. FFmpeg demux tung frame, ap filter scale,")
    session.say("roi chuyen frame YUV 4:2:0 cho libx264. Tai tao lai dung cac frame do:")
    if source_input.suffix.lower() == ".y4m":
        with source_input.open("rb") as stream:
            header = stream.readline(4096)
            offsets = [len(header)]
            frame_bytes = None
            match = re.search(rb" W(\d+) H(\d+)", header)
            if match:
                frame_bytes = int(match.group(1)) * int(match.group(2)) * 3 // 2
        session.say(f"  Y4M header ({len(header)} byte): {header.decode('ascii', 'replace').strip()}")
        if frame_bytes:
            marker = len(b"FRAME\n")
            for _ in range(1, 3):
                offsets.append(offsets[-1] + marker + frame_bytes)
            session.say(f"  Moi frame = 'FRAME\\n' (6 byte) + Y({frame_bytes * 2 // 3}) + U + V = {marker + frame_bytes} byte")
            session.say(f"  Vi tri marker FRAME cua 3 frame dau: {offsets}")
    vf = encode_command[encode_command.index("-vf") + 1]
    frames = encode_command[encode_command.index("-frames:v") + 1]
    raw = session.folder / "encoder_input.yuv"
    session.run("encoder_input", ["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", source_input, "-map", "0:v:0",
                                  "-frames:v", frames, "-vf", vf, "-pix_fmt", "yuv420p", "-f", "rawvideo", raw])
    y_size = width * height
    session.say(f"  YUV420p: Y {width}x{height} = {y_size} byte, U va V moi plane {width // 2}x{height // 2} = {y_size // 4} byte")
    first = raw.read_bytes()[:y_size]
    session.say("  Frame #0, plane Y truoc khi nen (ASCII: toi ' ' -> sang '@'):")
    for line in ascii_frame(first, width, height):
        session.say("    " + line)
    session.say("  16x16 mau Y dau tien (MB 0) dang so:")
    for row in range(16):
        session.say("    " + " ".join(f"{first[row * width + col]:3}" for col in range(16)))
    return raw


def encode_loss(session, raw: Path, source: Path, width: int, height: int) -> None:
    decoded = session.folder / "source_decoded.yuv"
    _decode_raw(session, "decode_source_for_loss", source, decoded, no_deblock=False)
    a, b = raw.read_bytes(), decoded.read_bytes()
    frame_size = width * height * 3 // 2
    session.say("Mat mat do NEN (encoder_input.yuv -> source.h264 -> decode), PSNR-Y tung frame:")
    values = []
    for index in range(min(len(a), len(b)) // frame_size):
        start = index * frame_size
        error = sum((x - y) ** 2 for x, y in zip(a[start:start + width * height], b[start:start + width * height]))
        values.append(math.inf if error == 0 else 10 * math.log10(255 ** 2 * width * height / error))
    session.say("  " + "  ".join(f"#{i}:{v:.2f}dB" for i, v in enumerate(values)))
    session.say("  Day la mat mat cua libx264 (luong tu hoa), KHONG phai do nhung. Phan nhung do rieng o buoc sau.")
    session.report["encode_psnr_y_db"] = [None if math.isinf(v) else v for v in values]


# ------------------------------------------------------ 3. NAL / EBSP / RBSP

def _sei_messages(rbsp: bytes) -> list[tuple[int, bytes]]:
    messages, position = [], 1
    while position < len(rbsp) and rbsp[position] != 0x80:
        payload_type = 0
        while rbsp[position] == 0xFF:
            payload_type += 255
            position += 1
        payload_type += rbsp[position]
        position += 1
        payload_size = 0
        while rbsp[position] == 0xFF:
            payload_size += 255
            position += 1
        payload_size += rbsp[position]
        position += 1
        messages.append((payload_type, rbsp[position:position + payload_size]))
        position += payload_size
    return messages


def nal_anatomy(session, source: Path, trace: dict) -> None:
    data = source.read_bytes()
    session.say("File .h264 Annex-B = chuoi [start code 00 00 01 | 00 00 00 01][NAL header 1 byte][EBSP].")
    session.say("EBSP = RBSP + emulation-prevention byte 0x03 chen sau moi '00 00' de start code khong xuat hien gia.")
    rows, details = trace["nals"], []
    for row in rows:
        start = row["offset"]
        header_at = start + row["start_code_bytes"]
        header = data[header_at]
        # ebsp_bytes counts the payload after the 1-byte NAL header.
        ebsp = data[header_at + 1:header_at + 1 + row["ebsp_bytes"]]
        epb, zeros = [], 0
        for index, byte in enumerate(ebsp):
            if zeros >= 2 and byte == 0x03:
                epb.append(index)
                zeros = 0
                continue
            zeros = zeros + 1 if byte == 0 else 0
        details.append({**row, "header_byte": header, "epb_positions": epb})
    session.save("nal_anatomy.json", details)
    session.say(f"{'NAL':>4} {'offset':>8} start  header    F NRI type  {'loai':16} {'EBSP':>7} {'RBSP':>7} EPB")
    for row in details[:session.args.rows]:
        header = row["header_byte"]
        start_code = "00 00 01" if row["start_code_bytes"] == 3 else "00000001"
        session.say(f"{row['index']:4} {row['offset']:8} {start_code} {header:08b}  {header >> 7}  {header >> 5 & 3}  "
                    f"{header & 31:4}  {NAL_TYPE_NAMES.get(header & 31, '?'):16} {row['ebsp_bytes']:7} "
                    f"{row['rbsp_bytes']:7} {len(row['epb_positions'])}")
    session.say("  header 8 bit = forbidden_zero_bit(1) | nal_ref_idc(2) | nal_unit_type(5)")
    with_epb = next((row for row in details if row["epb_positions"]), None)
    if with_epb:
        offset = with_epb["epb_positions"][0]
        header_at = with_epb["offset"] + with_epb["start_code_bytes"]
        window = data[header_at + 1 + max(0, offset - 4):header_at + 1 + offset + 4]
        session.say(f"  Vi du EPB trong NAL {with_epb['index']} tai byte EBSP {offset}: {window.hex(' ')}")
        session.say("  -> bo byte 03 dung sau '00 00' de co RBSP; bit offset cua parser tinh tren RBSP.")
    first_vcl = next(row for row in details if row["header_byte"] & 31 in (1, 5))
    header_at = first_vcl["offset"] + first_vcl["start_code_bytes"]
    session.say(f"  32 byte dau cua NAL slice {first_vcl['index']}: {data[header_at:header_at + 32].hex(' ')}")
    for row in details:
        if row["header_byte"] & 31 != 6:
            continue
        header_at = row["offset"] + row["start_code_bytes"]
        rbsp = data[header_at:header_at + 1 + row["ebsp_bytes"]].replace(b"\x00\x00\x03", b"\x00\x00")
        try:
            messages = _sei_messages(rbsp)
        except IndexError:
            session.say(f"  SEI NAL {row['index']}: cau truc SEI khong doc duoc, bo qua")
            messages = []
        for payload_type, payload in messages:
            if payload_type == 5 and len(payload) > 16:
                text = payload[16:].split(b"\x00")[0].decode("ascii", "replace")
                session.say(f"  SEI NAL {row['index']}: user_data_unregistered, UUID {payload[:16].hex()}")
                session.say("  libx264 ghi toan bo cau hinh encoder vao day:")
                for line in textwrap.wrap(text, 110):
                    session.say("    " + line)
        break


# ------------------------------------------ 4. FFmpeg's own bitstream tracer

def _parse_trace_headers(log: str) -> list[tuple[str, list[tuple[int, str, str, int]]]]:
    sections: list[tuple[str, list[tuple[int, str, str, int]]]] = []
    for line in log.splitlines():
        section = _SECTION_LINE.search(line.strip())
        if section and "trace_headers" in line and not _TRACE_LINE.search(line):
            sections.append((section.group(1).strip(), []))
            continue
        field = _TRACE_LINE.search(line)
        if field and sections:
            sections[-1][1].append((int(field.group(1)), field.group(2), field.group(3), int(field.group(4))))
    return sections


def library_header_trace(session, source: Path, trace: dict) -> None:
    session.say("FFmpeg co bitstream filter 'trace_headers' (thu vien CBS cua libavcodec): no doc lai SPS/PPS/SEI/")
    session.say("slice header va in tung truong: vi tri bit trong NAL | ten | chuoi bit | gia tri.")
    result = session.run("ffmpeg_trace_headers", ["ffmpeg", "-hide_banner", "-nostdin", "-i", source, "-c:v", "copy",
                                                  "-bsf:v", "trace_headers", "-frames:v", "1", "-f", "null", "-"])
    log = result.stderr.decode("utf-8", errors="replace")
    (session.folder / "ffmpeg_trace_headers.txt").write_text(log, encoding="utf-8")
    sections = _parse_trace_headers(log)
    wanted = ("Sequence Parameter Set", "Picture Parameter Set", "Slice Header")
    for name, fields in sections:
        if name not in wanted:
            continue
        session.say(f"\n  [{name}] ({len(fields)} truong)")
        for position, field_name, bits, value in fields:
            session.say(f"    bit {position:4}  {field_name:42} {bits:>20} = {value}")
        wanted = tuple(item for item in wanted if item != name)
    values = {name: value for _, fields in sections for _, name, _, value in fields}
    slice_info = trace["slices"][0]
    session.check("FFmpeg CBS va parser native cung do rong anh (MB)",
                  values.get("pic_width_in_mbs_minus1", -2) + 1 == slice_info["mb_width"])
    qp = 26 + values.get("pic_init_qp_minus26", 0) + values.get("slice_qp_delta", 0)
    session.check("FFmpeg CBS va parser native cung QP dau slice", qp == slice_info["initial_qp"])
    slice_fields = next((fields for name, fields in sections if name == "Slice Header"), [])
    if slice_fields:
        position, _, bits, _ = slice_fields[-1]
        session.say(f"  Slice header ket thuc o bit {position + len(bits)} cua NAL = bit {position + len(bits) - 8}"
                    f" cua RBSP (bo 8 bit NAL header); native data_bit_offset = {slice_info['data_bit_offset']}.")
        session.check("slice_data bat dau cung vi tri bit", position + len(bits) - 8 == slice_info["data_bit_offset"])
    session.say("  Log day du: ffmpeg_trace_headers.txt")


# ----------------------------------------- 5. FFmpeg decoder MB maps vs native

def _single_access_unit(source: Path, trace: dict, nal_index: int, output: Path) -> None:
    data = source.read_bytes()
    nals = trace["nals"]
    keep = [row for row in nals if row["type"] in (7, 8)][:2] + [nals[nal_index]]
    pieces = []
    for row in keep:
        end = row["offset"] + row["start_code_bytes"] + 1 + row["ebsp_bytes"]
        pieces.append(data[row["offset"]:end])
    output.write_bytes(b"".join(pieces))


def _debug_map(log: str, cell: int) -> list[list[str]]:
    blocks, current, header_pending = [], None, False
    for line in log.splitlines():
        if "[h264 @" not in line:
            continue
        if "New frame" in line:
            current = []
            blocks.append(current)
            header_pending = True  # the next line is the pixel-column ruler, not MB row 0
            continue
        match = re.search(r"\]\s+\d+ (.+)$", line)
        if current is not None and match and header_pending:
            header_pending = False
            continue
        if current is not None and match:
            body = match.group(1)
            current.append([body[i:i + cell].strip() for i in range(0, len(body), cell)])
    return blocks[-1] if blocks else []


def decoder_mb_maps(session, source: Path, trace: dict, detail: dict, qps: dict[int, int]) -> None:
    nal_index = detail["nal_index"]
    unit = session.folder / f"access_unit_nal{nal_index}.h264"
    _single_access_unit(source, trace, nal_index, unit)
    session.say(f"Tach rieng access unit chua NAL {nal_index} (SPS+PPS+IDR) -> {unit.name}, decode 1 thread voi")
    session.say("'-debug mb_type' va '-debug qp': decoder H.264 cua FFmpeg tu in loai/QP tung MB ma no giai ra.")
    types_log = session.run("ffmpeg_debug_mb_type", ["ffmpeg", "-hide_banner", "-nostdin", "-threads", "1", "-debug", "mb_type",
                                                     "-i", unit, "-f", "null", "-"]).stderr.decode("utf-8", "replace")
    qp_log = session.run("ffmpeg_debug_qp", ["ffmpeg", "-hide_banner", "-nostdin", "-threads", "1", "-debug", "qp",
                                             "-i", unit, "-f", "null", "-"]).stderr.decode("utf-8", "replace")
    width = detail["mb_width"]
    ffmpeg_types = _debug_map(types_log, 3)
    ffmpeg_qps = _debug_map(qp_log, 2)
    native_types = {mb["address"]: ("i" if mb["mb_type"] == 0 else "I") for mb in detail["macroblocks"]}
    type_matches = qp_matches = total = 0
    session.say(f"  {'FFmpeg mb_type (i=I4x4, I=I16x16)':{width + 4}}   native parser")
    for y, row in enumerate(ffmpeg_types):
        native_row = "".join(native_types.get(y * width + x, "?") for x in range(width))
        session.say(f"  {''.join(cell[:1] for cell in row):{width + 4}}   {native_row}")
        for x, cell in enumerate(row[:width]):
            total += 1
            type_matches += cell[:1] == native_types.get(y * width + x)
            if y < len(ffmpeg_qps) and x < len(ffmpeg_qps[y]) and ffmpeg_qps[y][x].isdigit():
                qp_matches += int(ffmpeg_qps[y][x]) == qps.get(y * width + x)
    session.say(f"  Loai MB khop: {type_matches}/{total}; QP_Y khop: {qp_matches}/{total}")
    session.check("decoder FFmpeg va parser native cung loai MB", total > 0 and type_matches == total)
    session.check("decoder FFmpeg va QP tinh tu mb_qp_delta trung nhau", total > 0 and qp_matches == total)


# ------------------------------------------------- 6. one block, end to end

def _print_fields(session, fields: list[hx.Field], embedded_bit: int | None = None) -> None:
    session.say(f"    {'bit':>6} {'len':>3}  {'chuoi bit':22} phan tu = gia tri")
    for item in fields:
        mark = "  <== BIT NHUNG" if embedded_bit is not None and item.start == embedded_bit else ""
        session.say(f"    {item.start:6} {len(item.bits):3}  {item.bits:22} {item.name} = {item.value}"
                    f"{'  (' + item.note + ')' if item.note else ''}{mark}")


def _coeff_token_table(n_c: int):
    from src import h264_tables as cavlc
    if n_c == -1:
        return cavlc.COEFF_TOKEN_CHROMA_DC, "ChromaDC (nC=-1)"
    if n_c < 2:
        return cavlc.COEFF_TOKEN_NC_0_1, "0<=nC<2"
    if n_c < 4:
        return cavlc.COEFF_TOKEN_NC_2_3, "2<=nC<4"
    if n_c < 8:
        return cavlc.COEFF_TOKEN_NC_4_7, "4<=nC<8"
    return None, "nC>=8 (ma co dinh 6 bit)"


def _macroblock_detail(session, tool: Path, video: Path, nal: int, address: int, label: str) -> dict:
    result = session.run(label, [tool, video, "--macroblock", nal, address])
    detail = json.loads(result.stdout)
    session.save(label + ".json", detail)
    return detail


def block_anatomy(session, tool: Path, source: Path, stego: Path, trace: dict, exemplar, raw_input: Path,
                  width: int, height: int) -> None:
    from src import h264_tables as cavlc

    if exemplar is None or exemplar.category != 1:
        session.say("Khong co block Luma4x4 bi lat trong clip nay; bo qua phan giai phau block.")
        return
    nal, address, blk = exemplar.nal_index, exemplar.macroblock_address, exemplar.block_index
    before = _macroblock_detail(session, tool, source, nal, address, "mb_detail_before")
    after = _macroblock_detail(session, tool, stego, nal, address, "mb_detail_after")
    mb = next(item for item in before["macroblocks"] if item["address"] == address)
    if mb["mb_type"] != 0:
        session.say("Block vi du nam trong MB I16x16 (DC tach rieng qua Hadamard); chi giai phau chi tiet MB I4x4.")
        return
    mb_width = before["mb_width"]
    rbsp_before, rbsp_after = bytes.fromhex(before["rbsp_hex"]), bytes.fromhex(after["rbsp_hex"])
    slice_qp = before["pic_init_qp"] + before["slice_qp_delta"]
    qps = hx.macroblock_qps(before["macroblocks"], slice_qp)
    vcl = [row["index"] for row in trace["nals"] if row["type"] in (1, 5)]
    frame = vcl.index(nal)
    mb_x, mb_y = address % mb_width, address // mb_width
    bx, by = hx.block_xy(blk)
    x0, y0 = mb_x * 16 + bx * 4, mb_y * 16 + by * 4
    if (mb_x + 1) * 16 > width or (mb_y + 1) * 16 > height:
        # Cropped output (size not a multiple of 16): this MB is partly outside the decoded picture.
        session.say(f"MB {address} nam o vung bi crop (anh {width}x{height}); bo qua phan giai phau block.")
        return

    session.say(f"Block duoc chon: NAL {nal} (frame #{frame}), MB {address} = (cot {mb_x}, hang {mb_y}),"
                f" luma4x4BlkIdx {blk} = 4x4 thu ({bx},{by}) trong MB -> pixel ({x0},{y0}).")
    session.say("Thu tu block trong MB la zig-zag theo 8x8:  0 1 4 5 / 2 3 6 7 / 8 9 12 13 / 10 11 14 15")

    session.say(f"\n[0] Doi chieu toan frame #{frame} voi decoder H.264 cua FFmpeg")
    decoder_mb_maps(session, source, trace, before, qps)

    session.say(f"\n[a] Header MB {address}: doc lai tung truong tu RBSP (bit {mb['start_bit']}..{mb['residual_bit']})")
    reader = hx.TracingBitReader(rbsp_before, mb["start_bit"])
    header = hx.parse_i_macroblock_header(reader)
    _print_fields(session, reader.fields)
    native_cbp = mb["cbp"] & 15 | (min(mb["cbp"] >> 4, 2) << 4)  # native stores chroma CBP 2 as 3
    session.check("Python doc header MB khop parser native",
                  reader.position == mb["residual_bit"] and header["cbp"] == native_cbp
                  and header["rem_intra4x4"] == mb["rem_intra4x4"])

    session.say("\n[b] Intra4x4PredMode: mode du doan = min(mode block trai A, block tren B), DC(2) neu thieu A/B;")
    session.say("    co prev_flag=1 -> dung mode du doan, nguoc lai rem<pred ? rem : rem+1.")
    modes = hx.derive_intra4x4_modes(before["macroblocks"], mb_width)
    grid = [[modes[address][hx.block_index(x, y)].mode for x in range(4)] for y in range(4)]
    for y in range(4):
        session.say("    " + " | ".join(f"{hx.INTRA4x4_MODE_NAMES[mode][:19]:19}" for mode in grid[y]))
    derivation = modes[address][blk]
    session.say(f"    Block {blk}: A={derivation.left}, B={derivation.top}, du doan={derivation.predicted},"
                f" rem={derivation.rem} -> mode {derivation.mode} {hx.INTRA4x4_MODE_NAMES[derivation.mode]}")

    block_before = next(b for b in before["detail"]["blocks"] if b["category"] == "Luma4x4" and b["index"] == blk)
    block_after = next(b for b in after["detail"]["blocks"] if b["category"] == "Luma4x4" and b["index"] == blk)
    table, table_name = _coeff_token_table(block_before["n_c"])
    session.say(f"\n[c] CAVLC cua block (bit {block_before['coeff_token_bit']}..{block_before['end_bit']}),"
                f" nC={block_before['n_c']} -> bang coeff_token {table_name}")
    session.say("    nC = trung binh TotalCoeff cua block trai va tren (lam tron len); chon bang VLC phu hop.")
    if table is None:
        session.say("    nC>=8: coeff_token la 6 bit co dinh 'xxxxyy' = (TotalCoeff-1, TrailingOnes); '000011' = khong co he so.")
    agreed = True
    for label, rbsp, block in (("TRUOC", rbsp_before, block_before), ("SAU", rbsp_after, block_after)):
        session.say(f"    -- {label} khi nhung --")
        # Raises if the independent re-read does not end exactly at the native end bit.
        fields = hx.segment_cavlc_block(rbsp, block, table, 16, cavlc.TOTAL_ZEROS_TABLES, cavlc.RUN_BEFORE_TABLES)
        _print_fields(session, fields, exemplar.rbsp_bit_offset)
        levels = [item.value for item in fields if item.name.startswith("level[")]
        signs = [-1 if item.value else 1 for item in fields if item.name.startswith("trailing_ones_sign")]
        agreed = agreed and levels == block["level_values"] and signs == block["trailing_one_values"]
    session.check("Python doc lai CAVLC khop level/dau T1 cua parser native", agreed)
    session.say("    Level giai theo thu tu NGUOC scan (tan so cao truoc); dau T1 dung ngay sau coeff_token.")
    session.say("    Lat dau T1 chi doi 1 bit, khong doi do dai ma -> TotalCoeff/nC/vi tri cac block sau giu nguyen.")

    coefficients = [hx.scan_to_matrix(block_before["coefficients_scan"]),
                    hx.scan_to_matrix(block_after["coefficients_scan"])]
    session.say(f"\n[d] He so luong tu: scan zig-zag {block_before['coefficients_scan']}")
    order = [[0] * 4 for _ in range(4)]
    for scan_position, raster in enumerate(hx.ZIGZAG_4x4):
        order[raster // 4][raster % 4] = scan_position
    session.say("    thu tu quet zig-zag (so = vi tri trong danh sach scan):")
    show_matrices(session, ["zig-zag"], [order], 3)
    session.say("    dat nguoc zig-zag vao ma tran 4x4 (hang = tan so doc, cot = tan so ngang):")
    show_matrices(session, ["c truoc", "c sau", "delta c"], coefficients + [_difference(*coefficients)], 5)

    qp = qps[address]
    session.say(f"\n[e] QP_Y cua MB = pic_init_qp {before['pic_init_qp']} + slice_qp_delta {before['slice_qp_delta']}"
                f" + tong mb_qp_delta = {qp}  (qP/6={qp // 6}, qP%6={qp % 6})")
    session.say("    Dequant 8.5.12.1: d = c * LevelScale(qP%6,i,j) " +
                (f"<< {qp // 6 - 4}" if qp >= 24 else f"+ 2^{3 - qp // 6} >> {4 - qp // 6}"))
    scaled = [hx.dequantize(matrix, qp) for matrix in coefficients]
    show_matrices(session, ["LevelScale", "d truoc", "d sau"], [hx.level_scale_matrix(qp)] + scaled, 6)

    session.say("\n[f] Bien doi nguyen nguoc 4x4 (8.5.12.2): tung hang, roi tung cot, r = (h + 32) >> 6")
    session.say("    1D: e0=d0+d2 e1=d0-d2 e2=(d1>>1)-d3 e3=d1+(d3>>1); f=[e0+e3, e1+e2, e1-e2, e0-e3]")
    transforms = [hx.inverse_transform(matrix) for matrix in scaled]
    show_matrices(session, ["sau bien doi hang", "sau bien doi cot", "residual r truoc"], list(transforms[0]), 6)
    residuals = [transforms[0][2], transforms[1][2]]
    show_matrices(session, ["residual truoc", "residual sau", "delta residual"],
                  residuals + [_difference(*residuals)], 5)

    session.say("\n[g] Du doan intra tu mau lan can CHUA deblock (decode FFmpeg -skip_loop_filter all)")
    planes = []
    for label, video in (("nodeblock_before", source), ("nodeblock_after", stego)):
        path = session.folder / f"{label}.yuv"
        if not path.is_file():
            _decode_raw(session, label, video, path, no_deblock=True)
        planes.append(_luma_plane(path, width, height, frame))
    predictions, reconstructions = [], []
    for index, plane in enumerate(planes):
        neighbours = hx.gather_neighbours(plane, width, height, mb_width, address, blk)
        if index == 0:
            session.say(f"    p[-1,-1]={neighbours.top[0]}  p[0..7,-1]={neighbours.top[1:]}  p[-1,0..3]={neighbours.left}")
            for note in neighbours.notes:
                session.say(f"    ({note})")
        predictions.append(hx.predict_intra4x4(derivation.mode, neighbours))
        reconstructions.append(hx.clip_add(predictions[-1], residuals[index]))
    actual = [_plane_block(plane, width, x0, y0) for plane in planes]
    show_matrices(session, [f"du doan ({hx.INTRA4x4_MODE_NAMES[derivation.mode]})", "+ residual", "= tai tao (clip 0..255)"],
                  [predictions[0], residuals[0], reconstructions[0]], 5)
    show_matrices(session, ["FFmpeg decode (no deblock)", "tai tao Python"], [actual[0], reconstructions[0]], 5)
    session.check("Python tinh pixel TRUOC nhung khop FFmpeg tung mau", reconstructions[0] == actual[0])
    session.check("Python tinh pixel SAU nhung khop FFmpeg tung mau", reconstructions[1] == actual[1])
    delta_pred, delta_res = _difference(*predictions), _difference(*residuals)
    show_matrices(session, ["delta pixel", "= delta du doan", "+ delta residual"],
                  [_difference(*actual), delta_pred, delta_res], 5)
    session.say("    delta du doan != 0 nghia la block truoc do (theo thu tu giai ma) cung bi lat -> anh huong lan truyen.")

    session.say("\n[h] Deblocking filter (ap sau khi tai tao ca frame) lam min bien block:")
    filtered = [_plane_block(_luma_plane(session.folder / name, width, height, frame), width, x0, y0)
                for name in ("before.yuv", "after.yuv")]
    show_matrices(session, ["sau deblock truoc", "sau deblock sau", "deblock - no deblock"],
                  filtered + [_difference(actual[0], filtered[0])], 5)

    session.say("\n[i] Chieu thuan (phia encoder, minh hoa): anh goc -> residual -> bien doi -> luong tu")
    original = _plane_block(_luma_plane(raw_input, width, height, frame), width, x0, y0)
    residual_true = _difference(predictions[0], original)
    forward = hx.forward_transform(residual_true)
    quantized = hx.quantize_intra(forward, qp)
    show_matrices(session, ["X goc (encoder_input)", "e = X - du doan", "W = Cf e Cf^T"],
                  [original, residual_true, forward], 6)
    agree = sum(quantized[r][c] == coefficients[0][r][c] for r in range(4) for c in range(4))
    show_matrices(session, ["Z luong tu sach giao khoa", "c thuc te trong bitstream"], [quantized, coefficients[0]], 5)
    session.say(f"    Khop {agree}/16 vi tri. x264 con dung deadzone/trellis/psy-RD nen co the khac cong thuc co ban;")
    session.say("    gia tri trong bitstream moi la su that, gia tri tren chi giai thich nguon goc cua he so.")
    session.say("    Cf = [[1,1,1,1],[2,1,-1,-2],[1,-1,-1,1],[1,-2,2,-1]]; MF va qbits=15+qP/6 theo bang chuan.")

    session.say(f"\n[j] 16x16 mau Y cua MB {address} (FFmpeg, chua deblock, truoc nhung); [..] = block {blk}:")
    for row in range(16):
        cells = []
        for col in range(16):
            value = planes[0][(mb_y * 16 + row) * width + mb_x * 16 + col]
            inside = bx * 4 <= col < bx * 4 + 4 and by * 4 <= row < by * 4 + 4
            cells.append(f"[{value:3}]" if inside else f" {value:3} ")
        session.say("    " + "".join(cells))
    session.report["block_anatomy"] = {"nal": nal, "macroblock": address, "block": blk, "qp": qp,
                                       "mode": hx.INTRA4x4_MODE_NAMES[derivation.mode],
                                       "forward_quant_agreement": agree}


# --------------------------------------- 7. where the embedded bit lives

def file_offset_of_rbsp_bit(data: bytes, nal_row: dict, rbsp_bit: int) -> tuple[int, int]:
    """Map an RBSP bit (NAL header excluded) to (file byte offset, EPBs skipped before it)."""
    payload_start = nal_row["offset"] + nal_row["start_code_bytes"] + 1
    target, rbsp_index, zeros, skipped = rbsp_bit // 8, 0, 0, 0
    for ebsp_index in range(nal_row["ebsp_bytes"]):
        byte = data[payload_start + ebsp_index]
        if zeros >= 2 and byte == 0x03:
            zeros, skipped = 0, skipped + 1
            continue
        if rbsp_index == target:
            return payload_start + ebsp_index, skipped
        zeros = zeros + 1 if byte == 0 else 0
        rbsp_index += 1
    raise ValueError("RBSP bit lies outside its NAL")


def frame_field(bit_index: int, message_bytes: int) -> str:
    byte = bit_index // 8
    proof_fields = (("A.x", 32), ("B.x.c0", 32), ("B.x.c1", 32), ("C.x", 32), ("co dau y", 1))
    if byte == 0:
        return "version khung (0x03)"
    if byte < 3:
        return "do dai payload (2 byte)"
    offset = byte - 3
    if offset < 4:
        return ("payload: format (0x01)", "payload: che do binding (0 = video)",
                "payload: message_length byte 0", "payload: message_length byte 1")[offset]
    offset -= 4
    if offset < message_bytes:
        return f"payload: message byte {offset}"
    offset -= message_bytes
    for name, size in proof_fields:
        if offset < size:
            return f"payload: proof {name} byte {offset}"
        offset -= size
    return f"ngoai khung (byte {offset})"


def embedded_bit_location(session, source: Path, stego: Path, before: dict, after: dict, exemplar,
                          placements: list, bits: list[int], max_bits: int, message_bytes: int, key: bytes,
                          width: int, height: int, ascii_frame) -> None:
    """Follow the exemplar from its segment and key-dependent rank to file bytes and payload meaning.

    ``placements`` is the segment schedule (``segment_schedule``) in frame-bit order and
    ``bits`` are the embedded (whitened) bits: frame bit XOR keystream bit.
    """
    from src.native_blind_contract import score_candidate, whitening_keystream_bits

    if exemplar is None:
        return
    placement = next(p for p in placements if p.candidate.nal_index == exemplar.nal_index
                     and p.candidate.rbsp_bit_offset == exemplar.rbsp_bit_offset)
    segment = placement.segment
    in_segment = [p for p in placements if p.segment == segment]
    rank = in_segment.index(placement)
    order = placement.frame_bit_index
    identity = placement.candidate.identity.serialize().decode()
    session.say(f"Ung vien trong file: '{exemplar.serialize().decode()}' (nal:mb:category:block:rbsp_bit) thuoc"
                f" segment {segment} = SPS + PPS + IDR NAL {exemplar.nal_index}.")
    session.say(f"Dinh danh TRONG segment: '{identity}' (NAL index tinh tren analysis input SPS+PPS+IDR,"
                f" = {placement.candidate.identity.nal_index}); schedule cham diem dinh danh nay.")
    session.say("schedule_key = HKDF-Expand(PRK, 'zkstego/cavlc/v2/schedule', 32),"
                " PRK = HMAC-SHA256(b'zkstego-cavlc-v2-salt', secret)")
    session.say(f"score = HMAC-SHA256(schedule_key, '{identity}') = {score_candidate(placement.candidate.identity, key).hex()}")
    session.say(f"Segment {segment}: sap xep moi candidate theo (score, dinh danh), lay min({max_bits}, so candidate);"
                f" ung vien nay dung hang {rank}.")
    session.say(f"Segment {segment} mang frame bits [{in_segment[0].frame_bit_index}, {in_segment[-1].frame_bit_index + 1})"
                f" (cac segment truoc da mang {in_segment[0].frame_bit_index} bit)"
                f" -> chi so frame bit = {in_segment[0].frame_bit_index} + {rank} = {order}")
    keystream_bit = whitening_keystream_bits(key, 1, order)[0]
    frame_bit = bits[order] ^ keystream_bit
    session.say(f"-> mang bit thu {order} cua khung = byte {order // 8}, bit {7 - order % 8} (MSB truoc); frame bit = {frame_bit}")
    session.say(f"-> frame bit nay thuoc: {frame_field(order, message_bytes)}")
    session.say(f"-> keystream bit {order} = HMAC-SHA256(whitening_key, uint64_be({order // 256}))"
                f" byte {order % 256 // 8}, bit {7 - order % 8} (MSB truoc) = {keystream_bit}")
    session.say(f"-> bit ghi vao file = frame bit XOR keystream bit = {frame_bit} ^ {keystream_bit} = {bits[order]}")
    rows = []
    for label, video, trace in (("source", source, before), ("stego", stego, after)):
        data = video.read_bytes()
        nal_row = trace["nals"][exemplar.nal_index]
        offset, skipped = file_offset_of_rbsp_bit(data, nal_row, exemplar.rbsp_bit_offset)
        rows.append((label, data, offset, skipped, nal_row))
    session.say(f"Vi tri vat ly: RBSP bit {exemplar.rbsp_bit_offset} = RBSP byte {exemplar.rbsp_bit_offset // 8},"
                f" bit {7 - exemplar.rbsp_bit_offset % 8} (tinh tu MSB) cua NAL {exemplar.nal_index}")
    bit_in_byte = exemplar.rbsp_bit_offset % 8
    for label, data, offset, skipped, nal_row in rows:
        window = data[offset - 4:offset + 5]
        session.say(f"  {label:6}: NAL bat dau o byte {nal_row['offset']}, {skipped} EPB dung truoc -> byte file {offset}")
        session.say(f"          hex quanh do: {window[:4].hex(' ')} [{data[offset]:02x}] {window[5:].hex(' ')}")
        bits_text = f"{data[offset]:08b}"
        session.say(f"          byte {data[offset]:02x} = {bits_text[:bit_in_byte]}[{bits_text[bit_in_byte]}]{bits_text[bit_in_byte + 1:]}")
    def bit_at(row: tuple) -> int:
        return (row[1][row[2]] >> (7 - bit_in_byte)) & 1

    session.say(f"  bit goc trong source = {bit_at(rows[0])}, bit trong stego = {bit_at(rows[1])},"
                f" bit can ghi = frame {frame_bit} XOR keystream {keystream_bit} = {frame_bit ^ keystream_bit}")
    session.check("bit trong file source khop trace native", bit_at(rows[0]) == exemplar_bit(before, exemplar))
    session.check("bit trong file stego = frame bit XOR keystream bit", bit_at(rows[1]) == frame_bit ^ keystream_bit)
    session.check("bit trong file source = sign bit ma --segments liet ke", bit_at(rows[0]) == placement.candidate.bit)

    vcl = [row["index"] for row in before["nals"] if row["type"] in (1, 5)]
    frame = vcl.index(exemplar.nal_index)
    mb_width = next(row["mb_width"] for row in before["slices"] if row["nal_index"] == exemplar.nal_index)
    plane = _luma_plane(session.folder / "before.yuv", width, height, frame)
    session.say(f"Vi tri tren frame #{frame} (ASCII, 'X' = MB {exemplar.macroblock_address} chua block vi du):")
    for line in frame_with_marker(plane, width, height, mb_width, exemplar.macroblock_address, ascii_frame):
        session.say("    " + line)


def exemplar_bit(trace: dict, exemplar) -> int:
    for row in trace["candidates"]:
        if tuple(row["id"]) == (exemplar.nal_index, exemplar.macroblock_address, exemplar.category,
                                exemplar.block_index, exemplar.rbsp_bit_offset):
            return row["bit"]
    raise KeyError("exemplar is not a candidate of this trace")


def frame_with_marker(plane: bytes, width: int, height: int, mb_width: int, address: int, ascii_frame) -> list[str]:
    """ASCII frame with the exemplar macroblock replaced by 'X' characters."""
    lines = [list(line) for line in ascii_frame(plane, width, height)]
    rows, cols = len(lines), len(lines[0])
    mb_x, mb_y = address % mb_width, address // mb_width
    x0, x1 = mb_x * 16 * cols // width, max(mb_x * 16 * cols // width + 1, (mb_x + 1) * 16 * cols // width)
    y0, y1 = mb_y * 16 * rows // height, max(mb_y * 16 * rows // height + 1, (mb_y + 1) * 16 * rows // height)
    for y in range(y0, min(y1, rows)):
        for x in range(x0, min(x1, cols)):
            lines[y][x] = "X"
    return ["".join(line) for line in lines]
