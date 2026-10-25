"""Independent native ownership, original-file and downstream fixture receipts."""

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tomllib

from native_prepared_otlp import BOUNDS, receipt, require, same

PROFILE = 'native-owned-v1'
LANES = ('baseline-0', 'baseline-1', 'instrumented_on-0', 'instrumented_on-1')


def read(path: Path) -> dict:
    """Duplicate keys and nonfinite JSON cannot repair an otherwise invalid record."""
    def unique(rows):
        result = {}
        for key, value in rows:
            require(key not in result, 'duplicate JSON field')
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError('native qualification: nonfinite JSON ' + value)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 32 * 1024**2, 'invalid JSON evidence file')
    return json.loads(path.read_bytes(), object_pairs_hook=unique, parse_constant=nonfinite)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def identity(path: Path, *, private: bool = False, owned: bool = False) -> dict:
    """Only caller-known original paths supply physical publication facts."""
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink()
            and path.resolve(strict=True) == path, 'nonordinary original evidence')
    require(not (owned or private) or info.st_uid == os.getuid(), 'foreign owned evidence')
    if private:
        require(stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1, 'invalid private publication')
    with path.open('rb') as stream:
        sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(path), 'resolved_path': str(path), 'sha256': sha256, 'size': info.st_size,
            'device': info.st_dev, 'inode': info.st_ino, 'mode': info.st_mode, 'uid': info.st_uid,
            'gid': info.st_gid, 'mtime_ns': info.st_mtime_ns, 'ctime_ns': info.st_ctime_ns, 'links': info.st_nlink}


def archive(original: Path, copied: Path) -> None:
    """Match every copied byte/kind/mode before consulting original file identities."""
    def manifest(root):
        require(root.is_dir() and root.resolve(strict=True) == root, 'noncanonical report tree')
        require(root.stat().st_uid == os.getuid(), 'foreign report root')
        result = {'.': (None, None, root.stat().st_mode)}
        def failed(error):
            raise error
        for current, directories, files in os.walk(root, followlinks=False, onerror=failed):
            for name in directories + files:
                path = Path(current) / name; info = path.lstat()
                require(not path.is_symlink() and info.st_uid == os.getuid(), 'foreign report tree entry')
                if stat.S_ISDIR(info.st_mode):
                    result[str(path.relative_to(root)) + '/'] = (None, None, info.st_mode)
                else:
                    require(stat.S_ISREG(info.st_mode), 'special report tree entry')
                    with path.open('rb') as stream:
                        sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
                    result[str(path.relative_to(root))] = (sha256, info.st_size, info.st_mode)
        return result
    require(original != copied and not original.is_relative_to(copied) and not copied.is_relative_to(original),
            'archive must be independent of original')
    same(manifest(original), manifest(copied))


def policy(value: dict, entry: dict) -> None:
    service = value['resource']['service_name']; endpoint = value['export']['endpoint']
    require(re.fullmatch(r'oteleq-gen-[0-9a-f]{32}', service) is not None, 'unbound generated service')
    match = re.fullmatch(r'http://127\.0\.0\.1:([1-9][0-9]{0,4})', endpoint)
    require(match is not None and int(match[1]) <= 65535, 'foreign telemetry endpoint')
    same(value, {'schema_version': 3, 'languages': [entry['language']], 'resource': {'service_name': service},
        'export': {'endpoint': endpoint, 'interval_ms': 1000, 'timeout_ms': 1000, 'shutdown_timeout_ms': 10000},
        'sources': {'include': [entry['path']], 'exclude': []},
        'functions': {'include': [entry['otelc_function']], 'exclude': []},
        'metrics': {'collection': True, 'emission': True, 'histogram_boundaries_seconds': BOUNDS},
        'traces': {'enabled': True, 'sample_ratio': 1.0},
        'lifetimes': {'enabled': False, 'include': [], 'exclude': [], 'max_live': 4096, 'release_methods': ['close']},
        'context': {'tasks': False, 'http': False}, 'benchmark': {'iterations': 10000, 'samples': 15, 'warmup': 5}})


