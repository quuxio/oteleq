"""Qualify native primitive callers while unresolved object aliases stay blocked."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys

from qualify_generation import command


def main() -> None:
    """Run witnessed C/C++ primitive cases beside accounted unsupported objects."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    args = parser.parse_args()
    root, cli = args.otelc_root.resolve(strict=True), args.cli.resolve(strict=True)
    destination = args.report_dir.resolve()
    if any(destination.is_relative_to(parent) for parent in (root, Path(__file__).resolve().parents[1])):
        parser.error("qualification directory must be new and external")
    destination.mkdir(mode=0o700, exist_ok=False)
    os.environ["OTELEQ_PYTHON"] = sys.executable
    source = destination / "application"
    source.mkdir()
    for language, boolean in (("c", "_Bool"), ("cpp", "bool")):
        (source / ("types." + language)).write_text(
            "typedef struct {char kind;int value;} i32;\n"
            "i32 selected_bad(void){i32 value={1,7};return value;}\n"
            "int selected_good(int value){return value+1;}\n"
            + f"int selected_bool({boolean} value){{return value?1:0;}}\n")
    policy = destination / "equivalence.toml"
    policy.write_text('''schema_version=1
languages=["c","cpp"]
[[fixtures]]
function="*selected_good*"
cases=[[7]]
[[fixtures]]
function="*selected_bool*"
cases=[[true],[false]]
''')
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", root,
                              "--workspace-parent", destination, "--config", policy], destination, "plan"))
    plan = json.loads((workspace / "plan.json").read_text())
    blocked = [entry for entry in plan["inventory"] if entry["status"] == "blocked"]
    aliases = [entry for entry in blocked if entry["name"] == "selected_bad"]
    assert len(aliases) == 2
    assert all("fixture" in entry["reason"] for entry in blocked)
    command([cli, "generate", "--workspace", workspace], destination, "generate")
    comparison = destination / "comparison"
    command([cli, "run", "--workspace", workspace, "--report-dir", comparison], destination, "run", expected=3)
    report = json.loads((comparison / "report.json").read_text())
    assert report["source_preserved"] and len(report["blocked"]) == len(blocked) and len(report["cases"]) == 6
    assert all(case["exit_code"] == 0 for case in report["cases"])
    for case in report["cases"]:
        bundle = json.loads((comparison / case["case"] / "bundle.json").read_text())["cases"][0]
        expected = 8 if "selected_good" in case["function"] else int(case["arguments"][0])
        token = ("return:int:" + expected.to_bytes(ctypes.sizeof(ctypes.c_int), sys.byteorder).hex()).encode()
        for lane in ("baseline", "instrumented_on"):
            assert len(bundle[lane]) == 2
            assert all(token in bytes(attempt["channels"]["state-and-outcome"]) for attempt in bundle[lane])
    summary = {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
               "scope": "six witnessed C/C++ primitive cases; object aliases and compiler-declared constructors remain blocked",
               "oteleq_cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
               "otelc_cli_sha256": hashlib.sha256((root / "target/debug/quux-otelc").read_bytes()).hexdigest(),
               "matching_cases": 6, "matching_attempts": 24, "blocked_callables": len(blocked),
               "blocked_object_aliases": len(aliases), "blocked_other_declarations": len(blocked) - len(aliases),
               "qualifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "strict_gate_exit": 3, "source_preserved": True, "native_scalar_value_oracles": True}
    (destination / "qualification.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
