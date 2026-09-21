"""
pipeline.py — Core H.264 IDR extraction pipeline.

Parses an H.264 video, extracts all IDR frame coefficients and their
exact bit offsets, and provides bit-level extraction from a stego video.

Public API:
    extract_all_idr_blocks(video_path, reconstructor)
        → (coefficients, frame_verified_data, nC_map, nal_length_map, t1_override_map)

    extract_bits_direct(stego_video_path, embed_safe_positions, ...)
        → bytes
"""

import os
import tempfile
from pathlib import Path

from ..bitstream.h264          import H264BitstreamParser, TraceableCAVLCParser, iter_annex_b_nal_units
from ..bitstream.bitstream_ops import BitstreamReconstructor, BitstreamPatcher, BitArray
from ..bitstream.bitstream_io  import BitstreamReader
from ..bitstream.cavlc         import CAVLCDecoder
from .stego                    import sort_blocks_interleaved, _CIF_MB_COUNT


def iter_idr_slices(video_path: str, reconstructor: BitstreamReconstructor):
    """Yield IDR NALs with their active parameter sets and global MB offset.

    The iterator updates SPS/PPS context as it walks Annex-B data and keeps no
    historical IDR/NAL collection.  It is intentionally a small, stateless
    primitive for the later streaming metadata and patch passes.
    """
    sps = pps = None
    mb_count_per_slice: int | None = None
    global_mb_idx = 0
    for nal in iter_annex_b_nal_units(video_path):
        nal_type = int(nal.nal_unit_type)
        if nal_type == 7:
            sps = reconstructor._parse_sps_from_nal(nal)
            mb_count_per_slice = (
                (sps.pic_width_in_mbs_minus1 + 1) *
                (sps.pic_height_in_map_units_minus1 + 1)
            )
        elif nal_type == 8:
            pps = reconstructor._parse_pps_from_nal(nal)
        elif nal_type == 5:
            if sps is None or pps is None or mb_count_per_slice is None:
                raise RuntimeError("IDR encountered before a usable SPS/PPS context")
            yield nal, sps, pps, global_mb_idx
            global_mb_idx += mb_count_per_slice
        elif nal_type == 1:
            if mb_count_per_slice is None:
                raise RuntimeError("non-IDR slice encountered before SPS context")
            global_mb_idx += mb_count_per_slice


def iter_idr_trace_results(
    video_path: str,
    reconstructor: BitstreamReconstructor,
    *,
    traceable_factory=TraceableCAVLCParser,
):
    """Decode and yield one IDR trace result at a time.

    Consumers own the yielded result and should release it before advancing the
    iterator when operating under an edge-memory budget.  The factory seam is
    intentional: it keeps the streaming offset contract independently testable.
    """
    for nal, sps, pps, global_mb_idx in iter_idr_slices(video_path, reconstructor):
        traceable = traceable_factory()
        result = traceable.extract_with_offsets(
            nal,
            sps,
            pps,
            global_mb_idx=global_mb_idx,
        )
        yield nal, sps, pps, global_mb_idx, result


