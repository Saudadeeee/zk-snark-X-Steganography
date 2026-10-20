"""Cost-adaptive syndrome-coded carriers: code, costs, contract and video round trip."""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from src import blind_sync
from src.blind_sync import (
    AdaptiveOperatingContract,
    BlindOperatingContract,
    coded_carrier_layout,
    derive_coded_carrier_positions,
    embed_blind_video_payload,
    extract_blind_video_payload,
    is_syndrome_coded,
    pack_blind_payload,
    syndrome_code_envelope,
)
from src.core import adaptive_carriers as ac

ROOT = Path(__file__).resolve().parents[2]
COVER = "data/encoded/container_cif_q22_g1.h264"
MAGNITUDE = BlindOperatingContract(
    version="stable-carriers-video-only-v1",
    require_bitstream_patchable=True,
    patchability_headroom=64,
    max_modifications_per_block=1,
    stable_carriers_only=True,
)
T1_SIGN = BlindOperatingContract(
    version="t1-sign-video-only-v2",
    signbit_only=True,
    require_bitstream_patchable=True,
    patchability_headroom=64,
    max_modifications_per_block=1,
    stable_carriers_only=True,
)


# -- syndrome-trellis code ------------------------------------------------- #

@pytest.mark.parametrize("height", [1, 3, 7, 10])
@pytest.mark.parametrize("message_bits,carrier_bits", [(1, 1), (5, 5), (40, 97), (300, 1000)])
def test_stc_round_trip(height, message_bits, carrier_bits):
    rng = np.random.default_rng(height * 1000 + carrier_bits)
    cover = rng.integers(0, 2, carrier_bits).tolist()
    message = rng.integers(0, 2, message_bits).tolist()
    costs = rng.uniform(0.1, 2.0, carrier_bits).tolist()
    stego = ac.stc_embed(cover, message, costs, height)
    assert ac.stc_extract(stego, message_bits, height) == message


def _syndrome_matrix(message_bits: int, carrier_bits: int, height: int) -> np.ndarray:
    matrix = np.zeros((message_bits, carrier_bits), dtype=np.int64)
    column_index = 0
    for row, width, columns in ac._block_layout(message_bits, carrier_bits, height):
        for column in columns:
            for bit in range(height):
                if column >> bit & 1:
                    matrix[row + bit, column_index] = 1
            column_index += 1
    return matrix


def test_stc_is_a_minimum_cost_solution_on_a_small_instance():
    rng = np.random.default_rng(7)
    message_bits, carrier_bits, height = 4, 11, 3
    matrix = _syndrome_matrix(message_bits, carrier_bits, height)
    for _trial in range(5):
        cover = rng.integers(0, 2, carrier_bits)
        message = rng.integers(0, 2, message_bits)
        costs = rng.uniform(0.1, 3.0, carrier_bits)
        best = min(
            float(costs[np.array(candidate) != cover].sum())
            for candidate in itertools.product((0, 1), repeat=carrier_bits)
            if np.array_equal(matrix @ np.array(candidate) % 2, message)
        )
        stego = np.array(ac.stc_embed(cover.tolist(), message.tolist(), costs.tolist(), height))
        assert np.array_equal(matrix @ stego % 2, message)
        assert float(costs[stego != cover].sum()) == pytest.approx(best)


def test_stc_needs_fewer_changes_than_direct_replacement_and_follows_costs():
    rng = np.random.default_rng(11)
    carrier_bits, message_bits = 6000, 3600
    cover = rng.integers(0, 2, carrier_bits).tolist()
    message = rng.integers(0, 2, message_bits).tolist()
    uniform = ac.stc_embed(cover, message, [1.0] * carrier_bits, 10)
    changes = sum(a != b for a, b in zip(cover, uniform))
    assert changes < 0.32 * message_bits  # direct replacement: ~0.5 per bit
    # Making half of the carriers expensive moves the changes to the cheap half.
    costs = [100.0 if index % 2 else 1.0 for index in range(carrier_bits)]
    weighted = ac.stc_embed(cover, message, costs, 10)
    expensive = sum(a != b for index, (a, b) in enumerate(zip(cover, weighted)) if index % 2)
    cheap = sum(a != b for index, (a, b) in enumerate(zip(cover, weighted)) if not index % 2)
    assert expensive < 0.1 * cheap