def exports(value: dict, unit: str, units: int, requests: int) -> None:
    same(sorted(value), sorted(('unit', 'exporters_observed', 'batches_started', 'batches_succeeded',
                               'batches_failed', 'batches_pending', 'units_started', 'units_succeeded', 'units_failed')))
    same(value['unit'], unit); same(value['exporters_observed'], 1)
    for key in ('batches_started', 'batches_succeeded', 'batches_failed', 'batches_pending',
                'units_started', 'units_succeeded', 'units_failed'):
        require(type(value[key]) is str and re.fullmatch(r'0|[1-9][0-9]{0,19}', value[key]) is not None,
                'invalid SDK export counter')
    same(value['batches_started'], value['batches_succeeded'])
    require(int(value['batches_succeeded']) >= requests, 'SDK API exports cannot explain HTTP requests')
    same([value[key] for key in ('batches_failed', 'batches_pending', 'units_failed')], ['0', '0', '0'])
    same(value['units_started'], str(units)); same(value['units_succeeded'], str(units))


def health(value: dict, expected_policy: dict, language: str, pid: int, points: int, traces: int, metrics: int) -> None:
    """Keep unavailable dimensions visible and bind final SDK units to raw receipt."""
    expected = {'schema_version': 1, 'kind': 'otelc.runtime-health', 'language': language, 'pid': pid,
        'phase': 'final', 'scope': 'sdk_pipeline', 'sdk_attached': True, 'source_complete': False,
        'policy_sha256': digest(expected_policy),
        'selection_sha256': digest({key: expected_policy[key] for key in ('sources', 'functions')}),
        'controls': {'schema_version': 1, 'pid': pid, 'collection': True, 'emission': True, 'effective_emission_off': False},
        'lifecycle': {'flush': 'succeeded', 'shutdown': 'succeeded'},
        'function_accounting': {'registered': '1', 'started': '1', 'ended': '1', 'active': '0', 'closed': True,
                                'lost': '0', 'invalid': '0', 'metadata_errors': '0'},
        'span_accounting': {'sampled_started': '1', 'sampled_ended': '1', 'sampled_active': '0',
            'queue_dropped': '0', 'queue_pending': '0', 'queue_evidence': 'derived_after_shutdown',
            'processors_observed': 1, 'batch_processors_observed': 1},
        'trace_exports': value['trace_exports'], 'metric_exports': value['metric_exports'],
        'metric_flush': value['metric_flush'], 'diagnostics': {'dropped': '0'},
        'downstream_receipt': 'unavailable', 'otlp_partial_rejection': 'unavailable'}
    same(value, expected)
    same(sorted(value['metric_flush']), ['attempts', 'failed_attempts'])
    require(type(value['metric_flush']['attempts']) is str
            and re.fullmatch(r'[1-9][0-9]{0,19}', value['metric_flush']['attempts']) is not None, 'no final SDK flush')
    same(value['metric_flush']['failed_attempts'], '0')
    exports(value['trace_exports'], 'spans', 1, traces)
    exports(value['metric_exports'], 'metric_points', points, metrics)


