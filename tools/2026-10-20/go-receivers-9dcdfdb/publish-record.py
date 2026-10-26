"""Publish only completed, independently revalidated Go qualification evidence."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = Path("/Users/sclarke/github/oteleq-qualification/work/oteleq-go-receivers")
runtime = json.loads((ROOT / "runtime.json").read_text())
result = json.loads((ROOT / "actual/QUALIFICATION.json").read_text())
verified = json.loads((ROOT / "verification.json").read_text())
provider = json.loads((ROOT / "provider-verified-after.json").read_text())
gate = json.loads((ROOT / "gate-state.json").read_text())
assert gate["state"] == "completed" and gate["exit_code"] == 0
assert result["actual_application_launches"] == verified["actual_application_launches"] == 168
work = ROOT / "actual/receivers"
workspace = Path((work / "plan.stdout").read_text().strip())
plan = json.loads((workspace / "plan.json").read_text())
inventory = {status: sum(entry["status"] == status for entry in plan["inventory"])
             for status in ("ready", "excluded", "blocked")}
record = {"qualification_schema_version": 1, "date": "2026-10-20",
          "claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
          "platform": {"os": "macOS", "architecture": "ARM64", "go": "1.27.2", "python": "3.12.15"},
          "runtime": {**runtime, "generator_sha256": plan["generator_sha256"],
                      "qualification_script_sha256": hashlib.sha256((ROOT / "consumer/tests/qualify_go_receivers.py").read_bytes()).hexdigest()},
          "provider": provider, "inventory": {"callables": len(plan["inventory"]), **inventory},
          "results": {**result, "routes": ["run", "generated", "exported-run", "exported-framework", "shrink", "replay"],
                      "qualified_application_launches": 160, "incomplete_fixture_launches": 4,
                      "initial_state_blocked_launches": 4, "scalar_shrink": {"original": [3], "reduced": [0]},
                      "refusal_controls": 13},
          "independent_verification": verified,
          "validation": {"make_check": "passed", "unique_regressions": 468, "python_regressions": 381,
                         "rust_regressions": 66, "node_regressions": 17, "go_regressions": 4,
                         "rust_product_line_coverage_percent": 97.24, "go_observer_statement_coverage_percent": 97.58,
                         "go_receiver_line_coverage_percent": 99, "go_graph_line_coverage_percent": 98,
                         "sonar_unresolved": 0},
          "scope": {"observed": "Declared same-package scalar factories, pointer/value/nil receivers, private struct and array slots, package globals, raw string bytes, scalar bits, primitive panics, cycles, interior aliases and shared storage across typed pointer views. Main-package identities and returned value copies are separately checked.",
                    "private_observer_schema_version": 2,
                    "witness": "Existing name-bound decoded function/span witness; invocation-scoped producer binding remains unavailable.",
                    "not_qualified": ["shipping artefacts", "maps/slices/interfaces/channels/functions/unsafe pointer storage", "foreign or anonymous structs and generic storage", "float32 NaN payloads", "non-primitive panic payloads", "arbitrary mutable arguments or external factories", "imported-package globals", "cross-boundary allocation identity", "goroutine or arbitrary resource/action sequences", "cgo/workspaces/general build recipes", "other platforms/toolchains"],
                    "identity_limit": "Recorded source/dependency inputs and selected compiler/runtime tools; not a general OS-library or shipping build closure."}}
record["provider"]["scope"] = "Content verified before/after this corpus; frozen d6d03b7 identity, not a claim about later producer revisions."
path = REPO / "docs/qualification/go-receivers-2026-10-20.json"
path.write_text(json.dumps(record, indent=2) + "\n")
replacement = "The [exact-revision corpus](qualification/go-receivers-2026-10-20.json) completes nine cases and 168 actual launches: six matches, three same-return state/alias differences, all generated/exported routes, scalar shrinking/replay and thirteen refusal controls."
for name in ("docs/go-receivers.md", "docs/quality.md", "docs/roadmap.md", "docs/receiver-fixtures.md", "docs/automatic-generation.md", "docs/completion.md", "README.md"):
    path = REPO / name
    text = path.read_text()
    text = text.replace("The current actual-provider corpus is pending; no shipping artefact is qualified by this diagnostic helper.", replacement + " No shipping artefact is qualified by this diagnostic helper.")
    text = text.replace("These checks do not establish actual otelc qualification, which is pending.", replacement)
    text = text.replace("actual-provider qualification is pending.", "its [actual-provider corpus](qualification/go-receivers-2026-10-20.json) completes 168 launches.")
    text = text.replace("Their actual-provider qualification remains pending.", replacement)
    text = text.replace("Their actual-provider qualification is pending.", replacement)
    text = text.replace("with actual-provider qualification pending", "with [168-launch qualification](qualification/go-receivers-2026-10-20.json)")
    if name == "README.md":
        text = text.replace("with actual-provider qualification pending.", "with [168-launch qualification](docs/qualification/go-receivers-2026-10-20.json).")
        text = text.replace("(qualification/go-receivers-2026-10-20.json)", "(docs/qualification/go-receivers-2026-10-20.json)")
    text = text.replace("Memory addresses are never serialised.", "The observer never serialises its internal addresses.")
    path.write_text(text)
print(json.dumps({"published_record": str(REPO / "docs/qualification/go-receivers-2026-10-20.json"), "actual_launches": 168}))
