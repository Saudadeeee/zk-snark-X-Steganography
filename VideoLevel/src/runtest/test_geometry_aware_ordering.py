"""Resolution-aware carrier order (``src.core.carrier_order``) and compatibility.

* picture geometry from the SPS at CIF, 4CIF, 720p and 1080p;
* ``order_carriers``: a keyed permutation, independent of the input order,
  bottom rows of each slot first, slots interleaved round-robin, slots of
  ``W x H`` macroblocks (not 396), slot-relative zones for multi-slice pictures;
* the original contracts are unchanged: carrier profile ids, and on a short
  CIF cut of a checked-in fixture and a short synthetic 4CIF clip their
  positions hash, canonical digest and stego bytes, all recorded with the code
  of commit c027c87 before the change;
* the geometry contracts have new profile ids, recompute the embedding order
  from the stego, and round-trip a registered lattice proof on a short
  multi-slice 720p clip.
"""

from __future__ import annotations

import dataclasses
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmark.latticezk_video_e2e import CARRIER_CONTRACTS
from src.transport import blind_sync_streaming as transport
from src.transport.blind_payload_chunks import pack_payload_chunks
from src.transport.blind_sync import (
    GeometryOrderedAdaptiveContract,
    GeometryOrderedOperatingContract,
    derive_blind_positions_operating_contract,
)
from src.core.analysis_cache import clear_video_analysis_cache, load_or_build_reconstruction_context
from src.core.carrier_order import (
    CIF_GEOMETRY,
    SPS_GEOMETRY_ORDER_V1,
    PictureGeometry,
    contract_carrier_order,
    geometry_from_sps,
    order_carriers,
    priority_rows,
)
from src.core.chaos import ChaosTransformer
from src.registry.lattice_pq import LatticeSigner
from src.lattice_zk import bdlop, codec
from src.lattice_zk import video_pipeline as pipeline
from src.lattice_zk.params import BDLOP_OPEN_128, BDLOP_OPEN_128_V2, TOY
from src.registry.zkp_registry import SignedZkpRelationRegistry

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "data" / "external" / "trust_corpus" / "mdn_friday_cif_q22_g1_30f.h264"
KEY = bytes(range(32))
ORIGINAL = ("magnitude", "t1", "adaptive")
GEOMETRY = ("magnitude-geo", "t1-geo", "adaptive-geo")

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg and ffprobe are required",
)

# Carrier profile ids recorded with commit c027c87 (before the change).
ORIGINAL_PROFILE_IDS = {
    ("magnitude", "BDLOP_OPEN_128", True): "93f63501a96424681ccb85c0c5c4ce221e5297f9baee9e6e1ed677b8a567734c",
    ("magnitude", "BDLOP_OPEN_128", False): "9f35b9e80d376184ba66839fc3fb5e1b7b794d2fc96469f566903c379e1c9532",
    ("magnitude", "TOY", True): "ec341daed1e9bcfeab58f0ef3e1cdce780ad6acd0963058159ef8503f708b28d",
    ("t1", "BDLOP_OPEN_128", True): "5df8d4bfa5f8c10f5263475545f81e2a23dce13f9cd2e0d57aba9643ed6c10bd",
    ("t1", "TOY", True): "491141f4c53ae449e8e5d3cf9d81e2c364d3e87cb716f9f70eac74c417ce8c81",
    ("adaptive", "BDLOP_OPEN_128", True): "a871de208faee08b3a0f43cd470cba7ee4d50ac915486257521e5a85cb397a0a",
    ("adaptive", "TOY", True): "3d65bfb395ed10e56614147336d318b89d23ea174ff2d7d135abc6d9e2c78f51",
    ("adaptive-texture", "BDLOP_OPEN_128", True): "482fc180c6d6829f43d30147a930a149df7c2983bb348c957c0326df3b13a7b0",
}
# The ids were recorded when the production set was bdlop-open-128-v2.
PARAMETER_SETS = {"BDLOP_OPEN_128": BDLOP_OPEN_128_V2, "TOY": TOY}

