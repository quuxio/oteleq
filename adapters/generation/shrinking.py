"""Reduce a qualified scalar counterexample without replacing its original evidence."""
import argparse
import copy
from contextlib import redirect_stdout
import glob
import io
from pathlib import Path
import shutil
import uuid

import domains
import harness


def shape(value: dict | None) -> dict | None:
    """Retain value representation, excluding changing content and local node IDs."""
    if value is None:
        return None
    result = {key: value[key] for key in ("kind", "type", "encoding", "signed") if key in value}
    if value.get("kind") == "integer":
        result["bits"] = value.get("bits")
    elif value.get("kind") == "float":
        result["width"] = len(value["bits"]) * 4
    return result


def outcome(observation: dict) -> dict:
    """Prevent a reduction from substituting another outcome or exception class."""
    if observation["gaps"]:
        raise ValueError("shrinking requires complete requested observations")
    value = observation["outcome"]
    root = "error" if value["kind"] == "error" else "result"
    graph = value["graph"]
    scalar = graph["roots"][root]
    summary = shape(scalar)
    if scalar["kind"] == "reference":
        summary["type"] = next(node["type"] for node in graph["nodes"] if node["id"] == scalar["node_id"])
    return {"kind": value["kind"], "category": value.get("category"), "root": summary}


def fingerprint(result: dict, bundle: dict) -> dict | None:
    """Only stable, fully qualified differences have a preservable failure signature."""
    if result["exit_code"] != 1:
        return None
    report = result["comparison"]["cases"][0]
    execution = report["execution"]
    if (report["verdict"] != "different_observed" or report["reasons"] or execution["reasons"]
            or execution["verdict"] not in ("different_observed", "equivalent_observed")):
        return None
    differences = None
    for pair in report["pairs"]:
        compared = pair["comparison"]
        if (compared["verdict"] not in ("different_observed", "equivalent_observed")
                or compared["reasons"] or compared["initial_differences"]):
            return None
        current = [{"path": item["path"], "reason": item["reason"],
                    "baseline": shape(item["baseline"]), "instrumented_on": shape(item["instrumented_on"])}
                   for item in compared["differences"]]
        if differences is not None and differences != current:
            return None
        differences = current
    observations = bundle["cases"][0]
    return {"channels": [item["path"] for item in execution["differences"]], "typed": differences,
            "outcomes": {lane: outcome(observations[lane][0]["observation"])
                         for lane in ("baseline", "instrumented_on")}}


def candidates(entry: dict, current: list):
    """Coerce legal candidates into the target representation before checking progress."""
    declared = entry["input_domains"]
    for index, (value, domain) in enumerate(zip(current, declared)):
        width = harness.float_width(harness.scalar_type(entry["parameters"][index]), entry["language"])
        for smaller in domains.reductions(value, domain, width=width):
            requested = list(current)
            requested[index] = smaller
            if not domains.contains(smaller, domain):
                continue
            try:
                concrete = harness.concrete_arguments(entry, requested)
                domains.arguments(concrete, declared)
            except ValueError:
                continue
            if domains.rank(concrete[index], domain) < domains.rank(value, domain):
                yield concrete


def invoke(workflow, name: str, args: argparse.Namespace, log: Path) -> int:
    """Keep nested CLI summaries in evidence; the outer command prints one result."""
    output = io.StringIO()
    with redirect_stdout(output):
        code = getattr(workflow, name)(args)
    log.write_text(output.getvalue())
    return code


def evaluate(workflow, workspace: Path, destination: Path) -> tuple[dict, dict | None]:
    """Use the ordinary sealed executor, preserving all repeats and witness guards."""
    invoke(workflow, "run", argparse.Namespace(command="run", workspace=workspace, report_dir=destination),
           destination.parent / (destination.name + ".stdout"))
    report = workflow.read(destination / "report.json")
    if len(report["cases"]) != 1:
        raise ValueError("shrink executor requires exactly one concrete target case")
    result = report["cases"][0]
    signature = None
    if result["exit_code"] == 1:
        bundle = workflow.read(destination / result["case"] / workflow.TYPED_BUNDLE)
        try:
            signature = fingerprint(result, bundle)
        except ValueError:
            signature = None
    return result, signature


