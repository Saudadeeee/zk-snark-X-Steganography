"""Security regression tests for Ed25519 manifest signing and binding fields."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from src.manifest import StegoManifest, compute_positions_hash  # noqa: E402
from src.runtest._helpers import run_test, section, summarise  # noqa: E402

_POSITIONS = [[0, 0, 1], [0, 1, 2], [1, 3, 5]]


def _keypair() -> tuple[bytes, bytes]:
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return private_bytes, public_bytes


def t_manifest_signature_uses_public_verification_key():
    private_key, public_key = _keypair()
    manifest = StegoManifest()
    manifest.sign(private_key, signer_id="security-test")

    assert manifest.signature_scheme == "ed25519"
    assert manifest.verify_signature(public_key)
    assert not manifest.verify_signature(private_key)


def t_manifest_signature_rejects_tampering():
    private_key, public_key = _keypair()
    manifest = StegoManifest()
    manifest.sign(private_key)
    manifest.payload.message_length = 1

    assert not manifest.verify_signature(public_key)


def t_manifest_binding_fields_are_optional_for_legacy_hash():
    manifest = StegoManifest(created="2026-01-01T00:00:00")
    legacy_hash = manifest.compute_content_hash()
    data = manifest.to_dict()
    assert "positions_sha256" not in data["embedding"]
    assert "stego_file_hash" not in data["video"]
    manifest.embedding.positions_sha256 = compute_positions_hash(_POSITIONS)
    assert manifest.compute_content_hash() != legacy_hash, "binding must be covered by signature"
    decoded = StegoManifest.from_json(manifest.to_json())
    assert decoded.embedding.positions_sha256 == manifest.embedding.positions_sha256


def main():
    section("Manifest security")
    results = [
        run_test("manifest_signature_uses_public_verification_key", t_manifest_signature_uses_public_verification_key),
        run_test("manifest_signature_rejects_tampering", t_manifest_signature_rejects_tampering),
        run_test("manifest_binding_fields_are_optional_for_legacy_hash",
                 t_manifest_binding_fields_are_optional_for_legacy_hash),
    ]
    sys.exit(summarise(results, "Manifest security"))


if __name__ == "__main__":
    main()
