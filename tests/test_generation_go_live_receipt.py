"""Literal retained-record and protobuf controls for the Go live qualifier."""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

import go_live_fixture as fixture
import go_live_receipt as receipt

POLICY = {'unit_boundary': True}
POLICY_SHA256 = hashlib.sha256(json.dumps(POLICY, sort_keys=True).encode()).hexdigest()


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + '\n')


def labels(rows, values: dict) -> None:
    for name, value in values.items():
        rows.add(key=name).value.string_value = value


def state(flags: dict) -> dict:
    return {'schema_version': 1, 'pid': 23, **flags, 'effective_emission_off': not flags['emission']}


def history(previous: dict, requested: dict) -> list:
    return [{'command': 'status', 'response': state(previous)},
            {'command': 'collection ' + ('on' if requested['collection'] else 'off'),
             'response': state({**previous, 'collection': requested['collection']})},
            {'command': 'emission ' + ('on' if requested['emission'] else 'off'), 'response': state(requested)}]


def health(completed: int, flags: dict, flush: int, metrics: int, traces: int, *, final: bool = False) -> dict:
    return {'schema_version': 4, 'kind': 'otelc.runtime-health', 'language': 'go', 'scope': 'sdk_pipeline',
        'pid': 23, 'policy_sha256': POLICY_SHA256, 'selection_sha256': 'b' * 64,
        'phase': 'final' if final else 'running', 'sdk_attached': True, 'source_complete': False,
        'controls': state(flags), 'lifecycle': {key: 'succeeded' if final else 'not_started' for key in ('flush', 'shutdown')},
        'metric_flush': {'attempts': str(flush), 'failed_attempts': '0'},
        'probe_accounting': {'function_started': str(completed), 'function_ended': str(completed),
            **{key: '0' for key in ('function_active', 'function_lost', 'observer_started', 'observer_ended',
                'observer_active', 'observer_lost', 'unwind_unknown', 'object_admitted', 'gc_observed',
                'resource_released', 'objects_pending', 'resources_unreleased', 'lifetime_lost', 'duplicate_objects')},
            'closed': final},
        'metric_exports': {'observed': True, 'closed': final, 'attempts': str(metrics), 'succeeded': str(metrics), 'failed': '0'},
        'trace_exports': {'observed': True, 'closed': final, 'attempts': str(traces), 'succeeded': str(traces),
                          'failed': '0', 'exported_spans': str(completed), 'queue_pending': '0', 'queue_dropped': '0'},
        'http_spans': {'observed': True, 'closed': final, 'started': '0', 'ended': '0', 'active': '0'},
        'downstream_receipt': 'unavailable', 'otlp_partial_rejection': 'unavailable'}