def derived_data(workflow, original: dict, entry: dict, case: dict) -> dict:
    """Retain all inventory rows and explicitly scope the new suite to one target."""
    data = copy.deepcopy(original)
    for item in data["inventory"]:
        if item["id"] == entry["id"]:
            item["input_cases"] = [case["arguments"]]
        else:
            item.update(status="excluded", reason="outside the explicitly selected shrink target")
    config = data["configuration"]
    config["functions"] = {"include": [glob.escape(entry["otelc_function"])], "exclude": []}
    config["fixtures"] = [{"function": glob.escape(entry["otelc_function"]), "source": glob.escape(entry["path"]), "language": entry["language"],
                            "cases": [case["arguments"]], "domains": entry["input_domains"],
                            "expected_baseline": entry["expected_baseline"]}]
    if "receiver_configuration" in entry:
        config["fixtures"][0]["receiver"] = copy.deepcopy(entry["receiver_configuration"])
    if "sequence_configuration" in entry:
        config["fixtures"][0]["sequence"] = copy.deepcopy(entry["sequence_configuration"])
    data["configuration_sha256"] = workflow.identity(config)
    data["derivation"] = {"kind": "scalar-shrink-v1", "parent_plan_sha256": workflow.identity(original),
                          "original_case": case, "original_configuration_sha256": original["configuration_sha256"]}
    return data


def reset(workflow, workspace: Path, data: dict, arguments: list) -> None:
    """Replace only verified generator-owned trial inputs; every run keeps a plan copy."""
    if (workspace / workflow.PLAN_FILE).exists():
        workflow.load_workspace(workspace, generated=True)
        shutil.rmtree(workspace / "tests")
        (workspace / workflow.GENERATED_MANIFEST).unlink()
    for entry in data["inventory"]:
        if entry["status"] == "ready":
            entry["input_cases"] = [arguments]
    data["configuration"]["fixtures"][0]["cases"] = [arguments]
    data["configuration_sha256"] = workflow.identity(data["configuration"])
    workflow.write(workspace / workflow.PLAN_FILE, data)
    marker = workflow.read(workspace / workflow.OWNED_MARKER)
    marker["plan_sha256"] = workflow.identity(data)
    workflow.write(workspace / workflow.OWNED_MARKER, marker)
    logs = workspace / "runs"
    logs.mkdir(exist_ok=True)
    invoke(workflow, "generate", argparse.Namespace(workspace=workspace), logs / ("generation-" + uuid.uuid4().hex + ".stdout"))


def retained_evaluate(workflow, workspace: Path, destination: Path) -> tuple[dict, dict | None]:
    """Retain the exact trial plan even when the candidate suite is later regenerated."""
    result, signature = evaluate(workflow, workspace, destination)
    shutil.copyfile(workspace / workflow.PLAN_FILE, destination / "trial-plan.json")
    shutil.copyfile(workspace / workflow.GENERATED_MANIFEST, destination / "trial-generated-manifest.json")
    return result, signature


def fresh_candidates(entry: dict, current: list, seen: set[str]):
    """Filter already evaluated concrete inputs before consuming trial budget."""
    for candidate in candidates(entry, current):
        token = domains.key(candidate)
        if token not in seen:
            yield token, candidate


def incomplete_candidate(result: dict, signature: dict | None) -> bool:
    """A blocked or unqualified experiment cannot support a minimality claim."""
    return result["exit_code"] in (2, 3, 4) or result["exit_code"] == 1 and signature is None


