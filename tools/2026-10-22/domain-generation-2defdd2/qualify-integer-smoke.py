"""Actual eight-language smoke for domain-only fixtures; integer scope only."""
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path("/Users/sclarke/github/oteleq-qualification/2026-10-22/domain-generation-2defdd2")
SOURCE = Path("/Users/sclarke/github/oteleq-qualification/work/oteleq-domain-inputs")
sys.path[:0] = [str(SOURCE / name) for name in ("tests", "adapters/generation", "examples")]
from node_project_oracle import number, object_node
from qualify_generation import command
from qualify_returns import LANGUAGES, scalar, source

CLI = ROOT / "quux-oteleq"
PROVIDER = Path("/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/provider")
folder = ROOT / "integer-smoke"
folder.mkdir(mode=0o700, exist_ok=False)
application = folder / "application"
application.mkdir()
policy = 'schema_version=1\n[generation]\nseed=123\ncases_per_function=3\n[functions]\ninclude=["*selected_match*"]\n'
for language in LANGUAGES:
    name, text = source(language)
    target = application / language / name
    target.parent.mkdir()
    target.write_text(text)
    policy += ('\n[[fixtures]]\nlanguage=' + json.dumps(language)
               + '\nfunction="*selected_match*"\ndomains=[{kind="integer",minimum=7,maximum=9}]\n')
config = folder / "policy.toml"
config.write_text(policy)
os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(CLI), PYTHONDONTWRITEBYTECODE="1")
workspace = Path(command([CLI, "plan", "--source", application, "--otelc-root", PROVIDER,
    "--workspace-parent", folder, "--config", config], folder, "plan"))
data = json.loads((workspace / "plan.json").read_text())
ready = [row for row in data["inventory"] if row["status"] == "ready"]
assert len(ready) == 8 and not any(row["status"] == "blocked" for row in data["inventory"])
assert len(data["source_manifest"]) == 8
assert all("cases" not in row for row in data["configuration"]["fixtures"])
assert all(row["input_cases"] == [[7], [9], [8]] for row in ready)
command([CLI, "generate", "--workspace", workspace], folder, "generate")
corpus = json.loads((workspace / "tests/corpus.json").read_text())
assert len(corpus) == 24 and all(case["arguments_requested"] in ([7], [9], [8]) for case in corpus)
command([CLI, "run", "--workspace", workspace, "--report-dir", folder / "comparison"], folder, "run", timeout=1800)
report = json.loads((folder / "comparison/report.json").read_text())
assert report["source_preserved"] and report["exit_code"] == 0 and not report["blocked"] and len(report["cases"]) == 24
inventory = {row["otelc_function"]: row for row in report["inventory"]}
attempts = set()
for case in report["cases"]:
    row = inventory[case["function"]]
    language = row["language"]
    value = (7, 9, 8)[int(case["case"].rsplit("-", 1)[1])]
    assert case["arguments"] == [value] and case["exit_code"] == 0
    graph = {"roots": {}, "nodes": []}
    if language == "python":
        graph = {"roots": {"arguments": {"kind": "reference", "node_id": "n0"}},
                 "nodes": [{"id": "n0", "type": "python.builtins.list", "fields": {"item:0": scalar(language, value)}}]}
    if language in ("javascript", "typescript"):
        graph = {"roots": {"arguments": {"kind": "reference", "node_id": "n0"}},
                 "nodes": [object_node(language, "n0", "ecmascript.array.prototype:Array",
                            {"0": number(language, value), "length": number(language, 1)}, array=True)]}
    result = {"roots": {**graph["roots"], "result": scalar(language, value + 4)}, "nodes": graph["nodes"]}
    parent = folder / "comparison" / case["case"]
    paired = json.loads((parent / "typed-bundle.json").read_text())["cases"][0]
    for lane in ("baseline", "instrumented_on"):
        assert len(paired[lane]) == 2
        for index, attempt in enumerate(paired[lane]):
            observed, execution = attempt["observation"], attempt["execution"]
            assert observed["fixture"] == {"status": "ready"} and not observed["gaps"]
            assert observed["before"] == observed["after"] == graph
            assert observed["outcome"] == {"kind": "return", "graph": result}
            assert execution["capture_complete"] and execution["termination"] == {"kind": "exit", "code": 0}
            assert execution["channels"] == {"stdout": [], "stderr": []}
            witness = execution["witness"]
            if lane == "instrumented_on":
                assert witness["functions"] == {row["otelc_function"]: 1}
                assert witness["spans"] == 1 and witness["pending"] == 0 and not any(witness["losses"].values())
            else:
                assert witness is None
            actual = parent / (lane + "-" + str(index))
            assert json.loads((actual / "typed-observation.json").read_text()) == observed
            assert (actual / "stdout").read_bytes() == (actual / "stderr").read_bytes() == b""
            attempts.add(str(actual.resolve()))
assert len(attempts) == 96
for name, expected in data["source_manifest"].items():
    assert hashlib.sha256((application / name).read_bytes()).hexdigest() == expected
summary = {"scope": "integer domain generation, direct route only",
           "claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
           "runtime_revision": "2defdd260c0664bf65e47ca2af693be8d21d8525",
           "cli_sha256": hashlib.sha256(CLI.read_bytes()).hexdigest(),
           "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           "languages": list(LANGUAGES), "cases": 24, "actual_application_launches": 96,
           "actual_attempt_directories": sorted(attempts), "complete_literal_graph_oracles": True,
           "source_preserved": True, "additional_types_and_retained_routes": "not qualified by this smoke"}
(folder / "qualification.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps({key: value for key, value in summary.items() if key != "actual_attempt_directories"}), flush=True)

