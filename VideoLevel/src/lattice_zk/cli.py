"""Role-separated command line for the BDLOP video proof.

Each command touches only the files its role owns:

    issuer    issuer-keygen, registry-sign
    holder    credential-new, embed, disclose
    verifier  session-issue, verify, disclosure-verify

The verifier needs the stego video, the signed registry, the issuer public
key, its own session database and the shared sync key (hex, in the
``ZKSTEGO_LATTICEZK_SYNC_KEY_HEX`` environment variable); it never reads a
sidecar, the cover video or any holder secret.  Two session modes exist:
interactive (``session-issue`` → ``--session``) and offline (``epoch-issue``
by the issuer → ``--epoch-beacon`` on both sides; the verifier database then
holds its replay ledger).  ``--payload-range-bytes L`` (in-band) pins a payload
length, pads the payload to it and attaches a range proof to the envelope.  ``--holder-id`` binds a
registered credential to a holder identity in the signed registry; the same
value must then be given wherever pins are resolved.  ``disclose`` reveals a
payload to one recipient with a zero-knowledge proof (the opening's randomness
never leaves the holder); the recipient checks it with ``disclosure-verify``.

    python -m src.lattice_zk.cli <command> --help
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

from ..registry.epoch_challenges import EpochChallenge, OfflineReplayLedger
from ..registry.lattice_pq import LatticeSigner
from ..registry.zkp_registry import SignedZkpRelationRegistry
from ..registry.zkp_sessions import SessionChallengeStore
from ..transport import gop_policy as gop_policies
from ..transport.adaptive_chunks import AdaptiveChunkPlan
from ..transport.blind_sync import BlindOperatingContract
from ..transport.cabac_sync import DEFAULT_CABAC_CONTRACT
from . import bdlop, codec, video_proof
from . import video_pipeline as pipeline
from .params import BDLOP_OPEN_128, BdlopParams

SYNC_KEY_ENV = "ZKSTEGO_LATTICEZK_SYNC_KEY_HEX"
PARAMS: BdlopParams = BDLOP_OPEN_128
CONTRACT = BlindOperatingContract(
    version="stable-carriers-video-only-v1",
    require_bitstream_patchable=True,
    patchability_headroom=64,
    max_modifications_per_block=1,
    stable_carriers_only=True,
)
_HEX_32 = re.compile(r"[0-9a-fA-F]{64}")
# CAVLC Baseline policies use ``CONTRACT``; the CABAC policy needs the CABAC
# carrier contract instead (Main/High I/IDR slices, docs/CABAC_SUPPORT.md).
CODEC_POLICIES = {
    "v1": pipeline.CODEC_POLICY_V1,
    "v2": pipeline.CODEC_POLICY_V2,
    "cabac": pipeline.CODEC_POLICY_CABAC_V1,
}


def _contract_for(codec_policy: str):
    """The carrier contract a codec policy requires."""
    return DEFAULT_CABAC_CONTRACT if codec_policy == pipeline.CODEC_POLICY_CABAC_V1 else CONTRACT


def _write_new(path: Path, data: bytes, *, private: bool = False) -> None:
    """Create a file, refusing to overwrite; private files are owner-only."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600 if private else 0o644)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def _require_absent(*paths: Path | None) -> None:
    """Fail before any work if an output would be overwritten.

    Writing still uses ``O_EXCL``; this pre-check only prevents creating one
    half of a key pair, or embedding a video whose opening cannot be kept.
    """
    given = [os.path.abspath(path) for path in paths if path is not None]
    if len(set(given)) != len(given):
        raise ValueError("output paths must be distinct")
    for path in paths:
        if path is not None and os.path.lexists(path):
            raise FileExistsError(f"{path} already exists; refusing to overwrite it")


