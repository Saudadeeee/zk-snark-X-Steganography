"""Groth16 setup for ``circuits/camera_video.circom``.

Phase 1 reuses the public Hermez Powers-of-Tau transcript
(``powersOfTau28_hez_final_16.ptau``, 2^16 constraints). Phase 2 is a
circuit-specific ceremony: several contributions, each with fresh entropy fed
through stdin (never argv), then a public random beacon, then
``snarkjs zkey verify`` against the R1CS and the Phase 1 transcript. Running all
contributions on one machine is a demo: a deployment needs independent parties,
any one of whom being honest makes the key sound.

Outputs (``circuits/build``): ``camera_video.zkey`` (proving key),
``camera_video_vkey.json`` (verification key) and ``camera_video_setup.json``
(transcript: hashes, contributors, beacon, verify result).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CIRCUITS = ROOT / "circuits"
BUILD = CIRCUITS / "build"
CIRCUIT = "camera_video"
PTAU = BUILD / "powersOfTau28_hez_final_16.ptau"
# BLAKE2b-512 of the prepared Hermez file, as published in the snarkjs README.
PTAU_BLAKE2B = ("6a6277a2f74e1073601b4f9fed6e1e55226917efb0f0db8a07d98ab01df1ccf43eb0"
                "e8c3159432acd4960e2f29fe84a4198501fa54c8dad9e43297453efec125")
SNARKJS = CIRCUITS / "node_modules" / "snarkjs" / "build" / "cli.cjs"
ZKEY = BUILD / f"{CIRCUIT}.zkey"
VKEY = BUILD / f"{CIRCUIT}_vkey.json"
TRANSCRIPT = BUILD / f"{CIRCUIT}_setup.json"
BEACON_ITERATIONS_EXP = 10


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _blake2b(path: Path) -> str:
    digest = hashlib.blake2b()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snarkjs(*args: str, stdin: bytes | None = None) -> str:
    result = subprocess.run(["node", str(SNARKJS), *args], input=stdin, capture_output=True,
                            cwd=str(CIRCUITS), check=False)
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"snarkjs {args[0]} {args[1] if len(args) > 1 else ''} failed:\n{output[-2000:]}")
    return output


def compile_circuit() -> Path:
    r1cs = BUILD / f"{CIRCUIT}.r1cs"
    wasm = BUILD / f"{CIRCUIT}_js" / f"{CIRCUIT}.wasm"
    source = CIRCUITS / f"{CIRCUIT}.circom"
    if not (r1cs.is_file() and wasm.is_file()) or r1cs.stat().st_mtime < source.stat().st_mtime:
        BUILD.mkdir(exist_ok=True)
        result = subprocess.run(["circom", source.name, "--r1cs", "--wasm", "--sym", "-o", "build"],
                                cwd=str(CIRCUITS), capture_output=True, check=False, shell=False)
        if result.returncode != 0:
            raise RuntimeError("circom compile failed:\n" + (result.stdout + result.stderr).decode(errors="replace")[-2000:])
    return r1cs


def run_setup(contributors: list[str], overwrite: bool = False) -> dict:
    """Run the Phase 2 ceremony and publish the keys and transcript."""
    if ZKEY.exists() and not overwrite:
        raise FileExistsError(f"{ZKEY.name} exists; pass overwrite=True to replace the keys")
    if not PTAU.is_file():
        raise FileNotFoundError(f"Phase 1 transcript missing: {PTAU}")
    if _blake2b(PTAU) != PTAU_BLAKE2B:
        raise ValueError(f"{PTAU.name} does not match the published BLAKE2b hash")
    if not contributors:
        raise ValueError("at least one Phase 2 contributor is required")
    r1cs = compile_circuit()
    work = BUILD / ("setup_" + secrets.token_hex(6))
    work.mkdir()
    try:
        current = work / "c0.zkey"
        _snarkjs("groth16", "setup", str(r1cs), str(PTAU), str(current))
        contributions = []
        for index, name in enumerate(contributors, start=1):
            following = work / f"c{index}.zkey"
            # snarkjs prompts for entropy when -e is absent; stdin keeps it out of the process list.
            output = _snarkjs("zkey", "contribute", str(current), str(following), f"--name={name}",
                              stdin=(secrets.token_hex(64) + "\n").encode("ascii"))
            contributions.append({"name": name, "zkey_sha256": _sha256(following),
                                  "log_tail": output.strip().splitlines()[-1:]})
            current = following
        beacon = secrets.token_hex(32)
        final = work / "final.zkey"
        _snarkjs("zkey", "beacon", str(current), str(final), beacon, str(BEACON_ITERATIONS_EXP), "--name=public beacon")
        verify_output = _snarkjs("zkey", "verify", str(r1cs), str(PTAU), str(final))
        if "ZKey Ok!" not in verify_output:
            raise RuntimeError("snarkjs zkey verify did not report 'ZKey Ok!'")
        _snarkjs("zkey", "export", "verificationkey", str(final), str(work / "vkey.json"))
        # Same-directory renames: each key file is either the old one or the complete new one.
        os.replace(final, ZKEY)
        os.replace(work / "vkey.json", VKEY)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    transcript = {
        "schema": "zkstego-groth16-setup-1", "circuit": f"{CIRCUIT}.circom",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "r1cs_sha256": _sha256(r1cs), "phase1": {"file": PTAU.name, "blake2b": PTAU_BLAKE2B,
                                                  "source": "Hermez Powers of Tau (public, 2^16), hash pinned"},
        "phase2_contributions": contributions,
        "beacon": {"hash_hex": beacon, "iterations_exp": BEACON_ITERATIONS_EXP,
                   "source": "locally generated random value, not a public randomness beacon"},
        "zkey_verify": "ZKey Ok!", "proving_key_sha256": _sha256(ZKEY), "verification_key_sha256": _sha256(VKEY),
        "trust": ("All Phase 2 contributions ran on one machine: a demo ceremony. A deployment needs "
                  "independent contributors; the key is sound if any one of them discarded their entropy."),
    }
    TRANSCRIPT.write_text(json.dumps(transcript, indent=2), encoding="utf-8")
    return transcript


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--contributor", action="append", default=None,
                        help="Phase 2 contributor name (repeat; default: two demo contributors)")
    parser.add_argument("--overwrite", action="store_true", help="replace existing keys")
    args = parser.parse_args()
    transcript = run_setup(args.contributor or ["demo contributor A", "demo contributor B"], args.overwrite)
    print(json.dumps({k: transcript[k] for k in ("circuit", "proving_key_sha256", "verification_key_sha256")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
