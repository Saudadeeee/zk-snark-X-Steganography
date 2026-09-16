"""Contracts for the bounded-latency Annex-B realtime transport layer."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.realtime import (
    AnnexBStreamParser,
    AccessUnitAssembler,
    BoundedAccessUnitQueue,
    RealtimeAnnexBRelay,
    RealtimePayloadScheduler,
)


def _nal(nal_type: int, payload: bytes = b"x") -> bytes:
    return b"\x00\x00\x00\x01" + bytes([0x60 | nal_type]) + payload


def t_annexb_parser_handles_split_start_codes_without_losing_nals():
    stream = _nal(7, b"sps") + _nal(8, b"pps") + _nal(9, b"aud") + _nal(5, b"idr")
    parser = AnnexBStreamParser()
    output = []
    for cut in (stream[:3], stream[3:10], stream[10:23], stream[23:]):
        output.extend(parser.feed(cut))
    output.extend(parser.finish())

    assert [nal.nal_type for nal in output] == [7, 8, 9, 5]
    assert output[-1].payload == bytes([0x65]) + b"idr"


def t_access_units_require_aud_and_preserve_idr_boundary():
    parser = AnnexBStreamParser()
    nals = parser.feed(_nal(9, b"a") + _nal(5, b"idr") + _nal(9, b"b") + _nal(1, b"p"))
    nals.extend(parser.finish())
    assembler = AccessUnitAssembler(require_aud=True)
    units = []
    for nal in nals:
        units.extend(assembler.push(nal))
    units.extend(assembler.finish())

    assert len(units) == 2
    assert units[0].is_idr is True
    assert units[1].is_idr is False
    assert units[0].to_annexb().startswith(b"\x00\x00\x00\x01")


def t_bounded_queue_drops_oldest_non_idr_before_an_idr():
    parser = AnnexBStreamParser()
    nals = parser.feed(_nal(9) + _nal(1, b"p1") + _nal(9) + _nal(1, b"p2") + _nal(9) + _nal(5, b"idr"))
    nals.extend(parser.finish())
    assembler = AccessUnitAssembler(require_aud=True)
    units = []
    for nal in nals:
        units.extend(assembler.push(nal))
    units.extend(assembler.finish())

    queue = BoundedAccessUnitQueue(max_units=2)
    for unit in units:
        queue.offer(unit)

    remaining = [queue.pop(), queue.pop()]
    assert [unit.is_idr for unit in remaining] == [False, True]
    assert queue.metrics.dropped_non_idr == 1
    assert queue.metrics.dropped_idr == 0


def t_scheduler_only_allocates_compact_lattice_chunks_to_idr_units():
    scheduler = RealtimePayloadScheduler(b"payload", chunk_bytes=2, repeat_every_idr=1)
    no_chunk = scheduler.next_for_access_unit(is_idr=False)
    first = scheduler.next_for_access_unit(is_idr=True)
    second = scheduler.next_for_access_unit(is_idr=True)

    assert no_chunk is None
    assert first is not None and first.data == b"pa" and first.sequence == 0
    assert second is not None and second.data == b"yl" and second.sequence == 1


def t_relay_preserves_live_annexb_and_only_schedules_idr_payload():
    stream = _nal(9, b"a") + _nal(5, b"idr") + _nal(9, b"b") + _nal(1, b"p")
    observed = []

    def mutator(unit, chunk):
        observed.append((unit.is_idr, None if chunk is None else chunk.data))
        return unit

    relay = RealtimeAnnexBRelay(
        RealtimePayloadScheduler(b"abc", chunk_bytes=2), mutator=mutator, max_queue_units=2
    )
    output = relay.feed(stream[:17]) + relay.feed(stream[17:]) + relay.finish()

    assert output == stream
    assert observed == [(True, b"ab"), (False, None)]
    assert relay.metrics.scheduled_chunks == 1
    assert relay.metrics.mutation_failures == 0


def t_relay_forwards_original_access_unit_when_mutator_fails():
    stream = _nal(9) + _nal(5, b"idr")

    def broken_mutator(_unit, _chunk):
        raise RuntimeError("simulated native backend failure")

    relay = RealtimeAnnexBRelay(RealtimePayloadScheduler(b"x"), mutator=broken_mutator)
    output = relay.feed(stream) + relay.finish()

    assert output == stream
    assert relay.metrics.mutation_failures == 1


def main():
    tests = [
        ("annexb_parser_handles_split_start_codes_without_losing_nals", t_annexb_parser_handles_split_start_codes_without_losing_nals),
        ("access_units_require_aud_and_preserve_idr_boundary", t_access_units_require_aud_and_preserve_idr_boundary),
        ("bounded_queue_drops_oldest_non_idr_before_an_idr", t_bounded_queue_drops_oldest_non_idr_before_an_idr),
        ("scheduler_only_allocates_compact_lattice_chunks_to_idr_units", t_scheduler_only_allocates_compact_lattice_chunks_to_idr_units),
        ("relay_preserves_live_annexb_and_only_schedules_idr_payload", t_relay_preserves_live_annexb_and_only_schedules_idr_payload),
        ("relay_forwards_original_access_unit_when_mutator_fails", t_relay_forwards_original_access_unit_when_mutator_fails),
    ]
    failures = []
    for name, test in tests:
        try:
            test()
            print(f"[PASS] {name}")
        except Exception as exc:
            failures.append((name, exc))
            print(f"[FAIL] {name}: {exc}")
    if failures:
        raise SystemExit(1)
    print(f"{len(tests)}/{len(tests)} passed")


if __name__ == "__main__":
    main()