def attempt(folder: Path, entry: dict, lane: str, witness, provider: Path, arguments: list) -> None:
    """Independently join fixed commands, original images, host ownership and signals."""
    runtime = folder / 'native-runtime'; plain = lane == 'baseline'
    request, plan = read(runtime / 'native-request.json'), read(runtime / 'native-plan.json')
    prepared = read(runtime / 'native-prepared.json')
    final = read(runtime / 'native-execution.json')
    supervisor = read(runtime / 'native-supervisor-start.json')
    application = read(runtime / 'native-application-start.json')
    started, finished = read(runtime / 'oteleq-native-start.json'), read(runtime / 'oteleq-native-finish.json')
    process = read(folder / 'process.json')
    expected_policy = tomllib.loads((folder / 'policy.toml').read_text()); policy(expected_policy, entry)
    require(re.fullmatch(r'[0-9a-f]{32}', request['launch_id']) is not None, 'invalid launch identity')
    same(request, {'schema_version': 1, 'kind': 'otelc.native.request', 'profile': PROFILE,
        'build': identity(folder / 'native-build/native-source-build.json', owned=True),
        'arguments': [], 'runtime': str(runtime), 'plain': plain, 'policy': expected_policy,
        'wait_ms': 30000, 'launch_id': request['launch_id']})
    pid, owner = application['pid'], supervisor['pid']
    require(all(type(value) is int and 1 < value < 2**31 for value in (pid, owner, supervisor['parent_pid']))
            and pid != owner, 'invalid owned process IDs')
    command = process['argv']
    require(len(command) == 5 and command[0] == str(Path(sys.executable).absolute())
            and command[1:] == ['-I', '-S', str(provider / 'otelc/native_supervisor.py'), str(runtime)],
            'metadata-selected supervisor command')
    same(read(folder / 'command.json'), command); same(process['pid'], owner)
    same(supervisor, {'schema_version': 1, 'kind': 'otelc.native.supervisor', 'pid': owner,
         'parent_pid': supervisor['parent_pid'], 'process_group': owner, 'session': owner, 'launch_id': request['launch_id']})
    image = identity(folder / 'native-build' / ('plain' if plain else 'instrumented'), owned=True)
    same(application, {'schema_version': 1, 'kind': 'otelc.native.application', 'pid': pid, 'parent_pid': owner,
        'process_group': pid, 'session': pid, 'launch_id': request['launch_id'], 'supervisor_pid': owner,
        'image': image, 'phase': 'waiting_exec', 'source_complete': False})
    same(plan, {'schema_version': 1, 'kind': 'otelc.native.plan', 'profile': PROFILE,
        'request_sha256': digest(request), 'cwd': str(folder / 'project'), 'argv': [image['path']],
        'image': image, 'source_complete': False})
    producers = sorted((provider / 'otelc').glob('*.py'))
    require(10 <= len(producers) <= 4096 and provider / 'otelc/native_supervisor.py' in producers,
            'incomplete native producer catalogue')
    same(prepared, {'schema_version': 1, 'kind': 'otelc.native.prepared', 'profile': PROFILE,
         'request_sha256': digest(request), 'plan_sha256': digest(plan),
         'interpreter': identity(Path(sys.executable).resolve(strict=True)), 'interpreter_spelling': command[0],
         'producer': [identity(path) for path in producers], 'source_complete': False})
    for name in ('native-request.json', 'native-plan.json', 'native-prepared.json', 'native-host-release.json'):
        identity(runtime / name, private=True)
    same(started, {'schema_version': 1, 'kind': 'oteleq.native.owned-start',
        'supervisor': {key: supervisor[key] for key in ('pid', 'parent_pid', 'process_group', 'session')},
        'application': {key: application[key] for key in ('pid', 'parent_pid', 'process_group', 'session')},
        'records': [identity(runtime / name, private=True) for name in ('native-supervisor-start.json', 'native-application-start.json')]})
    same(read(runtime / 'native-host-release.json'), {'schema_version': 1, 'kind': 'otelc.native.host-release',
         'launch_id': request['launch_id'], 'pid': pid, 'supervisor_pid': owner})
    same(finished, {'schema_version': 1, 'kind': 'oteleq.native.owned-finish', 'supervisor_pid': owner,
        'application_pid': pid, 'application_exit_code': 0, 'sdk_pid': None if plain else pid,
        'scope': 'owned completion; direct downstream telemetry qualification remains separate'})
    service = expected_policy['resource']['service_name']
    expected, points, traces, metrics = receipt(folder, read, entry['language'], service,
        entry['path'] + '::' + entry['otelc_function'], plain=plain)
    same(witness, expected)
    checkpoint = None if plain else read(runtime / 'app/health.json')
    if plain:
        require(not (runtime / 'app/health.json').exists(), 'plain application has SDK health')
    else:
        identity(runtime / 'app/health.json', private=True)
        health(checkpoint, expected_policy, entry['language'], pid, points, traces, metrics)
    same(final, {'schema_version': 1, 'kind': 'otelc.native.execution', 'profile': PROFILE,
        'request_sha256': digest(request), 'plan_sha256': digest(plan), 'supervisor': supervisor, 'application': application,
        'released': True, 'process_exit_code': 0, 'supervisor_exit_code': 0, 'inputs_rechecked': True,
        'sdk_health': checkpoint, 'failures': {}, 'exec_verified': False, 'source_complete': False})
    for name in ('native-after-build-inputs', 'native-after-execution-inputs'):
        require((folder / name).is_dir(), 'missing compiler semantic recheck')
    caller = read(folder / 'native-caller/caller.json')
    same(caller['entry'], entry); same(caller['arguments'], arguments)
    same(caller['kind'], 'oteleq.native.caller'); same(caller['schema_version'], 1)
    same(caller['source_complete'], False)


