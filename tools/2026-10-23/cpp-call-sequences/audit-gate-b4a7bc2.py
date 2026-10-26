"""Audit terminal validation and preserve distinct execution identities."""

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent
COMMIT = "b4a7bc22d894197a0a897c34126fe6ae90972dd8"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    receipt = json.loads((ROOT / "gate-b4a7bc2.json").read_text())
    assert receipt["commit"] == COMMIT and receipt["exit_code"] == 0
    seal = json.loads((ROOT / "source-b4a7bc2.json").read_text())
    assert seal["commit"] == COMMIT and len(seal["files"]) == 406
    for name, expected in seal["files"].items():
        assert digest(ROOT / "source-b4a7bc2" / name) == expected, name
    executed = json.loads((ROOT / "source-50f01a7.json").read_text())
    runtime = [name for name in executed["files"]
               if name.startswith(("src/", "adapters/", "examples/"))
               or name in ("Cargo.toml", "Cargo.lock")]
    assert len(runtime) == 103
    assert all(executed["files"][name] == seal["files"][name]
               for name in runtime)
    log_path = ROOT / "gate-b4a7bc2.log"
    log = log_path.read_text()
    counts = [int(value) for value in re.findall(r"Ran (\d+) tests? in ", log)]
    assert counts == [171, 9, 116, 807], counts
    assert "TOTAL                            2824" in log
    assert re.search(r"^TOTAL\s+2824.*97\.38%", log, re.MULTILINE)
    rust_runs = [int(value) for value in
                 re.findall(r"test result: ok\. (\d+) passed", log)]
    assert sum(rust_runs) == 148  # The same 74 tests run with coverage again.
    node_totals = [int(value) for value in re.findall(r"ℹ tests (\d+)", log)]
    assert node_totals == [3, 13, 7, 3, 4], node_totals
    assert not re.search(r"ℹ fail [1-9]|^FAILED|^FAIL:", log, re.MULTILINE)
    components = {"capture": 171, "generation": 807, "rust": 74,
                  "node": 27, "go": 4}
    record = {
        "commit": COMMIT, "exit_code": 0, "source_files_preserved": 406,
        "runtime_source_files_identical_to_executed_50f01a7": len(runtime),
        "unittest_runs": counts, "distinct_tests": sum(components.values()),
        "distinct_components": components,
        "counting": "Java9 and qualification116 recur in generation807; Node checkpoint3 and Rust74 coverage reruns are counted once.",
        "rust_product_line_coverage": 97.38,
        "log_sha256": digest(log_path),
        "scope": "Exact publication component gate with required host process permissions. Actual149/331 launch corpora retain executor50/70; original50 sandbox gate failure is preserved."
    }
    (ROOT / "gate-b4a7bc2-audit.json").write_text(
        json.dumps(record, indent=2) + "\n")
    print(json.dumps(record))


if __name__ == "__main__":
    main()
