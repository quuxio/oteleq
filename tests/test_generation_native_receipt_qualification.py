"""Independent native fixture receipts reject substituted or incomplete evidence."""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

import native_prepared_otlp as otlp
import native_prepared_receipt as oracle

SERVICE = 'oteleq-gen-' + 'a' * 32
FUNCTION = 'src/one.c::selected'
ENTRY = {'path': 'src/one.c', 'otelc_function': 'selected', 'language': 'c'}


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    path.chmod(0o600)


def seal(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def facts(path: Path) -> dict:
    info = path.stat()
    return {'path': str(path), 'resolved_path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'size': info.st_size, 'device': info.st_dev, 'inode': info.st_ino, 'mode': info.st_mode,
            'uid': info.st_uid, 'gid': info.st_gid, 'mtime_ns': info.st_mtime_ns, 'ctime_ns': info.st_ctime_ns,
            'links': info.st_nlink}


def labels(rows, values: dict) -> None:
    for key, value in values.items():
        row = rows.add(); row.key = key; row.value.string_value = value


def signals():
    trace, metric = ExportTraceServiceRequest(), ExportMetricsServiceRequest()
    for message, tracing in ((trace, True), (metric, False)):
        resource = (message.resource_spans if tracing else message.resource_metrics).add()
        labels(resource.resource.attributes, {'service.name': SERVICE, 'otelc.language': 'c',
            'telemetry.sdk.language': 'cpp', 'telemetry.sdk.name': 'opentelemetry', 'telemetry.sdk.version': '1.30.0'})
        scope = (resource.scope_spans if tracing else resource.scope_metrics).add()
        scope.scope.name = 'io.quux.otelc.native'
        if tracing:
            span = scope.spans.add(); span.name = FUNCTION; span.kind = 1; span.flags = 1
            span.trace_id = b't' * 16; span.span_id = b's' * 8
            span.start_time_unix_nano = 1; span.end_time_unix_nano = 2
            labels(span.attributes, {'function': FUNCTION})
        else:
            for name, unit, value in (('calls', '{call}', 1), ('errors', '{error}', 0), ('duration', 's', 1)):
                item = scope.metrics.add(); item.name = 'otelc.function.' + name; item.unit = unit
                data = item.histogram if name == 'duration' else item.sum
                data.aggregation_temporality = 2
                if name != 'duration':
                    data.is_monotonic = True
                point = data.data_points.add(); point.start_time_unix_nano = 1; point.time_unix_nano = 2
                labels(point.attributes, {'function': FUNCTION, **({'error.type': 'exception'} if name == 'errors' else {})})
                if name == 'duration':
                    point.count = 1; point.sum = point.min = point.max = .25
                    point.explicit_bounds.extend([1e-6, 1e-5, 1e-4, .001, .01, .1, 1.])
                    point.bucket_counts.extend([0, 0, 0, 0, 0, 0, 1, 0])
                else:
                    point.as_int = value
    return trace, metric


def capture(folder: Path, *, plain: bool = False) -> dict | None:
    rows, events = [], []
    messages = [] if plain else list(zip(('/v1/traces', '/v1/metrics'), signals()))
    raw_digest = hashlib.sha256()
    for index, (route, message) in enumerate(messages):
        raw = message.SerializeToString(); name = 'otlp-' + str(index) + '.protobuf'
        (folder / name).write_bytes(raw); rows.append({'path': route, 'file': name})
        events.append({'path': route, 'body_index': index, 'status': 200, 'headers_write_failed': False,
            'request_started_ns': 1, 'body_received_ns': 2, 'response_started_ns': 3,
            'headers_written_ns': 4, 'handler_finished_ns': 5})
        raw_digest.update(len(route).to_bytes(8, 'big') + route.encode() + len(raw).to_bytes(8, 'big') + raw)
    write(folder / 'http-capture.json', {'errors': [], 'bodies': rows})
    write(folder / 'http-responses.json', {'schema_version': 1,
        'scope': 'server response headers; client acknowledgement is not observed', 'clock': 'monotonic_ns',
        'unrecorded_events': 0, 'events': events})
    return None if plain else {'decoder': 'opentelemetry-proto native traces/metrics with independent owned health1',
        'raw_otlp_sha256': raw_digest.hexdigest(), 'functions': {FUNCTION: 1}, 'spans': 1,
        'losses': {'function_lost': 0, 'metadata_errors': 0, 'queue_dropped': 0, 'diagnostic_dropped': 0}, 'pending': 0}


def fixture(root: Path, *, plain: bool = False, name: str = 'attempt') -> tuple[Path, Path, dict | None]:
    folder, provider = root / name, root / 'provider'
    runtime = folder / 'native-runtime'
    for path in (folder / 'native-build', folder / 'project', runtime / 'app', provider / 'otelc',
                 folder / 'native-after-build-inputs', folder / 'native-after-execution-inputs'):
        path.mkdir(parents=True)
    (provider / 'otelc/native_supervisor.py').write_text('# fixed supervisor fixture\n')
    for index in range(9):
        (provider / 'otelc' / (str(index) + '.py')).write_text('# fixture producer\n')
    for name in ('plain', 'instrumented'):
        product = folder / 'native-build' / name
        product.write_bytes(b'held image'); product.chmod(0o755)
    image = folder / 'native-build' / ('plain' if plain else 'instrumented')
    write(root / 'report.json', {'cases': [{'case': 'attempt'}]})
    write(root / 'typed-bundle.json', {'cases': []})
    (folder / 'observation').write_text('held boundary observation\n')
    build = folder / 'native-build/native-source-build.json'; write(build, {'held': True})
    policy = {'schema_version': 3, 'languages': ['c'], 'resource': {'service_name': SERVICE},
        'export': {'endpoint': 'http://127.0.0.1:4318', 'interval_ms': 1000, 'timeout_ms': 1000, 'shutdown_timeout_ms': 10000},
        'sources': {'include': ['src/one.c'], 'exclude': []}, 'functions': {'include': ['selected'], 'exclude': []},
        'metrics': {'collection': True, 'emission': True, 'histogram_boundaries_seconds': [1e-6, 1e-5, 1e-4, .001, .01, .1, 1.]},
        'traces': {'enabled': True, 'sample_ratio': 1.0},
        'lifetimes': {'enabled': False, 'include': [], 'exclude': [], 'max_live': 4096, 'release_methods': ['close']},
        'context': {'tasks': False, 'http': False}, 'benchmark': {'iterations': 10000, 'samples': 15, 'warmup': 5}}
    sections = []
    for name, value in policy.items():
        if isinstance(value, dict):
            sections.append('[' + name + ']\n' + '\n'.join(key + '=' + json.dumps(item) for key, item in value.items()))
        else:
            sections.insert(0, name + '=' + json.dumps(value))
    (folder / 'policy.toml').write_text('\n'.join(sections) + '\n')
    request = {'schema_version': 1, 'kind': 'otelc.native.request', 'profile': 'native-owned-v1',
        'build': facts(build), 'arguments': [], 'runtime': str(runtime), 'plain': plain, 'policy': policy,
        'wait_ms': 30000, 'launch_id': 'b' * 32}
    plan = {'schema_version': 1, 'kind': 'otelc.native.plan', 'profile': 'native-owned-v1',
        'request_sha256': seal(request), 'cwd': str(folder / 'project'), 'argv': [str(image)],
        'image': facts(image), 'source_complete': False}
    command = [str(Path(sys.executable).absolute()), '-I', '-S', str(provider / 'otelc/native_supervisor.py'), str(runtime)]
    prepared = {'schema_version': 1, 'kind': 'otelc.native.prepared', 'profile': 'native-owned-v1',
        'request_sha256': seal(request), 'plan_sha256': seal(plan),
        'interpreter': facts(Path(sys.executable).resolve()), 'interpreter_spelling': command[0],
        'producer': [facts(path) for path in sorted((provider / 'otelc').glob('*.py'))], 'source_complete': False}
    supervisor = {'schema_version': 1, 'kind': 'otelc.native.supervisor', 'pid': 120, 'parent_pid': 110,
        'process_group': 120, 'session': 120, 'launch_id': request['launch_id']}
    application = {'schema_version': 1, 'kind': 'otelc.native.application', 'pid': 130, 'parent_pid': 120,
        'process_group': 130, 'session': 130, 'launch_id': request['launch_id'], 'supervisor_pid': 120,
        'image': facts(image), 'phase': 'waiting_exec', 'source_complete': False}
    for name, value in (('native-request.json', request), ('native-plan.json', plan), ('native-prepared.json', prepared),
                        ('native-supervisor-start.json', supervisor), ('native-application-start.json', application)):
        write(runtime / name, value)
    write(folder / 'command.json', command); write(folder / 'process.json', {'argv': command, 'pid': 120})
    write(runtime / 'oteleq-native-start.json', {'schema_version': 1, 'kind': 'oteleq.native.owned-start',
        'supervisor': {key: supervisor[key] for key in ('pid', 'parent_pid', 'process_group', 'session')},
        'application': {key: application[key] for key in ('pid', 'parent_pid', 'process_group', 'session')},
        'records': [facts(runtime / name) for name in ('native-supervisor-start.json', 'native-application-start.json')]})
    write(runtime / 'native-host-release.json', {'schema_version': 1, 'kind': 'otelc.native.host-release',
        'launch_id': request['launch_id'], 'pid': 130, 'supervisor_pid': 120})
    write(runtime / 'oteleq-native-finish.json', {'schema_version': 1, 'kind': 'oteleq.native.owned-finish',
        'supervisor_pid': 120, 'application_pid': 130, 'application_exit_code': 0, 'sdk_pid': None if plain else 130,
        'scope': 'owned completion; direct downstream telemetry qualification remains separate'})
    witness = capture(folder, plain=plain)
    health = None
    if not plain:
        def exports(unit: str, count: int) -> dict:
            return {'unit': unit, 'exporters_observed': 1, 'batches_started': '2', 'batches_succeeded': '2',
                'batches_failed': '0', 'batches_pending': '0', 'units_started': str(count),
                'units_succeeded': str(count), 'units_failed': '0'}
        health = {'schema_version': 1, 'kind': 'otelc.runtime-health', 'language': 'c', 'pid': 130,
            'phase': 'final', 'scope': 'sdk_pipeline', 'sdk_attached': True, 'source_complete': False,
            'policy_sha256': seal(policy), 'selection_sha256': seal({key: policy[key] for key in ('sources', 'functions')}),
            'controls': {'schema_version': 1, 'pid': 130, 'collection': True, 'emission': True, 'effective_emission_off': False},
            'lifecycle': {'flush': 'succeeded', 'shutdown': 'succeeded'},
            'function_accounting': {'registered': '1', 'started': '1', 'ended': '1', 'active': '0', 'closed': True,
                'lost': '0', 'invalid': '0', 'metadata_errors': '0'},
            'span_accounting': {'sampled_started': '1', 'sampled_ended': '1', 'sampled_active': '0',
                'queue_dropped': '0', 'queue_pending': '0', 'queue_evidence': 'derived_after_shutdown',
                'processors_observed': 1, 'batch_processors_observed': 1},
            'trace_exports': exports('spans', 1), 'metric_exports': exports('metric_points', 3),
            'metric_flush': {'attempts': '1', 'failed_attempts': '0'}, 'diagnostics': {'dropped': '0'},
            'downstream_receipt': 'unavailable', 'otlp_partial_rejection': 'unavailable'}
        write(runtime / 'app/health.json', health)
    write(runtime / 'native-execution.json', {'schema_version': 1, 'kind': 'otelc.native.execution', 'profile': 'native-owned-v1',
        'request_sha256': seal(request), 'plan_sha256': seal(plan), 'supervisor': supervisor, 'application': application,
        'released': True, 'process_exit_code': 0, 'supervisor_exit_code': 0, 'inputs_rechecked': True,
        'sdk_health': health, 'failures': {}, 'exec_verified': False, 'source_complete': False})
    write(folder / 'native-caller/caller.json', {'entry': ENTRY, 'arguments': [5], 'kind': 'oteleq.native.caller',
        'schema_version': 1, 'source_complete': False})
    return folder, provider, witness


class NativeReceiptQualificationTests(unittest.TestCase):
    def test_complete_owned_plain_and_instrumented_normal_calls(self):
        for plain in (False, True):
            with self.subTest(plain=plain), tempfile.TemporaryDirectory() as temporary:
                folder, provider, witness = fixture(Path(temporary).resolve(), plain=plain)
                oracle.attempt(folder, ENTRY, 'baseline' if plain else 'instrumented_on', witness, provider, [5])

    def test_changed_host_sdk_image_caller_and_health_refuse(self):
        mutations = [('native-runtime/native-request.json', 'wait_ms', 1),
                     ('native-runtime/native-prepared.json', 'interpreter_spelling', '/foreign/python'),
                     ('native-runtime/native-application-start.json', 'parent_pid', 999),
                     ('native-runtime/oteleq-native-start.json', 'schema_version', 2),
                     ('native-runtime/native-host-release.json', 'pid', 999),
                     ('native-runtime/oteleq-native-finish.json', 'application_exit_code', 1),
                     ('native-runtime/app/health.json', 'pid', 999),
                     ('native-runtime/native-execution.json', 'exec_verified', True),
                     ('native-caller/caller.json', 'arguments', [0]), ('process.json', 'argv', ['/foreign/python'])]
        for name, field, value in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                folder, provider, witness = fixture(Path(temporary).resolve())
                path = folder / name; row = oracle.read(path); row[field] = value; write(path, row)
                with self.assertRaises(ValueError):
                    oracle.attempt(folder, ENTRY, 'instrumented_on', witness, provider, [5])

    def test_wrong_health_units_losses_or_unavailable_dimensions_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder, _, _ = fixture(Path(temporary).resolve())
            original = oracle.read(folder / 'native-runtime/app/health.json')
            policy = oracle.tomllib.loads((folder / 'policy.toml').read_text())
            for section, field, value in [('metric_exports', 'units_succeeded', '2'),
                    ('trace_exports', 'batches_failed', '1'), ('function_accounting', 'lost', '1'),
                    ('metric_flush', 'attempts', '0'), ('trace_exports', 'batches_started', '02'),
                    ('controls', 'collection', False)]:
                row = copy.deepcopy(original); row[section][field] = value
                with self.subTest(section=section, field=field), self.assertRaises(ValueError):
                    oracle.health(row, policy, 'c', 130, 3, 1, 1)

    def test_protobuf_signal_and_transport_mutations_refuse(self):
        for mutation in ('service', 'scope', 'span', 'metric', 'sum', 'bucket', 'protobuf', 'response', 'extra-body'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); capture(root)
                trace, metric = signals()
                if mutation == 'service':
                    trace.resource_spans[0].resource.attributes[0].value.string_value = 'foreign'
                elif mutation == 'scope':
                    trace.resource_spans[0].scope_spans[0].scope.name = 'foreign'
                elif mutation == 'span':
                    trace.resource_spans[0].scope_spans[0].spans[0].parent_span_id = b'p' * 8
                elif mutation == 'metric':
                    metric.resource_metrics[0].scope_metrics[0].metrics[0].sum.data_points[0].as_int = 0
                elif mutation in ('sum', 'bucket'):
                    point = metric.resource_metrics[0].scope_metrics[0].metrics[2].histogram.data_points[0]
                    if mutation == 'sum': point.sum = .5
                    else: point.bucket_counts[6] = 0; point.bucket_counts[7] = 1
                (root / 'otlp-0.protobuf').write_bytes(b'\xff' if mutation == 'protobuf' else trace.SerializeToString())
                (root / 'otlp-1.protobuf').write_bytes(metric.SerializeToString())
                if mutation == 'response':
                    row = oracle.read(root / 'http-responses.json'); row['events'][0]['status'] = 503
                    write(root / 'http-responses.json', row)
                if mutation == 'extra-body':
                    (root / 'otlp-2.protobuf').write_bytes(b'foreign')
                with self.assertRaises(ValueError):
                    otlp.receipt(root, oracle.read, 'c', SERVICE, FUNCTION, plain=False)

    def test_cumulative_histograms_keep_single_call_and_zero_states(self):
        _, metric = signals(); point = metric.resource_metrics[0].scope_metrics[0].metrics[2].histogram.data_points[0]
        expected = otlp.histogram(point)
        point.count = 0; point.sum = point.min = point.max = 0
        point.bucket_counts[:] = [0] * 8
        self.assertEqual(otlp.histogram(point), (0, (0,) * 8, 0))
        series = {'otelc.function.calls': [(1, 2, 0, (), 0), (1, 3, 1, (), 0)],
                  'otelc.function.duration': [(1, 2, 0, (0,) * 8, 0), (1, 3, *expected), (1, 4, *expected)]}
        otlp.totals(series)
        series['otelc.function.duration'][-1] = (1, 4, 1, expected[1], .5)
        with self.assertRaises(ValueError): otlp.totals(series)
        with self.assertRaises(ValueError): otlp.totals({})

    def test_original_file_facts_json_and_complete_archive_denominators(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); path = root / 'evidence.json'
            write(path, {'value': 1}); self.assertEqual(oracle.identity(path, private=True), facts(path))
            for contents in ('{"x":1,"x":2}', '{"x":NaN}'):
                path.write_text(contents)
                with self.assertRaises(ValueError): oracle.read(path)
            path.chmod(0o644)
            with self.assertRaises(ValueError): oracle.identity(path, private=True)
            original = root / 'original'; original.mkdir(); (original / 'empty').mkdir()
            write(original / 'data.json', {'value': 1}); copied = root / 'copy'; shutil.copytree(original, copied)
            oracle.archive(original, copied)
            copied.chmod(0o700 if original.stat().st_mode & 0o777 != 0o700 else 0o755)
            with self.assertRaises(ValueError): oracle.archive(original, copied)
            copied.chmod(original.stat().st_mode & 0o777)
            (copied / 'empty').rmdir()
            with self.assertRaises(ValueError): oracle.archive(original, copied)
            with self.assertRaises(ValueError): oracle.archive(original, original)

    def test_archive_registry_requires_one_actual_original_and_counts_copies_separately(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); original = root / 'actual'; original.mkdir()
            report = original / 'report.json'; write(report, {'cases': [{'case': 'fixture'}]})
            for index, lane in enumerate(oracle.LANES):
                runtime = original / 'fixture' / lane / 'native-runtime'
                write(runtime / 'native-request.json', {'runtime': str(runtime), 'launch_id': format(index + 1, '032x')})
            copied = root / 'copied'; shutil.copytree(original, copied)
            selected = oracle.Oracle(root, root)
            self.assertEqual(selected.original(copied / 'report.json'), report)
            with patch.object(oracle, 'attempt') as audit, patch.object(oracle, 'identity', return_value={'held': True}):
                selected(copied / 'report.json', copied / 'fixture/baseline-0', ENTRY, 'baseline', None, [5])
                self.assertEqual(audit.call_args.args[0], original / 'fixture/baseline-0')
            self.assertEqual(selected.summary()['actual_application_records'], 1)
            self.assertEqual(selected.summary()['archived_reports'], 1)
            duplicate = root / 'duplicate'; shutil.copytree(original, duplicate)
            for lane in oracle.LANES:
                runtime = duplicate / 'fixture' / lane / 'native-runtime'
                path = runtime / 'native-request.json'; row = oracle.read(path); row['runtime'] = str(runtime)
                write(path, row)
            with self.assertRaises(ValueError): selected.original(copied / 'report.json')
            shutil.rmtree(duplicate)
            selected = oracle.Oracle(root, root)
            write(copied / 'unexpected.json', {})
            with self.assertRaises(ValueError): selected.original(copied / 'report.json')
            shutil.rmtree(original)
            with self.assertRaises(ValueError): selected.original(copied / 'report.json')

    def test_actual_refusal_corpus_preserves_original_files_and_detects_later_rewrites(self):
        for rewrite in (False, True):
            with self.subTest(rewrite=rewrite), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve(); folder, provider, witness = fixture(root)
                selected = oracle.Oracle(root, provider)
                report = root / 'report.json'
                with patch.object(selected, 'original', return_value=report):
                    selected(report, folder, ENTRY, 'instrumented_on', witness, [5])
                if rewrite:
                    write(report, {'changed': True})
                    with self.assertRaises(ValueError): selected.finish()
                else:
                    result = selected.finish()
                    self.assertEqual(result['altered_evidence_refusals'], 13)
                    self.assertGreaterEqual(result['original_evidence_files_held'], 20)


if __name__ == '__main__':
    unittest.main()
