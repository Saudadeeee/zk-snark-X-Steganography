"""Equivalence tests for the optimized Annex-B NAL parsing helpers."""

from src.bitstream.h264 import NALParser


def _reference_find_start_codes(data: bytes) -> list[tuple[int, int]]:
    positions = []
    index = 0
    while index < len(data) - 3:
        if data[index : index + 4] == b"\x00\x00\x00\x01":
            positions.append((index + 4, 4))
            index += 4
        elif data[index : index + 3] == b"\x00\x00\x01":
            positions.append((index + 3, 3))
            index += 3
        else:
            index += 1
    return positions


def _reference_remove_emulation_prevention(data: bytes) -> bytes:
    result = bytearray()
    index = 0
    while index < len(data):
        if (
            index + 2 < len(data)
            and data[index : index + 2] == b"\x00\x00"
            and data[index + 2] == 0x03
        ):
            result.extend(data[index : index + 2])
            index += 3
        else:
            result.append(data[index])
            index += 1
    return bytes(result)


def test_find_start_codes_matches_legacy_scan_with_zero_runs_and_trailing_prefixes():
    parser = NALParser(b"")
    fixtures = []
    for prefix_zeros in range(9):
        for between_zeros in range(6):
            fixtures.append(
                b"A" + b"\x00" * prefix_zeros + b"\x01\x65"
                + b"B" + b"\x00" * between_zeros + b"\x01\x41"
            )
    fixtures.extend((b"\x00\x00\x01", b"\x00\x00\x00\x01", b"\x00\x00\x01\x65"))

    for data in fixtures:
        parser.data = data
        assert parser._find_start_codes() == _reference_find_start_codes(data)


def test_remove_emulation_prevention_matches_legacy_scan_for_all_byte_values():
    parser = NALParser(b"")
    fixtures = [bytes(range(256))]
    fixtures.extend(
        b"\x00\x00\x03" + bytes((following,))
        for following in range(256)
    )
    fixtures.extend((b"\x00\x00\x03", b"\x00\x00\x03\x03", b"\x00\x00\x00\x03"))

    for data in fixtures:
        assert parser._remove_emulation_prevention(data) == _reference_remove_emulation_prevention(data)
