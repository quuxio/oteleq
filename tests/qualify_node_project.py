"""Qualify actual Node module formats, retained routes and refusal controls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import node_project_oracle as oracle
from qualify_generation import command

CONTEXTS = (
    ("cjs", ".cjs", None, "commonjs"),
    ("mjs", ".mjs", None, "module"),
    ("js-default", ".js", None, "commonjs"),
    ("js-module", ".js", "module", "module"),
    ("js-commonjs", ".js", "commonjs", "commonjs"),
    ("js-detected", ".js", None, "module"),
    ("cts", ".cts", None, "commonjs"),
    ("mts", ".mts", None, "module"),
    ("ts-default", ".ts", None, "commonjs"),
    ("ts-module", ".ts", "module", "module"),
    ("ts-commonjs", ".ts", "commonjs", "commonjs"),
)


def fixture(context: tuple, *, receiver: bool = False, different: bool = False) -> tuple[dict, str, str | None]:
    """Declare fixed source and complete expected values independently of workers."""
    name, suffix, package_type, module_format = context
    language = "typescript" if suffix in (".ts", ".mts", ".cts") else "javascript"
    annotation = ":number" if language == "typescript" else ""
    if receiver:
        source = ("class Counter {\nconstructor(start" + annotation
                  + "){this.value=start;this.alias=this;}\nadd(n" + annotation
                  + "){this.value+=n;return this.value;}\n}\n")
    else:
        prefix = "export " if name == "js-detected" else ""
        extra = "+Number(process.execArgv.join(' ').includes('/node/register.mjs'))" if different else ""
        result = "7" if different else "state+n"
        source = "let state=2;\n" + prefix + "function selected(n" + annotation + "){state+=n" + extra + ";return " + result + ";}\n"
    source += 'console.log(typeof require==="function"?"commonjs":"module");\n'
    package_text = json.dumps({"type": package_type}) + "\n" if package_type else None
    spec = {"context": name, "filename": "sample" + suffix, "language": language,
            "format": module_format, "receiver": receiver, "different": different,
            "function": "sample.Counter.add" if receiver else "sample.selected",
            "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
            "package": {"path": "package.json", "sha256": hashlib.sha256(package_text.encode()).hexdigest()} if package_text else None}
    return spec, source, package_text


def policy(spec: dict) -> str:
    """Use one known concrete input and an independently declared return value."""
    result = 17.0 if spec["receiver"] else 7.0 if spec["different"] else 16.0
    value = ("schema_version=1\nlanguages=" + json.dumps([spec["language"]])
             + "\n[functions]\ninclude=" + json.dumps([spec["function"]])
             + "\n[[fixtures]]\nfunction=" + json.dumps(spec["function"]) + "\ncases=[[7]]\n"
             + 'expected_baseline={kind="return_value",value={kind="float",type="'
             + spec["language"] + '.float64",bits="' + oracle.number(spec["language"], result)["bits"] + '"}}\n')
    if spec["receiver"]:
        value += 'receiver={factory="Counter",arguments=[10]}\n'
    if spec["different"]:
        value += 'domains=[{kind="integer",minimum=0,maximum=7}]\n'
    return value


def prepare(cli: Path, provider: Path, folder: Path, spec: dict, source: str, package: str | None) -> Path:
    """Create and seal an ordinary public-CLI workspace."""
    folder.mkdir()
    application = folder / "application"
    application.mkdir()
    (application / spec["filename"]).write_text(source)
    if package is not None:
        (application / "package.json").write_text(package)
    configuration = folder / "equivalence.toml"
    configuration.write_text(policy(spec))
    workspace = Path(command([cli, "plan", "--source", application, "--otelc-root", provider,
                              "--workspace-parent", folder, "--config", configuration], folder, "plan"))
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    return workspace


def source_preserved(folder: Path, spec: dict, source: str, package: str | None) -> None:
    """Require the original application's complete fixture bytes and file list."""
    application = folder / "application"
    expected = {spec["filename"]: source.encode()}
    if package is not None:
        expected["package.json"] = package.encode()
    actual = {p.relative_to(application).as_posix(): p.read_bytes() for p in application.rglob("*") if p.is_file()}
    oracle.require(actual == expected, "original fixture source changed")


def framework(workspace: Path, folder: Path, name: str, spec: dict, argument: float = 7.0) -> set[str]:
    """Check each generated case's retained report, not just the framework exit."""
    output = command([sys.executable, workspace / "tests/test_equivalence.py"], folder, name,
                     expected=int(spec["different"]))
    reports = [json.loads(line)["report"] for line in output.splitlines()]
    oracle.require(len(reports) == 1, "generated framework case count differs")
    return oracle.check_report(Path(reports[0]), spec, workspace, argument)


