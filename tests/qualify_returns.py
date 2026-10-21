"""Qualify declared scalar returns across real eight-language generated workers."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

from qualify_generation import command

LANGUAGES = ("c", "cpp", "rust", "python", "java", "javascript", "typescript", "go")


def scalar(language: str, value: int) -> dict:
    """Declare host primitive identities independently of worker observations."""
    if language in ("javascript", "typescript"):
        import struct
        return {"kind": "float", "type": language + ".float64", "bits": struct.pack(">d", value).hex()}
    labels = {"c": ("c.int", ctypes.sizeof(ctypes.c_int) * 8), "cpp": ("cpp.int", ctypes.sizeof(ctypes.c_int) * 8),
              "java": ("java.lang.Integer", 32), "rust": ("rust.i32", 32),
              "python": ("python.int", None), "go": ("go.int", ctypes.sizeof(ctypes.c_void_p) * 8)}
    label, bits = labels[language]
    return {"kind": "integer", "type": label, "value": str(value), "bits": bits, "signed": True}


def source(language: str) -> tuple[str, str]:
    """Both targets implement x+4; only the independently declared value differs."""
    names = ("selected_match", "selected_wrong_fixture")
    if language in ("c", "cpp"):
        return "app." + language, "\n".join(f"int {name}(int value){{return value+4;}}" for name in names) + "\n"
    if language == "rust":
        return "app.rs", "\n".join(f"fn {name}(value:i32)->i32{{value+4}}" for name in names) + "\n"
    if language == "go":
        return "app.go", "package main\n" + "\n".join(f"func {name}(value int)int{{return value+4}}" for name in names) + "\n"
    if language == "java":
        return "App.java", "class App {\n" + "\n".join(f"static int {name}(int value){{return value+4;}}" for name in names) + "\n}\n"
    if language == "python":
        return "app.py", "\n".join(f"def {name}(value:int)->int:return value+4" for name in names) + "\n"
    annotation = ":number" if language == "typescript" else ""
    extension = "ts" if language == "typescript" else "js"
    return "app." + extension, "\n".join(f"function {name}(value{annotation}){annotation}{{return value+4;}}" for name in names) + "\n"


def toml_value(value: dict) -> str:
    """Render the closed scalar fixture without a TOML-writing dependency."""
    def literal(item):
        return str(item).lower() if type(item) is bool else json.dumps(item)
    return "{" + ",".join(name + "=" + literal(item) for name, item in value.items() if item is not None) + "}"


def prepare(cli: Path, provider: Path, folder: Path) -> tuple[Path, Path]:
    """Use one source snapshot and one policy for all eight language IDs."""
    application = folder / "application"
    application.mkdir()
    policy = 'schema_version=1\n[functions]\ninclude=["*selected_*"]\n'
    for language in LANGUAGES:
        name, text = source(language)
        target = application / language / name
        target.parent.mkdir()
        target.write_text(text)
        for suffix, value in (("match", 7), ("wrong_fixture", 8)):
            policy += (f'\n[[fixtures]]\nlanguage="{language}"\nfunction="*selected_{suffix}*"\ncases=[[3]]\n'
                       + 'expected_baseline={kind="return_value",value=' + toml_value(scalar(language, value)) + '}\n')
    config = folder / "policy.toml"
    config.write_text(policy)
    workspace = Path(command([cli, "plan", "--source", application, "--otelc-root", provider,
                              "--workspace-parent", folder, "--config", config], folder, "plan"))
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    return application, workspace


def check_report(path: Path, count: int = 16) -> int:
    """Check complete literal results, fixtures and witnesses in every repeat."""
    report = json.loads(path.read_text())
    assert report["source_preserved"] and not report["blocked"] and len(report["cases"]) == count
    inventory = {entry["otelc_function"]: entry for entry in report["inventory"]}
    languages, launches = set(), 0
    for case in report["cases"]:
        entry = inventory[case["function"]]
        language = entry["language"]
        languages.add(language)
        invalid = "wrong_fixture" in case["function"]
        assert case["arguments"] == [3] and case["exit_code"] == (2 if invalid else 0)
        bundle = json.loads((path.parent / case["case"] / "typed-bundle.json").read_text())
        paired = bundle["cases"][0]
        assert paired["contract"]["expected_baseline"] == {"kind": "return_value", "value": scalar(language, 8 if invalid else 7)}
        assert case["comparison"]["verdict"] == ("blocked" if invalid else "equivalent_observed")
        for lane in ("baseline", "instrumented_on"):
            assert len(paired[lane]) == 2
            for attempt in paired[lane]:
                launches += 1
                check_attempt(attempt, entry, lane)
    assert len(languages) == (8 if count == 16 else 1)
    return launches


def check_attempt(attempt: dict, entry: dict, lane: str) -> None:
    """A matching result cannot hide a wrong codec, application exit or witness."""
    execution, observed = attempt["execution"], attempt["observation"]
    assert execution["capture_complete"] and execution["termination"] == {"kind": "exit", "code": 0}
    assert execution["channels"] == {"stdout": [], "stderr": []}
    assert observed["fixture"] == {"status": "ready"} and not observed["gaps"]
    assert observed["outcome"]["kind"] == "return"
    assert observed["outcome"]["graph"]["roots"]["result"] == scalar(entry["language"], 7)
    if lane == "instrumented_on":
        witness = execution["witness"]
        assert witness["functions"] == {entry["otelc_function"]: 1}
        assert witness["spans"] == 1 and witness["pending"] == 0 and not any(witness["losses"].values())
    else:
        assert execution["witness"] is None


def framework(workspace: Path, folder: Path, name: str) -> int:
    """A strict generated suite fails on the eight deliberately invalid fixtures."""
    output = command([sys.executable, workspace / "tests/test_equivalence.py"], folder, name, expected=1)
    records = [json.loads(line) for line in output.splitlines()]
    assert len(records) == 16
    return sum(check_report(Path(record["report"]), 1) for record in records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    args = parser.parse_args()
    provider, cli = args.otelc_root.resolve(strict=True), args.cli.resolve(strict=True)
    destination = args.report_dir.resolve()
    if any(destination.is_relative_to(root) for root in (provider, Path(__file__).resolve().parents[1])):
        parser.error("qualification directory must be new and external")
    destination.mkdir(mode=0o700, exist_ok=False)
    os.environ["OTELEQ_PYTHON"] = sys.executable
    application, workspace = prepare(cli, provider, destination)
    command([cli, "run", "--workspace", workspace, "--report-dir", destination / "comparison"], destination, "run", expected=2)
    launches = check_report(destination / "comparison/report.json")
    launches += framework(workspace, destination, "framework")
    exported = destination / "exported"
    command([cli, "export-tests", "--workspace", workspace, "--destination", exported, "--apply"], destination, "export")
    shutil.move(application, destination / "original-application-offline")
    command([cli, "run", "--workspace", exported, "--report-dir", destination / "export-comparison"], destination, "export-run", expected=2)
    launches += check_report(destination / "export-comparison/report.json")
    launches += framework(exported, destination, "export-framework")
    first = json.loads((exported / "tests/corpus.json").read_text())[0]
    expected_exit = 2 if "wrong_fixture" in first["function"] else 0
    replay = json.loads(command([cli, "replay", "--workspace", exported, "--case", first["id"]], destination, "replay", expected=expected_exit))
    launches += check_report(Path(replay["report"]), 1)
    result = {"claim": "equivalence over these tests and observations", "languages": list(LANGUAGES),
              "cases": 16, "matching_cases_per_route": 8, "invalid_baseline_cases_per_route": 8,
              "actual_application_launches": launches, "routes": ["run", "framework", "export-run", "export-framework", "replay"],
              "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
              "scope": "Frozen diagnostic scalar callers, declared host primitive values and every retained repeat; not shipping artefacts or replacement-SDK compatibility."}
    (destination / "qualification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
