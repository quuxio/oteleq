"""Revalidate every retained Go report, source identity and raw evidence file."""
import hashlib
import json
from collections import Counter
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "consumer/tests"))
import qualify_go_receivers as q


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


state = json.loads((ROOT / "qualification-state.json").read_text())
assert state["state"] == "completed" and state["exit_code"] == 0
result = json.loads((ROOT / "actual/QUALIFICATION.json").read_text())
assert result["cases"] == 9 and result["actual_application_launches"] == 168
runtime = json.loads((ROOT / "runtime.json").read_text())
assert digest(ROOT / "quux-oteleq") == runtime["cli_sha256"] == result["cli_sha256"]
assert digest(ROOT / "consumer-source.tar") == runtime["source_archive_sha256"]
source_count = 0
with tarfile.open(ROOT / "consumer-source.tar") as archive:
    for member in archive.getmembers():
        if member.isfile():
            assert digest(ROOT / "consumer" / member.name) == hashlib.sha256(archive.extractfile(member).read()).hexdigest()
            source_count += 1
reports = list((ROOT / "actual/receivers").rglob("report.json"))
sizes = [len(json.loads(path.read_text())["cases"]) for path in reports]
assert sorted(sizes) == [1]*23 + [9]*2
# Shrinking retains both the original replay report and its copied evidence.
assert sum(q.check_report(path, size) for path, size in zip(reports, sizes)) == 164
refusals = list((ROOT / "actual/refusals").glob("*/comparison/report.json"))
assert len(refusals) == 9
for path in refusals:
    report = json.loads(path.read_text())
    assert report["source_preserved"]
    expected = 3 if path.parent.parent.name in ("missing-factory", "wrong-factory", "opaque-global", "helper-collision") else 2 if path.parent.parent.name == "initial-state" else 4
    assert (bool(report["blocked"]) and not report["cases"]) if expected == 3 else (len(report["cases"]) == 1 and report["cases"][0]["exit_code"] == expected)
commands = [path for path in (ROOT / "actual").rglob("command.json")
            if path.parent.name.startswith(("baseline-", "instrumented_on-"))]
identities = {digest(path) for path in commands}
assert len(commands) == 172 and len(identities) == 168
assert sorted(Counter(digest(path) for path in commands).values()) == [1]*164 + [2]*4
loaded = {}
bundle_records = 0
for command in commands:
    bundle = command.parent / "go-bundle"
    metadata = json.loads((bundle / "build.json").read_text())
    assert metadata["schema_version"] == 1 and metadata["language"] == "go"
    for name, expected in metadata["files"].items():
        assert not Path(name).is_absolute() and ".." not in Path(name).parts
        assert digest(bundle / name) == expected
        bundle_records += 1
    recipe = json.loads((bundle / "recipe.json").read_text())
    for name, record in recipe["inputs"].items():
        assert Path(name).is_absolute() and set(record) in ({"sha256"}, {"absent"})
        assert name not in loaded or loaded[name] == record
        loaded[name] = record
for name, record in loaded.items():
    if "sha256" in record:
        assert digest(Path(name)) == record["sha256"]
    else:
        assert record["absent"] is True and not Path(name).exists() and not Path(name).is_symlink()
raw = {}
for path in sorted((ROOT / "actual").rglob("*")):
    if path.is_symlink():
        raw[str(path.relative_to(ROOT))] = {"symlink": str(path.readlink()), "resolved": str(path.resolve(strict=True))}
    elif path.is_file():
        raw[str(path.relative_to(ROOT))] = digest(path)
(ROOT / "raw-manifest.json").write_text(json.dumps(raw, indent=2) + "\n")
verified = {"source_files_verified": source_count, "qualified_reports_verified": len(reports),
            "refusal_reports_verified": len(refusals), "qualified_attempt_records_verified": 164,
            "qualified_actual_launches": 160, "copied_original_shrink_attempts": 4,
            "actual_application_launches": 168, "retained_attempt_folders": len(commands),
            "unique_command_identities": len(identities), "raw_records": len(raw),
            "bundle_file_records_verified": bundle_records, "unique_loaded_inputs_verified": len(loaded),
            "raw_manifest_sha256": digest(ROOT / "raw-manifest.json"), "source_preserved": True,
            "verifier_sha256": digest(Path(__file__))}
(ROOT / "verification.json").write_text(json.dumps(verified, indent=2) + "\n")
print(json.dumps(verified), flush=True)