# Transport digests of the original contracts recorded with commit c027c87.
BASELINE_PAYLOAD = (b"geometry-aware carrier order baseline payload " * 8)
CIF_CUT = {
    "frames": 20, "frames_per_segment": 10, "chunk": 16, "payload": 32,
    "sha256": "9545a50e3246157b8ef6cac3a8dfc4538af68d6351c5794fd98d3fb6520191ca",
    "pins": {
        "magnitude": {
            "positions_hash": "d857c66b7cf01ac42388ca182710f4650442723304f1781c0d964cf84b655352",
            "canonical_video_sha256": "09ca9a16e8de55ebb99d6d8342710b5f97d3752a82dbfbbe0d914b72b2f04bec",
            "stego_sha256": "af2c5a5c1d332461a29e5385956d140d0e5ca68ff08d2846d673a855a325c790",
        },
        "t1": {
            "positions_hash": "fb707d87bac11475aba442af0bb12b5aa6d0d5140a7471a169d5fd5535dedea7",
            "canonical_video_sha256": "8870d84203ab47b941bf80fd64c913437eba1f1b17a392e1afa4e5c42e6e1fb5",
            "stego_sha256": "6ca774ed4d77080c3dda4b6356e94e81c716f6ce445f762fbf756ea22358e5f2",
        },
        "adaptive": {
            "positions_hash": "a33f41a607d58bc75c909fa551c1b979191dcc6f6649170d3d75685800d2f5bf",
            "canonical_video_sha256": "35dc52d531d94d9c881dfe599ef850b0c8e9c05eba58cc5eced722702a0268cc",
            "stego_sha256": "4bd750d799e9e793ba237566be72341db334ea2a38392bbb82e7e15fad325a14",
        },
    },
}
SYNTH_4CIF = {
    "frames": 2, "frames_per_segment": 1, "chunk": 10, "payload": 20,
    "sha256": "a169b220a9ac426d2b4ff65b99af995773bd80209ada5068703385e94b341337",
    "pins": {
        "magnitude": {
            "positions_hash": "e8a71b9c0d3a455b87cf7fb2e2495f720750594f4267d00c0f063b405f53e6e8",
            "canonical_video_sha256": "c2a3843e3b7863cc28f47a845e28035abec26d3929f19fd3c9e87df23955f2cb",
            "stego_sha256": "7ddd863d92751508e02bbc2653c56ff286bc9147742f0b499c0cdee65f10a41e",
        },
        "adaptive": {
            "positions_hash": "965f6c5bb80002433c943e2085026f5dd1d813774296ebb4d0c567a36b6eccd5",
            "canonical_video_sha256": "9257e97fbdb4f4d9ee76bafa5624e46d0cb06ad5f8688cc2259e5848a91a7e24",
            "stego_sha256": "5d7cc188d42ae6e1a4dec66c1dfa80e9dcd5d922fcec6f38430173ca55a05e21",
        },
        # t1 recorded as well (a3489422...); not re-run here: the sign-bit
        # analysis of this noise clip takes ~3 min.  The CIF cut covers t1.
    },
}


# --------------------------------------------------------------------------- #
def _encode(path: Path, size: str, frames: int, *, noise: int, slices: int = 1,
            qp: int = 22) -> Path:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-f", "lavfi",
        "-i", f"testsrc2=size={size}:rate=25,noise=alls={noise}:allf=t",
        "-frames:v", str(frames), "-pix_fmt", "yuv420p", "-c:v", "libx264",
        "-profile:v", "baseline", "-coder", "0", "-bf", "0", "-g", "1", "-keyint_min", "1",
        "-sc_threshold", "0", "-qp", str(qp), "-threads", "1",
    ]
    if slices > 1:
        command += ["-x264-params", f"slices={slices}"]
    subprocess.run(command + ["-f", "h264", str(path)], check=True, timeout=300)
    return path


