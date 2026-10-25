"""Authored native metric records for reader regressions; no real applications."""

import hashlib
import json
from pathlib import Path

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

import native_metric_cases as cases
from qualify_project_tests import toml
from test_generation_native_receipt_qualification import fixture, seal, write

BOUNDS = [1e-6, 1e-5, 1e-4, .001, .01, .1, 1.]


def labels(rows, values: dict) -> None:
    for key, value in values.items():
        rows.add(key=key).value.string_value = value


class Capture:
    """Construct literal private files, scalar bytes and protobuf accounting."""

    def __init__(self, root: Path, language='c', mode='normal', start='11', amount=5,
                 *, plain=False, version=42, byte_order='little', lane_name='attempt'):
        self.folder, self.provider, _ = fixture(root, plain=plain, name=lane_name)
        self.language, self.mode, self.start, self.amount = language, mode, start, amount
        self.plain, self.version, self.byte_order = plain, version, byte_order
        self.flags = cases.schedule(start)[0]
        self.entry = {'language': language, 'path': 'app.' + ('cpp' if language == 'cpp' else 'c'),
            'name': 'selected', 'otelc_function': cases.function(language), 'output': 'int',
            'parameters': ['int'], 'globals': [{'name': name, 'type': 'int'} for name in ('calls', 'depth', 'state')],
            'native_backend': 'prepared', 'sequence_configuration': cases.configuration(language, mode, start, root)['fixtures'][0]['sequence']}
        self.name = self.entry['path'] + '::' + self.entry['otelc_function']
        request = json.loads((self.folder / 'native-runtime/native-request.json').read_bytes())
        self.policy = request['policy']
        self.policy.update(languages=[language], sources={'include': [self.entry['path']], 'exclude': []},
                           functions={'include': [self.entry['otelc_function']], 'exclude': []})
        self.policy['metrics'].update(self.flags)
        self.service = self.policy['resource']['service_name']
        (self.folder / 'policy.toml').write_text('\n'.join(key + '=' + toml(value) for key, value in self.policy.items()) + '\n')
        for path in self.folder.glob('otlp-*.protobuf'):
            path.unlink()
        self.bodies = []
        self.total = self.collected = self.errors = self.clock = 0
        self.calls = amount + 1 if mode == 'recursive' else 1
        self.record = {'schema_version': 1, 'kind': 'oteleq.native.live-controls', 'plain': plain,
            'pid': 130, 'supervisor_pid': 120, 'policy_sha256': seal(self.policy),
            'selection_sha256': seal({key: self.policy[key] for key in ('sources', 'functions')}),
            'interval_ms': 1000, 'steps': [], 'restored': None}
        self.frames()
        self.checkpoints()
        self.final = None
        if not plain:
            self.metric()
            self.final = self.health(final=True)
            write(self.folder / 'native-runtime/app/health.json', self.final)
            write(self.folder / 'native-runtime/app/control.json', {'pid': 130, 'token': 'c' * 64})
        self.capture()
        request['policy'] = self.policy
        write(self.folder / 'native-runtime/native-request.json', request)
        plan = json.loads((self.folder / 'native-runtime/native-plan.json').read_bytes())
        plan['request_sha256'] = seal(request)
        write(self.folder / 'native-runtime/native-plan.json', plan)
        prepared = json.loads((self.folder / 'native-runtime/native-prepared.json').read_bytes())
        prepared.update(request_sha256=seal(request), plan_sha256=seal(plan))
        write(self.folder / 'native-runtime/native-prepared.json', prepared)
        final = json.loads((self.folder / 'native-runtime/native-execution.json').read_bytes())
        final.update(request_sha256=seal(request), plan_sha256=seal(plan), sdk_health=self.final)
        write(self.folder / 'native-runtime/native-execution.json', final)
        write(self.folder / 'native-caller/caller.json', {'schema_version': 1, 'kind': 'oteleq.native.caller',
            'entry': self.entry, 'arguments': [amount], 'source_complete': False})

    def status(self) -> dict | None:
        return None if self.plain else {'schema_version': 1, 'pid': 130, **self.flags,
                                       'effective_emission_off': not all(self.flags.values())}

    def transition(self, flags: dict) -> list:
        if self.plain:
            self.flags = flags
            return []
        rows = [{'command': 'status', 'status': self.status()}]
        for key in ('collection', 'emission'):
            if self.flags[key] is not flags[key]:
                self.flags = {**self.flags, key: flags[key]}
                rows.append({'command': key + (' on' if flags[key] else ' off'), 'status': self.status()})
        return rows

    def group(self, message, traces: bool):
        group = (message.resource_spans if traces else message.resource_metrics).add()
        labels(group.resource.attributes, {'service.name': self.service, 'otelc.language': self.language,
            'telemetry.sdk.language': 'cpp', 'telemetry.sdk.name': 'opentelemetry', 'telemetry.sdk.version': '1.30.0'})
        scope = (group.scope_spans if traces else group.scope_metrics).add()
        scope.scope.name = 'io.quux.otelc.native'
        return scope

    def trace(self, index: int) -> None:
        message = ExportTraceServiceRequest(); scope = self.group(message, True)
        for depth in reversed(range(self.calls)):
            span = scope.spans.add(name=self.name, kind=1, flags=1,
                trace_id=(index + 1).to_bytes(16, 'big'), span_id=(32 * index + depth + 1).to_bytes(8, 'big'),
                start_time_unix_nano=100_000 * (index + 1) + 2 * depth,
                end_time_unix_nano=100_000 * (index + 1) + 10_000 - 2 * depth)
            if depth:
                span.parent_span_id = (32 * index + depth).to_bytes(8, 'big')
            values = {'function': self.name}
            if self.mode == 'error' and index == 1 and depth == 0:
                span.status.code = 2; values['error.type'] = 'exception'
            labels(span.attributes, values)
        self.bodies.append(('/v1/traces', message.SerializeToString()))

    def metric(self) -> None:
        if self.plain or not self.collected or not all(self.flags.values()):
            return
        message = ExportMetricsServiceRequest(); scope = self.group(message, False)
        self.clock += 1
        for suffix, unit in (('calls', '{call}'), ('errors', '{error}'), ('duration', 's')):
            metric = scope.metrics.add(name='otelc.function.' + suffix, unit=unit)
            data = metric.histogram if suffix == 'duration' else metric.sum
            data.aggregation_temporality = 2
            point = data.data_points.add(start_time_unix_nano=1, time_unix_nano=100 + self.clock)
            labels(point.attributes, {'function': self.name, **({'error.type': 'exception'} if suffix == 'errors' else {})})
            if suffix == 'duration':
                point.count = self.collected; point.sum = self.collected * .01; point.min = point.max = .01
                point.explicit_bounds.extend(BOUNDS)
                point.bucket_counts.extend([0, 0, 0, 0, self.collected, 0, 0, 0])
            else:
                data.is_monotonic = True; point.as_int = self.errors if suffix == 'errors' else self.collected
        self.bodies.append(('/v1/metrics', message.SerializeToString()))

    def health(self, *, final=False) -> dict | None:
        if self.plain:
            return None
        def exports(unit, batches, units):
            return {'exporters_observed': 1, 'unit': unit, 'batches_started': str(batches),
                'batches_succeeded': str(batches), 'batches_failed': '0', 'batches_pending': '0',
                'units_started': str(units), 'units_succeeded': str(units), 'units_failed': '0'}
        traces = sum(route == '/v1/traces' for route, _ in self.bodies)
        metrics = len(self.bodies) - traces
        return {'schema_version': 1, 'kind': 'otelc.runtime-health', 'language': self.language, 'pid': 130,
            'phase': 'final' if final else 'running', 'scope': 'sdk_pipeline', 'sdk_attached': True,
            'source_complete': False, 'policy_sha256': seal(self.policy),
            'selection_sha256': seal({key: self.policy[key] for key in ('sources', 'functions')}),
            'controls': self.status(), 'lifecycle': {'flush': 'succeeded', 'shutdown': 'succeeded' if final else 'not_started'},
            'function_accounting': {'registered': '1', 'started': str(self.total), 'ended': str(self.total),
                'active': '0', 'closed': final, 'lost': '0', 'invalid': '0', 'metadata_errors': '0'},
            'span_accounting': {'sampled_started': str(self.total), 'sampled_ended': str(self.total), 'sampled_active': '0',
                'queue_pending': '0' if final else None, 'queue_dropped': '0' if final else None,
                'queue_evidence': 'derived_after_shutdown' if final else 'unavailable',
                'processors_observed': 1, 'batch_processors_observed': 1},
            'metric_flush': {'attempts': str(max(1, metrics)), 'failed_attempts': '0'},
            'trace_exports': exports('spans', traces, self.total), 'metric_exports': exports('metric_points', metrics, 3 * metrics),
            'diagnostics': {'dropped': '0'}, 'downstream_receipt': 'unavailable', 'otlp_partial_rejection': 'unavailable'}

    def checkpoints(self) -> None:
        def publication():
            write(self.folder / ('native-live-' + str(len(list(self.folder.glob('native-live-*.json')))) + '.json'), self.record)
        for index, flags in enumerate(cases.schedule(self.start)):
            history = self.transition(flags); self.metric()
            before = {'history': history, 'flush': self.status(), 'health': self.health(), 'cursor': len(self.bodies)}
            step = {'id': 'step-' + str(index), 'requested': flags, 'before': before, 'after': None}
            self.record['steps'].append(step); publication()
            self.total += self.calls
            if not self.plain:
                self.trace(index)
            if flags['collection']:
                self.collected += self.calls; self.errors += int(self.mode == 'error' and index == 1)
            self.metric(); status = self.status(); first = self.health()
            self.metric()
            end = len(self.bodies)
            step['after'] = {'status': status, 'flush': status, 'health': first,
                'settled_flush': self.status(), 'settled': self.health(), 'cursor': end,
                'metric_bodies': [i for i in range(before['cursor'], end) if self.bodies[i][0] == '/v1/metrics'],
                'held_ns': 0 if all(flags.values()) else 1_000_000_001}
            publication()
        history = self.transition({'collection': True, 'emission': True}); self.metric()
        self.record['restored'] = {'history': history, 'flush': self.status(), 'health': self.health(), 'cursor': len(self.bodies)}
        publication(); write(self.folder / 'native-controls.json', self.record)

    def frames(self) -> None:
        root = self.folder / 'native-rendezvous'; root.mkdir(mode=0o700)
        phases = [phase + '-' + str(index) for index in range(4) for phase in ('before', 'after')] + ['finish']
        for phase in phases:
            for suffix in ('ready', 'resume'):
                (root / (phase + '.' + suffix)).mkdir(mode=0o700)
                write(root / (phase + '.' + suffix + '.json'), {'nonce': 'e' * 32, 'phase': phase})
        names = ('int', 'long', 'short', 'signed', 'signed int', 'long long', 'unsigned', 'unsigned int',
                 'unsigned long', 'unsigned short', 'unsigned long long', 'char', 'signed char', 'unsigned char', 'float', 'double')
        abi = {'byte_order': self.byte_order, 'char_signed': True, 'char_bits': 8, 'ieee754': True,
               'bits': {name: 8 if 'char' in name else 16 if 'short' in name else 64 if 'long' in name or name == 'double' else 32
                        for name in names}}
        integer = lambda value: int(value).to_bytes(4, self.byte_order, signed=True).hex().encode()
        def state(graph):
            return b''.join(item['name'].encode() + b':int:' + integer(graph['roots']['global:' + item['name']]['value']) + b'\n'
                            for item in self.entry['globals'])
        rows = []
        for index, step in enumerate(cases.expected(self.language, self.mode, self.amount,
                                                   instrumented=not self.plain, version=self.version)):
            outcome = step['outcome']
            value = (b'error:std::runtime_error\t' + ('failure-' + str(self.version) + '\nafter').encode()
                     if outcome['kind'] == 'error' else b'return:int:' + integer(outcome['graph']['roots']['result']['value']))
            raw = b'abi:' + json.dumps(abi).encode() + b'\nbefore\n' + state(step['before']) + value + b'\nafter\n' + state(step['after'])
            path = root / ('step-' + str(index) + '.observation'); path.write_bytes(raw); path.chmod(0o600)
            rows.append({'id': 'step-' + str(index), 'raw_hex': raw.hex()})
        write(self.folder / 'observation', {'schema_version': 1, 'kind': 'oteleq.native.scalar-sequence', 'frames': rows})

    def capture(self) -> None:
        rows, events, digest = [], [], hashlib.sha256()
        for index, (route, raw) in enumerate(self.bodies):
            filename = 'otlp-' + str(index) + '.protobuf'; (self.folder / filename).write_bytes(raw)
            rows.append({'path': route, 'file': filename})
            events.append({'body_index': index, 'path': route, 'status': 200, 'headers_write_failed': False,
                'request_started_ns': index * 10 + 1, 'body_received_ns': index * 10 + 2,
                'response_started_ns': index * 10 + 3, 'headers_written_ns': index * 10 + 4, 'handler_finished_ns': index * 10 + 5})
            digest.update(len(route).to_bytes(8, 'big') + route.encode() + len(raw).to_bytes(8, 'big') + raw)
        write(self.folder / 'http-capture.json', {'errors': [], 'bodies': rows})
        write(self.folder / 'http-responses.json', {'schema_version': 1, 'scope': 'server response headers; client acknowledgement is not observed',
            'clock': 'monotonic_ns', 'unrecorded_events': 0, 'events': events})
        self.witness = None
        if not self.plain:
            self.witness = {'decoder': 'native owned live controls, scalar frames and complete raw OTLP',
                'raw_otlp_sha256': digest.hexdigest(), 'functions': {self.name: self.total}, 'spans': self.total,
                'losses': {'function_lost': 0, 'metadata_errors': 0, 'queue_dropped': 0, 'diagnostic_dropped': 0}, 'pending': 0}
            write(self.folder / 'native-verified-controls.json', {**self.witness,
                'collected_functions': {self.name: self.collected}, 'collected_errors': {self.name: self.errors} if self.errors else {},
                'metric_points': sum(route == '/v1/metrics' for route, _ in self.bodies) * 3, 'health': self.final})
