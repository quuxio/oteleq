"""Independently qualify fixed original-source Rust producer workloads."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

from test_capture_rust_semantics import FIXTURES, alias_fixture, semantic_oracle
from qualify_generation import command as run_command

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
import otelc_capture as capture
import otelc_rust_build as compiler_build


SEMANTIC_NAMES = {"semantics.selected_column": 1, "semantics.selected_caller": 1,
                  "semantics.selected_closure": 1, "semantics.selected_future": 2,
                  "semantics.selected_panic": 1}
ALIAS_NAMES = {"first.shared.selected": 1, "second.shared.selected": 1}
ASYNC_UNSUPPORTED = "async compiler bodies require future-completion qualification"


def runtime_witness(bodies: list, runtime: dict, names: dict, service: str, decoder, kind: str) -> dict:
    """Cancellation and panic have distinct, independently required evidence."""
    spec = {"functions": names, "trees": sum(names.values()), "errors": 2 if kind == "semantics" else 0}
    witness = capture.witness(bodies, runtime, spec, service, decoder, "rust")
    if kind == "semantics":
        assert runtime["future_observers"] == {"admission_exhausted": False, "pending": 0}
        assert runtime["functions"]["semantics.selected_future"] == {"count": 2, "cancellations": 1, "unwinds": 0}
        assert runtime["functions"]["semantics.selected_panic"] == {"count": 1, "cancellations": 0, "unwinds": 1}
        spans = [span for path, body in bodies if path == capture.TRACE_PATH
                 for span in capture.service_spans(decoder.FromString(body), service)]
        cancelled = [span for span in spans if any(attribute.key == "otelc.cancelled" and attribute.value.bool_value
                                                   for attribute in span.attributes)]
        assert len(cancelled) == 1 and cancelled[0].name == "semantics.selected_future"
        assert cancelled[0].status.code == 2 and cancelled[0].status.message == "cancelled"
        panic = [span for span in spans if span.name == "semantics.selected_panic"]
        assert len(panic) == 1 and panic[0].status.code == 2 and panic[0].status.message == "escaping unwind"
    return witness


def verify_bundle(root: Path, project: Path, source: Path, bundle: Path, tools: dict,
                  environment: dict, names: dict[str, int], sources: dict[str, str]) -> dict:
    """Validate this fixed producer fixture without declaring a generated adapter."""
    metadata = capture.rust_metadata(bundle)
    assert metadata["schema_version"] == 3 and metadata["backend"] == "compiler"
    expected = {"executable_sha256": capture.file_digest(bundle / "application"),
                "source_sha256": capture.file_digest(source),
                "plan_sha256": capture.file_digest(bundle / "plan.json"),
                "sdk_sha256": capture.file_digest(root / "target/debug/libquux_otelc_rust.rlib"),
                "adapter_sha256": capture.file_digest(root / "target/debug/otelc-rust-adapter")}
    assert all(metadata[key] == value for key, value in expected.items())
    assert metadata["source"] == str(source.resolve()) and metadata["source_root"] == str(project)
    descriptor, assets = compiler_build.profile(root, tools)
    assert (bundle / "profile.json").read_bytes() == (root / compiler_build.PROFILE_FILENAME).read_bytes()
    evidence = {"profile_sha256": capture.file_digest(bundle / "profile.json"),
                "driver_sha256": capture.file_digest(assets["driver"]),
                "request_sha256": capture.file_digest(bundle / "compiler-request.json"),
                "inventory_sha256": capture.file_digest(bundle / "inventory.json")}
    assert metadata["compiler_driver"] == evidence
    compiler = capture.rust_compiler(metadata, tools)
    discovery = compiler_build.recipe(compiler, source, project, assets, environment)
    plan = capture.build_document(bundle / "plan.json")
    assert plan["backend"] == "compiler" and plan["language"] == "rust"
    assert plan["execution_available"] is True and plan["unavailable"] == []
    assert plan["sources"] == {"include": ["**"], "exclude": []}
    assert plan["functions"] == {"include": list(names), "exclude": []}
    request = capture.build_document(bundle / "compiler-request.json", limit=8 * 1024 * 1024)
    inventory = capture.build_document(bundle / "inventory.json")
    assert set(request) == compiler_build.REQUEST_FIELDS and type(request["schema_version"]) is int and request["schema_version"] == 1
    assert request["root"] == str(project) and request["entry"] == str(source)
    assert request["policy"] == {key: plan[key] for key in compiler_build.POLICY_FIELDS}
    assert request["protected_source_roots"] == descriptor["protected_source_roots"]
    assert request["sources"] == inventory["sources"] == sources
    assert request["discovery_argv"] == inventory["discovery_argv"] == discovery
    assert set(inventory) == {"schema_version", "functions", "sources", "discovery_argv"}
    assert type(inventory["schema_version"]) is int and inventory["schema_version"] == 3
    assert type(inventory["functions"]) is list and len(inventory["functions"]) <= 65536
    assert all(type(row["selected"]) is bool and type(row["startup"]) is bool for row in inventory["functions"])
    capture.rust_frontend_rows(inventory)
    selected = [row for row in inventory["functions"] if row["selected"]]
    startup = [row for row in inventory["functions"] if row["startup"]]
    assert len(selected) == len(names) and {row["name"] for row in selected} == set(names)
    assert len(startup) == 1 and startup[0]["name"] == source.stem + ".main"
    for row in (*selected, *startup):
        assert type(row["selected"]) is bool and type(row["startup"]) is bool
        assert not row["unsupported"] and row["emitted"] is True
        assert row["compiled_symbol"] and row["compiler_expansion"] is False
        assert row["file"] in sources
        original = {key: value for key, value in row.items() if key not in compiler_build.INSTANCE_FIELDS}
        matches = [item for item in request["declarations"] if item["name"] == row["name"]]
        assert len(matches) == 1
        declared = dict(matches[0])
        if row["name"] in ("semantics.selected_future", "semantics.selected_panic"):
            assert declared["unsupported"] == ASYNC_UNSUPPORTED
            declared["unsupported"] = ""
        assert original == declared
    return {**expected, "compiler_driver": evidence, "compiler": compiler,
            "selected_functions": sorted(names), "loaded_sources": sources}


def attempt(provider: Path, destination: Path, kind: str, lane: str, repeat: int, decoder) -> tuple[dict, dict]:
    folder = destination / (lane + "-" + str(repeat))
    folder.mkdir()
    project = folder / "project"
    project.mkdir()
    if kind == "semantics":
        source = project / "semantics.rs"
        shutil.copyfile(FIXTURES / "rust_compiler_semantics.rs", source)
        oracle, names = semantic_oracle(source.read_text()), SEMANTIC_NAMES
        files = [source]
    else:
        source, oracle = alias_fixture(project)
        names = ALIAS_NAMES
        files = [source, project / "shared.rs", project / "first/shared.rs", project / "second/shared.rs"]
    snapshots = {str(path): capture.file_digest(path) for path in files}
    tools = capture.selected_tools(provider, "rust")
    identities = capture.artefacts(provider, "rust", tools)
    service = "oteleq-rust-semantic-" + uuid.uuid4().hex
    environment = capture.environment(project, tools, service, provider)
    report = folder / "runtime.json"
    environment["OTELC_REPORT_PATH"] = str(report)
    with capture.receiver() as (endpoint, bodies, errors):
        policy = project / "policy.toml"
        policy.write_text('schema_version=2\nlanguages=["rust"]\n[sources]\ninclude=["**"]\n'
                          + '[functions]\ninclude=' + json.dumps(list(names))
                          + '\n[adapters.rust]\nbackend="compiler"\n[traces]\nenabled=true\nroot_sample_ratio=1.0\n'
                          + '[export]\ninterval_ms=50\nendpoint=' + json.dumps(endpoint) + '\n')
        if lane == "baseline":
            binary = folder / "plain"
            capture.build([tools["rustc"], *capture.RUST_BASELINE_FLAGS, source.name, "-o", binary],
                          project, environment, folder / "build.log")
            command = [binary]
            provenance = {"application_sha256": capture.file_digest(binary),
                          "baseline_flags": list(capture.RUST_BASELINE_FLAGS)}
        else:
            bundle = folder / "bundle"
            prefix = [provider / capture.OTELC_CLI_PATH, "--config", policy, "--language", "rust"]
            capture.build(prefix + ["rust", "--build", source.name, "--output-dir", bundle],
                          project, environment, folder / "build.log")
            provenance = verify_bundle(provider, project, source, bundle, tools, environment, names, snapshots)
            command = prefix + ["rust", "--run", bundle]
        result = capture.execute(command, project, environment)
    capture.retain_http(folder, bodies, errors)
    for channel in ("stdout", "stderr"):
        (folder / channel).write_bytes(getattr(result, channel))
    (folder / "command.json").write_text(json.dumps([str(item) for item in command], indent=2) + "\n")
    (folder / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    assert result.returncode == 0 and not result.stderr and json.loads(result.stdout) == oracle
    assert not errors and all(capture.file_digest(Path(path)) == digest for path, digest in snapshots.items())
    if kind == "aliases":
        assert (project / "shared.rs").stat().st_mode & 0o777 == 0o444
        assert all(os.readlink(project / name / "shared.rs") == "../shared.rs" for name in ("first", "second"))
    capture.stable(provider, "rust", tools, identities)
    witness = None
    if lane == "instrumented_on":
        witness = runtime_witness(bodies, capture.build_document(report), names, service, decoder, kind)
    else:
        assert not bodies and not report.exists()
    observed = {"termination": {"kind": "exit", "code": 0},
                "source_sha256_before": capture.file_digest(source), "source_sha256_after": capture.file_digest(source),
                "channels": {"stdout": list(result.stdout), "stderr": []},
                "capture_complete": True, "witness": witness}
    (folder / "attempt.json").write_text(json.dumps(observed, indent=2) + "\n")
    return observed, oracle


def comparison_bundle(folder: Path, kind: str, attempts: dict, oracle: dict) -> dict:
    """Expose fixed observations to the real byte-channel comparator."""
    names = SEMANTIC_NAMES if kind == "semantics" else ALIAS_NAMES
    source = "semantics.rs" if kind == "semantics" else "main.rs"
    source_hash = capture.file_digest(folder / "baseline-0/project" / source)
    corpus_hash = capture.digest(json.dumps({"kind": kind, "oracle": oracle, "functions": names}, sort_keys=True).encode())
    variants = {lane: capture.digest(b"".join((folder / (lane + "-" + str(index)) / "provenance.json").read_bytes()
                                              for index in range(2))) for lane in attempts}
    scope = {"language": "rust", "artefact_class": "diagnostic", "source_sha256": source_hash,
             "baseline_artefact_sha256": variants["baseline"], "instrumented_artefact_sha256": variants["instrumented_on"],
             "policy_sha256": corpus_hash, "observer": "fixed Rust semantic producer observer; qualifier hash retained",
             "channels": ["stdout", "stderr"],
             "gaps": ["fixed trusted workload; not a general generated async/module adapter",
                      "application-owned JSON observations; no arbitrary heap-state coverage",
                      "diagnostic build provenance; not shipping-artefact evidence",
                      "compiler sysroot and OS libraries outside content identity",
                      "name-bound telemetry; invocation witness API unavailable"]}
    case = {"case_id": "rust-" + kind, "corpus_sha256": corpus_hash,
            "expected_functions": names, "expected_spans": sum(names.values()), **attempts}
    return {"workload_schema_version": 1, "scope": scope, "cases": [case]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--workload", choices=("semantics", "aliases"), action="append")
    args = parser.parse_args()
    provider, destination = args.otelc_root.resolve(strict=True), args.report_dir.resolve()
    cli = args.cli.resolve(strict=True)
    if any(destination.is_relative_to(path) for path in (provider, Path(__file__).resolve().parents[1])):
        parser.error("report directory must be new and outside both repositories")
    if sys.flags.optimize:
        parser.error("qualification requires assertions")
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    destination.mkdir(mode=0o700, exist_ok=False)
    kinds = list(dict.fromkeys(args.workload or ("semantics", "aliases")))
    for kind in kinds:
        folder = destination / kind
        folder.mkdir()
        case = {"baseline": [], "instrumented_on": []}
        oracle = None
        for lane in case:
            for repeat in range(2):
                observed, oracle = attempt(provider, folder, kind, lane, repeat, ExportTraceServiceRequest)
                case[lane].append(observed)
        (folder / "observations.json").write_text(json.dumps({"oracle": oracle, "case": case}, indent=2) + "\n")
        bundle = folder / "bundle.json"
        bundle.write_text(json.dumps(comparison_bundle(folder, kind, case, oracle), indent=2) + "\n")
        run_command([cli, "compare-workload", bundle], folder, "comparison")
        print(json.dumps({"completed": kind, "actual_launches": 4, "oracle": oracle}), flush=True)
    result = {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
              "scope": "fixed independent Rust producer workloads; no general generated async/module adapter claim",
              "workloads": kinds, "actual_application_launches": 4 * len(kinds), "source_preserved": True,
              "qualifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (destination / "qualification.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
