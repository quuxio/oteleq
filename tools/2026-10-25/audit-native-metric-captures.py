"""Audit archived metric file bytes without recreating missing runner directories."""

from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
import sys
import tarfile
import tomllib
import zipfile

BASE = Path('/Users/sclarke/github/oteleq-qualification')
BUILD = BASE / '2026-10-25/native-metric-controls/hosted-9f90307'
SOURCE = BASE / 'work/oteleq-native-metric-histograms'
RUNNER = Path('/home/runner/work/_temp/native-metric-evidence')
HEAD = '9f9030747c62fcf0c1ffbab5d010b36e58b77921'
SDK_HEAD = 'acb13d7735526448209df37b7e6b98e5717befdb'
sys.path.insert(0, str(SOURCE / 'tests'))
import native_metric_cases as cases
import native_metric_frames as frames
import native_metric_health as health
import native_metric_otlp as otlp
import native_metric_receipt as controls
import native_metric_refusals as mutants
import native_prepared_otlp as wire
import native_prepared_receipt as records
import qualify_native_metrics as driver


def file_hash(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def raw_frames(folder: Path, entry: dict, expected: list) -> None:
    """Check every archived frame/nonce file; empty flag directories are unavailable."""
    container = frames.loads((folder / 'observation').read_bytes())
    records.same(sorted(container), ['frames', 'kind', 'schema_version'])
    records.same(container['kind'], 'oteleq.native.scalar-sequence')
    records.same(container['schema_version'], 1)
    assert len(container['frames']) == len(expected) == 4
    rendezvous = folder / 'native-rendezvous'
    phases = [name + '-' + str(i) for i in range(4) for name in ('before', 'after')] + ['finish']
    names = {phase + '.' + action + '.json' for phase in phases for action in ('ready', 'resume')}
    names.update('step-' + str(i) + '.observation' for i in range(4))
    assert {path.name for path in rendezvous.iterdir()} == names
    nonce = None
    for phase in phases:
        for action in ('ready', 'resume'):
            value = records.read(rendezvous / (phase + '.' + action + '.json'))
            assert type(value.get('nonce')) is str and re.fullmatch('[a-f0-9]{32}', value['nonce'])
            nonce = value['nonce'] if nonce is None else nonce
            records.same(value, {'nonce': nonce, 'phase': phase})
    for index, (value, step) in enumerate(zip(container['frames'], expected, strict=True)):
        records.same(sorted(value), ['id', 'raw_hex'])
        records.same(value['id'], 'step-' + str(index))
        raw = (rendezvous / ('step-' + str(index) + '.observation')).read_bytes()
        records.same(value['raw_hex'], raw.hex())
        frames.frame(raw, entry, step)


class HistoricalAudit:
    """Bind original launch/image/file bytes while treating kernel/stat facts as data."""

    def __init__(self, root: Path, bundle: zipfile.ZipFile, original: dict, start: str):
        self.root, self.bundle, self.original = root, bundle, original
        self.start, self.language = start, original['language']
        self.provider = Path('/home/runner/work/oteleq/oteleq/provider')
        self.seen, self.contexts, self.observations = {}, {}, Counter()
        self.copied_observations = 0
        self.metrics = Counter()
        self.image_hashes = {}

    def member(self, folder: Path, suffix: str) -> str:
        return 'native-metric-evidence/' + (folder.relative_to(self.root) / suffix).as_posix()

    def bytes_identity(self, value: dict, folder: Path, suffix: str) -> None:
        expected = RUNNER / folder.relative_to(self.root) / suffix
        assert value['path'] == value['resolved_path'] == str(expected)
        assert set(value) == {'path', 'resolved_path', 'sha256', 'size', 'device', 'inode',
                              'mode', 'uid', 'gid', 'mtime_ns', 'ctime_ns', 'links'}
        assert all(type(value[key]) is int for key in set(value) - {'path', 'resolved_path', 'sha256'})
        assert stat.S_ISREG(value['mode']) and value['links'] >= 1
        name = self.member(folder, suffix)
        if name not in self.image_hashes:
            with self.bundle.open(name) as stream:
                self.image_hashes[name] = hashlib.file_digest(stream, 'sha256').hexdigest()
        assert value['sha256'] == self.image_hashes[name]
        assert value['size'] == self.bundle.getinfo(name).file_size

    def process(self, folder: Path, entry: dict, plain: bool, amount: int) -> tuple[dict, dict]:
        runtime = folder / 'native-runtime'
        request, plan = records.read(runtime / 'native-request.json'), records.read(runtime / 'native-plan.json')
        app = records.read(runtime / 'native-application-start.json')
        supervisor = records.read(runtime / 'native-supervisor-start.json')
        pid, owner = app['pid'], supervisor['pid']
        assert all(type(x) is int and 1 < x < 2**31 for x in (pid, owner, supervisor['parent_pid'])) and pid != owner
        self.bytes_identity(request['build'], folder, 'native-build/native-source-build.json')
        policy = tomllib.loads((folder / 'policy.toml').read_text())
        records.policy(policy, entry, metric_flags=cases.schedule(self.start)[0])
        original_runtime = str(RUNNER / folder.relative_to(self.root) / 'native-runtime')
        records.same(request, {'schema_version': 1, 'kind': 'otelc.native.request', 'profile': records.PROFILE,
            'build': request['build'], 'arguments': [], 'runtime': original_runtime, 'plain': plain,
            'policy': policy, 'wait_ms': 30000, 'launch_id': request['launch_id']})
        assert re.fullmatch('[0-9a-f]{32}', request['launch_id'])
        image = app['image']
        self.bytes_identity(image, folder, 'native-build/' + ('plain' if plain else 'instrumented'))
        records.same(app, {'schema_version': 1, 'kind': 'otelc.native.application', 'pid': pid,
            'parent_pid': owner, 'process_group': pid, 'session': pid, 'launch_id': request['launch_id'],
            'supervisor_pid': owner, 'image': image, 'phase': 'waiting_exec', 'source_complete': False})
        records.same(supervisor, {'schema_version': 1, 'kind': 'otelc.native.supervisor', 'pid': owner,
            'parent_pid': supervisor['parent_pid'], 'process_group': owner, 'session': owner, 'launch_id': request['launch_id']})
        records.same(plan, {'schema_version': 1, 'kind': 'otelc.native.plan', 'profile': records.PROFILE,
            'request_sha256': records.digest(request), 'cwd': str(RUNNER / folder.relative_to(self.root) / 'project'),
            'argv': [image['path']], 'image': image, 'source_complete': False})
        prepared = records.read(runtime / 'native-prepared.json')
        process = records.read(folder / 'process.json')
        command = process['argv']
        assert command == [prepared['interpreter_spelling'], '-I', '-S',
                           str(self.provider / 'otelc/native_supervisor.py'), original_runtime]
        records.same(records.read(folder / 'command.json'), command)
        records.same(process['pid'], owner)
        assert prepared['request_sha256'] == records.digest(request) and prepared['plan_sha256'] == records.digest(plan)
        records.same(records.read(runtime / 'native-host-release.json'), {'schema_version': 1,
            'kind': 'otelc.native.host-release', 'launch_id': request['launch_id'], 'pid': pid, 'supervisor_pid': owner})
        records.same(records.read(runtime / 'oteleq-native-finish.json'), {'schema_version': 1,
            'kind': 'oteleq.native.owned-finish', 'supervisor_pid': owner, 'application_pid': pid,
            'application_exit_code': 0, 'sdk_pid': None if plain else pid,
            'scope': 'owned completion; direct downstream telemetry qualification remains separate'})
        final = records.read(runtime / 'native-execution.json')
        checkpoint = None if plain else records.read(runtime / 'app/health.json')
        records.same(final, {'schema_version': 1, 'kind': 'otelc.native.execution', 'profile': records.PROFILE,
            'request_sha256': records.digest(request), 'plan_sha256': records.digest(plan), 'supervisor': supervisor,
            'application': app, 'released': True, 'process_exit_code': 0, 'supervisor_exit_code': 0,
            'inputs_rechecked': True, 'sdk_health': checkpoint, 'failures': {}, 'exec_verified': False, 'source_complete': False})
        caller = records.read(folder / 'native-caller/caller.json')
        records.same(caller['entry'], entry); records.same(caller['arguments'], [amount])
        records.same(caller['kind'], 'oteleq.native.caller'); records.same(caller['schema_version'], 1)
        return app, policy

    def receipt(self, folder: Path, entry: dict, plain: bool, mode: str, amount: int, version: int) -> dict | None:
        app, policy = self.process(folder, entry, plain, amount)
        bodies = wire.payloads(folder, records.read)
        expected = cases.expected(self.language, mode, amount, instrumented=not plain, version=version)
        raw_frames(folder, entry, expected)
        record = records.read(folder / 'native-controls.json')
        controls.publications(folder, record)
        checked = controls.controls(record, bodies, entry, self.start, mode, amount, policy,
                                    app['pid'], app['supervisor_pid'], plain=plain)
        if plain:
            assert not bodies and not (folder / 'native-verified-controls.json').exists()
            assert not (folder / 'native-runtime/app/health.json').exists()
            return None
        service, name = policy['resource']['service_name'], checked.name
        spans = otlp.traces(bodies, self.language, service, name, checked.calls, failed=checked.failed)
        points = otlp.metrics(bodies, self.language, service, name, checked.collected, checked.errors)
        final = records.read(folder / 'native-runtime/app/health.json')
        traces = sum(route == '/v1/traces' for route, _ in bodies)
        metrics = len(bodies) - traces
        records.health(final, policy, self.language, app['pid'], points, traces, metrics, functions=spans)
        health.progress([*checked.snapshots, final])
        witness = otlp.witness(bodies, name, spans)
        records.same(records.read(folder / 'native-verified-controls.json'), {**witness,
            'collected_functions': {name: checked.collected},
            'collected_errors': {name: checked.errors} if checked.errors else {}, 'metric_points': points, 'health': final})
        return {'witness': witness, 'spans': spans, 'metric_points': points,
                'trace_requests': traces, 'metric_requests': metrics}

    def attempt(self, report, folder, entry, lane, witness, amount, function, version, repeat):
        request = records.read(folder / 'native-runtime/native-request.json')
        launch = request['launch_id']
        original = self.original['audit']['records'][launch]
        actual = self.root / Path(original['folder']).relative_to(RUNNER)
        mode = actual.relative_to(self.root).parts[0]
        assert mode in cases.MODES[self.language] and entry['language'] == self.language
        assert actual.name == lane + '-' + str(repeat)
        assert entry['otelc_function'] == cases.function(self.language, function)
        result = self.receipt(actual, entry, lane == 'baseline', mode, amount, version)
        records.same(witness, None if result is None else result['witness'])
        records.same(original, {'folder': str(RUNNER / actual.relative_to(self.root)),
            'pid': records.read(actual / 'native-runtime/native-application-start.json')['pid'],
            'plain': lane == 'baseline', 'mode': mode, 'start': self.start, 'language': self.language,
            'amount': amount, 'function': function, 'version': version})
        if folder != actual:
            # The copied report must carry the same raw frame, checkpoint and telemetry bytes.
            records.same(self.receipt(folder, entry, lane == 'baseline', mode, amount, version), result)
            self.copied_observations += 1
        if launch not in self.seen:
            self.seen[launch] = result
            if result is not None:
                self.metrics.update({key: result[key] for key in ('spans', 'metric_points', 'trace_requests', 'metric_requests')})
                self.contexts[launch] = {'folder': str(actual), 'entry': copy.deepcopy(entry), 'mode': mode,
                    'start': self.start, 'amount': amount, 'version': version, 'witness': witness, 'repeat': repeat}
        else:
            records.same(self.seen[launch], result)
        self.observations[mode] += 1


def main(start: str) -> None:
    index = records.read(BUILD / ('c-' + start + '-selected-index-02.json'))
    selected = Path(index['root'])
    root = selected / 'native-metric-evidence'
    output = BUILD / ('c-' + start + '-raw-audit-01'); output.mkdir()
    assert file_hash(Path(index['archive'])) == index['archive_sha256']
    for name, value in index['files'].items():
        assert file_hash(selected / name) == value['sha256']
    original = records.read(root / 'qualification.json')
    assert original['consumer_source'] == HEAD and original['sdk_source'] == SDK_HEAD
    assert original['language'] == 'c' and original['start'] == start
    assert original['audit']['actual_application_records'] == 104
    with zipfile.ZipFile(index['archive']) as bundle:
        audit = HistoricalAudit(root, bundle, original, start)
        promoted = {}
        for row in original['workloads']:
            assert row['mode'] in cases.MODES['c']
            promotion = row['promotion']
            assert promotion['fresh_current_source'] is True
            records.same(promotion['original_calls'], dict(driver.BASE_CALLS))
            records.same(promotion['changed_calls'], dict(driver.PROMOTED_CALLS))
            assert promotion['relocated_compilation_database'] is (row['mode'] == 'recursive')
            names = []
            for position, report in enumerate(promotion['reports']):
                path = root / Path(report).relative_to(RUNNER)
                promoted[path] = driver.BASE_CALLS if position == 0 else driver.PROMOTED_CALLS
                names.append(records.read(path)['cases'][0]['function'])
            assert names == ['selected', 'selected', 'selected_extra'] and len(names) == 3
        reports = sorted(root.rglob('report.json')); assert len(reports) == 27 and len(promoted) == 9
        for path in reports:
            relative = path.relative_to(root)
            mode = relative.parts[0]
            amount = 0 if relative.parts[1] == 'shrinking' and relative.parts[2] != 'original' else 5
            contracts = promoted.get(path, driver.BASE_CALLS)
            function = records.read(path)['cases'][0]['function']
            driver.check_report(path, audit, mode=mode, amount=amount, function=function, contracts=contracts)
        assert set(audit.seen) == set(original['audit']['records']) and len(audit.seen) == 104
        assert sum(value is not None for value in audit.seen.values()) == 52
        assert sum(audit.observations.values()) == 108 and audit.copied_observations == 4
        rejected = mutants.refusals(audit, output / 'fresh-altered-captures')
        assert sum(value['count'] for value in rejected.values()) == 42
    for name, value in index['files'].items():
        assert file_hash(selected / name) == value['sha256']
    result = {'status': 'pass for original captured bytes and declared metric workload observations',
        'head': HEAD, 'language': 'c', 'start': start, 'archive_sha256': index['archive_sha256'],
        'distinct_application_records': len(audit.seen), 'instrumented_receipts': 52,
        'archived_reports_audited': len(reports), 'original_controller_visited_report_paths': len(original['audit']['reports']),
        'promotion_reports': len(promoted), 'observations': dict(audit.observations),
        'copied_observations_not_new_launches': audit.copied_observations,
        'complete_raw_totals': dict(audit.metrics), 'actual_altered_capture_refusals': 42,
        'selected_original_files_preserved': index['selected_members'], 'new_application_launches': 0,
        'compiler_builds': 0, 'sdk_builds': 0,
        'limits': ['Original runner kernel/UID/inode/time facts are historical data, not recertified on this Mac.',
            'GitHub ZIP omitted empty rendezvous flag directories. All22original nonce/frame files and9host snapshots are checked; no missing directories were invented.',
            'Original app image and build-record bytes are rehashed from ZIP; interpreter/system LLVM library bytes are not recertified.',
            'This is a partial matrix audit of one C startup state, not admission of all8shards/944applications or shipping artefacts.']}
    path = output / 'review.json'; path.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main(sys.argv[1])