def refusals(root: Path, folder: Path, entry: dict, witness: dict, provider: Path, arguments: list) -> int:
    """Alter separate values/captures from a real completed call; never its originals."""
    root.mkdir()
    rejected = []

    def rejects(name, operation):
        try:
            operation()
        except ValueError:
            rejected.append(name)
        else:
            raise AssertionError('altered native evidence was accepted: ' + name)

    for field, value in (('raw_otlp_sha256', '0' * 64), ('pending', 1), ('functions', {})):
        changed = copy.deepcopy(witness); changed[field] = value
        rejects('witness-' + field, lambda: attempt(folder, entry, 'instrumented_on', changed, provider, arguments))
    rejects('caller-arguments', lambda: attempt(folder, entry, 'instrumented_on', witness, provider, [999]))
    expected_policy = tomllib.loads((folder / 'policy.toml').read_text())
    checkpoint = read(folder / 'native-runtime/app/health.json')
    _, points, traces, metrics = receipt(folder, read, entry['language'], expected_policy['resource']['service_name'],
                                        entry['path'] + '::' + entry['otelc_function'], plain=False)
    for section, field, value in (('function_accounting', 'lost', '1'), ('span_accounting', 'queue_dropped', '1'),
            ('metric_exports', 'units_succeeded', str(points + 1)), ('metric_flush', 'failed_attempts', '1'),
            ('controls', 'collection', False)):
        changed = copy.deepcopy(checkpoint); changed[section][field] = value
        rejects('health-' + field, lambda: health(changed, expected_policy, entry['language'], checkpoint['pid'],
                                                points, traces, metrics))
    manifest = read(folder / 'http-capture.json')
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    for name in ('wrong-trace', 'malformed-protobuf', 'failed-response', 'extra-body'):
        copied = root / name; copied.mkdir()
        for filename in ('http-capture.json', 'http-responses.json', *(row['file'] for row in manifest['bodies'])):
            shutil.copy2(folder / filename, copied / filename)
        trace_file = copied / next(row['file'] for row in manifest['bodies'] if row['path'] == '/v1/traces')
        if name == 'wrong-trace':
            message = ExportTraceServiceRequest.FromString(trace_file.read_bytes())
            message.resource_spans[0].scope_spans[0].spans[0].name = 'foreign-selected-function'
            trace_file.write_bytes(message.SerializeToString())
        elif name == 'malformed-protobuf':
            trace_file.write_bytes(b'\xff')
        elif name == 'failed-response':
            response = read(copied / 'http-responses.json'); response['events'][0]['status'] = 503
            (copied / 'http-responses.json').write_text(json.dumps(response))
        else:
            (copied / 'otlp-4096.protobuf').write_bytes(b'foreign')
        rejects(name, lambda: receipt(copied, read, entry['language'], expected_policy['resource']['service_name'],
                                     entry['path'] + '::' + entry['otelc_function'], plain=False))
    (root / 'refusals.json').write_text(json.dumps({'rejected': rejected, 'new_application_launches': 0}, indent=2) + '\n')
    return len(rejected)


