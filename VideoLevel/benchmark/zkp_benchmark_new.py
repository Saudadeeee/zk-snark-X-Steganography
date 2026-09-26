"""Compare actual Groth16 and PLONK proofs for the same Circom R1CS statement."""

from __future__ import annotations

import json
import math
import os
import re
import secrets
import shutil
import statistics
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

from src.zk_proof import ZKSnarkBridge, proof_to_bytes


ROOT = Path(__file__).resolve().parents[1]
CIRCUITS = ROOT / "circuits"
BUILD = CIRCUITS / "build"
NODE = shutil.which("node") or "node"
SNARKJS = CIRCUITS / "node_modules" / "snarkjs" / "build" / "cli.cjs"


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
    required = (SNARKJS, BUILD / "payload_verify.r1cs", BUILD / "pot17_final.ptau",
                BUILD / "payload_verify_js" / "payload_verify.wasm",
                BUILD / "payload_verify_js" / "generate_witness.js",
                BUILD / "proving_key.zkey", BUILD / "verification_key.json")
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


def run_zkp_benchmark(output_root: Path, trials: int = 1,
                      existing_setup_dir: Path | None = None,
                      existing_setup_elapsed_ms: float | None = None) -> dict[str, Any]:
    _require_artifacts()
    output_root = output_root.resolve()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]
    if existing_setup_dir is None:
        out_dir = (output_root / "zkp_new" / run_id).resolve()
        out_dir.mkdir(parents=True, exist_ok=False)
    else:
        out_dir = existing_setup_dir.resolve()
        if not out_dir.is_dir():
            raise RuntimeError(f"precomputed PLONK setup directory not found: {out_dir}")
    bridge = ZKSnarkBridge(str(CIRCUITS))
    payload = b"zkp-benchmark-new-common-statement-v1"
    secret = bytes(range(32))
    results: list[dict[str, Any]] = []

    for trial in range(trials):
        witness_start = time.perf_counter_ns()
        witness = bridge._compute_witness(bridge._build_circuit_input(payload, secret))
        witness_ms = (time.perf_counter_ns() - witness_start) / 1e6
        work = witness.parent
        proof_path, public_path = work / "groth16_proof.json", work / "groth16_public.json"
        tampered_path = work / "groth16_public_tampered.json"
        try:
            prove = _run_cli("groth16", "prove", str(BUILD / "proving_key.zkey"),
                             str(witness), str(proof_path), str(public_path), timeout=7200)
            verify = _verify_with_cli(BUILD / "verification_key.json", public_path, proof_path, "groth16")
            verification_output = (verify["stdout"] + verify["stderr"]).decode(errors="replace").lower()
            groth_ok = "ok" in verification_output and "invalid" not in verification_output
            groth_public = json.loads(public_path.read_text(encoding="utf-8"))
            groth_proof = json.loads(proof_path.read_text(encoding="utf-8"))
            tampered_public = list(groth_public)
            tampered_public[-1] = str(int(tampered_public[-1]) + 1)
            tampered_path.write_text(json.dumps(tampered_public), encoding="utf-8")
            negative = _verify_expected_invalid(BUILD / "verification_key.json", tampered_path, proof_path, "groth16")
            negative_output = (negative["stdout"] + negative["stderr"]).decode(errors="replace").lower()
            groth_tamper = "invalid" in negative_output or negative["returncode"] != 0
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
                "trusted_setup": "existing circuit-specific setup; ceremony provenance must be verified independently",
                "artifact": "circuits/build/proving_key.zkey",
            })
        finally:
            witness.unlink(missing_ok=True)
            proof_path.unlink(missing_ok=True)
            public_path.unlink(missing_ok=True)
            tampered_path.unlink(missing_ok=True)
            (work / "input_live.json").unlink(missing_ok=True)
            try:
                work.rmdir()
            except OSError:
                pass

    # Read the actual constraint count from the R1CS instead of trusting the
    # stale bridge constant; choose a sufficiently large local universal SRS.
    r1cs_info = _run_cli("r1cs", "info", str(BUILD / "payload_verify.r1cs"))
    info_text = (r1cs_info["stdout"] + r1cs_info["stderr"]).decode(errors="replace")
    count_match = re.search(r"(?:# of Constraints|Constraints)\s*[:=]\s*(\d+)", info_text, re.IGNORECASE)
    if not count_match:
        count_match = re.search(r"Constraints:\s*(\d+)", info_text, re.IGNORECASE)
    if not count_match:
        raise RuntimeError("could not read circuit constraint count from snarkjs r1cs info: " + info_text[-1500:])
    actual_constraints = int(count_match.group(1))
    # snarkjs' PLONK arithmetization adds selector/permutation constraints; its
    # reported domain for this 62,553-row R1CS is 221,039, so allow a 4x margin.
    power = max(18, math.ceil(math.log2(4 * actual_constraints)))
    plonk_zkey = out_dir / "payload_verify_plonk.zkey"
    plonk_vkey = out_dir / "payload_verify_plonk_vkey.json"
    if existing_setup_dir is None:
        ptau, ceremony = _build_local_ptau(out_dir, power)
        setup = _run_cli("plonk", "setup", str(BUILD / "payload_verify.r1cs"),
                         str(ptau), str(plonk_zkey), timeout=7200)
        vkey = _run_cli("zkey", "export", "verificationkey", str(plonk_zkey), str(plonk_vkey))
    else:
        ptau = out_dir / f"pot{power}_final.ptau"
        ceremony = []
        setup = {"wall_ms": existing_setup_elapsed_ms, "peak_rss_bytes_sampled": None,
                 "reused_existing_artifact": True,
                 "timing_basis": "file creation to final write timestamps; whole-second approximate"}
        vkey = {"wall_ms": None}
        if not plonk_zkey.is_file() or not plonk_vkey.is_file() or not ptau.is_file():
            raise RuntimeError("precomputed PLONK zkey, verification key or Powers-of-Tau file is missing")
    plonk_trials: list[dict[str, Any]] = []
    for trial in range(trials):
        witness_start = time.perf_counter_ns()
        witness = bridge._compute_witness(bridge._build_circuit_input(payload, secret))
        witness_ms = (time.perf_counter_ns() - witness_start) / 1e6
        work = witness.parent
        proof_path, public_path = work / "plonk_proof.json", work / "plonk_public.json"
        try:
            prove = _run_cli("plonk", "prove", str(plonk_zkey), str(witness),
                             str(proof_path), str(public_path), timeout=7200)
            verify = _verify_with_cli(plonk_vkey, public_path, proof_path, "plonk")
            proof_data = json.loads(proof_path.read_text(encoding="utf-8"))
            public_data = json.loads(public_path.read_text(encoding="utf-8"))
            verification_output = (verify["stdout"] + verify["stderr"]).decode(errors="replace").lower()
            valid = "ok" in verification_output and "invalid" not in verification_output
            tampered_public = list(public_data)
            tampered_public[-1] = str(int(tampered_public[-1]) + 1)
            tampered_path = work / "plonk_public_tampered.json"
            tampered_path.write_text(json.dumps(tampered_public), encoding="utf-8")
            negative = _verify_expected_invalid(plonk_vkey, tampered_path, proof_path, "plonk")
            negative_output = (negative["stdout"] + negative["stderr"]).decode(errors="replace").lower()
            rejected = "invalid" in negative_output or negative["returncode"] != 0
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
            plonk_trials.append(record)
        finally:
            witness.unlink(missing_ok=True)
            proof_path.unlink(missing_ok=True)
            public_path.unlink(missing_ok=True)
            (work / "plonk_public_tampered.json").unlink(missing_ok=True)
            for path in (work / "input_live.json",):
                path.unlink(missing_ok=True)
            try:
                work.rmdir()
            except OSError:
                pass
    results.extend(plonk_trials)
    if not all(row["proof_valid"] and row["tampered_public_input_rejected"] for row in results):
        raise RuntimeError("proof positive/negative verification gate failed")

    record = {
        "schema": "zkstego-zkp-benchmark-new-v1", "run_id": run_id,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "statement": "Same existing Circom payload_verify R1CS, same payload and 32-byte secret; proves SHA256(SHA256(payload)||secret) commitment and payload length.",
        "circuit_constraints": actual_constraints,
        "payload_bytes": len(payload), "trials_per_system": trials,
        "methodology": "Measured actual Node/snarkjs witness/prove/verify commands; PLONK uses a locally generated, adequately sized Powers-of-Tau transcript and setup time is reported separately. Wall times include Node process startup. Peak process RSS sampled every 10ms and may undercount short peaks. No literature-only estimates.",
        "groth16_proving_key_sha256": __import__("hashlib").sha256((BUILD / "proving_key.zkey").read_bytes()).hexdigest(),
        "powers_of_tau_power": power,
        "powers_of_tau_commands": [{"wall_ms": item["wall_ms"], "peak_rss_bytes_sampled": item["peak_rss_bytes_sampled"]} for item in ceremony],
        "powers_of_tau_final_sha256": __import__("hashlib").sha256(ptau.read_bytes()).hexdigest(),
        "powers_of_tau_final_bytes": ptau.stat().st_size,
        "plonk_setup_ms": setup["wall_ms"], "plonk_setup_peak_rss_bytes_sampled": setup["peak_rss_bytes_sampled"],
        "plonk_setup_reused_from_existing_run": existing_setup_dir is not None,
        "plonk_setup_timing_basis": setup.get("timing_basis", "perf_counter around snarkjs command"),
        "plonk_proving_key_bytes": plonk_zkey.stat().st_size,
        "plonk_vkey_export_ms": vkey["wall_ms"],
        "results": results,
        "limitations": [
            "Only Groth16 and PLONK are implemented for this exact R1CS in this run; no STARK/Halo2/Bulletproof timings are invented.",
            "Proof demonstrates the circuit statement only; it does not prove camera origin or bind the complete video bitstream.",
            "Existing Groth16 setup provenance is not independently certified by this benchmark.",
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
