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
import dataclasses
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

from src.transport import gop_policy as gop_policies  # noqa: E402
from src.transport.adaptive_chunks import AdaptiveChunkPlan  # noqa: E402
from src.transport.blind_sync import (  # noqa: E402
    T1_SPS_GEOMETRY_CONTRACT_VERSION,
    AdaptiveOperatingContract,
    BlindOperatingContract,
    GeometryOrderedAdaptiveContract,
    GeometryOrderedOperatingContract,
)
from src.registry.lattice_pq import LatticeSigner  # noqa: E402
from src.lattice_zk import params as parameter_sets  # noqa: E402
from src.lattice_zk import video_pipeline as pipeline  # noqa: E402
from benchmark.latticezk_quality import frame_quality  # noqa: E402
from src.lattice_zk import bdlop, codec, linkage, video_proof  # noqa: E402
from src.registry.zkp_registry import SignedZkpRelationRegistry  # noqa: E402
from src.registry.zkp_sessions import SessionChallengeStore  # noqa: E402

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
# (docs/CARRIERS_VA_CHUNKING.md): fewer, cheaper changes for the same envelope.
ADAPTIVE_CONTRACT = AdaptiveOperatingContract()
ADAPTIVE_TEXTURE_CONTRACT = AdaptiveOperatingContract(cost_model="texture-magnitude-v1")
# Resolution-aware variants (src/core/carrier_order.py): the same carriers in
# an order computed on the SPS macroblock grid instead of a CIF 22 x 18 grid.
# New contract versions, hence new carrier profile ids; the originals above
# keep their ids, positions and stego bytes.
GEOMETRY_CONTRACT = GeometryOrderedOperatingContract()
T1_GEOMETRY_CONTRACT = GeometryOrderedOperatingContract(
    version=T1_SPS_GEOMETRY_CONTRACT_VERSION, signbit_only=True,
)
ADAPTIVE_GEOMETRY_CONTRACT = GeometryOrderedAdaptiveContract()
CARRIER_CONTRACTS = {
    "magnitude": CONTRACT, "t1": T1_SIGN_CONTRACT,
    "adaptive": ADAPTIVE_CONTRACT, "adaptive-texture": ADAPTIVE_TEXTURE_CONTRACT,
    "magnitude-geo": GEOMETRY_CONTRACT, "t1-geo": T1_GEOMETRY_CONTRACT,
    "adaptive-geo": ADAPTIVE_GEOMETRY_CONTRACT,
}
DEMO_PAYLOAD = b"zkstego lattice-ZK demo payload: hidden provenance record #0001"
CODEC_POLICIES = {"v1": pipeline.CODEC_POLICY_V1, "v2": pipeline.CODEC_POLICY_V2}


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


def _link_to_credential(params, embedded, verified, allow_toy: bool = False) -> dict[str, Any] | None:
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
        "linked_to_credential": linkage.verify_linkage(
            params, context, in_video, credential, proof, allow_toy_parameters=allow_toy
        ),
        "other_credential_rejected": not linkage.verify_linkage(
            params, context, in_video, stranger, proof, allow_toy_parameters=allow_toy
        ),
        "disclosure_bytes": len(disclosure),
        "disclose_s": round(disclose_s, 3),
        "disclosure_verifies": video_proof.verify_disclosure_proof(
            params, verified.envelope, disclosure, statement_id=verified.statement_id, nonce=nonce,
            allow_toy_parameters=allow_toy,
        ),
    }


