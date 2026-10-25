"""Qualify native live metrics through generated and retained public workflows.

One matrix shard covers every declared normal, transient, recursive and supported
error workload for one language and initial metric state. Each original process,
source, frame, checkpoint, raw signal, reduction and promotion is checked against
caller-owned fixture expectations. Broader profiles and shipping remain separate.
"""

import argparse
import copy
from functools import partial
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import native_metric_cases as cases
import native_metric_receipt as raw
import native_prepared_receipt as retained
import qualification_storage
from qualify_native_lifetimes import command, digest, fixture_facts, source_facts, write
from otelc_capture import path_within

BASE_CALLS = (('selected', 42),)
PROMOTED_CALLS = (('selected', 43), ('selected_extra', 44))


def argument(value: object) -> int:
    assert type(value) is list and len(value) == 1 and type(value[0]) is int and 0 <= value[0] <= 5
    return value[0]


def observation(value: dict, contract: dict, entry: dict, steps: list[dict]) -> None:
    """Compare the complete typed observation, including every intermediate graph."""
    retained.same(value, {'observation_schema_version': 1, 'case_id': contract['case_id'],
        'function_id': entry['path'] + '::' + entry['otelc_function'], 'fixture_sha256': contract['fixture_sha256'],
        'fixture': {'status': 'ready'}, 'gaps': [], 'before': steps[0]['before'],
        'outcome': steps[-1]['outcome'], 'after': steps[-1]['after'], 'steps': steps})


class Audit:
    """Original request IDs count once; copied evidence keeps its original owner."""

    def __init__(self, root: Path, provider: Path, language: str, start: str):
        cases.validate(language, 'normal', start)
        self.root, self.provider, self.language, self.start = root, provider, language, start
        self.registry = retained.Oracle(root, provider)
        self.records, self.files, self.contexts, self.reports = {}, {}, {}, set()

    def mode(self, folder: Path) -> str:
        matches = [mode for mode in cases.MODES[self.language] if folder.is_relative_to(self.root / mode)]
        assert len(matches) == 1, 'attempt has no unique caller-owned workload'
        return matches[0]

    def attempt(self, report: Path, folder: Path, entry: dict, lane: str, witness,
                amount: int, function: str, version: int, repeat: int) -> None:
        original = self.registry.original(report)
        actual = original.parent / folder.relative_to(report.parent)
        mode = self.mode(actual)
        assert entry['language'] == self.language and cases.function(self.language, function) == entry['otelc_function']
        assert type(amount) is int and 0 <= amount <= 5
        assert type(repeat) is int and repeat in (0, 1) and actual.name == lane + '-' + str(repeat)
        checked = partial(raw.receipt, entry=entry, mode=mode, start=self.start, amount=amount, version=version)
        total = 4 * (amount + 1 if mode == 'recursive' else 1)
        retained.attempt(actual, entry, lane, witness, self.provider, [amount], receipt_check=checked,
            policy_check=partial(retained.policy, metric_flags=cases.schedule(self.start)[0]),
            health_check=partial(retained.health, functions=total))
        request = retained.read(actual / 'native-runtime/native-request.json')
        application = retained.read(actual / 'native-runtime/native-application-start.json')
        value = {'folder': str(actual), 'pid': application['pid'], 'plain': lane == 'baseline',
                 'mode': mode, 'start': self.start, 'language': self.language, 'amount': amount,
                 'function': function, 'version': version}
        retained.same(value, self.records.setdefault(request['launch_id'], value))
        self.reports.add(str(report))
        if lane != 'baseline':
            self.contexts.setdefault(request['launch_id'], {'folder': str(actual), 'entry': copy.deepcopy(entry),
                'mode': mode, 'start': self.start, 'amount': amount, 'version': version,
                'witness': copy.deepcopy(witness), 'repeat': repeat})
        for path in actual.rglob('*'):
            if path.is_file():
                facts = retained.identity(path, owned=True)
                retained.same(facts, self.files.setdefault(str(path), facts))
        for path in (original, original.parent / folder.parent.name / 'typed-bundle.json'):
            facts = retained.identity(path, owned=True)
            retained.same(facts, self.files.setdefault(str(path), facts))

    def finish(self) -> dict:
        for path, facts in self.files.items():
            retained.same(retained.identity(Path(path), owned=True), facts)
        expected = 28 * len(cases.MODES[self.language]) + 20
        assert len(self.records) == expected
        assert sum(not row['plain'] for row in self.records.values()) == expected // 2
        return {'actual_application_records': len(self.records), 'instrumented_receipts': expected // 2,
            'original_evidence_files_held': len(self.files), 'records': self.records,
            'reports': sorted(self.reports), 'copied_reports': sorted(self.registry.archived)}


