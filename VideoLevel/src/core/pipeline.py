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

from ..bitstream.h264          import H264BitstreamParser, TraceableCAVLCParser
from ..bitstream.bitstream_ops import BitstreamReconstructor, BitstreamPatcher, BitArray
from ..bitstream.bitstream_io  import BitstreamReader
from ..bitstream.cavlc         import CAVLCDecoder


def extract_all_idr_blocks(video_path: str, reconstructor: BitstreamReconstructor,
                            verbose: bool = False):
    """
    Parse ALL IDR NAL units from video_path using TraceableCAVLCParser.

    Returns
    -------
    coefficients       : list[(mb_global, blk_idx, coeffs)]
    frame_verified_data: {idr_mb_offset: (global_offsets, global_blocks)}
    nC_map             : {(mb_global, blk_idx): nC}
    nal_length_map     : {(mb_global, blk_idx): bit_length}
    t1_override_map    : {(mb_global, blk_idx): trailing_ones_override}
    """
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

            luma_off = {(ml, bi): v for (ml, bi), v in offsets.items() if bi < 16}
            _p = BitstreamPatcher()
            unpatch, matched = _p.get_unpatchable_blocks(nal.rbsp_byte, luma_off)

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
            frame_verified_data[idr_off] = (g_off, g_blk)

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
            block  = CAVLCDecoder(reader).decode_block_cavlc(nC, max_num_coeff=16)
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

    seen_blocks = []
    # Descending order — must match embedding order from get_safe_positions()
    for idr_off in sorted(frame_verified_data.keys(), reverse=True):
        _, g_blk = frame_verified_data[idr_off]
        for (mb, blk) in sorted(g_blk.keys(), reverse=True):
            if blk >= 16:
                continue
            if not any(c != 0 for c in g_blk[(mb, blk)]):
                continue
            if (mb, blk) in safe_map:
                seen_blocks.append((mb, blk))

    idr_desc   = sorted(frame_verified_data.keys(), reverse=True)
    ext_bits   = []
    bits_read  = 0

    for (mb, blk) in seen_blocks:
        if bits_read >= payload_bits:
            break
        idr_off = next((off for off in idr_desc if off <= mb), None)
        if idr_off is None:
            continue
        g_off, _ = frame_verified_data[idr_off]
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