def _slice_nal_comparison(cover: Path, stego: Path) -> dict[str, int]:
    """Count IDR / non-IDR slice NAL units that the embedding left byte-identical."""
    cover_bytes, stego_bytes = cover.read_bytes(), stego.read_bytes()
    cover_nals = [cover_bytes[a:b] for a, b in gop_policies.nal_unit_spans(cover_bytes)]
    stego_nals = [stego_bytes[a:b] for a, b in gop_policies.nal_unit_spans(stego_bytes)]
    report = {"nal_units": len(cover_nals), "nal_count_matches": len(cover_nals) == len(stego_nals),
              "idr_slices": 0, "idr_slices_changed": 0, "non_idr_slices": 0,
              "non_idr_slices_identical": 0, "other_nal_units_changed": 0}
    for before, after in zip(cover_nals, stego_nals):
        nal_type = before[0] & 0x1F
        if nal_type == gop_policies.NAL_SLICE_IDR:
            report["idr_slices"] += 1
            report["idr_slices_changed"] += before != after
        elif nal_type == gop_policies.NAL_SLICE_NON_IDR:
            report["non_idr_slices"] += 1
            report["non_idr_slices_identical"] += before == after
        else:
            report["other_nal_units_changed"] += before != after
    return report


def _verify_tampered(output, data: bytes, params, pins, profile, sync_key, pinned, challenge):
    tampered = output.with_suffix(".tampered.h264")
    tampered.write_bytes(data)
    try:
        result = pipeline.verify_video_proof(
            tampered, params=params, pins=pins, profile=profile, sync_key=sync_key,
            expected_session=challenge, credential=pinned,
            allow_toy_parameters=params.challenge_space_bits < 256,
        )
        return not result.valid, result.reason
    except Exception as error:  # a corrupted stream may fail to parse at all
        return True, f"{type(error).__name__}: {error}"
    finally:
        tampered.unlink(missing_ok=True)


