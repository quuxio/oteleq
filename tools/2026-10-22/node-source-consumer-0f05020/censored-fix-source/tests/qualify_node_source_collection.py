"""Qualify source5 ordered calls, actual collection and a retained-object control."""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys

import node_collection_oracle as oracle
from qualify_generation import command


def fixture(language: str, *, held: bool = False) -> str:
    annotation = ":number" if language == "typescript" else ""
    source = ('class Counter {constructor(start' + annotation + '){this.value=start;this.self=this;} '
              'add(value' + annotation + '){this.value+=value;return this.value;}}\n'
              'function make(start' + annotation + '){return new Counter(start);}\n')
    if held:
        source = "let held=null;\n" + source.replace("return new Counter(start);", "held=new Counter(start);return held;")
    return source


def policy(language: str, compiler: str) -> str:
    return ('schema_version=1\nlanguages=' + json.dumps([language]) + '\n[functions]\ninclude=["seq.Counter.add"]\n'
            '[adapters.node]\nbackend="source-v1"\ntypescript_compiler=' + json.dumps(compiler) + '\n'
            '[[fixtures]]\nfunction="seq.Counter.add"\ncases=[[7]]\nreceiver={factory="make",arguments=[10]}\n'
            'sequence=[{action="call",arguments="case"},{action="call",arguments=[2]},'
            '{action="release"},{action="collect",gc_rounds=64,settle_turns=4}]\n')


def check_sdk(sdk: dict) -> None:
    """The fixed factory and two methods yield three functions and one lifetime."""
    values = (sdk["function_completions"], sdk["span_accounting"]["received"],
              *(sdk["lifetimes"][key] for key in ("admitted", "gc_completed", "censored", "current_live")))
    if any(type(actual) is not int or actual != wanted for actual, wanted in zip(values, (3, 4, 1, 1, 0, 0))):
        raise ValueError("collection SDK function/lifetime counts differ")


def check_report(path: Path, *, held: bool = False) -> set[tuple[str, int]]:
    """Check every raw boundary, output channel, SDK receipt and actual app identity."""
    report = json.loads(path.read_bytes())
    expected = 3 if held else 0
    if not report["source_preserved"] or report["blocked"] or len(report["cases"]) != 1:
        raise ValueError("collection source/inventory coverage differs")
    case = report["cases"][0]
    if report["exit_code"] != expected or case["exit_code"] != expected:
        raise ValueError("collection verdict differs: " + json.dumps(case))
    identities = set()
    for lane in ("baseline", "instrumented_on"):
        for index in range(2):
            folder = path.parent / case["case"] / (lane + "-" + str(index))
            oracle.check(json.loads((folder / "observation").read_bytes()), held=held)
            if (folder / "stdout").read_bytes() or (folder / "stderr").read_bytes():
                raise ValueError("collection application channels differ")
            request = json.loads((folder / "node-source-request.json").read_bytes())
            app = json.loads((folder / "node-source-application.json").read_bytes())
            identities.add((request["runtime"], app["pid"]))
            if request["gc_fixture"] is not True:
                raise ValueError("collection launch lacks the declared GC test mode")
            if lane == "instrumented_on" and not held:
                sdk = json.loads((folder / "node-runtime/node-status.json").read_bytes())
                check_sdk(sdk)
    if len(identities) != 4:
        raise ValueError("collection applications were not independent")
    return identities


def qualify(cli: Path, provider: Path, folder: Path, language: str, compiler: str, suffix: str,
            *, held: bool = False) -> dict:
    folder.mkdir(mode=0o700)
    application = folder / "application"
    application.mkdir()
    source = fixture(language, held=held)
    filename = application / ("seq" + suffix)
    filename.write_text(source)
    config = folder / "equivalence.toml"
    config.write_text(policy(language, compiler))
    stages = []

    def run(stage, arguments, expected=0):
        receipt = {"stage": stage, "started": True}
        stages.append(receipt)
        (folder / "stages.json").write_text(json.dumps(stages, indent=2) + "\n")
        result = command([cli, *arguments], folder, stage, expected=expected)
        receipt["completed"] = True
        (folder / "stages.json").write_text(json.dumps(stages, indent=2) + "\n")
        return result

    workspace = Path(run("plan", ["plan", "--source", application, "--otelc-root", provider,
                                  "--workspace-parent", folder, "--config", config]))
    run("generate", ["generate", "--workspace", workspace])
    run("run", ["run", "--workspace", workspace, "--report-dir", folder / "comparison"], 3 if held else 0)
    identities = check_report(folder / "comparison/report.json", held=held)
    if held:
        report = json.loads((folder / "comparison/report.json").read_bytes())
        bundle = json.loads((folder / "comparison" / report["cases"][0]["case"] / "typed-bundle.json").read_bytes())
        altered = copy.deepcopy(bundle)
        for lane in ("baseline", "instrumented_on"):
            for attempt in altered["cases"][0][lane]:
                attempt["execution"]["capture_complete"] = True
                attempt["observation"]["gaps"] = []
                for step in attempt["observation"]["steps"]:
                    step["gaps"] = []
        control = folder / "hidden-collection-gap.json"
        control.write_text(json.dumps(altered))
        result = json.loads(run("hidden-collection-gap", ["compare-observations", control], 3))
        if result["verdict"] != "inconclusive":
            raise ValueError("censored collection became an equivalence pass")
    if filename.read_text() != source:
        raise ValueError("original collection source changed")
    return {"language": language, "compiler": compiler, "held": held, "actual_applications": len(identities),
            "application_identities": sorted(identities), "workspace": str(workspace), "source_preserved": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    cli, provider, root = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True), args.report_dir.resolve()
    if root.is_relative_to(provider) or root.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("report directory must be new and outside source and provider")
    root.mkdir(mode=0o700)
    os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli))
    rows = []
    for language, compiler, suffix in (("javascript", "native", ".cjs"), ("typescript", "native", ".cts"),
                                      ("typescript", "api", ".mts")):
        rows.append(qualify(cli, provider, root / (language + "-" + compiler), language, compiler, suffix))
        (root / "progress.json").write_text(json.dumps(rows, indent=2) + "\n")
    rows.append(qualify(cli, provider, root / "retained-object", "javascript", "native", ".cjs", held=True))
    result = {"claim": "equivalence over these tests and observations", "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
              "profiles": rows, "actual_applications": sum(row["actual_applications"] for row in rows),
              "scope": "Declared two-call source receiver and bounded GC; no GC timing or leak claim."}
    (root / "QUALIFICATION.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
