"""Security regression tests for manifest signing and cache defaults."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.core.analysis_cache import _trusted_pickle_cache_enabled
from src.manifest import StegoManifest
from src.runtest._helpers import run_test, section, summarise


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


def t_pickle_cache_requires_explicit_trust_opt_in():
    previous = os.environ.pop("ZK_STEGO_TRUSTED_PICKLE_CACHE", None)
    try:
        assert not _trusted_pickle_cache_enabled()
        os.environ["ZK_STEGO_TRUSTED_PICKLE_CACHE"] = "1"
        assert _trusted_pickle_cache_enabled()
    finally:
        if previous is None:
            os.environ.pop("ZK_STEGO_TRUSTED_PICKLE_CACHE", None)
        else:
            os.environ["ZK_STEGO_TRUSTED_PICKLE_CACHE"] = previous


def main():
    section("Phase 6 — Security Hardening")
    results = [
        run_test("manifest_signature_uses_public_verification_key", t_manifest_signature_uses_public_verification_key),
        run_test("manifest_signature_rejects_tampering", t_manifest_signature_rejects_tampering),
        run_test("pickle_cache_requires_explicit_trust_opt_in", t_pickle_cache_requires_explicit_trust_opt_in),
    ]
    sys.exit(summarise(results, "Phase 6"))


if __name__ == "__main__":
    main()
