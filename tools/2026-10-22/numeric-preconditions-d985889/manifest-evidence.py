"""Seal accepted numeric-precondition evidence, excluding rebuildable Go caches."""
import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ACTUAL = ROOT / "actual"
MANIFEST = ROOT / "raw-evidence-manifest.json"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def records() -> dict:
    result = {}
    for parent, directories, filenames in os.walk(ACTUAL):
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    observed = records()
    if args.verify:
        expected = json.loads(MANIFEST.read_text())
        if observed != expected["records"]:
            raise ValueError("retained evidence differs from the accepted manifest")
    else:
        if MANIFEST.exists():
            raise ValueError("accepted manifest already exists; use --verify")
        result = {"root": str(ROOT), "excluded_rebuildable_directories": ["go-cache"],
                  "records": observed, "retained_evidence_records": len(observed)}
        MANIFEST.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"mode": "verified" if args.verify else "sealed", "records": len(observed),
                      "manifest_sha256": digest(MANIFEST)}, indent=2))


if __name__ == "__main__":
    main()