def _write_json(path: Path, value: dict[str, Any], *, private: bool = False) -> None:
    _write_new(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("ascii"), private=private)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _sync_key(arguments: argparse.Namespace | None = None, profile=None) -> bytes:
    if arguments is not None and getattr(arguments, "public_carrier_order", False):
        return pipeline.public_sync_key(PARAMS, profile)
    value = os.environ.get(SYNC_KEY_ENV, "")
    if re.fullmatch(r"(?:[0-9a-fA-F]{2}){16,}", value) is None:
        raise ValueError(f"set {SYNC_KEY_ENV} to at least 16 bytes of hex key material")
    return bytes.fromhex(value)


def _hex_32(value: str, name: str) -> bytes:
    if _HEX_32.fullmatch(value) is None:
        raise ValueError(f"{name} must be 64 hex characters")
    return bytes.fromhex(value)


def _challenge(value: str) -> bytes:
    return _hex_32(value, "session challenge")


def _profile(arguments: argparse.Namespace, *, registered: bool) -> pipeline.CarrierProfile:
    length = getattr(arguments, "payload_range_bytes", None)
    if length is not None and registered:
        raise ValueError("--payload-range-bytes applies to in-band mode only")
    adaptive = getattr(arguments, "adaptive_chunks", False)
    if adaptive and arguments.chunk_bytes != pipeline.DEFAULT_CHUNK_BYTES:
        raise ValueError("--adaptive-chunks replaces --chunk-bytes")
    codec_policy = CODEC_POLICIES[arguments.codec_policy]
    gop_policy = getattr(arguments, "gop_policy", None) or gop_policies.ALL_INTRA
    return pipeline.CarrierProfile(
        _contract_for(codec_policy), frames_per_segment=arguments.frames_per_segment,
        chunk_bytes=arguments.chunk_bytes, registered=registered,
        codec_policy=codec_policy, gop_policy=gop_policy,
        chunk_plan=AdaptiveChunkPlan() if adaptive else None,
        payload_range_length=length,
    )


def _epoch_beacon(arguments: argparse.Namespace) -> EpochChallenge | None:
    """The issuer-signed epoch challenge named by ``--epoch-beacon``, verified."""
    path = getattr(arguments, "epoch_beacon", None)
    if path is None:
        return None
    beacon = EpochChallenge.from_dict(_read_json(path))
    if not beacon.verify(arguments.issuer_public.read_bytes()):
        raise ValueError("epoch beacon signature did not verify against the issuer key")
    if not beacon.is_current(max_age_epochs=arguments.max_age_epochs):
        raise ValueError("epoch beacon is expired or not yet valid")
    return beacon


def _session_for_embed(arguments: argparse.Namespace) -> bytes:
    beacon = _epoch_beacon(arguments)
    if (beacon is None) == (arguments.session is None):
        raise ValueError("supply exactly one of --session or --epoch-beacon")
    return _challenge(arguments.session) if beacon is None else beacon.challenge


def _attachment(arguments: argparse.Namespace) -> video_proof.PayloadRangeAttachment | None:
    length = getattr(arguments, "payload_range_bytes", None)
    return None if length is None else video_proof.payload_range_attachment(PARAMS, length)


def _public_credential(path: Path | None) -> bdlop.Commitment | None:
    if path is None:
        return None
    record = _read_json(path)
    if record.get("parameter_id") != PARAMS.parameter_id.hex():
        raise ValueError("credential was created for another parameter set")
    return bdlop.Commitment.from_bytes(PARAMS, bytes.fromhex(record["commitment"]))


def _verifier_pins(arguments: argparse.Namespace):
    """Resolve pins from verifier-held configuration only."""
    credential = _public_credential(arguments.credential)
    profile = _profile(arguments, registered=credential is not None)
    registry = SignedZkpRelationRegistry.from_dict(_read_json(arguments.registry))
    pins = pipeline.pins_from_registry(
        registry, arguments.issuer_public.read_bytes(), PARAMS, profile,
        minimum_epoch=arguments.minimum_epoch, credential=credential,
        holder_id=arguments.holder_id,
    )
    return pins, profile, credential


# -- issuer --------------------------------------------------------------- #

