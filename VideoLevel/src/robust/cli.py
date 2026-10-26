"""Role-separated command line for the robust (semi-fragile) video proof.

This is the robust-mode twin of ``src.lattice_zk.cli``: the envelope rides in
the *decoded* picture (QIM carriers under a convolutional code) and the
statement binds a coarse content fingerprint, so the proof survives a
re-compression at the same resolution.  Commands touch only the files their
role owns:

    issuer    issuer-keygen, registry-sign
    holder    credential-new, embed, disclose
    verifier  session-issue, verify, disclosure-verify

The issuer key pair and the credential (a BDLOP commitment plus its opening)
are *identical* to the fragile mode's and are produced by reusing that CLI's
handlers: both modes share ``PARAMS = BDLOP_OPEN_128``, so credentials and
issuer keys are interchangeable between them.  The robust *relation
descriptor*, *policy*, *session binding* and *carrier channel* differ, so a
robust registry or session is **not** interchangeable with a fragile one: this
module resolves all three with ``src.robust.pipeline``'s own functions.

The verifier needs only the stego video, the signed registry, the issuer
public key, its own session database and the shared sync key (hex, in the
``ZKSTEGO_ROBUST_SYNC_KEY_HEX`` environment variable, or
``--public-carrier-order`` to derive it from the public profile); it never
reads a cover, a sidecar or any holder secret.  ``embed`` re-encodes the cover,
so its ``--output`` must not exist and must differ from the cover.

    python -m src.robust.cli <command> --help
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

import numpy as np

from ..lattice_zk import cli as lattice_cli
from ..lattice_zk.params import BDLOP_OPEN_128, BdlopParams
from ..registry.zkp_registry import SignedZkpRelationRegistry
from ..registry.zkp_sessions import SessionChallengeStore
from . import decode as video_io
from . import pipeline as robust

SYNC_KEY_ENV = "ZKSTEGO_ROBUST_SYNC_KEY_HEX"
PARAMS: BdlopParams = BDLOP_OPEN_128
# The robust watermark keys SHAKE-256 with exactly 32 bytes (watermark.py).
_SYNC_KEY_HEX = re.compile(r"(?:[0-9a-fA-F]{2}){32}")


def _sync_key(arguments: argparse.Namespace, profile: robust.RobustProfile) -> bytes:
    """Public carrier key from the profile, or the 32-byte secret stego key."""
    if getattr(arguments, "public_carrier_order", False):
        return robust.public_sync_key(PARAMS, profile)
    value = os.environ.get(SYNC_KEY_ENV, "")
    if _SYNC_KEY_HEX.fullmatch(value) is None:
        raise ValueError(f"set {SYNC_KEY_ENV} to exactly 32 bytes (64 hex characters) of key material")
    return bytes.fromhex(value)


def _profile(*, registered: bool) -> robust.RobustProfile:
    """The single pinned robust profile; its step follows the mode."""
    return robust.RobustProfile.recommended(registered=registered)


def _encoder(arguments: argparse.Namespace) -> video_io.EncoderSettings:
    """Stego re-encoder; not part of what a verifier pins."""
    return video_io.EncoderSettings(codec=arguments.encoder, crf=arguments.crf)


def _verifier_pins(arguments: argparse.Namespace):
    """Resolve robust pins from verifier-held configuration only."""
    credential = lattice_cli._public_credential(arguments.credential)
    profile = _profile(registered=credential is not None)
    registry = SignedZkpRelationRegistry.from_dict(lattice_cli._read_json(arguments.registry))
    pins = robust.pins_from_registry(
        registry, arguments.issuer_public.read_bytes(), PARAMS, profile,
        minimum_epoch=arguments.minimum_epoch, credential=credential,
        holder_id=arguments.holder_id,
    )
    return pins, profile, credential


# -- issuer --------------------------------------------------------------- #

def _registry_sign(arguments: argparse.Namespace) -> dict[str, Any]:
    credential = lattice_cli._public_credential(arguments.credential)
    profile = _profile(registered=credential is not None)
    descriptor = robust.relation_descriptor(PARAMS, profile, credential, holder_id=arguments.holder_id)
    registry = SignedZkpRelationRegistry.create(epoch=arguments.epoch, relations=[descriptor]).sign(
        arguments.issuer_private.read_bytes(), signer_id=arguments.signer_id
    )
    lattice_cli._write_json(arguments.out, registry.to_dict())
    return {"registry": str(arguments.out), "epoch": registry.epoch, "root": registry.root(),
            "mode": "registered" if credential is not None else "in-band",
            "holder_id": arguments.holder_id, "policy": robust.ROBUST_POLICY}


# -- holder --------------------------------------------------------------- #

def _embed(arguments: argparse.Namespace) -> dict[str, Any]:
    if (arguments.payload_file is None) == (arguments.credential_private is None):
        raise ValueError("supply exactly one of --payload-file or --credential-private")
    if arguments.payload_file is not None and arguments.opening_out is None:
        raise ValueError("--opening-out is required to keep the payload opening")
    # Checked before proving: a stego video whose opening cannot be saved is lost.
    lattice_cli._require_absent(arguments.output, arguments.opening_out)
    credential = None
    if arguments.credential_private is not None:
        credential = lattice_cli._private_credential(arguments.credential_private)
    profile = _profile(registered=credential is not None)
    registry = SignedZkpRelationRegistry.from_dict(lattice_cli._read_json(arguments.registry))
    pins = robust.pins_from_registry(
        registry, arguments.issuer_public.read_bytes(), PARAMS, profile,
        minimum_epoch=arguments.minimum_epoch,
        credential=None if credential is None else credential.commitment,
        holder_id=arguments.holder_id,
    )
    payload = None if credential is not None else arguments.payload_file.read_bytes()
    result = robust.embed_robust_proof(
        arguments.video, arguments.output, payload, params=PARAMS, pins=pins, profile=profile,
        session_challenge=lattice_cli._challenge(arguments.session),
        sync_key=_sync_key(arguments, profile), credential=credential, encoder=_encoder(arguments),
    )
    if result.opening is not None:
        lattice_cli._write_json(arguments.opening_out, {
            "payload": result.opening.payload.hex(),
            "randomness": result.opening.randomness.astype(np.int8).tobytes().hex(),
        }, private=True)
    return {"output": str(arguments.output), "statement_id": result.statement_id.hex(),
            "envelope_bytes": result.envelope_bytes, "fingerprint_bytes": result.fingerprint_bytes,
            "capacity_bits": result.capacity_bits, "coded_bits": result.coded_bits,
            "rate": result.rate, "repetitions": result.repetitions,
            "watermark_psnr": result.watermark_psnr,
            "mode": "registered" if credential is not None else "in-band"}


# -- verifier ------------------------------------------------------------- #

def _session_issue(arguments: argparse.Namespace) -> dict[str, Any]:
    pins, _profile_unused, _credential = _verifier_pins(arguments)
    store = SessionChallengeStore(arguments.database, ttl_seconds=arguments.ttl_seconds)
    grant = store.issue(context_binding=robust.session_binding(PARAMS, pins))
    return grant.to_dict()


def _verify(arguments: argparse.Namespace) -> dict[str, Any]:
    lattice_cli._require_absent(arguments.envelope_out)
    pins, profile, credential = _verifier_pins(arguments)
    if arguments.envelope_out is not None and credential is not None:
        raise ValueError("--envelope-out applies to in-band mode only")
    store = SessionChallengeStore(arguments.database, ttl_seconds=arguments.ttl_seconds)
    result = robust.verify_robust_proof(
        arguments.video, params=PARAMS, pins=pins, profile=profile,
        sync_key=_sync_key(arguments, profile), session_store=store,
        credential=credential, holder_id=arguments.holder_id,
    )
    if result.valid and arguments.envelope_out is not None:
        lattice_cli._write_new(arguments.envelope_out, result.envelope)
    return {"valid": result.valid, "reason": result.reason,
            "statement_id": None if result.statement_id is None else result.statement_id.hex(),
            "mode": "registered" if credential is not None else "in-band",
            "holder_id": arguments.holder_id,
            # Localization: counts plus the per-frame channel quality.
            "bad_frames": list(result.bad_frames), "damaged_windows": len(result.damaged_windows),
            "flagged_cells": len(result.flagged_cells),
            "flagged_chroma_cells": len(result.flagged_chroma_cells),
            "raw_ber": result.raw_ber, "max_frame_ber": result.max_frame_ber,
            "max_cell_delta": result.max_cell_delta, "max_chroma_delta": result.max_chroma_delta}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.robust.cli", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    def add(name: str, handler, summary: str) -> argparse.ArgumentParser:
        command = commands.add_parser(name, help=summary, description=summary)
        command.set_defaults(handler=handler)
        return command

    def registry_options(command: argparse.ArgumentParser) -> None:
        command.add_argument("--registry", type=Path, required=True)
        command.add_argument("--issuer-public", type=Path, required=True)
        command.add_argument("--minimum-epoch", type=int, required=True)
        command.add_argument(
            "--holder-id", help="holder identity the issuer bound to the registered credential",
        )
        command.add_argument(
            "--public-carrier-order", action="store_true",
            help="derive the carrier key from the public profile instead of the secret stego key "
                 f"(public verification; gives up undetectability, and lets anyone with the pins "
                 f"erase the watermark). Otherwise set {SYNC_KEY_ENV}. Embedder and verifier must "
                 f"both use the same choice, or verification simply fails.",
        )

    # issuer-keygen and credential-new are identical to the fragile mode's; reuse them.
    command = add("issuer-keygen", lattice_cli._issuer_keygen, "Create an ML-DSA-65 issuer key pair.")
    command.add_argument("--public", type=Path, required=True)
    command.add_argument("--private", type=Path, required=True)

    command = add("credential-new", lattice_cli._credential_new, "Commit to a credential payload.")
    command.add_argument("--payload-file", type=Path, required=True)
    command.add_argument("--public", type=Path, required=True)
    command.add_argument("--private", type=Path, required=True)

    command = add("registry-sign", _registry_sign, "Sign a registry with one robust relation.")
    command.add_argument("--issuer-private", type=Path, required=True)
    command.add_argument("--epoch", type=int, required=True)
    command.add_argument("--signer-id", default="issuer")
    command.add_argument("--credential", type=Path, help="public credential; selects registered mode")
    command.add_argument("--holder-id", help="registered mode: bind the credential to this holder")
    command.add_argument("--out", type=Path, required=True)

    command = add("embed", _embed, "Prove and embed the envelope robustly into a re-encoded video.")
    command.add_argument("--video", type=Path, required=True, help="cover video (anything ffmpeg decodes)")
    command.add_argument("--output", type=Path, required=True, help="stego video; must not exist, differs from cover")
    command.add_argument("--session", required=True, help="verifier-issued challenge (hex)")
    command.add_argument("--payload-file", type=Path, help="in-band mode: payload to commit to")
    command.add_argument("--opening-out", type=Path, help="in-band mode: where to keep the opening")
    command.add_argument("--credential-private", type=Path, help="registered mode: credential secret")
    command.add_argument("--encoder", default="libx264", help="ffmpeg video encoder for the stego output")
    command.add_argument("--crf", type=int, default=12, help="stego encoder CRF (lower = higher quality)")
    registry_options(command)

    command = add("disclose", lattice_cli._disclose,
                  "Reveal a committed payload to one recipient, in zero knowledge.")
    command.add_argument("--opening", type=Path, required=True,
                         help="embed --opening-out file, or a credential secret")
    command.add_argument("--statement-id", required=True,
                         help="hex: verified video statement id, or the id the recipient names")
    command.add_argument("--nonce", required=True, help="recipient-chosen 32-byte nonce (hex)")
    command.add_argument("--out", type=Path, required=True)

    for name, handler, summary in (
        ("session-issue", _session_issue, "Issue a one-use session challenge."),
        ("verify", _verify, "Verify a robust stego video from the video alone."),
    ):
        command = add(name, handler, summary)
        command.add_argument("--database", type=Path, required=True)
        command.add_argument("--ttl-seconds", type=int, default=24 * 3600)
        command.add_argument("--credential", type=Path, help="public credential; selects registered mode")
        registry_options(command)
        if name == "verify":
            command.add_argument("--video", type=Path, required=True)
            command.add_argument("--envelope-out", type=Path,
                                 help="in-band mode: keep the verified envelope for disclosure-verify")

    command = add("disclosure-verify", lattice_cli._disclosure_verify, "Check a payload disclosure.")
    command.add_argument("--envelope", type=Path, help="envelope saved by verify --envelope-out")
    command.add_argument("--credential", type=Path, help="public credential (registered mode)")
    command.add_argument("--statement-id", required=True, help="hex statement id the holder used")
    command.add_argument("--nonce", required=True, help="the nonce this recipient chose (hex)")
    command.add_argument("--disclosure", type=Path, required=True)
    # Robust mode pins no payload-range attachment; the reused handler reads this attribute.
    command.set_defaults(payload_range_bytes=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    try:
        report = arguments.handler(arguments)
    except (ValueError, TypeError, OSError, KeyError, RuntimeError, sqlite3.Error) as error:
        sys.stderr.write(f"error: {type(error).__name__}: {error}\n")
        return 2
    sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")
    return 0 if report.get("valid", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
