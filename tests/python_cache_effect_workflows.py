"""Cached effects and current-source promotion with independent historical-stage inputs."""

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import py_compile
import sys

import generation
import python_inputs
import python_provider
import python_origin_effect_workflows as effects
import qualify_python_generated_origins as origins
from python_cache_qualification import CacheInputs
from qualify_project_tests import command
from qualify_python_caches import recompute_case, scalar

TIME = 1_700_000_000_123456789
PROMOTED = ('promoted-unchanged', 'promoted-changed-body', 'promoted-added-function')
REFUSALS = {'original-cache-bytes': 'original Python source/cache context changed',
            'source-time': 'original Python source/cache context changed',
            'cache-mode': 'original Python source/cache context changed',
            'stored-cache-bytes': 'frozen Python cache context changed',
            'snapshot-time': 'private Python context bytes, timestamps or permissions changed',
            'new-cache': 'original Python source/cache context changed'}


@dataclass(frozen=True)
class Stage:
    """A historical plan is checked against its own literal source/cache pair."""

    name: str
    report: Path
    workspace: Path
    inputs: CacheInputs
    shift: int
    functions: int


def starts(folder: Path) -> dict[str, str]:
    """Retain every actual process-start record when checking prelaunch refusals."""
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in folder.rglob('python-application-start.json')}


def initial_inputs(folder: Path) -> CacheInputs:
    inputs = CacheInputs.capture(folder / 'application', {'app.py': effects.SOURCE.encode()})
    assert inputs.receipt() == generation.read(folder / 'initial-inputs.json')
    return inputs


def run(cli: Path, provider: Path, folder: Path, catalogue: dict) -> None:
    """Run scalar domains, file/HTTP effects, detached suites and fresh source promotion."""
    folder.mkdir(mode=0o700); source = folder / 'application'; source.mkdir()
    target = source / 'app.py'; target.write_text(effects.SOURCE); os.utime(target, ns=(TIME, TIME))
    py_compile.compile(str(target), doraise=True)
    initial = CacheInputs.capture(source, {'app.py': effects.SOURCE.encode()})
    generation.write(folder / 'initial-inputs.json', initial.receipt())
    generation.write(folder / 'provider-inputs.json', catalogue)
    config = folder / 'equivalence.toml'
    config.write_text(effects.POLICY.replace('python-native-origins-v2', 'python-native-cache-origins-v3'))
    workspace = Path(command([cli, 'plan', '--source', source, '--otelc-root', provider,
        '--workspace-parent', folder, '--config', config], folder, 'plan'))
    initial.verify_workspace(workspace)
    command([cli, 'generate', '--workspace', workspace], folder, 'generate')
    command([cli, 'run', '--workspace', workspace, '--report-dir', folder / 'comparison'], folder, 'run')
    effects.check_report(folder / 'comparison/report.json')
    exported = folder / 'exported'
    command([cli, 'export-tests', '--workspace', workspace, '--destination', exported, '--apply'], folder, 'export')
    command([cli, 'run', '--workspace', exported, '--report-dir', folder / 'export-comparison'], folder, 'export-run')
    effects.check_report(folder / 'export-comparison/report.json'); initial.verify_originals()
    promoted = source / 'equivalence-tests'
    command([cli, 'promote', '--workspace', workspace, '--source', source,
             '--destination', promoted, '--apply'], folder, 'promote')
    try:
        for index, name in enumerate(PROMOTED):
            text = effects.stage_source(name); target.write_text(text)
            stamp = TIME + index * 2_000_000_000; os.utime(target, ns=(stamp, stamp))
            inputs = CacheInputs.capture(source, {'app.py': text.encode()})
            generation.write(folder / (name + '-inputs.json'), inputs.receipt())
            output = command([sys.executable, '-I', '-B', promoted / 'test_equivalence.py'], folder, name, 0,
                {'OTELEQ_SOURCE': str(source), 'OTELEQ_WORKSPACE_PARENT': str(folder)})
            rows = [json.loads(line) for line in output.splitlines()]
            functions = 2 if index == 2 else 1
            assert len(rows) == functions * 3 + 1 and rows[0]['project_source'] == str(source)
            inputs.verify_workspace(Path(rows[0]['workspace'])); inputs.verify_originals()
            for row in rows[1:]:
                effects.check_report(Path(row['report']), int(index > 0), functions)
    finally:
        target.write_text(effects.SOURCE); os.utime(target, ns=(TIME, TIME))
    initial.verify_originals()
    refuse_changed_inputs(cli, folder, workspace, initial)