def _issuer_keygen(arguments: argparse.Namespace) -> dict[str, Any]:
    _require_absent(arguments.public, arguments.private)
    public_key, private_key = LatticeSigner.generate_keypair()
    _write_new(arguments.private, private_key, private=True)
    _write_new(arguments.public, public_key)
    return {"issuer_public": str(arguments.public), "algorithm": "ML-DSA-65"}


def _registry_sign(arguments: argparse.Namespace) -> dict[str, Any]:
    credential = _public_credential(arguments.credential)
    profile = _profile(arguments, registered=credential is not None)
    descriptor = pipeline.relation_descriptor(
        PARAMS, profile, credential, holder_id=arguments.holder_id
    )
    registry = SignedZkpRelationRegistry.create(epoch=arguments.epoch, relations=[descriptor]).sign(
        arguments.issuer_private.read_bytes(), signer_id=arguments.signer_id
    )
    _write_json(arguments.out, registry.to_dict())
    return {"registry": str(arguments.out), "epoch": registry.epoch, "root": registry.root(),
            "mode": "registered" if credential is not None else "in-band",
            "holder_id": arguments.holder_id, "codec_policy": arguments.codec_policy,
            "payload_range_bytes": getattr(arguments, "payload_range_bytes", None)}


def _epoch_issue(arguments: argparse.Namespace) -> dict[str, Any]:
    """Publish one signed challenge for the current time window (offline mode)."""
    _require_absent(arguments.out)
    beacon = EpochChallenge.issue_now(
        arguments.issuer_private.read_bytes(), window_seconds=arguments.window_seconds,
        signer_id=arguments.signer_id,
    )
    _write_json(arguments.out, beacon.to_dict())
    return {"epoch_beacon": str(arguments.out), "epoch_index": beacon.epoch_index,
            "window_seconds": beacon.window_seconds, "challenge": beacon.challenge.hex()}


# -- holder --------------------------------------------------------------- #

def _credential_new(arguments: argparse.Namespace) -> dict[str, Any]:
    _require_absent(arguments.public, arguments.private)
    payload = arguments.payload_file.read_bytes()
    randomness = bdlop.sample_randomness(PARAMS)
    commitment = bdlop.commit(PARAMS, codec.encode_payload(PARAMS, payload), randomness)
    public = {"parameter_id": PARAMS.parameter_id.hex(), "commitment": commitment.to_bytes(PARAMS).hex()}
    secret = {**public, "payload": payload.hex(), "randomness": randomness.astype(np.int8).tobytes().hex()}
    # Secret first: a public credential must never exist without its opening.
    _write_json(arguments.private, secret, private=True)
    _write_json(arguments.public, public)
    return {"credential_public": str(arguments.public)}


def _read_opening(record: dict[str, Any]) -> video_proof.PayloadOpening:
    """Payload and ternary randomness from a holder-private JSON record."""
    if not isinstance(record.get("randomness"), str) or not isinstance(record.get("payload"), str):
        raise ValueError("holder secret is malformed")
    raw = np.frombuffer(bytes.fromhex(record["randomness"]), dtype=np.int8)
    if raw.size != PARAMS.width * PARAMS.degree:
        raise ValueError("holder secret is malformed")
    randomness = raw.astype(np.int64).reshape(PARAMS.width, PARAMS.degree)
    return video_proof.PayloadOpening(bytes.fromhex(record["payload"]), randomness)


def _private_credential(path: Path) -> pipeline.Credential:
    commitment = _public_credential(path)
    if commitment is None:
        raise ValueError("credential secret is malformed")
    opening = _read_opening(_read_json(path))
    message = codec.encode_payload(PARAMS, opening.payload)
    if not bdlop.verify_opening(PARAMS, commitment, message, opening.randomness):
        raise ValueError("credential secret does not open its commitment")
    return pipeline.Credential(commitment, opening.randomness)


