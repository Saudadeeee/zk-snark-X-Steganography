"""Session enforcement around blind extraction of the LNP22 video envelope."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE_DIR = ROOT / "benchmark" / "lnp22_context_probe"
if str(PROBE_DIR) not in sys.path:
    sys.path.insert(0, str(PROBE_DIR))

from video_e2e import (
    DEMO_PAYLOAD,
    _verify_from_video,
    encode_video_probe_payload,
    make_video_probe_statement,
)

from src.zkp_sessions import SessionChallengeStore


def _patch_extracted_video(
    monkeypatch,
    *,
    challenge: bytes,
    relation_pin: str,
    proof_valid: bool = True,
):
    positions_hash = "31" * 32
    canonical_video_hash = "42" * 32
    statement = make_video_probe_statement(
        session_id=challenge,
        payload=DEMO_PAYLOAD,
        canonical_video_sha256=canonical_video_hash,
        positions_hash=positions_hash,
        relation_sha256=relation_pin,
    )
    proof = b"LNPF\x01" + b"\x00" * 6
    encoded = encode_video_probe_payload(statement, proof, DEMO_PAYLOAD)
    monkeypatch.setattr(
        "video_e2e.extract_chunked_video_payload",
        lambda *_args, **_kwargs: SimpleNamespace(
            payload=encoded,
            positions_hash=positions_hash,
            canonical_video_sha256=canonical_video_hash,
            carriers_used=123,
        ),
    )
    go_calls = []

    def fake_go(args, *, stdin, **_kwargs):
        go_calls.append((args, stdin))
        return {"valid": proof_valid, "verify_ms": 1.25}

    monkeypatch.setattr("video_e2e._run_go", fake_go)
    return go_calls


def _verify(video: Path, relation: Path, relation_pin: str, store, binding: bytes):
    return _verify_from_video(
        video,
        relation_path=relation,
        trusted_relation_sha256=relation_pin,
        sync_key=b"s" * 32,
        session_store=store,
        session_context_binding=binding,
    )


def test_video_challenge_is_consumed_once_after_blind_proof_verification(
    monkeypatch, tmp_path
):
    relation_pin = "53" * 32
    binding = b"b" * 32
    store = SessionChallengeStore(tmp_path / "sessions.sqlite3", ttl_seconds=60)
    grant = store.issue(context_binding=binding)
    go_calls = _patch_extracted_video(
        monkeypatch, challenge=grant.challenge, relation_pin=relation_pin
    )
    video = tmp_path / "received.h264"

    # The prover's local round-trip may check cryptography, but has no access to
    # the verifier-owned store and must not consume the challenge.
    local_result = _verify_from_video(
        video,
        relation_path=tmp_path / "relation.json",
        trusted_relation_sha256=relation_pin,
        sync_key=b"s" * 32,
    )
    assert local_result["valid"] is True
    assert local_result["session_replay_protected"] is False
    assert store.is_active(grant.challenge, context_binding=binding)

    result = _verify(video, tmp_path / "relation.json", relation_pin, store, binding)

    assert result["valid"] is True
    assert result["session_replay_protected"] is True
    assert len(go_calls) == 2
    with pytest.raises(ValueError, match="session|challenge"):
        _verify(video, tmp_path / "relation.json", relation_pin, store, binding)
    assert len(go_calls) == 2


def test_video_with_unissued_session_is_rejected_before_proof_verifier(
    monkeypatch, tmp_path
):
    relation_pin = "64" * 32
    binding = b"w" * 32
    store = SessionChallengeStore(tmp_path / "sessions.sqlite3", ttl_seconds=60)
    store.issue(context_binding=binding)
    video_challenge = b"x" * 32
    go_calls = _patch_extracted_video(
        monkeypatch, challenge=video_challenge, relation_pin=relation_pin
    )

    with pytest.raises(ValueError, match="session|challenge"):
        _verify(
            tmp_path / "received.h264",
            tmp_path / "relation.json",
            relation_pin,
            store,
            binding,
        )
    assert go_calls == []


def test_rejected_proof_does_not_consume_the_video_session(monkeypatch, tmp_path):
    relation_pin = "86" * 32
    binding = b"f" * 32
    store = SessionChallengeStore(tmp_path / "sessions.sqlite3", ttl_seconds=60)
    grant = store.issue(context_binding=binding)
    _patch_extracted_video(
        monkeypatch,
        challenge=grant.challenge,
        relation_pin=relation_pin,
        proof_valid=False,
    )

    with pytest.raises(ValueError, match="session|challenge"):
        _verify(
            tmp_path / "received.h264",
            tmp_path / "relation.json",
            relation_pin,
            store,
            binding,
        )
    assert store.is_active(grant.challenge, context_binding=binding)


def test_expired_video_session_is_rejected_before_proof_verifier(
    monkeypatch, tmp_path
):
    relation_pin = "75" * 32
    binding = b"e" * 32
    store = SessionChallengeStore(tmp_path / "sessions.sqlite3", ttl_seconds=1)
    grant = store.issue(context_binding=binding, now=1)
    go_calls = _patch_extracted_video(
        monkeypatch, challenge=grant.challenge, relation_pin=relation_pin
    )

    with pytest.raises(ValueError, match="session|challenge"):
        _verify(
            tmp_path / "received.h264",
            tmp_path / "relation.json",
            relation_pin,
            store,
            binding,
        )
    assert go_calls == []
