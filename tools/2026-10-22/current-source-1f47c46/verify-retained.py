"""Verify frozen current-source qualification without launching applications."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parent


def read(path: Path):
    return json.loads(path.read_text())


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    assert not sys.flags.optimize
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--through", choices=("preflight", "initial", "changed", "added", "different", "complete"), default="preflight")
    args = parser.parse_args()
    frozen = read(ROOT / "freeze.json")
    archive, cli = ROOT / "source-1f47c46.tar", Path(frozen["cli"])
    assert digest(archive) == frozen["source_archive_sha256"] and digest(cli) == frozen["cli_sha256"]
    source = ROOT / "reviewed-source-1f47c46"
    with tarfile.open(archive) as contents:
        members = contents.getmembers()
        assert all(member.isfile() or member.isdir() for member in members)
        if not source.exists():
            contents.extractall(source, filter="data")
        for member in members:
            if member.isfile():
                assert not (source / member.name).is_symlink()
                assert (source / member.name).read_bytes() == contents.extractfile(member).read()
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source / "tests"))
    import project_fixture_oracle as oracle
    stages = ["initial", "changed", "added", "different"]
    selected = [] if args.through == "preflight" else stages if args.through == "complete" else stages[:stages.index(args.through) + 1]
    seen, reports = set(), {}

    def suite(folder: Path, name: str, stage: str, preflight: bool = False) -> None:
        assert (folder / (name + ".exit")).read_text().strip() == str(int(stage == "different"))
        stdout = folder / (name + ".stdout")
        workspace, observed = oracle.check_suite(stdout, stage, preflight=preflight)
        checked = read(folder / (name + ".checked.json"))
        plan = read(workspace / "plan.json")
        assert plan["cli_sha256"] == frozen["cli_sha256"]
        assert plan["source_manifest"] == checked["source_manifest"]
        assert set(checked["attempts"]) == observed and seen.isdisjoint(observed)
        seen.update(observed)
        for record in [json.loads(line) for line in stdout.read_text().splitlines()][1:]:
            path = Path(record["report"])
            report = read(path)
            case = report["cases"][0]
            bundle = path.parent / case["case"] / "typed-bundle.json"
            result = subprocess.run([str(cli), "compare-observations", str(bundle)], capture_output=True, check=False, timeout=30)
            assert result.returncode == case["exit_code"] and not result.stderr
            assert json.loads(result.stdout) == case["comparison"]
            assert str(path) not in reports
            reports[str(path)] = {"sha256": digest(path), "bundle_sha256": digest(bundle), "stage": stage}

    suite(ROOT / "preflight/preflight", "suite", "initial", True)
    preliminary = len(seen)
    actual = ROOT / "actual"
    if selected:
        suite(actual / "preflight", "suite", "initial", True)
        for stage in selected:
            suite(actual, stage, stage)
    if args.through == "complete":
        assert (ROOT / "qualification.exit").read_text().strip() == "0"
        final = read(actual / "qualification.json")
        assert final["status"] == "complete" and final["actual_launches"] == 936
        assert final["prelaunch_refusals"] == 10 and final["cli_sha256"] == frozen["cli_sha256"]
        assert set(final["attempts"]) == {item for item in seen if Path(item).is_relative_to(actual)}
        controls = actual / "controls"
        for name in ("missing-source", "missing-file", "extra-file", "changed-file", "linked-file", "changed-cli",
                     "changed-generator", "changed-provider", "empty-source"):
            assert (controls / (name + ".exit")).read_text().strip() == "1"
            assert "Ran 1 test" in (controls / (name + ".stderr")).read_text()
        assert (controls / "resealed-foreign.exit").read_text().strip() == "4"
        assert not list(controls.rglob("typed-observation.json"))
        physical = set()
        for parent, directories, files in os.walk(actual):
            directories[:] = [name for name in directories if name != "go-cache"]
            if "typed-observation.json" in files:
                physical.add(str(Path(parent).resolve()))
        assert physical == set(final["attempts"])
        assert len(seen) == preliminary + 936 == 956 and len(reports) == 239
    record = {"scope": args.through, "preliminary_preflight_launches": preliminary,
        "distinct_launches_verified": len(seen), "reports_verified": len(reports),
        "typed_comparisons_recomputed": len(reports), "literal_graphs_and_raw_channels_checked": True,
        "source_archive_sha256": frozen["source_archive_sha256"], "cli_sha256": frozen["cli_sha256"],
        "reports": reports, "attempts": sorted(seen)}
    write = ROOT / ("retained-independent-review.json" if args.through == "complete" else "retained-" + args.through + "-review.json")
    write.write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({key: value for key, value in record.items() if key not in ("reports", "attempts")}, indent=2))


if __name__ == "__main__":
    main()