def stages(folder: Path, initial: CacheInputs) -> list[Stage]:
    """Bind each promoted body and timestamp to its independent prelaunch receipt."""
    workspace = Path((folder / 'plan.stdout').read_text().strip())
    result = [Stage('direct', folder / 'comparison/report.json', workspace, initial, 0, 1),
              Stage('export', folder / 'export-comparison/report.json', folder / 'exported', initial, 0, 1)]
    for index, name in enumerate(PROMOTED):
        text = effects.stage_source(name); receipt = generation.read(folder / (name + '-inputs.json'))
        facts = {**initial.source_facts['app.py'], 'sha256': hashlib.sha256(text.encode()).hexdigest(),
                 'size': len(text.encode()), 'mtime_ns': TIME + index * 2_000_000_000}
        assert receipt == {'sources': {'app.py': facts}, 'caches': initial.cache_facts}
        inputs = CacheInputs(initial.root, {'app.py': text.encode()}, initial.caches,
                             receipt['sources'], receipt['caches'])
        rows = [json.loads(line) for line in (folder / (name + '.stdout')).read_text().splitlines()]
        functions = 2 if index == 2 else 1
        assert len(rows) == functions * 3 + 1 and rows[0]['project_source'] == str(initial.root)
        current = Path(rows[0]['workspace']); assert current.is_relative_to(folder)
        result.extend(Stage(name, Path(row['report']), current, inputs, int(index > 0), functions)
                      for row in rows[1:])
    assert len(result) == 14 and len({stage.report for stage in result}) == 14
    return result


def typed_graph(value: int, counter: int, *, result: bool = False) -> dict:
    roots = {'arguments': {'kind': 'reference', 'node_id': 'n0'}, 'global:counter': scalar(counter)}
    if result:
        roots['result'] = scalar(7)
    return {'roots': roots, 'nodes': [{'id': 'n0', 'type': 'python.builtins.list',
                                     'fields': {'item:0': scalar(value)}}]}


def check_typed(case: dict, bundle: dict, shift: int) -> None:
    """Check the entire typed graph independently of the production scalar codec."""
    value, = case['arguments']
    expected = {'case_id': case['case'], 'function_id': case['function'], 'observation_schema_version': 1,
                'fixture_sha256': bundle['contract']['fixture_sha256'], 'fixture': {'status': 'ready'}, 'gaps': [],
                'before': typed_graph(value, 0), 'after': typed_graph(value, value + shift),
                'outcome': {'kind': 'return', 'graph': typed_graph(value, value + shift, result=True)}}
    for lane in ('baseline', 'instrumented_on'):
        assert len(bundle[lane]) == 2
        assert all(python_provider.same(attempt['observation'], expected) for attempt in bundle[lane])