def _embed(arguments: argparse.Namespace) -> dict[str, Any]:
    if (arguments.payload_file is None) == (arguments.credential_private is None):
        raise ValueError("supply exactly one of --payload-file or --credential-private")
    if arguments.payload_file is not None and arguments.opening_out is None:
        raise ValueError("--opening-out is required to keep the payload opening")
    # Checked before proving: a stego video whose opening cannot be saved is lost.
    _require_absent(arguments.output, arguments.opening_out)
    credential = None
    if arguments.credential_private is not None:
        credential = _private_credential(arguments.credential_private)
    profile = _profile(arguments, registered=credential is not None)
    registry = SignedZkpRelationRegistry.from_dict(_read_json(arguments.registry))
    pins = pipeline.pins_from_registry(
        registry, arguments.issuer_public.read_bytes(), PARAMS, profile,
        minimum_epoch=arguments.minimum_epoch,
        credential=None if credential is None else credential.commitment,
        holder_id=arguments.holder_id,
    )
    payload = None if credential is not None else arguments.payload_file.read_bytes()
    padded = False
    if payload is not None and profile.payload_range_length is not None:
        # The pinned length is public; the true length hides inside the padding.
        payload = video_proof.pad_payload(payload, profile.payload_range_length)
        padded = True
    result = pipeline.embed_video_proof(
        arguments.video, arguments.output, payload, params=PARAMS, pins=pins, profile=profile,
        session_challenge=_session_for_embed(arguments), sync_key=_sync_key(arguments, profile),
        credential=credential,
    )
    if result.opening is not None:
        _write_json(arguments.opening_out, {
            "payload": result.opening.payload.hex(),
            "randomness": result.opening.randomness.astype(np.int8).tobytes().hex(),
            "padded": padded,
        }, private=True)
    return {"output": str(arguments.output), "statement_id": result.statement_id.hex(),
            "envelope_bytes": result.envelope_bytes, "carriers_used": result.carriers_used,
            "segments_used": result.segments_used, "payload_padded": padded,
            "session_mode": "offline-epoch" if arguments.epoch_beacon is not None else "interactive"}


def _disclose(arguments: argparse.Namespace) -> dict[str, Any]:
    """Reveal the payload of an opening file (or credential secret) with a proof."""
    _require_absent(arguments.out)
    record = _read_json(arguments.opening)
    opening = _read_opening(record)
    commitment = bdlop.commit(PARAMS, codec.encode_payload(PARAMS, opening.payload), opening.randomness)
    pinned = _public_credential(arguments.opening) if "commitment" in record else commitment
    if pinned is None or pinned.to_bytes(PARAMS) != commitment.to_bytes(PARAMS):
        raise ValueError("holder secret does not open its commitment")
    disclosure = video_proof.create_commitment_disclosure(
        PARAMS, commitment, opening,
        statement_id=_hex_32(arguments.statement_id, "statement id"),
        nonce=_hex_32(arguments.nonce, "disclosure nonce"),
    )
    _write_new(arguments.out, disclosure)
    return {"disclosure": str(arguments.out), "disclosure_bytes": len(disclosure),
            "payload_bytes": len(opening.payload)}


# -- verifier ------------------------------------------------------------- #

def _session_issue(arguments: argparse.Namespace) -> dict[str, Any]:
    pins, _profile_unused, _credential = _verifier_pins(arguments)
    store = SessionChallengeStore(arguments.database, ttl_seconds=arguments.ttl_seconds)
    grant = store.issue(context_binding=pipeline.session_binding(PARAMS, pins))
    return grant.to_dict()


