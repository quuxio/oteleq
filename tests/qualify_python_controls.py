"""Qualify prepared Python live schedules and audit retained evidence without new apps."""

import argparse
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import py_compile
import sys

import python_live_qualification as oracle
import generation
import python_inputs
import qualify_python_generated_origins as origins
import qualify_python_sequences as legacy
import sequence_qualification as shared
from python_cache_qualification import CacheInputs
from qualify_project_tests import command


def make_inputs(source: Path, profile: str, *, changed: bool = False) -> CacheInputs:
    """Freeze literal application bytes and ordinary caches before planning."""
    literals = oracle.sources(changed=changed)
    for name, raw in literals.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        os.utime(path, ns=(oracle.TIME, oracle.TIME))
        if profile == oracle.PROFILES[1]:
            py_compile.compile(str(path), doraise=True)
    return CacheInputs.capture(source, literals)


def prepare(cli: Path, provider: Path, folder: Path, profile: str, start: str) -> tuple[Path, CacheInputs]:
    folder.mkdir(mode=0o700)
    inputs = make_inputs(folder / 'application', profile)
    config = folder / 'equivalence.toml'
    config.write_text(oracle.policy(profile, start))
    workspace = shared.plan_generate(cli, provider, folder, inputs.root, config, set(oracle.FUNCTIONS))
    if profile == oracle.PROFILES[1]:
        inputs.verify_workspace(workspace)
    return workspace, inputs


def framework(workspace: Path, folder: Path, name: str, count: int = len(oracle.METHODS), *, start: str) -> int:
    return shared.framework(workspace, folder, name, count, partial(oracle.check_report, start=start))


def current_suite(bundle: Path, source: Path, folder: Path, name: str, start: str, *, changed: bool) -> None:
    output = command([sys.executable, '-I', '-B', bundle / 'test_equivalence.py'], folder, name, 1,
        {'OTELEQ_SOURCE': str(source), 'OTELEQ_WORKSPACE_PARENT': str(folder)})
    rows = [json.loads(line) for line in output.splitlines()]
    assert len(rows) == len(oracle.METHODS) + 1 and rows[0]['project_source'] == str(source)
    reports = [Path(row['report']) for row in rows[1:]]
    assert {generation.read(path)['cases'][0]['function'] for path in reports} == set(oracle.FUNCTIONS)
    for path in reports:
        oracle.check_report(path, 1, start=start, changed=changed)


def run(cli: Path, provider: Path, folder: Path, profile: str, start: str, catalogue: dict) -> None:
    """Require all methods on generated, retained, reduced and promoted routes."""
    folder.mkdir(mode=0o700)
    generation.write(folder / 'provider-inputs.json', catalogue)
    workspace, inputs = prepare(cli, provider, folder / 'cases', profile, start)
    generation.write(folder / 'independent-inputs.json', inputs.receipt())
    shared.exercise_routes(cli, folder, workspace, oracle.METHODS, oracle.FUNCTIONS,
        partial(oracle.check_report, start=start), legacy.controls, partial(framework, start=start))
    bundle = folder / 'project-tests'
    arguments = [cli, 'promote', '--workspace', workspace, '--source', inputs.root, '--destination', bundle]
    planned = json.loads(command(arguments, folder, 'promote-plan'))
    assert planned['mode'] == 'dry-run' and planned['files'] and not bundle.exists()
    command([*arguments, '--apply'], folder, 'promote-apply')
    current_suite(bundle, inputs.root, folder, 'current-original', start, changed=False)
    changed = make_inputs(folder / 'current-source', profile, changed=True)
    generation.write(folder / 'current-inputs.json', changed.receipt())
    current_suite(bundle, changed.root, folder, 'current-changed', start, changed=True)
    inputs.verify_originals()
    changed.verify_originals()