@contextmanager
def mutated_input(initial: CacheInputs, workspace: Path, fault: str):
    """Change one owned fixture input and restore all originally recorded facts."""
    assert fault in REFUSALS and len(initial.caches) == 1
    cached, = initial.caches
    original = initial.root / cached; stored = workspace / 'python-cache-context/files' / cached
    source = initial.root / 'app.py'; snapshot = workspace / 'snapshot/app.py'
    extra = original.with_name('app.foreign.pyc'); assert not extra.exists() and not extra.is_symlink()
    content, stored_content = original.read_bytes(), stored.read_bytes()
    attributes = {path: path.stat() for path in (original, stored, source, snapshot)}
    try:
        if fault == 'original-cache-bytes':
            original.write_bytes(content + b'changed')
        elif fault == 'source-time':
            os.utime(source, ns=(TIME + 1, TIME + 1))
        elif fault == 'cache-mode':
            original.chmod(0o600 if (attributes[original].st_mode & 0o777) != 0o600 else 0o640)
        elif fault == 'stored-cache-bytes':
            stored.write_bytes(stored_content + b'changed')
        elif fault == 'snapshot-time':
            os.utime(snapshot, ns=(TIME + 1, TIME + 1))
        else:
            extra.write_bytes(b'new associated cache')
        yield
    finally:
        if fault == 'original-cache-bytes':
            original.write_bytes(content)
        if fault == 'stored-cache-bytes':
            stored.write_bytes(stored_content)
        if fault == 'new-cache' and extra.exists():
            extra.unlink()
        for path, info in attributes.items():
            os.chmod(path, info.st_mode & 0o7777)
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        initial.verify_originals(); initial.verify_workspace(workspace)


def refuse_changed_inputs(cli: Path, folder: Path, workspace: Path, initial: CacheInputs) -> None:
    """Every altered input must refuse before a new application starts."""
    before = starts(folder); assert len(before) == 72
    case = generation.read(folder / 'comparison/report.json')['cases'][0]['case']
    rows = []
    for fault, message in REFUSALS.items():
        with mutated_input(initial, workspace, fault):
            command([cli, 'replay', '--workspace', workspace, '--case', case], folder, 'refuse-' + fault, 4)
            error = (folder / ('refuse-' + fault + '.stderr')).read_text()
            assert error == 'oteleq: Python prepared provider: ' + message + '\n'
            assert not (folder / ('refuse-' + fault + '.stdout')).read_bytes()
            assert starts(folder) == before
            rows.append({'fault': fault, 'exit_code': 4, 'additional_application_launches': 0, 'stderr': error})
    generation.write(folder / 'refusals.json', rows)


def check_operations(folder: Path, cli: Path, provider: Path) -> None:
    """Require all named routes and refusal receipts, including their expected failures."""
    successful = ('plan', 'generate', 'run', 'export', 'export-run', 'promote', *PROMOTED)
    expected = {**dict.fromkeys(successful, 0), **{'refuse-' + name: 4 for name in REFUSALS}}
    assert {path.stem for path in folder.glob('*.exit')} == set(expected)
    workspace = Path((folder / 'plan.stdout').read_text().strip()); assert workspace.is_relative_to(folder)
    source, exported = folder / 'application', folder / 'exported'
    promoted = source / 'equivalence-tests'
    case = generation.read(folder / 'comparison/report.json')['cases'][0]['case']
    argv = {'plan': [cli, 'plan', '--source', source, '--otelc-root', provider,
                    '--workspace-parent', folder, '--config', folder / 'equivalence.toml'],
            'generate': [cli, 'generate', '--workspace', workspace],
            'run': [cli, 'run', '--workspace', workspace, '--report-dir', folder / 'comparison'],
            'export': [cli, 'export-tests', '--workspace', workspace, '--destination', exported, '--apply'],
            'export-run': [cli, 'run', '--workspace', exported, '--report-dir', folder / 'export-comparison'],
            'promote': [cli, 'promote', '--workspace', workspace, '--source', source,
                        '--destination', promoted, '--apply'],
            **{name: [sys.executable, '-I', '-B', promoted / 'test_equivalence.py'] for name in PROMOTED},
            **{'refuse-' + fault: [cli, 'replay', '--workspace', workspace, '--case', case] for fault in REFUSALS}}
    for name, code in expected.items():
        assert (folder / (name + '.exit')).read_text() == str(code) + '\n'
        assert generation.read(folder / (name + '.started.json')) == {
            'argv': list(map(str, argv[name])), 'expected_exit': code}
        assert (folder / (name + '.stdout')).is_file() and (folder / (name + '.stderr')).is_file()
    refusals = generation.read(folder / 'refusals.json')
    assert len(refusals) == len(REFUSALS) and {row['fault'] for row in refusals} == set(REFUSALS)
    for row in refusals:
        assert row == {'fault': row['fault'], 'exit_code': 4, 'additional_application_launches': 0,
                       'stderr': 'oteleq: Python prepared provider: ' + REFUSALS[row['fault']] + '\n'}
        assert (folder / ('refuse-' + row['fault'] + '.stderr')).read_text() == row['stderr']
        assert not (folder / ('refuse-' + row['fault'] + '.stdout')).read_bytes()


