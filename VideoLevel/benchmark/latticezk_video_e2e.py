"""End-to-end run: BDLOP opening proof embedded in, and verified from, H.264.

Embeds the fixed-size lattice-ZK envelope into CAVLC carriers of a cover
video, then verifies it from the stego video alone with a one-use session
challenge, and checks that a replay and a tampered copy are rejected.

    python -m benchmark.latticezk_video_e2e \
        --video data/encoded/coastguard_cif_q22_g1_3000f.h264 \
        --output tmp/latticezk_e2e.h264 --report tmp/latticezk_e2e.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.blind_sync import AdaptiveOperatingContract, BlindOperatingContract  # noqa: E402
from src.lattice_pq import LatticeSigner  # noqa: E402
from src.lattice_zk import params as parameter_sets  # noqa: E402
from src.lattice_zk import video_pipeline as pipeline  # noqa: E402
from benchmark.latticezk_quality import frame_quality  # noqa: E402
from src.lattice_zk import bdlop, codec, linkage, video_proof  # noqa: E402
from src.zkp_registry import SignedZkpRelationRegistry  # noqa: E402
from src.zkp_sessions import SessionChallengeStore  # noqa: E402

logger = logging.getLogger("latticezk_video_e2e")

CONTRACT = BlindOperatingContract(
    version="stable-carriers-video-only-v1",
    require_bitstream_patchable=True,
    patchability_headroom=64,
    max_modifications_per_block=1,
    stable_carriers_only=True,
)
# Original trailing-one sign-flip carrier: one sign per block, carrier set
# invariant under the flip because trailing ones are defined by magnitudes.
T1_SIGN_CONTRACT = BlindOperatingContract(
    # v2: the carrier analysis skips the magnitude pass, which changes the
    # pre-shuffle candidate order; v1 videos do not extract under v2.
    version="t1-sign-video-only-v2",
    signbit_only=True,
    require_bitstream_patchable=True,
    patchability_headroom=64,
    max_modifications_per_block=1,
    stable_carriers_only=True,
)
# Same stable magnitude carriers, cost-adaptive syndrome-trellis coded
# (docs/ADAPTIVE_CARRIERS.md): fewer, cheaper changes for the same envelope.
ADAPTIVE_CONTRACT = AdaptiveOperatingContract()
ADAPTIVE_TEXTURE_CONTRACT = AdaptiveOperatingContract(cost_model="texture-magnitude-v1")
CARRIER_CONTRACTS = {
    "magnitude": CONTRACT, "t1": T1_SIGN_CONTRACT,
    "adaptive": ADAPTIVE_CONTRACT, "adaptive-texture": ADAPTIVE_TEXTURE_CONTRACT,
}
DEMO_PAYLOAD = b"zkstego lattice-ZK demo payload: hidden provenance record #0001"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _log_progress(event: dict[str, Any]) -> None:
    logger.info("progress %s", json.dumps(event, sort_keys=True, default=str))


def _decoded_quality(cover: Path, stego: Path) -> dict[str, float | None]:
    """Whole-video PSNR/SSIM of the decoded stego stream against the cover."""
    completed = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-i", str(stego), "-i", str(cover),
         "-lavfi", "[0:v][1:v]psnr;[0:v][1:v]ssim", "-f", "null", "-"],
        capture_output=True, text=True, timeout=3600, check=False,
    )
    psnr = re.search(r"PSNR .*average:(inf|[0-9.]+)", completed.stderr)
    ssim = re.search(r"SSIM .*All:([0-9.]+)", completed.stderr)
    return {
        "psnr_average_db": None if psnr is None or psnr.group(1) == "inf" else float(psnr.group(1)),
        "psnr_is_lossless": psnr is not None and psnr.group(1) == "inf",
        "ssim_all": None if ssim is None else float(ssim.group(1)),
    }


def _link_to_credential(params, embedded, verified) -> dict[str, Any] | None:
    """Link the commitment extracted from the video to a credential commitment.

    Only meaningful for in-band envelopes: shows, from the bytes the verifier
    extracted, that the hidden payload equals a separately committed record.
    """
    if embedded.opening is None or verified.envelope is None:
        return None
    randomness = bdlop.sample_randomness(params)
    credential = bdlop.commit(params, codec.encode_payload(params, DEMO_PAYLOAD), randomness)
    in_video = linkage.envelope_commitment(params, verified.envelope)
    context = (verified.statement_id, credential.to_bytes(params))
    started = time.perf_counter()
    proof = linkage.prove_linkage(
        params, context, in_video, embedded.opening.randomness, credential, randomness
    )
    prove_s = time.perf_counter() - started
    stranger = bdlop.commit(
        params, codec.encode_payload(params, DEMO_PAYLOAD), bdlop.sample_randomness(params)
    )
    # Zero-knowledge disclosure: the payload plus an equality proof bound to a
    # recipient nonce; the opening randomness is never handed over.
    nonce = os.urandom(video_proof.DISCLOSURE_NONCE_BYTES)
    started = time.perf_counter()
    disclosure = video_proof.create_disclosure(
        params, verified.envelope, embedded.opening, statement_id=verified.statement_id, nonce=nonce
    )
    disclose_s = time.perf_counter() - started
    return {
        "proof_bytes": len(proof),
        "prove_s": round(prove_s, 3),
        "linked_to_credential": linkage.verify_linkage(params, context, in_video, credential, proof),
        "other_credential_rejected": not linkage.verify_linkage(
            params, context, in_video, stranger, proof
        ),
        "disclosure_bytes": len(disclosure),
        "disclose_s": round(disclose_s, 3),
        "disclosure_verifies": video_proof.verify_disclosure_proof(
            params, verified.envelope, disclosure, statement_id=verified.statement_id, nonce=nonce
        ),
    }


def _security_checks(output, params, pins, profile, sync_key, store, pinned, challenge):
    """Replay the consumed session, then verify a copy with one flipped bit."""
    replay = pipeline.verify_video_proof(
        output, params=params, pins=pins, profile=profile, sync_key=sync_key,
        session_store=store, credential=pinned,
    )
    logger.info("replay_rejected=%s", not replay.valid)
    tampered = output.with_suffix(".tampered.h264")
    stego_bytes = bytearray(output.read_bytes())
    stego_bytes[len(stego_bytes) // 2] ^= 0x01
    tampered.write_bytes(bytes(stego_bytes))
    try:
        result = pipeline.verify_video_proof(
            tampered, params=params, pins=pins, profile=profile, sync_key=sync_key,
            expected_session=challenge, credential=pinned,
        )
        tamper_rejected, tamper_reason = not result.valid, result.reason
    except Exception as error:  # a corrupted stream may fail to parse at all
        tamper_rejected, tamper_reason = True, f"{type(error).__name__}: {error}"
    finally:
        tampered.unlink(missing_ok=True)
    return not replay.valid, tamper_rejected, tamper_reason


def run(arguments: argparse.Namespace) -> dict[str, Any]:
    params = getattr(parameter_sets, arguments.parameter_set)
    profile = pipeline.CarrierProfile(
        CARRIER_CONTRACTS[arguments.carrier], frames_per_segment=arguments.frames_per_segment,
        chunk_bytes=arguments.chunk_bytes, registered=arguments.registered,
    )
    credential = None
    if arguments.registered:
        randomness = bdlop.sample_randomness(params)
        message = codec.encode_payload(params, DEMO_PAYLOAD)
        credential = pipeline.Credential(bdlop.commit(params, message, randomness), randomness)
    pinned = None if credential is None else credential.commitment
    cover, output = arguments.video.resolve(strict=True), arguments.output.resolve()
    sync_key = os.urandom(32)
    issuer_public, issuer_private = LatticeSigner.generate_keypair()
    registry = SignedZkpRelationRegistry.create(
        epoch=1, relations=[pipeline.relation_descriptor(params, profile, pinned)]
    ).sign(issuer_private, signer_id="e2e-issuer")
    pins = pipeline.pins_from_registry(
        registry, issuer_public, params, profile, minimum_epoch=1,
        allow_toy_parameters=arguments.parameter_set == "TOY", credential=pinned,
    )
    timings: dict[str, float] = {}

    with tempfile.TemporaryDirectory(prefix="latticezk-e2e-") as state_dir:
        store = SessionChallengeStore(Path(state_dir) / "sessions.sqlite3", ttl_seconds=24 * 3600)
        grant = store.issue(context_binding=pipeline.session_binding(params, pins))

        started = time.perf_counter()
        embedded = pipeline.embed_video_proof(
            cover, output, None if arguments.registered else DEMO_PAYLOAD,
            params=params, pins=pins, profile=profile, credential=credential,
            session_challenge=grant.challenge, sync_key=sync_key, progress_callback=_log_progress,
        )
        timings["embed_s"] = time.perf_counter() - started

        started = time.perf_counter()
        verified = pipeline.verify_video_proof(
            output, params=params, pins=pins, profile=profile, sync_key=sync_key,
            session_store=store, credential=pinned, progress_callback=_log_progress,
        )
        timings["verify_s"] = time.perf_counter() - started
        logger.info("verified=%s", verified.valid)
        linkage_report = _link_to_credential(params, embedded, verified)
        logger.info("credential_linkage %s", json.dumps(linkage_report, sort_keys=True))
        replay_rejected = tamper_rejected = None
        tamper_reason = "not run (--skip-security-checks)"
        if not arguments.skip_security_checks:
            replay_rejected, tamper_rejected, tamper_reason = _security_checks(
                output, params, pins, profile, sync_key, store, pinned, grant.challenge
            )

    return {
        "protocol": "bdlop-open-v1 in-band H.264 CAVLC",
        "mode": "registered-commitment" if arguments.registered else "in-band-commitment",
        "carrier": arguments.carrier,
        "carrier_contract": CARRIER_CONTRACTS[arguments.carrier].version,
        "security_status": "research prototype; self-implemented published protocol; unaudited",
        "parameter_set": params.name,
        "parameter_id": params.parameter_id.hex(),
        "input_video": cover.name,
        "input_video_sha256": _sha256_file(cover),
        "output_video_sha256": _sha256_file(output),
        "envelope_bytes": embedded.envelope_bytes,
        "commitment_bytes_in_video": 0 if arguments.registered else params.commitment_bytes,
        "proof_bytes": params.proof_bytes,
        "expected_envelope_bytes": video_proof.envelope_size(params, registered=arguments.registered),
        "carriers_used": embedded.carriers_used,
        "segments_used": embedded.segments_used,
        "frames_per_segment": profile.frames_per_segment,
        "chunk_bytes": profile.chunk_bytes,
        "statement_id": embedded.statement_id.hex(),
        "blind_video_only_verification": verified.valid,
        "verify_reason": verified.reason,
        "replay_rejected": replay_rejected,
        "tamper_rejected": tamper_rejected,
        "tamper_reason": tamper_reason,
        "payload_absent_from_output": DEMO_PAYLOAD not in output.read_bytes(),
        "decoded_quality": _decoded_quality(cover, output),
        "frame_quality": frame_quality(cover, output),
        "credential_linkage": linkage_report,
        "timings_s": {name: round(value, 3) for name, value in timings.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--parameter-set", default="BDLOP_OPEN_128")
    parser.add_argument("--frames-per-segment", type=int, default=pipeline.DEFAULT_FRAMES_PER_SEGMENT)
    parser.add_argument("--chunk-bytes", type=int, default=pipeline.DEFAULT_CHUNK_BYTES)
    parser.add_argument(
        "--carrier", choices=sorted(CARRIER_CONTRACTS), default="magnitude",
        help="magnitude: LSB of the first |level|>=4 AC coefficient; t1: trailing-one sign flip; "
        "adaptive: the magnitude carriers, syndrome-trellis coded (fewest changes); "
        "adaptive-texture: the same with texture/magnitude costs",
    )
    parser.add_argument(
        "--skip-security-checks", action="store_true",
        help="skip the replay and tamper re-verifications (each re-extracts the whole video)",
    )
    parser.add_argument(
        "--registered", action="store_true",
        help="prove a registry-pinned credential commitment; the video carries only the proof",
    )
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stderr)
    if arguments.output.exists() or arguments.report.exists():
        parser.error("refusing to overwrite an existing output or report")
    report = run(arguments)
    arguments.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    passed = report["blind_video_only_verification"] and (
        arguments.skip_security_checks
        or (report["replay_rejected"] and report["tamper_rejected"])
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