def search(workflow, workspace: Path, data: dict, entry: dict, original: list,
           wanted: dict, destination: Path, budget: int) -> tuple[list, list, str]:
    """Greedily restart deterministic rules after each accepted reduction."""
    current, trials, seen = original, [], {domains.key(original)}
    incomplete = False
    while True:
        accepted = False
        for token, candidate in fresh_candidates(entry, current, seen):
            if len(trials) >= budget:
                return current, trials, "budget_limited"
            seen.add(token)
            reset(workflow, workspace, data, candidate)
            folder = destination / ("trial-" + str(len(trials)).zfill(4))
            result, signature = retained_evaluate(workflow, workspace, folder)
            same = signature == wanted
            gap = incomplete_candidate(result, signature)
            incomplete |= gap
            trials.append({"arguments": candidate, "accepted": same, "incomplete": gap, "exit_code": result["exit_code"],
                           "report": str(folder / "report.json")})
            workflow.write(destination / "partial-shrink.json", trials)
            if same:
                current, accepted = candidate, True
                break
        if not accepted:
            return current, trials, "incomplete_candidates" if incomplete else "candidate_rule_minimal"


def run(args: argparse.Namespace, workflow) -> int:
    """Reconfirm the original, search, then seal and reconfirm a retained replay suite."""
    original_workspace, original = workflow.load_workspace(args.workspace, generated=True)
    cases = workflow.read(original_workspace / "tests/corpus.json")
    case = next((item for item in cases if item["id"] == args.case), None)
    if case is None:
        raise ValueError("unknown case ID")
    entry = next(item for item in original["inventory"] if item["id"] == case["function_id"])
    if "input_domains" not in entry:
        raise ValueError("shrinking requires explicit fixture domains; create a new configured plan")
    domains.arguments(case["arguments"], entry["input_domains"])
    destination = workflow.source_outside(args.report_dir, original_workspace, Path(original["source"]), Path(original["otelc_root"]))
    destination.mkdir(mode=0o700, exist_ok=False)
    shutil.copyfile(original_workspace / workflow.PLAN_FILE, destination / "parent-plan.json")
    replay = argparse.Namespace(command="replay", workspace=original_workspace, case=case["id"])
    output = io.StringIO()
    with redirect_stdout(output):
        workflow.run(replay)
    summary = workflow.capture.strict_json(output.getvalue())
    original_report = Path(summary["report"])
    shutil.copytree(original_report.parent, destination / "original")
    result = workflow.read(original_report)["cases"][0]
    bundle = workflow.read(original_report.parent / case["id"] / workflow.TYPED_BUNDLE) if result["exit_code"] == 1 else {}
    wanted = fingerprint(result, bundle)
    if wanted is None:
        raise ValueError("the original case is not a stable, fully qualified observed difference; retained original evidence")
    workspace = destination / "workspace"
    workspace.mkdir(mode=0o700)
    shutil.copytree(original_workspace / "snapshot", workspace / "snapshot")
    workflow.write(workspace / workflow.OWNED_MARKER, {"schema_version": workflow.VERSION, "id": uuid.uuid4().hex})
    data = derived_data(workflow, original, entry, case)
    best, trials, status = search(workflow, workspace, data, entry, case["arguments"], wanted, destination, args.trials)
    reset(workflow, workspace, data, best)
    result, confirmed = retained_evaluate(workflow, workspace, destination / "confirmation")
    if confirmed != wanted:
        raise ValueError("reduced counterexample failed final confirmation; retain all shrink evidence")
    workflow.load_workspace(original_workspace, generated=True)
    workflow.load_workspace(workspace, generated=True)
    report = {"schema_version": 1, "claim": "equivalence over these tests and observations",
              "artefact_class": "diagnostic", "exit_code": 1, "status": status, "trials": trials,
              "incomplete_trials": sum(trial["incomplete"] for trial in trials),
              "original_arguments": case["arguments"], "reduced_arguments": best, "failure_signature": wanted,
              "parent_workspace": str(original_workspace), "workspace": str(workspace),
              "confirmation": str(destination / "confirmation/report.json"), "source_preserved": True,
              "scope": "declared independent scalar domains and deterministic candidate rules; no global minimum, relational preconditions, objects or action sequences"}
    workflow.write(destination / "shrink.json", report)
    print(workflow.json.dumps({"report": str(destination / "shrink.json"), "workspace": str(workspace),
                               "exit_code": 1, "trials": len(trials), "status": status}), flush=True)
    return 1
