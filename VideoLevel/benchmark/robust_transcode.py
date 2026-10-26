"""Robust mode under re-compression and tampering (docs/ROBUST_MODE.md).

For each clip and envelope mode: embed with the recommended profile, then
verify blind after a set of re-encodes (expected: accept) and of tampering
operations (expected: reject).  Records stego quality, raw BER before the
convolutional decoder, fingerprint drift, localization and timings.

    python benchmark/robust_transcode.py --clips container_cif foreman_cif_300f akiyo_cif
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.lattice_zk import bdlop, codec
from src.lattice_zk.params import BDLOP_OPEN_128
from src.lattice_zk.video_pipeline import Credential
from src.registry.lattice_pq import LatticeSigner
from src.registry.zkp_registry import SignedZkpRelationRegistry
from src.registry.zkp_sessions import SessionChallengeStore
from src.robust import decode as video_io
from src.robust import pipeline as robust

TRANSCODES = {
    "x264_crf18": ["-c:v", "libx264", "-crf", "18"],
    "x264_crf23": ["-c:v", "libx264", "-crf", "23"],
    "x264_crf28": ["-c:v", "libx264", "-crf", "28"],
    "x265_crf23": ["-c:v", "libx265", "-crf", "23", "-x265-params", "log-level=error"],
    "x264_main_cabac_crf23": ["-c:v", "libx264", "-profile:v", "main", "-coder", "1", "-bf", "2", "-crf", "23"],
}
PATCH = 48
PATCH_FRAME = 150
PATCH_AT = (120, 150)      # (row, col) of the pasted patch
PATCH_FROM = (16, 16)      # copy-move source
DROP_FRAME = 100
SWAP_FRAMES = (60, 240)
RECOLOUR_SHIFT = 16        # added to the U plane of every frame (global recolouring)


def _ffmpeg(*arguments: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *arguments], check=True)


def _psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = float(np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2))
    return float("inf") if mse == 0 else 10 * np.log10(255 ** 2 / mse)


def _ssim(a: np.ndarray, b: np.ndarray) -> float:
    """Mean SSIM over frames (Gaussian 11x11, sigma 1.5, Wang et al. constants)."""
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    scores = []
    for x, y in zip(a.astype(np.float64), b.astype(np.float64)):
        blur = lambda image: cv2.GaussianBlur(image, (11, 11), 1.5)
        mx, my = blur(x), blur(y)
        sxx, syy, sxy = blur(x * x) - mx * mx, blur(y * y) - my * my, blur(x * y) - mx * my
        ssim = ((2 * mx * my + c1) * (2 * sxy + c2)) / ((mx * mx + my * my + c1) * (sxx + syy + c2))
        scores.append(float(ssim[5:-5, 5:-5].mean()))
    return float(np.mean(scores))


def _tampered(stego: Path, work: Path) -> dict[str, Path]:
    decoded = video_io.decode(stego)
    settings = video_io.EncoderSettings(crf=12)
    out: dict[str, Path] = {}

    y = decoded.y.copy()
    (r, c), (sr, sc) = PATCH_AT, PATCH_FROM
    y[PATCH_FRAME, r:r + PATCH, c:c + PATCH] = decoded.y[PATCH_FRAME, sr:sr + PATCH, sc:sc + PATCH]
    out["tamper_patch_48x48"] = work / "patch.mp4"
    video_io.encode(dataclasses.replace(decoded, y=y), out["tamper_patch_48x48"], settings)

    keep = np.r_[0:DROP_FRAME, DROP_FRAME + 1:decoded.frames]
    out["tamper_drop_frame"] = work / "drop.mp4"
    video_io.encode(
        video_io.DecodedVideo(decoded.y[keep], decoded.u[keep], decoded.v[keep], decoded.frame_rate),
        out["tamper_drop_frame"], settings,
    )

    order = np.arange(decoded.frames)
    order[list(SWAP_FRAMES)] = order[list(SWAP_FRAMES[::-1])]
    out["tamper_swap_frames"] = work / "swap.mp4"
    video_io.encode(
        video_io.DecodedVideo(decoded.y[order], decoded.u[order], decoded.v[order], decoded.frame_rate),
        out["tamper_swap_frames"], settings,
    )

    shifted_u = np.clip(decoded.u.astype(np.int64) + RECOLOUR_SHIFT, 0, 255).astype(np.uint8)
    out["tamper_recolour_u+16"] = work / "recolour.mp4"
    video_io.encode(dataclasses.replace(decoded, u=shifted_u), out["tamper_recolour_u+16"], settings)

    out["tamper_downscale_half"] = work / "downscale.mp4"
    _ffmpeg("-i", str(stego), "-vf", "scale=iw/2:ih/2", "-c:v", "libx264", "-crf", "18",
            str(out["tamper_downscale_half"]))
    return out


def _setup(registered: bool, issuer: tuple[bytes, bytes]):
    params = BDLOP_OPEN_128
    profile = robust.RobustProfile.recommended(registered=registered)
    credential = None
    if registered:
        randomness = bdlop.sample_randomness(params)
        credential = Credential(bdlop.commit(params, codec.encode_payload(params, b"camera-7"), randomness), randomness)
    commitment = credential.commitment if credential else None
    descriptor = robust.relation_descriptor(params, profile, commitment)
    registry = SignedZkpRelationRegistry.create(epoch=1, relations=[descriptor]).sign(issuer[1], signer_id="bench")
    pins = robust.pins_from_registry(registry, issuer[0], params, profile, minimum_epoch=1, credential=commitment)
    return params, profile, credential, pins


def run_case(clip: str, registered: bool, issuer, work: Path, frames: int | None) -> dict:
    params, profile, credential, pins = _setup(registered, issuer)
    key = robust.public_sync_key(params, profile)
    cover_path = ROOT / "data" / "raw" / f"{clip}.y4m"
    if frames is not None:
        trimmed = work / f"{clip}_{frames}.y4m"
        _ffmpeg("-i", str(cover_path), "-frames:v", str(frames), str(trimmed))
        cover_path = trimmed
    store = SessionChallengeStore(work / "sessions.sqlite3", ttl_seconds=24 * 3600)
    grant = store.issue(context_binding=robust.session_binding(params, pins))
    stego = work / "stego.mp4"
    started = time.perf_counter()
    embedded = robust.embed_robust_proof(
        cover_path, stego, None if registered else b"robust in-band payload",
        params=params, pins=pins, profile=profile, session_challenge=grant.challenge,
        sync_key=key, credential=credential,
    )
    embed_seconds = time.perf_counter() - started
    cover = video_io.decode(cover_path)
    stego_y = video_io.decode(stego).y
    record = {
        "clip": clip, "mode": "registered" if registered else "in-band",
        "parameter_set": params.name, "frames": cover.frames,
        "resolution": f"{cover.width}x{cover.height}", "profile": profile.descriptor(params),
        "envelope_bytes": embedded.envelope_bytes, "fingerprint_bytes": embedded.fingerprint_bytes,
        "message_bytes": embedded.message_bytes, "code_rate": f"1/{embedded.rate}",
        "coded_bits": embedded.coded_bits, "capacity_slots": embedded.capacity_bits,
        "repetitions": round(embedded.repetitions, 3),
        "watermark_psnr_db": round(embedded.watermark_psnr, 2),
        "stego_psnr_db": round(_psnr(cover.y, stego_y), 2),
        "stego_ssim": round(_ssim(cover.y, stego_y), 4),
        "stego_bytes": stego.stat().st_size, "embed_seconds": round(embed_seconds, 1),
        "cases": {},
    }
    candidates = {"stego": stego}
    for label, arguments in TRANSCODES.items():
        path = work / f"{label}.mkv"
        _ffmpeg("-i", str(stego), *arguments, str(path))
        candidates[label] = path
    candidates.update(_tampered(stego, work))
    for label, path in candidates.items():
        started = time.perf_counter()
        result = robust.verify_robust_proof(
            path, params=params, pins=pins, profile=profile, sync_key=key,
            expected_session=grant.challenge, credential=credential.commitment if credential else None,
        )
        entry = {
            "expected": "reject" if label.startswith("tamper") else "accept",
            "valid": result.valid, "reason": result.reason,
            "raw_ber": None if result.raw_ber is None else round(result.raw_ber, 4),
            "max_frame_ber": None if result.max_frame_ber is None else round(result.max_frame_ber, 4),
            "bad_frames": list(result.bad_frames)[:20], "bad_frame_count": len(result.bad_frames),
            "max_cell_delta": result.max_cell_delta,
            "flagged_cells": [list(cell) for cell in result.flagged_cells[:20]],
            "flagged_cell_count": len(result.flagged_cells),
            "max_chroma_delta": result.max_chroma_delta,
            "flagged_chroma_cells": [list(cell) for cell in result.flagged_chroma_cells[:20]],
            "flagged_chroma_cell_count": len(result.flagged_chroma_cells),
            "damaged_window_count": len(result.damaged_windows),
            "damaged_window_frames": sorted({window[0] for window in result.damaged_windows})[:20],
            "verify_seconds": round(time.perf_counter() - started, 1),
            "file_bytes": path.stat().st_size,
        }
        if label.startswith(("x264", "x265")):
            entry["psnr_vs_cover_db"] = round(_psnr(cover.y, video_io.decode(path).y), 2)
        entry["outcome_as_expected"] = entry["valid"] == (entry["expected"] == "accept")
        record["cases"][label] = entry
        print(f"  {clip} {record['mode']} {label}: valid={result.valid} ({result.reason}) "
              f"ber={entry['raw_ber']} cells>={entry['flagged_cell_count']} "
              f"chroma>={entry['flagged_chroma_cell_count']}", flush=True)
    # Replay through a one-use session store on an accepted re-encode.
    replay_path = candidates["x264_crf18"]
    first = robust.verify_robust_proof(
        replay_path, params=params, pins=pins, profile=profile, sync_key=key, session_store=store,
        credential=credential.commitment if credential else None,
    )
    second = robust.verify_robust_proof(
        replay_path, params=params, pins=pins, profile=profile, sync_key=key, session_store=store,
        credential=credential.commitment if credential else None,
    )
    record["session_replay"] = {"first_valid": first.valid, "replay_valid": second.valid,
                                "replay_reason": second.reason}
    return record


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--clips", nargs="+", default=["container_cif", "foreman_cif_300f", "akiyo_cif"])
    parser.add_argument("--modes", nargs="+", choices=["registered", "in-band"], default=["registered", "in-band"])
    parser.add_argument("--frames", type=int, default=None, help="trim covers (default: whole clip)")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "benchmark" / "results" / "robust" / f"robust_transcode_{_today()}.json")
    arguments = parser.parse_args()
    issuer = LatticeSigner.generate_keypair()
    report = {"date": _today(), "transcodes": TRANSCODES,
              "tamper": {"patch": {"size": PATCH, "frame": PATCH_FRAME, "at": PATCH_AT, "from": PATCH_FROM},
                         "drop_frame": DROP_FRAME, "swap_frames": SWAP_FRAMES, "downscale": "half",
                         "recolour": {"plane": "U", "shift": RECOLOUR_SHIFT, "frames": "all"}},
              "runs": []}
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    for clip in arguments.clips:
        for mode in arguments.modes:
            print(f"{clip} {mode}", flush=True)
            with tempfile.TemporaryDirectory() as work:
                report["runs"].append(run_case(clip, mode == "registered", issuer, Path(work), arguments.frames))
            arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