def retained_routes(cli: Path, folder: Path, workspace: Path, spec: dict) -> set[str]:
    """Exercise replay, generated tests and export after detaching original source."""
    case = json.loads((workspace / "tests/corpus.json").read_text())[0]["id"]
    replay = json.loads(command([cli, "replay", "--workspace", workspace, "--case", case],
                                folder, "replay", expected=int(spec["different"])))
    launches = oracle.check_report(Path(replay["report"]), spec, workspace)
    launches |= framework(workspace, folder, "framework", spec)
    exported = folder / "exported"
    command([cli, "export-tests", "--workspace", workspace, "--destination", exported], folder, "export-dry-run")
    oracle.require(not exported.exists(), "dry-run created export destination")
    command([cli, "export-tests", "--workspace", workspace, "--destination", exported, "--apply"], folder, "export-apply")
    original = folder / "application"
    detached = folder / "detached-application"
    original.rename(detached)
    try:
        launches |= framework(exported, folder, "detached-framework", spec)
    finally:
        detached.rename(original)
    return launches


def reduction(cli: Path, folder: Path, workspace: Path, spec: dict) -> set[str]:
    """Retain and check original, every trial, confirmation and reduced replay."""
    case = json.loads((workspace / "tests/corpus.json").read_text())[0]["id"]
    destination = folder / "shrinking"
    command([cli, "shrink", "--workspace", workspace, "--case", case,
             "--report-dir", destination, "--trials", "16"], folder, "shrink", expected=1)
    summary = json.loads((destination / "shrink.json").read_text())
    oracle.require(summary["status"] == "candidate_rule_minimal" and summary["reduced_arguments"] == [0.0], "scalar reduction differs")
    reduced = Path(summary["workspace"])
    launches = oracle.check_report(destination / "original/report.json", spec, workspace)
    paths = [destination / "confirmation/report.json", *(Path(t["report"]) for t in summary["trials"])]
    for path in paths:
        report = json.loads(path.read_text())
        launches |= oracle.check_report(path, spec, reduced, report["cases"][0]["arguments"][0])
    launches |= framework(reduced, folder, "reduced-framework", spec, 0.0)
    replay = json.loads(command([cli, "replay", "--workspace", reduced, "--case", case], folder, "reduced-replay", expected=1))
    launches |= oracle.check_report(Path(replay["report"]), spec, reduced, 0.0)
    return launches


def qualify(cli: Path, provider: Path, destination: Path, context: tuple,
            node_version: str, direct: Path | None = None, *, receiver: bool = False,
            different: bool = False) -> dict:
    """Qualify one frozen module context through all consumer routes."""
    spec, source, package = fixture(context, receiver=receiver, different=different)
    spec["node_version"] = node_version
    folder = destination / (spec["context"] + ("-receiver" if receiver else "-difference" if different else ""))
    if direct is not None:
        folder = direct / spec["context"]
        workspace = Path((folder / "plan.stdout").read_text().strip())
        plan = json.loads((workspace / "plan.json").read_text())
        oracle.require(plan["cli_sha256"] == oracle.digest(cli), "retained direct CLI differs")
        oracle.require((folder / "equivalence.toml").read_text() == policy(spec), "retained direct policy differs")
    else:
        workspace = prepare(cli, provider, folder, spec, source, package)
        command([cli, "run", "--workspace", workspace, "--report-dir", folder / "comparison"],
                folder, "run", expected=int(different))
    source_preserved(folder, spec, source, package)
    launches = oracle.check_report(folder / "comparison/report.json", spec, workspace)
    launches |= retained_routes(cli, folder, workspace, spec)
    if different:
        launches |= reduction(cli, folder, workspace, spec)
    source_preserved(folder, spec, source, package)
    return {**spec, "folder": str(folder), "workspace": str(workspace), "routes": ["run", "replay", "framework", "detached-framework"],
            "actual_application_launches": len(launches), "application_command_identities": sorted(launches), "source_preserved": True}


def refusal(cli: Path, provider: Path, destination: Path, kind: str) -> dict:
    """Prove unsafe context is refused before launching an application."""
    spec, source, package = fixture(CONTEXTS[4])
    folder = destination / kind
    if kind == "shadowed-require":
        source = "const require=()=>({});\n" + source
    marker = folder / "application-started"
    if kind == "forged-format":
        source = "require('node:fs').writeFileSync(" + json.dumps(str(marker)) + ",'started');\n" + source
    workspace = prepare(cli, provider, folder, spec, source, package)
    if kind == "changed-source":
        (folder / "application" / spec["filename"]).write_text(source + "\n// changed\n")
    elif kind == "forged-format":
        path = workspace / "plan.json"
        plan = json.loads(path.read_text())
        for entry in plan["inventory"]:
            if entry["status"] == "ready":
                entry["node_context"]["format"] = "module"
        path.write_text(json.dumps(plan))
        marker_path = workspace / ".oteleq-owned.json"
        marker = json.loads(marker_path.read_text())
        marker["plan_sha256"] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        marker_path.write_text(json.dumps(marker))
    comparison = folder / "comparison"
    expected = 3 if kind == "shadowed-require" else 4
    command([cli, "run", "--workspace", workspace, "--report-dir", comparison], folder, "run", expected=expected)
    oracle.require(not list(comparison.rglob("command.json")), "refusal launched application")
    oracle.require(not (folder / "application-started").exists(), "context inspection evaluated application initialisers")
    if kind == "shadowed-require":
        report = json.loads((comparison / "report.json").read_text())
        oracle.require(len(report["blocked"]) == 1 and not report["cases"] and "unshadowed" in json.dumps(report["blocked"]), "missing named require blocker")
    elif kind == "forged-format":
        report = json.loads((comparison / "report.json").read_text())
        oracle.require("changed its source/package module context" in json.dumps(report), "forged format not refused by caller context")
    else:
        oracle.require("changed" in (folder / "run.stderr").read_text(), "changed source refusal missing")
    return {"control": kind, "exit_code": expected, "actual_application_launches": 0}


