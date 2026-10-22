"""Qualify current-source suites, changed bodies and fresh callable discovery."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from precondition_fixture_oracle import LANGUAGES, SEQUENCES, source
from project_fixture_oracle import STAGES, TEXT_VALUES, check_suite
from qualify_preconditions import fixture


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def command(arguments: list, folder: Path, name: str, expected: int = 0,
            environment: dict | None = None) -> str:
    """A started operation is never silently relaunched after partial evidence."""
    marker = folder / (name + ".started.json")
    assert not marker.exists(), "inspect an incomplete operation before any recovery: " + name
    write(marker, {"argv": list(map(str, arguments)), "expected_exit": expected})
    result = subprocess.run(list(map(str, arguments)), capture_output=True, check=False,
                            env=None if environment is None else {**os.environ, **environment})
    (folder / (name + ".stdout")).write_bytes(result.stdout)
    (folder / (name + ".stderr")).write_bytes(result.stderr)
    (folder / (name + ".exit")).write_text(str(result.returncode) + "\n")
    assert result.returncode == expected, name + ": inspect retained output"
    return result.stdout.decode().strip()


def toml(value) -> str:
    """An independent literal policy writer preserves non-BMP input characters."""
    if isinstance(value, dict):
        return "{" + ",".join(key + "=" + toml(item) for key, item in value.items() if item is not None) + "}"
    if isinstance(value, list):
        return "[" + ",".join(map(toml, value)) + "]"
    return json.dumps(value, ensure_ascii=False, allow_nan=False).replace("\x7f", "\\u007f")


def policy(path: Path, *, preflight: bool = False) -> None:
    languages = [language for language in LANGUAGES if not preflight or language in SEQUENCES | {"python"}]
    fixtures = []
    for language in languages:
        kinds = [] if preflight else ["integer", "float"]
        if language in SEQUENCES:
            kinds.append("sequence")
        fixtures.extend(fixture(language, kind) for kind in kinds)
    fixtures.append({"source": "python/app.py", "function": "*current_text", "cases": [[value] for value in TEXT_VALUES],
        "expected_baseline": {"kind": "return_value", "value": {
            "kind": "integer", "type": "python.int", "value": "1", "signed": True}}})
    includes = ["*Meter.numeric_step*", "*current_text"] if preflight else [
        "*numeric_span*", "*numeric_float*", "*Meter.numeric_step*", "*current_*"]
    text = 'schema_version=1\nlanguages=' + toml(languages)
    text += '\n[generation]\nseed=123\ncases_per_function=3\n'
    text += '[functions]\ninclude=' + toml(includes) + '\n'
    for item in fixtures:
        text += '\n[[fixtures]]\n' + '\n'.join(key + '=' + toml(value) for key, value in item.items()) + '\n'
    text += '\n[adapters.go]\nbuild_timeout_ms=600000\n'
    path.write_text(text)


def added_source(language: str) -> str:
    if language in ("c", "cpp"):
        return "int current_added(){return 5;}\n"
    if language == "rust":
        return "fn current_added()->i32{5}\n"
    if language == "python":
        return "def current_added()->int:return 5\n"
    if language == "java":
        return "static int current_added(){return 5;}\n"
    if language == "go":
        return "func current_added()int{return 5}\n"
    annotation = ":number" if language == "typescript" else ""
    return "function current_added()" + annotation + "{return 5;}\n"


def application_sources(application: Path) -> dict:
    return {language + "/" + source(language)[0]: digest(application / language / source(language)[0])
            for language in LANGUAGES}


def prepare(cli: Path, provider: Path, folder: Path, application: Path,
            *, preflight: bool = False) -> tuple[Path, Path]:
    config = folder / "policy.toml"
    policy(config, preflight=preflight)
    workspace = Path(command([cli, "plan", "--source", application, "--otelc-root", provider,
        "--workspace-parent", folder, "--config", config], folder, "plan"))
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    bundle = application / ("preflight-tests" if preflight else "equivalence-tests")
    dry = json.loads(command([cli, "promote", "--workspace", workspace, "--source", application,
        "--destination", bundle], folder, "promote-dry"))
    assert dry["mode"] == "dry-run" and len(dry["files"]) == 6 and not bundle.exists()
    command([cli, "promote", "--workspace", workspace, "--source", application,
        "--destination", bundle, "--apply"], folder, "promote")
    assert len(list(bundle.iterdir())) == 6
    return workspace, bundle


def suite(bundle: Path, folder: Path, name: str, stage: str, *, preflight: bool = False,
          discovery: bool = False, source_path: Path | None = None) -> tuple[Path, set[str]]:
    before = application_sources(source_path or bundle.parent)
    argv = [sys.executable, "-I", "-B"]
    argv += ["-m", "unittest", "discover", "-s", bundle] if discovery else [bundle / "test_equivalence.py"]
    environment = {"OTELEQ_WORKSPACE_PARENT": str(folder), "OTELEQ_SOURCE": str(source_path) if source_path else ""}
    command(argv, folder, name, int(stage == "different"), environment)
    workspace, attempts = check_suite(folder / (name + ".stdout"), stage, preflight=preflight)
    assert application_sources(source_path or bundle.parent) == before
    plan = json.loads((workspace / "plan.json").read_text())
    assert plan["source_manifest"] == before
    count = 5 if preflight else STAGES[stage][1]
    assert "Ran " + str(count) + " test" in (folder / (name + ".stderr")).read_text()
    write(folder / (name + ".checked.json"), {"workspace": str(workspace), "stage": stage,
        "source_manifest": before, "cases": count, "attempts": sorted(attempts)})
    return workspace, attempts


def reseal(bundle: Path, data: dict) -> None:
    write(bundle / "project.json", data)
    marker = json.loads((bundle / ".oteleq-owned.json").read_text())
    marker["project_sha256"] = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    write(bundle / ".oteleq-owned.json", marker)


def refusal_controls(cli: Path, provider: Path, folder: Path, bundle: Path, application: Path) -> int:
    """Bad retained context fails before any paired application attempt."""
    controls = folder / "controls"
    controls.mkdir()
    count = 0
    for name in ("missing-source", "missing-file", "extra-file", "changed-file", "linked-file", "changed-cli",
                 "changed-generator", "changed-provider", "empty-source"):
        selected = controls / name
        shutil.copytree(bundle, selected)
        environment = {"OTELEQ_SOURCE": str(application), "OTELEQ_WORKSPACE_PARENT": str(controls)}
        if name == "missing-source":
            environment["OTELEQ_SOURCE"] = ""
        elif name == "missing-file":
            (selected / "README.txt").unlink()
        elif name == "extra-file":
            (selected / "foreign.py").write_text("raise RuntimeError('foreign source')\n")
        elif name == "changed-file":
            (selected / "README.txt").write_text("changed\n")
        elif name == "linked-file":
            (selected / "README.txt").unlink()
            (selected / "README.txt").symlink_to(application / "python/app.py")
        elif name == "changed-cli":
            altered = controls / "changed-cli.bin"
            altered.write_bytes(cli.read_bytes() + b"changed")
            environment["OTELEQ_CLI"] = str(altered)
        elif name in ("changed-generator", "changed-provider"):
            data = json.loads((selected / "project.json").read_text())
            data["generator_sha256" if name == "changed-generator" else "artefacts"] = "0" * 64 if name == "changed-generator" else {}
            reseal(selected, data)
        else:
            empty = controls / "empty-application"
            empty.mkdir()
            environment["OTELEQ_SOURCE"] = str(empty)
        before = set(controls.rglob("typed-observation.json"))
        command([sys.executable, "-I", "-B", selected / "test_equivalence.py"], controls, name, 1, environment)
        assert set(controls.rglob("typed-observation.json")) == before == set()
        assert "Ran 1 test" in (controls / (name + ".stderr")).read_text()
        count += 1
    control_source = controls / "foreign-application"
    control_source.mkdir()
    (control_source / "app.py").write_text("def selected()->int:return 7\n")
    foreign = control_source / "equivalence-tests"
    shutil.copytree(bundle, foreign)
    (foreign / "test_equivalence.py").write_text("raise RuntimeError('foreign runner')\n")
    data = json.loads((foreign / "project.json").read_text())
    data["files_sha256"]["test_equivalence.py"] = digest(foreign / "test_equivalence.py")
    reseal(foreign, data)
    command([cli, "plan", "--source", control_source, "--otelc-root", provider,
        "--language", "python", "--workspace-parent", controls], controls, "resealed-foreign", 4)
    assert "not recognised" in (controls / "resealed-foreign.stderr").read_text()
    assert not list(controls.rglob("typed-observation.json"))
    return count + 1


def make_application(folder: Path) -> Path:
    """Retain one readable eight-language source fixture before any generated caller."""
    application = folder / "application"
    application.mkdir()
    for language in LANGUAGES:
        filename, text = source(language)
        if language == "python":
            text += "def current_text(value:str)->int:return len(value)\n"
        target = application / language / filename
        target.parent.mkdir()
        target.write_text(text)
    return application


def change_bodies(application: Path) -> None:
    """The changed literal return distinguishes fresh code from a stale snapshot."""
    for language in LANGUAGES:
        target = application / language / source(language)[0]
        text = target.read_text()
        assert text.count("start*100+end") == 1
        target.write_text(text.replace("start*100+end", "start*100+end+1000"))


def add_functions(application: Path) -> None:
    """Newly discovered zero-argument functions must become actual cases in every language."""
    for language in LANGUAGES:
        target = application / language / source(language)[0]
        text = target.read_text()
        extra = added_source(language)
        if language == "java":
            assert text.count("}\nclass Meter") == 1
            text = text.replace("}\nclass Meter", extra + "}\nclass Meter")
        else:
            text += extra
        target.write_text(text)


def full_routes(cli: Path, provider: Path, folder: Path, application: Path) -> tuple[Path, Path, set[str]]:
    _, bundle = prepare(cli, provider, folder, application)
    _, attempts = suite(bundle, folder, "initial", "initial")
    change_bodies(application)
    _, observed = suite(bundle, folder, "changed", "changed")
    assert attempts.isdisjoint(observed)
    attempts |= observed
    application = application.rename(folder / "relocated-application")
    bundle = application / bundle.name
    add_functions(application)
    workspace, observed = suite(bundle, folder, "added", "added", discovery=True)
    assert attempts.isdisjoint(observed)
    attempts |= observed
    external = folder / "external-tests"
    command([cli, "promote", "--workspace", workspace, "--source", application,
        "--destination", external, "--apply"], folder, "external-promote")
    active = '"quux.otelc" in (' + ','.join('sys.monitoring.get_tool(' + str(index) + ')' for index in range(6)) + ')'
    with (application / "python/app.py").open("a") as output:
        output.write("def current_probe()->int:return int(" + active + ")\n")
    _, observed = suite(external, folder, "different", "different", source_path=application)
    assert attempts.isdisjoint(observed)
    attempts |= observed
    assert len(attempts) == 916
    return application, external, attempts


def main() -> None:
    if sys.flags.optimize:
        raise ValueError("qualification requires enabled assertion checks")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    cli, provider, folder = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True), args.report_dir.resolve()
    assert not any(folder.is_relative_to(path) for path in (provider, Path(__file__).resolve().parents[1]))
    folder.mkdir(mode=0o700, exist_ok=False)
    os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli), PYTHONDONTWRITEBYTECODE="1", PYTHONOPTIMIZE="0")
    application = make_application(folder)
    preflight = folder / "preflight"
    preflight.mkdir()
    _, preflight_bundle = prepare(cli, provider, preflight, application, preflight=True)
    _, attempts = suite(preflight_bundle, preflight, "suite", "initial", preflight=True)
    command([cli, "clean", "--workspace", preflight_bundle], preflight, "clean")
    if args.preflight_only:
        write(folder / "qualification.json", {"status": "preflight-only", "actual_launches": len(attempts),
            "cli_sha256": digest(cli), "attempts": sorted(attempts)})
        return
    application, external, observed = full_routes(cli, provider, folder, application)
    assert attempts.isdisjoint(observed)
    attempts |= observed
    controls = refusal_controls(cli, provider, folder, external, application)
    assert len(attempts) == 936
    write(folder / "qualification.json", {"status": "complete", "claim": "equivalence over these tests and observations",
        "cli": str(cli), "provider": str(provider), "cli_sha256": digest(cli),
        "actual_launches": len(attempts), "prelaunch_refusals": controls,
        "stages": STAGES, "attempts": sorted(attempts)})


if __name__ == "__main__":
    main()
