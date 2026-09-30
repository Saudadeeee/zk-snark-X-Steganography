"""Tests for verifier-issued one-use session challenges."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from src.zkp_sessions import SessionChallengeStore


def test_issued_challenge_has_fixed_length_binding_and_expiry(tmp_path) -> None:
    store = SessionChallengeStore(tmp_path / "sessions.sqlite3", ttl_seconds=30)

    grant = store.issue(context_binding=b"c" * 32, now=1_000)

    assert len(grant.challenge) == 32
    assert grant.issued_at == 1_000
    assert grant.expires_at == 1_030
    assert grant.to_dict() == {
        "challenge": grant.challenge.hex(),
        "issued_at": 1_000,
        "expires_at": 1_030,
    }


def test_failed_proof_does_not_spend_challenge_but_valid_proof_is_one_use(
    tmp_path,
) -> None:
    path = tmp_path / "sessions.sqlite3"
    binding = b"p" * 32
    grant = SessionChallengeStore(path, ttl_seconds=60).issue(
        context_binding=binding,
        now=100,
    )
    store = SessionChallengeStore(path, ttl_seconds=60)

    assert not store.verify_and_consume(
        grant.challenge,
        context_binding=binding,
        verify=lambda _challenge, _binding: False,
        now=101,
    )
    assert store.verify_and_consume(
        grant.challenge,
        context_binding=binding,
        verify=lambda received_challenge, received_binding: (
            received_challenge == grant.challenge and received_binding == binding
        ),
        now=102,
    )

    restarted_store = SessionChallengeStore(path, ttl_seconds=60)
    assert not restarted_store.verify_and_consume(
        grant.challenge,
        context_binding=binding,
        verify=lambda _challenge, _binding: True,
        now=103,
    )


def test_challenge_expires_at_boundary_without_running_verifier(tmp_path) -> None:
    store = SessionChallengeStore(tmp_path / "sessions.sqlite3", ttl_seconds=10)
    grant = store.issue(context_binding=b"b" * 32, now=20)
    verifier_calls = []

    accepted = store.verify_and_consume(
        grant.challenge,
        context_binding=b"b" * 32,
        verify=lambda _challenge, _binding: verifier_calls.append(True) or True,
        now=grant.expires_at,
    )

    assert not accepted
    assert verifier_calls == []


def test_challenge_that_expires_during_verification_is_not_consumed(
    tmp_path,
    monkeypatch,
) -> None:
    store = SessionChallengeStore(tmp_path / "sessions.sqlite3", ttl_seconds=10)
    grant = store.issue(context_binding=b"e" * 32, now=20)
    times = iter((29, 30))
    monkeypatch.setattr("src.zkp_sessions.time.time", lambda: next(times))

    accepted = store.verify_and_consume(
        grant.challenge,
        context_binding=b"e" * 32,
        verify=lambda _challenge, _binding: True,
    )

    assert not accepted


def test_wrong_context_binding_does_not_consume_challenge(tmp_path) -> None:
    store = SessionChallengeStore(tmp_path / "sessions.sqlite3", ttl_seconds=30)
    grant = store.issue(context_binding=b"a" * 32, now=500)

    assert not store.verify_and_consume(
        grant.challenge,
        context_binding=b"x" * 32,
        verify=lambda _challenge, _binding: True,
        now=501,
    )
    assert store.verify_and_consume(
        grant.challenge,
        context_binding=b"a" * 32,
        verify=lambda _challenge, _binding: True,
        now=502,
    )


def test_unknown_and_malformed_challenges_fail_closed(tmp_path) -> None:
    store = SessionChallengeStore(tmp_path / "sessions.sqlite3", ttl_seconds=30)
    verifier_calls = []

    for challenge in (b"u" * 32, b"short"):
        assert not store.verify_and_consume(
            challenge,
            context_binding=b"b" * 32,
            verify=lambda _challenge, _binding: verifier_calls.append(True) or True,
            now=100,
        )

    assert verifier_calls == []


def test_concurrent_verification_consumes_challenge_at_most_once(tmp_path) -> None:
    store = SessionChallengeStore(tmp_path / "sessions.sqlite3", ttl_seconds=30)
    binding = b"r" * 32
    grant = store.issue(context_binding=binding, now=100)

    def verify_once(_: int) -> bool:
        return store.verify_and_consume(
            grant.challenge,
            context_binding=binding,
            verify=lambda _challenge, _binding: True,
            now=101,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(verify_once, range(16)))

    assert sum(results) == 1


def test_store_requires_durable_path_and_positive_integer_ttl(tmp_path) -> None:
    with pytest.raises(ValueError, match="durable SQLite path"):
        SessionChallengeStore(":memory:")
    with pytest.raises(TypeError, match="ttl_seconds must be an integer"):
        SessionChallengeStore(tmp_path / "sessions.sqlite3", ttl_seconds=True)
    with pytest.raises(ValueError, match="positive integer"):
        SessionChallengeStore(tmp_path / "sessions.sqlite3", ttl_seconds=0)
