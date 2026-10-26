"""Independent retained Go ownership, checkpoint, health and OTLP expectations."""

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import stat
import sys

from go_live_fixture import exact, runtime_function, states

FACTORY = 'example.test/live/counter.New'
SCOPE = 'io.quux.otelc.go'
CALLS = 'otelc.function.calls'
ERRORS = 'otelc.function.errors'
DURATION = 'otelc.function.duration'
BOUNDS = [1e-6, 1e-5, 1e-4, 1e-3, .01, .1, 1.0]
PROBES = ('function_started', 'function_ended', 'function_active', 'function_lost',
          'observer_started', 'observer_ended', 'observer_active', 'observer_lost',
          'unwind_unknown', 'object_admitted', 'gc_observed', 'resource_released',
          'objects_pending', 'resources_unreleased', 'lifetime_lost', 'duplicate_objects')


def read(path: Path) -> dict:
    return json.loads(path.read_bytes())


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError('Go live qualification: ' + message)


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def identity(path: Path, expected: dict) -> None:
    """Copied evidence keeps its original absolute path and its original bytes."""
    require(not path.is_symlink() and path.is_file(), 'missing ordinary artefact')
    original = Path(expected['path'])
    require(original.is_absolute() and '..' not in original.parts, 'noncanonical artefact name')
    exact(expected, {'path': str(original), 'resolved_path': str(original),
                     'size': path.stat().st_size, 'sha256': digest(path)})


def status(pid: int, flags: dict) -> dict:
    return {'schema_version': 1, 'pid': pid, **flags,
            'effective_emission_off': not flags['emission']}


def transition(rows: list, pid: int, previous: dict, requested: dict) -> None:
    intermediate = {**previous, 'collection': requested['collection']}
    exact(rows, [
        {'command': 'status', 'response': status(pid, previous)},
        {'command': 'collection ' + ('on' if requested['collection'] else 'off'),
         'response': status(pid, intermediate)},
        {'command': 'emission ' + ('on' if requested['emission'] else 'off'),
         'response': status(pid, requested)},
    ])


def counter(value: object) -> int:
    require(type(value) is str and re.fullmatch(r'0|[1-9][0-9]{0,19}', value) is not None,
            'noncanonical health counter')
    result = int(value)
    require(result < 1 << 64, 'health counter overflow')
    return result


def health(raw: dict, control: dict, completed: int, flags: dict, *, final: bool = False) -> dict:
    """Every raw field has an expectation; dynamic export/flush counts stay explicit."""
    metric = counter(raw['metric_exports']['attempts'])
    trace = counter(raw['trace_exports']['attempts'])
    flush = counter(raw['metric_flush']['attempts'])
    probes = {name: str(completed) if name in ('function_started', 'function_ended') else '0'
              for name in PROBES}
    exact(raw, {'schema_version': 4, 'kind': 'otelc.runtime-health', 'language': 'go',
        'scope': 'sdk_pipeline', 'pid': control['pid'], 'policy_sha256': control['policy_sha256'],
        'selection_sha256': control['selection_sha256'], 'phase': 'final' if final else 'running',
        'sdk_attached': True, 'source_complete': False, 'controls': status(control['pid'], flags),
        'lifecycle': {name: 'succeeded' if final else 'not_started' for name in ('flush', 'shutdown')},
        'metric_flush': {'attempts': str(flush), 'failed_attempts': '0'},
        'probe_accounting': {**probes, 'closed': final},
        'metric_exports': {'observed': True, 'closed': final, 'attempts': str(metric),
                           'succeeded': str(metric), 'failed': '0'},
        'trace_exports': {'observed': True, 'closed': final, 'attempts': str(trace),
                         'succeeded': str(trace), 'failed': '0', 'queue_pending': '0',
                         'queue_dropped': '0', 'exported_spans': str(completed)},
        'http_spans': {'observed': True, 'closed': final, 'started': '0', 'ended': '0', 'active': '0'},
        'downstream_receipt': 'unavailable', 'otlp_partial_rejection': 'unavailable'})
    return {'metric': metric, 'trace': trace, 'flush': flush}


