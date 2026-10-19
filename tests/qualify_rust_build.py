"""Qualify separate Rust build diagnostics and application execution on real otelc."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

from qualify_generation import command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--cli", type=Path, default=Path(__file__).resolve().parents[1] / "target/debug/quux-oteleq")
    args = parser.parse_args()
    cli, root = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True)
    destination = args.report_dir.resolve()
    if destination.is_relative_to(root) or destination.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("report directory must be new and external")
    destination.mkdir(mode=0o700, exist_ok=False)
    os.environ["OTELEQ_PYTHON"] = sys.executable
    source = destination / "application"
    source.mkdir()
    (source / "wide.rs").write_text('''fn echo(value:u128)->u128{eprintln!("app-stderr:echo");value}
fn decimal(value:f32)->f32{value}
fn logical_source_length()->usize{file!().len()}
''')
    policy = destination / "equivalence.toml"
    policy.write_text('''schema_version=1
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
''')
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", root,
                              "--workspace-parent", destination, "--config", policy], destination, "plan"))
    plan = json.loads((workspace / "plan.json").read_text())
    assert not any(entry["status"] == "blocked" for entry in plan["inventory"])
    command([cli, "generate", "--workspace", workspace], destination, "generate")
    report_root = destination / "comparison"
    command([cli, "run", "--workspace", workspace, "--report-dir", report_root], destination, "run", timeout=900)
    report = json.loads((report_root / "report.json").read_text())
    assert len(report["cases"]) == 4 and report["source_preserved"]
    for case in report["cases"]:
        assert case["exit_code"] == 0
        folder = report_root / case["case"]
        bundle = json.loads((folder / "bundle.json").read_text())["cases"][0]
        expected_stderr = b"app-stderr:echo\n" if case["function"] == "wide.echo" else b""
        if case["function"] == "wide.echo":
            token = ("return:u128:" + str(2**128 - 1)).encode()
        elif case["function"] == "wide.decimal":
            token = ("return:f32:" + struct.pack(">f", case["arguments"][0]).hex()).encode()
        else:
            token = b"return:usize:7"
        for lane in ("baseline", "instrumented_on"):
            assert len(bundle[lane]) == 3
            for index, attempt in enumerate(bundle[lane]):
                assert bytes(attempt["channels"]["stdout"]) == b""
                assert bytes(attempt["channels"]["stderr"]) == expected_stderr
                assert token in bytes(attempt["channels"]["state-and-outcome"])
                evidence = folder / f"{lane}-{index}"
                log = evidence / ("plain-build.log" if lane == "baseline" else "instrumented-build.log")
                assert b"warning:" in log.read_bytes()
                identities = json.loads((evidence / "build-identities.json").read_text())
                assert identities["baseline_flags"] == ["--edition=2024", "-O", "-g"]
                launch = json.loads((evidence / "command.json").read_text())
                assert "--build" not in launch
                if lane == "instrumented_on":
                    assert launch[-3:-1] == ["rust", "--run"]
                    assert identities["manifest_sha256"] and identities["plan_sha256"]
    case = report["cases"][0]
    altered = json.loads((report_root / case["case"] / "bundle.json").read_text())
    for attempt in altered["cases"][0]["instrumented_on"]:
        attempt["channels"]["stderr"] += list(b"warning: injected retained build diagnostic\n")
    control = destination / "altered-retained-stderr"
    control.mkdir()
    (control / "bundle.json").write_text(json.dumps(altered))
    command([cli, "compare-workload", control / "bundle.json"], control, "compare", expected=1)
    (control / "KIND.txt").write_text("Deliberately altered retained stderr; not another target execution.\n")
    artefacts = plan["artefacts"]["rust"]
    summary = {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
               "scope": "Rust-only standalone-source build/run contract; no integrated eight-language claim",
               "oteleq_cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
               "provider_artefacts_sha256": hashlib.sha256(json.dumps(artefacts, sort_keys=True).encode()).hexdigest(),
               "otelc_cli_sha256": artefacts["target/debug/quux-otelc"],
               "cases": 4, "attempts": 24, "repeats_per_lane": 3,
               "build_warnings_retained_separately": True, "raw_application_stderr_preserved": True,
               "u128_f32_negative_zero_and_logical_source_path": True,
               "altered_stderr_control_rejected": True, "source_preserved": report["source_preserved"]}
    (destination / "qualification.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
