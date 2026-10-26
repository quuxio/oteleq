"""Independently recheck retained results and count all inventory entries."""
import hashlib
import json
from pathlib import Path
import sys
import tarfile
import xml.etree.ElementTree as ET

ROOT = Path("/Users/sclarke/github/oteleq-qualification/2026-10-22/input-walks-6c61dcc")
SOURCE = ROOT / "reviewed-source"
if not SOURCE.exists():
    archive = ROOT / "source.tar"
    expected = json.loads((ROOT / "frozen-build.json").read_text())["source_archive_sha256"]
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected
    with tarfile.open(archive) as contents:
        assert all(item.isfile() or item.isdir() for item in contents.getmembers())
        contents.extractall(SOURCE, filter="data")
sys.path[:0] = [str(SOURCE / name) for name in ("tests", "adapters/generation", "examples")]
from qualify_retained_source import check_report

positive = ROOT / "actual/positive"
reports = sorted(positive.rglob("report.json"))
seen = set()
for path in reports:
    data = json.loads(path.read_text())
    checked = check_report(path, {x["path"] for x in data["owned_source_exclusions"]}, len(data["cases"]))
    assert seen.isdisjoint(checked), str(path)
    seen.update(checked)
assert len(reports) == 20 and len(seen) == 136
assert seen == set(json.loads((positive / "qualification.json").read_text())["actual_attempt_directories"])
junit = ET.parse(positive / "presentation/junit.xml").getroot()
assert junit.attrib == {"tests": "16", "failures": "0", "errors": "0", "skipped": "8"}
assert len(list(junit.iter("testcase"))) == 16
assert len(list(junit.iter("skipped"))) == 8
assert not list(junit.iter("failure")) and not list(junit.iter("error"))
assert "retained; workspace" in (positive / "presentation/index.html").read_text()
result = {"reports_verified": 20, "distinct_attempts_verified": 136,
          "complete_graphs_raw_channels_witnesses_verified": True,
          "junit_inventory_entries": 16, "junit_completed_cases": 8, "junit_explicit_exclusions": 8,
          "junit_failures": 0, "junit_errors": 0, "html_scope_present": True,
          "visual_review": "unchanged renderer; no new visual qualification claimed"}
(ROOT / "retained-independent-review.json").write_text(json.dumps(result, indent=2) + "\n")
records = {}
for path in sorted((ROOT / "actual").rglob("*")):
    if "go-cache" in path.relative_to(ROOT / "actual").parts:
        continue
    assert not path.is_symlink(), str(path)
    if path.is_file():
        records[path.relative_to(ROOT / "actual").as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
manifest = {"scope": "actual qualification evidence; rebuildable go-cache contents excluded",
            "file_count": len(records), "files": records}
(ROOT / "raw-evidence-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps({**result, "retained_evidence_files": len(records)}, indent=2))