def test_stc_parameters_are_public_and_deterministic():
    assert ac.stc_columns(10, 5) == ac.stc_columns(10, 5)
    assert all(column & 1 and column >> 9 & 1 for column in ac.stc_columns(10, 40))
    widths = ac.stc_block_widths(300, 1001)
    assert sum(widths) == 1001 and min(widths) >= 3 and max(widths) <= 4


@pytest.mark.parametrize(
    "call",
    [
        lambda: ac.stc_block_widths(10, 9),
        lambda: ac.stc_embed([0, 1], [1, 2], [1.0, 1.0], 3),
        lambda: ac.stc_embed([0, 1], [1], [1.0], 3),
        lambda: ac.stc_embed([0, 1], [1], [1.0, float("nan")], 3),
        lambda: ac.stc_embed([0, 1], [1], [1.0, -1.0], 3),
        lambda: ac.stc_extract([0, 1], 1, 0),
        lambda: ac.stc_extract([0, 1], 1, 13),
        lambda: ac.stc_columns(4, 0),
    ],
)
def test_stc_rejects_invalid_input(call):
    with pytest.raises(ValueError):
        call()


# -- carrier-invariant costs ------------------------------------------------ #

def _toy_blocks(rng: np.random.Generator, macroblocks: int = 6):
    blocks = []
    positions = []
    for mb in range(macroblocks):
        for blk in range(16):
            levels = [0] * 16
            levels[0] = int(rng.integers(-9, 10))
            levels[1] = int(rng.choice([-1, 1]) * rng.integers(4, 30))
            levels[3] = int(rng.integers(-3, 4))
            levels[6] = int(rng.choice([-1, 1]))
            blocks.append((mb, blk, levels))
            positions.append((mb, blk, 1))
        blocks.append((mb, 16, [int(rng.integers(-5, 6))] + [0] * 15))  # chroma: ignored
    return blocks, positions


def _toggle_carriers(blocks, positions, mask):
    toggled = {(mb, blk): list(levels) for mb, blk, levels in blocks}
    for (mb, blk, index), flip in zip(positions, mask):
        if flip:
            value = toggled[(mb, blk)][index]
            toggled[(mb, blk)][index] = (abs(value) ^ 1) * (1 if value > 0 else -1)
    return [(mb, blk, toggled[(mb, blk)]) for mb, blk, _levels in blocks]


@pytest.mark.parametrize("model", ac.COST_MODELS)
def test_costs_are_invariant_under_any_carrier_modification(model):
    rng = np.random.default_rng(3)
    blocks, positions = _toy_blocks(rng)
    reference = ac.carrier_costs(positions, blocks, model)
    for _trial in range(5):
        mask = rng.integers(0, 2, len(positions))
        assert ac.carrier_costs(positions, _toggle_carriers(blocks, positions, mask), model) == reference
    assert all(cost > 0 for cost in reference)


def test_cost_model_prefers_large_levels_in_textured_macroblocks():
    smooth = [(0, blk, [0, 4] + [0] * 14) for blk in range(16)]
    textured = [(1, blk, [0, 4, 9, 7, -6, 3] + [0] * 10) for blk in range(16)]
    large = [(2, blk, [0, 40] + [0] * 14) for blk in range(16)]
    blocks = smooth + textured + large
    costs = ac.carrier_costs([(0, 0, 1), (1, 0, 1), (2, 0, 1)], blocks, "texture-magnitude-v1")
    assert costs[1] < costs[0] and costs[2] < costs[0]
    with pytest.raises(ValueError):
        ac.carrier_costs([(0, 0, 1)], blocks, "no-such-model")
    with pytest.raises(ValueError):
        ac.carrier_costs([(9, 0, 1)], blocks, "texture-magnitude-v1")


