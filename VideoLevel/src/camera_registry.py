"""Registry of authorized cameras: a Poseidon Merkle tree the camera proof opens.

Each camera holds a private field element ``s`` and is registered by its public
key ``pk = Poseidon(s)``. The registry is a depth-16 binary Merkle tree whose
nodes are ``Poseidon(left, right)`` and whose unused leaves are 0, matching
``MerkleInclusion`` in ``circuits/camera_video.circom``. Verifiers trust only
the root; the proof hides which leaf (camera) produced it.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from src.poseidon import FIELD_MODULUS, poseidon

TREE_DEPTH = 16
REGISTRY_SCHEMA = "zkstego-camera-registry-1"
SECRET_SCHEMA = "zkstego-camera-secret-1"


@lru_cache(maxsize=None)
def _empty_subtree_roots(depth: int) -> tuple[int, ...]:
    roots = [0]
    for _ in range(depth):
        roots.append(poseidon([roots[-1], roots[-1]]))
    return tuple(roots)


def camera_public_key(secret: int) -> int:
    return poseidon([secret])


def new_camera_secret() -> int:
    """A uniformly random non-zero BN254 scalar."""
    return secrets.randbelow(FIELD_MODULUS - 1) + 1


@dataclass(frozen=True)
class MerklePath:
    siblings: tuple[int, ...]
    path_indices: tuple[int, ...]


class CameraRegistry:
    """Immutable registry built from public keys (leaf ``i`` = ``public_keys[i]``)."""

    def __init__(self, public_keys: list[int], depth: int = TREE_DEPTH) -> None:
        if depth <= 0 or len(public_keys) > 1 << depth:
            raise ValueError("registry holds at most 2**depth cameras")
        if any(type(key) is not int or not 0 < key < FIELD_MODULUS for key in public_keys):
            raise ValueError("camera public keys must be non-zero BN254 field elements")
        if len(set(public_keys)) != len(public_keys):
            raise ValueError("a camera public key is registered twice")
        self.depth = depth
        self.public_keys = tuple(public_keys)
        empty = _empty_subtree_roots(depth)
        self._levels: list[list[int]] = [list(public_keys)]
        for level in range(depth):
            nodes = self._levels[-1]
            parents = [poseidon([nodes[i], nodes[i + 1] if i + 1 < len(nodes) else empty[level]])
                       for i in range(0, len(nodes), 2)]
            self._levels.append(parents)
        self.root = self._levels[depth][0] if public_keys else empty[depth]

    def index_of(self, public_key: int) -> int:
        try:
            return self.public_keys.index(public_key)
        except ValueError as exc:
            raise ValueError("camera is not registered") from exc

    def path(self, index: int) -> MerklePath:
        if not 0 <= index < len(self.public_keys):
            raise ValueError("registry index is out of range")
        empty = _empty_subtree_roots(self.depth)
        siblings, indices = [], []
        for level in range(self.depth):
            nodes = self._levels[level]
            sibling = index ^ 1
            siblings.append(nodes[sibling] if sibling < len(nodes) else empty[level])
            indices.append(index & 1)
            index >>= 1
        return MerklePath(tuple(siblings), tuple(indices))

    def to_json(self) -> dict:
        return {"schema": REGISTRY_SCHEMA, "depth": self.depth, "root": hex(self.root),
                "public_keys": [hex(key) for key in self.public_keys]}

    @classmethod
    def from_json(cls, data: dict) -> CameraRegistry:
        if data.get("schema") != REGISTRY_SCHEMA:
            raise ValueError(f"registry must use schema {REGISTRY_SCHEMA!r}")
        registry = cls([int(key, 16) for key in data["public_keys"]], int(data["depth"]))
        if hex(registry.root) != data.get("root"):
            raise ValueError("registry root does not match its public keys")
        return registry

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_json(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> CameraRegistry:
        return cls.from_json(json.loads(Path(path).read_text(encoding="utf-8")))


def save_camera_secret(secret: int, path: Path) -> None:
    """Write a camera secret to a new owner-only file (never overwrites an existing one)."""
    descriptor = os.open(Path(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump({"schema": SECRET_SCHEMA, "secret": hex(secret)}, handle)


def load_camera_secret(path: Path) -> int:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != SECRET_SCHEMA:
        raise ValueError(f"camera secret must use schema {SECRET_SCHEMA!r}")
    secret = int(data["secret"], 16)
    if not 0 < secret < FIELD_MODULUS:
        raise ValueError("camera secret is not a BN254 scalar")
    return secret
