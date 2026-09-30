"""Real-video test for re-deriving payload carriers from the stego video alone."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.blind_sync import (
    BlindOperatingContract,
    _stable_candidate_index,
    derive_blind_positions_operating_contract,
    embed_blind_video_payload,
    extract_blind_video_payload,
    pack_blind_payload,
)
from src.core.analysis_cache import (
    load_or_build_reconstruction_context,
    load_or_build_video_analysis,
)
from src.core.pipeline import _extract_bits_from_decoded_analysis, extract_bits_direct
from src.runtest._helpers import get_video
from src.video_canonicalization import canonical_video_sha256


def test_stable_carrier_choice_survives_lsb_toggle():
    coefficients = [0, 3, 0, 4, 5] + [0] * 11
    assert _stable_candidate_index(coefficients, set()) == 3

    coefficients[3] = 5
    assert _stable_candidate_index(coefficients, set()) == 3


def test_sidecar_free_embed_refuses_to_overwrite_existing_output(tmp_path):
    output = tmp_path / "already-there.h264"
    original_bytes = b"keep-existing-output"
    output.write_bytes(original_bytes)
    contract = BlindOperatingContract(
        require_bitstream_patchable=True,
        stable_carriers_only=True,
    )

    with pytest.raises(FileExistsError):
        embed_blind_video_payload(
            "missing-cover.h264",
            str(output),
            b"payload",
            b"sync-key",
            contract,
        )

    assert output.read_bytes() == original_bytes


def test_stable_signbit_profile_derives_one_trailing_sign_per_block(monkeypatch):
    from src.blind_sync import derive_blind_positions_operating_contract

    fake_analysis = (
        [(0, 0, [0] * 16), (1, 0, [0] * 16)],
        {},
        {},
        {(0, 0): 8, (1, 0): 8},
        {},
        [(0, 0, -15), (0, 0, -14), (1, 0, -15), (1, 0, 7)],
    )
    monkeypatch.setattr(
        "src.blind_sync.load_or_build_video_analysis",
        lambda *_args, **_kwargs: fake_analysis,
    )
    contract = BlindOperatingContract(
        signbit_only=True,
        require_bitstream_patchable=True,
        max_modifications_per_block=1,
        stable_carriers_only=True,
    )

    positions, metadata = derive_blind_positions_operating_contract(
        "fixture.h264", b"session-seed", 2, contract, use_analysis_cache=False
    )

    assert len(positions) == 2
    assert all(coefficient_index < 0 for _, _, coefficient_index in positions)
    assert {(macroblock, block) for macroblock, block, _ in positions} == {
        (0, 0),
        (1, 0),
    }
    assert metadata.analysis_profile == "full-v1"
    assert metadata.stable_candidate_count == 3


def test_stego_video_alone_rederives_carriers_and_extracts_payload():
    source = get_video("foreman_cif_g8_300f_b800k.h264")
    payload = bytes.fromhex("5a17c09e31b46d82")
    envelope = pack_blind_payload(payload)
    payload_bits = len(envelope) * 8
    session_challenge = bytes(range(32))
    sync_key = hashlib.sha256(
        b"zkstego/pq-video/carrier-order-seed/v1\x00" + session_challenge
    ).digest()
    contract = BlindOperatingContract(
        version="stable-carriers-video-only-v1",
        signbit_only=True,
        require_bitstream_patchable=True,
        patchability_headroom=64,
        max_modifications_per_block=1,
        stable_carriers_only=True,
    )

    with TemporaryDirectory(prefix="zkstego-blind-video-only-") as temp:
        root = Path(temp)
        output_dir = root / "stego"
        output_dir.mkdir()
        stego_path = output_dir / "carrier.h264"

        embedded = embed_blind_video_payload(
            source,
            str(stego_path),
            payload,
            sync_key,
            contract,
        )
        assert embedded.carriers_used == payload_bits

        assert [path.name for path in output_dir.iterdir()] == ["carrier.h264"]
        extracted = extract_blind_video_payload(
            str(stego_path), sync_key, contract
        )
        assert extracted.payload == payload
        assert all(position[2] < 0 for position in extracted.carrier_positions)
        assert extracted.metadata.candidate_fingerprint == embedded.metadata.candidate_fingerprint
        assert extracted.carriers_used == embedded.carriers_used

        # On an actual stego stream, the fast path must match direct CAVLC
        # decoding for the exact blind-selected carrier sequence.
        analysis = load_or_build_video_analysis(stego_path, use_cache=True)
        parser = load_or_build_reconstruction_context(
            stego_path, use_cache=True
        )["parser"]
        extraction_args = {
            "stego_video_path": str(stego_path),
            "embed_safe_positions": list(extracted.carrier_positions),
            "frame_verified_data": analysis[1],
            "nC_map": analysis[2],
            "payload_bits": extracted.carriers_used,
            "max_modifications_per_block": contract.max_modifications_per_block,
            "parser": parser,
        }
        fast_envelope = _extract_bits_from_decoded_analysis(**extraction_args)
        direct_envelope = extract_bits_direct(**extraction_args)
        assert fast_envelope == direct_envelope == pack_blind_payload(payload)

        cover_positions, _ = derive_blind_positions_operating_contract(
            source, sync_key, payload_bits, contract, use_analysis_cache=True
        )
        stego_positions, _ = derive_blind_positions_operating_contract(
            str(stego_path), sync_key, payload_bits, contract, use_analysis_cache=True
        )
        assert cover_positions == stego_positions
        assert canonical_video_sha256(source, cover_positions) == canonical_video_sha256(
            stego_path, stego_positions
        )

        # The video-only statement boundary must derive the same carriers
        # itself from verifier-pinned session/configuration, not accept a
        # prover-supplied position list. This validates context binding only;
        # no ZK proof backend is invoked here.
        from src.lattice_pq import LatticeSigner
        from src.manifest import hash_positions
        from src.video_zkp_contract import (
            build_video_zkp_statement,
            carrier_policy_hash,
            payload_commitment,
            policy_hash,
            verify_video_zkp_context_binding_video_only,
        )
        from src.zkp_registry import SignedZkpRelationRegistry

        policy = {
            "codec": "h264-baseline-cavlc",
            "embedding_strategy": "t1_sign_flip",
            "max_modifications_per_block": contract.max_modifications_per_block,
            "proof_backend": "lattice",
            "carrier_profile_hash": carrier_policy_hash(contract, payload_bits),
        }
        policy_digest = policy_hash(policy)
        descriptor = {
            "zkp_suite": "lazer-v1",
            "constraint_module_hash": "11" * 32,
            "verifier_key_hash": "22" * 32,
            "parameter_set_hash": "33" * 32,
            "policy_hash": policy_digest,
        }
        issuer_public_key, issuer_private_key = LatticeSigner.generate_keypair()
        registry = SignedZkpRelationRegistry.create(epoch=12, relations=[descriptor]).sign(
            issuer_private_key, signer_id="issuer-v1"
        )
        relation_id = registry.relations[0].relation_id
        statement = build_video_zkp_statement(
            session_id=session_challenge,
            payload_commitment_hex=payload_commitment(payload, b"o" * 32),
            cover_hash=hashlib.sha256(Path(source).read_bytes()).hexdigest(),
            stego_hash=canonical_video_sha256(stego_path, stego_positions),
            positions_hash=hash_positions(stego_positions),
            relation_id=relation_id,
            registry_root=registry.root(),
            registry_epoch=registry.epoch,
            policy=policy,
        )
        assert verify_video_zkp_context_binding_video_only(
            statement,
            registry,
            issuer_public_key,
            video_path=str(stego_path),
            expected_session_id=session_challenge,
            required_bits=payload_bits,
            carrier_contract=contract,
            expected_relation_id=relation_id,
            expected_policy_hash=policy_digest,
            minimum_epoch=10,
        ) == (registry.root(), registry.epoch)

        # Truncation changes the independently derived carrier universe; the
        # extractor must fail closed rather than return arbitrary payload bytes.
        truncated_path = root / "truncated.h264"
        stego_bytes = stego_path.read_bytes()
        truncated_path.write_bytes(stego_bytes[: len(stego_bytes) // 2])
        with pytest.raises((ValueError, RuntimeError, EOFError)):
            extract_blind_video_payload(
                str(truncated_path), sync_key, contract
            )