def checkpoints(folder: Path, owner: dict) -> None:
    root = folder / 'go-runtime/oteleq-rendezvous'
    phases = ['start', *[phase + '-' + str(index) for index in range(5)
                          for phase in ('before', 'after')], 'finish']
    require({path.name for path in root.iterdir()} ==
            {phase + suffix for phase in phases for suffix in ('.ready', '.tmp', '.resume', '.resume.tmp')},
            'checkpoint denominator changed')
    token = read(root / 'start.ready')['token']
    require(type(token) is str and re.fullmatch('[0-9a-f]{32}', token) is not None, 'invalid checkpoint nonce')
    for phase in phases:
        expected = {'schema_version': 1, 'kind': 'oteleq.go.ready' if phase == 'start' else 'oteleq.go.checkpoint',
                    'token': token, 'pid': owner['application_pid'], 'parent_pid': owner['pid']}
        if phase != 'start':
            expected['phase'] = phase
        for suffix in ('.ready', '.tmp'):
            exact(read(root / (phase + suffix)), expected)
        reply = token + ('\n' if phase == 'start' else ' ' + phase + '\n')
        for suffix in ('.resume', '.resume.tmp'):
            require((root / (phase + suffix)).read_bytes() == reply.encode(), 'wrong checkpoint acknowledgement')
        for a, b in (('.ready', '.tmp'), ('.resume', '.resume.tmp')):
            first, second = (root / (phase + suffix) for suffix in (a, b))
            info = first.lstat()
            require(not first.is_symlink() and not second.is_symlink()
                    and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 2
                    and info == second.lstat(), 'changed checkpoint publication links')


def ownership(folder: Path, plain: bool, provider: Path) -> tuple[dict, dict]:
    host = read(folder / 'go-runtime/oteleq-go-start.json')
    owner, kernel = host['owner'], host['kernel']
    supervisor, application = owner['pid'], owner['application_pid']
    require(type(supervisor) is type(application) is int and min(supervisor, application) > 1
            and supervisor != application, 'invalid native process identities')
    original_runtime = str(Path(read(folder / 'go-runtime/go-request.json')['runtime']))
    exact(owner, {'pid': supervisor, 'parent_pid': owner['parent_pid'], 'application_pid': application,
                  'command': [sys.executable, '-I', '-S', '-B', str(provider / 'otelc/go_supervisor.py'),
                              '--runtime', original_runtime]})
    exact(sorted(host), ['kernel', 'owner', 'ready_files'])
    exact(kernel, {'supervisor': {'pid': supervisor, 'parent_pid': owner['parent_pid'], 'process_group': supervisor},
                   'application': {'pid': application, 'parent_pid': supervisor, 'process_group': supervisor}})
    started = read(folder / 'go-runtime/go-application-start.json')
    original = Path(started['binary']['path'])
    require(original.name == ('plain' if plain else 'instrumented') and original.parent.name == 'go-build',
            'wrong application binary')
    identity(folder / 'go-build' / original.name, started['binary'])
    exact(started, {'schema_version': 1, 'kind': 'otelc.go.application', 'profile': 'go-source-v1',
                   'plain': plain, 'pid': application, 'supervisor_pid': supervisor, 'process_group': supervisor,
                   'launch_id': started['launch_id'], 'binary': started['binary'], 'argv': [str(original)]})
    require(re.fullmatch('[0-9a-f]{32}', started['launch_id']) is not None, 'invalid launch nonce')
    checkpoints(folder, owner)
    require(set(host['ready_files']) == {'start.ready', 'start.tmp'}, 'incomplete host start binding')
    for name, value in host['ready_files'].items():
        identity(folder / 'go-runtime/oteleq-rendezvous' / name, value)
    return owner, started


def attributes(rows) -> dict:
    values = {row.key: row.value.string_value for row in rows}
    require(len(values) == len(rows) and all(row.value.WhichOneof('value') == 'string_value' for row in rows),
            'duplicate or non-string OTLP labels')
    return values


