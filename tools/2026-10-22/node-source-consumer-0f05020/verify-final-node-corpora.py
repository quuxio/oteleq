"""Deduplicate actual launches and recompute all retained successful/incomplete cases."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

if sys.flags.optimize:
    raise ValueError("verification requires assertions")

ROOT = Path(__file__).parent
CLI = ROOT / "quux-oteleq-3e9614e"
EXPECTED_CLI = "eb8e74a66b752f22fc6ca50dcb4c6190ee56e10ba864c7bbe4cb8970063c7446"
assert hashlib.sha256(CLI.read_bytes()).hexdigest() == EXPECTED_CLI
CORPORA = {
    "module-3e-node24-native": 245, "module-3e-node24-api": 245,
    "module-3e-node26-native": 245, "module-3e-node26-api": 245,
    "receivers-3e-node24-api": 186, "receivers-3e-node26-native": 186,
    "collection-828ecb4-node24": 64, "collection-828ecb4-node26": 64,
    "effects-v2-node24-js": 64, "effects-v2-node26-ts-api": 64,
    "effects-e33-node24-ts-native": 64, "effects-e33-node26-js": 64,
}

global_identities = set()
rows = []
for name, expected in CORPORA.items():
    root = ROOT / name
    receipt = json.loads((root / "QUALIFICATION.json").read_bytes())
    assert receipt["cli_sha256"] == EXPECTED_CLI
    assert receipt.get("actual_application_launches", receipt.get("actual_applications", receipt.get("applications"))) == expected
    identities, raw_records = set(), 0
    for path in root.rglob("node-source-application.json"):
        request = json.loads((path.parent / "node-source-request.json").read_bytes())
        app = json.loads(path.read_bytes())
        assert type(app["pid"]) is int and app["pid"] > 0
        identities.add((request["runtime"], app["pid"]))
        raw_records += 1
    assert len(identities) == expected, (name, expected, len(identities))
    assert not global_identities & identities, name
    global_identities |= identities
    compared, refused, report_count = 0, 0, 0
    for path in sorted(root.rglob("report.json")):
        report = json.loads(path.read_bytes())
        if "cases" not in report or "source_preserved" not in report:
            continue
        assert report["source_preserved"] is True, path
        report_count += 1
        for case in report["cases"]:
            if case["exit_code"] not in (0, 1, 3):
                assert case["exit_code"] in (2, 4)
                refused += 1
                continue
            bundle = path.parent / case["case"] / "typed-bundle.json"
            result = subprocess.run([str(CLI), "compare-observations", str(bundle)], capture_output=True, timeout=30)
            assert result.returncode == case["exit_code"], (path, case["case"], result.returncode)
            assert json.loads(result.stdout) == case["comparison"], (path, case["case"])
            compared += 1
    rows.append({"corpus": name, "actual_applications": len(identities), "raw_application_receipts": raw_records,
                 "reports_checked": report_count, "comparisons_recomputed": compared,
                 "tool_fixture_refusal_case_records": refused})
    print(json.dumps(rows[-1]), flush=True)

assert len(global_identities) == sum(CORPORA.values()) == 1736
record = {"actual_applications": len(global_identities), "corpora": rows,
          "comparisons_recomputed": sum(row["comparisons_recomputed"] for row in rows),
          "cli_sha256": EXPECTED_CLI, "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
(ROOT / "final-corpus-audit.json").write_text(json.dumps(record, indent=2) + "\n")
