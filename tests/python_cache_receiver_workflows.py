"""Portable cached receiver workflows with literal graphs and retained native evidence."""

import json
import os
from pathlib import Path
import py_compile
import sys

import generation
import python_inputs
import qualify_python_generated_origins as origins
import qualify_python_sequences as legacy
import sequence_qualification as shared
from python_cache_qualification import CacheInputs
from python_sequence_fixture import FUNCTIONS, METHODS, SOURCE, function
from qualify_project_tests import command

TIME = 1_700_000_000_123456789
SOURCES = {'src/pkg/__init__.py': b'', 'src/pkg/state.py': SOURCE.encode()}


def policy() -> str:
    """Keep target, constructor/factory and ordered inputs independent of inventory output."""
    text = ('schema_version=1\nlanguages=["python"]\n[adapters.python]\nimport_roots=["src"]\n'
            'backend="prepared"\nprofile="python-native-cache-origins-v3"\n[functions]\ninclude='
            + json.dumps(list(FUNCTIONS)) + '\n')
    for method in METHODS:
        factory = 'make_counter' if method == 'secret' else 'Counter'
        text += ('\n[[fixtures]]\nfunction=' + json.dumps(function(method)) + '\ncases=[[7]]\n'
                 'receiver={factory=' + json.dumps(factory) + ',arguments=[10]}\n')
        error = (',expected_baseline={kind="error",category="exception",type="python.builtins.ValueError"}'
                 if method == 'fail' else '')
        text += 'sequence=[{action="call",arguments="case"' + error + '},{action="call",arguments=[2]}]\n'
        if method == 'transient':
            text += 'domains=[{kind="integer",minimum=0,maximum=7}]\n'
    return text


def run(cli: Path, provider: Path, folder: Path, catalogue: dict) -> None:
    """Run generated, replay, framework, detached and reduced cached receiver suites."""
    folder.mkdir(mode=0o700)
    generation.write(folder / 'provider-inputs.json', catalogue)
    cases = folder / 'cases'; cases.mkdir()
    source = cases / 'application'
    for name, raw in SOURCES.items():
        path = source / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        os.utime(path, ns=(TIME, TIME)); py_compile.compile(str(path), doraise=True)
    inputs = CacheInputs.capture(source, SOURCES)
    generation.write(folder / 'independent-inputs.json', inputs.receipt())
    config = cases / 'equivalence.toml'; config.write_text(policy())
    workspace = shared.plan_generate(cli, provider, cases, source, config, set(FUNCTIONS))
    inputs.verify_workspace(workspace)
    shared.exercise_routes(cli, folder, workspace, METHODS, FUNCTIONS,
                           origins.check_report, legacy.controls, origins.framework)
    inputs.verify_originals()


def check_operations(folder: Path, cli: Path, provider: Path) -> None:
    """Omitted retained routes or altered terminal receipts cannot pass the audit."""
    expected = {'run': 1, 'framework': 1, 'export': 0, 'export-run': 1, 'export-framework': 1,
                'shrink': 1, 'reduced-framework': 1, 'reduced-replay': 1,
                **{'replay-' + method: int(method == 'transient') for method in METHODS},
                **{name: row[0] for name, row in shared.CONTROL_VERDICTS.items()}}
    assert {path.stem for path in folder.glob('*.exit')} == set(expected)
    workspace = Path((folder / 'cases/plan.stdout').read_text().strip())
    assert workspace.is_relative_to(folder / 'cases')
    reduced = Path(generation.read(folder / 'shrink/shrink.json')['workspace'])
    assert reduced == folder / 'shrink/workspace'
    cases = {FUNCTIONS[case['function']]: case['case']
             for case in generation.read(folder / 'comparison/report.json')['cases']}
    argv = {'run': [cli, 'run', '--workspace', workspace, '--report-dir', folder / 'comparison'],
            'framework': [sys.executable, workspace / 'tests/test_equivalence.py'],
            'export': [cli, 'export-tests', '--workspace', workspace, '--destination', folder / 'exported', '--apply'],
            'export-run': [cli, 'run', '--workspace', folder / 'exported', '--report-dir', folder / 'export-comparison'],
            'export-framework': [sys.executable, folder / 'exported/tests/test_equivalence.py'],
            'shrink': [cli, 'shrink', '--workspace', workspace, '--case', cases['transient'],
                       '--report-dir', folder / 'shrink', '--trials', '1'],
            'reduced-framework': [sys.executable, reduced / 'tests/test_equivalence.py'],
            'reduced-replay': [cli, 'replay', '--workspace', reduced, '--case', cases['transient']],
            **{'replay-' + method: [cli, 'replay', '--workspace', workspace, '--case', cases[method]] for method in METHODS},
            **{name: [cli, 'compare-observations', folder / (name + '.json')] for name in shared.CONTROL_VERDICTS}}
    for name, code in expected.items():
        assert (folder / (name + '.exit')).read_text() == str(code) + '\n'
        assert generation.read(folder / (name + '.started.json')) == {
            'argv': list(map(str, argv[name])), 'expected_exit': code}
        assert (folder / (name + '.stdout')).is_file() and (folder / (name + '.stderr')).is_file()
        if name in shared.CONTROL_VERDICTS:
            assert generation.read(folder / (name + '.stdout'))['verdict'] == shared.CONTROL_VERDICTS[name][1]
    assert (folder / 'cases/plan.exit').read_text() == (folder / 'cases/generate.exit').read_text() == '0\n'
    expected_plan = [cli, 'plan', '--source', folder / 'cases/application', '--otelc-root', provider,
                     '--workspace-parent', folder / 'cases', '--config', folder / 'cases/equivalence.toml']
    for name, arguments in [('plan', expected_plan), ('generate', [cli, 'generate', '--workspace', workspace])]:
        assert generation.read(folder / 'cases' / (name + '.started.json')) == {
            'argv': list(map(str, arguments)), 'expected_exit': 0}