def patch_selected_sign_positions_streaming(
    video_path: str,
    output_path: str,
    position_bits: dict[tuple[int, int, int], int],
    *,
    reconstructor: BitstreamReconstructor | None = None,
    traceable_factory=TraceableCAVLCParser,
    patcher_factory=BitstreamPatcher,
) -> dict[str, int]:
    """Patch pre-selected CAVLC trailing-one signs one IDR slice at a time.

    ``position_bits`` maps global ``(macroblock, block, ~coefficient_index)``
    tuples to bits. The function retains only one trace result and one NAL at a
    time, writes to a temporary sibling file, and atomically publishes output
    only after every selected position was either already in the requested
    state or was confirmed as patched. It deliberately rejects non-sign and
    duplicate-block requests.
    """
    source = Path(video_path)
    destination = Path(output_path)
    if not source.is_file():
        raise FileNotFoundError(f"video not found: {video_path}")
    if not position_bits:
        raise ValueError("position_bits must not be empty")

    selected_by_mb: dict[int, list[tuple[int, int, int]]] = {}
    selected_blocks: set[tuple[int, int]] = set()
    for raw_position, raw_bit in position_bits.items():
        if len(raw_position) != 3:
            raise ValueError("each selected position must contain macroblock, block, and coefficient")
        mb_idx, block_idx, coefficient_idx = (int(value) for value in raw_position)
        bit = int(raw_bit)
        if coefficient_idx >= 0:
            raise ValueError("streaming blind patcher accepts CAVLC sign positions only")
        if bit not in (0, 1):
            raise ValueError("each payload bit must be 0 or 1")
        block_key = (mb_idx, block_idx)
        if block_key in selected_blocks:
            raise ValueError("streaming blind patcher accepts at most one position per block")
        selected_blocks.add(block_key)
        selected_by_mb.setdefault(mb_idx, []).append((block_idx, coefficient_idx, bit))

    active_reconstructor = reconstructor or BitstreamReconstructor()
    patcher = patcher_factory()
    sps = pps = None
    mb_count_per_slice: int | None = None
    global_mb_idx = 0
    idr_slices = 0
    satisfied_positions: set[tuple[int, int, int]] = set()
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=".zkstego-stream-",
        suffix=".h264",
        dir=destination.parent,
        delete=False,
    )
    temporary_path = Path(handle.name)

    def write_nal(nal) -> None:
        start_code = b"\x00\x00\x01" if getattr(nal, "start_code_size", 4) == 3 else b"\x00\x00\x00\x01"
        header = (
            (int(nal.forbidden_zero_bit) << 7)
            | (int(nal.nal_ref_idc) << 5)
            | int(nal.nal_unit_type)
        )
        handle.write(start_code)
        handle.write(bytes([header]))
        handle.write(active_reconstructor._add_emulation_prevention(nal.rbsp_byte))

    try:
        for nal in iter_annex_b_nal_units(str(source)):
            nal_type = int(nal.nal_unit_type)
            if nal_type == 7:
                sps = active_reconstructor._parse_sps_from_nal(nal)
                mb_count_per_slice = (
                    (sps.pic_width_in_mbs_minus1 + 1)
                    * (sps.pic_height_in_map_units_minus1 + 1)
                )
                write_nal(nal)
                continue
            if nal_type == 8:
                pps = active_reconstructor._parse_pps_from_nal(nal)
                write_nal(nal)
                continue
            if nal_type != 5:
                write_nal(nal)
                if nal_type == 1:
                    if mb_count_per_slice is None:
                        raise RuntimeError("non-IDR slice encountered before SPS")
                    global_mb_idx += mb_count_per_slice
                continue
            if sps is None or pps is None or mb_count_per_slice is None:
                raise RuntimeError("IDR encountered before usable SPS/PPS")

            positions_in_slice = [
                (mb_global, positions)
                for mb_global, positions in selected_by_mb.items()
                if global_mb_idx <= mb_global < global_mb_idx + mb_count_per_slice
            ]
            if not positions_in_slice:
                write_nal(nal)
                idr_slices += 1
                global_mb_idx += mb_count_per_slice
                continue

            trace = traceable_factory().extract_with_offsets(
                nal, sps, pps, global_mb_idx=global_mb_idx)
            blocks = trace.get("blocks", {})
            offsets = trace.get("offsets", {})
            modifications: list[tuple[int, int, list[int]]] = []
            for mb_global, positions in positions_in_slice:
                local_mb = mb_global - global_mb_idx
                for block_idx, coefficient_idx, bit in positions:
                    local_key = (local_mb, block_idx)
                    coefficients = blocks.get(local_key)
                    if coefficients is None or local_key not in offsets:
                        continue
                    real_index = ~coefficient_idx
                    if real_index < 1 or real_index >= len(coefficients):
                        continue
                    original = int(coefficients[real_index])
                    if original == 0:
                        continue
                    requested_position = (mb_global, block_idx, coefficient_idx)
                    replacement = abs(original) if bit == 0 else -abs(original)
                    if replacement == original:
                        satisfied_positions.add(requested_position)
                        continue
                    modified = list(coefficients)
                    modified[real_index] = replacement
                    modifications.append((mb_global, block_idx, modified))

            output_nal = nal
            if modifications:
                output_nal = patcher.patch_slice(
                    nal,
                    modifications,
                    sps=sps,
                    pps=pps,
                    global_mb_offset=global_mb_idx,
                    pre_computed_offsets=offsets,
                    pre_computed_blocks=blocks,
                )
                applied_blocks = {
                    (int(mb_idx), int(block_idx))
                    for mb_idx, block_idx in getattr(output_nal, "applied_block_keys", [])
                }
                for mb_idx, block_idx, _coefficients in modifications:
                    position = next(
                        (position for position in position_bits if position[:2] == (mb_idx, block_idx)),
                        None,
                    )
                    if position is not None and (mb_idx, block_idx) in applied_blocks:
                        satisfied_positions.add(position)
            write_nal(output_nal)
            idr_slices += 1
            global_mb_idx += mb_count_per_slice

        handle.close()
        if len(satisfied_positions) != len(position_bits):
            missing = len(position_bits) - len(satisfied_positions)
            raise RuntimeError(f"streaming CAVLC patch did not apply {missing} selected positions")
        os.replace(temporary_path, destination)
    except Exception:
        handle.close()
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    return {
        "idr_slices": idr_slices,
        "selected_positions": len(position_bits),
        "applied_positions": len(satisfied_positions),
    }