class Oracle:
    """Bind copied shrink evidence to exactly one original four-launch report."""

    def __init__(self, root: Path, provider: Path):
        self.root, self.provider = root.resolve(strict=True), provider.resolve(strict=True)
        self.originals = {}; self.actual = set(); self.archived = set(); self.held = {}; self.contexts = {}

    def launches(self, report: Path) -> tuple | None:
        document = read(report)
        if len(document.get('cases', [])) != 1:
            return None
        name = document['cases'][0]['case']
        require(type(name) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', name) is not None, 'foreign case directory')
        folders = [report.parent / name / lane / 'native-runtime' for lane in LANES]
        if not all((folder / 'native-request.json').is_file() for folder in folders):
            return None
        rows = [read(folder / 'native-request.json') for folder in folders]
        ids = tuple(row['launch_id'] for row in rows)
        require(len(set(ids)) == 4 and all(re.fullmatch(r'[0-9a-f]{32}', value) for value in ids), 'duplicate launch denominator')
        return ids, all(row['runtime'] == str(folder) for row, folder in zip(rows, folders))

    def original(self, report: Path) -> Path:
        require(report.is_absolute() and report.resolve(strict=True) == report and report.is_relative_to(self.root), 'foreign report')
        current = self.launches(report)
        require(current is not None, 'report lacks four native launch records')
        ids, actual = current
        if actual:
            matches = self.originals.setdefault(ids, set()); matches.add(report)
            require(len(matches) == 1, 'ambiguous original launch report')
            return report
        reports = list(self.root.rglob('report.json'))
        require(len(reports) <= 512, 'report registry budget exceeded')
        for candidate in reports:
            found = self.launches(candidate)
            if found is not None and found[1]:
                self.originals.setdefault(found[0], set()).add(candidate)
        matches = self.originals.get(ids, set())
        require(len(matches) == 1, 'archive has no unique original launch report')
        original, = matches
        archive(original.parent, report.parent)
        self.archived.add(str(report))
        return original

    def __call__(self, report: Path, folder: Path, entry: dict, lane: str, witness, arguments: list) -> None:
        original = self.original(report)
        source = original.parent / folder.relative_to(report.parent)
        attempt(source, entry, lane, witness, self.provider, arguments)
        self.actual.add(str(source))
        self.contexts[str(source)] = (copy.deepcopy(entry), lane, copy.deepcopy(witness), list(arguments))
        paths = [original, source.parent / 'typed-bundle.json',
                 *[source / name for name in ('command.json', 'process.json', 'policy.toml', 'observation',
                    'http-capture.json', 'http-responses.json', 'native-caller/caller.json',
                    'native-build/native-source-build.json', 'native-build/plain', 'native-build/instrumented')],
                 *(source / 'native-runtime').glob('*.json'), *source.glob('otlp-*.protobuf')]
        if lane != 'baseline':
            paths.append(source / 'native-runtime/app/health.json')
        for path in paths:
            observed = identity(path, owned=True)
            same(observed, self.held.setdefault(str(path), observed))

    def finish(self) -> dict:
        """Recheck every originally observed file fact after the actual refusal corpus."""
        candidates = [(name, values) for name, values in sorted(self.contexts.items()) if values[1] == 'instrumented_on']
        require(bool(candidates), 'qualification lacks an actual instrumented call')
        name, (entry, _, witness, arguments) = candidates[0]
        count = refusals(self.root / 'receipt-refusals', Path(name), entry, witness, self.provider, arguments)
        for name, expected in self.held.items():
            same(identity(Path(name), owned=True), expected)
        return {**self.summary(), 'altered_evidence_refusals': count, 'original_evidence_files_held': len(self.held)}

    def summary(self) -> dict:
        return {'actual_application_records': len(self.actual), 'archived_reports': len(self.archived),
                'claims': 'original host/file/health records and direct protobuf; copied evidence is not a new launch'}