def record_fixture(folder: Path, start: str, plain: bool) -> tuple[Path, dict | None]:
    runtime = folder / 'go-runtime'
    rendezvous = runtime / 'oteleq-rendezvous'
    rendezvous.mkdir(parents=True)
    (folder / 'go-build').mkdir()
    provider = folder / 'sdk'
    binary = folder / 'go-build' / ('plain' if plain else 'instrumented')
    binary.write_bytes(b'unit boundary artefact; never executed')
    identity = {'path': str(binary), 'resolved_path': str(binary), 'sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                'size': binary.stat().st_size}
    owner = {'pid': 22, 'parent_pid': 21, 'application_pid': 23,
             'command': [sys.executable, '-I', '-S', '-B', str(provider / 'otelc/go_supervisor.py'), '--runtime', str(runtime)]}
    phases = ['start', *[p + '-' + str(i) for i in range(5) for p in ('before', 'after')], 'finish']
    for phase in phases:
        ready = {'schema_version': 1, 'kind': 'oteleq.go.ready' if phase == 'start' else 'oteleq.go.checkpoint',
                 'token': 'c' * 32, 'pid': 23, 'parent_pid': 22}
        if phase != 'start': ready['phase'] = phase
        first = rendezvous / (phase + '.ready')
        write(first, ready); first.chmod(0o600)
        os.link(first, rendezvous / (phase + '.tmp'))
        first = rendezvous / (phase + '.resume')
        first.write_text('c' * 32 + (' release\n' if phase == 'start' else ' ' + phase + '\n'))
        first.chmod(0o600); os.link(first, rendezvous / (phase + '.resume.tmp'))
    ready_files = {}
    for name in ('start.ready', 'start.tmp'):
        path = rendezvous / name
        ready_files[name] = {'path': str(path), 'resolved_path': str(path), 'size': path.stat().st_size,
                             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    write(runtime / 'oteleq-go-start.json', {'owner': owner, 'kernel': {
        'supervisor': {'pid': 22, 'parent_pid': 21, 'process_group': 22},
        'application': {'pid': 23, 'parent_pid': 22, 'process_group': 22}}, 'ready_files': ready_files})
    write(runtime / 'go-application-start.json', {'schema_version': 1, 'kind': 'otelc.go.application',
        'profile': 'go-source-v1', 'plain': plain, 'pid': 23, 'supervisor_pid': 22, 'process_group': 22,
        'launch_id': 'd' * 32, 'binary': identity, 'argv': [str(binary)]})
    write(runtime / 'go-request.json', {'runtime': str(runtime), 'policy': POLICY})
    write(folder / 'build-identities.json', {'selection_sha256': 'b' * 64})
    if not plain:
        write(runtime / 'config.json', {'policy_sha256': POLICY_SHA256, 'selection_sha256': 'b' * 64, 'service_name': 'test-go-live'})
    bodies, points, metric_count = [], 0, 0
    target = fixture.runtime_function('identity')

    def append(route: str, message) -> None:
        name = 'otlp-' + str(len(bodies)) + '.protobuf'
        (folder / name).write_bytes(message.SerializeToString())
        bodies.append({'path': route, 'file': name})

    def resource(group) -> None:
        labels(group.resource.attributes, {'service.name': 'test-go-live', 'telemetry.sdk.language': 'go',
            'telemetry.sdk.name': 'opentelemetry', 'telemetry.sdk.version': '1.47.0'})

    def traces(index: int) -> None:
        message = ExportTraceServiceRequest()
        group = message.resource_spans.add(); resource(group)
        scope = group.scope_spans.add(); scope.scope.name = 'io.quux.otelc.go'
        for number in ((0, 1) if index == 0 else (index + 1,)):
            name = 'example.test/live/counter.New' if number == 0 else target
            span = scope.spans.add(name=name, kind=1, trace_id=bytes([number + 1]) * 16,
                span_id=bytes([number + 1]) * 8, start_time_unix_nano=10 + number * 10, end_time_unix_nano=15 + number * 10)
            labels(span.attributes, {'function': name})
            if number == 5:
                span.status.code = 2; labels(span.attributes, {'error.type': 'panic'})
        append('/v1/traces', message)

    def metrics(calls: int, factory: int, errors: int) -> None:
        nonlocal points, metric_count
        metric_count += 1
        message = ExportMetricsServiceRequest()
        group = message.resource_metrics.add(); resource(group)
        scope = group.scope_metrics.add(); scope.scope.name = 'io.quux.otelc.go'
        for name, unit in (('otelc.function.calls', '{call}'), ('otelc.function.duration', 's'), ('otelc.function.errors', '{error}')):
            metric = scope.metrics.add(name=name, unit=unit)
            histogram = name.endswith('duration')
            data = metric.histogram if histogram else metric.sum
            data.aggregation_temporality = 2
            if not histogram: data.is_monotonic = True
            for function, count in ((target, calls), ('example.test/live/counter.New', factory)):
                if histogram and not count:
                    continue
                point = data.data_points.add(start_time_unix_nano=1, time_unix_nano=100 + len(bodies))
                labels(point.attributes, {'function': function})
                if histogram:
                    point.count = count; point.sum = .01 * count; point.min = point.max = .01
                    point.explicit_bounds.extend([1e-6, 1e-5, 1e-4, .001, .01, .1, 1.0])
                    point.bucket_counts.extend([0, 0, 0, 0, count, 0, 0, 0])
                else:
                    point.as_int = (errors if function == target else 0) if name.endswith('errors') else count
                    if name.endswith('errors'): labels(point.attributes, {'error.type': 'panic'})
                points += 1
        append('/v1/metrics', message)

    schedule = fixture.states(start)
    steps, calls, factory, errors = [], 0, 0, 0
    for index, flags in enumerate(schedule):
        before = {'cursor': len(bodies), 'history': [] if plain else history(schedule[max(0, index - 1)], flags),
                  'flush': None if plain else state(flags),
                  'health': None if plain else health(0 if index == 0 else index + 1, flags, index * 3 + 1, metric_count, index)}
        if not plain:
            traces(index)
            if flags['collection']:
                calls += 1; factory += int(index == 0); errors += int(index == 4)
            if all(flags.values()): metrics(calls, factory, errors)
        after = {'cursor': len(bodies), 'held_ns': 0 if all(flags.values()) else 1_000_000_000,
                 'metric_bodies': [i for i in range(before['cursor'], len(bodies)) if bodies[i]['path'] == '/v1/metrics'],
                 'status': None if plain else state(flags), 'flush': None if plain else state(flags),
                 'settled_flush': None if plain else state(flags),
                 'health': None if plain else health(index + 2, flags, index * 3 + 2, metric_count, index + 1),
                 'settled': None if plain else health(index + 2, flags, index * 3 + 3, metric_count, index + 1)}
        steps.append({'id': 'step-' + str(index), 'requested': flags, 'before': before, 'after': after})
    flags = {'collection': True, 'emission': True}
    if not plain: metrics(calls, factory, errors)
    restored = {'history': [] if plain else history(schedule[-1], flags), 'flush': None if plain else state(flags),
                'health': None if plain else health(6, flags, 16, metric_count, 5), 'cursor': len(bodies)}
    write(folder / 'http-capture.json', {'errors': [], 'bodies': bodies})
    write(folder / 'go-controls.json', {'control_schema_version': 1, 'plain': plain, 'supervisor_pid': 22,
        'pid': 23, 'sdk_pid': None if plain else 23, 'launch_id': 'd' * 32, 'policy_sha256': POLICY_SHA256,
        'selection_sha256': 'b' * 64, 'interval_ms': 1000, 'steps': steps, 'restored': restored})
    witness = None
    if not plain:
        final = health(6, flags, 17, metric_count, 5, final=True)
        write(runtime / 'health.json', final)
        digest = hashlib.sha256()
        for item in bodies:
            route, raw = item['path'], (folder / item['file']).read_bytes()
            digest.update(len(route).to_bytes(8, 'big') + route.encode() + len(raw).to_bytes(8, 'big') + raw)
        witness = {'decoder': 'opentelemetry-proto Go traces/metrics with independent owned health4',
            'raw_otlp_sha256': digest.hexdigest(), 'functions': {target: 5, 'example.test/live/counter.New': 1},
            'spans': 6, 'losses': {key: 0 for key in ('function_lost', 'observer_lost', 'unwind_unknown', 'lifetime_lost')}, 'pending': 0}
        received = {'trace_batches': 5, 'metric_batches': metric_count, 'spans': 6, 'metric_points': points}
        normalised = {name: {key: value if type(value) is bool else int(value) for key, value in final[name].items() if key != 'observed'}
                      for name in ('probe_accounting', 'metric_flush', 'http_spans', 'metric_exports', 'trace_exports')}
        write(folder / 'go-verified-telemetry.json', {**witness, 'sdk_pid': 23, 'received': received,
            'health': {**normalised, 'pid': 23, 'sdk_pid': 23, 'received': received, 'metric_exported_points': None, 'source_complete': False},
            'controls': {'record_sha256': hashlib.sha256((folder / 'go-controls.json').read_bytes()).hexdigest(),
                        'steps': 5, 'metric_functions': {target: calls, 'example.test/live/counter.New': factory}, 'interval_ms': 1000}})
    return provider, witness


class GoLiveRetainedReceiptTests(unittest.TestCase):
    def test_archive_bytes_are_bound_without_recertifying_copied_publisher_inodes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            original, archived = root / 'original', root / 'archive'
            original.mkdir()
            sdk, witness = record_fixture(original, 'both-on', False)
            shutil.copytree(original, archived)
            receipt.identical_archive(original, archived)
            self.assertEqual((original / 'go-runtime/oteleq-rendezvous/start.ready').stat().st_nlink, 2)
            self.assertEqual((archived / 'go-runtime/oteleq-rendezvous/start.ready').stat().st_nlink, 1)
            receipt.check(original, 'identity', 'both-on', False, witness, sdk)
            with self.assertRaises(ValueError):
                receipt.check(archived, 'identity', 'both-on', False, witness, sdk)
            for kind in ('bytes', 'extra-file', 'extra-directory', 'mode', 'symlink'):
                candidate = root / kind; shutil.copytree(original, candidate)
                if kind == 'bytes': (candidate / 'http-capture.json').write_text('{}')
                elif kind == 'extra-file': (candidate / 'extra').write_text('extra')
                elif kind == 'extra-directory': (candidate / 'extra').mkdir()
                elif kind == 'mode': (candidate / 'http-capture.json').chmod(0o600)
                else:
                    path = candidate / 'http-capture.json'; path.unlink(); path.symlink_to(original / 'http-capture.json')
                with self.subTest(kind=kind), self.assertRaises(ValueError): receipt.identical_archive(original, candidate)
            with self.assertRaises(ValueError): receipt.identical_archive(original, original)
            with self.assertRaises(ValueError): receipt.identical_archive(root, original)

    def test_json_reader_refuses_duplicate_fields_and_nonfinite_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'record.json'
            for raw in ('{"field":1,"field":1}', '{"outer":{"field":1,"field":2}}',
                        '{"value":NaN}', '{"value":Infinity}'):
                path.write_text(raw)
                with self.subTest(raw=raw), self.assertRaises(ValueError):
                    receipt.read(path)

    def test_complete_plain_and_woven_receipts_cover_all_startups(self):
        for start in fixture.STARTS:
            for plain in (False, True):
                with self.subTest(start=start, plain=plain), tempfile.TemporaryDirectory() as temporary:
                    folder = Path(temporary)
                    sdk, witness = record_fixture(folder, start, plain)
                    self.assertEqual(receipt.check(folder, 'identity', start, plain, witness, sdk),
                                     {'launch_id': 'd' * 32, 'pid': 23, 'plain': plain})

    def test_altered_live_metadata_and_health_never_pass(self):
        for kind in ('flags', 'quiet', 'cursor', 'coupled', 'flush', 'health', 'receipt', 'pid', 'group', 'argv', 'checkpoint', 'extra'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                sdk, witness = record_fixture(folder, 'both-on', False)
                name = 'go-controls.json'
                if kind == 'pid': name = 'go-runtime/go-application-start.json'
                elif kind in ('group', 'argv'): name = 'go-runtime/oteleq-go-start.json'
                elif kind == 'receipt': name = 'go-verified-telemetry.json'
                elif kind == 'checkpoint': name = 'go-runtime/oteleq-rendezvous/finish.ready'
                value = receipt.read(folder / name)
                if kind == 'flags': value['steps'][0]['requested']['collection'] = False
                elif kind == 'quiet': value['steps'][2]['after']['held_ns'] = 999
                elif kind == 'cursor': value['steps'][1]['after']['cursor'] = 999
                elif kind == 'coupled': value['steps'][2]['before']['history'][1]['response']['emission'] = False
                elif kind == 'flush': value['steps'][1]['after']['settled']['metric_flush']['attempts'] = '1'
                elif kind == 'health': value['steps'][1]['after']['health']['probe_accounting']['function_ended'] = '2'
                elif kind == 'receipt': value['health']['metric_exported_points'] = 0
                elif kind == 'pid': value['pid'] = 24
                elif kind == 'group': value['kernel']['application']['process_group'] = 23
                elif kind == 'argv': value['owner']['command'] = ['untrusted-tool']
                elif kind == 'checkpoint': value['token'] = 'e' * 32
                else: value['extra'] = True
                write(folder / name, value)
                with self.assertRaises(ValueError):
                    receipt.check(folder, 'identity', 'both-on', False, witness, sdk)

    def test_running_periodic_metric_export_is_retained_until_closed_final_drain(self):
        flags = {'collection': True, 'emission': True}
        control = {'pid': 23, 'policy_sha256': POLICY_SHA256, 'selection_sha256': 'b' * 64}
        raw = health(2, flags, 3, 4, 1)
        raw['metric_exports']['succeeded'] = '3'
        current = receipt.health(raw, control, 2, flags)
        self.assertEqual((current['metric'], current['metric_succeeded']), (4, 3))
        # An independently loaded succeeded counter can pass the earlier
        # attempts load. Chronological snapshots and final receipt anchor both.
        raw['metric_exports']['succeeded'] = '5'
        self.assertEqual(receipt.health(raw, control, 2, flags)['metric_succeeded'], 5)
        for name, value in (('failed', '1'), ('succeeded', True), ('succeeded', '04')):
            altered = copy.deepcopy(raw); altered['metric_exports'][name] = value
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                receipt.health(altered, control, 2, flags)
        final = health(6, flags, 17, 4, 5, final=True)
        final['metric_exports']['succeeded'] = '3'
        with self.assertRaisesRegex(ValueError, 'did not drain'):
            receipt.health(final, control, 6, flags, final=True)

    def test_running_metric_success_cannot_decrease_or_exceed_final_receipt(self):
        for where in ('later', 'restored', 'final'):
            with self.subTest(where=where), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                sdk, witness = record_fixture(folder, 'both-on', False)
                path = folder / 'go-controls.json'
                value = receipt.read(path)
                if where == 'later':
                    value['steps'][0]['after']['health']['metric_exports']['succeeded'] = '99'
                elif where == 'restored':
                    value['restored']['health']['metric_exports']['succeeded'] = '0'
                else:
                    value['restored']['health']['metric_exports']['succeeded'] = '99'
                write(path, value)
                with self.assertRaises(ValueError):
                    receipt.check(folder, 'identity', 'both-on', False, witness, sdk)

    def test_cumulative_series_refuse_time_repeats_resets_and_decreases(self):
        key = ('metric', 'target', '')
        receipt.cumulative({0: {key: (1, 2, 1)}, 2: {key: (1, 3, 2)}})
        for sample in ((2, 3, 2), (1, 2, 2), (1, 1, 2), (1, 3, 0)):
            with self.subTest(sample=sample), self.assertRaises(ValueError):
                receipt.cumulative({0: {key: (1, 2, 1)}, 2: {key: sample}})

    def test_metric_exemplars_bind_to_collected_function_trace_roots(self):
        for kind in ('valid', 'foreign', 'uncollected', 'labels', 'value', 'time', 'error'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                record_fixture(folder, 'both-on', False)
                path = folder / 'otlp-1.protobuf'
                message = ExportMetricsServiceRequest.FromString(path.read_bytes())
                metric = message.resource_metrics[0].scope_metrics[0].metrics[2 if kind == 'error' else 0]
                point = metric.sum.data_points[0]
                example = point.exemplars.add(trace_id=b'\x02' * 16, span_id=b'\x02' * 8,
                                               time_unix_nano=90, as_int=1)
                if kind == 'foreign': example.trace_id = b'x' * 16
                elif kind == 'uncollected': example.trace_id = b'\x04' * 16; example.span_id = b'\x04' * 8
                elif kind == 'labels': labels(example.filtered_attributes, {'extra': 'field'})
                elif kind == 'value': example.as_int = 2
                elif kind == 'time': example.time_unix_nano = 999
                path.write_bytes(message.SerializeToString())
                if kind == 'valid':
                    spans, _, _ = receipt.decode(folder, 'identity', 'test-go-live', 'both-on')
                    self.assertEqual(len(spans), 6)
                else:
                    with self.assertRaises(ValueError):
                        receipt.decode(folder, 'identity', 'test-go-live', 'both-on')

    def test_changed_raw_trace_or_metric_bytes_are_refused(self):
        for kind in ('trace', 'metric', 'hash', 'extra-file'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                sdk, witness = record_fixture(folder, 'both-on', False)
                if kind == 'trace':
                    path = folder / 'otlp-0.protobuf'
                    message = ExportTraceServiceRequest.FromString(path.read_bytes())
                    message.resource_spans[0].scope_spans[0].spans[0].name = 'foreign'
                    path.write_bytes(message.SerializeToString())
                elif kind == 'metric':
                    path = folder / 'otlp-1.protobuf'
                    message = ExportMetricsServiceRequest.FromString(path.read_bytes())
                    message.resource_metrics[0].scope_metrics[0].metrics[0].sum.data_points[0].as_int = 999
                    path.write_bytes(message.SerializeToString())
                elif kind == 'hash': witness['raw_otlp_sha256'] = '0' * 64
                else: (folder / 'otlp-999.protobuf').write_bytes(b'extra')
                with self.assertRaises(ValueError):
                    receipt.check(folder, 'identity', 'both-on', False, witness, sdk)


if __name__ == '__main__':
    unittest.main()
