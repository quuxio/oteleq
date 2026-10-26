"""Independently check declared Go build budgets in completed actual routes."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STAGES = ("initial", "changed", "added", "different")
ENVIRONMENT_KEYS = ("GOVERSION", "GOROOT", "GOTOOLDIR", "GOOS", "GOARCH", "GOAMD64",
                    "GOARM64", "GOEXPERIMENT", "GOFLAGS", "CGO_ENABLED", "GOWORK")


def read(path):
    return json.loads(path.read_text())


def main():
    assert not __import__("sys").flags.optimize
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through", choices=STAGES, default="initial")
    args = parser.parse_args()
    checked = {}
    for stage in STAGES[:STAGES.index(args.through) + 1]:
        route = read(ROOT / "actual" / (stage + ".checked.json"))
        workspace = Path(route["workspace"])
        plan = read(workspace / "plan.json")
        assert plan["configuration"]["adapters"]["go"]["build_timeout_ms"] == 600000
        assert plan["configuration"]["limits"]["case_timeout_ms"] == 60000
        entries = [entry for entry in plan["inventory"] if entry["language"] == "go"]
        assert len(entries) == (2 if stage in ("initial", "changed") else 3)
        assert all(entry["go_build_timeout_ms"] == 600000 for entry in entries)
        attempts = [Path(name) for name in route["attempts"]
                    if (Path(name) / "go-build-identities.json").is_file()]
        assert len(attempts) == (24 if stage in ("initial", "changed") else 28)
        for attempt in attempts:
            project = attempt / "project"
            expected = [
                [plan["tools"]["go"]["go"], "env", "-json", *ENVIRONMENT_KEYS],
                [str(Path(plan["otelc_root"]) / "target/debug/quux-otelc"),
                 "--config", str(attempt / "policy.toml"), "--language", "go", "go", "--build",
                 str(project / "go/app.go"), "--output-dir", str(attempt / "go-bundle")],
            ]
            receipts = list(attempt.glob("build-*/build-command.json"))
            assert len(receipts) == 2
            vectors = []
            for receipt in receipts:
                data = read(receipt)
                assert set(data) == {"schema_version", "argv", "cwd", "timeout_ms"}
                assert type(data["schema_version"]) is int and data["schema_version"] == 1
                assert type(data["timeout_ms"]) is int and data["timeout_ms"] == 600000
                assert data["cwd"] == str(project)
                assert (receipt.parent / "stdout").is_file() and (receipt.parent / "stderr").is_file()
                vectors.append(data["argv"])
                checked[str(receipt)] = hashlib.sha256(receipt.read_bytes()).hexdigest()
            assert sorted(vectors) == sorted(expected)
    record = {"through": args.through, "go_attempts": len(checked) // 2,
              "build_commands": len(checked), "per_build_timeout_ms": 600000,
              "unchanged_application_timeout_ms": 60000, "receipts": checked}
    (ROOT / ("go-build-budget-" + args.through + "-review.json")).write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({key: value for key, value in record.items() if key != "receipts"}))


if __name__ == "__main__":
    main()
