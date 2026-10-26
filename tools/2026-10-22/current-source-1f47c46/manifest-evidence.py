"""Seal complete current-source qualification evidence, excluding Go caches."""
import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "raw-evidence-manifest.json"


def read(path):
    return json.loads(path.read_text())


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def failed_walk(error):
    raise error


def records():
    result = {}
    for tree in (ROOT / "actual", ROOT / "preflight"):
        for parent, directories, filenames in os.walk(tree, onerror=failed_walk):
            directories[:] = sorted(name for name in directories if name != "go-cache")
            for name in (*directories, *sorted(filenames)):
                path = Path(parent) / name
                relative = path.relative_to(ROOT).as_posix()
                if path.is_symlink():
                    result[relative] = {"symlink": os.readlink(path)}
                elif path.is_file():
                    result[relative] = {"sha256": digest(path), "bytes": path.stat().st_size}
                elif not path.is_dir():
                    raise ValueError("unsupported evidence entry: " + relative)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if (ROOT / "qualification.exit").read_text().strip() != "0":
        raise ValueError("actual qualifier did not complete successfully")
    actual, reviewed = read(ROOT / "actual/qualification.json"), read(ROOT / "retained-independent-review.json")
    if actual["actual_launches"] != 936 or reviewed["distinct_launches_verified"] != 956:
        raise ValueError("complete actual and independent review receipts are required")
    if reviewed["reports_verified"] != 239 or reviewed["typed_comparisons_recomputed"] != 239:
        raise ValueError("complete retained comparison review is required")
    observed = records()
    if args.verify:
        if observed != read(MANIFEST)["records"]:
            raise ValueError("retained evidence differs from the accepted manifest")
    else:
        if MANIFEST.exists():
            raise ValueError("accepted manifest already exists; use --verify")
        MANIFEST.write_text(json.dumps({"root": str(ROOT), "trees": ["actual", "preflight"],
            "excluded_rebuildable_directories": ["go-cache"], "records": observed,
            "retained_evidence_records": len(observed)}, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"mode": "verified" if args.verify else "sealed", "records": len(observed),
                      "manifest_sha256": digest(MANIFEST)}, indent=2))


if __name__ == "__main__":
    main()
