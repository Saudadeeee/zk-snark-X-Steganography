"""Diagnostic for experimental future trust-plane modules.

This benchmark is diagnostic-grade only. It validates interface behavior for:
- provenance root anchoring,
- fingerprint registry lookup,
- watermark receipt,
- mock TEE attestation,
- ZKML interface contract.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from src.manifest import StegoManifest, VideoMetadata
from src.provenance import attach_anchor_to_manifest, build_c2pa_anchor, verify_c2pa_anchor
from src.trust import (
    AttestationBundle,
    AttestationSidecar,
    CalibratedThresholdDetector,
    FingerprintPreprocessPolicy,
    FingerprintRecord,
    FingerprintRegistry,
    MockTEESigner,
    TinyThresholdDetector,
    ZKMLInterfaceSpec,
    build_provenance_root,
    compute_framehash,
    compute_video_fingerprint,
    extract_tiny_video_features,
    load_attestation_sidecar,
    save_attestation_sidecar,
    verify_provenance_root,
)
from src.trust.canonical import canonical_json_hash
from benchmark._common import SEQUENCES, decode_luma_frames


ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "benchmark" / "results"
OUTPUT_PATH = RESULTS_DIR / "trust_architecture_diagnostic.json"
CIRCUIT_OUT_DIR = ROOT / ".cache" / "future_circuits"
ATTESTATION_TMP_PATH = ROOT / "data" / "output" / "_trust_architecture_attestation.json"
_SHELL = sys.platform == "win32"


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _parse_circom_stats(output: str) -> dict[str, int]:
    clean = _strip_ansi(output)
    labels = {
        "template_instances": r"^template instances:\s*(\d+)$",
        "non_linear_constraints": r"^non-linear constraints:\s*(\d+)$",
        "linear_constraints": r"^linear constraints:\s*(\d+)$",
        "public_inputs": r"^public inputs:\s*(\d+)$",
        "private_inputs": r"^private inputs:\s*(\d+)$",
        "public_outputs": r"^public outputs:\s*(\d+)$",
        "wires": r"^wires:\s*(\d+)$",
        "labels": r"^labels:\s*(\d+)$",
    }
    stats: dict[str, int] = {}
    for key, pattern in labels.items():
        match = re.search(pattern, clean, flags=re.MULTILINE)
        if match:
            stats[key] = int(match.group(1))
    return stats


def _run_command(cmd: list[str], *, timeout: int = 120) -> tuple[bool, str, float]:
    start = time.perf_counter()
    completed = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=_SHELL,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    output = f"{completed.stdout}\n{completed.stderr}"
    return completed.returncode == 0, output, elapsed_ms


def _compile_circuit(circuit_name: str, *, wasm: bool = False) -> dict[str, object]:
    circuit_path = ROOT / "circuits" / f"{circuit_name}.circom"
    if not circuit_path.exists():
        return {
            "exists": False,
            "compile_ok": False,
            "error": f"missing {circuit_path}",
            "stats": {},
        }
    if shutil.which("circom") is None:
        return {
            "exists": True,
            "compile_ok": False,
            "error": "circom not found on PATH",
            "stats": {},
        }
    CIRCUIT_OUT_DIR.mkdir(parents=True, exist_ok=True)
    cmd = ["circom", str(circuit_path), "--r1cs", "--sym", "-o", str(CIRCUIT_OUT_DIR)]
    if wasm:
        cmd.insert(3, "--wasm")
    completed = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    return {
        "exists": True,
        "compile_ok": completed.returncode == 0,
        "error": None if completed.returncode == 0 else _strip_ansi(output)[-500:],
        "stats": _parse_circom_stats(output),
    }


def _witness_input_for(circuit_name: str) -> dict[str, Any]:
    if circuit_name == "detector_receipt":
        return {
            "features": [100, 100, 50, 50],
            "weights": [25, 25, 25, 25],
            "threshold": 7000,
        }
    if circuit_name == "fingerprint_verify":
        bits = [0] * 32 + [1] * 32
        chunks = []
        for c in range(8):
            value = 0
            for j in range(8):
                value += bits[c * 8 + j] * (1 << j)
            chunks.append(value)
        return {
            "query_bits": bits,
            "record_bits": bits,
            "record_chunks": chunks,
            "threshold": 0,
        }
    raise ValueError(f"unknown circuit {circuit_name}")


def _measure_groth16_circuit(circuit_name: str) -> dict[str, object]:
    compiled = _compile_circuit(circuit_name, wasm=True)
    if compiled.get("compile_ok") is not True:
        return {
            "attempted": True,
            "verified": False,
            "error": compiled.get("error") or "compile failed",
        }
    ptau_path = ROOT / "circuits" / "build" / "pot17_final.ptau"
    if not ptau_path.exists():
        return {
            "attempted": True,
            "verified": False,
            "error": f"missing {ptau_path}",
        }

    r1cs_path = CIRCUIT_OUT_DIR / f"{circuit_name}.r1cs"
    js_dir = CIRCUIT_OUT_DIR / f"{circuit_name}_js"
    wasm_path = js_dir / f"{circuit_name}.wasm"
    gen_js = js_dir / "generate_witness.js"
    zkey_path = CIRCUIT_OUT_DIR / f"{circuit_name}_0000.zkey"
    vkey_path = CIRCUIT_OUT_DIR / f"{circuit_name}_vkey.json"
    input_path = CIRCUIT_OUT_DIR / f"{circuit_name}_input.json"
    witness_path = CIRCUIT_OUT_DIR / f"{circuit_name}.wtns"
    proof_path = CIRCUIT_OUT_DIR / f"{circuit_name}_proof.json"
    public_path = CIRCUIT_OUT_DIR / f"{circuit_name}_public.json"

    setup_time_ms = 0.0
    setup_ran = False
    if not zkey_path.exists():
        setup_ran = True
        ok, output, setup_time_ms = _run_command(
            [
                "npx",
                "--prefix",
                "circuits",
                "snarkjs",
                "groth16",
                "setup",
                str(r1cs_path),
                str(ptau_path),
                str(zkey_path),
            ],
            timeout=180,
        )
        if not ok:
            return {
                "attempted": True,
                "verified": False,
                "error": _strip_ansi(output)[-500:],
                "setup_time_ms": round(setup_time_ms, 2),
            }

    if not vkey_path.exists():
        ok, output, _elapsed = _run_command(
            [
                "npx",
                "--prefix",
                "circuits",
                "snarkjs",
                "zkey",
                "export",
                "verificationkey",
                str(zkey_path),
                str(vkey_path),
            ],
            timeout=60,
        )
        if not ok:
            return {
                "attempted": True,
                "verified": False,
                "error": _strip_ansi(output)[-500:],
                "setup_time_ms": round(setup_time_ms, 2),
            }

    input_path.write_text(json.dumps(_witness_input_for(circuit_name)), encoding="utf-8")
    try:
        ok, output, witness_time_ms = _run_command(
            ["node", str(gen_js), str(wasm_path), str(input_path), str(witness_path)],
            timeout=60,
        )
        if not ok:
            return {
                "attempted": True,
                "verified": False,
                "error": _strip_ansi(output)[-500:],
            }

        ok, output, prove_time_ms = _run_command(
            [
                "npx",
                "--prefix",
                "circuits",
                "snarkjs",
                "groth16",
                "prove",
                str(zkey_path),
                str(witness_path),
                str(proof_path),
                str(public_path),
            ],
            timeout=120,
        )
        if not ok:
            return {
                "attempted": True,
                "verified": False,
                "error": _strip_ansi(output)[-500:],
            }

        ok, output, verify_time_ms = _run_command(
            [
                "npx",
                "--prefix",
                "circuits",
                "snarkjs",
                "groth16",
                "verify",
                str(vkey_path),
                str(public_path),
                str(proof_path),
            ],
            timeout=60,
        )
        public_signals = json.loads(public_path.read_text(encoding="utf-8"))
        return {
            "attempted": True,
            "verified": ok and "OK" in _strip_ansi(output),
            "setup_ran": setup_ran,
            "setup_time_ms": round(setup_time_ms, 2),
            "witness_time_ms": round(witness_time_ms, 2),
            "prove_time_ms": round(prove_time_ms, 2),
            "verify_time_ms": round(verify_time_ms, 2),
            "proof_json_size_bytes": proof_path.stat().st_size,
            "public_signal_count": len(public_signals),
            "public_signals": public_signals,
        }
    finally:
        for path in (input_path, witness_path, proof_path, public_path):
            path.unlink(missing_ok=True)


def _synthetic_fingerprint_rates(registry: FingerprintRegistry, base_fingerprint: str) -> dict[str, object]:
    near_match = hex(int(base_fingerprint, 16) ^ 0b111)[2:].zfill(len(base_fingerprint))
    far_match = hex(int(base_fingerprint, 16) ^ ((1 << 32) - 1))[2:].zfill(len(base_fingerprint))
    rows = []
    for threshold in (0, 2, 4, 8):
        positives = [
            registry.lookup(base_fingerprint, threshold=threshold).matched,
            registry.lookup(near_match, threshold=threshold).matched,
        ]
        negatives = [registry.lookup(far_match, threshold=threshold).matched]
        rows.append(
            {
                "threshold": threshold,
                "true_accept_rate": sum(positives) / len(positives),
                "false_accept_rate": sum(negatives) / len(negatives),
            }
        )
    return {
        "synthetic_rows": rows,
        "base_fingerprint": base_fingerprint,
        "near_distance": registry.lookup(near_match, threshold=64).distance,
        "far_distance": registry.lookup(far_match, threshold=64).distance,
    }


def _synthetic_clip_suite(frame_count: int = 8, size: int = 64) -> dict[str, np.ndarray]:
    x = np.linspace(0, 255, size, dtype=np.float32)
    y = np.linspace(0, 255, size, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)
    rng = np.random.default_rng(20260609)

    gradient_motion = np.stack([np.tile(np.roll(x, i * 2), (size, 1)) for i in range(frame_count)])
    vertical_motion = np.stack([np.tile(np.roll(y, i * 2), (size, 1)).T for i in range(frame_count)])
    checker = (((np.indices((size, size)).sum(axis=0) // 8) % 2) * 255).astype(np.float32)
    checker_motion = np.stack([np.roll(checker, i, axis=1) for i in range(frame_count)])
    bar_motion = np.zeros((frame_count, size, size), dtype=np.float32)
    for i in range(frame_count):
        start = (i * 5) % (size - 10)
        bar_motion[i, :, start : start + 10] = 230
        bar_motion[i] += 20
    radial = np.sqrt((xx - 127.5) ** 2 + (yy - 127.5) ** 2)
    radial = np.clip(255 - radial * 2.0, 0, 255).astype(np.float32)
    radial_motion = np.stack([np.roll(radial, i, axis=0) for i in range(frame_count)])
    noise = rng.integers(0, 256, size=(frame_count, size, size), dtype=np.uint8).astype(np.float32)

    return {
        "gradient_motion": gradient_motion.astype(np.float32),
        "vertical_motion": vertical_motion.astype(np.float32),
        "checker_motion": checker_motion.astype(np.float32),
        "bar_motion": bar_motion.astype(np.float32),
        "radial_motion": radial_motion.astype(np.float32),
        "seeded_noise": noise,
    }


def _box_blur(frames: np.ndarray) -> np.ndarray:
    padded = np.pad(frames, ((0, 0), (1, 1), (1, 1)), mode="edge")
    acc = np.zeros_like(frames, dtype=np.float32)
    for dy in range(3):
        for dx in range(3):
            acc += padded[:, dy : dy + frames.shape[1], dx : dx + frames.shape[2]]
    return acc / 9.0


def _fingerprint_positive_variants(base: np.ndarray) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(4242)
    return {
        "original": base,
        "brightness_shift": np.clip(base + 10.0, 0, 255),
        "contrast_scale": np.clip((base - 128.0) * 1.08 + 128.0, 0, 255),
        "mild_noise": np.clip(base + rng.normal(0.0, 3.0, size=base.shape), 0, 255).astype(np.float32),
        "down_up_nearest": _down_up_nearest(base),
        "box_blur": _box_blur(base),
        "frame_drop": base[::2],
    }


def _committed_synthetic_fingerprint_benchmark() -> dict[str, object]:
    policy = FingerprintPreprocessPolicy(sample_count=4, hash_size=8)
    clips = _synthetic_clip_suite()
    base_name = "gradient_motion"
    base_fp = compute_video_fingerprint(clips[base_name], policy=policy)
    registry = FingerprintRegistry(
        [
            FingerprintRecord(
                record_id=base_name,
                fingerprint_hex=base_fp.fingerprint_hex,
                metadata_hash=canonical_json_hash({"source": "committed-synthetic-suite"}),
            )
        ]
    )

    positives = {
        name: compute_video_fingerprint(frames, policy=policy)
        for name, frames in _fingerprint_positive_variants(clips[base_name]).items()
    }
    negatives = {
        name: compute_video_fingerprint(frames, policy=policy)
        for name, frames in clips.items()
        if name != base_name
    }

    rows = []
    for threshold in (0, 2, 4, 8, 12, 16, 24):
        positive_matches = [registry.lookup(fp.fingerprint_hex, threshold=threshold).matched for fp in positives.values()]
        negative_matches = [registry.lookup(fp.fingerprint_hex, threshold=threshold).matched for fp in negatives.values()]
        rows.append(
            {
                "threshold": threshold,
                "positive_count": len(positive_matches),
                "negative_count": len(negative_matches),
                "true_accept_rate": sum(positive_matches) / len(positive_matches),
                "false_reject_rate": 1.0 - (sum(positive_matches) / len(positive_matches)),
                "false_accept_rate": sum(negative_matches) / len(negative_matches),
            }
        )

    return {
        "available": True,
        "policy": policy.to_dict(),
        "registry_record": base_name,
        "positive_distances": {
            name: registry.lookup(fp.fingerprint_hex, threshold=64).distance for name, fp in positives.items()
        },
        "negative_distances": {
            name: registry.lookup(fp.fingerprint_hex, threshold=64).distance for name, fp in negatives.items()
        },
        "rows": rows,
    }


def _real_clip_fingerprint_benchmark() -> dict[str, object]:
    policy = FingerprintPreprocessPolicy(sample_count=4, hash_size=8)
    sequence_names = sorted(name for name in SEQUENCES if name.endswith("_q22_g1"))
    fingerprints: dict[str, Any] = {}
    for name in sequence_names:
        path = SEQUENCES.get(name)
        if path is None or not path.exists():
            continue
        frames = decode_luma_frames(path, max_frames=16)
        fingerprints[name] = compute_video_fingerprint(frames, policy=policy)
    if len(fingerprints) < 2:
        return {
            "available": False,
            "reason": "not enough local H.264 assets for diagnostic benchmark",
            "policy": policy.to_dict(),
            "rows": [],
        }

    first_name = next(iter(fingerprints))
    registry = FingerprintRegistry(
        [
            FingerprintRecord(
                record_id=first_name,
                fingerprint_hex=fingerprints[first_name].fingerprint_hex,
                metadata_hash=canonical_json_hash({"source": "local-diagnostic"}),
            )
        ]
    )
    rows = []
    for threshold in (0, 4, 8, 16):
        positives = [
            registry.lookup(fingerprints[first_name].fingerprint_hex, threshold=threshold).matched,
        ]
        negatives = [
            registry.lookup(fp.fingerprint_hex, threshold=threshold).matched
            for name, fp in fingerprints.items()
            if name != first_name
        ]
        rows.append(
            {
                "threshold": threshold,
                "true_accept_rate": sum(positives) / len(positives),
                "false_accept_rate": sum(negatives) / len(negatives),
                "negative_count": len(negatives),
            }
        )
    return {
        "available": True,
        "policy": policy.to_dict(),
        "registry_record": first_name,
        "clip_count": len(fingerprints),
        "fingerprints": {name: fp.to_dict() for name, fp in fingerprints.items()},
        "rows": rows,
    }


def _down_up_nearest(frames: np.ndarray) -> np.ndarray:
    down = frames[:, ::2, ::2]
    return np.repeat(np.repeat(down, 2, axis=1), 2, axis=2)[:, : frames.shape[1], : frames.shape[2]]


def _detector_transform_benchmark() -> dict[str, object]:
    base = np.stack(
        [
            np.tile(np.linspace(32 + i * 8, 220 + i * 8, 64, dtype=np.float32), (64, 1))
            for i in range(4)
        ]
    )
    transformed = {
        "original": base,
        "brightness_shift": np.clip(base + 12.0, 0, 255),
        "contrast_scale": np.clip((base - 128.0) * 1.12 + 128.0, 0, 255),
        "mild_noise": np.clip(base + np.random.default_rng(7).normal(0, 4, base.shape), 0, 255).astype(np.float32),
        "down_up_nearest": _down_up_nearest(base),
        "box_blur": _box_blur(base),
        "center_crop_padded": np.pad(base[:, 8:56, 8:56], ((0, 0), (8, 8), (8, 8)), mode="edge"),
        "horizontal_flip": base[:, :, ::-1],
        "temporal_reverse": base[::-1],
        "frame_drop": base[::2],
    }
    negative_controls = {
        "dark_flat": np.zeros_like(base) + 8,
        "low_motion_gray": np.zeros_like(base) + 64,
        "dark_noise": np.random.default_rng(99).normal(16, 2, base.shape).clip(0, 255).astype(np.float32),
    }
    detector = CalibratedThresholdDetector([0.35, 0.35, 0.2, 0.1])
    positive_features = [extract_tiny_video_features(frames) for frames in transformed.values()]
    negative_features = [extract_tiny_video_features(frames) for frames in negative_controls.values()]
    calibration = detector.calibrate(positive_features, negative_features)
    threshold = calibration.threshold
    rows = []
    for name, frames in transformed.items():
        features = extract_tiny_video_features(frames)
        receipt = detector.receipt(features, threshold=threshold)
        rows.append(
            {
                "transform": name,
                "features": features,
                "score": receipt.score,
                "threshold": threshold,
                "expected": True,
                "accepted": receipt.valid,
                "correct": receipt.valid is True,
            }
        )
    for name, frames in negative_controls.items():
        features = extract_tiny_video_features(frames)
        receipt = detector.receipt(features, threshold=threshold)
        rows.append(
            {
                "transform": name,
                "features": features,
                "score": receipt.score,
                "threshold": threshold,
                "expected": False,
                "accepted": receipt.valid,
                "correct": receipt.valid is False,
            }
        )
    positives = [row["accepted"] for row in rows if row["expected"] is True]
    negatives = [row["accepted"] for row in rows if row["expected"] is False]
    return {
        "detector_commitment": detector.commitment,
        "calibration": calibration.to_dict(),
        "threshold": threshold,
        "rows": rows,
        "summary": {
            "positive_count": len(positives),
            "negative_count": len(negatives),
            "positive_accept_rate": sum(positives) / len(positives),
            "false_accept_rate": sum(negatives) / len(negatives),
            "accuracy": sum(row["correct"] for row in rows) / len(rows),
        },
        "proof_overhead_reference": "detector_receipt.circom Groth16 measurement",
    }


def _synthetic_manifest() -> dict[str, object]:
    return {
        "claim_generator": "zk-stego-future-branch",
        "assertions": [
            {"label": "video_hash", "value": "00" * 32},
            {"label": "policy", "value": "fragile-provenance-anchor-v1"},
        ],
    }


def run_diagnostic() -> dict[str, object]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    manifest = _synthetic_manifest()
    root = build_provenance_root(manifest, manifest_uri="registry://example/manifest/1")
    tampered_manifest = dict(manifest)
    tampered_manifest["claim_generator"] = "tampered"
    c2pa_sidecar = build_c2pa_anchor(manifest, registry_uri="registry://example/manifest/1")
    stego_manifest = attach_anchor_to_manifest(
        StegoManifest(video=VideoMetadata(file_path="synthetic.h264", file_hash="00" * 32)),
        c2pa_sidecar,
    )
    stego_manifest_roundtrip = StegoManifest.from_json(stego_manifest.to_json())

    frame = np.arange(64 * 64, dtype=np.float32).reshape(64, 64)
    fp = compute_framehash(frame)
    frames = np.stack([frame + float(i) for i in range(6)])
    fingerprint_policy = FingerprintPreprocessPolicy(sample_count=3, hash_size=8)
    video_fp = compute_video_fingerprint(frames, policy=fingerprint_policy)
    registry = FingerprintRegistry(
        [
            FingerprintRecord(
                record_id="synthetic-frame-1",
                fingerprint_hex=fp,
                metadata_hash=canonical_json_hash({"owner": "private"}),
            )
        ]
    )
    match = registry.lookup(fp, threshold=0)

    detector = TinyThresholdDetector([0.25, 0.25, 0.25, 0.25])
    receipt = detector.receipt([1.0, 1.0, 0.5, 0.5], threshold=0.7, payload_commitment=root.manifest_root_hash)

    bundle = AttestationBundle(
        video_hash="11" * 32,
        model_config_hash="22" * 32,
        model_binary_hash="33" * 32,
        policy_id="mock-policy-v1",
        timestamp="2026-06-08T00:00:00Z",
        hardware_root="mock-root",
    )
    signer = MockTEESigner(b"mock-tee-key")
    signed = signer.sign(bundle)
    attestation_sidecar = AttestationSidecar(
        signed_attestation=signed,
        provenance_root_hash=root.manifest_root_hash,
    )
    ATTESTATION_TMP_PATH.parent.mkdir(parents=True, exist_ok=True)
    save_attestation_sidecar(attestation_sidecar, ATTESTATION_TMP_PATH)
    loaded_attestation = load_attestation_sidecar(ATTESTATION_TMP_PATH)
    ATTESTATION_TMP_PATH.unlink(missing_ok=True)

    zkml = ZKMLInterfaceSpec(
        circuit_name="future_video_model_attestation",
        public_outputs=("accepted", "model_commitment"),
        private_inputs=("model_weights", "activation_trace"),
    )

    result = {
        "tier": "diagnostic_grade",
        "provenance": {
            "root": root.to_dict(),
            "valid": verify_provenance_root(root, manifest),
            "tamper_detected": not verify_provenance_root(root, tampered_manifest),
        },
        "c2pa_bridge": {
            "sidecar": c2pa_sidecar.to_dict(),
            "payload_bytes": len(c2pa_sidecar.anchor.payload_bytes),
            "manifest_fields": {
                "provenance_uri": stego_manifest_roundtrip.video.provenance_uri,
                "provenance_root_hash": stego_manifest_roundtrip.video.provenance_root_hash,
                "roundtrip_valid": (
                    stego_manifest_roundtrip.video.provenance_uri == c2pa_sidecar.registry_uri
                    and stego_manifest_roundtrip.video.provenance_root_hash
                    == c2pa_sidecar.anchor.root.manifest_root_hash
                ),
            },
            "embedded_payload_valid": verify_c2pa_anchor(
                c2pa_sidecar,
                manifest,
                embedded_payload=c2pa_sidecar.anchor.payload_bytes,
            ),
            "embedded_payload_tamper_detected": not verify_c2pa_anchor(
                c2pa_sidecar,
                manifest,
                embedded_payload=b"\x00" * 32,
            ),
            "manifest_tamper_detected": not verify_c2pa_anchor(c2pa_sidecar, tampered_manifest),
        },
        "fingerprint_registry": {
            "fingerprint_hex": fp,
            "video_fingerprint": video_fp.to_dict(),
            "registry_commitment": registry.commitment(),
            "matched": match.matched,
            "record_id": match.record_id,
            "distance": match.distance,
            "threshold": match.threshold,
            "threshold_behavior": _synthetic_fingerprint_rates(registry, fp),
            "committed_synthetic_benchmark": _committed_synthetic_fingerprint_benchmark(),
            "real_clip_benchmark": _real_clip_fingerprint_benchmark(),
        },
        "watermark_receipt": {
            "receipt": receipt.to_dict(),
            "receipt_commitment": receipt.commitment(),
            "transform_benchmark": _detector_transform_benchmark(),
        },
        "attestation": {
            "statement_hash": bundle.statement_hash(),
            "signature_valid": signer.verify(signed),
            "signed": signed.to_dict(),
            "sidecar_roundtrip_valid": signer.verify(loaded_attestation.signed_attestation)
            and loaded_attestation.provenance_root_hash == root.manifest_root_hash,
        },
        "zkml_interface": {
            "spec": zkml.to_dict(),
            "interface_valid": zkml.validate_interface_only(),
        },
        "circuits": {},
    }
    for circuit_name in ("fingerprint_verify", "detector_receipt"):
        result["circuits"][circuit_name] = _compile_circuit(circuit_name)
        result["circuits"][circuit_name]["groth16_measurement"] = _measure_groth16_circuit(circuit_name)
    OUTPUT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=True), encoding="utf-8")
    return result


def main() -> None:
    result = run_diagnostic()
    checks = [
        result["provenance"]["valid"],
        result["provenance"]["tamper_detected"],
        result["c2pa_bridge"]["embedded_payload_valid"],
        result["c2pa_bridge"]["manifest_fields"]["roundtrip_valid"],
        result["c2pa_bridge"]["embedded_payload_tamper_detected"],
        result["c2pa_bridge"]["manifest_tamper_detected"],
        result["fingerprint_registry"]["matched"],
        result["fingerprint_registry"]["video_fingerprint"]["fingerprint_hex"],
        result["watermark_receipt"]["receipt"]["valid"],
        result["attestation"]["signature_valid"],
        result["attestation"]["sidecar_roundtrip_valid"],
        result["zkml_interface"]["interface_valid"],
        result["circuits"]["fingerprint_verify"]["compile_ok"],
        result["circuits"]["detector_receipt"]["compile_ok"],
        result["circuits"]["fingerprint_verify"]["groth16_measurement"]["verified"],
        result["circuits"]["detector_receipt"]["groth16_measurement"]["verified"],
    ]
    print("=== Trust Architecture Diagnostic ===")
    print(f"  output: {OUTPUT_PATH}")
    print(f"  checks: {sum(bool(v) for v in checks)}/{len(checks)}")
    if not all(checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