def ambient_refusal(cli: Path, provider: Path, destination: Path) -> dict:
    """An original parent package cannot disappear silently in a private snapshot."""
    folder = destination / "ambient-package"
    folder.mkdir()
    source = folder / "application"
    source.mkdir()
    marker = folder / "application-started"
    (source / "sample.js").write_text("import fs from 'node:fs';fs.writeFileSync("
        + json.dumps(str(marker)) + ",'started');\nexport function selected(n){return n;}\n")
    (folder / "package.json").write_text('{"type":"module"}\n')
    parent = destination / "isolated-workspaces"
    parent.mkdir()
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", provider,
        "--workspace-parent", parent, "--language", "javascript"], folder, "plan"))
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    comparison = folder / "comparison"
    command([cli, "run", "--workspace", workspace, "--report-dir", comparison], folder, "run", expected=3)
    report = json.loads((comparison / "report.json").read_text())
    oracle.require(len(report["blocked"]) == 1 and not report["cases"]
                   and "escapes the private snapshot" in json.dumps(report["blocked"]), "ambient source context not named")
    oracle.require(not marker.exists() and not list(comparison.rglob("command.json")), "ambient context launched application")
    return {"control": "ambient-package", "exit_code": 3, "actual_application_launches": 0}


def rebound_refusal(cli: Path, provider: Path, destination: Path) -> dict:
    """Startup rebinding cannot substitute a different callable for the source body."""
    spec, source, package = fixture(CONTEXTS[4])
    folder = destination / "rebound-callable"
    source += "selected=()=>99;\n"
    workspace = prepare(cli, provider, folder, spec, source, package)
    comparison = folder / "comparison"
    command([cli, "run", "--workspace", workspace, "--report-dir", comparison], folder, "run", expected=4)
    report = json.loads((comparison / "report.json").read_text())
    oracle.require(report["source_preserved"] and len(report["cases"]) == 1 and report["cases"][0]["exit_code"] == 4,
                   "startup replacement was accepted")
    oracle.require(len(list(comparison.rglob("command.json"))) == 1 and not list(comparison.rglob("observation")), "binding refusal launch count differs")
    channels = b"\n".join(p.read_bytes() for p in comparison.rglob("stderr"))
    oracle.require(b"binding" in channels, "source binding refusal missing")
    return {"control": "rebound-callable", "exit_code": 4, "actual_application_launches": 1}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--direct-matrix", type=Path)
    args = parser.parse_args()
    cli, provider, destination = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True), args.report_dir.resolve()
    if destination.is_relative_to(provider) or destination.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("report directory must be new and outside both repositories")
    destination.mkdir(mode=0o700, exist_ok=False)
    os.environ["OTELEQ_PYTHON"], os.environ["OTELEQ_CLI"] = sys.executable, str(cli)
    node = os.environ.get("OTELC_NODE") or shutil.which("node")
    version = subprocess.run([node, "--version"], capture_output=True, text=True, check=True).stdout.strip()
    results = []
    for context in CONTEXTS:
        results.append(qualify(cli, provider, destination, context, version, args.direct_matrix))
        (destination / "progress.json").write_text(json.dumps(results, indent=2) + "\n")
    for context in (CONTEXTS[4], CONTEXTS[10]):
        results.append(qualify(cli, provider, destination, context, version, receiver=True))
    results.append(qualify(cli, provider, destination, CONTEXTS[4], version, different=True))
    controls = [refusal(cli, provider, destination, kind) for kind in ("shadowed-require", "changed-source", "forged-format")]
    controls.extend((ambient_refusal(cli, provider, destination), rebound_refusal(cli, provider, destination)))
    summary = {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
               "cli_sha256": oracle.digest(cli), "cases": results, "controls": controls,
               "actual_application_launches": sum(r["actual_application_launches"] for r in [*results, *controls]),
               "scope": "Fixed source formats and supported own state; dependency installation, semantic TypeScript builds and shipping artefacts remain open."}
    (destination / "QUALIFICATION.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