def check_routes(folder: Path) -> None:
    """Every named route must retain the full declared methods or its fixed single case."""
    for name in ('comparison', 'export-comparison'):
        cases = generation.read(folder / name / 'report.json')['cases']
        assert {case['function'] for case in cases} == set(FUNCTIONS)
        assert len(cases) == len(METHODS) and all(case['arguments'] == [7] for case in cases)
    names = ['replay-' + method for method in METHODS]
    names += ['framework', 'export-framework', 'reduced-framework', 'reduced-replay']
    for name in names:
        rows = [json.loads(line) for line in (folder / (name + '.stdout')).read_text().splitlines()]
        assert len(rows) == (len(METHODS) if name in ('framework', 'export-framework') else 1)
        methods = set()
        for row in rows:
            report = Path(row['report']); assert report.is_relative_to(folder)
            case, = generation.read(report)['cases']; method = FUNCTIONS[case['function']]; methods.add(method)
            assert case['arguments'] == ([0] if name.startswith('reduced-') else [7])
        if name in ('framework', 'export-framework'):
            assert methods == set(METHODS)
        else:
            assert methods == {name.removeprefix('replay-') if name.startswith('replay-') else 'transient'}


def retained(folder: Path, cli: Path, provider: Path, catalogue: dict, interpreter: dict) -> dict:
    """Audit every retained observation while counting copied originals only once."""
    assert generation.read(folder / 'provider-inputs.json') == catalogue
    inputs = CacheInputs.capture(folder / 'cases/application', SOURCES)
    assert inputs.receipt() == generation.read(folder / 'independent-inputs.json')
    check_operations(folder, cli, provider); check_routes(folder)
    reports = sorted(folder.rglob('report.json'))
    observations, comparisons = shared.compare_reports(folder, reports, cli, origins.check_report, ())
    identities, start_paths = {}, set()
    for path in reports:
        report = generation.read(path); workspace = Path(report['workspace']); inputs.verify_workspace(workspace)
        assert report['source_sha256'] == generation.read(workspace / 'plan.json')['source_sha256']
        entries = {entry['otelc_function']: entry for entry in report['inventory']}
        for case in report['cases']:
            for lane in ('baseline', 'instrumented_on'):
                for repeat in range(2):
                    attempt = path.parent / case['case'] / (lane + '-' + str(repeat))
                    start_paths.add(attempt / 'python-runtime/python-application-start.json')
                    verified = generation.read(attempt / 'python-verified-origins.json')
                    assert verified['source_origin'] == 'selected-input-bound' and len(verified['selected']) == 2
                    assert all(match['input_binding'] == 'cache-read'
                               for selected in verified['selected'] for match in selected['matches'])
                    actual = origins.recheck_attempt(attempt, entries[case['function']], provider,
                        catalogue, interpreter, cache_builder=inputs.frozen_caches)
                    assert actual['application_pid'] == verified['application_pid']
                    identities[actual['runtime']] = actual
    assert set(folder.rglob('python-application-start.json')) == start_paths
    assert observations == 144 and comparisons == 36 and len(identities) == 140
    assert len({row['application_pid'] for row in identities.values()}) == 140
    assert len({row['sdk_pid'] for row in identities.values() if not row['plain']}) == 70
    inputs.verify_originals()
    assert python_inputs.artefacts(provider, {'python': Path(sys.executable).absolute()}) == catalogue
    return {'claim': 'equivalence over these tests and observations', 'artefact_class': 'diagnostic',
            'actual_application_launches': 140, 'sdk_processes': 70, 'reports': len(reports),
            'complete_raw_and_typed_observations': 144, 'copied_original_observations': 4,
            'recomputed_comparisons': 36, 'altered_comparison_refusals': len(shared.CONTROL_VERDICTS),
            'all_selected_target_and_creator_cache_bound': True, 'source_and_cache_facts_preserved': True,
            'scope': 'Synchronous cached package receivers/factories, ordered calls, recursion, exceptions and '
                     'a real intermediate mutation; generated/replay/framework/detached/reduced routes. '
                     'Broader loaders, live controls, async/resources, shipping and whole-project acceptance remain separate.'}
