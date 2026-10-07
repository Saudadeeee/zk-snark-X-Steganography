"""Sender and verifier sides of the camera proof (registry membership + video binding).

Sender (camera): ``build_payload`` computes the video digest of the *cover*
H.264 for the exact frame size the payload will have, binds it with the
message, proves membership of the camera in the registry and packs the
payload. The digest masks exactly the sign positions the stego key will carry
the frame in, and embedding changes only those, so the stego video has the
same digest.

Verifier: ``verify_payload`` unpacks an extracted payload, recomputes the
digest from the *stego* video, rebuilds the binding and checks the Groth16
proof against the trusted registry root. It needs the stego key (to extract
and to locate the carrier bits), the root and the verification key; never the
camera secret.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from src.camera_registry import CameraRegistry
from src.native_blind_contract import FRAME_HEADER_BYTES
from src.video_binding import (
    DIGEST_BYTES,
    MODE_MESSAGE_ONLY,
    MODE_VIDEO,
    binding_digest,
    native_video_digest,
)
from src.zk_proof import (
    CameraPayload,
    CameraProofBridge,
    bytes_to_proof,
    pack_payload,
    payload_size,
    proof_to_bytes,
    unpack_payload,
)


def frame_bits_for_message(message_bytes: int) -> int:
    """Bits of the v3 channel frame carrying a camera payload with this message size."""
    return 8 * (FRAME_HEADER_BYTES + payload_size(message_bytes))


@dataclass(frozen=True)
class SignedPayload:
    payload: bytes
    mode: int
    video_digest: bytes
    binding: bytes
    proof: dict


def build_payload(bridge: CameraProofBridge, registry: CameraRegistry, secret: int, message: bytes, *,
                  native_cli: str | Path | None = None, cover: str | Path | None = None,
                  stego_key: bytes | None = None, max_bits_per_idr: int = 64,
                  mode: int = MODE_VIDEO, select: str = "random", key_mode: str = "master") -> SignedPayload:
    """Prove and pack. Mode 0 needs ``native_cli``, the ``cover`` it will be embedded in and the stego key.

    ``select`` / ``key_mode`` are the channel parameters the cover will be embedded with; the
    digest marks the carriers of exactly that embedding.
    """
    if mode == MODE_VIDEO:
        if native_cli is None or cover is None or stego_key is None:
            raise ValueError("video binding needs the native CLI, the cover video and the stego key")
        digest = native_video_digest(native_cli, cover, stego_key, frame_bits_for_message(len(message)),
                                     max_bits_per_idr, select=select, key_mode=key_mode)
    elif mode == MODE_MESSAGE_ONLY:
        digest = bytes(DIGEST_BYTES)
    else:
        raise ValueError("binding mode must be 0 (video) or 1 (message only)")
    binding = binding_digest(mode, digest, message)
    proof = bridge.prove(secret, registry, binding)
    return SignedPayload(pack_payload(mode, message, proof_to_bytes(proof)), mode, digest, binding, proof)


@dataclass(frozen=True)
class Verdict:
    valid: bool
    reason: str | None
    mode: int | None = None
    message: bytes | None = None

    @property
    def video_bound(self) -> bool:
        return self.valid and self.mode == MODE_VIDEO

    def to_json(self) -> dict:
        if not self.valid:
            return {"valid": False, "reason": self.reason}
        return {"valid": True, "video_bound": self.video_bound, "binding_mode": self.mode,
                "message_sha256": hashlib.sha256(self.message or b"").hexdigest()}


def parse_payload(payload: bytes) -> tuple[CameraPayload, dict] | None:
    """(payload, decompressed proof), or None when the bytes are not a well-formed camera payload."""
    try:
        unpacked = unpack_payload(payload)
        return unpacked, bytes_to_proof(unpacked.proof_bytes)
    except ValueError:
        return None


def verify_payload(bridge: CameraProofBridge, root: int, payload: bytes, *, native_cli: str | Path | None = None,
                   stego: str | Path | None = None, stego_key: bytes | None = None, max_bits_per_idr: int = 64,
                   require_video_binding: bool = True, select: str = "random",
                   key_mode: str = "master") -> Verdict:
    """Groth16 decision for an extracted payload; reasons match the service verify job.

    In ``key_mode="per-video"`` the ``stego_key`` may be the video's 64-byte verification token.
    """
    parsed = parse_payload(payload)
    if parsed is None:
        return Verdict(False, "malformed_proof_payload")
    return check_proof(bridge, root, *parsed, native_cli=native_cli, stego=stego, stego_key=stego_key,
                       max_bits_per_idr=max_bits_per_idr, require_video_binding=require_video_binding,
                       select=select, key_mode=key_mode)


def check_proof(bridge: CameraProofBridge, root: int, unpacked: CameraPayload, proof: dict, *,
                native_cli: str | Path | None = None, stego: str | Path | None = None,
                stego_key: bytes | None = None, max_bits_per_idr: int = 64,
                require_video_binding: bool = True, select: str = "random",
                key_mode: str = "master") -> Verdict:
    """Rebuild the binding (from the stego video for mode 0) and verify the proof against ``root``."""
    if unpacked.mode == MODE_MESSAGE_ONLY:
        if require_video_binding:
            return Verdict(False, "video_binding_required", unpacked.mode)
        digest = bytes(DIGEST_BYTES)
    else:
        if native_cli is None or stego is None or stego_key is None:
            raise ValueError("a video-bound payload needs the native CLI, the stego video and the stego key")
        try:
            digest = native_video_digest(native_cli, stego, stego_key, frame_bits_for_message(len(unpacked.message)),
                                         max_bits_per_idr, select=select, key_mode=key_mode)
        except ValueError:
            return Verdict(False, "video_digest_unavailable", unpacked.mode)
    binding = binding_digest(unpacked.mode, digest, unpacked.message)
    if bridge.verify(proof, root, binding) is not True:
        return Verdict(False, "proof_invalid", unpacked.mode)
    return Verdict(True, None, unpacked.mode, unpacked.message)
