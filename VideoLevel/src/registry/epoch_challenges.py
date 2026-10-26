"""Offline replay protection: issuer-signed epoch challenges.

The interactive protocol gives every verifier its own one-use challenge
(:mod:`zkp_sessions`).  That needs a round trip before embedding and a live
verifier.  This module is the offline alternative: the registry issuer
publishes one ML-DSA-65 signed challenge per time window (an *epoch beacon*),
the holder binds the video statement to the current beacon's challenge, and any
verifier that trusts the issuer checks the video without contacting anyone.

What it does and does not give:

* **Freshness.**  A beacon is valid for ``max_age_epochs`` windows after its
  epoch; a video bound to an older beacon is rejected, so an attacker cannot
  replay a years-old video.
* **Per-verifier replay protection.**  A verifier records the statement id of
  every video it accepted under a beacon (:class:`OfflineReplayLedger`); the
  same video shown again to the same verifier is rejected.  Showing it to
  another verifier within the window is accepted: offline verifiers do not
  share state.  Use the interactive session store when that matters.
* **No interaction.**  The holder needs only the published beacon; the
  verifier needs the issuer key, the beacon and its own clock.

The challenge is ``SHA-256(domain || epoch_index || window || nonce ||
signer_id)``: deterministic from the signed fields, so the verifier recomputes
it and never trusts a challenge read from the video.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import struct
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pqcrypto.sign import ml_dsa_65

from .lattice_pq import LatticeSigner

EPOCH_CHALLENGE_PROTOCOL = "zkstego/video-zk/epoch-challenge/v1"
_DOMAIN = b"zkstego/video-zk/epoch-challenge/v1\0"
NONCE_BYTES = 32
DEFAULT_WINDOW_SECONDS = 3600
DEFAULT_MAX_AGE_EPOCHS = 24
# A beacon for the next window is accepted this many windows early, so a
# verifier whose clock lags the issuer around a window boundary still works.
DEFAULT_SKEW_EPOCHS = 1
MAX_SIGNER_ID_BYTES = 64
_U64_MAX = (1 << 64) - 1
_SQLITE_INTEGER_MAX = (1 << 63) - 1


def _require_u64(name: str, value: object, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= _U64_MAX:
        raise ValueError(f"{name} must be an integer in [{minimum}, 2^64)")
    return value


def _require_signer_id(signer_id: object) -> str:
    if not isinstance(signer_id, str) or not signer_id or not signer_id.isascii():
        raise ValueError("signer_id must be a non-empty ASCII string")
    if len(signer_id) > MAX_SIGNER_ID_BYTES:
        raise ValueError("signer_id is too long")
    return signer_id


def epoch_index_at(timestamp: int, window_seconds: int) -> int:
    """Epoch index of a Unix timestamp for a window length."""
    _require_u64("timestamp", timestamp)
    _require_u64("window_seconds", window_seconds, minimum=1)
    return timestamp // window_seconds


@dataclass(frozen=True)
class EpochChallenge:
    """One issuer-signed challenge for one time window."""

    epoch_index: int
    window_seconds: int
    nonce: bytes
    signer_id: str
    signature: bytes | None = None

    def __post_init__(self) -> None:
        _require_u64("epoch_index", self.epoch_index)
        _require_u64("window_seconds", self.window_seconds, minimum=1)
        if not isinstance(self.nonce, bytes) or len(self.nonce) != NONCE_BYTES:
            raise ValueError(f"nonce must be exactly {NONCE_BYTES} bytes")
        _require_signer_id(self.signer_id)
        if self.signature is not None and (
            not isinstance(self.signature, bytes) or len(self.signature) != ml_dsa_65.SIGNATURE_SIZE
        ):
            raise ValueError("signature must be an ML-DSA-65 signature")

    def _fields(self) -> bytes:
        signer = self.signer_id.encode("ascii")
        return (
            struct.pack(">QQ", self.epoch_index, self.window_seconds) + self.nonce
            + struct.pack(">H", len(signer)) + signer
        )

    @property
    def challenge(self) -> bytes:
        """32-byte session challenge the video statement binds."""
        return hashlib.sha256(_DOMAIN + b"challenge\0" + self._fields()).digest()

    def _signing_bytes(self) -> bytes:
        return _DOMAIN + b"signature\0" + self._fields()

    @classmethod
    def issue(
        cls, private_key: bytes, *, epoch_index: int, window_seconds: int = DEFAULT_WINDOW_SECONDS,
        signer_id: str = "issuer", nonce: bytes | None = None,
    ) -> EpochChallenge:
        """Sign a fresh challenge for ``epoch_index``."""
        nonce = secrets.token_bytes(NONCE_BYTES) if nonce is None else nonce
        unsigned = cls(epoch_index, window_seconds, nonce, signer_id)
        signature = LatticeSigner.sign(private_key, unsigned._signing_bytes())
        return cls(epoch_index, window_seconds, nonce, signer_id, signature)

    @classmethod
    def issue_now(
        cls, private_key: bytes, *, window_seconds: int = DEFAULT_WINDOW_SECONDS,
        signer_id: str = "issuer", now: int | None = None,
    ) -> EpochChallenge:
        timestamp = int(time.time()) if now is None else now
        return cls.issue(
            private_key, epoch_index=epoch_index_at(timestamp, window_seconds),
            window_seconds=window_seconds, signer_id=signer_id,
        )

    def verify(self, public_key: bytes) -> bool:
        """Check the issuer signature; ``False`` for an unsigned beacon."""
        if self.signature is None:
            return False
        try:
            return LatticeSigner.verify(public_key, self._signing_bytes(), self.signature)
        except (TypeError, ValueError):
            return False

    def is_current(
        self, *, now: int | None = None, max_age_epochs: int = DEFAULT_MAX_AGE_EPOCHS,
        skew_epochs: int = DEFAULT_SKEW_EPOCHS,
    ) -> bool:
        """``True`` iff the beacon is at most ``skew_epochs`` windows in the future and not expired."""
        _require_u64("max_age_epochs", max_age_epochs)
        _require_u64("skew_epochs", skew_epochs)
        timestamp = int(time.time()) if now is None else _require_u64("now", now)
        current = epoch_index_at(timestamp, self.window_seconds)
        return self.epoch_index <= current + skew_epochs and current <= self.epoch_index + max_age_epochs

    def expires_at(self, max_age_epochs: int) -> int:
        """First timestamp at which the beacon is no longer current."""
        _require_u64("max_age_epochs", max_age_epochs)
        return (self.epoch_index + max_age_epochs + 1) * self.window_seconds

    def to_dict(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "protocol": EPOCH_CHALLENGE_PROTOCOL,
            "epoch_index": self.epoch_index,
            "window_seconds": self.window_seconds,
            "nonce": self.nonce.hex(),
            "signer_id": self.signer_id,
            "challenge": self.challenge.hex(),
        }
        if self.signature is not None:
            record["signature"] = self.signature.hex()
        return record

    @classmethod
    def from_dict(cls, record: dict[str, Any]) -> EpochChallenge:
        if not isinstance(record, dict) or record.get("protocol") != EPOCH_CHALLENGE_PROTOCOL:
            raise ValueError("not an epoch challenge record")
        try:
            nonce = bytes.fromhex(record["nonce"])
            signature = bytes.fromhex(record["signature"]) if "signature" in record else None
            beacon = cls(record["epoch_index"], record["window_seconds"], nonce, record["signer_id"], signature)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"malformed epoch challenge record: {error}") from None
        # The challenge field is informational; a record that disagrees with
        # its own signed fields is rejected rather than silently recomputed.
        if "challenge" in record and record["challenge"] != beacon.challenge.hex():
            raise ValueError("epoch challenge record carries a challenge that does not match its fields")
        return beacon


class OfflineReplayLedger:
    """SQLite record of the statements one verifier accepted under each beacon.

    A statement id names one exact stego video under one challenge, so a
    second acceptance of the same id is a replay.  Each row records when its
    beacon stops being current under the ledger's settings and is pruned only
    after that; by then such videos are rejected before this ledger is
    consulted.  The settings are stored in the database and a ledger opened
    with different ones is refused, so pruning can never run ahead of beacon
    expiry.
    """

    def __init__(
        self, database_path: str | Path, *, window_seconds: int = DEFAULT_WINDOW_SECONDS,
        max_age_epochs: int = DEFAULT_MAX_AGE_EPOCHS,
    ) -> None:
        if str(database_path) == ":memory:":
            raise ValueError("a durable SQLite path is required for replay protection")
        _require_u64("window_seconds", window_seconds, minimum=1)
        _require_u64("max_age_epochs", max_age_epochs)
        if window_seconds * (max_age_epochs + 2) > _SQLITE_INTEGER_MAX:
            raise ValueError("window and age exceed the SQLite integer range")
        path = Path(database_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = path
        self.window_seconds = window_seconds
        self.max_age_epochs = max_age_epochs
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS zkp_epoch_ledger_meta (
                    key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS zkp_epoch_acceptances (
                    challenge_digest BLOB NOT NULL,
                    statement_id BLOB NOT NULL,
                    epoch_index INTEGER NOT NULL,
                    accepted_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    PRIMARY KEY (challenge_digest, statement_id)
                );
                CREATE INDEX IF NOT EXISTS zkp_epoch_acceptances_expiry
                    ON zkp_epoch_acceptances (expires_at);
                """
            )
            connection.execute("BEGIN IMMEDIATE")
            stored = dict(connection.execute("SELECT key, value FROM zkp_epoch_ledger_meta"))
            if not stored:
                connection.executemany(
                    "INSERT INTO zkp_epoch_ledger_meta (key, value) VALUES (?, ?)",
                    [("window_seconds", window_seconds), ("max_age_epochs", max_age_epochs)],
                )
            connection.commit()
        if stored and (
            stored.get("window_seconds") != window_seconds or stored.get("max_age_epochs") != max_age_epochs
        ):
            raise ValueError(
                "replay ledger was created with window_seconds="
                f"{stored.get('window_seconds')}, max_age_epochs={stored.get('max_age_epochs')}; "
                "open it with the same settings"
            )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        try:
            yield connection
        finally:
            connection.close()

    def _accept(self, beacon: EpochChallenge, statement_id: bytes, timestamp: int) -> bool:
        """Insert the acceptance; ``False`` if it was already there (replay)."""
        expires_at = beacon.expires_at(self.max_age_epochs)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            # Only rows whose beacon can no longer be current are dropped.
            connection.execute("DELETE FROM zkp_epoch_acceptances WHERE expires_at <= ?", (timestamp,))
            cursor = connection.execute(
                """INSERT OR IGNORE INTO zkp_epoch_acceptances
                   (challenge_digest, statement_id, epoch_index, accepted_at, expires_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (hashlib.sha256(beacon.challenge).digest(), statement_id, beacon.epoch_index,
                 timestamp, expires_at),
            )
            connection.commit()
        return cursor.rowcount == 1

    def verify_and_record(
        self, beacon: EpochChallenge, issuer_public_key: bytes, *,
        verify: Callable[[bytes], bytes | None], now: int | None = None,
    ) -> tuple[bool, str]:
        """Check the beacon, run ``verify(challenge)`` and record the acceptance once.

        ``verify`` receives the beacon's challenge and returns the accepted
        statement id (32 bytes) or ``None`` when the video is rejected.  The
        beacon must verify under ``issuer_public_key``, use this ledger's window
        and be current; a replayed statement id is rejected.
        """
        if not callable(verify):
            raise TypeError("verify must be callable")
        if not isinstance(beacon, EpochChallenge):
            return False, "epoch challenge is not an EpochChallenge"
        if beacon.window_seconds != self.window_seconds:
            return False, "epoch challenge window differs from the verifier ledger window"
        if not beacon.verify(issuer_public_key):
            return False, "epoch challenge signature did not verify against the issuer key"
        timestamp = int(time.time()) if now is None else _require_u64("now", now)
        if not beacon.is_current(now=timestamp, max_age_epochs=self.max_age_epochs):
            return False, "epoch challenge is expired or not yet valid"
        statement_id = verify(beacon.challenge)
        if statement_id is None:
            return False, "proof rejected"
        if not isinstance(statement_id, bytes) or len(statement_id) != 32:
            return False, "verifier returned a malformed statement id"
        if not self._accept(beacon, statement_id, timestamp):
            return False, "replay: this statement was already accepted under this epoch challenge"
        return True, "ok"


__all__ = [
    "DEFAULT_MAX_AGE_EPOCHS",
    "DEFAULT_SKEW_EPOCHS",
    "DEFAULT_WINDOW_SECONDS",
    "EPOCH_CHALLENGE_PROTOCOL",
    "EpochChallenge",
    "OfflineReplayLedger",
    "epoch_index_at",
]
