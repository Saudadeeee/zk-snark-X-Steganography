"""Run measured implementations of payload authentication/encryption choices.

This is an algorithm comparison harness, not a claim that every protocol has
been integrated into the CAVLC production data plane. Each operation performs
real seal/sign and open/verify calls from ``cryptography`` and records a
positive and negative (tamper) check. Security properties are deliberately
kept distinct: signatures, MACs and AEAD are not interchangeable.
"""

from __future__ import annotations

import json
import os
import statistics
import time
import tracemalloc
from pathlib import Path
from typing import Any, Callable

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa, x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def _bad(action: Callable[[], Any]) -> bool:
    try:
        action()
    except (InvalidSignature, InvalidTag, ValueError):
        return True
    return False


def build_protocols() -> list[dict[str, Any]]:
    """Construct independent real implementations and their test closures."""
    from cryptography.hazmat.primitives import hmac

    protocols: list[dict[str, Any]] = []

    # Shared-secret authentication only; intentionally offers no encryption.
    hmac_key = os.urandom(32)

    def hmac_seal(message: bytes) -> tuple[bytes, bytes]:
        mac = hmac.HMAC(hmac_key, hashes.SHA256())
        mac.update(message)
        return message, mac.finalize()

    def hmac_open(message: bytes, token: bytes) -> bytes:
        mac = hmac.HMAC(hmac_key, hashes.SHA256())
        mac.update(message)
        mac.verify(token)
        return message

    protocols.append({
        "name": "hmac_sha256", "category": "symmetric MAC",
        "role": "this_work_component_reference",
        "properties": {"confidentiality": False, "integrity": True,
                       "shared_key_authentication": True, "public_verifiability": False},
        "notes": "Reference primitive measured with full 32-byte HMAC output in Python cryptography. Protocol v2 carried a native CAVLC frame tag that truncated HMAC-SHA-256 to 16 bytes; this row is not the native tag's exact timing/overhead.",
        "seal": hmac_seal, "open": hmac_open,
    })

    # Publicly verifiable signatures (payload remains cleartext).
    ed_private = ed25519.Ed25519PrivateKey.generate()
    ed_public = ed_private.public_key()

    def ed_seal(message: bytes) -> tuple[bytes, bytes]:
        return message, ed_private.sign(message)

    def ed_open(message: bytes, token: bytes) -> bytes:
        ed_public.verify(token, message)
        return message

    protocols.append({
        "name": "ed25519_signature", "category": "digital signature",
        "properties": {"confidentiality": False, "integrity": True,
                       "shared_key_authentication": False, "public_verifiability": True},
        "notes": "RFC 8032 Ed25519 detached signature; signing key is generated once per run.",
        "seal": ed_seal, "open": ed_open,
    })

    # RSA-PSS public-key signature.
    rsa_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rsa_public = rsa_private.public_key()

    def rsa_sign(message: bytes) -> tuple[bytes, bytes]:
        sig = rsa_private.sign(message, padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH,
        ), hashes.SHA256())
        return message, sig

    def rsa_verify(message: bytes, token: bytes) -> bytes:
        rsa_public.verify(token, message, padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH,
        ), hashes.SHA256())
        return message

    protocols.append({
        "name": "rsa_pss_2048_signature", "category": "digital signature",
        "properties": {"confidentiality": False, "integrity": True,
                       "shared_key_authentication": False, "public_verifiability": True},
        "notes": "RSA-2048 PSS/SHA-256; payload remains cleartext.",
        "seal": rsa_sign, "open": rsa_verify,
    })

    # Symmetric authenticated encryption.
    for name, cipher_factory, note in (
        ("aes_256_gcm", AESGCM, "AES-256-GCM shared-key AEAD."),
        ("chacha20_poly1305", ChaCha20Poly1305, "ChaCha20-Poly1305 shared-key AEAD."),
    ):
        cipher = cipher_factory.generate_key(bit_length=256) if name == "aes_256_gcm" else cipher_factory.generate_key()
        aead = cipher_factory(cipher)
        aad = b"zkstego-benchmark-v1"

        def seal(message: bytes, aead: Any = aead, aad: bytes = aad) -> tuple[bytes, bytes]:
            nonce = os.urandom(12)
            return nonce, aead.encrypt(nonce, message, aad)

        def open_(nonce: bytes, token: bytes, aead: Any = aead, aad: bytes = aad) -> bytes:
            return aead.decrypt(nonce, token, aad)

        protocols.append({
            "name": name, "category": "symmetric AEAD",
            "properties": {"confidentiality": True, "integrity": True,
                           "shared_key_authentication": True, "public_verifiability": False},
            "notes": note, "seal": seal, "open": open_,
        })

    # Public-key hybrid encryption: RSA-OAEP wraps a fresh AES-256-GCM key.
    oaep_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    oaep_public = oaep_private.public_key()

    def oaep_seal(message: bytes) -> tuple[bytes, bytes]:
        aes_key, nonce = os.urandom(32), os.urandom(12)
        wrapped = oaep_public.encrypt(aes_key, padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None,
        ))
        ciphertext = AESGCM(aes_key).encrypt(nonce, message, b"zkstego-rsa-hybrid-v1")
        return wrapped + nonce, ciphertext

    def oaep_open(header: bytes, ciphertext: bytes) -> bytes:
        aes_key = oaep_private.decrypt(header[:-12], padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None,
        ))
        return AESGCM(aes_key).decrypt(header[-12:], ciphertext, b"zkstego-rsa-hybrid-v1")

    protocols.append({
        "name": "rsa_oaep_aes256gcm", "category": "public-key hybrid encryption",
        "properties": {"confidentiality": True, "integrity": True,
                       "shared_key_authentication": False, "public_verifiability": False},
        "notes": "RSA-OAEP/SHA-256 wraps a fresh AES-256-GCM key; does not authenticate sender identity.",
        "seal": oaep_seal, "open": oaep_open,
    })

    # Authenticated public-key encryption using a pre-authenticated static
    # sender X25519 identity and recipient X25519 key. This is explicitly not
    # presented as a standardized/formally analyzed signcryption scheme.
    sender_private = x25519.X25519PrivateKey.generate()
    sender_public = sender_private.public_key()
    recipient_private = x25519.X25519PrivateKey.generate()
    recipient_public = recipient_private.public_key()
    sender_public_raw = sender_public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    recipient_public_raw = recipient_public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    def x25519_key(shared: bytes) -> bytes:
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                    info=b"zkstego-x25519-aead-v1" + sender_public_raw + recipient_public_raw).derive(shared)

    static_shared = sender_private.exchange(recipient_public)
    static_aead = ChaCha20Poly1305(x25519_key(static_shared))

    def x25519_seal(message: bytes) -> tuple[bytes, bytes]:
        nonce = os.urandom(12)
        return nonce, static_aead.encrypt(nonce, message, sender_public_raw + recipient_public_raw)

    def x25519_open(nonce: bytes, ciphertext: bytes) -> bytes:
        # Receiver independently derives the same pairwise static-DH secret.
        shared = recipient_private.exchange(sender_public)
        key = x25519_key(shared)
        return ChaCha20Poly1305(key).decrypt(
            nonce, ciphertext, sender_public_raw + recipient_public_raw,
        )

    protocols.append({
        "name": "x25519_chacha20poly1305", "category": "authenticated public-key encryption",
        "properties": {"confidentiality": True, "integrity": True,
                       "shared_key_authentication": True, "public_verifiability": False},
        "notes": "X25519 static-DH + HKDF-SHA-256 + ChaCha20-Poly1305; receiver must trust sender key binding; not formal signcryption.",
        "seal": x25519_seal, "open": x25519_open,
    })

    # A genuinely executed encrypt-plus-public-signature composition. Keep it
    # separate from signcryption: it has different proof and key semantics.
    signing_private = ed25519.Ed25519PrivateKey.generate()
    signing_public = signing_private.public_key()

    def composed_seal(message: bytes) -> tuple[bytes, bytes]:
        nonce, ciphertext = x25519_seal(message)
        signature = signing_private.sign(sender_public_raw + recipient_public_raw + nonce + ciphertext)
        return nonce + ciphertext, signature

    def composed_open(header: bytes, signature: bytes) -> bytes:
        nonce, ciphertext = header[:12], header[12:]
        signing_public.verify(signature, sender_public_raw + recipient_public_raw + nonce + ciphertext)
        return x25519_open(nonce, ciphertext)

    protocols.append({
        "name": "x25519_aead_plus_ed25519", "category": "encrypt-then-sign composition",
        "properties": {"confidentiality": True, "integrity": True,
                       "shared_key_authentication": True, "public_verifiability": True},
        "notes": "Explicit X25519 AEAD + detached Ed25519 signature composition; not formal signcryption.",
        "seal": composed_seal, "open": composed_open,
    })
    return protocols


