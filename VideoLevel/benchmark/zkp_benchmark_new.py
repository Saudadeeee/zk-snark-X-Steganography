"""Compare actual Groth16 and PLONK proofs for the camera_video R1CS (registry membership + binding)."""

from __future__ import annotations

import json
import math
import re
import secrets
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

from src.camera_registry import CameraRegistry, camera_public_key, new_camera_secret
from src.video_binding import MODE_VIDEO, binding_digest
from src.zk_proof import CameraProofBridge, proof_to_bytes


ROOT = Path(__file__).resolve().parents[1]
CIRCUITS = ROOT / "circuits"
BUILD = CIRCUITS / "build"
NODE = shutil.which("node") or "node"
SNARKJS = CIRCUITS / "node_modules" / "snarkjs" / "build" / "cli.cjs"
R1CS = BUILD / "camera_video.r1cs"
GROTH16_ZKEY = BUILD / "camera_video.zkey"
GROTH16_VKEY = BUILD / "camera_video_vkey.json"
PUBLIC_PTAU = BUILD / "powersOfTau28_hez_final_16.ptau"
PUBLIC_PTAU_POWER = 16


def _measured(args: list[str], *, cwd: Path, timeout: int = 7200) -> dict[str, Any]:
    start = time.perf_counter_ns()
    process = psutil.Popen(args, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc_info = psutil.Process(process.pid)
    peak_rss = peak_cpu = 0.0
    deadline = time.monotonic() + timeout
    while process.poll() is None:
        try:
            peak_rss = max(peak_rss, float(proc_info.memory_info().rss))
            usage = proc_info.cpu_times()
            peak_cpu = max(peak_cpu, usage.user + usage.system)
        except psutil.Error:
            pass
        if time.monotonic() > deadline:
            process.kill()
            raise TimeoutError(f"command timed out: {' '.join(args[:3])}")
        time.sleep(0.01)
    stdout = process.stdout.read() if process.stdout else b""
    stderr = process.stderr.read() if process.stderr else b""
    return {"returncode": int(process.returncode), "stdout": stdout, "stderr": stderr,
            "wall_ms": (time.perf_counter_ns() - start) / 1e6,
            "peak_rss_bytes_sampled": int(peak_rss), "cpu_seconds_sampled": peak_cpu}


def _run_cli(*args: str, timeout: int = 7200) -> dict[str, Any]:
    record = _measured([NODE, str(SNARKJS), *args], cwd=CIRCUITS, timeout=timeout)
    if record["returncode"]:
        raise RuntimeError((record["stdout"] + record["stderr"]).decode(errors="replace")[-3000:])
    return record


def _require_artifacts() -> None:
    required = (SNARKJS, R1CS, BUILD / "camera_video_js" / "camera_video.wasm",
                BUILD / "camera_video_js" / "generate_witness.js", GROTH16_ZKEY, GROTH16_VKEY)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("missing actual proving artifacts: " + ", ".join(missing))


def _build_local_ptau(out_dir: Path, power: int) -> tuple[Path, list[dict[str, Any]]]:
    """Create a reproducible PLONK Powers-of-Tau transcript large enough for this R1CS."""
    paths = [out_dir / f"pot{power}_0000.ptau", out_dir / f"pot{power}_0001.ptau",
             out_dir / f"pot{power}_final.ptau"]
    created = []
    created.append(_run_cli("powersoftau", "new", "bn128", str(power), str(paths[0]), timeout=7200))
    # Entropy is ephemeral: it is passed only to the ceremony process and is
    # deliberately never serialized into benchmark output.
    contribution = _run_cli("powersoftau", "contribute", str(paths[0]), str(paths[1]),
                            "--name=local benchmark contribution", "-e=" + secrets.token_hex(32),
                            timeout=7200)
    created.append(contribution)
    created.append(_run_cli("powersoftau", "prepare", "phase2", str(paths[1]),
                             str(paths[2]), timeout=7200))
    return paths[2], created


def _verify_with_cli(vkey: Path, public: Path, proof: Path, mode: str) -> dict[str, Any]:
    return _run_cli(mode, "verify", str(vkey), str(public), str(proof))


def _verify_expected_invalid(vkey: Path, public: Path, proof: Path, mode: str) -> dict[str, Any]:
    """A negative verification is expected to exit non-zero or print Invalid Proof."""
    return _measured([NODE, str(SNARKJS), mode, "verify", str(vkey), str(public), str(proof)], cwd=CIRCUITS)


def run_zkp_benchmark(output_root: Path, trials: int = 1, plonk_trials: int | None = None) -> dict[str, Any]:
    _require_artifacts()
    output_root = output_root.resolve()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]
    out_dir = (output_root / "zkp_new" / run_id).resolve()
    out_dir.mkdir(parents=True, exist_ok=False)
    bridge = CameraProofBridge(CIRCUITS)
    camera_secrets = [new_camera_secret() for _ in range(8)]
    registry = CameraRegistry([camera_public_key(secret) for secret in camera_secrets])
    message = b"zkp-benchmark-common-statement"
    binding = binding_digest(MODE_VIDEO, bytes(range(32)), message)
    circuit_input = bridge.circuit_input(camera_secrets[5], registry, binding)
    results: list[dict[str, Any]] = []

    for trial in range(trials):
        witness_start = time.perf_counter_ns()
        witness = bridge._compute_witness(circuit_input)
        witness_ms = (time.perf_counter_ns() - witness_start) / 1e6
        work = witness.parent
        proof_path, public_path = work / "groth16_proof.json", work / "groth16_public.json"
        tampered_path = work / "groth16_public_tampered.json"
        try:
            prove = _run_cli("groth16", "prove", str(GROTH16_ZKEY),
                             str(witness), str(proof_path), str(public_path), timeout=7200)
            verify = _verify_with_cli(GROTH16_VKEY, public_path, proof_path, "groth16")
            verification_output = (verify["stdout"] + verify["stderr"]).decode(errors="replace").lower()
            # snarkjs exits 0 and prints "OK!" only for a valid proof.
            groth_ok = verify["returncode"] == 0 and "ok!" in verification_output
            groth_public = json.loads(public_path.read_text(encoding="utf-8"))
            groth_proof = json.loads(proof_path.read_text(encoding="utf-8"))
            tampered_public = list(groth_public)
            tampered_public[-1] = str(int(tampered_public[-1]) + 1)
            tampered_path.write_text(json.dumps(tampered_public), encoding="utf-8")
            negative = _verify_expected_invalid(GROTH16_VKEY, tampered_path, proof_path, "groth16")
            negative_output = (negative["stdout"] + negative["stderr"]).decode(errors="replace").lower()
            # A crash must not count as a rejection: require snarkjs' own invalid-proof verdict.
            groth_tamper = negative["returncode"] != 0 and "invalid proof" in negative_output
            results.append({
                "algorithm": "Groth16 BN254 / snarkjs", "trial": trial + 1,
                "witness_ms": witness_ms,
                "prove_ms": prove["wall_ms"], "verify_ms": verify["wall_ms"],
                "prove_peak_rss_bytes_sampled": prove["peak_rss_bytes_sampled"],
                "verify_peak_rss_bytes_sampled": verify["peak_rss_bytes_sampled"],
                "prove_cpu_seconds_sampled": prove["cpu_seconds_sampled"],
                "verify_cpu_seconds_sampled": verify["cpu_seconds_sampled"],
                "serialized_proof_json_bytes": proof_path.stat().st_size,
                "compact_proof_bytes": len(proof_to_bytes(groth_proof)),
                "public_signals_json_bytes": public_path.stat().st_size,
                "proof_valid": groth_ok, "tampered_public_input_rejected": groth_tamper,
                "trusted_setup": "Hermez public Phase 1 + local multi-contribution Phase 2 + beacon (src/zk_setup.py; demo)",
                "artifact": "circuits/build/camera_video.zkey",
            })
        finally:
            witness.unlink(missing_ok=True)
            proof_path.unlink(missing_ok=True)
            public_path.unlink(missing_ok=True)
            tampered_path.unlink(missing_ok=True)
            (work / "input.json").unlink(missing_ok=True)
            try:
                work.rmdir()
            except OSError:
                pass

    # Read the actual constraint count from the R1CS; PLONK's domain is larger than the
    # R1CS (selectors, permutation), so allow a 4x margin when choosing the universal SRS.
    r1cs_info = _run_cli("r1cs", "info", str(R1CS))
    info_text = (r1cs_info["stdout"] + r1cs_info["stderr"]).decode(errors="replace")
    count_match = re.search(r"(?:# of Constraints|Constraints)\s*[:=]\s*(\d+)", info_text, re.IGNORECASE)
    if not count_match:
        raise RuntimeError("could not read circuit constraint count from snarkjs r1cs info: " + info_text[-1500:])
    actual_constraints = int(count_match.group(1))
    power = max(12, math.ceil(math.log2(4 * actual_constraints)))
    if power <= PUBLIC_PTAU_POWER and PUBLIC_PTAU.is_file():
        # PLONK's universal SRS: the public Hermez transcript, no circuit-specific ceremony.
        ptau, ceremony, ptau_source = PUBLIC_PTAU, [], "public Hermez Powers of Tau 2^16"
    else:
        ptau, ceremony = _build_local_ptau(out_dir, power)
        ptau_source = f"local Powers of Tau 2^{power}"
    plonk_zkey = out_dir / "camera_video_plonk.zkey"
    plonk_vkey = out_dir / "camera_video_plonk_vkey.json"
    setup = _run_cli("plonk", "setup", str(R1CS), str(ptau), str(plonk_zkey), timeout=7200)
    vkey = _run_cli("zkey", "export", "verificationkey", str(plonk_zkey), str(plonk_vkey))
    plonk_trial_count = trials if plonk_trials is None else plonk_trials
    plonk_records: list[dict[str, Any]] = []
    for trial in range(plonk_trial_count):
        witness_start = time.perf_counter_ns()
        witness = bridge._compute_witness(circuit_input)
        witness_ms = (time.perf_counter_ns() - witness_start) / 1e6
        work = witness.parent
        proof_path, public_path = work / "plonk_proof.json", work / "plonk_public.json"
        try:
            prove = _run_cli("plonk", "prove", str(plonk_zkey), str(witness),
                             str(proof_path), str(public_path), timeout=7200)
            verify = _verify_with_cli(plonk_vkey, public_path, proof_path, "plonk")
            public_data = json.loads(public_path.read_text(encoding="utf-8"))
            verification_output = (verify["stdout"] + verify["stderr"]).decode(errors="replace").lower()
            valid = verify["returncode"] == 0 and "ok!" in verification_output
            tampered_public = list(public_data)
            tampered_public[-1] = str(int(tampered_public[-1]) + 1)
            tampered_path = work / "plonk_public_tampered.json"
            tampered_path.write_text(json.dumps(tampered_public), encoding="utf-8")
            negative = _verify_expected_invalid(plonk_vkey, tampered_path, proof_path, "plonk")
            negative_output = (negative["stdout"] + negative["stderr"]).decode(errors="replace").lower()
            rejected = negative["returncode"] != 0 and "invalid proof" in negative_output
            record = {
                "algorithm": "PLONK KZG / snarkjs", "trial": trial + 1,
                "witness_ms": witness_ms,
                "prove_ms": prove["wall_ms"], "verify_ms": verify["wall_ms"],
                "prove_peak_rss_bytes_sampled": prove["peak_rss_bytes_sampled"],
                "verify_peak_rss_bytes_sampled": verify["peak_rss_bytes_sampled"],
                "prove_cpu_seconds_sampled": prove["cpu_seconds_sampled"],
                "verify_cpu_seconds_sampled": verify["cpu_seconds_sampled"],
                "serialized_proof_json_bytes": proof_path.stat().st_size,
                "compact_proof_bytes": None,
                "public_signals_json_bytes": public_path.stat().st_size,
                "proof_valid": valid, "tampered_public_input_rejected": rejected,
                "trusted_setup": "universal Powers-of-Tau transcript plus circuit-specific PLONK setup",
                "public_signal_count": len(public_data),
                "plonk_proving_key_bytes": plonk_zkey.stat().st_size,
            }
            plonk_records.append(record)
        finally:
            witness.unlink(missing_ok=True)
            proof_path.unlink(missing_ok=True)
            public_path.unlink(missing_ok=True)
            (work / "plonk_public_tampered.json").unlink(missing_ok=True)
            (work / "input.json").unlink(missing_ok=True)
            try:
                work.rmdir()
            except OSError:
                pass
    results.extend(plonk_records)
    if not all(row["proof_valid"] and row["tampered_public_input_rejected"] for row in results):
        raise RuntimeError("proof positive/negative verification gate failed")

    record = {
        "schema": "zkstego-zkp-benchmark-new-v1", "run_id": run_id,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "statement": ("Same camera_video R1CS and witness: a camera registered in a depth-16 Poseidon Merkle "
                      "tree (root public) vouches for a 256-bit binding of video digest and message (two public "
                      "128-bit inputs); the camera secret and its leaf stay private."),
        "circuit_constraints": actual_constraints, "public_inputs": 3, "registry_size": len(registry.public_keys),
        "trials_per_system": {"groth16": trials, "plonk": plonk_trial_count},
        "methodology": "Measured actual Node/snarkjs witness/prove/verify commands; PLONK uses a locally generated, adequately sized Powers-of-Tau transcript and setup time is reported separately. Wall times include Node process startup. Peak process RSS sampled every 10ms and may undercount short peaks. No literature-only estimates.",
        "groth16_proving_key_sha256": __import__("hashlib").sha256(GROTH16_ZKEY.read_bytes()).hexdigest(),
        "groth16_proving_key_bytes": GROTH16_ZKEY.stat().st_size,
        "powers_of_tau_power": PUBLIC_PTAU_POWER if ptau == PUBLIC_PTAU else power,
        "powers_of_tau_source": ptau_source,
        "powers_of_tau_commands": [{"wall_ms": item["wall_ms"], "peak_rss_bytes_sampled": item["peak_rss_bytes_sampled"]} for item in ceremony],
        "powers_of_tau_final_sha256": __import__("hashlib").sha256(ptau.read_bytes()).hexdigest(),
        "powers_of_tau_final_bytes": ptau.stat().st_size,
        "plonk_setup_ms": setup["wall_ms"], "plonk_setup_peak_rss_bytes_sampled": setup["peak_rss_bytes_sampled"],
        "plonk_setup_timing_basis": "perf_counter around snarkjs command",
        "plonk_proving_key_bytes": plonk_zkey.stat().st_size,
        "plonk_vkey_export_ms": vkey["wall_ms"],
        "results": results,
        "limitations": [
            "Only Groth16 and PLONK are implemented for this exact R1CS in this run; no STARK/Halo2/Bulletproof timings are invented.",
            "The proof shows registry membership and the binding; the binding covers the masked video digest and the message (src/video_binding.py).",
            "The Groth16 Phase 2 ran on one machine (demo ceremony); a deployment needs independent contributors.",
            "Groth16 compact 129-byte proof serialization is project-specific; raw JSON bytes are also reported for transport context.",
        ],
    }
    record["run_artifact_directory"] = str(out_dir)
    out_path = output_root / "zkp_new.json"
    out_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


if __name__ == "__main__":
    data = run_zkp_benchmark(ROOT / "benchmark" / "results")
    print(json.dumps({"results": data["results"], "setup_ms": data["plonk_setup_ms"]}, indent=2))
