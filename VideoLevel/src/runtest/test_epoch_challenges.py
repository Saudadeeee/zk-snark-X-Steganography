"""Issuer-signed epoch challenges and the offline replay ledger."""

from __future__ import annotations

import pytest

from src.registry.epoch_challenges import (
    DEFAULT_WINDOW_SECONDS, EpochChallenge, OfflineReplayLedger, epoch_index_at,
)
from src.registry.lattice_pq import LatticeSigner

NOW = 1_800_000_000
WINDOW = 3600


@pytest.fixture(scope="module")
def issuer():
    public, private = LatticeSigner.generate_keypair()
    return public, private


@pytest.fixture(scope="module")
def beacon(issuer):
    _, private = issuer
    return EpochChallenge.issue_now(private, window_seconds=WINDOW, signer_id="issuer", now=NOW)


def test_epoch_index() -> None:
    assert epoch_index_at(NOW, WINDOW) == NOW // WINDOW
    assert epoch_index_at(0, DEFAULT_WINDOW_SECONDS) == 0
    with pytest.raises(ValueError):
        epoch_index_at(NOW, 0)
    with pytest.raises(ValueError):
        epoch_index_at(-1, WINDOW)


def test_beacon_signature_and_currency(issuer, beacon) -> None:
    public, _ = issuer
    assert beacon.epoch_index == NOW // WINDOW
    assert beacon.verify(public)
    assert not beacon.verify(LatticeSigner.generate_keypair()[0])
    assert not EpochChallenge(beacon.epoch_index, WINDOW, beacon.nonce, "issuer").verify(public)
    assert beacon.is_current(now=NOW) and beacon.is_current(now=NOW + 24 * WINDOW, max_age_epochs=24)
    assert not beacon.is_current(now=NOW + 25 * WINDOW, max_age_epochs=24)
    # One window of clock skew is tolerated by default; more is "the future".
    assert beacon.is_current(now=NOW - WINDOW)
    assert not beacon.is_current(now=NOW - WINDOW, skew_epochs=0)
    assert not beacon.is_current(now=NOW - 2 * WINDOW)
    assert beacon.expires_at(24) == (beacon.epoch_index + 25) * WINDOW
    assert len(beacon.challenge) == 32


def test_challenge_is_a_function_of_the_signed_fields(issuer, beacon) -> None:
    _, private = issuer
    same = EpochChallenge(beacon.epoch_index, WINDOW, beacon.nonce, "issuer")
    assert same.challenge == beacon.challenge  # the signature is not part of it
    other_nonce = EpochChallenge.issue(private, epoch_index=beacon.epoch_index, window_seconds=WINDOW)
    other_epoch = EpochChallenge.issue(
        private, epoch_index=beacon.epoch_index + 1, window_seconds=WINDOW, nonce=beacon.nonce
    )
    other_signer = EpochChallenge(beacon.epoch_index, WINDOW, beacon.nonce, "issuer2")
    assert len({beacon.challenge, other_nonce.challenge, other_epoch.challenge, other_signer.challenge}) == 4


def test_record_round_trip_and_rejections(beacon) -> None:
    record = beacon.to_dict()
    assert EpochChallenge.from_dict(record) == beacon
    assert record["challenge"] == beacon.challenge.hex()
    tampered = dict(record, challenge="00" * 32)
    with pytest.raises(ValueError):
        EpochChallenge.from_dict(tampered)
    with pytest.raises(ValueError):
        EpochChallenge.from_dict(dict(record, protocol="other"))
    with pytest.raises(ValueError):
        EpochChallenge.from_dict(dict(record, nonce="zz"))
    for bad in (
        dict(epoch_index=-1, window_seconds=WINDOW, nonce=beacon.nonce, signer_id="i"),
        dict(epoch_index=1, window_seconds=0, nonce=beacon.nonce, signer_id="i"),
        dict(epoch_index=1, window_seconds=WINDOW, nonce=b"short", signer_id="i"),
        dict(epoch_index=1, window_seconds=WINDOW, nonce=beacon.nonce, signer_id=""),
        dict(epoch_index=1, window_seconds=WINDOW, nonce=beacon.nonce, signer_id="i", signature=b"x"),
    ):
        with pytest.raises(ValueError):
            EpochChallenge(**bad)


def test_ledger_accepts_once_per_statement(tmp_path, issuer, beacon) -> None:
    public, _ = issuer
    ledger = OfflineReplayLedger(tmp_path / "ledger.sqlite", window_seconds=WINDOW, max_age_epochs=24)
    statement = b"\x11" * 32
    seen = []

    def verify(challenge: bytes) -> bytes | None:
        seen.append(challenge)
        return statement

    assert ledger.verify_and_record(beacon, public, verify=verify, now=NOW) == (True, "ok")
    assert seen == [beacon.challenge]
    replay = ledger.verify_and_record(beacon, public, verify=verify, now=NOW + 10)
    assert replay[0] is False and replay[1].startswith("replay")
    # Another statement under the same beacon is a different video: accepted.
    assert ledger.verify_and_record(beacon, public, verify=lambda _: b"\x22" * 32, now=NOW)[0]
    # The ledger survives reopening.
    reopened = OfflineReplayLedger(tmp_path / "ledger.sqlite", window_seconds=WINDOW, max_age_epochs=24)
    assert reopened.verify_and_record(beacon, public, verify=verify, now=NOW)[0] is False