def check_operations(folder: Path, cli: Path, provider: Path) -> None:
    """Missing operations and changed commands must not produce a partial pass."""
    workspace = Path((folder / 'cases/plan.stdout').read_text().strip())
    assert workspace.is_relative_to(folder / 'cases')
    cases = {oracle.FUNCTIONS[row['function']]: row['case']
             for row in generation.read(folder / 'comparison/report.json')['cases']}
    reduced = Path(generation.read(folder / 'shrink/shrink.json')['workspace'])
    assert reduced == folder / 'shrink/workspace'
    bundle = folder / 'project-tests'
    promote = [cli, 'promote', '--workspace', workspace, '--source', folder / 'cases/application', '--destination', bundle]
    expected = {
        'run': (1, [cli, 'run', '--workspace', workspace, '--report-dir', folder / 'comparison']),
        'framework': (1, [sys.executable, workspace / 'tests/test_equivalence.py']),
        'export': (0, [cli, 'export-tests', '--workspace', workspace, '--destination', folder / 'exported', '--apply']),
        'export-run': (1, [cli, 'run', '--workspace', folder / 'exported', '--report-dir', folder / 'export-comparison']),
        'export-framework': (1, [sys.executable, folder / 'exported/tests/test_equivalence.py']),
        'shrink': (1, [cli, 'shrink', '--workspace', workspace, '--case', cases['transient'], '--report-dir', folder / 'shrink', '--trials', '1']),
        'reduced-framework': (1, [sys.executable, reduced / 'tests/test_equivalence.py']),
        'reduced-replay': (1, [cli, 'replay', '--workspace', reduced, '--case', cases['transient']]),
        'promote-plan': (0, promote), 'promote-apply': (0, [*promote, '--apply']),
        'current-original': (1, [sys.executable, '-I', '-B', bundle / 'test_equivalence.py']),
        'current-changed': (1, [sys.executable, '-I', '-B', bundle / 'test_equivalence.py']),
        **{'replay-' + method: (int(method == 'transient'), [cli, 'replay', '--workspace', workspace, '--case', cases[method]])
           for method in oracle.METHODS},
        **{name: (value[0], [cli, 'compare-observations', folder / (name + '.json')])
           for name, value in shared.CONTROL_VERDICTS.items()},
    }
    assert {p.stem for p in folder.glob('*.started.json')} == {name + '.started' for name in expected}
    assert {p.stem for p in folder.glob('*.exit')} == set(expected)
    for name, (code, argv) in expected.items():
        assert generation.read(folder / (name + '.started.json')) == {'argv': list(map(str, argv)), 'expected_exit': code}
        assert (folder / (name + '.exit')).read_text() == str(code) + '\n'
        assert all((folder / (name + '.' + suffix)).is_file() for suffix in ('stdout', 'stderr'))
        if name in shared.CONTROL_VERDICTS:
            assert generation.read(folder / (name + '.stdout'))['verdict'] == shared.CONTROL_VERDICTS[name][1]
    for name, argv in (
        ('plan', [cli, 'plan', '--source', folder / 'cases/application', '--otelc-root', provider,
                  '--workspace-parent', folder / 'cases', '--config', folder / 'cases/equivalence.toml']),
        ('generate', [cli, 'generate', '--workspace', workspace]),
    ):
        assert generation.read(folder / 'cases' / (name + '.started.json')) == {'argv': list(map(str, argv)), 'expected_exit': 0}
        assert (folder / 'cases' / (name + '.exit')).read_text() == '0\n'


