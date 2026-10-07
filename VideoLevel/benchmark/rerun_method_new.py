"""Re-run one method everywhere after a fix: drop its quality rows and stego files, or merge new
steganalysis groups for it into the recorded detector results.

    py -3.12 -m benchmark.rerun_method_new drop <method>
    py -3.12 -m benchmark.rerun_method_new manifest <method>      # writes steganalysis_manifest_<method>.json
    py -3.12 -m benchmark.rerun_method_new merge <method>         # merges steganalysis_<det>_<method>.json
"""
from __future__ import annotations

import json
import sys

from benchmark.stego_compare_new import OUT

DETECTORS = ("cavlc", "spam", "srmlite", "cnn")


def drop(method: str) -> None:
    for dataset in ("cif", "hd"):
        path = OUT / f"{dataset}.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        kept = [line for line in lines if json.loads(line)["method"] != method]
        path.write_text("".join(line + "\n" for line in kept), encoding="utf-8")
        print(f"{dataset}: removed {len(lines) - len(kept)} rows")
    removed = 0
    for stego in (OUT / "stego").glob(f"*__{method}__*.h264"):
        stego.unlink()
        removed += 1
    print(f"removed {removed} stego files")


def manifest(method: str) -> None:
    entries = json.loads((OUT / "steganalysis_manifest.json").read_text(encoding="utf-8"))
    subset = [e for e in entries if e["method"] == method]
    (OUT / f"steganalysis_manifest_{method}.json").write_text(json.dumps(subset, indent=1), encoding="utf-8")
    print(f"{len(subset)} pairs")


def merge(method: str) -> None:
    for detector in DETECTORS:
        main_path, new_path = OUT / f"steganalysis_{detector}.json", OUT / f"steganalysis_{detector}_{method}.json"
        document = json.loads(main_path.read_text(encoding="utf-8"))
        fresh = json.loads(new_path.read_text(encoding="utf-8"))["groups"]
        document["groups"] = [g for g in document["groups"] if g.get("method") != method] + fresh
        main_path.write_text(json.dumps(document, indent=2), encoding="utf-8")
        new_path.unlink()
        print(f"{detector}: merged {len(fresh)} groups")


if __name__ == "__main__":
    {"drop": drop, "manifest": manifest, "merge": merge}[sys.argv[1]](sys.argv[2])