def test_ledger_rejects_bad_beacons_before_verifying(tmp_path, issuer, beacon) -> None:
    public, private = issuer
    ledger = OfflineReplayLedger(tmp_path / "ledger.sqlite", window_seconds=WINDOW, max_age_epochs=24)
    calls = []

    def verify(challenge: bytes) -> bytes | None:
        calls.append(challenge)
        return b"\x33" * 32

    unsigned = EpochChallenge(beacon.epoch_index, WINDOW, beacon.nonce, "issuer")
    assert ledger.verify_and_record(unsigned, public, verify=verify, now=NOW)[0] is False
    other_key = LatticeSigner.generate_keypair()[0]
    assert ledger.verify_and_record(beacon, other_key, verify=verify, now=NOW)[0] is False
    expired = ledger.verify_and_record(beacon, public, verify=verify, now=NOW + 26 * WINDOW)
    assert expired == (False, "epoch challenge is expired or not yet valid")
    other_window = EpochChallenge.issue(private, epoch_index=NOW // 60, window_seconds=60)
    assert ledger.verify_and_record(other_window, public, verify=verify, now=NOW)[0] is False
    assert calls == []  # nothing reached proof verification
    rejected = ledger.verify_and_record(beacon, public, verify=lambda _: None, now=NOW)
    assert rejected == (False, "proof rejected")
    malformed = ledger.verify_and_record(beacon, public, verify=lambda _: b"short", now=NOW)
    assert malformed[0] is False


def test_ledger_prunes_old_epochs(tmp_path, issuer) -> None:
    public, private = issuer
    ledger = OfflineReplayLedger(tmp_path / "ledger.sqlite", window_seconds=WINDOW, max_age_epochs=2)
    old = EpochChallenge.issue(private, epoch_index=NOW // WINDOW, window_seconds=WINDOW)
    assert ledger.verify_and_record(old, public, verify=lambda _: b"\x44" * 32, now=NOW)[0]
    later = NOW + 5 * WINDOW
    new = EpochChallenge.issue(private, epoch_index=later // WINDOW, window_seconds=WINDOW)
    assert ledger.verify_and_record(new, public, verify=lambda _: b"\x55" * 32, now=later)[0]
    import sqlite3

    with sqlite3.connect(ledger.database_path) as connection:
        epochs = [row[0] for row in connection.execute("SELECT epoch_index FROM zkp_epoch_acceptances")]
    assert epochs == [later // WINDOW]


def test_ledger_refuses_memory_and_bad_parameters(tmp_path) -> None:
    with pytest.raises(ValueError):
        OfflineReplayLedger(":memory:")
    with pytest.raises(ValueError):
        OfflineReplayLedger(tmp_path / "x.sqlite", window_seconds=0)


def test_ledger_refuses_to_reopen_with_other_settings(tmp_path) -> None:
    path = tmp_path / "ledger.sqlite"
    OfflineReplayLedger(path, window_seconds=WINDOW, max_age_epochs=24)
    OfflineReplayLedger(path, window_seconds=WINDOW, max_age_epochs=24)  # same settings: fine
    with pytest.raises(ValueError, match="same settings"):
        OfflineReplayLedger(path, window_seconds=WINDOW, max_age_epochs=2)
    with pytest.raises(ValueError, match="same settings"):
        OfflineReplayLedger(path, window_seconds=60, max_age_epochs=24)


def test_ledger_keeps_rows_until_their_beacon_expires(tmp_path, issuer) -> None:
    """A row is never pruned while its beacon is still current (replay window)."""
    public, private = issuer
    ledger = OfflineReplayLedger(tmp_path / "ledger.sqlite", window_seconds=WINDOW, max_age_epochs=2)
    beacon = EpochChallenge.issue(private, epoch_index=NOW // WINDOW, window_seconds=WINDOW)
    assert ledger.verify_and_record(beacon, public, verify=lambda _: b"\x66" * 32, now=NOW)[0]
    # Two windows later the beacon is still current (max_age 2): the replay is still caught.
    late = NOW + 2 * WINDOW
    newer = EpochChallenge.issue(private, epoch_index=late // WINDOW, window_seconds=WINDOW)
    assert ledger.verify_and_record(newer, public, verify=lambda _: b"\x77" * 32, now=late)[0]
    replay = ledger.verify_and_record(beacon, public, verify=lambda _: b"\x66" * 32, now=late)
    assert replay[0] is False and replay[1].startswith("replay")
