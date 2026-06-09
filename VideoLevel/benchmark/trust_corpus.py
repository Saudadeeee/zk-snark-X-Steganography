"""Trust corpus manifest validation for Upgrade-v2 evidence.

The validator keeps Section 45 honest: local diagnostics can pass, but broad
public-dataset promotion is blocked until an external corpus is explicitly
registered with source, license, file metadata, and matching hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from benchmark._common import ROOT, RESULTS_DIR, SEQUENCES


DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parent / "trust_corpus_manifest.json"
DEFAULT_OUTPUT_PATH = RESULTS_DIR / "trust_corpus_validation.json"
REQUIRED_TOP_LEVEL = {
    "schema",
    "status",
    "description",
    "claim_scope",
    "external_public_dataset",
    "entries",
    "promotion_requirements",
}
REQUIRED_EXTERNAL_FILE_FIELDS = {
    "id",
    "path",
    "sha256",
    "codec",
    "frame_count",
    "resolution",
}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_commitment(data: dict[str, Any]) -> str:
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resolve_path(path: str | Path, *, root: Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else root / p


def _is_external_entry(entry: dict[str, Any]) -> bool:
    group = str(entry.get("group", "")).lower()
    source = str(entry.get("source", "")).lower()
    return bool(entry.get("files")) or "external" in group or "public" in group or source.startswith("http")


def _validate_resolution(value: Any) -> bool:
    if isinstance(value, str):
        parts = value.lower().replace(" ", "").split("x")
        return len(parts) == 2 and all(part.isdigit() and int(part) > 0 for part in parts)
    if isinstance(value, list) and len(value) == 2:
        return all(isinstance(part, int) and part > 0 for part in value)
    return False


def validate_trust_corpus_manifest(data: dict[str, Any], *, root: str | Path = ROOT) -> dict[str, Any]:
    root_path = Path(root)
    errors: list[str] = []
    warnings: list[str] = []
    missing = sorted(REQUIRED_TOP_LEVEL - set(data.keys()))
    if missing:
        errors.append(f"missing top-level keys: {', '.join(missing)}")

    if data.get("schema") != "trust-corpus-manifest-v1":
        errors.append("schema must be trust-corpus-manifest-v1")

    entries = data.get("entries", [])
    if not isinstance(entries, list):
        errors.append("entries must be a list")
        entries = []
    if not isinstance(data.get("promotion_requirements", []), list):
        errors.append("promotion_requirements must be a list")

    local_registered_count = 0
    local_existing_count = 0
    external_entry_count = 0
    external_file_count = 0
    external_existing_count = 0
    external_hash_match_count = 0

    for entry_index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"entry {entry_index} must be an object")
            continue
        if entry.get("source") == "benchmark._common.SEQUENCES":
            local_registered_count += len(SEQUENCES)
            local_existing_count += sum(1 for path in SEQUENCES.values() if Path(path).exists())

        if not _is_external_entry(entry):
            continue
        external_entry_count += 1
        entry_source_uri = entry.get("source_uri") or entry.get("source")
        entry_license = entry.get("license")
        files = entry.get("files", [])
        if not entry_source_uri:
            errors.append(f"external entry {entry_index} must declare source_uri")
        if not entry_license:
            errors.append(f"external entry {entry_index} must declare license")
        if not isinstance(files, list) or not files:
            errors.append(f"external entry {entry_index} must declare non-empty files")
            continue

        for file_index, file_info in enumerate(files):
            external_file_count += 1
            if not isinstance(file_info, dict):
                errors.append(f"external entry {entry_index} file {file_index} must be an object")
                continue
            missing_file_fields = sorted(REQUIRED_EXTERNAL_FILE_FIELDS - set(file_info.keys()))
            if missing_file_fields:
                errors.append(
                    f"external entry {entry_index} file {file_index} missing fields: "
                    f"{', '.join(missing_file_fields)}"
                )
            if not (file_info.get("license") or entry_license):
                errors.append(f"external entry {entry_index} file {file_index} must declare license")
            if not (file_info.get("source_uri") or entry_source_uri):
                errors.append(f"external entry {entry_index} file {file_index} must declare source_uri")
            if not (file_info.get("container") or file_info.get("bitstream_format")):
                errors.append(f"external entry {entry_index} file {file_index} must declare container or bitstream_format")
            if "frame_count" in file_info:
                try:
                    if int(file_info["frame_count"]) <= 0:
                        errors.append(f"external entry {entry_index} file {file_index} frame_count must be positive")
                except (TypeError, ValueError):
                    errors.append(f"external entry {entry_index} file {file_index} frame_count must be an integer")
            if "resolution" in file_info and not _validate_resolution(file_info["resolution"]):
                errors.append(f"external entry {entry_index} file {file_index} resolution must be WxH or [W, H]")

            path_value = file_info.get("path")
            if not path_value:
                continue
            path = _resolve_path(str(path_value), root=root_path)
            if not path.exists():
                errors.append(f"external entry {entry_index} file {file_index} missing file: {path_value}")
                continue
            external_existing_count += 1
            expected_hash = str(file_info.get("sha256", "")).lower()
            actual_hash = sha256_file(path)
            if expected_hash and actual_hash == expected_hash:
                external_hash_match_count += 1
            else:
                errors.append(f"external entry {entry_index} file {file_index} sha256 mismatch")

    if local_registered_count and local_existing_count < local_registered_count:
        warnings.append(
            f"registered local corpus has {local_existing_count}/{local_registered_count} files available on this machine"
        )

    external_public_dataset = data.get("external_public_dataset") is True
    schema_valid = not errors
    promotion_blockers: list[str] = []
    if not external_public_dataset:
        promotion_blockers.append("external_public_dataset is false")
    if external_file_count <= 0:
        promotion_blockers.append("no external corpus files are registered")
    if external_file_count and external_existing_count != external_file_count:
        promotion_blockers.append("not all external corpus files exist locally")
    if external_file_count and external_hash_match_count != external_file_count:
        promotion_blockers.append("not all external corpus file hashes match")
    if errors:
        promotion_blockers.append("corpus manifest has validation errors")

    return {
        "schema": "trust-corpus-validation-v1",
        "manifest_commitment": _canonical_commitment(data),
        "schema_valid": schema_valid,
        "external_public_dataset": external_public_dataset,
        "local_registered_count": local_registered_count,
        "local_existing_count": local_existing_count,
        "external_entry_count": external_entry_count,
        "external_file_count": external_file_count,
        "external_existing_count": external_existing_count,
        "external_hash_match_count": external_hash_match_count,
        "promotion_ready": schema_valid and external_public_dataset and external_file_count > 0 and not promotion_blockers,
        "promotion_blockers": promotion_blockers,
        "errors": errors,
        "warnings": warnings,
    }


def load_and_validate_manifest(path: str | Path = DEFAULT_MANIFEST_PATH, *, root: str | Path = ROOT) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("trust corpus manifest must be a JSON object")
    return validate_trust_corpus_manifest(data, root=root)


def build_external_file_entry(
    *,
    file_id: str,
    path: str | Path,
    source_uri: str,
    license_name: str,
    codec: str,
    frame_count: int,
    resolution: str,
    source: str,
    group: str,
    container: str | None = None,
    bitstream_format: str | None = None,
    root: str | Path = ROOT,
) -> dict[str, Any]:
    resolved = _resolve_path(path, root=Path(root))
    if not resolved.exists():
        raise FileNotFoundError(f"external corpus file not found: {path}")
    if not container and not bitstream_format:
        raise ValueError("container or bitstream_format must be provided")
    if frame_count <= 0:
        raise ValueError("frame_count must be positive")
    if not _validate_resolution(resolution):
        raise ValueError("resolution must be WxH, for example 352x288")

    file_info: dict[str, Any] = {
        "id": file_id,
        "path": str(path).replace("\\", "/"),
        "sha256": sha256_file(resolved),
        "source_uri": source_uri,
        "license": license_name,
        "codec": codec,
        "frame_count": int(frame_count),
        "resolution": resolution,
    }
    if container:
        file_info["container"] = container
    if bitstream_format:
        file_info["bitstream_format"] = bitstream_format
    return {
        "group": group,
        "source": source,
        "source_uri": source_uri,
        "license": license_name,
        "files": [file_info],
    }


def _register_file_cli(args: argparse.Namespace) -> dict[str, Any]:
    entry = build_external_file_entry(
        file_id=args.id,
        path=args.path,
        source_uri=args.source_uri,
        license_name=args.license,
        codec=args.codec,
        frame_count=args.frame_count,
        resolution=args.resolution,
        source=args.source,
        group=args.group,
        container=args.container,
        bitstream_format=args.bitstream_format,
        root=args.root,
    )
    print(json.dumps(entry, indent=2, ensure_ascii=True))
    return entry


def _validate_cli(args: argparse.Namespace) -> dict[str, Any]:
    validation = load_and_validate_manifest(args.manifest, root=args.root)
    Path(args.output).write_text(json.dumps(validation, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(validation, indent=2, ensure_ascii=True))
    return validation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and register Upgrade-v2 trust corpus metadata")
    subparsers = parser.add_subparsers(dest="command")

    validate = subparsers.add_parser("validate", help="Validate a trust corpus manifest")
    validate.add_argument("--manifest", default=str(DEFAULT_MANIFEST_PATH), help="Path to trust corpus manifest JSON")
    validate.add_argument("--root", default=str(ROOT), help="Root used to resolve relative corpus file paths")
    validate.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Path to write validation JSON")
    validate.set_defaults(func=_validate_cli)

    register = subparsers.add_parser("register-file", help="Print one external corpus manifest entry")
    register.add_argument("--id", required=True, help="Stable corpus file id")
    register.add_argument("--path", required=True, help="Path to the external corpus file")
    register.add_argument("--source-uri", required=True, help="Dataset or source URL")
    register.add_argument("--license", required=True, help="Dataset/file license")
    register.add_argument("--codec", required=True, help="Codec, for example h264")
    register.add_argument("--container", help="Container or bitstream type, for example raw_h264")
    register.add_argument("--bitstream-format", help="Alternative bitstream format field")
    register.add_argument("--frame-count", required=True, type=int, help="Frame count")
    register.add_argument("--resolution", required=True, help="Resolution as WxH, for example 352x288")
    register.add_argument("--source", required=True, help="Human-readable dataset/source name")
    register.add_argument("--group", default="external_public_video", help="Corpus group label")
    register.add_argument("--root", default=str(ROOT), help="Root used to resolve relative corpus file paths")
    register.set_defaults(func=_register_file_cli)

    args = parser.parse_args(argv)
    if args.command is None:
        args = parser.parse_args(["validate", *([] if argv is None else argv)])

    result = args.func(args)
    if isinstance(result, dict) and result.get("schema") == "trust-corpus-validation-v1":
        return 0 if result["schema_valid"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
