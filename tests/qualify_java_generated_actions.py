"""Qualify explicit generated Java action scopes through public retained workflows."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import java_action_fixture as fixture
import java_action_audit as audit
import java_action_faults as faults
import generation
import java_provider
import java_build
from qualify_generation import command


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + '\n')


def prepare(cli: Path, sdk: Path, folder: Path, java: Path, profile: str,
            *, start: int = 0, counter_only: bool = False, source: Path | None = None) -> tuple[Path, Path]:
    """The public planner must account for both requested source targets."""
    folder.mkdir()
    source = fixture.fixture(folder, java, profile) if source is None else Path(shutil.copytree(source, folder / 'application'))
    config = fixture.configuration(folder, profile, start=start, counter_only=counter_only)
    workspace = Path(command([cli, 'plan', '--source', source, '--otelc-root', sdk,
        '--workspace-parent', folder, '--config', config], folder, 'plan'))
    plan = audit.read(workspace / 'plan.json')
    expected = {fixture.COUNTER} if counter_only else {fixture.COUNTER, fixture.STATIC}
    assert {row['otelc_function'] for row in plan['inventory'] if row['status'] == 'ready'} == expected
    assert not any(row['status'] == 'blocked' for row in plan['inventory'])
    command([cli, 'generate', '--workspace', workspace], folder, 'generate')
    return workspace, source


def check_report(path: Path, *, expected_cases: int | None = None, static_base: int = 10,
                 static_return: int = 7) -> list[dict]:
    """Retain independent literal, compiler, harness, receipt and health conclusions."""
    report = audit.read(path)
    assert report['source_preserved'] and not report['blocked'] and report['cases']
    if expected_cases is not None:
        assert len(report['cases']) == expected_cases
    records = []
    for case in report['cases']:
        function = case['function']
        assert function in (fixture.COUNTER, fixture.STATIC) and case['exit_code'] == int(function == fixture.STATIC)
        folder = path.parent / case['case']
        frozen = audit.read(folder / 'corpus.json')
        entry, = [row for row in report['inventory'] if row['id'] == frozen['function_id']]
        bundle = audit.read(folder / 'typed-bundle.json')['cases'][0]
        assert bundle['contract']['function_id'] == function and bundle['contract']['case_id'] == frozen['id']
        for lane in ('baseline', 'instrumented_on'):
            assert len(bundle[lane]) == 2
            for index, row in enumerate(bundle[lane]):
                observed = row['observation']
                assert observed['case_id'] == frozen['id']
                assert observed['fixture_sha256'] == bundle['contract']['fixture_sha256']
                graphs = fixture.observation(observed, function, case['arguments'][0], instrumented=lane == 'instrumented_on',
                                             static_base=static_base, static_return=static_return)
                attempt = folder / (lane + '-' + str(index))
                checked = audit.attempt(attempt, entry, frozen, observed, plain=lane == 'baseline')
                witness = row['execution']['witness']
                if lane == 'baseline':
                    assert witness is None
                else:
                    calls, count = (8, 4) if function == fixture.COUNTER else (1, 1)
                    assert witness['functions'] == {function: calls, 'otelc.action.wrapper': count, 'otelc.action.target': calls}
                    assert witness['spans'] == checked['spans'] and witness['pending'] == 0 and not any(witness['losses'].values())
                process = audit.read(attempt / 'process.json')
                records.append({**checked, 'folder': str(attempt), 'graphs': graphs,
                    'command_sha256': hashlib.sha256(json.dumps(process['argv']).encode()).hexdigest()})
    return records


def framework(workspace: Path, folder: Path, label: str, *, expected: int = 1) -> list[Path]:
    output = command([sys.executable, workspace / 'tests/test_equivalence.py'], folder, label, expected=expected)
    reports = [Path(json.loads(line)['report']) for line in output.splitlines()]
    assert len(reports) == (1 if expected == 0 or label.startswith('reduced') else 2)
    return reports


def routes(cli: Path, sdk: Path, root: Path, java: Path, profile: str) -> list[dict]:
    """Exercise retained/current workflows; record a route before checking its data."""
    main = root / 'main'
    workspace, source = prepare(cli, sdk, main, java, profile)
    original = audit.inventory(source)
    recorded = []
    def add(path: Path, **expectations) -> None:
        recorded.append({'report': str(path), **expectations})
        write(root / 'routes.json', recorded)
        check_report(path, **expectations)
    command([cli, 'run', '--workspace', workspace, '--report-dir', main / 'comparison'], main, 'run', expected=1)
    add(main / 'comparison/report.json', expected_cases=2)
    for path in framework(workspace, main, 'framework'):
        add(path, expected_cases=1)
    exported = main / 'exported'
    command([cli, 'export-tests', '--workspace', workspace, '--destination', exported, '--apply'], main, 'export')
    detached = main / 'application-detached';source.rename(detached)
    try:
        for path in framework(exported, main, 'detached'):
            add(path, expected_cases=1)
    finally:
        detached.rename(source)
    cases = audit.read(workspace / 'tests/corpus.json')
    for index, case in enumerate(cases):
        expected = int(case['function_id'] == next(row['id'] for row in audit.read(workspace / 'plan.json')['inventory']
                                                  if row['otelc_function'] == fixture.STATIC))
        value = json.loads(command([cli, 'replay', '--workspace', workspace, '--case', case['id']], main,
                                    'replay-' + str(index), expected=expected))
        add(Path(value['report']), expected_cases=1)
    promoted = main / 'promoted'
    command([cli, 'promote', '--workspace', workspace, '--source', source, '--destination', promoted, '--apply'], main, 'promote')
    environment = {'OTELEQ_SOURCE': str(source), 'OTELEQ_WORKSPACE_PARENT': str(main)}
    previous = {key: os.environ.get(key) for key in environment}
    original_work = (source / 'Work.java').read_bytes()
    try:
        os.environ.update(environment)
        for changed in (False, True):
            if changed:
                path = source / 'Work.java'
                text = path.read_text().replace('total=10', 'total=20').replace('return 7;', 'return 9;')
                path.write_text(text)
            output = command([sys.executable, '-I', '-B', promoted / 'test_equivalence.py'], main,
                             'promoted-changed' if changed else 'promoted', expected=1)
            reports = [json.loads(line) for line in output.splitlines() if 'report' in json.loads(line)]
            assert len(reports) == 2
            for row in reports:
                add(Path(row['report']), expected_cases=1, static_base=20 if changed else 10,
                    static_return=9 if changed else 7)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        (source / 'Work.java').write_bytes(original_work)
    target = next(row for row in audit.read(main / 'comparison/report.json')['cases'] if row['function'] == fixture.STATIC)
    reduced = main / 'shrink'
    command([cli, 'shrink', '--workspace', workspace, '--case', target['case'], '--report-dir', reduced,
             '--trials', '1'], main, 'shrink', expected=1)
    shrink = audit.read(reduced / 'shrink.json')
    assert shrink['reduced_arguments'] == [0] and shrink['status'] == 'candidate_rule_minimal'
    for path in [reduced / 'original/report.json', reduced / 'confirmation/report.json',
                 *[Path(row['report']) for row in shrink['trials']]]:
        add(path, expected_cases=1)
    retained = Path(shrink['workspace'])
    for path in framework(retained, main, 'reduced-framework'):
        add(path, expected_cases=1)
    value = json.loads(command([cli, 'replay', '--workspace', retained, '--case', target['case']], main,
                              'reduced-replay', expected=1))
    add(Path(value['report']), expected_cases=1)
    for start in (1, 2, 3):
        folder = root / ('startup-' + str(start))
        current, _ = prepare(cli, sdk, folder, java, profile, start=start, counter_only=True, source=source)
        command([cli, 'run', '--workspace', current, '--report-dir', folder / 'comparison'], folder, 'run')
        add(folder / 'comparison/report.json', expected_cases=1)
    assert audit.inventory(source) == original
    return recorded


def retained(root: Path, cli: Path) -> dict:
    """Every route is checked afresh; copies cannot inflate the launch denominator."""
    records = []
    routes_record = audit.read(root / 'routes.json')
    for row in routes_record:
        records.extend(check_report(Path(row['report']), **{key: value for key, value in row.items() if key != 'report'}))
    identities = {(row['pid'], row['command_sha256']) for row in records}
    assert len(records) == len(identities) == 80
    refusals = faults.qualify(root / 'main/comparison/report.json', root / 'refusals' if not (root / 'refusals').exists() else None)
    return {'schema_version': 1, 'kind': 'oteleq.java-generated-action-qualification',
            'claim': 'equivalence over these tests and observations', 'artefact_class': 'diagnostic',
            'cli_sha256': audit.sha(cli), 'profile': fixture.PROFILE, 'reports': len(routes_record),
            'distinct_application_launches': len(identities), 'complete_boundary_graphs': sum(row['graphs'] for row in records),
            'action_scopes': sum(row['scopes'] for row in records), 'spans': sum(row['spans'] for row in records),
            'altered_evidence_refusals': len(refusals),
            'source_preserved': True, 'scope': 'Selected private static and receiver calls, recursion, original error/aliases, four metric startup states, retained/replayed/reduced/current-source workflows'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--otelc-root', required=True, type=Path)
    parser.add_argument('--report-dir', required=True, type=Path)
    parser.add_argument('--cli', required=True, type=Path)
    parser.add_argument('--java-profile', choices=('safe-methods-v1', 'archive-methods-v1'), default='safe-methods-v1')
    parser.add_argument('--retained-only', action='store_true')
    args = parser.parse_args()
    if sys.flags.optimize:
        raise ValueError('qualification requires assertions; disable -O/PYTHONOPTIMIZE')
    sdk, cli = args.otelc_root.resolve(strict=True), args.cli.resolve(strict=True)
    root = args.report_dir.resolve()
    if not args.retained_only:
        assert not root.is_relative_to(sdk) and not root.is_relative_to(audit.REPO)
        root.mkdir(mode=0o700)
        java = Path(os.environ.get('OTELC_JAVA') or shutil.which('java')).resolve(strict=True)
        tools = {'java': java, 'javac': java.with_name('javac'), 'java-modules': java_build.module_image(java)}
        if args.java_profile == 'archive-methods-v1':
            tools['javap'] = java.with_name('javap')
        before = java_provider.artefacts(sdk, tools, args.java_profile, action=True)
        own = {name: audit.sha(Path(__file__).with_name(name)) for name in
               ('qualify_java_generated_actions.py', 'java_action_fixture.py', 'java_action_audit.py', 'java_action_faults.py')}
        identities = {'sdk': before, 'consumer': generation.generator_identity(), 'cli_sha256': audit.sha(cli),
                      'qualifier': own, 'python': sys.version, 'sdk_root': str(sdk), 'java_profile': args.java_profile}
        write(root / 'inputs.json', identities)
        os.environ['OTELEQ_PYTHON'] = sys.executable
        routes(cli, sdk, root, java, args.java_profile)
        assert java_provider.artefacts(sdk, tools, args.java_profile, action=True) == before
        assert generation.generator_identity() == identities['consumer'] and audit.sha(cli) == identities['cli_sha256']
        assert {name: audit.sha(Path(__file__).with_name(name)) for name in own} == own
    result = retained(root, cli)
    inputs = audit.read(root / 'inputs.json')
    assert inputs['java_profile'] == args.java_profile and inputs['cli_sha256'] == audit.sha(cli)
    result.update(consumer_inputs_sha256=inputs['consumer'], qualifier_sha256=inputs['qualifier'],
                  sdk_inputs_sha256=inputs['sdk'], python=inputs['python'])
    result['java_profile'] = args.java_profile
    write(root / 'qualification.json', result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