def extract_selected_sign_bits_streaming(
    video_path: str,
    positions: list[tuple[int, int, int]],
    *,
    reconstructor: BitstreamReconstructor | None = None,
    traceable_factory=TraceableCAVLCParser,
) -> bytes:
    """Extract sign bits in caller-provided schedule order without a sidecar.

    The schedule must contain exactly one sign position per block. Each IDR is
    traced and released independently; missing or no-longer-nonzero positions
    are a hard error because returning a shifted partial payload would make
    proof verification diagnostically ambiguous.
    """
    if not positions:
        raise ValueError("positions must not be empty")
    requested: list[tuple[int, int, int]] = []
    seen_blocks: set[tuple[int, int]] = set()
    for raw_position in positions:
        if len(raw_position) != 3:
            raise ValueError("each position must contain macroblock, block, and coefficient")
        mb_idx, block_idx, coefficient_idx = (int(value) for value in raw_position)
        if coefficient_idx >= 0:
            raise ValueError("streaming blind extractor accepts CAVLC sign positions only")
        block_key = (mb_idx, block_idx)
        if block_key in seen_blocks:
            raise ValueError("streaming blind extractor accepts at most one position per block")
        seen_blocks.add(block_key)
        requested.append((mb_idx, block_idx, coefficient_idx))

    remaining = set(requested)
    extracted: dict[tuple[int, int, int], int] = {}
    active_reconstructor = reconstructor or BitstreamReconstructor()
    for _idr_offset, coefficients, _n_c_map, _nal_lengths, _frame_data in iter_idr_luma_analysis(
        video_path,
        active_reconstructor,
        traceable_factory=traceable_factory,
    ):
        coefficient_map = {
            (int(mb_idx), int(block_idx)): values
            for mb_idx, block_idx, values in coefficients
        }
        for position in tuple(remaining):
            mb_idx, block_idx, coefficient_idx = position
            values = coefficient_map.get((mb_idx, block_idx))
            if values is None:
                continue
            real_index = ~coefficient_idx
            if real_index < 1 or real_index >= len(values):
                continue
            value = int(values[real_index])
            if value == 0:
                continue
            extracted[position] = 0 if value > 0 else 1
            remaining.remove(position)
        if not remaining:
            break

    if remaining:
        raise RuntimeError(f"streaming CAVLC extraction could not recover {len(remaining)} selected positions")
    bits = [extracted[position] for position in requested]
    padded = bits + [0] * ((8 - len(bits) % 8) % 8)
    return bytes(
        sum(padded[offset + bit_index] << (7 - bit_index) for bit_index in range(8))
        for offset in range(0, len(padded), 8)
    )


def iter_idr_luma_analysis(
    video_path: str,
    reconstructor: BitstreamReconstructor,
    *,
    traceable_factory=TraceableCAVLCParser,
):
    """Yield the CAVLC analysis needed for one IDR slice at a time.

    Each record is ``(idr_offset, coefficients, n_c_map, nal_length_map,
    frame_verified_data)``.  Keys are global macroblock coordinates, matching
    the legacy full-video analysis contract, while all maps are bounded to the
    yielded IDR.  The caller must release each record before advancing to keep
    memory bounded.
    """
    for nal, _sps, _pps, idr_offset, result in iter_idr_trace_results(
        video_path,
        reconstructor,
        traceable_factory=traceable_factory,
    ):
        blocks = result.get("blocks", {})
        offsets = result.get("offsets", {})
        coefficients = []
        for (local_mb, block_idx), values in sorted(blocks.items()):
            if block_idx < 16 and any(value != 0 for value in values):
                coefficients.append((idr_offset + int(local_mb), int(block_idx), list(values)))

        global_offsets = {
            (idr_offset + int(local_mb), int(block_idx)): value
            for (local_mb, block_idx), value in offsets.items()
        }
        global_blocks = {
            (idr_offset + int(local_mb), int(block_idx)): value
            for (local_mb, block_idx), value in blocks.items()
        }
        n_c_map = {}
        nal_length_map = {}
        for (local_mb, block_idx), offset_data in offsets.items():
            if block_idx >= 16:
                continue
            global_key = (idr_offset + int(local_mb), int(block_idx))
            if "nC" in offset_data:
                n_c_map[global_key] = int(offset_data["nC"])
            if "bit_length" in offset_data:
                nal_length_map[global_key] = int(offset_data["bit_length"])

        frame_verified_data = {
            idr_offset: (global_offsets, global_blocks, nal.rbsp_byte),
        }
        yield idr_offset, coefficients, n_c_map, nal_length_map, frame_verified_data