def exercise_protocol(protocol: dict[str, Any], payload: bytes) -> dict[str, Any]:
    """Perform one correctness and tamper-rejection trial."""
    body, token = protocol["seal"](payload)
    clear = protocol["open"](body, token)
    if protocol["name"] in {"hmac_sha256", "ed25519_signature", "rsa_pss_2048_signature"}:
        bad_body, bad_token = body[:-1] + bytes([body[-1] ^ 1]), token
    elif protocol["name"] == "x25519_chacha20poly1305":
        bad_body, bad_token = body, token[:-1] + bytes([token[-1] ^ 1])
    elif protocol["name"] == "x25519_aead_plus_ed25519":
        bad_body, bad_token = body[:-1] + bytes([body[-1] ^ 1]), token
    else:
        bad_body, bad_token = body, token[:-1] + bytes([token[-1] ^ 1])
    rejected = _bad(lambda: protocol["open"](bad_body, bad_token))
    return {
        "roundtrip_ok": clear == payload,
        "tamper_rejected": rejected,
        "payload_bytes": len(payload),
        "overhead_bytes": len(body) + len(token) - len(payload),
    }


def benchmark_protocol(protocol: dict[str, Any], payload_bytes: int, trials: int = 100) -> dict[str, Any]:
    payload = bytes((i * 131 + 17) & 0xFF for i in range(payload_bytes))
    exercise = exercise_protocol(protocol, payload)
    seal_ms: list[float] = []
    open_ms: list[float] = []
    seal_cpu_ms: list[float] = []
    open_cpu_ms: list[float] = []
    tracemalloc.start()
    for _ in range(trials):
        t0 = time.perf_counter_ns()
        c0 = time.process_time_ns()
        body, token = protocol["seal"](payload)
        seal_ms.append((time.perf_counter_ns() - t0) / 1e6)
        seal_cpu_ms.append((time.process_time_ns() - c0) / 1e6)
        t0 = time.perf_counter_ns()
        c0 = time.process_time_ns()
        opened = protocol["open"](body, token)
        open_ms.append((time.perf_counter_ns() - t0) / 1e6)
        open_cpu_ms.append((time.process_time_ns() - c0) / 1e6)
        if opened != payload:
            raise RuntimeError(f"{protocol['name']} round-trip mismatch")
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    token_bytes = int(exercise["overhead_bytes"])
    return {
        "algorithm": protocol["name"], "category": protocol["category"],
        "role": protocol.get("role", "comparison_candidate"),
        "properties": protocol["properties"], "notes": protocol["notes"],
        "payload_bytes": payload_bytes, "overhead_bytes": token_bytes,
        "envelope_bytes": payload_bytes + token_bytes, "trials": trials,
        "seal_ms_median": statistics.median(seal_ms),
        "seal_ms_p95": sorted(seal_ms)[int(0.95 * (len(seal_ms) - 1))],
        "seal_process_cpu_ms_median": statistics.median(seal_cpu_ms),
        "open_verify_ms_median": statistics.median(open_ms),
        "open_verify_ms_p95": sorted(open_ms)[int(0.95 * (len(open_ms) - 1))],
        "open_verify_process_cpu_ms_median": statistics.median(open_cpu_ms),
        "python_tracemalloc_peak_bytes": peak_bytes,
        "roundtrip_ok": exercise["roundtrip_ok"],
        "tamper_rejected": exercise["tamper_rejected"],
    }


