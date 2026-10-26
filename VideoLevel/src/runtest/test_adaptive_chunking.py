"""Capacity-adaptive chunking (ZKBC v2): plan, framing, transport and pipeline.

The real H.264 round trip at production size is ``benchmark/latticezk_video_e2e.py
--adaptive-chunks`` (docs/CARRIERS_VA_CHUNKING.md); here a 30-frame fixture covers
the real transport and a stand-in channel covers the proof pipeline.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.transport import adaptive_chunks as ac
from src.transport import blind_sync_adaptive as transport
from src.transport.blind_payload_chunks import pack_payload_chunks, payload_chunk_count
from src.transport.blind_sync import BLIND_ENVELOPE_HEADER_BYTES, AdaptiveOperatingContract, BlindOperatingContract
from src.transport.gop_policy import SegmentStructure
from src.registry.lattice_pq import LatticeSigner
from src.lattice_zk import video_pipeline as pipeline
from src.lattice_zk.params import BDLOP_OPEN_128, BDLOP_OPEN_128_V1, BDLOP_OPEN_128_V2, TOY
from src.lattice_zk.video_proof import envelope_size
from src.registry.zkp_registry import SignedZkpRelationRegistry
from src.registry.zkp_sessions import SessionChallengeStore

ROOT = Path(__file__).resolve().parents[2]
CREW_4CIF_Q22 = [11093, 11762, 16852, 9642, 5613, 8794]  # capacity_crew4cif_q22_reg_s6.json
SOCCER_4CIF_Q22 = [38552, 47977, 3501]  # capacity_soccer4cif_q22_reg.json (3 of 6 scanned)
V1_FRAMING = BLIND_ENVELOPE_HEADER_BYTES + 23  # ZKVP header + ZKBC v1 header
MAGNITUDE = BlindOperatingContract(
    version="stable-carriers-video-only-v1", require_bitstream_patchable=True,
    patchability_headroom=64, max_modifications_per_block=1, stable_carriers_only=True,
)


def _uniform_fits(payload_bytes: int, capacities: list[int]) -> bool:
    """Whether ANY fixed ZKBC v1 chunk size puts chunk i into segment i."""
    room = [bits // 8 - V1_FRAMING for bits in capacities]
    for chunk in range(1, 65_536):
        count = -(-payload_bytes // chunk)
        sizes = [chunk] * (count - 1) + [payload_bytes - chunk * (count - 1)]
        if count <= len(room) and all(size <= free for size, free in zip(sizes, room)):
            return True
    return False


# -- plan ------------------------------------------------------------------ #


def test_framing_constants_match_the_segment_envelope() -> None:
    assert ac.SEGMENT_ENVELOPE_HEADER_BYTES == BLIND_ENVELOPE_HEADER_BYTES
    assert ac.CHUNK_HEADER.size == 21 and ac.FRAMING_BYTES == 35


def test_plan_is_deterministic_and_every_parameter_changes_its_id() -> None:
    plan = ac.AdaptiveChunkPlan()
    capacities = [40_000, 900, 25_000, 60_000]
    first = ac.plan_layout(9_000, capacities, plan)
    assert first == ac.plan_layout(9_000, list(capacities), ac.AdaptiveChunkPlan())
    assert plan.plan_id() == ac.AdaptiveChunkPlan().plan_id()
    ids = {plan.plan_id()}
    for field, value in (("min_chunk_bytes", 128), ("reserve_bits", 8),
                         ("fill_permille", 999), ("max_chunk_bytes", 4_000)):
        ids.add(dataclasses.replace(plan, **{field: value}).plan_id())
    assert len(ids) == 5
    assert json.loads(json.dumps(plan.descriptor())) == plan.descriptor()


@pytest.mark.parametrize("field, value", [
    ("version", "zkbc-v2-other"), ("min_chunk_bytes", 0), ("min_chunk_bytes", True),
    ("reserve_bits", -1), ("fill_permille", 0), ("fill_permille", 1001),
    ("max_chunk_bytes", 0), ("min_chunk_bytes", 70_000),
])
def test_invalid_plan_parameters_are_rejected(field, value) -> None:
    with pytest.raises(ValueError):
        ac.AdaptiveChunkPlan(**{field: value})


def test_greedy_fill_uses_each_segment_up_to_its_exact_capacity() -> None:
    plan = ac.AdaptiveChunkPlan(min_chunk_bytes=1)
    layout = ac.plan_layout(8_165, SOCCER_4CIF_Q22, plan)
    assert [(slot.segment_index, slot.size) for slot in layout] == [(0, 4_784), (1, 3_381)]
    # Each chunk plus its two frames fits the segment's carriers exactly.
    assert (4_784 + ac.FRAMING_BYTES) * 8 <= SOCCER_4CIF_Q22[0] < (4_785 + ac.FRAMING_BYTES) * 8


def test_soccer_fits_where_the_sweep_uniform_rule_failed() -> None:
    """The sweep sized one chunk for the smallest scanned segment (3 501 bits)."""
    envelope = envelope_size(BDLOP_OPEN_128, registered=True)
    sweep_chunk = int((min(SOCCER_4CIF_Q22) // 8 - V1_FRAMING) * 0.97)
    assert -(-envelope // sweep_chunk) > len(SOCCER_4CIF_Q22)
    layout = ac.plan_layout(envelope, SOCCER_4CIF_Q22, ac.AdaptiveChunkPlan())
    assert [slot.segment_index for slot in layout] == [0, 1]


def test_crew_fits_adaptively_where_no_uniform_chunk_does_and_reports_true_shortfall() -> None:
    v1_envelope = envelope_size(BDLOP_OPEN_128_V1, registered=True)  # 7 589 B
    assert not _uniform_fits(v1_envelope, CREW_4CIF_Q22)
    layout = ac.plan_layout(v1_envelope, CREW_4CIF_Q22, ac.AdaptiveChunkPlan())
    assert [slot.segment_index for slot in layout] == list(range(6))
    # The production envelope (8 741 B) exceeds crew's whole Q22 capacity
    # (7 757 B usable in 600 frames): no chunking can fit it; say so.
    with pytest.raises(ValueError, match="984 of 8741 payload bytes"):
        ac.plan_layout(envelope_size(BDLOP_OPEN_128, registered=True), CREW_4CIF_Q22,
                       ac.AdaptiveChunkPlan())


def test_sweep_flags_and_dry_run_uniform_search() -> None:
    from benchmark import latticezk_q2_sweep as sweep
    from benchmark.latticezk_adaptive_chunk_plan import best_uniform_chunk

    assert sweep.adaptive_chunk_arguments({"density": 0.5, "min_chunk_bytes": 512}) == [
        "--adaptive-chunks", "--fill-permille", "500", "--min-chunk-bytes", "512"]
    assert best_uniform_chunk(7_589, CREW_4CIF_Q22, 1000) is None
    assert best_uniform_chunk(8_165, SOCCER_4CIF_Q22, 1000) == 38_552 // 8 - V1_FRAMING


def test_low_capacity_segments_are_skipped() -> None:
    plan = ac.AdaptiveChunkPlan(min_chunk_bytes=256)
    capacities = [1_000, 30_000, (256 + ac.FRAMING_BYTES) * 8 - 1, 30_000, 30_000]
    layout = ac.plan_layout(6_000, capacities, plan)
    assert [slot.segment_index for slot in layout] == [1, 3]
    assert [slot.size for slot in layout] == [30_000 // 8 - 35, 6_000 - (30_000 // 8 - 35)]
    assert plan.chunk_capacity_bytes(capacities[2] + 1) == 256


def test_density_reserve_and_cap_lower_the_per_segment_load() -> None:
    capacities = [40_000] * 6  # 4 965 B usable each at full density

    def sizes(**plan):
        return [slot.size for slot in ac.plan_layout(8_000, capacities, ac.AdaptiveChunkPlan(**plan))]

    assert sizes() == [4_965, 3_035]
    assert sizes(fill_permille=500) == [2_465, 2_465, 2_465, 605]
    assert sizes(reserve_bits=16_000) == [2_965, 2_965, 2_070]
    assert sizes(max_chunk_bytes=2_000) == [2_000] * 4
    with pytest.raises(ValueError, match="insufficient"):
        sizes(max_chunk_bytes=1_000)  # would need 8 segments


def test_insufficient_or_invalid_inputs_raise() -> None:
    plan = ac.AdaptiveChunkPlan()
    with pytest.raises(ValueError, match="insufficient"):
        ac.plan_layout(10_000, [8_000] * 3, plan)
    with pytest.raises(ValueError):
        ac.plan_layout(0, [8_000], plan)
    with pytest.raises(ValueError):
        ac.plan_layout(10, [-1], plan)
    with pytest.raises(TypeError):
        ac.plan_layout(10, [8_000], object())


# -- ZKBC v2 framing -------------------------------------------------------- #

PLAN = ac.AdaptiveChunkPlan(min_chunk_bytes=64)
CAPACITIES = [2_000, 600, 4_000, 9_000]  # usable 215, skipped, 465, 1 090 bytes
PAYLOAD = bytes((index * 37 + 11) % 256 for index in range(733))


def test_v2_round_trip_is_canonical_and_differs_from_v1() -> None:
    chunks, layout = ac.canonical_adaptive_chunks(PAYLOAD, CAPACITIES, PLAN)
    assert [slot.segment_index for slot in layout] == [0, 2, 3]
    assert ac.assemble_adaptive_chunks(chunks, CAPACITIES, PLAN) == (PAYLOAD, layout)
    with pytest.raises(ValueError):
        payload_chunk_count(chunks[0])  # a v1 reader refuses v2
    with pytest.raises(ValueError):
        ac.parse_adaptive_chunk(pack_payload_chunks(PAYLOAD, chunk_size=200)[0])


@pytest.mark.parametrize("field", [2, 3, 4, 5, 6])  # chunk, segment, total, offset, crc
def test_any_rewritten_header_field_is_rejected(field) -> None:
    chunks, _ = ac.canonical_adaptive_chunks(PAYLOAD, CAPACITIES, PLAN)
    for target in range(len(chunks)):
        values = list(ac.CHUNK_HEADER.unpack_from(chunks[target]))
        values[field] += 1
        forged = list(chunks)
        forged[target] = ac.CHUNK_HEADER.pack(*values) + chunks[target][ac.CHUNK_HEADER.size:]
        with pytest.raises(ValueError):
            ac.assemble_adaptive_chunks(forged, CAPACITIES, PLAN)


def test_rechunked_reordered_truncated_or_extended_sets_are_rejected() -> None:
    chunks, layout = ac.canonical_adaptive_chunks(PAYLOAD, CAPACITIES, PLAN)
    # Self-consistent v2 framing of the same payload under another layout.
    other = (ac.ChunkSlot(0, 0, 0, 100), ac.ChunkSlot(1, 2, 100, 400), ac.ChunkSlot(2, 3, 500, 233))
    rechunked = ac.pack_adaptive_chunks(PAYLOAD, other)
    candidates = [
        rechunked, chunks[::-1], chunks[:-1], chunks + [chunks[-1]],
        chunks[:-1] + [chunks[-1][:-1]], chunks[:-1] + [chunks[-1] + b"\x00"],
    ]
    for candidate in candidates:
        with pytest.raises(ValueError):
            ac.assemble_adaptive_chunks(candidate, CAPACITIES, PLAN)
    # The same chunks under different (recomputed) capacities or plan fail too.
    with pytest.raises(ValueError):
        ac.assemble_adaptive_chunks(chunks, [2_000, 4_000, 4_000, 9_000], PLAN)
    with pytest.raises(ValueError):
        ac.assemble_adaptive_chunks(chunks, CAPACITIES, ac.AdaptiveChunkPlan(min_chunk_bytes=32))


def test_layouts_must_be_contiguous_and_increasing() -> None:
    for bad in (
        (ac.ChunkSlot(0, 1, 0, 300), ac.ChunkSlot(1, 1, 300, 433)),
        (ac.ChunkSlot(0, 0, 0, 300), ac.ChunkSlot(1, 2, 301, 432)),
        (ac.ChunkSlot(1, 0, 0, 733),),
        (ac.ChunkSlot(0, 0, 0, 732),),
    ):
        with pytest.raises(ValueError):
            ac.pack_adaptive_chunks(PAYLOAD, bad)


# -- existing contracts stay byte-identical ---------------------------------- #

# Recorded at 10bce11 before this change (tmp/baseline_ids.py in the worktree).
BASELINE_DIGEST = "6f3aa1b39d44eba8c6519d8b2e56c652e2367e3bb41f2acc96a9d88808895920"
BASELINE_V1_CHUNKS = "cbad9f4fc90133bf71c154c9394c4abe7cd85e4cf295f23ee26b766e84cc3250"
BASELINE_V1_COMBINED = "9a52d7a4fe7dfc7f29490fbd7d0c76b4c010af0a999189683ed62046da8cd95d"
BASELINE_REGISTERED_MAGNITUDE = "93f63501a96424681ccb85c0c5c4ce221e5297f9baee9e6e1ed677b8a567734c"


def test_existing_profiles_and_v1_framing_are_byte_identical() -> None:
    from benchmark.latticezk_video_e2e import CARRIER_CONTRACTS
    from src.transport import gop_policy
    from src.transport.blind_sync_streaming import _combine_segment_digests

    table = {}
    # The carriers that existed at 10bce11; later contracts (e.g. the *-geo
    # orders) have their own identifiers and are pinned in their own tests.
    existing = ("adaptive", "adaptive-texture", "magnitude", "t1")
    for name in existing:
        contract = CARRIER_CONTRACTS[name]
        for registered in (False, True):
            for chunk in (1250, 4200, 65535):
                for policy in (gop_policy.ALL_INTRA, gop_policy.IDR_CARRIERS_INTER_RAW):
                    profile = pipeline.CarrierProfile(
                        contract, chunk_bytes=chunk, registered=registered, gop_policy=policy,
                        codec_policy=pipeline.CODEC_POLICY_V1,  # recorded under v1
                    )
                    # Pinned to the v2 set: the table was recorded under it.
                    for params in (BDLOP_OPEN_128_V2, TOY):
                        table[f"{name}/{registered}/{chunk}/{policy}/{params.name}"] = [
                            profile.profile_id(params).hex(), pipeline.policy_hash(params, profile),
                            pipeline.public_sync_key(params, profile).hex(),
                        ]
    payload = bytes(range(256)) * 40
    table["v1_chunks"] = hashlib.sha256(
        b"".join(pack_payload_chunks(payload, chunk_size=1000))
    ).hexdigest()
    table["v1_combined"] = _combine_segment_digests([(100, "ab" * 32), (100, "cd" * 32)], 100)
    assert table["v1_chunks"] == BASELINE_V1_CHUNKS
    assert table["v1_combined"] == BASELINE_V1_COMBINED
    assert table["magnitude/True/1250/all-intra/bdlop-open-128-v2"][0] == BASELINE_REGISTERED_MAGNITUDE
    assert hashlib.sha256(json.dumps(table, sort_keys=True).encode()).hexdigest() == BASELINE_DIGEST


def test_adaptive_profile_has_its_own_id_and_rejects_ambiguous_fields() -> None:
    base = pipeline.CarrierProfile(MAGNITUDE, registered=True)
    adaptive = dataclasses.replace(base, chunk_plan=ac.AdaptiveChunkPlan())
    assert base.profile_id(TOY).hex() != adaptive.profile_id(TOY).hex()
    other = dataclasses.replace(adaptive, chunk_plan=ac.AdaptiveChunkPlan(min_chunk_bytes=512))
    assert other.profile_id(TOY) != adaptive.profile_id(TOY)
    assert pipeline.policy_hash(TOY, other) != pipeline.policy_hash(TOY, adaptive)
    with pytest.raises(ValueError):
        dataclasses.replace(adaptive, chunk_bytes=4_200)
    with pytest.raises(ValueError):
        pipeline.CarrierProfile(MAGNITUDE, chunk_plan={"min_chunk_bytes": 1})
    assert pipeline._default_adaptive_transport() is transport


# -- transport walk with stand-in segments ------------------------------------ #


def _stand_in_segments(monkeypatch, tmp_path, capacities, extracted_chunks, structures=None):
    segments = [tmp_path / f"segment_{index:05}.h264" for index in range(len(capacities))]
    for index, segment in enumerate(segments):
        segment.write_bytes(b"segment %d" % index)
    capacity_of = dict(zip(segments, capacities))
    monkeypatch.setattr(transport, "_split_video_into_segments",
                        lambda *_a, **_k: (segments, [100] * len(segments)))
    monkeypatch.setattr(transport, "_inspect_segments", lambda _s, counts, _p: structures or [
        SegmentStructure(count, count, count, 0, 0) for count in counts])
    monkeypatch.setattr(transport, "segment_capacity_bits",
                        lambda segment, _key, _contract: capacity_of[Path(segment)])
    monkeypatch.setattr(transport, "clear_video_analysis_cache", lambda: 0)
    monkeypatch.setattr(transport, "load_or_build_video_analysis",
                        lambda *_a, **_k: ([], {0: ({}, {}, b"")}, {}, {}, {}, []))
    monkeypatch.setattr(transport, "load_or_build_reconstruction_context",
                        lambda *_a, **_k: {"mb_count_per_slice": 396, "parser": object()})
    monkeypatch.setattr("src.transport.video_canonicalization.canonical_video_sha256",
                        lambda segment, *_a, **_k: hashlib.sha256(Path(segment).read_bytes()).hexdigest())
    seen = []

    def fake_extract(path, *_a, **_k):
        index = segments.index(Path(path))
        seen.append(index)
        chunk = extracted_chunks[index]
        return SimpleNamespace(payload=chunk, carriers_used=8 * len(chunk),
                               carrier_positions=((0, index, 1),))

    monkeypatch.setattr("src.transport.blind_sync.extract_blind_video_payload", fake_extract)
    video = tmp_path / "video.h264"
    video.write_bytes(b"video")
    return video, seen


def _by_segment(chunks, layout):
    return {slot.segment_index: chunk for slot, chunk in zip(layout, chunks)}


def test_extractor_recomputes_plan_skips_low_segments_and_binds_roles(monkeypatch, tmp_path) -> None:
    chunks, layout = ac.canonical_adaptive_chunks(PAYLOAD, CAPACITIES + [9_000], PLAN)
    video, seen = _stand_in_segments(monkeypatch, tmp_path, CAPACITIES + [9_000],
                                     _by_segment(chunks, layout))
    events = []
    result = transport.extract_adaptive_video_payload(
        video, b"key", MAGNITUDE, plan=PLAN, payload_bytes=len(PAYLOAD),
        progress_callback=events.append,
    )
    assert result.payload == PAYLOAD and result.chunks == tuple(chunks)
    assert seen == [0, 2, 3]  # segment 1 is below the threshold, segment 4 unused
    assert result.segment_capacity_bits == tuple(CAPACITIES)
    assert result.layout == layout
    # Global positions use each segment's slot offset.
    assert result.global_positions == ((0, 0, 1), (200 * 396, 2, 1), (300 * 396, 3, 1))
    names = [event["event"] for event in events if "segment_index" in event]
    assert names.count("segment_below_threshold") == 1 and names[-1] == "segment_unused"
    # Without a pinned size the first header supplies it.
    unpinned = transport.extract_adaptive_video_payload(video, b"key", MAGNITUDE, plan=PLAN)
    assert unpinned.canonical_video_sha256 == result.canonical_video_sha256
    # The digest binds the plan, the roles and the capacities.
    records = [transport.SegmentRecord(0, 100, transport.ROLE_CARRIER, 2_000, 215, "00" * 32)]
    digests = {
        transport.combine_adaptive_segment_digests(records, 100, PLAN, 215),
        transport.combine_adaptive_segment_digests(records, 100, ac.AdaptiveChunkPlan(), 215),
        transport.combine_adaptive_segment_digests(
            [dataclasses.replace(records[0], capacity_bits=2_001)], 100, PLAN, 215),
        transport.combine_adaptive_segment_digests(
            [dataclasses.replace(records[0], role=transport.ROLE_SKIPPED)], 100, PLAN, 215),
    }
    assert len(digests) == 4


def test_extractor_rejects_chunks_that_deviate_from_the_plan(monkeypatch, tmp_path) -> None:
    chunks, layout = ac.canonical_adaptive_chunks(PAYLOAD, CAPACITIES, PLAN)
    honest = _by_segment(chunks, layout)
    forged_header = list(ac.CHUNK_HEADER.unpack_from(chunks[1]))
    forged_header[3] = 1  # claims segment 1
    variants = {
        "wrong segment": {**honest, 2: ac.CHUNK_HEADER.pack(*forged_header) + chunks[1][21:]},
        "short chunk": {**honest, 2: chunks[1][:-5]},
        "other payload size": {**honest, 0: ac.pack_adaptive_chunks(
            PAYLOAD + b"x", ac.plan_layout(734, CAPACITIES, PLAN))[0]},
    }
    cases = [(name, CAPACITIES, extracted, PLAN) for name, extracted in variants.items()]
    # Embedder/verifier plan mismatch: a lower threshold makes segment 1 a carrier.
    cases.append(("plan mismatch", CAPACITIES, {**honest, 1: b"\x00" * 40},
                  ac.AdaptiveChunkPlan(min_chunk_bytes=8)))
    cases.append(("too few segments", CAPACITIES[:3], honest, PLAN))
    for number, (name, capacities, extracted, plan) in enumerate(cases):
        directory = tmp_path / f"case{number}"
        directory.mkdir()
        video, _ = _stand_in_segments(monkeypatch, directory, capacities, extracted)
        with pytest.raises(ValueError):
            transport.extract_adaptive_video_payload(
                video, b"key", MAGNITUDE, plan=plan, payload_bytes=len(PAYLOAD)
            )
            pytest.fail(name)


def test_plan_and_codec_policy_v2_are_bound_together(monkeypatch, tmp_path) -> None:
    from src.transport.video_canonicalization import DIGEST_V1, DIGEST_V2

    # codec policy v2 is the default: PROFILE is already plan + v2.
    v1_plain = pipeline.CarrierProfile(MAGNITUDE, codec_policy=pipeline.CODEC_POLICY_V1)
    v1_plan = dataclasses.replace(PROFILE, codec_policy=pipeline.CODEC_POLICY_V1)
    v2_plain = pipeline.CarrierProfile(MAGNITUDE)
    both = dataclasses.replace(v2_plain, chunk_plan=PLAN)
    assert both == PROFILE
    ids = {profile.profile_id(TOY) for profile in (PROFILE, v1_plain, v1_plan, v2_plain)}
    assert len(ids) == 4
    assert both.options()["digest_policy"] == DIGEST_V2
    assert "digest_policy" not in v1_plan.options()
    chunks, layout = ac.canonical_adaptive_chunks(PAYLOAD, CAPACITIES, PLAN)
    video, _ = _stand_in_segments(monkeypatch, tmp_path, CAPACITIES, _by_segment(chunks, layout))
    digests = {
        policy: transport.extract_adaptive_video_payload(
            video, b"key", MAGNITUDE, plan=PLAN, digest_policy=policy
        ).canonical_video_sha256
        for policy in (DIGEST_V1, DIGEST_V2)
    }
    assert digests[DIGEST_V1] != digests[DIGEST_V2]
    with pytest.raises(ValueError):
        transport.extract_adaptive_video_payload(video, b"key", MAGNITUDE, plan=PLAN,
                                                 digest_policy="other")


def test_gop_segments_offset_positions_by_coded_slices(monkeypatch, tmp_path) -> None:
    chunks, layout = ac.canonical_adaptive_chunks(PAYLOAD, CAPACITIES, PLAN)
    # GOP > 1 segments: 100 pictures but 120 coded slices (slot numbering).
    structures = [SegmentStructure(120, 100, 20, 100, 100) for _ in CAPACITIES]
    video, _ = _stand_in_segments(monkeypatch, tmp_path, CAPACITIES,
                                  _by_segment(chunks, layout), structures)
    result = transport.extract_adaptive_video_payload(
        video, b"key", MAGNITUDE, plan=PLAN, gop_policy="idr-carriers-inter-raw-v1"
    )
    assert result.payload == PAYLOAD
    assert result.global_positions == ((0, 0, 1), (240 * 396, 2, 1), (360 * 396, 3, 1))


# -- proof pipeline over a stand-in adaptive channel --------------------------- #

SYNC_KEY = b"k" * 32
MARKER = b"\x00ADAPTIVE\x00"
PROFILE = pipeline.CarrierProfile(MAGNITUDE, chunk_plan=PLAN)


class FakeAdaptiveTransport:
    """Stores length-prefixed chunks (one per 'segment') after the fake video body.

    The 'video' has fixed per-segment capacities, identical for cover and
    stego (the carrier set is invariant).  Extraction does not validate, so
    the pipeline's own canonical check is what is tested.
    """

    def __init__(self, capacities=tuple(CAPACITIES)):
        self.capacities = tuple(capacities)

    def _context(self, body: bytes, layout, capacities):
        positions = tuple((slot.segment_index * 10_000 + bit, 0, 1)
                          for slot in layout for bit in range((slot.size + 35) * 8))
        bound = hashlib.sha256(body + repr((layout, capacities)).encode()).hexdigest()
        return dict(positions_hash=hashlib.sha256(repr(positions).encode()).hexdigest(),
                    canonical_video_sha256=bound, global_positions=positions)

    def derive_adaptive_video_context(self, video_path, payload, sync_key, contract, *, plan,
                                      **_options):
        layout = ac.plan_layout(len(payload), self.capacities, plan)
        capacities = self.capacities[: layout[-1].segment_index + 1]
        return SimpleNamespace(layout=layout, segment_capacity_bits=capacities,
                               **self._context(Path(video_path).read_bytes(), layout, capacities))

    def embed_adaptive_video_payload(self, cover, output, payload, sync_key, contract, *, plan,
                                     expected_layout=None, **_options):
        layout = ac.plan_layout(len(payload), self.capacities, plan)
        assert expected_layout == layout
        chunks = ac.pack_adaptive_chunks(payload, layout)
        framed = b"".join(struct.pack(">H", len(chunk)) + chunk for chunk in chunks)
        Path(output).write_bytes(Path(cover).read_bytes() + MARKER + framed)
        return SimpleNamespace(carriers_used=sum((len(c) + 14) * 8 for c in chunks),
                               segments_used=len(chunks))

    def extract_adaptive_video_payload(self, video_path, sync_key, contract, *, plan,
                                       payload_bytes=None, **_options):
        body, found, framed = Path(video_path).read_bytes().partition(MARKER)
        if not found:
            raise ValueError("no carriers found")
        chunks = []
        while framed:
            (length,), framed = struct.unpack(">H", framed[:2]), framed[2:]
            chunks.append(framed[:length])
            framed = framed[length:]
        headers = [ac.parse_adaptive_chunk(chunk) for chunk in chunks]
        payload = b"".join(header.part for header in headers)
        last = max(header.segment_index for header in headers)
        capacities = self.capacities[: last + 1]
        layout = tuple(ac.ChunkSlot(h.chunk_index, h.segment_index, h.offset, len(h.part))
                       for h in headers)
        return SimpleNamespace(payload=payload, chunks=tuple(chunks), carriers_used=0,
                               segment_capacity_bits=capacities,
                               **self._context(body, layout, capacities))


def _pins(issuer, profile, params=TOY):
    registry = SignedZkpRelationRegistry.create(
        epoch=2, relations=[pipeline.relation_descriptor(params, profile)]
    ).sign(issuer[1], signer_id="test-issuer")
    return pipeline.pins_from_registry(registry, issuer[0], params, profile, minimum_epoch=2,
                                       allow_toy_parameters=True)


@pytest.fixture(scope="module")
def issuer():
    return LatticeSigner.generate_keypair()


def _embed(tmp_path, issuer, profile=PROFILE, session=b"\x07" * 32, channel=None, pins=None):
    pins = pins or _pins(issuer, profile)
    cover, stego = tmp_path / "cover.h264", tmp_path / "stego.h264"
    cover.write_bytes(b"non-carrier syntax" * 50)
    result = pipeline.embed_video_proof(
        cover, stego, b"hidden record", params=TOY, pins=pins, profile=profile,
        session_challenge=session, sync_key=SYNC_KEY, transport=channel or FakeAdaptiveTransport(),
    )
    return stego, pins, result


def _verify(stego, pins, profile=PROFILE, channel=None, **options):
    options.setdefault("expected_session", b"\x07" * 32)
    options.setdefault("allow_toy_parameters", True)
    return pipeline.verify_video_proof(
        stego, params=TOY, pins=pins, profile=profile, sync_key=SYNC_KEY,
        transport=channel or FakeAdaptiveTransport(), **options,
    )


def _rewrite(stego: Path, transform) -> None:
    body, _, framed = stego.read_bytes().partition(MARKER)
    chunks = []
    while framed:
        (length,), framed = struct.unpack(">H", framed[:2]), framed[2:]
        chunks.append(framed[:length])
        framed = framed[length:]
    chunks = transform(chunks)
    stego.write_bytes(body + MARKER + b"".join(struct.pack(">H", len(c)) + c for c in chunks))


def test_pipeline_round_trip_skips_low_segments_and_rejects_replay(tmp_path, issuer) -> None:
    pins = _pins(issuer, PROFILE)
    store = SessionChallengeStore(tmp_path / "sessions.sqlite3", ttl_seconds=60)
    grant = store.issue(context_binding=pipeline.session_binding(TOY, pins))
    stego, pins, embedded = _embed(tmp_path, issuer, session=grant.challenge, pins=pins)
    assert embedded.envelope_bytes == 733
    assert embedded.chunk_layout == ((0, 215), (2, 465), (3, 53))
    assert embedded.segment_capacity_bits == tuple(CAPACITIES)
    first = _verify(stego, pins, session_store=store, expected_session=None)
    assert first.valid and first.statement_id == embedded.statement_id
    assert not _verify(stego, pins, session_store=store, expected_session=None).valid


def test_fixed_chunk_profile_cannot_carry_what_the_adaptive_one_does() -> None:
    assert not _uniform_fits(733, CAPACITIES)
    assert ac.plan_layout(733, CAPACITIES, PLAN)


def test_registered_adaptive_round_trip(tmp_path, issuer) -> None:
    from src.lattice_zk import bdlop, codec

    profile = dataclasses.replace(PROFILE, registered=True)
    randomness = bdlop.sample_randomness(TOY, b"c" * 32)
    commitment = bdlop.commit(TOY, codec.encode_payload(TOY, b"device 42"), randomness)
    registry = SignedZkpRelationRegistry.create(
        epoch=2, relations=[pipeline.relation_descriptor(TOY, profile, commitment)]
    ).sign(issuer[1], signer_id="test-issuer")
    pins = pipeline.pins_from_registry(registry, issuer[0], TOY, profile, minimum_epoch=2,
                                       allow_toy_parameters=True, credential=commitment)
    cover, stego = tmp_path / "cover.h264", tmp_path / "stego.h264"
    cover.write_bytes(b"non-carrier syntax" * 50)
    embedded = pipeline.embed_video_proof(
        cover, stego, None, params=TOY, pins=pins, profile=profile, credential=pipeline.Credential(
            commitment, randomness), session_challenge=b"\x07" * 32, sync_key=SYNC_KEY,
        transport=FakeAdaptiveTransport(),
    )
    assert embedded.chunk_layout == ((0, 215), (2, 198))
    assert _verify(stego, pins, profile, credential=commitment).valid


@pytest.mark.parametrize("field", [2, 3, 4, 5, 6])
def test_pipeline_rejects_rewritten_chunk_headers(tmp_path, issuer, field) -> None:
    stego, pins, _ = _embed(tmp_path, issuer)
    assert _verify(stego, pins).valid

    def forge(chunks):
        values = list(ac.CHUNK_HEADER.unpack_from(chunks[0]))
        values[field] += 1
        return [ac.CHUNK_HEADER.pack(*values) + chunks[0][21:], *chunks[1:]]

    _rewrite(stego, forge)
    assert not _verify(stego, pins).valid


def test_pipeline_rejects_rechunked_truncated_or_extended_envelopes(tmp_path, issuer) -> None:
    stego, pins, _ = _embed(tmp_path, issuer)
    original = stego.read_bytes()

    def rechunk(chunks):
        payload = b"".join(chunk[21:] for chunk in chunks)
        other = (ac.ChunkSlot(0, 0, 0, 200), ac.ChunkSlot(1, 2, 200, 465), ac.ChunkSlot(2, 3, 665, 68))
        return ac.pack_adaptive_chunks(payload, other)

    for transform in (rechunk, lambda c: c[:-1], lambda c: c + [c[-1]],
                      lambda c: c[:-1] + [c[-1][:-1]], lambda c: c[:-1] + [c[-1] + b"\x00"]):
        stego.write_bytes(original)
        _rewrite(stego, transform)
        result = _verify(stego, pins)
        assert not result.valid, transform


def test_embedder_verifier_plan_mismatch_is_rejected(tmp_path, issuer) -> None:
    stego, pins, _ = _embed(tmp_path, issuer)
    other = dataclasses.replace(PROFILE, chunk_plan=ac.AdaptiveChunkPlan(min_chunk_bytes=32))
    with pytest.raises(ValueError, match="relation id"):
        _verify(stego, pins, other)  # pins of one plan, profile of another
    # Properly pinned for the other plan: the recomputed layout differs.
    assert not _verify(stego, _pins(issuer, other), other).valid
    # A fixed-chunk profile is a different relation altogether.
    fixed = pipeline.CarrierProfile(MAGNITUDE)
    with pytest.raises(ValueError, match="relation id"):
        _verify(stego, pins, fixed)


def test_capacity_reports_that_disagree_with_the_video_are_rejected(tmp_path, issuer) -> None:
    stego, pins, _ = _embed(tmp_path, issuer)

    class Liar(FakeAdaptiveTransport):
        def __init__(self, lie):
            super().__init__()
            self.lie = lie

        def extract_adaptive_video_payload(self, *arguments, **options):
            return SimpleNamespace(**{**vars(super().extract_adaptive_video_payload(
                *arguments, **options)), **self.lie})

    for lie in ({"segment_capacity_bits": None},
                {"segment_capacity_bits": (2_000, 600, 4_000, 9_000, 9_000)},
                {"segment_capacity_bits": (2_000, 4_000, 4_000, 9_000)},
                {"layout": (ac.ChunkSlot(0, 0, 0, 733),)}):
        assert not _verify(stego, pins, channel=Liar(lie)).valid
    # A video whose (recomputed) capacities differ from the cover's is rejected.
    assert not _verify(stego, pins, channel=FakeAdaptiveTransport([2_000, 2_000, 4_000, 9_000])).valid


def test_non_carrier_change_or_other_session_is_rejected(tmp_path, issuer) -> None:
    stego, pins, _ = _embed(tmp_path, issuer)
    assert not _verify(stego, pins, expected_session=b"\x08" * 32).valid
    data = bytearray(stego.read_bytes())
    data[3] ^= 1
    stego.write_bytes(bytes(data))
    assert not _verify(stego, pins).valid


# -- real H.264 fixture ----------------------------------------------------- #

FIXTURE = ROOT / "data" / "external" / "trust_corpus" / "mdn_friday_cif_q22_g1_30f.h264"


@pytest.mark.parametrize("contract", [MAGNITUDE, AdaptiveOperatingContract()],
                         ids=["magnitude", "stc"])
def test_real_video_round_trip_skips_a_segment_and_recomputes_capacity(tmp_path, contract) -> None:
    if not FIXTURE.is_file():
        pytest.skip("the checked-in 30-frame H.264 fixture is unavailable")
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg and ffprobe are required for this real-video test")
    plan = ac.AdaptiveChunkPlan(min_chunk_bytes=30)  # segment 0 (28 B usable) is skipped
    payload = bytes(range(70))
    key = bytes(range(32))
    context = transport.derive_adaptive_video_context(
        FIXTURE, payload, key, contract, plan=plan, frames_per_segment=10
    )
    assert [slot.segment_index for slot in context.layout] == [1, 2]
    output = tmp_path / "stego.h264"
    embedded = transport.embed_adaptive_video_payload(
        FIXTURE, output, payload, key, contract, plan=plan,
        expected_layout=context.layout, frames_per_segment=10,
    )
    extracted = transport.extract_adaptive_video_payload(
        output, key, contract, plan=plan, payload_bytes=len(payload), frames_per_segment=10
    )
    assert extracted.payload == payload
    # Blind: the stego video yields the cover's capacities, plan and context.
    assert extracted.segment_capacity_bits == context.segment_capacity_bits
    assert extracted.segment_capacity_bits == embedded.segment_capacity_bits
    assert extracted.layout == context.layout
    assert extracted.positions_hash == context.positions_hash
    assert extracted.canonical_video_sha256 == context.canonical_video_sha256
    # The skipped segment is byte-identical (its first IDR slice is unchanged).
    cover_bytes, stego_bytes = FIXTURE.read_bytes(), output.read_bytes()
    assert cover_bytes != stego_bytes
    from src.transport.gop_policy import nal_unit_spans

    first_cover = [cover_bytes[a:b] for a, b in nal_unit_spans(cover_bytes)][:12]
    first_stego = [stego_bytes[a:b] for a, b in nal_unit_spans(stego_bytes)][:12]
    assert first_cover == first_stego
    with pytest.raises(ValueError):  # verifier with another plan
        transport.extract_adaptive_video_payload(
            output, key, contract, plan=ac.AdaptiveChunkPlan(min_chunk_bytes=20),
            payload_bytes=len(payload), frames_per_segment=10,
        )