def extract_all_idr_blocks(video_path: str, reconstructor: BitstreamReconstructor,
                            verbose: bool = False,
                            parser: H264BitstreamParser | None = None):
    """
    Parse ALL IDR NAL units from video_path using TraceableCAVLCParser.

    Returns
    -------
    coefficients       : list[(mb_global, blk_idx, coeffs)]
    frame_verified_data: {idr_mb_offset: (global_offsets, global_blocks, rbsp_bytes)}
    nC_map             : {(mb_global, blk_idx): nC}
    nal_length_map     : {(mb_global, blk_idx): bit_length}
    t1_override_map    : {(mb_global, blk_idx): trailing_ones_override}
    """
    if parser is None:
        parser = H264BitstreamParser(video_path)
        parser.parse()

    sps = pps = None
    for nal in parser.nal_units:
        t = int(nal.nal_unit_type)
        if   t == 7: sps = reconstructor._parse_sps_from_nal(nal)
        elif t == 8: pps = reconstructor._parse_pps_from_nal(nal)

    if not sps or not pps:
        raise RuntimeError("Could not parse SPS/PPS from video")

    mb_count = ((sps.pic_width_in_mbs_minus1  + 1) *
                (sps.pic_height_in_map_units_minus1 + 1))

    traceable           = TraceableCAVLCParser()
    patcher             = BitstreamPatcher()
    coefficients        = []
    frame_verified_data = {}
    nC_map              = {}
    nal_length_map      = {}
    t1_override_map     = {}
    global_mb_idx       = 0
    idr_count           = 0

    for nal in parser.nal_units:
        t = int(nal.nal_unit_type)

        if t == 5:   # IDR slice
            idr_off = global_mb_idx
            result  = traceable.extract_with_offsets(nal, sps, pps,
                                                     global_mb_idx=idr_off)
            blocks  = result.get('blocks',  {})
            offsets = result.get('offsets', {})

            luma_off = {
                (ml, bi): v
                for (ml, bi), v in offsets.items()
                if bi < 16 and any(c != 0 for c in blocks.get((ml, bi), ()))
            }
            # Lazy patchability validation: do not eagerly round-trip every block here.
            # Keep original parser metadata and let the safety filter validate only
            # blocks that actually survive cheap candidate checks.
            unpatch, matched = set(), {}

            idr_coeffs = []
            for (ml, bi) in sorted(blocks.keys()):
                if bi >= 16:
                    continue
                coeffs = matched[(ml, bi)][1] if (ml, bi) in matched else blocks[(ml, bi)]
                if any(c != 0 for c in coeffs):
                    mb_g = ml + idr_off
                    idr_coeffs.append((mb_g, bi, list(coeffs)))
            coefficients.extend(idr_coeffs)

            g_off = {(ml + idr_off, bi): v for (ml, bi), v in offsets.items()}
            g_blk = {}
            for (ml, bi), v in blocks.items():
                g_blk[(ml + idr_off, bi)] = (matched[(ml, bi)][1]
                                              if (ml, bi) in matched else v)
            frame_verified_data[idr_off] = (g_off, g_blk, nal.rbsp_byte)

            for (ml, bi), od in offsets.items():
                if bi >= 16:
                    continue
                mb_g = ml + idr_off
                if (ml, bi) in matched:
                    nC_map[(mb_g, bi)] = matched[(ml, bi)][0]
                elif 'nC' in od:
                    nC_map[(mb_g, bi)] = od['nC']

                if 'bit_length' in od:
                    if (ml, bi) in unpatch:
                        nal_length_map[(mb_g, bi)] = -1
                    else:
                        nal_length_map[(mb_g, bi)] = od['bit_length']
                        mi = matched.get((ml, bi))
                        if mi is not None and mi[2] is not None:
                            t1_override_map[(mb_g, bi)] = mi[2]

            idr_count += 1
            global_mb_idx += mb_count

        elif t == 1:
            global_mb_idx += mb_count

    if idr_count == 0:
        raise RuntimeError(f"No IDR NAL found in {video_path}")
    if len(coefficients) == 0:
        raise RuntimeError(f"No coefficients extracted from {video_path}")

    return coefficients, frame_verified_data, nC_map, nal_length_map, t1_override_map


