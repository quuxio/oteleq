"""Recheck the frozen legacy SDK records without modifying the provider."""
import hashlib
import json
import os
from pathlib import Path

PROOF = Path("/Users/sclarke/github/oteleq-qualification/2026-10-22/domain-generation-1a16757")
manifest = Path("/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/manifest.json")
digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
assert digest(manifest) == "2a8dbf239c6444c0fb536dff049993beade7eaed6578c9654c1e2d7233e9431f"
data = json.loads(manifest.read_text())
root = Path(data["source_root"])
counts = {}
symlinks = 0
for section in ("source_sha256", "products_sha256", "dependencies"):
    counts[section] = len(data[section])
    for name, record in data[section].items():
        path = root / name
        assert path.is_relative_to(root), name
        if isinstance(record, str):
            assert digest(path) == record, name
        elif "symlink" in record:
            assert path.is_symlink() and os.readlink(path) == record["symlink"], name
            assert str(path.resolve(strict=True)) == record["resolved"], name
            symlinks += 1
        else:
            assert not path.is_symlink() and digest(path) == record["sha256"], name
for name, record in data["tools"].items():
    path = Path(record["path"])
    assert str(path.resolve(strict=True)) == record["resolved"], name
    assert digest(path) == record["sha256"], name
result = {"provider_commit": data["source_commit"], "manifest_sha256": digest(manifest),
          "verified_records": sum(counts.values()), "counts": counts,
          "symlinks_verified": symlinks, "external_tools_verified": len(data["tools"]),
          "result": "all recorded SDK inputs unchanged after qualification"}
(PROOF / "provider-input-recheck.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))