def run_crypto_benchmark(out_path: Path, trials: int = 100) -> dict[str, Any]:
    results = [
        benchmark_protocol(protocol, size, trials)
        for protocol in build_protocols()
        for size in (32, 256, 1024)
    ]
    record = {
        "schema": "zkstego-crypto-benchmark-new-v1",
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "runtime": {"python": os.sys.version, "cryptography": __import__("cryptography").__version__},
        "methodology": "Real in-process seal/sign and open/verify calls; 32/256/1024-byte messages; 100 measured operations after one correctness/tamper trial; keys generated once per run except per-message RSA hybrid AES keys.",
        "proposal_mapping": {
            "this_work": "Native H.264 CAVLC stream modification, channel protocol v3: the frame carries no MAC (the v2 16-byte HMAC tag was removed); the payload's Groth16 proof authenticates it and HMAC-SHA-256 is used only as a keyed PRF for the sign schedule and whitening. No payload confidentiality.",
            "hmac_row_scope": "Primitive reference only: Python cryptography full 32-byte HMAC output. Protocol v3 has no native frame tag; end-to-end video cost is reported separately by the media and E2E benchmarks.",
            "zkp_scope": "Groth16/PLONK tests prove a payload commitment statement separately; the current video benchmark does not prove camera origin or bind the entire video stream."
        },
        "results": results,
        "non_equivalence_note": "MACs, digital signatures and AEAD have different security properties. The measured X25519+AEAD scheme and the Ed25519+AEAD composition are not claimed to be standardized signcryption. No literature-only timing values are included.",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


if __name__ == "__main__":
    from pathlib import Path
    result_path = Path(__file__).resolve().parent / "results" / "security_new.json"
    record = run_crypto_benchmark(result_path)
    print(f"wrote {len(record['results'])} measured records: {result_path}")