def evidence_facts(folder: Path) -> dict:
    """Audit must leave original bytes and filesystem identity facts unchanged."""
    result = {}
    for path in folder.rglob('*'):
        if path.is_file():
            info = path.stat()
            result[str(path.relative_to(folder))] = (hashlib.sha256(path.read_bytes()).hexdigest(),
                info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    return result


def audit(cli: Path, provider: Path, folder: Path, destination: Path, profile: str, start: str, catalogue: dict) -> dict:
    """Re-read native ownership/origins/health/raw OTLP; start no applications."""
    assert generation.read(folder / 'provider-inputs.json') == catalogue
    before = evidence_facts(folder)
    inputs = CacheInputs.capture(folder / 'cases/application', oracle.sources())
    changed = CacheInputs.capture(folder / 'current-source', oracle.sources(changed=True))
    assert inputs.receipt() == generation.read(folder / 'independent-inputs.json')
    assert changed.receipt() == generation.read(folder / 'current-inputs.json')
    check_operations(folder, cli, provider)
    changed_reports = {Path(row['report']) for row in map(json.loads,
        (folder / 'current-changed.stdout').read_text().splitlines()) if 'report' in row}
    assert len(changed_reports) == len(oracle.METHODS)
    reports = sorted(folder.rglob('report.json'))
    assert len(reports) == 38
    interpreter = origins.interpreter_probe()
    observed = comparisons = 0
    identities, starts = {}, set()
    for path in reports:
        document = generation.read(path)
        is_changed = path in changed_reports
        observed += oracle.check_report(path, len(document['cases']), start=start, changed=is_changed)
        selected_inputs = changed if is_changed else inputs
        workspace = Path(document['workspace'])
        if profile == oracle.PROFILES[1]:
            selected_inputs.verify_workspace(workspace)
        else:
            assert not (workspace / 'python-cache-context').exists()
        inventory = {row['otelc_function']: row for row in document['inventory']}
        for case in document['cases']:
            case_folder = path.parent / case['case']
            for lane in ('baseline', 'instrumented_on'):
                for repeat in range(2):
                    attempt = case_folder / (lane + '-' + str(repeat))
                    starts.add(attempt / 'python-runtime/python-application-start.json')
                    actual = origins.recheck_attempt(attempt, inventory[case['function']], provider,
                        catalogue, interpreter, selection_builder=partial(oracle.selection, changed=is_changed),
                        cache_builder=selected_inputs.frozen_caches if profile == oracle.PROFILES[1] else None)
                    identities[actual['runtime']] = actual
            comparison = destination / ('comparison-' + str(comparisons))
            comparison.mkdir()
            actual = json.loads(command([cli, 'compare-observations', case_folder / 'typed-bundle.json'],
                comparison, 'compare', case['exit_code']))
            assert actual == case['comparison']
            comparisons += 1
    assert set(folder.rglob('python-application-start.json')) == starts
    assert (observed, comparisons, len(identities)) == (192, 48, 188)
    assert len({row['sdk_pid'] for row in identities.values() if not row['plain']}) == 94
    inputs.verify_originals()
    changed.verify_originals()
    assert python_inputs.artefacts(provider, {'python': Path(sys.executable).absolute()}) == catalogue
    assert evidence_facts(folder) == before
    return {'claim': 'equivalence over these tests and observations', 'artefact_class': 'diagnostic',
        'profile': profile, 'startup': start, 'python_hexversion': sys.hexversion,
        'cli_sha256': generation.capture.file_digest(cli), 'actual_application_launches': 188,
        'sdk_processes': 94, 'reports': 38, 'complete_raw_and_typed_observations': observed,
        'copied_original_observations': 4, 'recomputed_comparisons': comparisons,
        'altered_comparison_refusals': len(shared.CONTROL_VERDICTS),
        'original_evidence_files_held': len(before), 'new_application_launches_during_audit': 0,
        'scope': 'Synchronous source/cache receiver calls, recursion/errors, constructor/factory prefix and all four '
                 'same-process metric states. Generated/replay/unittest/export/detached/reduced/current-source '
                 'routes with complete literal graphs. Async/lifetimes, action cookies, general loaders/builds '
                 'and shipping or whole-project qualification remain separate.'}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--otelc-root', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--profile', choices=oracle.PROFILES, default=oracle.PROFILES[0])
    parser.add_argument('--startup-state', choices=oracle.STARTS, default='both-on')
    parser.add_argument('--retained-only', action='store_true')
    parser.add_argument('--audit-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    if sys.flags.optimize:
        parser.error('qualification requires assertions; disable Python optimisation')
    cli, provider, folder, destination = (value.resolve() for value in
        (args.cli, args.otelc_root, args.report_dir, args.audit_dir))
    for root in (provider, oracle.ROOT):
        if folder.is_relative_to(root) or destination.is_relative_to(root):
            parser.error('qualification and audit output must be outside the SDK and consumer source trees')
    if destination.is_relative_to(folder) or folder.is_relative_to(destination):
        parser.error('audit output must be separate from original evidence')
    destination.mkdir(mode=0o700)
    os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli), PYTHONDONTWRITEBYTECODE='1')
    catalogue = python_inputs.artefacts(provider, {'python': Path(sys.executable).absolute()})
    if not args.retained_only:
        run(cli, provider, folder, args.profile, args.startup_state, catalogue)
    result = audit(cli, provider, folder, destination, args.profile, args.startup_state, catalogue)
    generation.write(destination / 'qualification.json', result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
