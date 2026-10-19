"""Qualify matched standalone Rust build/run contracts on the selected backend."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import sys

from qualify_generation import command

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import otelc_capture as capture


def fixture(destination, backend):
    """Keep default compiler cases and add LLVM-specific location/panic controls."""
    source = destination / "application"
    source.mkdir()
    text = '''fn echo(value:u128)->u128{eprintln!("app-stderr:echo");value}
fn decimal(value:f32)->f32{value}
fn logical_source_length()->usize{file!().len()}
'''
    if backend == "llvm":
        text += '''fn logical_source_column()->usize{column!() as usize}
fn intentional_error()->i32{std::panic::panic_any("expected")}
'''
    (source / "wide.rs").write_text(text)
    policy = destination / "equivalence.toml"
    settings = '''schema_version=1
languages=["rust"]
[limits]
baseline_repeats=3
instrumented_repeats=3
[[fixtures]]
function="wide.echo"
cases=[[340282366920938463463374607431768211455]]
[[fixtures]]
function="wide.decimal"
cases=[[1.3],[-0.0]]
'''
    if backend == "llvm":
        settings += '''[adapters.rust]
backend="llvm"
[[fixtures]]
function="wide.intentional_error"
cases=[[]]
expected_baseline={kind="error",category="panic",type="rust.panic.str"}
'''
    policy.write_text(settings)
    column = next((line.index("column!") + 1 for line in text.splitlines() if "column!" in line), None)
    return source, policy, column


def expected_channels(case, column):
    """Expected values are independent of agreement between instrumented lanes."""
    function = case["function"]
    stderr = b"app-stderr:echo\n" if function == "wide.echo" else b""
    if function == "wide.echo":
        token = "return:u128:" + str(2**128 - 1)
    elif function == "wide.decimal":
        token = "return:f32:" + struct.pack(">f", case["arguments"][0]).hex()
    elif function == "wide.logical_source_column":
        token = "return:usize:" + str(column)
    elif function == "wide.intentional_error":
        token = 'error:str:"expected"'
    else:
        assert function == "wide.logical_source_length"
        token = "return:usize:7"
    return token.encode(), stderr


def check_attempt(case, folder, backend, column, lane, index, attempt):
    """Validate one independent application capture and its separate build record."""
    token, expected_stderr = expected_channels(case, column)
    assert bytes(attempt["channels"]["stdout"]) == b""
    assert bytes(attempt["channels"]["stderr"]) == expected_stderr
    assert token in bytes(attempt["channels"]["state-and-outcome"])
    evidence = folder / f"{lane}-{index}"
    log = evidence / ("plain-build.log" if lane == "baseline" else "instrumented-build.log")
    assert b"warning:" in log.read_bytes()
    identities = json.loads((evidence / "build-identities.json").read_text())
    assert identities["baseline_flags"] == list(capture.rust_flags(backend))
    launch = json.loads((evidence / "command.json").read_text())
    assert "--build" not in launch
    if lane == "instrumented_on":
        assert launch[-3:-1] == ["rust", "--run"]
        assert identities["manifest_sha256"] and identities["plan_sha256"]
        if backend == "llvm":
            assert identities["backend"] == "llvm" and identities["selected_symbol"]
            assert identities["selected_function"] == case["function"]
            assert identities["resolution_phase"] == "llvm-pipeline-start"


def check_case(case, report_root, backend, column):
    """Build diagnostics never become application channels or launch commands."""
    assert case["exit_code"] == 0
    folder = report_root / case["case"]
    bundle = json.loads((folder / "bundle.json").read_text())["cases"][0]
    for lane in ("baseline", "instrumented_on"):
        assert len(bundle[lane]) == 3
        for index, attempt in enumerate(bundle[lane]):
            check_attempt(case, folder, backend, column, lane, index, attempt)


def altered_channels(cli, destination, folder):
    """Reject deliberately edited raw/typed evidence without claiming another run."""
    control = destination / "altered-retained-stderr"
    control.mkdir()
    for kind, filename, comparator in (("raw", "bundle.json", "compare-workload"),
                                       ("typed", "typed-bundle.json", "compare-observations")):
        altered = json.loads((folder / filename).read_text())
        for attempt in altered["cases"][0]["instrumented_on"]:
            execution = attempt if kind == "raw" else attempt["execution"]
            execution["channels"]["stderr"] += list(b"warning: injected retained build diagnostic\n")
        path = control / filename
        path.write_text(json.dumps(altered))
        command([cli, comparator, path], control, kind, expected=1)
    (control / "KIND.txt").write_text("Deliberately altered retained evidence; no new target execution.\n")


def write_manifest_control(control, original_bytes, documents, filename, keys, value):
    """Preserve original bytes except the selected edit and its declared digest."""
    for name, payload in original_bytes.items():
        (control / name).write_bytes(payload)
    current = json.loads(json.dumps(documents))
    target = current[filename]
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value
    (control / filename).write_text(json.dumps(current[filename]))
    if filename != "build.json":
        digest = capture.file_digest(control / filename)
        if filename == "plan.json":
            current["build.json"]["plan_sha256"] = digest
        else:
            current["build.json"]["compiler_hook"][filename.removesuffix(".json") + "_sha256"] = digest
    (control / "build.json").write_text(json.dumps(current["build.json"]))


def manifest_controls(destination, root, plan, case, folder):
    """Exercise real retained LLVM records with the exact embedded verifier bytes."""
    assert plan["artefacts"]["rust"]["observer:otelc_capture.py"] == capture.file_digest(Path(capture.__file__))
    evidence = folder / "instrumented_on-0"
    original = evidence / "scratch/rust-bundle"
    control = destination / "altered-retained-manifests"
    control.mkdir()
    names = ("build.json", "plan.json", "inventory.json", "resolved.json")
    original_bytes = {name: (original / name).read_bytes() for name in names}
    documents = {name: json.loads(data) for name, data in original_bytes.items()}
    shutil.copyfile(original / "application", control / "application")
    tools = {name: Path(path) for name, path in plan["tools"]["rust"].items()}
    project = evidence / "project"
    environment = capture.environment(project, tools, "oteleq-retained-control", root)
    environment["TMPDIR"] = str(evidence / "scratch")
    for name, payload in original_bytes.items():
        (control / name).write_bytes(payload)
    capture.rust_manifest(root, project, project / "wide.rs", control, tools, backend="llvm",
                          expected_function=case["function"], environment=environment)
    mutations = [
        ("flags", "build.json", ("baseline_flags",), list(capture.RUST_BASELINE_FLAGS)),
        ("compiler-args", "build.json", ("compiler", "argv"), documents["build.json"]["compiler"]["argv"] + ["-Cpanic=abort"]),
        ("compiler-version", "build.json", ("compiler", "version"), "unqualified compiler"),
        *[(key, "build.json", ("compiler_hook", key), "0" * 64) for key in ("profile_sha256", "plugin_sha256", "inventory_sha256", "resolved_sha256")],
        ("phase", "resolved.json", ("phase",), "after-optimisation"),
        ("selection", "plan.json", ("functions",), {"include": ["wide.unrelated"], "exclude": []}),
    ]
    selected_index = next(index for index, row in enumerate(documents["resolved.json"]["functions"]) if row["selected"])
    mutations += [("symbol", "resolved.json", ("functions", selected_index, "compiled_symbol"), ""),
                  ("function", "resolved.json", ("functions", selected_index, "name"), "wide.unrelated")]
    for label, filename, keys, value in mutations:
        write_manifest_control(control, original_bytes, documents, filename, keys, value)
        try:
            capture.rust_manifest(root, project, project / "wide.rs", control, tools, backend="llvm",
                                  expected_function=case["function"], environment=environment)
        except ValueError as error:
            (control / (label + ".rejected.txt")).write_text(str(error) + "\n")
        else:
            raise AssertionError("altered retained manifest qualified: " + label)
    (control / "KIND.txt").write_text("Edited retained metadata, including rehashed semantic changes; no new target execution.\n")
    return len(mutations)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--cli", type=Path, default=Path(__file__).resolve().parents[1] / "target/debug/quux-oteleq")
    parser.add_argument("--backend", choices=("compiler", "llvm"), default="compiler")
    args = parser.parse_args()
    cli, root = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True)
    destination = args.report_dir.resolve()
    if destination.is_relative_to(root) or destination.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("report directory must be new and external")
    destination.mkdir(mode=0o700, exist_ok=False)
    os.environ["OTELEQ_PYTHON"] = sys.executable
    source, policy, column = fixture(destination, args.backend)
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", root,
                              "--workspace-parent", destination, "--config", policy], destination, "plan"))
    plan = json.loads((workspace / "plan.json").read_text())
    assert not any(entry["status"] == "blocked" for entry in plan["inventory"])
    command([cli, "generate", "--workspace", workspace], destination, "generate")
    report_root = destination / "comparison"
    command([cli, "run", "--workspace", workspace, "--report-dir", report_root], destination, "run", timeout=900)
    report = json.loads((report_root / "report.json").read_text())
    count = 6 if args.backend == "llvm" else 4
    assert len(report["cases"]) == count and report["source_preserved"]
    for case in report["cases"]:
        check_case(case, report_root, args.backend, column)
    case = report["cases"][0]
    folder = report_root / case["case"]
    altered_channels(cli, destination, folder)
    controls = manifest_controls(destination, root, plan, case, folder) if args.backend == "llvm" else 0
    artefacts = plan["artefacts"]["rust"]
    print(json.dumps({"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
                      "scope": "Rust-only standalone-source build/run contract; no Cargo, async or eight-language LLVM claim",
                      "backend": args.backend, "oteleq_cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
                      "provider_artefacts_sha256": hashlib.sha256(json.dumps(artefacts, sort_keys=True).encode()).hexdigest(),
                      "cases": count, "attempts": count * 6, "source_preserved": True,
                      "build_warnings_separate": True, "raw_and_typed_stderr_controls_rejected": True,
                      "retained_manifest_controls_rejected": controls,
                      "llvm_column_and_expected_panic_controls": args.backend == "llvm"}), flush=True)


if __name__ == "__main__":
    main()
