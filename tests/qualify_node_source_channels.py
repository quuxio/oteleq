"""Qualify exact nonempty application byte channels under the source SDK."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import node_project_oracle as graph_oracle
import node_source_oracle as sdk_oracle
from qualify_project_tests import command

STDOUT = b"\0\xff\n"
CHANGED_STDOUT = b"\0\xfe\n"
STDERR = b"\x01\xff\n"


def fixture(language: str) -> str:
    annotation = ":number" if language == "typescript" else ""
    return ('let state=2;\n'
            'function selected_match(value' + annotation + '){state+=value;'
            'process.stdout.write(Buffer.from([0,255,10]));process.stderr.write(Buffer.from([1,255,10]));return state+value;}\n'
            'function selected_difference(value' + annotation + '){state+=value;'
            'const active=process.execArgv.join(" ").includes("/node-bootstrap.cjs");'
            'process.stdout.write(Buffer.from([0,active?254:255,10]));'
            'process.stderr.write(Buffer.from([1,255,10]));return state+value;}\n')


def policy(language: str, compiler: str) -> str:
    return ('schema_version=1\nlanguages=' + json.dumps([language]) + '\n'
            '[adapters.node]\nbackend="source-v1"\ntypescript_compiler=' + json.dumps(compiler) + '\n'
            '[functions]\ninclude=["channels.selected_match","channels.selected_difference"]\n'
            '[[fixtures]]\nfunction="channels.selected_match"\ncases=[[7]]\n'
            '[[fixtures]]\nfunction="channels.selected_difference"\ncases=[[7]]\n')


def expected_stdout(function: str, lane: str) -> bytes:
    if function not in {"channels.selected_match", "channels.selected_difference"}:
        raise ValueError("unknown channel fixture")
    return CHANGED_STDOUT if function.endswith("selected_difference") and lane == "instrumented_on" else STDOUT


def check_report(path: Path, language: str, count: int) -> set[tuple[str, int]]:
    """Check literal binary outputs separately from complete state and SDK receipts."""
    report = json.loads(path.read_bytes())
    assert report["source_preserved"] is True and not report["blocked"] and len(report["cases"]) == count
    identities = set()
    for case in report["cases"]:
        different = case["function"] == "channels.selected_difference"
        assert case["arguments"] == [7.0] and case["exit_code"] == int(different)
        bundle = json.loads((path.parent / case["case"] / "typed-bundle.json").read_bytes())["cases"][0]
        for lane in ("baseline", "instrumented_on"):
            assert len(bundle[lane]) == 2
            for index, attempt in enumerate(bundle[lane]):
                folder = path.parent / case["case"] / (lane + "-" + str(index))
                execution = attempt["execution"]
                assert bytes(execution["channels"]["stdout"]) == (folder / "stdout").read_bytes() == expected_stdout(case["function"], lane)
                assert bytes(execution["channels"]["stderr"]) == (folder / "stderr").read_bytes() == STDERR
                graph_oracle.check_observation(attempt["observation"], {"language": language, "receiver": False, "different": False}, lane, 7.0)
                request = json.loads((folder / "node-source-request.json").read_bytes())
                app = json.loads((folder / "node-source-application.json").read_bytes())
                identities.add((request["runtime"], app["pid"]))
                if lane == "instrumented_on":
                    sdk_oracle.check_attempt(folder, {"function": case["function"], "language": language},
                                             json.loads((folder / "http-capture.json").read_bytes()))
        if different:
            compared = case["comparison"]["cases"][0]
            assert {row["path"] for row in compared["execution"]["differences"]} == {"channels.stdout"}
            assert all(not pair["comparison"]["differences"] for pair in compared["pairs"])
    assert len(identities) == count * 4
    return identities


def framework(workspace: Path, root: Path, name: str, language: str) -> set[tuple[str, int]]:
    text = command([sys.executable, "-I", "-B", workspace / "tests/test_equivalence.py"], root, name, 1)
    records = [json.loads(line) for line in text.splitlines()]
    assert len(records) == 2
    identities = set()
    for row in records:
        identities |= check_report(Path(row["report"]), language, 1)
    return identities


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    if sys.flags.optimize:
        parser.error("qualification requires Python assertion checks; disable -O/PYTHONOPTIMIZE")
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--language", choices=("javascript", "typescript"), default="javascript")
    parser.add_argument("--typescript-compiler", choices=("native", "api"), default="native")
    args = parser.parse_args(argv)
    cli, provider, root = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True), args.report_dir.resolve()
    if any(root.is_relative_to(path) for path in (provider, Path(__file__).resolve().parents[1])):
        parser.error("report directory must be new and outside source and provider")
    root.mkdir(mode=0o700)
    os.environ.update(OTELEQ_CLI=str(cli), OTELEQ_PYTHON=sys.executable)
    application = root / "application"; application.mkdir()
    source = fixture(args.language)
    filename = application / ("channels.mjs" if args.language == "javascript" else "channels.mts")
    filename.write_text(source)
    config = root / "policy.toml"; config.write_text(policy(args.language, args.typescript_compiler))

    def run(name, arguments, expected=0):
        return command([cli, *arguments], root, name, expected)

    workspace = Path(run("plan", ["plan", "--source", application, "--otelc-root", provider, "--workspace-parent", root, "--config", config]))
    run("generate", ["generate", "--workspace", workspace])
    run("run", ["run", "--workspace", workspace, "--report-dir", root / "comparison"], 1)
    report = json.loads((root / "comparison/report.json").read_bytes())
    identities = check_report(root / "comparison/report.json", args.language, 2)
    identities |= framework(workspace, root, "framework", args.language)
    for case in report["cases"]:
        replay = json.loads(run("replay-" + case["case"], ["replay", "--workspace", workspace, "--case", case["case"]], case["exit_code"]))
        identities |= check_report(Path(replay["report"]), args.language, 1)
    exported = root / "exported"
    run("export-dry", ["export-tests", "--workspace", workspace, "--destination", exported])
    assert not exported.exists()
    run("export", ["export-tests", "--workspace", workspace, "--destination", exported, "--apply"])
    detached = root / "detached-application"; application.rename(detached)
    try:
        identities |= framework(exported, root, "detached-framework", args.language)
    finally:
        detached.rename(application)
    assert filename.read_text() == source and len(identities) == 32
    record = {"claim": "equivalence over these tests and observations", "applications": len(identities),
              "language": args.language, "compiler": args.typescript_compiler,
              "actual_application_identities": sorted(identities), "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
              "scope": "Literal nonempty binary stdout/stderr, matching state/returns and one stdout-only difference through four retained routes."}
    (root / "QUALIFICATION.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
