"""Qualify every Java startup state through retained and current-source suites."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

import java_startup_receipts
import java_startup_builds
import qualify_java_controls as controls
from qualify_project_tests import command
from qualify_sequences import source_control

STATES = ((True, True), (False, True), (True, False), (False, False))
STARTS = ('both-on', 'collection-off', 'emission-off', 'both-off')
MetricStates = tuple[tuple[bool, bool], ...]


def startup_states(name: str) -> MetricStates:
    if name not in STARTS:
        raise ValueError('unknown Java startup state')
    offset = STARTS.index(name)
    return STATES[offset:] + STATES[:offset]


def read(path: Path) -> dict:
    return json.loads(path.read_bytes())


def check_report(path: Path, states: MetricStates, *, console_prefix: str = '') -> str:
    report = read(path)
    controls.check_report(path, len(report['cases']), states=states, console_prefix=console_prefix)
    return report['cases'][0]['function']


def framework(workspace: Path, folder: Path, name: str, states: MetricStates, *, reduced: bool = False) -> None:
    output = command([sys.executable, '-I', '-B', workspace / 'tests/test_equivalence.py'], folder, name, 1)
    rows = [json.loads(line) for line in output.splitlines()]
    wanted = {'Counter.transient_value(int)'} if reduced else set(controls.FUNCTIONS)
    assert len(rows) == len(wanted)
    actual = [check_report(Path(row['report']), states) for row in rows]
    assert len(set(actual)) == len(actual) and set(actual) == wanted


def current_suite(bundle: Path, application: Path, folder: Path, name: str, states: MetricStates, *, changed: bool) -> None:
    output = command([sys.executable, '-I', '-B', bundle / 'test_equivalence.py'], folder, name, 1,
        {'OTELEQ_SOURCE': str(application), 'OTELEQ_WORKSPACE_PARENT': str(folder)})
    rows = [json.loads(line) for line in output.splitlines()]
    assert len(rows) == 7 and rows[0]['project_source'] == str(application)
    workspace = Path(rows[0]['workspace'])
    assert (workspace / 'snapshot/Counter.java').read_bytes() == (application / 'Counter.java').read_bytes()
    actual = [check_report(Path(row['report']), states,
        console_prefix='changed-' if changed else '') for row in rows[1:]]
    assert len(set(actual)) == len(actual) and set(actual) == set(controls.FUNCTIONS)


def reduce_case(cli: Path, workspace: Path, target: dict, folder: Path, states: MetricStates) -> None:
    reduced = folder / 'shrink'
    command([cli, 'shrink', '--workspace', workspace, '--case', target['case'],
        '--report-dir', reduced, '--trials', '1'], folder, 'shrink', 1)
    result = read(reduced / 'shrink.json')
    assert result['original_arguments'] == [7] and result['reduced_arguments'] == [0]
    assert result['status'] == 'candidate_rule_minimal' and len(result['trials']) == 1
    for report in [reduced / 'original/report.json', reduced / 'confirmation/report.json',
                   *[Path(row['report']) for row in result['trials']]]:
        check_report(report, states)
    replay = Path(result['workspace'])
    framework(replay, folder, 'reduced-framework', states, reduced=True)
    row = json.loads(command([cli, 'replay', '--workspace', replay, '--case', target['case']],
        folder, 'reduced-replay', 1))
    check_report(Path(row['report']), states)


def promote(cli: Path, workspace: Path, application: Path, folder: Path, states: MetricStates) -> None:
    bundle = folder / 'project-tests'
    arguments = [cli, 'promote', '--workspace', workspace, '--source', application, '--destination', bundle]
    plan = json.loads(command(arguments, folder, 'promote-plan'))
    assert plan['mode'] == 'dry-run' and len(plan['files']) == 6 and not bundle.exists()
    command([*arguments, '--apply'], folder, 'promote-apply')
    current_suite(bundle, application, folder, 'promoted-original', states, changed=False)
    filename = application / 'Counter.java'
    original = filename.read_text()
    changed = original.replace('"out"+amount', '"changed-out"+amount').replace('"err"+amount', '"changed-err"+amount')
    assert changed != original and changed.count('changed-out') == changed.count('changed-err') == 1
    try:
        filename.write_text(changed)
        current_suite(bundle, application, folder, 'promoted-changed', states, changed=True)
    finally:
        filename.write_text(original)


def routes(cli: Path, provider: Path, root: Path, profile: str, states: MetricStates) -> Path:
    folder = root / 'corpus';folder.mkdir()
    workspace = controls.prepare(cli, provider, folder / 'cases', profile, states=states,
        classpath=[] if profile == 'archive-methods-v1' else None, case_timeout_ms=60000)
    command([cli, 'run', '--workspace', workspace, '--report-dir', folder / 'comparison'], folder, 'run', 1)
    report = read(folder / 'comparison/report.json')
    check_report(folder / 'comparison/report.json', states)
    source_control(cli, workspace, folder, report['cases'][0], source_name='Counter.java')
    for case in report['cases']:
        row = json.loads(command([cli, 'replay', '--workspace', workspace, '--case', case['case']],
            folder, 'replay-' + controls.FUNCTIONS[case['function']], case['exit_code']))
        check_report(Path(row['report']), states)
    framework(workspace, folder, 'framework', states)
    exported = folder / 'exported'
    arguments = [cli, 'export-tests', '--workspace', workspace, '--destination', exported]
    command(arguments, folder, 'export-plan')
    assert not exported.exists()
    command([*arguments, '--apply'], folder, 'export-apply')
    application = Path(read(workspace / 'plan.json')['source'])
    detached = application.with_name('application-detached')
    application.rename(detached)
    try:
        command([cli, 'run', '--workspace', exported, '--report-dir', folder / 'export-comparison'], folder, 'export-run', 1)
        check_report(folder / 'export-comparison/report.json', states)
        framework(exported, folder, 'export-framework', states)
    finally:
        detached.rename(application)
    target = next(case for case in report['cases'] if case['function'] == 'Counter.transient_value(int)')
    reduce_case(cli, workspace, target, folder, states)
    promote(cli, workspace, application, folder, states)
    assert (application / 'Counter.java').read_text() == controls.SOURCE
    return workspace


def recheck(root: Path, cli: Path, states: MetricStates, *, java_profile: str = 'safe-methods-v1',
            comparison_directory: Path | None = None) -> dict:
    folder = root / 'corpus'
    changed = {Path(row['report']) for row in
        map(json.loads, (folder / 'promoted-changed.stdout').read_text().splitlines()) if 'report' in row}
    assert len(changed) == 6
    reports = sorted(folder.rglob('report.json'))
    assert len(reports) == 38
    for path in reports:
        check_report(path, states, console_prefix='changed-' if path in changed else '')
    launches = controls.verify_launches(folder, 188)
    assert launches['raw_attempt_folders'] == 192
    builds = java_startup_builds.verify(folder, java_profile)
    prepared = controls.verify_prepared(folder, lambda *args: controls.verify_receipt(*args, states=states))
    assert prepared['unique_processes'] == 188
    comparisons = 0
    for path in folder.rglob('typed-bundle.json'):
        destination = path.parent
        if comparison_directory is not None:
            destination = comparison_directory / hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:24]
            destination.mkdir(parents=True)
        actual = json.loads(command([cli, 'compare-observations', path], destination,
            'startup-recomparison', 1 if read(path.parent / 'comparison.json')['verdict'] == 'different_observed' else 0))
        assert actual == read(path.parent / 'comparison.json')
        comparisons += 1
    assert comparisons == 48
    for path in folder.rglob('plan.json'):
        plan = read(path)
        for name, expected in plan['source_manifest'].items():
            assert hashlib.sha256((path.parent / 'snapshot' / name).read_bytes()).hexdigest() == expected
    return {'actual_jvm_launches': 188, 'raw_attempt_folders': 192, 'copied_attempts_excluded': 4,
        'typed_comparisons_recomputed': comparisons, 'qualified_reports': len(reports),
        'launches': launches, 'builds': builds, 'prepared': prepared, 'source_preserved': True}


def route_operations(folder: Path, workspace: Path, cli: Path) -> dict[str, dict]:
    """Derive all required route commands independently of their completion records."""
    plan = read(workspace / 'plan.json')
    application = folder / 'cases/application'
    assert plan['source'] == str(application)
    cases = {controls.FUNCTIONS[entry['otelc_function']]: entry['id'] + '-0'
        for entry in plan['inventory'] if entry['status'] == 'ready'}
    assert len(cases) == 6 and len(set(cases.values())) == 6
    exported, reduced, promoted = folder / 'exported', folder / 'shrink/workspace', folder / 'project-tests'
    target = cases['transient_value']
    operations = {}

    def add(name: str, arguments: list, expected: int = 0) -> None:
        operations[name] = {'argv': list(map(str, arguments)), 'expected_exit': expected}

    add('run', [cli, 'run', '--workspace', workspace, '--report-dir', folder / 'comparison'], 1)
    for method, case in cases.items():
        add('replay-' + method, [cli, 'replay', '--workspace', workspace, '--case', case],
            int(method in ('transient_value', 'withheld')))
    export = [cli, 'export-tests', '--workspace', workspace, '--destination', exported]
    add('export-plan', export);add('export-apply', [*export, '--apply'])
    add('export-run', [cli, 'run', '--workspace', exported, '--report-dir', folder / 'export-comparison'], 1)
    add('shrink', [cli, 'shrink', '--workspace', workspace, '--case', target,
        '--report-dir', folder / 'shrink', '--trials', '1'], 1)
    add('reduced-replay', [cli, 'replay', '--workspace', reduced, '--case', target], 1)
    promote = [cli, 'promote', '--workspace', workspace, '--source', application, '--destination', promoted]
    add('promote-plan', promote);add('promote-apply', [*promote, '--apply'])
    for name, suite in (('framework', workspace / 'tests'), ('export-framework', exported / 'tests'),
                        ('reduced-framework', reduced / 'tests'), ('promoted-original', promoted),
                        ('promoted-changed', promoted)):
        add(name, [sys.executable, '-I', '-B', suite / 'test_equivalence.py'], 1)
    assert len(operations) == 19
    return operations


def retained_workspace(root: Path, provider: Path, profile: str, cli: Path) -> Path:
    """Only the original complete corpus and requested frozen profile can be reused."""
    paths = list((root / 'corpus/cases').glob('oteleq-run-*/plan.json'))
    assert len(paths) == 1
    plan = read(paths[0])
    assert Path(plan['otelc_root']).resolve(strict=True) == provider
    ready = [entry for entry in plan['inventory'] if entry['status'] == 'ready']
    assert len(ready) == 6 and {entry['otelc_function'] for entry in ready} == set(controls.FUNCTIONS)
    assert all(entry.get('java_profile', 'stock-methods-v1') == profile for entry in ready)
    folder, workspace = root / 'corpus', paths[0].parent
    operations = route_operations(folder, workspace, cli)
    assert {path.name for path in folder.glob('*.started.json')} == {
        name + '.started.json' for name in operations}
    for name, expected in operations.items():
        for suffix in ('.started.json', '.exit', '.stdout', '.stderr'):
            path = folder / (name + suffix)
            assert path.is_file() and not path.is_symlink()
        recorded = read(folder / (name + '.started.json'))
        assert type(recorded.get('expected_exit')) is int and recorded == expected
        assert (folder / (name + '.exit')).read_text().strip() == str(expected['expected_exit'])
    return paths[0].parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--otelc-root', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--startup-state', choices=STARTS, default='both-on')
    parser.add_argument('--java-profile', choices=('stock-methods-v1', 'safe-methods-v1', 'archive-methods-v1'), default='safe-methods-v1')
    parser.add_argument('--recheck', action='store_true')
    args = parser.parse_args()
    cli, provider = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True)
    root = args.report_dir.resolve()
    if root.is_relative_to(provider) or root.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error('qualification output must be new and outside the consumer/provider sources')
    states = startup_states(args.startup_state)
    os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli))
    if args.recheck:
        workspace = retained_workspace(root, provider, args.java_profile, cli)
        destination = Path(tempfile.mkdtemp(prefix='offline-recheck-', dir=root))
        negatives = java_startup_receipts.recheck(root / 'evidence-controls', workspace, states)
    else:
        root.mkdir(mode=0o700)
        destination = root
        workspace = routes(cli, provider, root, args.java_profile, states)
        negatives = java_startup_receipts.qualify(root / 'corpus', workspace, root / 'evidence-controls', states)
    result = recheck(root, cli, states, java_profile=args.java_profile,
        comparison_directory=destination / 'comparisons' if args.recheck else None)
    result.update(claim='equivalence over these tests and observations', java_profile=args.java_profile,
        initial_metric_state={'collection': states[0][0], 'emission': states[0][1]},
        cli_sha256=hashlib.sha256(cli.read_bytes()).hexdigest(), evidence_controls=negatives,
        scope='Six declared synchronous/private/recursive receiver methods, one declared initial state and all four live states, retained suites and changed current-source console behaviour. No shipping, invocation-cookie or general build integration admission.')
    if args.recheck:
        result.update(mode='retained_recheck', new_application_launches=0, audit_directory=str(destination))
    (destination / 'QUALIFICATION.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
