"""Qualify native primitive callers while unresolved object aliases stay blocked."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys

from qualify_generation import command


def integer(value: int, language: str) -> dict:
    """Independent expected storage for the qualified host C int ABI."""
    return {'kind': 'integer', 'type': language + '.int', 'value': str(value),
            'bits': 8 * ctypes.sizeof(ctypes.c_int), 'signed': True}


def native_bytes(value: int) -> bytes:
    """Encode the fixture's independent expected native C int bytes."""
    return value.to_bytes(ctypes.sizeof(ctypes.c_int), sys.byteorder).hex().encode()


def check_case(folder: Path, case: dict) -> tuple[str, str, tuple]:
    """Reject equal wrong values, observer callbacks and missing invocation evidence."""
    raw = json.loads((folder / 'bundle.json').read_text())
    language = raw['scope']['language']
    assert language in ('c', 'cpp') and case['exit_code'] == 0
    name, arguments = case['function'].split('(')[0], case['arguments']
    assert name in ('selected_macro', 'selected_good', 'selected_bool')
    if name == 'selected_macro':
        assert arguments == [3]
        before, after, expected = {'global:state': integer(4, language)}, {'global:state': integer(7, language)}, 7
    elif name == 'selected_good':
        assert arguments == [7]
        before, after, expected = {}, {}, 8
    else:
        assert len(arguments) == 1 and type(arguments[0]) is bool
        before, after, expected = {}, {}, int(arguments[0])
    typed = json.loads((folder / 'typed-bundle.json').read_text())['cases'][0]
    assert typed['contract']['function_id'] == case['function'] and typed['contract']['case_id'] == case['case']
    assert set(typed['contract']['required_roots']) == set(before)
    raw_case = raw['cases'][0]
    assert raw_case['expected_functions'] == {case['function']: 1}
    initial = b'state:int:' + native_bytes(4) + b'\n' if before else b''
    final = b'state:int:' + native_bytes(7) + b'\n' if after else b''
    expected_bytes = b'before\n' + initial + b'return:int:' + native_bytes(expected) + b'\nafter\n' + final
    for lane in ('baseline', 'instrumented_on'):
        assert len(raw_case[lane]) == len(typed[lane]) == 2
        for captured, attempt in zip(raw_case[lane], typed[lane]):
            observed = attempt['observation']
            assert observed['case_id'] == case['case'] and observed['function_id'] == case['function']
            assert observed['fixture_sha256'] == typed['contract']['fixture_sha256']
            assert not observed['gaps']
            assert observed['before'] == {'roots': before, 'nodes': []}
            assert observed['after'] == {'roots': after, 'nodes': []}
            assert observed['outcome'] == {'kind': 'return', 'graph': {
                'roots': {**after, 'result': integer(expected, language)}, 'nodes': []}}
            assert captured['capture_complete'] and captured['termination'] == {'kind': 'exit', 'code': 0}
            assert captured['channels']['stdout'] == captured['channels']['stderr'] == []
            assert bytes(captured['channels']['state-and-outcome']).partition(b'\n')[2] == expected_bytes
            if lane == 'instrumented_on':
                assert attempt['execution']['witness']['functions'] == {case['function']: 1}
    return language, name, tuple(arguments)


def check_report(path: Path) -> int:
    """Account for all expected native inputs independently of cross-lane equality."""
    report = json.loads(path.read_text())
    assert report['source_preserved'] and len(report['cases']) == 8
    identities = [check_case(path.parent / case['case'], case) for case in report['cases']]
    expected = {(language, name, arguments) for language in ('c', 'cpp')
                for name, arguments in (('selected_macro', (3,)), ('selected_good', (7,)),
                                        ('selected_bool', (True,)), ('selected_bool', (False,)))}
    assert len(set(identities)) == len(identities) and set(identities) == expected
    return 4 * len(identities)


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
    (source / 'thread-local.c').write_text('_Thread_local int hidden=0;\nint selected_tls(int value){return value;}\n')
    (source / 'thread-local.cpp').write_text('int initialise(){__builtin_trap();return 1;}\n'
        'thread_local int hidden=initialise();\nint selected_tls(int value){return value;}\n')
    (source / 'template.cpp').write_text('template<class T>struct Holder{inline static int state=0;};\n'
        'int selected_template(int value){Holder<int>::state+=value;return 7;}\n')
    for language in ('c', 'cpp'):
        (source / ('macros.' + language)).write_text('int state=4;\n'
            'int* address(){__builtin_trap();return &state;}\n'
            'int selected_macro(int value){state+=value;return state;}\n#define state (*address())\n')
    policy = destination / "equivalence.toml"
    policy.write_text('''schema_version=1
languages=["c","cpp"]
[functions]
exclude=["*address*"]
[[fixtures]]
function="*selected_macro*"
cases=[[3]]
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
    thread_local = [entry for entry in blocked if entry['path'].startswith('thread-local.')]
    templates = [entry for entry in blocked if entry['path'] == 'template.cpp']
    assert len(aliases) == 2
    assert len(thread_local) == 3 and all('thread-local' in entry['reason'] for entry in thread_local)
    assert len(templates) == 1 and 'globals' in templates[0]['reason']
    assert all("fixture" in entry["reason"] for entry in blocked)
    command([cli, "generate", "--workspace", workspace], destination, "generate")
    comparison = destination / "comparison"
    command([cli, "run", "--workspace", workspace, "--report-dir", comparison], destination, "run", expected=3)
    report = json.loads((comparison / "report.json").read_text())
    assert report["source_preserved"] and len(report["blocked"]) == len(blocked) and len(report["cases"]) == 8
    assert all(case["exit_code"] == 0 for case in report["cases"])
    assert not any('thread-local.' in case['function'] for case in report['cases'])
    launches = check_report(comparison / 'report.json')
    summary = {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
               "scope": "eight witnessed C/C++ primitive/macro cases; aliases, thread-local and template storage remain visible blockers",
               "oteleq_cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(),
               "otelc_cli_sha256": hashlib.sha256((root / "target/debug/quux-otelc").read_bytes()).hexdigest(),
               "matching_cases": 8, "matching_attempts": launches, "blocked_callables": len(blocked),
               "blocked_object_aliases": len(aliases), "blocked_thread_local_callables": len(thread_local),
               "blocked_template_callables": len(templates),
               "blocked_other_declarations": len(blocked) - len(aliases) - len(thread_local) - len(templates),
               "qualifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "strict_gate_exit": 3, "source_preserved": True, "native_scalar_value_oracles": True}
    (destination / "qualification.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