def check_report(path: Path, audit: Audit, *, mode: str, amount: int = 5, function='selected', contracts=BASE_CALLS) -> int:
    report = retained.read(path)
    difference = mode == 'transient'
    assert report['source_preserved'] is True and report['blocked'] == []
    retained.same(report['exit_code'], int(difference))
    assert report['claim'] == 'equivalence over these tests and observations' and len(report['cases']) == 1
    result, = report['cases']; retained.same(result['exit_code'], int(difference))
    assert result['comparison']['verdict'] == ('different_observed' if difference else 'equivalent_observed')
    assert contracts in (BASE_CALLS, PROMOTED_CALLS) and function in dict(contracts)
    entries = [entry for entry in report['inventory'] if entry['status'] == 'ready']
    assert len(entries) == len(contracts) and {entry['language'] for entry in entries} == {audit.language}
    assert {entry['otelc_function'] for entry in entries} == {cases.function(audit.language, name) for name, _ in contracts}
    assert len({entry['id'] for entry in entries}) == len(entries)
    entry, = [entry for entry in entries if entry['otelc_function'] == cases.function(audit.language, function)]
    assert result['function'] == entry['otelc_function'] and result['case'] == entry['id'] + '-0'
    assert entry['native_backend'] == 'prepared' and entry['native_options']['profile'] == 'native-owned-v1'
    retained.same(entry['parameters'], ['int']); retained.same(entry['output'], 'int')
    assert len(entry['globals']) == 3 and {row['name'] for row in entry['globals']} == {'state', 'calls', 'depth'}
    configuration = cases.configuration(audit.language, mode, audit.start, audit.provider)
    retained.same(entry['sequence_configuration'], configuration['fixtures'][0]['sequence'])
    assert argument(result['arguments']) == amount
    typed = retained.read(path.parent / result['case'] / 'typed-bundle.json')
    bundle, = typed['cases']; contract = bundle['contract']
    assert re.fullmatch('[0-9a-f]{64}', contract['fixture_sha256'])
    roots = ['global:' + row['name'] for row in entry['globals']]
    retained.same(contract, {'case_id': result['case'], 'function_id': entry['path'] + '::' + entry['otelc_function'],
        'fixture_sha256': contract['fixture_sha256'], 'observation_schema_version': 1,
        'required_roots': roots, 'expected_baseline': {'kind': 'return'}, 'steps': [
            {'id': 'step-' + str(index), 'action': 'call', 'required_roots': roots,
             'expected_baseline': row['expected_baseline']} for index, row in enumerate(configuration['fixtures'][0]['sequence'])]})
    total = 4 * (amount + 1 if mode == 'recursive' else 1)
    retained.same(bundle['expected_functions'], {entry['path'] + '::' + entry['otelc_function']: total})
    retained.same(bundle['expected_spans'], total)
    for lane in ('baseline', 'instrumented_on'):
        assert len(bundle[lane]) == 2
        steps = cases.expected(audit.language, mode, amount, instrumented=lane == 'instrumented_on',
                               version=dict(contracts)[function])
        for index, attempt in enumerate(bundle[lane]):
            observation(attempt['observation'], contract, entry, steps)
            execution = attempt['execution']
            assert execution['capture_complete'] is True
            retained.same(execution['channels'], {'stdout': [], 'stderr': []})
            retained.same(execution['termination'], {'kind': 'exit', 'code': 0})
            audit.attempt(path, path.parent / result['case'] / (lane + '-' + str(index)), entry,
                          lane, execution['witness'], amount, function, dict(contracts)[function], index)
    return 4


def framework(workspace: Path, folder: Path, label: str, audit: Audit, mode: str, *, amount=5) -> None:
    output = command([sys.executable, '-I', '-B', workspace / 'tests/test_equivalence.py'], folder, label,
                     expected=int(mode == 'transient'))
    rows = [json.loads(line) for line in output.splitlines()]; assert len(rows) == 1
    check_report(Path(rows[0]['report']), audit, mode=mode, amount=amount)


def replay(cli: Path, workspace: Path, case: str, folder: Path, label: str, audit: Audit, mode: str, *, amount=5) -> None:
    output = command([cli, 'replay', '--workspace', workspace, '--case', case], folder, label,
                     expected=int(mode == 'transient'))
    check_report(Path(json.loads(output)['report']), audit, mode=mode, amount=amount)


