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

from bisect import bisect_right

from ..bitstream.bitstream_io import BitstreamReader
from ..bitstream.bitstream_ops import BitstreamReconstructor
from ..bitstream.cavlc import CAVLCDecoder
from ..bitstream.h264 import H264BitstreamParser, TraceableCAVLCParser


def _rbsp_bit_window_to_bytes(rbsp_bytes: bytes, start_bit: int, end_bit: int) -> bytes:
    """Pack the same bounded RBSP bit slice as ``BitArray`` without unpacking it."""
    total_bits = len(rbsp_bytes) * 8
    stop_bit = min(end_bit + 64, total_bits)
    start, stop, _ = slice(start_bit, stop_bit).indices(total_bits)
    if stop <= start:
        return b""

    first_byte = start // 8
    bit_offset = start % 8
    bit_count = stop - start
    byte_count = (bit_offset + bit_count + 7) // 8
    window = int.from_bytes(rbsp_bytes[first_byte : first_byte + byte_count], "big")
    window_bits = byte_count * 8
    shift = window_bits - bit_offset - bit_count
    value = (window >> shift) & ((1 << bit_count) - 1)

    padding = (-bit_count) % 8
    packed_bytes = (bit_count + padding) // 8
    return (value << padding).to_bytes(packed_bytes, "big")


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
    coefficients        = []
    frame_verified_data = {}
    nC_map              = {}
    nal_length_map      = {}
    t1_override_map     = {}
    global_mb_idx       = 0
    idr_count           = 0

    for nal_index, nal in enumerate(parser.nal_units):
        t = int(nal.nal_unit_type)

        if t == 5:   # IDR slice
            idr_off = global_mb_idx
            result  = traceable.extract_with_offsets(nal, sps, pps,
                                                     global_mb_idx=idr_off)
            if not result.get('parse_trusted', False):
                issues = result.get('parse_integrity_issues', [])
                preview = '; '.join(str(issue) for issue in issues[:5])
                raise RuntimeError(
                    "Refusing to use untrusted CAVLC parse offsets for embedding. "
                    "The local parser required heuristic recovery, so its "
                    "macroblock-to-bit offsets are not authoritative; this does "
                    "not imply that the input H.264 stream is invalid. "
                    f"NAL index {nal_index}; "
                    f"integrity issues: {preview or 'unspecified parser recovery'}"
                )
            blocks  = result.get('blocks',  {})
            offsets = result.get('offsets', {})

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
                    # frame_verified_data retains the decoded block vectors and
                    # downstream consumers treat the source vectors as read-only
                    # (PayloadEmbedder makes mutable working copies). Reuse the
                    # same list here instead of duplicating 16 coefficient slots
                    # for every luma block in a long all-intra stream.
                    idr_coeffs.append((mb_g, bi, coeffs))
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
                        max_modifications_per_block: int = 1,
                        parser: H264BitstreamParser | None = None) -> bytes:
    """Extract bits by decoding the selected CAVLC blocks from the video."""
    return _extract_bits_direct(
        stego_video_path,
        embed_safe_positions,
        frame_verified_data,
        nC_map,
        payload_bits,
        max_modifications_per_block,
        parser,
        use_decoded_blocks=False,
    )


def _extract_bits_from_decoded_analysis(
    stego_video_path: str,
    embed_safe_positions: list,
    frame_verified_data: dict,
    nC_map: dict,
    payload_bits: int,
    max_modifications_per_block: int = 1,
    parser: H264BitstreamParser | None = None,
) -> bytes:
    """Reuse CAVLC levels from analysis freshly built for this same video.

    This internal fast path is only valid when ``frame_verified_data`` came
    from ``stego_video_path``. Keep it private: public extraction continues to
    decode the selected blocks from the named bitstream.
    """
    return _extract_bits_direct(
        stego_video_path,
        embed_safe_positions,
        frame_verified_data,
        nC_map,
        payload_bits,
        max_modifications_per_block,
        parser,
        use_decoded_blocks=True,
    )


def _extract_bits_direct(stego_video_path: str,
                         embed_safe_positions: list,
                         frame_verified_data: dict,
                         nC_map: dict,
                         payload_bits: int,
                         max_modifications_per_block: int,
                         parser: H264BitstreamParser | None,
                         *,
                         use_decoded_blocks: bool) -> bytes:
    """
    Extract embedded bits from stego video using bit-offset-based decode.

    Length-preserving patching keeps offsets valid for the bitstream path.
    The internal decoded-block mode is restricted to the blind extractor,
    which supplies analysis built from this same video path.
    """
    def _bits_to_bytes(bits):
        padded = bits + [0] * ((8 - len(bits) % 8) % 8)
        out = bytearray()
        for i in range(0, len(padded), 8):
            out.append(sum(padded[i + j] << (7 - j) for j in range(8)))
        return bytes(out)

    def _decode_level_list(rbsp_bytes, start_bit, end_bit, nC, max_num_coeff):
        raw = _rbsp_bit_window_to_bytes(rbsp_bytes, start_bit, end_bit)
        try:
            reader = BitstreamReader(raw)
            block = CAVLCDecoder(reader).decode_block_cavlc(
                nC, max_num_coeff=max_num_coeff
            )
            return list(block.levels)
        except Exception:
            return None

    stego_rbsp = {}
    if not use_decoded_blocks:
        idr_sorted = sorted(frame_verified_data.keys())
        sp = parser
        if sp is None:
            sp = H264BitstreamParser(stego_video_path)
            sp.parse()
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

    idr_offsets = sorted(frame_verified_data)
    ext_bits   = []
    bits_read  = 0

    for (mb, blk) in seen_blocks:
        if bits_read >= payload_bits:
            break
        idr_index = bisect_right(idr_offsets, mb) - 1
        if idr_index < 0:
            continue
        idr_off = idr_offsets[idr_index]
        g_off, g_blk, _rbsp = frame_verified_data[idr_off]
        od = g_off.get((mb, blk))
        if od is None:
            continue
        if use_decoded_blocks:
            levels = g_blk.get((mb, blk))
        else:
            rbsp = stego_rbsp.get(idr_off)
            if rbsp is None:
                continue
            nC = nC_map.get((mb, blk), 0)
            levels = _decode_level_list(
                rbsp,
                od['start_bit'],
                od['end_bit'],
                nC,
                od.get('max_num_coeff', 16),
            )
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