def _cut(source: Path, target: Path, frames: int) -> Path:
    sys.path.insert(0, str(ROOT / "scripts"))
    from repro import cut_annexb  # noqa: PLC0415

    assert cut_annexb(source, target, frames) == frames
    return target


# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("width, height", [(22, 18), (44, 36), (80, 45), (120, 68)])
def test_geometry_from_sps_fields(width, height) -> None:
    sps = SimpleNamespace(pic_width_in_mbs_minus1=width - 1,
                          pic_height_in_map_units_minus1=height - 1, frame_mbs_only_flag=1)
    geometry = geometry_from_sps(sps)
    assert (geometry.width_mbs, geometry.height_mbs) == (width, height)
    assert geometry.mbs_per_picture == width * height


def test_geometry_refuses_missing_or_interlaced_sps() -> None:
    with pytest.raises(ValueError):
        geometry_from_sps(None)
    with pytest.raises(ValueError):
        geometry_from_sps(SimpleNamespace(pic_width_in_mbs_minus1=21,
                                          pic_height_in_map_units_minus1=8,
                                          frame_mbs_only_flag=0))
    with pytest.raises(ValueError):
        PictureGeometry(0, 18)


@needs_ffmpeg
@pytest.mark.parametrize("size, expected", [
    ("352x288", (22, 18)), ("704x576", (44, 36)), ("1280x720", (80, 45)), ("1920x1080", (120, 68)),
])
def test_geometry_from_encoded_sps(tmp_path, size, expected) -> None:
    clip = _encode(tmp_path / f"{size}.h264", size, 1, noise=0)
    context = load_or_build_reconstruction_context(clip, use_cache=False)
    geometry = geometry_from_sps(context["sps"])
    assert (geometry.width_mbs, geometry.height_mbs) == expected
    assert context["mb_count_per_slice"] == geometry.mbs_per_picture


def test_priority_rows_scale_the_cif_zone() -> None:
    assert [priority_rows(rows) for rows in (18, 36, 45, 68)] == [4, 8, 10, 15]
    assert priority_rows(1) == 1 and priority_rows(12) == 3
    with pytest.raises(ValueError):
        priority_rows(0)


# --------------------------------------------------------------------------- #
def _grid(geometry: PictureGeometry, slots: int, step: int = 3) -> list[tuple[int, int, int]]:
    return [(mb, block, 5) for mb in range(0, slots * geometry.mbs_per_picture, step)
            for block in (0, 7)]


def test_order_is_a_keyed_permutation_independent_of_input_order() -> None:
    geometry = PictureGeometry(80, 45)
    positions = _grid(geometry, 3)
    ordered = order_carriers(positions, geometry, KEY)
    assert sorted(ordered) == sorted(positions)
    assert order_carriers(list(reversed(positions)), geometry, KEY) == ordered
    assert order_carriers(positions, geometry, KEY) == ordered
    assert order_carriers(positions, geometry, b"other key") != ordered
    assert order_carriers([], geometry, KEY) == []
    with pytest.raises(ValueError):
        order_carriers(positions, geometry, b"")