def _p_slice_tamper_check(output, params, pins, profile, sync_key, pinned, challenge):
    """Flip one bit inside the first non-IDR slice; ``None`` for all-intra streams."""
    data = bytearray(output.read_bytes())
    for start, end in gop_policies.nal_unit_spans(bytes(data)):
        if data[start] & 0x1F == gop_policies.NAL_SLICE_NON_IDR and end - start > 4:
            data[(start + end) // 2] ^= 0x01
            return _verify_tampered(output, bytes(data), params, pins, profile, sync_key,
                                    pinned, challenge)
    return None


def _segment_tamper_check(output, segment_index, params, pins, profile, sync_key, pinned,
                          challenge):
    """Flip one bit in the first slice of ``segment_index`` (one slice per picture)."""
    data = bytearray(output.read_bytes())
    first_picture = segment_index * profile.frames_per_segment
    pictures = 0
    for start, end in gop_policies.nal_unit_spans(bytes(data)):
        if data[start] & 0x1F in (gop_policies.NAL_SLICE_IDR, gop_policies.NAL_SLICE_NON_IDR):
            if pictures == first_picture and end - start > 4:
                data[(start + end) // 2] ^= 0x01
                return _verify_tampered(output, bytes(data), params, pins, profile, sync_key,
                                        pinned, challenge)
            pictures += 1
    return None


def _adaptive_checks(output, embedded, params, pins, profile, sync_key, pinned, challenge):
    """Tamper a skipped segment; verify under a different plan (its own registry)."""
    used = {segment for segment, _size in embedded.chunk_layout}
    skipped = [index for index in range(len(embedded.segment_capacity_bits)) if index not in used]
    skipped_tamper = None
    if skipped:
        skipped_tamper = _segment_tamper_check(
            output, skipped[0], params, pins, profile, sync_key, pinned, challenge
        )
    plan = profile.chunk_plan
    other_plan = dataclasses.replace(plan, min_chunk_bytes=max(1, plan.min_chunk_bytes // 2))
    if other_plan == plan:
        other_plan = dataclasses.replace(plan, min_chunk_bytes=plan.min_chunk_bytes + 1)
    other_profile = dataclasses.replace(profile, chunk_plan=other_plan)
    issuer_public, issuer_private = LatticeSigner.generate_keypair()
    registry = SignedZkpRelationRegistry.create(
        epoch=1, relations=[pipeline.relation_descriptor(params, other_profile, pinned)]
    ).sign(issuer_private, signer_id="e2e-other-plan")
    other_pins = pipeline.pins_from_registry(
        registry, issuer_public, params, other_profile, minimum_epoch=1,
        allow_toy_parameters=params.challenge_space_bits < 256, credential=pinned,
    )
    mismatch = pipeline.verify_video_proof(
        output, params=params, pins=other_pins, profile=other_profile, sync_key=sync_key,
        expected_session=challenge, credential=pinned,
        allow_toy_parameters=params.challenge_space_bits < 256,
    )
    return {
        "skipped_segments": skipped,
        "skipped_segment_tamper_rejected": None if skipped_tamper is None else skipped_tamper[0],
        "skipped_segment_tamper_reason": None if skipped_tamper is None else skipped_tamper[1],
        "other_plan": other_plan.descriptor(),
        "other_plan_rejected": not mismatch.valid,
        "other_plan_reason": mismatch.reason,
    }


def _trailing_rbsp_tamper_check(output, params, pins, profile, sync_key, pinned, challenge):
    """Append one zero byte after the RBSP stop bit of a carrier-bearing IDR NAL unit.

    Codec policy v1 does not bind zero bits after the stop bit of a carrier
    NAL unit (D5); v2 hashes the full RBSP, so the copy must be rejected.
    """
    if profile.chunk_plan is None:
        from src.transport.blind_sync_streaming import extract_chunked_video_payload

        extracted = extract_chunked_video_payload(
            output, sync_key, profile.contract, **profile.options()
        )
    else:
        from src.transport.blind_sync_adaptive import extract_adaptive_video_payload

        extracted = extract_adaptive_video_payload(
            output, sync_key, profile.contract, plan=profile.chunk_plan, **profile.options()
        )
    data = output.read_bytes()
    idr = [span for span in gop_policies.nal_unit_spans(data)
           if data[span[0]] & 0x1F == gop_policies.NAL_SLICE_IDR]
    macroblocks = len(extracted.global_positions) and max(
        position[0] for position in extracted.global_positions
    )
    # Every coded slice has a picture-sized macroblock slot, so (all-intra)
    # the slot of a carrier's macroblock is the index of its IDR NAL unit.
    sps = next(data[s:e] for s, e in gop_policies.nal_unit_spans(data) if data[s] & 0x1F == 7)
    per_picture = gop_policies._check_sps(sps[1:].replace(b"\x00\x00\x03", b"\x00\x00"))
    frames = sorted({mb // per_picture for mb, _block, _coefficient in extracted.global_positions})
    for frame in reversed(frames):
        _start, end = idr[frame]
        if end == len(data) or data[end:end + 4] == b"\x00\x00\x00\x01":
            rejected, reason = _verify_tampered(
                output, data[:end] + b"\x00" + data[end:], params, pins, profile, sync_key,
                pinned, challenge,
            )
            return {"carrier_frame": frame, "carrier_frames": len(frames),
                    "max_carrier_macroblock": macroblocks, "inserted_at_byte": end,
                    "rejected": rejected, "reason": reason}
    return None


def _security_checks(output, params, pins, profile, sync_key, store, pinned, challenge):
    """Replay the consumed session, then verify a copy with one flipped bit."""
    replay = pipeline.verify_video_proof(
        output, params=params, pins=pins, profile=profile, sync_key=sync_key,
        session_store=store, credential=pinned,
        allow_toy_parameters=params.challenge_space_bits < 256,
    )
    logger.info("replay_rejected=%s", not replay.valid)
    stego_bytes = bytearray(output.read_bytes())
    stego_bytes[len(stego_bytes) // 2] ^= 0x01
    tamper_rejected, tamper_reason = _verify_tampered(
        output, bytes(stego_bytes), params, pins, profile, sync_key, pinned, challenge
    )
    return not replay.valid, tamper_rejected, tamper_reason


def _chunk_plan(arguments: argparse.Namespace) -> AdaptiveChunkPlan | None:
    if not arguments.adaptive_chunks:
        return None
    return AdaptiveChunkPlan(
        min_chunk_bytes=arguments.min_chunk_bytes, reserve_bits=arguments.reserve_bits,
        fill_permille=arguments.fill_permille, max_chunk_bytes=arguments.max_chunk_bytes,
    )


def run(arguments: argparse.Namespace) -> dict[str, Any]:
    params = getattr(parameter_sets, arguments.parameter_set)
    profile = pipeline.CarrierProfile(
        CARRIER_CONTRACTS[arguments.carrier], frames_per_segment=arguments.frames_per_segment,
        chunk_bytes=arguments.chunk_bytes, registered=arguments.registered,
        gop_policy=arguments.gop_policy, codec_policy=CODEC_POLICIES[arguments.codec_policy],
        chunk_plan=_chunk_plan(arguments),
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
            allow_toy_parameters=arguments.parameter_set == "TOY",
        )
        timings["verify_s"] = time.perf_counter() - started
        logger.info("verified=%s", verified.valid)
        linkage_report = _link_to_credential(
            params, embedded, verified, allow_toy=arguments.parameter_set == "TOY"
        )
        logger.info("credential_linkage %s", json.dumps(linkage_report, sort_keys=True))
        replay_rejected = tamper_rejected = None
        tamper_reason = "not run (--skip-security-checks)"
        p_slice_tamper = None
        adaptive_checks = None
        trailing_rbsp_tamper = None
        if not arguments.skip_security_checks:
            replay_rejected, tamper_rejected, tamper_reason = _security_checks(
                output, params, pins, profile, sync_key, store, pinned, grant.challenge
            )
            p_slice_tamper = _p_slice_tamper_check(
                output, params, pins, profile, sync_key, pinned, grant.challenge
            )
            if profile.chunk_plan is not None:
                adaptive_checks = _adaptive_checks(
                    output, embedded, params, pins, profile, sync_key, pinned, grant.challenge
                )
                logger.info("adaptive_checks %s", json.dumps(adaptive_checks, sort_keys=True))
            if arguments.trailing_rbsp_check:
                trailing_rbsp_tamper = _trailing_rbsp_tamper_check(
                    output, params, pins, profile, sync_key, pinned, grant.challenge
                )

    report = {
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
        "gop_policy": profile.gop_policy,
        "codec_policy": profile.codec_policy,
        "codec_policy_id": pipeline.codec_policy_id(profile.codec_policy).hex(),
        "carrier_profile_id": profile.profile_id(params).hex(),
        "statement_id": embedded.statement_id.hex(),
        "blind_video_only_verification": verified.valid,
        "verify_reason": verified.reason,
        "replay_rejected": replay_rejected,
        "tamper_rejected": tamper_rejected,
        "tamper_reason": tamper_reason,
        "p_slice_tamper_rejected": None if p_slice_tamper is None else p_slice_tamper[0],
        "p_slice_tamper_reason": None if p_slice_tamper is None else p_slice_tamper[1],
        "trailing_rbsp_zero_tamper": trailing_rbsp_tamper,
        "slice_nal_comparison": _slice_nal_comparison(cover, output),
        "payload_absent_from_output": DEMO_PAYLOAD not in output.read_bytes(),
        "decoded_quality": _decoded_quality(cover, output),
        "frame_quality": frame_quality(cover, output),
        "credential_linkage": linkage_report,
        "timings_s": {name: round(value, 3) for name, value in timings.items()},
    }
    if profile.chunk_plan is not None:
        # Only adaptive runs carry these keys; fixed-chunk reports are unchanged.
        report["chunk_bytes"] = None
        report["adaptive_chunking"] = {
            "transport": "zkbc-v2 capacity-adaptive (src/transport/blind_sync_adaptive.py)",
            "chunk_plan": profile.chunk_plan.descriptor(),
            "plan_id": profile.chunk_plan.plan_id().hex(),
            "segment_capacity_bits": list(embedded.segment_capacity_bits),
            "chunk_layout": [{"segment": segment, "bytes": size}
                             for segment, size in embedded.chunk_layout],
            "checks": adaptive_checks,
        }
    return report


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
        "adaptive-texture: the same with texture/magnitude costs; *-geo: the same carriers "
        "ordered on the SPS macroblock grid (resolution-aware, new contract versions)",
    )
    parser.add_argument(
        "--skip-security-checks", action="store_true",
        help="skip the replay and tamper re-verifications (each re-extracts the whole video)",
    )
    parser.add_argument(
        "--gop-policy", choices=gop_policies.POLICIES, default=gop_policies.ALL_INTRA,
        help="all-intra: GOP=1 streams only; idr-carriers-inter-raw-v1: GOP>1 Baseline streams, "
        "carriers in IDR slices, P slices bound byte-exactly (docs/GOP_HD_SUPPORT.md)",
    )
    parser.add_argument(
        "--adaptive-chunks", action="store_true",
        help="capacity-adaptive ZKBC v2 transport: chunk sizes follow each segment's capacity, "
        "low-capacity segments are skipped (docs/CARRIERS_VA_CHUNKING.md); replaces --chunk-bytes",
    )
    defaults = AdaptiveChunkPlan()
    parser.add_argument("--min-chunk-bytes", type=int, default=defaults.min_chunk_bytes,
                        help="adaptive plan: skip segments whose usable chunk is smaller")
    parser.add_argument("--fill-permille", type=int, default=defaults.fill_permille,
                        help="adaptive plan: use this fraction (per mille) of each segment's carriers")
    parser.add_argument("--reserve-bits", type=int, default=defaults.reserve_bits,
                        help="adaptive plan: carriers left unused per segment")
    parser.add_argument("--max-chunk-bytes", type=int, default=defaults.max_chunk_bytes,
                        help="adaptive plan: largest chunk per segment")
    parser.add_argument(
        "--codec-policy", choices=sorted(CODEC_POLICIES), default="v1",
        help="v1: original canonical digest (default, unchanged identifiers); v2: full RBSP of "
        "carrier NAL units, tagged raw segments, pinned access-unit segmentation (D5)",
    )
    parser.add_argument(
        "--trailing-rbsp-check", action="store_true",
        help="also verify a copy with a zero byte appended after the RBSP stop bit of a "
        "carrier-bearing IDR NAL unit (one extra extraction and verification)",
    )
    parser.add_argument(
        "--registered", action="store_true",
        help="prove a registry-pinned credential commitment; the video carries only the proof",
    )
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stderr)
    if arguments.output.exists() or arguments.report.exists():
        parser.error("refusing to overwrite an existing output or report")
    if arguments.adaptive_chunks and arguments.chunk_bytes != pipeline.DEFAULT_CHUNK_BYTES:
        parser.error("--adaptive-chunks replaces --chunk-bytes")
    report = run(arguments)
    arguments.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    slices = report["slice_nal_comparison"]
    # Embedding may rewrite only IDR slices.
    untouched = (slices["nal_count_matches"] and slices["other_nal_units_changed"] == 0
                 and slices["non_idr_slices_identical"] == slices["non_idr_slices"])
    p_slice_check = (report["p_slice_tamper_rejected"] is True if slices["non_idr_slices"]
                     else report["p_slice_tamper_rejected"] is None)
    adaptive = (report.get("adaptive_chunking") or {}).get("checks")
    adaptive_check = adaptive is None or (
        adaptive["other_plan_rejected"]
        and adaptive["skipped_segment_tamper_rejected"] in (True, None)
    )
    trailing = report["trailing_rbsp_zero_tamper"]
    # Under v2 the zero-extended carrier NAL unit must be rejected (D5); under
    # v1 the outcome is recorded only, since v1 does not bind those bits.
    trailing_check = (
        not arguments.trailing_rbsp_check or arguments.codec_policy != "v2"
        or (trailing is not None and trailing["rejected"] is True)
    )
    passed = report["blind_video_only_verification"] and untouched and (
        arguments.skip_security_checks
        or (report["replay_rejected"] and report["tamper_rejected"] and p_slice_check
            and adaptive_check and trailing_check)
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
