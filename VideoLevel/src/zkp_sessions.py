"""Durable, one-use verifier challenges for future video-ZK sessions.

This module provides session policy state only. It is not a proof verifier and
must not be used to accept the repository's research-only lattice artifacts.
The caller supplies a verifier-owned 32-byte context binding (for example,
the digest of the pinned relation, parameters, registry, and codec policy).
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

_CHALLENGE_SIZE = 32
_SQLITE_INTEGER_MAX = (1 << 63) - 1
_CHALLENGE_DIGEST_DOMAIN = b"zkstego/video-zk/session-challenge/v1\x00"


@dataclass(frozen=True)
class SessionGrant:
    """Public challenge returned by a verifier session-issuance endpoint."""

    challenge: bytes
    issued_at: int
    expires_at: int

    def to_dict(self) -> dict[str, int | str]:
        """Return the canonical JSON-friendly public grant fields."""
        return {
            "challenge": self.challenge.hex(),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
        }


class SessionChallengeStore:
    """SQLite-backed issue/expiry/replay state for one verifier host.

    `verify_and_consume` should be called only after the caller has parsed the
    in-band proof and independently checked its relation, video context, and
    registry policy. It preflights the session before invoking expensive proof
    verification, then atomically consumes the challenge if it is still live.
    A shared durable database is required across all workers of one verifier;
    separate databases or `:memory:` do not provide cross-worker replay safety.
    """

    def __init__(self, database_path: str | Path, *, ttl_seconds: int = 300) -> None:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
            raise TypeError("ttl_seconds must be an integer")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be a positive integer")
        if ttl_seconds > _SQLITE_INTEGER_MAX:
            raise ValueError("ttl_seconds exceeds the SQLite integer range")

        path = Path(database_path).expanduser()
        if str(database_path) == ":memory:":
            raise ValueError("a durable SQLite path is required for replay protection")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = path
        self.ttl_seconds = ttl_seconds
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS zkp_session_challenges (
                    challenge_digest BLOB PRIMARY KEY
                        CHECK (length(challenge_digest) = 32),
                    context_binding BLOB NOT NULL
                        CHECK (length(context_binding) = 32),
                    issued_at INTEGER NOT NULL CHECK (issued_at >= 0),
                    expires_at INTEGER NOT NULL CHECK (expires_at > issued_at),
                    consumed_at INTEGER,
                    CHECK (consumed_at IS NULL OR consumed_at >= issued_at)
                );
                CREATE INDEX IF NOT EXISTS zkp_session_expiry_idx
                    ON zkp_session_challenges(expires_at);
                """
            )

    @staticmethod
    def _timestamp(now: int | None) -> int:
        value = int(time.time()) if now is None else now
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("now must be an integer Unix timestamp in seconds")
        if value < 0:
            raise ValueError("now must be a non-negative Unix timestamp in seconds")
        return value

    @staticmethod
    def _validate_context_binding(context_binding: bytes) -> bytes:
        if not isinstance(context_binding, bytes):
            raise TypeError("context_binding must be bytes")
        if len(context_binding) != 32:
            raise ValueError("context_binding must be exactly 32 bytes")
        return context_binding

    @staticmethod
    def _challenge_digest(challenge: bytes) -> bytes | None:
        if not isinstance(challenge, bytes) or len(challenge) != _CHALLENGE_SIZE:
            return None
        return hashlib.sha256(_CHALLENGE_DIGEST_DOMAIN + challenge).digest()

    def issue(
        self,
        *,
        context_binding: bytes,
        now: int | None = None,
    ) -> SessionGrant:
        """Issue and persist a fresh challenge bound to verifier policy."""
        binding = self._validate_context_binding(context_binding)
        issued_at = self._timestamp(now)
        expires_at = issued_at + self.ttl_seconds
        if expires_at > _SQLITE_INTEGER_MAX:
            raise ValueError("session expiry exceeds the SQLite integer range")

        for _attempt in range(4):
            challenge = secrets.token_bytes(_CHALLENGE_SIZE)
            digest = hashlib.sha256(_CHALLENGE_DIGEST_DOMAIN + challenge).digest()
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    # Expired challenges are unusable regardless of whether
                    # their replay tombstone remains in the table.
                    connection.execute(
                        "DELETE FROM zkp_session_challenges WHERE expires_at <= ?",
                        (issued_at,),
                    )
                    connection.execute(
                        """INSERT INTO zkp_session_challenges
                           (challenge_digest, context_binding, issued_at, expires_at)
                           VALUES (?, ?, ?, ?)""",
                        (digest, binding, issued_at, expires_at),
                    )
                    connection.commit()
                    return SessionGrant(challenge, issued_at, expires_at)
                except sqlite3.IntegrityError:
                    connection.rollback()

        raise RuntimeError("could not allocate a unique session challenge")

    def is_active(
        self,
        challenge: bytes,
        *,
        context_binding: bytes,
        now: int | None = None,
    ) -> bool:
        """Check issuance, context binding, and expiry without consuming."""
        digest = self._challenge_digest(challenge)
        if digest is None:
            return False
        if not isinstance(context_binding, bytes) or len(context_binding) != 32:
            return False
        timestamp = self._timestamp(now)

        with self._connection() as connection:
            row = connection.execute(
                """SELECT 1 FROM zkp_session_challenges
                   WHERE challenge_digest = ? AND context_binding = ?
                     AND consumed_at IS NULL AND expires_at > ?""",
                (digest, context_binding, timestamp),
            ).fetchone()
        return row is not None

    def consume(
        self,
        challenge: bytes,
        *,
        context_binding: bytes,
        now: int | None = None,
    ) -> bool:
        """Atomically mark a live, correctly bound challenge as spent."""
        digest = self._challenge_digest(challenge)
        if digest is None:
            return False
        if not isinstance(context_binding, bytes) or len(context_binding) != 32:
            return False
        timestamp = self._timestamp(now)

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """UPDATE zkp_session_challenges SET consumed_at = ?
                   WHERE challenge_digest = ? AND context_binding = ?
                     AND consumed_at IS NULL AND expires_at > ?""",
                (timestamp, digest, context_binding, timestamp),
            )
            connection.commit()
        return cursor.rowcount == 1

    def verify_and_consume(
        self,
        challenge: bytes,
        *,
        context_binding: bytes,
        verify: Callable[[bytes, bytes], bool],
        now: int | None = None,
    ) -> bool:
        """Run proof verification for a live challenge and spend it once.

        The callback receives the exact challenge and context binding and must
        verify that the video statement contains those verifier-pinned values,
        as well as checking the proof and all other policy. Failed verification,
        a wrong binding, or an expired/unknown challenge leaves the session
        unspent. Concurrent successful callers race on the final SQLite update;
        only one can receive `True`.
        """
        if not callable(verify):
            raise TypeError("verify must be callable")
        preflight_time = self._timestamp(now)
        if not self.is_active(
            challenge,
            context_binding=context_binding,
            now=preflight_time,
        ):
            return False
        if verify(challenge, context_binding) is not True:
            return False
        return self.consume(
            challenge,
            context_binding=context_binding,
            # With a real clock, re-check after potentially expensive proof
            # verification so a challenge cannot be accepted past expiry.
            now=now,
        )
