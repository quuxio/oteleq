"""Extract repeated qualification mechanics; keep each language's independent oracle."""
import ast
from pathlib import Path

ROOT=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-python-call-sequences')
py=(ROOT/'tests/qualify_python_sequences.py').read_text()
cpp=(ROOT/'tests/qualify_cpp_sequences.py').read_text()

def function(source,name):
    lines=source.splitlines(keepends=True)
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name==name)
    return ''.join(lines[node.lineno-1:node.end_lineno])

def replace_function(source,name,replacement):
    old=function(source,name)
    assert source.count(old)==1
    return source.replace(old,replacement.rstrip()+'\n')

header='''"""Shared retained-route mechanics; language fixtures and graph oracles stay separate."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from collections.abc import Callable

from qualify_project_tests import command

CONTROL_VERDICTS = {
    "missing-call": (3, "inconclusive"),
    "reordered-calls": (3, "inconclusive"),
    "missing-field": (1, "different_observed"),
    "missing-method-witness": (3, "inconclusive"),
    "undeclared-intermediate-error": (2, "blocked"),
}


def plan_generate(cli: Path, provider: Path, folder: Path, source: Path,
                  config: Path, expected_functions: set[str]) -> Path:
    """Require the complete selected inventory before generating a retained suite."""
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", provider,
        "--workspace-parent", folder, "--config", config], folder, "plan"))
    plan = json.loads((workspace / "plan.json").read_text())
    assert {row["otelc_function"] for row in plan["inventory"] if row["status"] == "ready"} == expected_functions
    assert not any(row["status"] == "blocked" for row in plan["inventory"])
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    return workspace


def check_contract(bundle: dict, roots: set[str], steps: int) -> None:
    """Every intermediate boundary needs the same declared roots and call order."""
    assert set(bundle["contract"]["required_roots"]) == roots
    assert len(bundle["contract"]["steps"]) == steps
    for index, step in enumerate(bundle["contract"]["steps"]):
        assert (step["id"], step["action"], set(step["required_roots"])) == ("step-" + str(index), "call", roots)


def check_execution(attempt: dict, function_id: str, expected: int, *, active: bool) -> None:
    """Empty application channels and complete selected-function witness are required."""
    assert all(attempt["execution"]["channels"][name] == [] for name in ("stdout", "stderr"))
    if active:
        witness = attempt["execution"]["witness"]
        assert witness["functions"] == {function_id: expected} and witness["spans"] == expected
        assert not any(witness["losses"].values()) and witness["pending"] == 0

'''
framework=function(py,'framework').replace('count: int = len(METHODS))','count: int, check_report: Callable[..., int])')
controls=function(py,'controls').replace('folder: Path) -> None:', 'folder: Path, functions: dict[str, str],\n             node: Callable, value_field: str) -> None:').replace('FUNCTIONS[','functions[').replace('.pop("property:value")','.pop(value_field)')
operations=function(py,'verify_operations').replace('cli: Path) -> int:', 'cli: Path, methods: tuple[str, ...], functions: dict[str, str],\n                      refusals: tuple[str, ...], *, historical_source_expectation: bool = False) -> int:').replace('METHODS','methods').replace('FUNCTIONS[','functions[')
operations=operations.replace('assert marker == {"argv": list(map(str, expected_argv[name])), "expected_exit": expected}', 'recorded = 2 if historical_source_expectation and name == "changed-source" else expected\n        assert marker == {"argv": list(map(str, expected_argv[name])), "expected_exit": recorded}')
operations=operations.replace('("cases", "edge-one", "edge-thirty-two", "edge-rich-thirty-two", "rebound-class")','("cases", "edge-one", "edge-thirty-two", *refusals)').replace('name in ("edge-rich-thirty-two", "rebound-class")','name in refusals').replace('return len(required) + 14','return len(required) + 3 * (3 + len(refusals)) - 1')
routes=function(py,'verify_routes').replace('folder: Path) -> None:', 'folder: Path, methods: tuple[str, ...],\n                  functions: dict[str, str], function: Callable[[str], str]) -> None:').replace('METHODS','methods').replace('FUNCTIONS','functions')
# Decode only the shared wire framing; runtime-specific health stays in each caller.
receipts=function(py,'verify_receipts')
start=receipts.index('        receipt = json.loads')
end=receipts.index('        roots = sorted')
decode=receipts[start:end]
decode='\n'.join(line[4:] for line in decode.splitlines())+'\n'
decode=decode.replace('attempt /', 'attempt /')
decode='''def decode_receipt(attempt: Path) -> tuple[list, dict]:
    """Read exact captured OTLP bodies and reject transport errors or foreign signals."""
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
'''+decode+'    return spans, counters\n'
start=receipts.index('        roots = sorted')
end=receipts.index('        assert set(counters)')
trees=receipts[start:end]
trees=trees.replace('        assert sum(span.status.code == 2 for span in spans) == errors\n','')
trees='\n'.join(line[4:] for line in trees.splitlines())+'\n'
trees=trees.replace('observed["function_id"]','function_id')
trees='''def check_serial_trees(spans: list, expected: list[int], function_id: str) -> None:
    """Require complete non-overlapping root trees with valid parent/child identities."""
'''+trees
common_compare='''def compare_reports(folder: Path, reports: list[Path], cli: Path,
                    check_report: Callable[..., int], excluded: tuple[str, ...]) -> tuple[int, int]:
    """Recompute every retained comparison while preserving the original report bytes."""
    observations, comparisons = 0, 0
    for path in reports:
        if any(path.is_relative_to(folder / name) for name in excluded):
            continue
        steps = 32 if path.is_relative_to(folder / "edge-thirty-two") else 1 if path.is_relative_to(folder / "edge-one") else 2
        observations += check_report(path, len(json.loads(path.read_text())["cases"]), steps=steps, compact=steps == 32)
        for case in json.loads(path.read_text())["cases"]:
            bundle = path.parent / case["case"] / "typed-bundle.json"
            result = subprocess.run([str(cli), "compare-observations", str(bundle)], capture_output=True, check=False, timeout=30)
            assert result.returncode == case["exit_code"] and json.loads(result.stdout) == case["comparison"]
            comparisons += 1
    return observations, comparisons


def verify_sources(folder: Path) -> None:
    """Every retained plan still binds its complete source manifest."""
    for path in folder.rglob("plan.json"):
        plan = json.loads(path.read_text())
        for name, expected in plan["source_manifest"].items():
            assert hashlib.sha256((Path(plan["source"]) / name).read_bytes()).hexdigest() == expected

'''
main=function(py,'main')
start=main.index('        report_path = folder / "comparison/report.json"')
end=main.index('        for name, steps, compact, expected in ')
exercise=main[start:end]
exercise='\n'.join(line[4:] for line in exercise.splitlines())+'\n'
exercise=exercise.replace('len(METHODS)','len(methods)').replace('FUNCTIONS[','functions[')
exercise='''def exercise_routes(cli: Path, folder: Path, workspace: Path, methods: tuple[str, ...],
                    functions: dict[str, str], check_report: Callable[..., int],
                    controls: Callable, framework: Callable) -> tuple[Path, dict]:
    """Exercise direct, replay, framework, detached and reduced routes on the same fixed corpus."""
'''+exercise+'    return source, target\n'
common='\n\n'.join((header.rstrip(),framework,controls,operations,routes,decode,trees,common_compare,exercise))+'\n'
compile(common,'sequence_qualification.py','exec')
(ROOT/'tests/sequence_qualification.py').write_text(common)