# -- contract ------------------------------------------------------------- #

def test_direct_contract_serialisation_and_profile_ids_are_unchanged():
    from src.lattice_zk import video_pipeline as pipeline
    from src.lattice_zk.params import BDLOP_OPEN_128

    assert [field.name for field in dataclasses.fields(BlindOperatingContract)] == [
        "version", "signbit_only", "bottom_rows", "dedup_per_block", "max_bits_per_idr",
        "metadata_bound", "require_bitstream_patchable", "patchability_headroom",
        "max_modifications_per_block", "stable_carriers_only",
    ]
    expected = {
        # Profile ids computed at commit 18c5123, before adaptive carriers existed.
        MAGNITUDE.version: "ff66b446eef5d8c5c9aa1312395dee5dd94487e5e902f573b89a025e574664b7",
        T1_SIGN.version: "f97e7878b023901a9c4d0a250d6da745d0b1ca8119a75e90334b279f5e6fac28",
    }
    profiles = {}
    for contract in (MAGNITUDE, T1_SIGN, AdaptiveOperatingContract()):
        profile = pipeline.CarrierProfile(contract, chunk_bytes=3800, registered=True)
        profiles[contract.version] = profile.profile_id(BDLOP_OPEN_128).hex()
    for version, digest in expected.items():
        assert profiles[version] == digest
    assert len(set(profiles.values())) == 3
    assert not is_syndrome_coded(MAGNITUDE) and not is_syndrome_coded(T1_SIGN)
    assert is_syndrome_coded(AdaptiveOperatingContract())


@pytest.mark.parametrize(
    "changes",
    [
        {"signbit_only": True},
        {"stable_carriers_only": False},
        {"require_bitstream_patchable": False},
        {"max_modifications_per_block": 2},
        {"dedup_per_block": False},
        {"max_bits_per_idr": 3},
        {"bottom_rows": 2},
        {"stc_constraint_height": 0},
        {"stc_constraint_height": 13},
        {"header_carriers_per_bit": 0},
        {"cost_model": "unknown"},
    ],
)
def test_coded_contract_rejects_unsupported_settings(changes):
    contract = dataclasses.replace(AdaptiveOperatingContract(), **changes)
    with pytest.raises(ValueError):
        blind_sync._require_coded_contract(contract)


def test_unknown_carrier_coding_is_refused():
    with pytest.raises(ValueError):
        is_syndrome_coded(dataclasses.replace(AdaptiveOperatingContract(), carrier_coding="ldpc"))


def test_layout_reserves_the_fixed_header_code_and_fails_closed():
    contract = AdaptiveOperatingContract()
    # Default: the header code has rate 1, so capacity equals the direct contract's.
    assert coded_carrier_layout(contract, 112 + 800, 912) == (112, 800)
    assert coded_carrier_layout(contract, 112 + 800, 2000) == (112, 1888)
    with pytest.raises(ValueError):
        coded_carrier_layout(contract, 112 + 800, 911)
    wide = dataclasses.replace(contract, header_carriers_per_bit=4)
    assert coded_carrier_layout(wide, 112 + 800, 2000) == (448, 1552)
    assert coded_carrier_layout(wide, 112, 448) == (448, 0)
    with pytest.raises(ValueError):
        coded_carrier_layout(wide, 112 + 800, 448 + 799)
    with pytest.raises(ValueError):
        coded_carrier_layout(contract, 100, 4000)


# -- coded envelope over a fake analysis ----------------------------------- #