def _verify(arguments: argparse.Namespace) -> dict[str, Any]:
    _require_absent(arguments.envelope_out)
    pins, profile, credential = _verifier_pins(arguments)
    if arguments.envelope_out is not None and credential is not None:
        raise ValueError("--envelope-out applies to in-band mode only")
    common = {
        "params": PARAMS, "pins": pins, "profile": profile, "sync_key": _sync_key(arguments, profile),
        "credential": credential, "holder_id": arguments.holder_id,
    }
    beacon = _epoch_beacon(arguments)
    if beacon is None:
        store = SessionChallengeStore(arguments.database, ttl_seconds=arguments.ttl_seconds)
        result = pipeline.verify_video_proof(arguments.video, session_store=store, **common)
    else:
        ledger = OfflineReplayLedger(
            arguments.database, window_seconds=beacon.window_seconds,
            max_age_epochs=arguments.max_age_epochs,
        )
        result = pipeline.verify_video_proof_offline(
            arguments.video, beacon=beacon, issuer_public_key=arguments.issuer_public.read_bytes(),
            ledger=ledger, **common,
        )
    if result.valid and arguments.envelope_out is not None:
        _write_new(arguments.envelope_out, result.envelope)
    return {"valid": result.valid, "reason": result.reason, "carriers_used": result.carriers_used,
            "statement_id": None if result.statement_id is None else result.statement_id.hex(),
            "mode": "registered" if credential is not None else "in-band",
            "holder_id": arguments.holder_id,
            "session_mode": "offline-epoch" if beacon is not None else "interactive"}