for language,source in (('python',py),('cpp',cpp)):
    source=source.replace('import copy\n','').replace('import subprocess\n','')
    insertion='from qualify_project_tests import command\n'
    source=source.replace(insertion,insertion+'import sequence_qualification as shared\nfrom sequence_qualification import CONTROL_VERDICTS\n')
    controls_node=next(n for n in ast.parse(source).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CONTROL_VERDICTS' for t in n.targets))
    lines=source.splitlines(keepends=True)
    del lines[controls_node.lineno-1:controls_node.end_lineno]
    source=''.join(lines)
    prepare=function(source,'prepare')
    start=prepare.index('    workspace = Path(command(')
    source=source.replace(prepare,prepare[:start]+'    return shared.plan_generate(cli, provider, folder, source, config, {function(method) for method in methods})\n')
    source=replace_function(source,'framework','''def framework(workspace: Path, folder: Path, name: str, count: int = len(METHODS)) -> int:
    """Check the retained unittest against this language's independent graph oracle."""
    return shared.framework(workspace, folder, name, count, check_report)''')
    field='property:value' if language=='python' else 'field:value_'
    source=replace_function(source,'controls',f'''def controls(cli: Path, report: Path, folder: Path) -> None:
    """Alter retained evidence using the declared {language} receiver field."""
    shared.controls(cli, report, folder, FUNCTIONS, node, {field!r})''')
    refusals='("edge-rich-thirty-two", "rebound-class")' if language=='python' else '("edge-rich-thirty-two",)'
    signature='folder: Path, cli: Path' if language=='python' else 'folder: Path, cli: Path, *, historical_source_expectation: bool = False'
    kwargs='' if language=='python' else ',\n        historical_source_expectation=historical_source_expectation'
    source=replace_function(source,'verify_operations',f'''def verify_operations({signature}) -> int:
    """Verify exact terminal receipts for the declared {language} routes."""
    return shared.verify_operations(folder, cli, METHODS, FUNCTIONS, {refusals}{kwargs})''')
    source=replace_function(source,'verify_routes','''def verify_routes(folder: Path) -> None:
    """Require every language-specific function and fixed input on every retained route."""
    shared.verify_routes(folder, METHODS, FUNCTIONS, function)''')
    source=source.replace('''        assert set(bundle["contract"]["required_roots"]) == roots
        assert len(bundle["contract"]["steps"]) == steps
        for index, step in enumerate(bundle["contract"]["steps"]):
            assert (step["id"], step["action"], set(step["required_roots"])) == ("step-" + str(index), "call", roots)''','''        shared.check_contract(bundle, roots, steps)''')
    old='''                assert all(attempt["execution"]["channels"][name] == [] for name in ("stdout", "stderr"))
                if lane == "instrumented_on":
                    expected = steps + (int(case["arguments"][0] > 0) + int(steps == 2) if method == "recursive" else 0)
                    witness = attempt["execution"]["witness"]
                    assert witness["functions"] == {case["function"]: expected} and witness["spans"] == expected
                    assert not any(witness["losses"].values()) and witness["pending"] == 0'''
    if language=='python':old=old.replace('if lane == "instrumented_on":','if active:')
    assert old in source
    source=source.replace(old,'''                expected = steps + (int(case["arguments"][0] > 0) + int(steps == 2) if method == "recursive" else 0)
                shared.check_execution(attempt, case["function"], expected, active=lane == "instrumented_on")''')
    original=function(source,'verify_receipts')
    revised=original
    for line in ('    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest\n','    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest\n'):
        revised=revised.replace(line,'')
    start=revised.index('        receipt = json.loads')
    end=revised.index('        assert set(counters)')
    replacement='''        spans, counters = shared.decode_receipt(attempt)
        shared.check_serial_trees(spans, expected, observed["function_id"])
'''
    if language=='python': replacement+='        assert sum(span.status.code == 2 for span in spans) == errors\n'
    revised=revised[:start]+replacement+revised[end:]
    source=source.replace(original,revised)
    retained=function(source,'retained')
    start=retained.index('    observations, comparisons = 0, 0')
    end=retained.index('    raw = [path')
    retained=retained[:start]+f'    observations, comparisons = shared.compare_reports(folder, reports, cli, check_report, {refusals})\n'+retained[end:]
    start=retained.index('    for path in folder.rglob("plan.json"):')
    end=retained.index('    return {',start)
    retained=retained[:start]+'    shared.verify_sources(folder)\n'+retained[end:]
    source=replace_function(source,'retained',retained)
    main=function(source,'main')
    start=main.index('        report_path = folder / "comparison/report.json"')
    end=main.index('        for name, steps, compact, expected in ')
    main=main[:start]+'''        source, target = shared.exercise_routes(cli, folder, workspace, METHODS, FUNCTIONS,
            check_report, controls, framework)
'''+main[end:]
    source=replace_function(source,'main',main)
    compile(source,'qualify_'+language+'_sequences.py','exec')
    (ROOT/('tests/qualify_'+language+'_sequences.py')).write_text(source)
print('Extracted shared qualification mechanics; independent source fixtures, graph oracles and runtime health remain language-specific.')