@pytest.mark.parametrize("width, height", [(22, 18), (44, 36), (80, 45), (120, 68)])
def test_bottom_rows_first_and_pictures_round_robin(width, height) -> None:
    geometry = PictureGeometry(width, height)
    slots = 3
    positions = _grid(geometry, slots, step=1)
    ordered = order_carriers(positions, geometry, KEY)
    per_picture = geometry.mbs_per_picture
    # Strict round robin over pictures (equal-size slots here).
    assert [mb // per_picture for mb, _b, _c in ordered[: 3 * slots]] == [0, 1, 2] * 3
    zone = priority_rows(height) * width * 2  # carriers in the low-drift zone per picture
    head = ordered[: zone * slots]
    assert all((mb % per_picture) // width >= height - priority_rows(height) for mb, _b, _c in head)
    assert any((mb % per_picture) // width < height - priority_rows(height)
               for mb, _b, _c in ordered[zone * slots:])


def test_cif_grid_order_misplaces_larger_pictures() -> None:
    """The original order groups 396-MB "frames"; the new one groups real pictures."""
    geometry = PictureGeometry(80, 45)
    positions = _grid(geometry, 2, step=1)
    legacy = ChaosTransformer(KEY).shuffle_positions(list(positions))
    legacy_rows = [(mb % 3600) // 80 for mb, _b, _c in legacy[: len(legacy) // 5]]
    new_rows = [(mb % 3600) // 80 for mb, _b, _c in order_carriers(positions, geometry, KEY)[
        : len(positions) // 5]]
    assert min(new_rows) >= 45 - priority_rows(45)
    assert min(legacy_rows) < 10  # CIF "bottom rows" are stripes all over a 720p picture


def test_multi_slice_slots_use_their_own_bottom_rows() -> None:
    geometry = PictureGeometry(80, 45)
    per_picture = geometry.mbs_per_picture
    # Two slices of one picture: rows 0-21 in slot 0, rows 22-44 in slot 1.
    positions = [(row * 80 + column, 0, 3) for row in range(22) for column in range(80)]
    positions += [(per_picture + row * 80 + column, 0, 3) for row in range(22, 45)
                  for column in range(80)]
    ordered = order_carriers(positions, geometry, KEY)
    first_slot0 = [(mb % per_picture) // 80 for mb, _b, _c in ordered if mb < per_picture][:80]
    assert min(first_slot0) >= 22 - priority_rows(22)


def test_contract_carrier_order_selection() -> None:
    for name in ORIGINAL + ("adaptive-texture",):
        assert contract_carrier_order(CARRIER_CONTRACTS[name]) is None
    for name in GEOMETRY:
        assert contract_carrier_order(CARRIER_CONTRACTS[name]) == SPS_GEOMETRY_ORDER_V1
    with pytest.raises(ValueError):
        contract_carrier_order(GeometryOrderedOperatingContract(carrier_order="raster"))
    assert CIF_GEOMETRY.mbs_per_picture == 396


def test_geometry_contracts_mirror_the_original_carrier_rules() -> None:
    for original, geometry in zip(ORIGINAL, GEOMETRY):
        old = dataclasses.asdict(CARRIER_CONTRACTS[original])
        new = dataclasses.asdict(CARRIER_CONTRACTS[geometry])
        assert new.pop("carrier_order") == SPS_GEOMETRY_ORDER_V1
        assert new.pop("version") != old.pop("version")
        assert new == old
    assert isinstance(CARRIER_CONTRACTS["adaptive-geo"], GeometryOrderedAdaptiveContract)


# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("key", sorted(ORIGINAL_PROFILE_IDS))
def test_original_profile_ids_are_unchanged(key) -> None:
    carrier, parameter_set, registered = key
    profile = pipeline.CarrierProfile(
        CARRIER_CONTRACTS[carrier], registered=registered, codec_policy=pipeline.CODEC_POLICY_V1
    )
    assert profile.profile_id(PARAMETER_SETS[parameter_set]).hex() == ORIGINAL_PROFILE_IDS[key]


def test_geometry_profiles_have_new_ids_and_relations() -> None:
    ids = {name: pipeline.CarrierProfile(contract, registered=True).profile_id(BDLOP_OPEN_128)
           for name, contract in CARRIER_CONTRACTS.items()}
    assert len(set(ids.values())) == len(ids)
    for name in GEOMETRY:
        assert ids[name].hex() not in ORIGINAL_PROFILE_IDS.values()
    old = pipeline.CarrierProfile(CARRIER_CONTRACTS["magnitude"])
    new = pipeline.CarrierProfile(CARRIER_CONTRACTS["magnitude-geo"])
    assert pipeline.policy_hash(TOY, old) != pipeline.policy_hash(TOY, new)
    assert pipeline.public_sync_key(TOY, old) != pipeline.public_sync_key(TOY, new)


# --------------------------------------------------------------------------- #
def _transport_pins(clip: Path, carrier: str, frames_per_segment: int, chunk: int,
                    payload: bytes, tmp_path: Path) -> dict[str, str]:
    contract = CARRIER_CONTRACTS[carrier]
    clear_video_analysis_cache()
    chunks = pack_payload_chunks(payload, chunk_size=chunk)
    context = transport.derive_chunked_video_context(
        clip, chunks, KEY, contract, frames_per_segment=frames_per_segment
    )
    stego = tmp_path / f"stego_{carrier}.h264"
    transport.embed_chunked_video_payload(
        clip, stego, payload, KEY, contract, frames_per_segment=frames_per_segment, chunk_size=chunk
    )
    clear_video_analysis_cache()
    return {
        "positions_hash": context.positions_hash,
        "canonical_video_sha256": context.canonical_video_sha256,
        "stego_sha256": hashlib.sha256(stego.read_bytes()).hexdigest(),
    }


@pytest.fixture(scope="module")
def cif_cut(tmp_path_factory):
    if not FIXTURE.is_file():
        pytest.skip("checked-in CIF fixture missing")
    return _cut(FIXTURE, tmp_path_factory.mktemp("cif") / "cif_cut.h264", CIF_CUT["frames"])


@pytest.fixture(scope="module")
def synthetic_4cif(tmp_path_factory):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg and ffprobe are required")
    clip = _encode(tmp_path_factory.mktemp("4cif") / "synthetic_4cif.h264", "704x576",
                   SYNTH_4CIF["frames"], noise=20)
    if hashlib.sha256(clip.read_bytes()).hexdigest() != SYNTH_4CIF["sha256"]:
        pytest.skip("this ffmpeg/x264 build encodes a different synthetic 4CIF cover")
    return clip


@needs_ffmpeg
@pytest.mark.parametrize("carrier", ORIGINAL)
def test_original_contracts_byte_identical_on_cif_cut(cif_cut, carrier, tmp_path) -> None:
    assert hashlib.sha256(cif_cut.read_bytes()).hexdigest() == CIF_CUT["sha256"]
    payload = BASELINE_PAYLOAD[: CIF_CUT["payload"]]
    pins = _transport_pins(cif_cut, carrier, CIF_CUT["frames_per_segment"], CIF_CUT["chunk"],
                           payload, tmp_path)
    assert pins == CIF_CUT["pins"][carrier]


@needs_ffmpeg
@pytest.mark.parametrize("carrier", ["magnitude", "adaptive"])
def test_original_contracts_byte_identical_on_4cif(synthetic_4cif, carrier, tmp_path) -> None:
    payload = BASELINE_PAYLOAD[: SYNTH_4CIF["payload"]]
    pins = _transport_pins(synthetic_4cif, carrier, SYNTH_4CIF["frames_per_segment"],
                           SYNTH_4CIF["chunk"], payload, tmp_path)
    assert pins == SYNTH_4CIF["pins"][carrier]


@needs_ffmpeg
def test_geometry_order_differs_and_is_recomputed_from_the_stego(synthetic_4cif, tmp_path) -> None:
    """Same carrier set as the original, other order; extraction reproduces it."""
    clear_video_analysis_cache()
    segment = synthetic_4cif
    old, _ = derive_blind_positions_operating_contract(
        str(segment), KEY, 10**7, CARRIER_CONTRACTS["magnitude"])
    new, _ = derive_blind_positions_operating_contract(
        str(segment), KEY, 10**7, CARRIER_CONTRACTS["magnitude-geo"])
    assert sorted(old) == sorted(new) and old != new
    zone_start = 36 - priority_rows(36)
    head = new[: len(new) // 10]
    assert all((mb % 1584) // 44 >= zone_start for mb, _b, _c in head)
    payload = b"4CIF geometry payload"[:20]  # two 10-byte chunks fit one picture each
    stego = tmp_path / "stego_geo.h264"
    contract = CARRIER_CONTRACTS["magnitude-geo"]
    clear_video_analysis_cache()
    context = transport.derive_chunked_video_context(
        segment, pack_payload_chunks(payload, chunk_size=10), KEY, contract, frames_per_segment=1)
    transport.embed_chunked_video_payload(
        segment, stego, payload, KEY, contract, frames_per_segment=1, chunk_size=10)
    clear_video_analysis_cache()
    extracted = transport.extract_chunked_video_payload(stego, KEY, contract, frames_per_segment=1)
    assert extracted.payload == payload
    assert extracted.global_positions == context.global_positions
    assert extracted.positions_hash == context.positions_hash
    clear_video_analysis_cache()


@needs_ffmpeg
@pytest.mark.parametrize("carrier", ["t1-geo", "adaptive-geo"])
def test_geometry_contracts_round_trip_on_cif_cut(cif_cut, carrier, tmp_path) -> None:
    contract = CARRIER_CONTRACTS[carrier]
    payload = b"geometry contract payload"
    stego = tmp_path / f"stego_{carrier}.h264"
    clear_video_analysis_cache()
    transport.embed_chunked_video_payload(
        cif_cut, stego, payload, KEY, contract, frames_per_segment=CIF_CUT["frames"], chunk_size=32)
    clear_video_analysis_cache()
    extracted = transport.extract_chunked_video_payload(
        stego, KEY, contract, frames_per_segment=CIF_CUT["frames"])
    assert extracted.payload == payload
    clear_video_analysis_cache()


@needs_ffmpeg
def test_registered_proof_round_trip_on_multi_slice_720p(tmp_path) -> None:
    # Low QP: most coded blocks get a |level| >= 4 carrier, so one picture holds the
    # 413-byte TOY envelope.
    cover = _encode(tmp_path / "hd720_s4.h264", "1280x720", 1, noise=12, slices=4, qp=10)
    profile = pipeline.CarrierProfile(
        CARRIER_CONTRACTS["magnitude-geo"], frames_per_segment=1, chunk_bytes=480, registered=True,
    )
    randomness = bdlop.sample_randomness(TOY)
    commitment = bdlop.commit(TOY, codec.encode_payload(TOY, b"720p credential"), randomness)
    public, private = LatticeSigner.generate_keypair()
    registry = SignedZkpRelationRegistry.create(
        epoch=1, relations=[pipeline.relation_descriptor(TOY, profile, commitment)]
    ).sign(private, signer_id="geometry-order-test")
    pins = pipeline.pins_from_registry(
        registry, public, TOY, profile, minimum_epoch=1, allow_toy_parameters=True,
        credential=commitment,
    )
    session = bytes(range(32, 64))
    stego = tmp_path / "stego720.h264"
    clear_video_analysis_cache()
    embedded = pipeline.embed_video_proof(
        cover, stego, None, params=TOY, pins=pins, profile=profile, session_challenge=session,
        sync_key=KEY, credential=pipeline.Credential(commitment, randomness),
    )
    clear_video_analysis_cache()
    result = pipeline.verify_video_proof(
        stego, params=TOY, pins=pins, profile=profile, sync_key=KEY, expected_session=session,
        credential=commitment, allow_toy_parameters=True,
    )
    assert result.valid, result.reason
    assert result.statement_id == embedded.statement_id
    # The original-order profile is a different relation: its pins do not verify this video.
    clear_video_analysis_cache()
    other = dataclasses.replace(profile, contract=CARRIER_CONTRACTS["magnitude"])
    with pytest.raises(ValueError):
        pipeline.verify_video_proof(
            stego, params=TOY, pins=pins, profile=other, sync_key=KEY, expected_session=session,
            credential=commitment, allow_toy_parameters=True,
        )
    clear_video_analysis_cache()