def decode(folder: Path, method: str, service: str) -> tuple[list, dict, dict]:
    """Decode raw protobufs without SDK or consumer telemetry renderers."""
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    capture = read(folder / 'http-capture.json')
    exact(sorted(capture), ['bodies', 'errors'])
    exact(capture['errors'], [])
    bodies, spans, windows, points = capture['bodies'], [], {}, 0
    digest = hashlib.sha256()
    names = {FACTORY, runtime_function(method)}
    for index, item in enumerate(bodies):
        exact(sorted(item), ['file', 'path'])
        require(item['path'] in ('/v1/traces', '/v1/metrics') and item['file'] == 'otlp-' + str(index) + '.protobuf',
                'foreign OTLP route or body')
        raw = (folder / item['file']).read_bytes()
        route = item['path']
        digest.update(len(route).to_bytes(8, 'big') + route.encode() + len(raw).to_bytes(8, 'big') + raw)
        decoder = ExportTraceServiceRequest if route == '/v1/traces' else ExportMetricsServiceRequest
        message = decoder.FromString(raw)
        groups = message.resource_spans if route == '/v1/traces' else message.resource_metrics
        require(bool(groups), 'empty OTLP request')
        for resource in groups:
            exact(attributes(resource.resource.attributes), {'service.name': service, 'telemetry.sdk.language': 'go',
                  'telemetry.sdk.name': 'opentelemetry', 'telemetry.sdk.version': '1.47.0'})
            require(not resource.schema_url and resource.resource.dropped_attributes_count == 0, 'changed resource scope')
            scopes = resource.scope_spans if route == '/v1/traces' else resource.scope_metrics
            require(bool(scopes), 'missing instrumentation scope')
            for scope in scopes:
                require(scope.scope.name == SCOPE and not scope.scope.version and not scope.schema_url
                        and not scope.scope.attributes and scope.scope.dropped_attributes_count == 0, 'foreign instrumentation scope')
                if route == '/v1/traces':
                    require(bool(scope.spans), 'empty trace scope')
                    spans.extend(scope.spans)
                else:
                    window = windows.setdefault(index, {})
                    require(bool(scope.metrics), 'empty metric scope')
                    for metric in scope.metrics:
                        points += metric_points(metric, names, window)
    received = {'trace_batches': sum(row['path'] == '/v1/traces' for row in bodies),
                'metric_batches': sum(row['path'] == '/v1/metrics' for row in bodies),
                'spans': len(spans), 'metric_points': points, 'raw_otlp_sha256': digest.hexdigest()}
    require({path.name for path in folder.glob('otlp-*.protobuf')} == {row['file'] for row in bodies}, 'unaccounted OTLP body')
    return spans, windows, received


def metric_points(metric, names: set[str], window: dict) -> int:
    """Retain each cumulative sample and its exact function/error dimensions."""
    if metric.name == 'otelc.lifetime.live':
        require(metric.WhichOneof('data') == 'gauge' and metric.unit == '', 'wrong lifetime metric kind')
        values = {}
        for point in metric.gauge.data_points:
            labels = attributes(point.attributes)
            require(labels.get('type') == 'all' and set(labels) == {'type', 'boundary'}
                    and labels['boundary'] in ('observed_gc', 'resource'), 'foreign lifetime dimension')
            require(point.WhichOneof('value') == 'as_int' and point.as_int == 0 and point.flags == 0,
                    'unrequested lifetime observation')
            require(labels['boundary'] not in values, 'duplicate lifetime dimension')
            values[labels['boundary']] = 0
        exact(values, {'observed_gc': 0, 'resource': 0})
        return len(values)
    kind, unit = {CALLS: ('sum', '{call}'), ERRORS: ('sum', '{error}'),
                  DURATION: ('histogram', 's')}[metric.name]
    require(metric.WhichOneof('data') == kind and metric.unit == unit, 'wrong function metric kind/unit')
    data = getattr(metric, kind)
    require(data.aggregation_temporality == 2 and bool(data.data_points), 'non-cumulative or empty metric')
    for point in data.data_points:
        labels = attributes(point.attributes)
        function = labels.pop('function')
        require(function in names and point.flags == 0 and not point.exemplars
                and 0 < point.start_time_unix_nano <= point.time_unix_nano, 'unbound metric point')
        if kind == 'histogram':
            exact(list(point.explicit_bounds), BOUNDS)
            require(not labels and len(point.bucket_counts) == 8 and sum(point.bucket_counts) == point.count
                    and point.HasField('sum') and math.isfinite(point.sum) and point.sum >= 0, 'invalid duration histogram')
            value = point.count
        else:
            require(data.is_monotonic and point.WhichOneof('value') == 'as_int' and point.as_int >= 0,
                    'invalid call/error counter')
            value = point.as_int
        if metric.name == ERRORS:
            require(set(labels) == {'error.type'} and labels['error.type'] in ('panic', 'goexit', 'returned_error'),
                    'foreign error metric dimension')
        else:
            require(not labels, 'foreign function metric dimension')
        key = metric.name, function, labels.get('error.type', '')
        require(key not in window, 'duplicate metric series in a request')
        window[key] = (point.start_time_unix_nano, point.time_unix_nano, value)
    return len(data.data_points)