def retained(folder: Path, cli: Path, provider: Path, catalogue: dict, interpreter: dict) -> dict:
    """Audit every historical input pair, actual process and complete effect/typed oracle."""
    assert generation.read(folder / 'provider-inputs.json') == catalogue
    initial = initial_inputs(folder); check_operations(folder, cli, provider)
    identities, reports = {}, set()
    comparisons, observations = 0, 0
    for stage in stages(folder, initial):
        assert stage.report.is_relative_to(folder)
        stage.inputs.verify_workspace(stage.workspace)
        report = generation.read(stage.report); assert report['workspace'] == str(stage.workspace)
        plan = generation.read(stage.workspace / 'plan.json')
        assert plan['source'] == str(stage.workspace / 'snapshot' if stage.name == 'export' else initial.root)
        assert report['source_sha256'] == plan['source_sha256']
        effects.check_report(stage.report, stage.shift, stage.functions); reports.add(stage.report)
        entries = {entry['otelc_function']: entry for entry in report['inventory']}
        for case in report['cases']:
            path = stage.report.parent / case['case'] / 'typed-bundle.json'
            bundle = generation.read(path)['cases'][0]; check_typed(case, bundle, stage.shift)
            recompute_case(cli, path, case['comparison']); comparisons += 1
            for lane in ('baseline', 'instrumented_on'):
                for repeat in range(2):
                    attempt = stage.report.parent / case['case'] / (lane + '-' + str(repeat)); observations += 1
                    verified = generation.read(attempt / 'python-verified-origins.json')
                    expected = 'source-compiler' if stage.shift else 'cache-read'
                    assert verified['source_origin'] == 'selected-input-bound' and len(verified['selected']) == 1
                    assert all(match['input_binding'] == expected for match in verified['selected'][0]['matches'])
                    actual = origins.recheck_attempt(attempt, entries[case['function']], provider,
                        catalogue, interpreter, selection_builder=stage.inputs.scalar_selection,
                        cache_builder=stage.inputs.frozen_caches)
                    identities[actual['runtime']] = actual
    assert reports == set(folder.rglob('report.json')) and len(reports) == 14
    assert observations == len(identities) == 72 and comparisons == 18
    assert len({row['application_pid'] for row in identities.values()}) == 72
    assert len({row['sdk_pid'] for row in identities.values() if not row['plain']}) == 36
    assert set(starts(folder)) == {str(Path(runtime) / 'python-application-start.json') for runtime in identities}
    initial.verify_originals()
    assert python_inputs.artefacts(provider, {'python': Path(sys.executable).absolute()}) == catalogue
    return {'claim': 'equivalence over these tests and observations', 'artefact_class': 'diagnostic',
            'actual_application_launches': 72, 'sdk_processes': 36, 'reports': 14,
            'complete_raw_and_typed_observations': 72, 'copied_original_observations': 0,
            'recomputed_comparisons': 18, 'prelaunch_input_mutation_refusals': len(REFUSALS),
            'all_actual_start_records_accounted': True, 'current_source_unchanged_changed_added_function': True,
            'scope': 'Cached scalar domains/filesystem/HTTP/direct/export/current-source workflows, '
                     'historical literal source/cache facts and prelaunch refusals. No shipping/full-project claim.'}