def extract_bits_direct(stego_video_path: str,
                        embed_safe_positions: list,
                        frame_verified_data: dict,
                        nC_map: dict,
                        payload_bits: int,
                        max_modifications_per_block: int = 1) -> bytes:
    """
    Extract embedded bits from stego video using bit-offset-based decode.
    Length-preserving patcher guarantees original offsets remain valid.
    """
    def _bits_to_bytes(bits):
        padded = bits + [0] * ((8 - len(bits) % 8) % 8)
        out = bytearray()
        for i in range(0, len(padded), 8):
            out.append(sum(padded[i + j] << (7 - j) for j in range(8)))
        return bytes(out)

    def _decode_level_list(rbsp_bytes, start_bit, end_bit, nC):
        rbsp_bits = BitArray(rbsp_bytes)
        end = min(end_bit + 64, len(rbsp_bits))
        raw = _bits_to_bytes(list(rbsp_bits[start_bit:end]))
        try:
            reader = BitstreamReader(raw)
            block  = CAVLCDecoder(reader).decode_block_cavlc(nC, max_num_coeff=od.get('max_num_coeff', 16))
            return list(block.levels)
        except Exception:
            return None

    idr_sorted = sorted(frame_verified_data.keys())
    sp = H264BitstreamParser(stego_video_path)
    sp.parse()
    stego_rbsp = {}
    idx = 0
    for nal in sp.nal_units:
        if int(nal.nal_unit_type) == 5 and idx < len(idr_sorted):
            stego_rbsp[idr_sorted[idx]] = nal.rbsp_byte
            idx += 1

    safe_map = {}
    for mb, blk, cidx in embed_safe_positions:
        safe_map.setdefault((mb, blk), []).append(cidx)

    # Build seen_blocks in the EXACT SAME ORDER as the embedder uses.
    # PayloadEmbedder._embed_with_safety_filter now iterates safe_positions
    # directly (already sorted by sort_blocks_interleaved inside get_safe_positions).
    # The block visit order is the first-occurrence order of each (mb, blk) in
    # embed_safe_positions — preserve that here by deduplicating while keeping order.
    seen_block_set: set = set()
    seen_blocks = []
    for mb, blk, _ in embed_safe_positions:
        k = (mb, blk)
        if k not in seen_block_set:
            seen_block_set.add(k)
            seen_blocks.append(k)

    idr_desc   = sorted(frame_verified_data.keys(), reverse=True)
    ext_bits   = []
    bits_read  = 0

    for (mb, blk) in seen_blocks:
        if bits_read >= payload_bits:
            break
        idr_off = next((off for off in idr_desc if off <= mb), None)
        if idr_off is None:
            continue
        g_off, _, _rbsp = frame_verified_data[idr_off]
        od = g_off.get((mb, blk))
        if od is None:
            continue
        rbsp = stego_rbsp.get(idr_off)
        if rbsp is None:
            continue
        nC     = nC_map.get((mb, blk), 0)
        levels = _decode_level_list(rbsp, od['start_bit'], od['end_bit'], nC)
        if levels is None:
            continue
        for i, cidx in enumerate(safe_map[(mb, blk)]):
            if i >= max_modifications_per_block or bits_read >= payload_bits:
                break
            if cidx >= 0:
                if cidx < len(levels):
                    ext_bits.append(abs(levels[cidx]) & 1)
                    bits_read += 1
            else:
                real_idx = ~cidx
                if real_idx < len(levels):
                    ext_bits.append(0 if levels[real_idx] > 0 else 1)
                    bits_read += 1

    return _bits_to_bytes(ext_bits)