def trace_values(spans: list, method: str) -> None:
    ordered = sorted(spans, key=lambda value: value.start_time_unix_nano)
    require(len(ordered) == 6 and len({span.trace_id for span in spans}) == 6
            and len({(span.trace_id, span.span_id) for span in spans}) == 6, 'incomplete serial trace roots')
    for index, span in enumerate(ordered):
        name = FACTORY if index == 0 else runtime_function(method)
        error = index == 5
        exact(attributes(span.attributes), {'function': name, **({'error.type': 'panic'} if error else {})})
        require(span.name == name and span.kind == 1 and span.status.code == (2 if error else 0)
                and not span.status.message and not span.parent_span_id and not span.events and not span.links
                and span.dropped_attributes_count == span.dropped_events_count == span.dropped_links_count == 0
                and len(span.trace_id) == 16 and any(span.trace_id) and len(span.span_id) == 8 and any(span.span_id)
                and 0 < span.start_time_unix_nano <= span.end_time_unix_nano, 'invalid selected-function trace')
        if index:
            require(ordered[index - 1].end_time_unix_nano <= span.start_time_unix_nano, 'overlapping serial calls')


def metric_window(windows: dict, first: int, last: int, calls: dict, *, required: bool) -> None:
    expected = {(metric, name, ''): count for name, count in calls.items() for metric in (CALLS, DURATION)}
    expected.update({(ERRORS, name, error): int(name != FACTORY and error == 'panic' and calls.get('_error', 0))
                     for name in calls if name != '_error' for error in ('panic', 'goexit', 'returned_error')})
    expected = {key: value for key, value in expected.items() if key[1] != '_error'}
    observed = {}
    for index in range(first, last):
        for key, (_, _, count) in windows.get(index, {}).items():
            require(key in expected and count <= expected[key], 'uncollected or future metric')
            observed[key] = max(observed.get(key, 0), count)
    if required:
        require(all(observed.get(key) == count for key, count in expected.items() if count),
                'missing positive/restored measurements')