def relocate(source: Path, changed: Path) -> bool:
    """The recursive fixture keeps opaque before/after depth reads in another unit."""
    database = changed / 'build/compile_commands.json'
    if not database.exists():
        return False
    rows = retained.read(database)
    assert type(rows) is list and len(rows) == 2
    for row in rows:
        assert row['directory'] == str(source / 'build')
        row['directory'] = str(changed / 'build')
    write(database, rows)
    return True


def promotion(cli: Path, workspace: Path, source: Path, folder: Path, audit: Audit, mode: str) -> dict:
    folder.mkdir(); held = fixture_facts(source)
    destination = folder / 'project-tests'
    argv = [cli, 'promote', '--workspace', workspace, '--source', source, '--destination', destination]
    planned = json.loads(command(argv, folder, 'promote-plan'))
    assert planned['mode'] == 'dry-run' and planned['files'] and not destination.exists()
    retained.same(fixture_facts(source), held)
    command([*argv, '--apply'], folder, 'promote-apply'); retained.same(fixture_facts(source), held)
    parent = folder / 'current-workspaces'; parent.mkdir()
    reports = []
    def current(application: Path, label: str, contracts: tuple) -> None:
        facts = fixture_facts(application); previous = set(audit.records)
        output = command([sys.executable, '-I', '-B', destination / 'test_equivalence.py'], folder, label,
            expected=int(mode == 'transient'), environment={'OTELEQ_SOURCE': str(application), 'OTELEQ_WORKSPACE_PARENT': str(parent)})
        rows = [json.loads(line) for line in output.splitlines()]
        assert len(rows) == len(contracts) + 1 and rows[0]['project_source'] == str(application)
        seen = []
        for row in rows[1:]:
            path = Path(row['report']); assert path.is_relative_to(parent) and path.name == 'report.json'
            function = retained.read(path)['cases'][0]['function']
            name, = [name for name, _ in contracts if cases.function(audit.language, name) == function]
            check_report(path, audit, mode=mode, function=name, contracts=contracts)
            seen.append(name); reports.append(str(path))
        assert sorted(seen) == sorted(name for name, _ in contracts)
        assert len(set(audit.records) - previous) == 4 * len(contracts)
        retained.same(fixture_facts(application), facts)
    current(source, 'current-original', BASE_CALLS)
    changed = folder / 'current-source'; shutil.copytree(source, changed)
    unit = changed / ('app.cpp' if audit.language == 'cpp' else 'app.c')
    unit.write_text(cases.source(audit.language, mode, changed=True))
    relocated = relocate(source, changed)
    assert relocated is (mode == 'recursive')
    current(changed, 'current-changed', PROMOTED_CALLS)
    assert len(reports) == 3
    return {'reports': reports, 'fresh_current_source': True, 'original_calls': dict(BASE_CALLS),
            'changed_calls': dict(PROMOTED_CALLS), 'relocated_compilation_database': relocated}


def reduction(cli: Path, workspace: Path, case: str, folder: Path, audit: Audit) -> None:
    previous = set(audit.records)
    reduced = folder / 'shrinking'
    command([cli, 'shrink', '--workspace', workspace, '--case', case, '--report-dir', reduced, '--trials', '8'],
            folder, 'shrink', expected=1)
    summary = retained.read(reduced / 'shrink.json')
    retained.same(summary['original_arguments'], [5]); retained.same(summary['reduced_arguments'], [0])
    assert summary['status'] == 'candidate_rule_minimal' and summary['source_preserved'] is True
    assert len(summary['trials']) == 1 and summary['incomplete_trials'] == 0
    check_report(reduced / 'original/report.json', audit, mode='transient')
    check_report(reduced / 'confirmation/report.json', audit, mode='transient', amount=0)
    for trial in summary['trials']:
        assert argument(trial['arguments']) == 0
        check_report(Path(trial['report']), audit, mode='transient', amount=0)
    assert len(set(audit.records) - previous) == 12
    replay_workspace = Path(summary['workspace'])
    framework(replay_workspace, folder, 'reduced-framework', audit, 'transient', amount=0)
    replay(cli, replay_workspace, case, folder, 'reduced-replay', audit, 'transient', amount=0)
    assert len(set(audit.records) - previous) == 20


