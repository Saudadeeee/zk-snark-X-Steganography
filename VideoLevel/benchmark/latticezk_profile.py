"""Time (and optionally profile) lattice-ZK video embed and blind verify.

Runs the same registry/pin setup as ``benchmark.latticezk_video_e2e`` but
skips quality metrics and security re-checks, so the numbers isolate the
transport hot path.  Use a short cut (about 100 CIF frames)::

    python -B -m benchmark.latticezk_profile --video tmp/cut100.h264 \
        --workdir tmp/profile --parameter-set TOY --registered --chunk-bytes 3800 \
        --runs 3 --profile
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import os
import pstats
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark.latticezk_video_e2e import CARRIER_CONTRACTS, DEMO_PAYLOAD  # noqa: E402
from src.lattice_pq import LatticeSigner  # noqa: E402
from src.lattice_zk import bdlop, codec  # noqa: E402
from src.lattice_zk import params as parameter_sets  # noqa: E402
from src.lattice_zk import video_pipeline as pipeline  # noqa: E402
from src.zkp_registry import SignedZkpRelationRegistry  # noqa: E402
from src.zkp_sessions import SessionChallengeStore  # noqa: E402


def _top(profile: cProfile.Profile, limit: int) -> str:
    stream = io.StringIO()
    stats = pstats.Stats(profile, stream=stream)
    stats.sort_stats("cumulative").print_stats(limit)
    stats.sort_stats("tottime").print_stats(limit)
    return stream.getvalue()


def _setup(arguments: argparse.Namespace) -> dict[str, Any]:
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
    issuer_public, issuer_private = LatticeSigner.generate_keypair()
    registry = SignedZkpRelationRegistry.create(
        epoch=1, relations=[pipeline.relation_descriptor(params, profile, pinned)]
    ).sign(issuer_private, signer_id="profile-issuer")
    pins = pipeline.pins_from_registry(
        registry, issuer_public, params, profile, minimum_epoch=1,
        allow_toy_parameters=arguments.parameter_set == "TOY", credential=pinned,
    )
    return {
        "params": params, "profile": profile, "credential": credential,
        "pinned": pinned, "pins": pins,
    }


def _one_run(arguments: argparse.Namespace, setup: dict[str, Any], run_dir: Path, index: int):
    output = run_dir / f"stego_{index}.h264"
    sync_key = bytes(range(32)) if arguments.fixed_key else os.urandom(32)
    result: dict[str, Any] = {}
    profiles: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="latticezk-profile-") as state_dir:
        store = SessionChallengeStore(Path(state_dir) / "sessions.sqlite3", ttl_seconds=3600)
        grant = store.issue(
            context_binding=pipeline.session_binding(setup["params"], setup["pins"])
        )
        for phase in ("embed", "verify"):
            profiler = cProfile.Profile() if arguments.profile else None
            started = time.perf_counter()
            if profiler is not None:
                profiler.enable()
            if phase == "embed":
                outcome = pipeline.embed_video_proof(
                    arguments.video, output,
                    None if arguments.registered else DEMO_PAYLOAD,
                    params=setup["params"], pins=setup["pins"], profile=setup["profile"],
                    credential=setup["credential"], session_challenge=grant.challenge,
                    sync_key=sync_key,
                )
            else:
                outcome = pipeline.verify_video_proof(
                    output, params=setup["params"], pins=setup["pins"],
                    profile=setup["profile"], sync_key=sync_key, session_store=store,
                    credential=setup["pinned"],
                )
            if profiler is not None:
                profiler.disable()
                profiles[phase] = _top(profiler, arguments.top)
            result[f"{phase}_s"] = round(time.perf_counter() - started, 3)
            if phase == "verify":
                result["verified"] = bool(outcome.valid)
                result["reason"] = outcome.reason
            else:
                result["carriers_used"] = outcome.carriers_used
    return result, profiles


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--parameter-set", default="TOY")
    parser.add_argument("--frames-per-segment", type=int, default=pipeline.DEFAULT_FRAMES_PER_SEGMENT)
    parser.add_argument("--chunk-bytes", type=int, default=pipeline.DEFAULT_CHUNK_BYTES)
    parser.add_argument("--carrier", choices=sorted(CARRIER_CONTRACTS), default="magnitude")
    parser.add_argument("--registered", action="store_true")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--profile", action="store_true", help="cProfile the first run")
    parser.add_argument("--top", type=int, default=35)
    parser.add_argument("--fixed-key", action="store_true", help="use a fixed sync key")
    arguments = parser.parse_args()
    arguments.video = arguments.video.resolve(strict=True)
    arguments.workdir.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="runs-", dir=arguments.workdir))

    setup = _setup(arguments)
    runs = []
    for index in range(arguments.runs):
        profile_this = arguments.profile and index == 0
        saved = arguments.profile
        arguments.profile = profile_this
        result, profiles = _one_run(arguments, setup, run_dir, index)
        arguments.profile = saved
        runs.append(result)
        for phase, text in profiles.items():
            (run_dir / f"profile_{phase}.txt").write_text(text, encoding="utf-8")
        sys.stderr.write(json.dumps(result) + "\n")
    summary = {"video": str(arguments.video), "run_dir": str(run_dir), "runs": runs}
    sys.stdout.write(json.dumps(summary, indent=2) + "\n")
    return 0 if all(run["verified"] for run in runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