def _fake_coded_video(monkeypatch, payload: bytes, carriers: int = 1800, seed: int = 5):
    rng = np.random.default_rng(seed)
    contract = AdaptiveOperatingContract()
    blocks = [
        (index // 16, index % 16, [0, int(rng.choice([-1, 1]) * rng.integers(4, 40))] + [0] * 14)
        for index in range(carriers)
    ]
    order = rng.permutation(carriers)
    positions = [(int(blocks[i][0]), int(blocks[i][1]), 1) for i in order]
    monkeypatch.setattr(
        blind_sync, "derive_blind_positions_operating_contract",
        lambda *_args, **_kwargs: (list(positions), None),
    )
    envelope = pack_blind_payload(payload)
    stego_bits = syndrome_code_envelope(envelope, positions, blocks, contract)
    levels = {(mb, blk): list(values) for mb, blk, values in blocks}
    changed = 0
    for (mb, blk, index), bit in zip(positions, stego_bits):
        value = levels[(mb, blk)][index]
        if abs(value) & 1 != bit:
            levels[(mb, blk)][index] = (abs(value) ^ 1) * (1 if value > 0 else -1)
            changed += 1
    return contract, positions, levels, changed, len(envelope) * 8


def _frame_data(levels):
    return {0: ({key: {} for key in levels}, levels, b"")}


def test_coded_envelope_round_trips_through_the_extractor(monkeypatch):
    payload = os.urandom(120)
    contract, positions, levels, changed, envelope_bits = _fake_coded_video(monkeypatch, payload)
    result = blind_sync._extract_syndrome_coded_payload("fake.h264", b"k", contract, _frame_data(levels))
    assert result.payload == payload
    assert result.carrier_positions == tuple(positions)
    assert result.carriers_used == len(positions)
    assert changed < 0.4 * envelope_bits


def test_empty_payload_uses_only_the_header_code(monkeypatch):
    contract, _positions, levels, _changed, _bits = _fake_coded_video(monkeypatch, b"", carriers=600)
    result = blind_sync._extract_syndrome_coded_payload("fake.h264", b"k", contract, _frame_data(levels))
    assert result.payload == b""


@pytest.mark.parametrize("region", ["header", "body"])
def test_flipping_a_coded_carrier_is_detected(monkeypatch, region):
    contract, positions, levels, _changed, _bits = _fake_coded_video(monkeypatch, os.urandom(120))
    target = positions[10] if region == "header" else positions[-10]
    value = levels[target[:2]][target[2]]
    levels[target[:2]][target[2]] = (abs(value) ^ 1) * (1 if value > 0 else -1)
    with pytest.raises(ValueError):
        blind_sync._extract_syndrome_coded_payload("fake.h264", b"k", contract, _frame_data(levels))


def test_missing_carrier_fails_closed(monkeypatch):
    contract, positions, levels, _changed, _bits = _fake_coded_video(monkeypatch, os.urandom(40))
    del levels[positions[-1][:2]]
    with pytest.raises(ValueError, match="missing"):
        blind_sync._extract_syndrome_coded_payload("fake.h264", b"k", contract, _frame_data(levels))


def test_too_few_carriers_for_the_envelope_is_refused(monkeypatch):
    payload = os.urandom(400)
    with pytest.raises(ValueError, match="insufficient"):
        _fake_coded_video(monkeypatch, payload, carriers=1500)


# -- real video ------------------------------------------------------------ #

def _cut(tmp_path: Path, frames: int) -> Path:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not available")
    cover = tmp_path / f"cover_{frames}.h264"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", str(ROOT / COVER),
         "-frames:v", str(frames), "-c", "copy", str(cover)],
        check=True,
    )
    return cover


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.needs_data(COVER)
def test_direct_carriers_produce_byte_identical_stego(tmp_path):
    from src.core.analysis_cache import clear_video_analysis_cache

    cover = _cut(tmp_path, 3)
    if _sha256(cover) != "2667960243232a2574a6a3bab5772f8846f33d6c056e712d90a4ade55f63ed47":
        pytest.skip("this ffmpeg cuts a different cover; reference digests do not apply")
    # Output digests recorded with the code of commit 18c5123.
    expected = {
        "magnitude": "64febf3682373301465c9d061fb167e3c871620cd38b4a8d9ead23a54c41c264",
        "t1": "73e8ebd8e7a1016793d250ca3594c7e76c6cc631b9776eb78b03575cf04af8e7",
    }
    for name, contract in (("magnitude", MAGNITUDE), ("t1", T1_SIGN)):
        output = tmp_path / f"{name}.h264"
        embed_blind_video_payload(
            str(cover), str(output), bytes(range(96)), b"adaptive-regression-key", contract
        )
        clear_video_analysis_cache()
        assert _sha256(output) == expected[name]