def check(folder: Path, method: str, start: str, plain: bool, witness: dict | None,
          provider: Path) -> dict:
    """Bind one actual application to all five calls and the restored error counter."""
    owner, application = ownership(folder, plain, provider)
    control = read(folder / 'go-controls.json')
    config = read(folder / 'go-runtime/config.json')
    expected = {'control_schema_version': 1, 'plain': plain, 'supervisor_pid': owner['pid'],
                'pid': owner['application_pid'], 'sdk_pid': None if plain else owner['application_pid'],
                'launch_id': application['launch_id'], 'policy_sha256': config['policy_sha256'],
                'selection_sha256': config['selection_sha256'], 'interval_ms': 1000,
                'steps': control['steps'], 'restored': control['restored']}
    exact(control, expected)
    require(len(control['steps']) == 5, 'missing live calls')
    capture = read(folder / 'http-capture.json')
    bodies = capture['bodies']
    if plain:
        exact(capture, {'errors': [], 'bodies': []})
        exact(witness, None)
        require(not (folder / 'go-verified-telemetry.json').exists() and not (folder / 'go-runtime/health.json').exists(),
                'plain worker fabricated SDK evidence')
        windows, received = {}, None
    else:
        spans, windows, received = decode(folder, method, config['service_name'])
        trace_values(spans, method)
    schedule, cursor, flush, previous_health = states(start), 0, 0, None
    calls = {runtime_function(method): 0, FACTORY: 0, '_error': 0}
    for index, (step, flags) in enumerate(zip(control['steps'], schedule)):
        before, after = step['before'], step['after']
        exact(sorted(before), ['cursor', 'flush', 'health', 'history'])
        exact(sorted(after), ['cursor', 'flush', 'health', 'held_ns', 'metric_bodies', 'settled', 'settled_flush', 'status'])
        exact(step, {'id': 'step-' + str(index), 'requested': flags, 'before': before, 'after': after})
        first, last = before['cursor'], after['cursor']
        require(type(first) is type(last) is int and cursor <= first <= last <= len(bodies), 'invalid receipt cursor')
        indices = [i for i in range(first, last) if bodies[i]['path'] == '/v1/metrics']
        exact(after['metric_bodies'], indices)
        require(type(after['held_ns']) is int and 0 <= after['held_ns'] <= 60_000_000_000, 'invalid quiet interval')
        if not all(flags.values()):
            require(not indices and after['held_ns'] >= 1_000_000_000, 'metrics in a disabled window')
        if plain:
            exact(before['history'], [])
            exact([before['flush'], before['health'], *[after[key] for key in
                  ('status', 'flush', 'health', 'settled_flush', 'settled')]], [None] * 7)
        else:
            transition(before['history'], control['pid'], schedule[max(0, index - 1)], flags)
            exact(before['flush'], status(control['pid'], flags))
            metric_window(windows, cursor, first, calls, required=False)
            snapshots = [(before['health'], 0 if index == 0 else index + 1),
                         (after['health'], index + 2), (after['settled'], index + 2)]
            for raw, completed in snapshots:
                current = health(raw, control, completed, flags)
                require(current['flush'] > flush, 'flush barrier did not advance')
                if previous_health is not None:
                    require(all(current[key] >= previous_health[key] for key in current), 'health counter decreased')
                flush, previous_health = current['flush'], current
            for name in ('status', 'flush', 'settled_flush'):
                exact(after[name], status(control['pid'], flags))
            if flags['collection']:
                calls[runtime_function(method)] += 1
                calls[FACTORY] += int(index == 0)
                calls['_error'] += int(index == 4)
            metric_window(windows, first, last, calls, required=all(flags.values()))
        cursor = last
    restored, flags = control['restored'], {'collection': True, 'emission': True}
    exact(sorted(restored), ['cursor', 'flush', 'health', 'history'])
    require(type(restored['cursor']) is int and cursor <= restored['cursor'] <= len(bodies), 'invalid restored cursor')
    if plain:
        exact(restored, {'history': [], 'flush': None, 'health': None, 'cursor': 0})
    else:
        transition(restored['history'], control['pid'], schedule[-1], flags)
        exact(restored['flush'], status(control['pid'], flags))
        restored_health = health(restored['health'], control, 6, flags)
        require(restored_health['flush'] > flush, 'restoration did not flush')
        metric_window(windows, cursor, restored['cursor'], calls, required=True)
        metric_window(windows, restored['cursor'], len(bodies), calls, required=False)
        final = health(read(folder / 'go-runtime/health.json'), control, 6, flags, final=True)
        require(final['flush'] > restored_health['flush'] and final['trace'] == received['trace_batches']
                and final['metric'] == received['metric_batches'], 'final SDK counters differ from actual receipt')
        receipt = read(folder / 'go-verified-telemetry.json')
        fields = ('decoder', 'raw_otlp_sha256', 'functions', 'spans', 'losses', 'pending')
        exact(witness, {key: receipt[key] for key in fields})
        exact({key: receipt[key] for key in ('raw_otlp_sha256', 'functions', 'spans', 'losses', 'pending', 'sdk_pid')},
              {'raw_otlp_sha256': received.pop('raw_otlp_sha256'), 'functions': {runtime_function(method): 5, FACTORY: 1},
               'spans': 6, 'losses': {key: 0 for key in ('function_lost', 'observer_lost', 'unwind_unknown', 'lifetime_lost')},
               'pending': 0, 'sdk_pid': control['pid']})
        exact(receipt['received'], received)
        exact(receipt['controls'], {'record_sha256': digest(folder / 'go-controls.json'), 'steps': 5,
                                   'metric_functions': {key: value for key, value in calls.items() if key != '_error'},
                                   'interval_ms': 1000})
    return {'launch_id': application['launch_id'], 'pid': control['pid'], 'plain': plain}