def _disclosure_verify(arguments: argparse.Namespace) -> dict[str, Any]:
    """Check a disclosure against a verified envelope or a registered credential."""
    if (arguments.envelope is None) == (arguments.credential is None):
        raise ValueError("supply exactly one of --envelope or --credential")
    if arguments.envelope is not None:
        commitment = video_proof.decode_envelope(
            PARAMS, arguments.envelope.read_bytes(), _attachment(arguments)
        ).commitment
    else:
        commitment = _public_credential(arguments.credential)
    data = arguments.disclosure.read_bytes()
    valid = video_proof.verify_commitment_disclosure(
        PARAMS, commitment, data,
        statement_id=_hex_32(arguments.statement_id, "statement id"),
        nonce=_hex_32(arguments.nonce, "disclosure nonce"),
    )
    payload = video_proof.decode_disclosure(PARAMS, data).payload if valid else None
    report: dict[str, Any] = {"valid": valid, "payload_hex": None if payload is None else payload.hex()}
    if payload is not None and arguments.payload_range_bytes is not None:
        # The holder padded to the pinned length (embed --payload-range-bytes);
        # a disclosed payload without that padding is reported as-is.
        try:
            report["payload_unpadded_hex"] = video_proof.unpad_payload(payload).hex()
        except ValueError:
            report["payload_unpadded_hex"] = None
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.lattice_zk.cli", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    def add(name: str, handler, summary: str) -> argparse.ArgumentParser:
        command = commands.add_parser(name, help=summary, description=summary)
        command.set_defaults(handler=handler)
        return command

    def carrier_options(command: argparse.ArgumentParser) -> None:
        command.add_argument("--frames-per-segment", type=int, default=pipeline.DEFAULT_FRAMES_PER_SEGMENT)
        command.add_argument("--chunk-bytes", type=int, default=pipeline.DEFAULT_CHUNK_BYTES)
        command.add_argument(
            "--codec-policy", choices=sorted(CODEC_POLICIES), default="v2",
            help="v2 (default): full-RBSP canonical digest with tagged raw segments; "
                 "v1: the original digest, for videos and registries made under it; "
                 "cabac: H.264 Main/High (CABAC) streams, carriers in I/IDR slices "
                 "(docs/CABAC_SUPPORT.md)",
        )
        command.add_argument(
            "--gop-policy", choices=sorted(gop_policies.POLICIES), default=gop_policies.ALL_INTRA,
            help="all-intra (default): GOP=1 streams; idr-carriers-inter-raw-v1: GOP>1 streams, "
                 "carriers in IDR slices only, P/B slices bound byte-exactly",
        )
        command.add_argument(
            "--adaptive-chunks", action="store_true",
            help="capacity-adaptive ZKBC v2 transport (replaces --chunk-bytes)",
        )
        command.add_argument(
            "--payload-range-bytes", type=int,
            help="in-band mode: pin this payload length, pad the payload to it and attach a "
                 "payload range proof to the envelope (the length is public)",
        )

    def epoch_options(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--epoch-beacon", type=Path,
            help="offline mode: issuer-signed epoch challenge (epoch-issue output) instead of a "
                 "verifier session",
        )
        command.add_argument(
            "--max-age-epochs", type=int, default=24,
            help="offline mode: accept beacons up to this many windows old",
        )

    def registry_options(command: argparse.ArgumentParser) -> None:
        command.add_argument("--registry", type=Path, required=True)
        command.add_argument("--issuer-public", type=Path, required=True)
        command.add_argument("--minimum-epoch", type=int, required=True)
        command.add_argument(
            "--holder-id", help="holder identity the issuer bound to the registered credential",
        )
        command.add_argument(
            "--public-carrier-order", action="store_true",
            help="derive the carrier order from the public profile instead of the secret stego key "
                 "(public verification; gives up undetectability). Embedder and verifier must "
                 "both use it, or both not; a mismatch simply fails verification.",
        )
        carrier_options(command)

    command = add("issuer-keygen", _issuer_keygen, "Create an ML-DSA-65 issuer key pair.")
    command.add_argument("--public", type=Path, required=True)
    command.add_argument("--private", type=Path, required=True)

    command = add("registry-sign", _registry_sign, "Sign a registry with one BDLOP relation.")
    command.add_argument("--issuer-private", type=Path, required=True)
    command.add_argument("--epoch", type=int, required=True)
    command.add_argument("--signer-id", default="issuer")
    command.add_argument("--credential", type=Path, help="public credential; selects registered mode")
    command.add_argument("--holder-id", help="registered mode: bind the credential to this holder")
    command.add_argument("--out", type=Path, required=True)
    carrier_options(command)

    command = add("epoch-issue", _epoch_issue, "Publish a signed epoch challenge (offline mode).")
    command.add_argument("--issuer-private", type=Path, required=True)
    command.add_argument("--window-seconds", type=int, default=3600)
    command.add_argument("--signer-id", default="issuer")
    command.add_argument("--out", type=Path, required=True)

    command = add("credential-new", _credential_new, "Commit to a credential payload.")
    command.add_argument("--payload-file", type=Path, required=True)
    command.add_argument("--public", type=Path, required=True)
    command.add_argument("--private", type=Path, required=True)

    command = add("embed", _embed, "Prove and embed the envelope into an H.264 video.")
    command.add_argument("--video", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--session", help="verifier-issued challenge (hex); or use --epoch-beacon")
    command.add_argument("--payload-file", type=Path, help="in-band mode: payload to commit to")
    command.add_argument("--opening-out", type=Path, help="in-band mode: where to keep the opening")
    command.add_argument("--credential-private", type=Path, help="registered mode: credential secret")
    registry_options(command)
    epoch_options(command)

    command = add("disclose", _disclose, "Reveal a committed payload to one recipient, in zero knowledge.")
    command.add_argument("--opening", type=Path, required=True,
                         help="embed --opening-out file, or a credential secret")
    command.add_argument("--statement-id", required=True,
                         help="hex: verified video statement id, or the id the recipient names")
    command.add_argument("--nonce", required=True, help="recipient-chosen 32-byte nonce (hex)")
    command.add_argument("--out", type=Path, required=True)

    for name, handler, summary in (
        ("session-issue", _session_issue, "Issue a one-use session challenge."),
        ("verify", _verify, "Verify a stego video from the video alone."),
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
            epoch_options(command)

    command = add("disclosure-verify", _disclosure_verify, "Check a payload disclosure.")
    command.add_argument("--envelope", type=Path, help="envelope saved by verify --envelope-out")
    command.add_argument("--credential", type=Path, help="public credential (registered mode)")
    command.add_argument("--statement-id", required=True, help="hex statement id the holder used")
    command.add_argument("--nonce", required=True, help="the nonce this recipient chose (hex)")
    command.add_argument("--disclosure", type=Path, required=True)
    command.add_argument("--payload-range-bytes", type=int,
                         help="the pinned payload length the envelope was made with, if any")
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