@pytest.mark.needs_data(COVER)
def test_adaptive_carriers_round_trip_from_the_stego_video_alone(tmp_path):
    from src.core.analysis_cache import clear_video_analysis_cache, load_or_build_video_analysis

    cover = _cut(tmp_path, 4)
    stego = tmp_path / "stego.h264"
    payload = os.urandom(150)
    contract = AdaptiveOperatingContract(cost_model="texture-magnitude-v1")
    envelope_bits = len(pack_blind_payload(payload)) * 8
    embedded = embed_blind_video_payload(str(cover), str(stego), payload, b"sync", contract)
    embed_positions, _ = derive_coded_carrier_positions(str(cover), b"sync", envelope_bits, contract)
    cover_costs = ac.carrier_costs(
        embed_positions, load_or_build_video_analysis(cover, stable_blind_only=True)[0],
        "texture-magnitude-v1",
    )
    clear_video_analysis_cache()

    extracted = extract_blind_video_payload(str(stego), b"sync", contract)
    stego_costs = ac.carrier_costs(
        list(extracted.carrier_positions),
        load_or_build_video_analysis(stego, stable_blind_only=True)[0],
        "texture-magnitude-v1",
    )
    clear_video_analysis_cache()
    assert extracted.payload == payload
    assert list(extracted.carrier_positions) == embed_positions
    assert embedded.carriers_used == len(embed_positions)
    assert stego_costs == cover_costs
    # Far fewer changes than the ~envelope_bits / 2 of direct replacement.
    assert 0 < embedded.modified_carriers < 0.42 * envelope_bits
    assert _sha256(stego) != _sha256(cover)

    with pytest.raises(ValueError):
        extract_blind_video_payload(str(stego), b"other-key", contract)
    clear_video_analysis_cache()
    # The direct magnitude contract does not read an adaptive envelope.
    with pytest.raises(ValueError):
        extract_blind_video_payload(str(stego), b"sync", MAGNITUDE)
    clear_video_analysis_cache()


@pytest.mark.needs_data(COVER)
def test_adaptive_segmented_context_matches_extraction(tmp_path):
    from src.blind_payload_chunks import pack_payload_chunks
    from src.blind_sync_streaming import (
        derive_chunked_video_context,
        embed_chunked_video_payload,
        extract_chunked_video_payload,
    )

    cover = _cut(tmp_path, 8)
    stego = tmp_path / "stego.h264"
    payload = os.urandom(240)
    contract = AdaptiveOperatingContract()
    chunks = pack_payload_chunks(payload, chunk_size=130)
    assert len(chunks) == 2
    context = derive_chunked_video_context(cover, chunks, b"sync", contract, frames_per_segment=4)
    embedded = embed_chunked_video_payload(
        cover, stego, payload, b"sync", contract, frames_per_segment=4, chunk_size=130
    )
    extracted = extract_chunked_video_payload(stego, b"sync", contract, frames_per_segment=4)
    assert extracted.payload == payload
    assert extracted.global_positions == context.global_positions
    assert extracted.positions_hash == context.positions_hash
    assert extracted.canonical_video_sha256 == context.canonical_video_sha256
    assert embedded.carriers_used == extracted.carriers_used == len(context.global_positions)
