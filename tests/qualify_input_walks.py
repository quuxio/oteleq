"""Qualify strict input enumeration and existing eight-language execution."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys

from qualify_generation import command
from qualify_returns import LANGUAGES, source


@contextmanager
def unreadable(directory: Path):
    """Restore the exact original mode even when a qualification assertion fails."""
    mode = stat.S_IMODE(directory.stat().st_mode)
    directory.chmod(0)
    try:
        try:
            list(directory.iterdir())
        except PermissionError:
            pass
        else:
            raise ValueError("qualification requires a real directory permission denial")
        yield
    finally:
        directory.chmod(mode)


@contextmanager
def hidden_sources(parent: Path):
    """Add only owned fixture files and remove them after restoring access."""
    private = parent / "unreadable-inputs"
    private.mkdir()
    try:
        for language in LANGUAGES:
            name, text = source(language)
            target = private / language / name
            target.parent.mkdir()
            target.write_text(text)
        with unreadable(private):
            yield private
    finally:
        shutil.rmtree(private)


def plan_control(cli: Path, provider: Path, application: Path, config: Path, folder: Path,
                 name: str, language: str, *, expected: int) -> dict | None:
    """Keep every planning result without executing a selected application target."""
    text = command([cli, "plan", "--source", application, "--otelc-root", provider,
                    "--workspace-parent", folder, "--config", config, "--language", language],
                   folder, name, expected=expected)
    if expected:
        assert "Permission denied" in (folder / (name + ".stderr")).read_text()
        return None
    return json.loads((Path(text) / "plan.json").read_text())


def refuse_replays(cli: Path, workspace: Path, folder: Path, prefix: str) -> int:
    """All eight language cases must stop before creating another attempt."""
    cases = json.loads((workspace / "tests/corpus.json").read_text())
    assert len(cases) == 8
    for index, case in enumerate(cases):
        name = prefix + "-" + str(index)
        command([cli, "replay", "--workspace", workspace, "--case", case["id"]], folder, name, expected=4)
        assert "Permission denied" in (folder / (name + ".stderr")).read_text()
    return len(cases)


def source_controls(cli: Path, before: Path, provider: Path, application: Path,
                    workspace: Path, config: Path, folder: Path, original: dict) -> tuple[int, int]:
    """Demonstrate old partial plans, then refuse planning and frozen replay."""
    with hidden_sources(application):
        for language in LANGUAGES:
            data = plan_control(before, provider, application, config, folder,
                                "before-source-" + language, language, expected=0)
            assert data["source_manifest"] == original
            assert len([entry for entry in data["inventory"] if entry["status"] == "ready"]) == 1
            plan_control(cli, provider, application, config, folder,
                         "after-source-" + language, language, expected=4)
        replays = refuse_replays(cli, workspace, folder, "source-replay")
    return len(LANGUAGES) + replays, len(LANGUAGES)


def owned_controls(cli: Path, before: Path, provider: Path, application: Path,
                   config: Path, folder: Path, original: dict) -> tuple[int, int]:
    """An inaccessible addition cannot certify a retained bundle as unchanged."""
    with hidden_sources(application / "retained/snapshot"):
        for language in LANGUAGES:
            data = plan_control(before, provider, application, config, folder,
                                "before-owned-" + language, language, expected=0)
            assert data["source_manifest"] == original
            plan_control(cli, provider, application, config, folder,
                         "after-owned-" + language, language, expected=4)
    return len(LANGUAGES), len(LANGUAGES)


def generated_java_control(cli: Path, before: Path, provider: Path, application: Path,
                           config: Path, folder: Path) -> tuple[int, int]:
    """Explicit generated roots must not silently omit a third Java source unit."""
    build = application / "build"
    generated = build / "generated"
    hidden = generated / "private"
    hidden.mkdir(parents=True)
    (generated / "Readable.java").write_text("class Readable {static int selected_match(int n){return n+4;}}\n")
    (hidden / "Hidden.java").write_text("class Hidden {static int selected_match(int n){return n+4;}}\n")
    policy = folder / "generated-java.toml"
    policy.write_text(config.read_text().replace('source_roots=["."]', 'source_roots=["java","build/generated"]'))
    try:
        with unreadable(hidden):
            data = plan_control(before, provider, application, policy, folder, "before-java-generated", "java", expected=0)
            assert data["java_context"]["source_units"] == ["build/generated/Readable.java", "java/App.java"]
            plan_control(cli, provider, application, policy, folder, "after-java-generated", "java", expected=4)
    finally:
        shutil.rmtree(build)
    return 1, 1


def main() -> None:
    """Execute the full positive corpus and retain all filesystem refusal controls."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--before-cli", type=Path, required=True)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    args = parser.parse_args()
    cli, before, provider = (getattr(args, name).resolve(strict=True) for name in ("cli", "before_cli", "otelc_root"))
    folder = args.report_dir.resolve()
    folder.mkdir(mode=0o700, exist_ok=False)
    os.environ.update(OTELEQ_CLI=str(cli), OTELEQ_PYTHON=sys.executable, PYTHONDONTWRITEBYTECODE="1")
    positive = folder / "positive"
    command([sys.executable, Path(__file__).with_name("qualify_retained_source.py"), "--cli", cli,
             "--otelc-root", provider, "--report-dir", positive], folder, "positive")
    receipt = json.loads((positive / "qualification.json").read_text())
    assert receipt["actual_application_launches"] == 136
    application = positive / "application"
    workspace = Path((positive / "replan-plan.stdout").read_text().strip())
    config = positive / "policy.toml"
    original = json.loads((workspace / "plan.json").read_text())["source_manifest"]
    assert len(original) == 8
    recorded_attempts = set(positive.rglob("typed-observation.json"))
    assert len(recorded_attempts) == 136
    controls, reproduced = source_controls(cli, before, provider, application, workspace, config, folder, original)
    added_controls, added_reproductions = owned_controls(cli, before, provider, application, config, folder, original)
    controls += added_controls
    reproduced += added_reproductions
    with hidden_sources(workspace / "snapshot"):
        controls += refuse_replays(cli, workspace, folder, "snapshot-replay")
    added_controls, added_reproductions = generated_java_control(cli, before, provider, application, config, folder)
    controls += added_controls
    reproduced += added_reproductions
    assert controls == 33 and reproduced == 17
    assert set(positive.rglob("typed-observation.json")) == recorded_attempts
    for name, expected in original.items():
        assert hashlib.sha256((application / name).read_bytes()).hexdigest() == expected
    command([cli, "export-tests", "--workspace", workspace, "--destination", folder / "final-identity-check"],
            folder, "final-identity-check")
    result = {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
              "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
              "before_cli_sha256": hashlib.sha256(before.read_bytes()).hexdigest(),
              "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "languages": list(LANGUAGES), "actual_application_launches": 136,
              "before_successful_partial_plans": reproduced, "after_prelaunch_refusal_controls": controls,
              "application_launches_from_refusal_controls": 0, "full_graph_and_witness_positive_corpus": True,
              "source_and_owned_snapshot_changes_restored": True, "source_preserved": True,
              "limits": "Recorded POSIX permission semantics and frozen legacy provider only; not shipping qualification."}
    (folder / "qualification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