def exercise(cli: Path, provider: Path, sdk: Path, root: Path, language: str, start: str) -> dict:
    audit = Audit(root, provider, language, start); results = []
    for mode in cases.MODES[language]:
        folder = root / mode; folder.mkdir()
        source, config = cases.fixture(folder, language, mode, start, sdk); original = fixture_facts(source)
        workspace = Path(command([cli, 'plan', '--source', source, '--otelc-root', provider,
            '--workspace-parent', folder, '--config', config], folder, 'plan'))
        command([cli, 'generate', '--workspace', workspace], folder, 'generate')
        comparison = folder / 'comparison'; previous = set(audit.records)
        command([cli, 'run', '--workspace', workspace, '--report-dir', comparison], folder, 'run',
                expected=int(mode == 'transient'))
        check_report(comparison / 'report.json', audit, mode=mode)
        framework(workspace, folder, 'generated-framework', audit, mode)
        case = retained.read(comparison / 'report.json')['cases'][0]['case']
        replay(cli, workspace, case, folder, 'replay', audit, mode)
        exported = folder / 'exported'
        command([cli, 'export-tests', '--workspace', workspace, '--destination', exported, '--apply'], folder, 'export')
        promoted = promotion(cli, workspace, source, folder / 'promotion', audit, mode)
        retained.same(fixture_facts(source), original); shutil.rmtree(source)
        framework(exported, folder, 'detached-framework', audit, mode)
        assert len(set(audit.records) - previous) == 28
        if mode == 'transient':
            reduction(cli, exported, case, folder, audit)
        results.append({'mode': mode, 'promotion': promoted})
    from native_metric_refusals import refusals
    refused = refusals(audit, root / 'raw-evidence-refusals')
    return {'claim': 'equivalence over these tests and observations', 'language': language, 'start': start,
        'workloads': results, 'audit': audit.finish(), 'raw_evidence_refusals': refused,
        'consumer_cli_sha256': digest(cli), 'sdk_source': cases.SDK_HEAD,
        'routes': ['generated', 'framework', 'replay', 'detached', 'scalar-reduction', 'current-source-promotion'],
        'scope': 'selected free-function diagnostic workflows; no receivers, lifetime/resource live controls or shipping admission'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--otelc-root', type=Path, required=True)
    parser.add_argument('--sdk-build', type=Path, required=True)
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--language', choices=tuple(cases.MODES), required=True)
    parser.add_argument('--start', choices=cases.STARTS, required=True)
    parser.add_argument('--min-free-bytes', type=int, default=qualification_storage.MIN_FREE_BYTES)
    args = parser.parse_args()
    provider, cli = args.otelc_root.resolve(strict=True), args.cli.resolve(strict=True)
    consumer = Path(__file__).resolve().parents[1]
    root, sdk = args.report_dir.resolve(), args.sdk_build.resolve()
    assert not root.exists() and not sdk.exists() and root != sdk
    assert not any(path_within(root, path) or path_within(sdk, path) for path in (provider, consumer))
    assert not path_within(root, sdk) and not path_within(sdk, root)
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=provider).decode().strip() == cases.SDK_HEAD
    for source in (provider, consumer):
        assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=source).strip(), 'source checkout is dirty'
    root.mkdir(mode=0o700, parents=True)
    held = {str(source): source_facts(source) for source in (provider, consumer)}
    original_cli = retained.identity(cli); write(root / 'original-source-facts.json', held)
    os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli), PYTHONDONTWRITEBYTECODE='1')
    with qualification_storage.budget(args.min_free_bytes):
        command([sys.executable, '-B', '-m', 'otelc.native_launch', '--output', sdk], root, 'sdk-build',
                environment={'PYTHONPATH': str(provider)})
        library = 'libotelc_native_runtime.dylib' if sys.platform == 'darwin' else 'libotelc_native_runtime.so'
        products = {str(path): retained.identity(path) for path in (sdk / 'native-sdk-build.json', sdk / library)}
        assert retained.read(sdk / 'native-sdk-build.json')['coverage'] is False
        write(root / 'sdk-original-products.json', products)
        result = exercise(cli, provider, sdk, root, args.language, args.start)
        retained.same({str(source): source_facts(source) for source in map(Path, held)}, held)
        retained.same({name: retained.identity(Path(name)) for name in products}, products)
        retained.same(retained.identity(cli), original_cli)
        result['consumer_source'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=consumer).decode().strip()
        write(root / 'qualification.json', result); print(json.dumps(result))


if __name__ == '__main__':
    main()
