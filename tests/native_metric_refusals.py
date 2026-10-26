"""Preserve changed copies from genuine native captures and require their refusal."""

import copy
import json
from pathlib import Path
import tomllib

from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

import native_metric_cases as cases
import native_metric_otlp as otlp
import native_metric_receipt as raw
import native_prepared_otlp as wire
import native_prepared_receipt as retained
from qualify_native_metrics import observation


def profile(context: dict, root: Path) -> dict:
    root.mkdir()
    folder, entry = Path(context['folder']), context['entry']
    policy = tomllib.loads((folder / 'policy.toml').read_text())
    record = retained.read(folder / 'native-controls.json')
    bodies = wire.payloads(folder, retained.read)
    app = retained.read(folder / 'native-runtime/native-application-start.json')
    checker = raw.controls(record, bodies, entry, context['start'], context['mode'], context['amount'],
                           policy, app['pid'], app['supervisor_pid'], plain=False)
    name, language, service = checker.name, entry['language'], policy['resource']['service_name']
    off = next(index for index, row in enumerate(record['steps']) if not all(row['requested'].values()))
    setter = next(index for index, row in enumerate(record['steps']) if len(row['before']['history']) > 1)
    rejected = []

    def reject(label, operation):
        try:
            operation()
        except ValueError:
            rejected.append(label)
        else:
            raise AssertionError('changed native capture was accepted: ' + label)

    def control(label, mutate):
        changed = copy.deepcopy(record); mutate(changed)
        (root / (label + '.json')).write_text(json.dumps(changed, indent=2) + '\n')
        reject(label, lambda: raw.controls(changed, bodies, entry, context['start'], context['mode'], context['amount'],
                                           policy, app['pid'], app['supervisor_pid'], plain=False))

    control('control-pid', lambda row: row.update(pid=app['pid'] + 1))
    control('requested-collection', lambda row: row['steps'][0]['requested'].update(collection=not row['steps'][0]['requested']['collection']))
    control('missing-setter', lambda row: row['steps'][setter]['before'].update(history=row['steps'][setter]['before']['history'][:1]))
    control('disabled-barrier', lambda row: row['steps'][off]['before']['history'][-1]['status'].update(effective_emission_off=False))
    control('short-window', lambda row: row['steps'][off]['after'].update(held_ns=1))
    control('health-active', lambda row: row['steps'][0]['after']['health']['function_accounting'].update(active='1'))
    control('health-queue-invented', lambda row: row['steps'][0]['after']['health']['span_accounting'].update(queue_pending='0'))
    control('restored-control', lambda row: row['restored']['health']['controls'].update(collection=False))
    trace = next(index for index, (route, _) in enumerate(bodies) if route == '/v1/traces')
    changed = list(bodies)
    message = ExportTraceServiceRequest.FromString(changed[trace][1])
    message.resource_spans[0].scope_spans[0].spans[0].name = 'foreign-selected-function'
    payload = message.SerializeToString(); (root / 'raw-root-name.protobuf').write_bytes(payload)
    changed[trace] = ('/v1/traces', payload)
    reject('raw-root-name', lambda: otlp.traces(changed, language, service, name, checker.calls, failed=checker.failed))
    changed[trace] = ('/v1/traces', b'\xff'); (root / 'raw-malformed.protobuf').write_bytes(b'\xff')
    reject('raw-malformed', lambda: otlp.traces(changed, language, service, name, checker.calls, failed=checker.failed))
    changed = list(bodies)
    found = False
    for index, (route, body) in enumerate(bodies):
        if route != '/v1/metrics':
            continue
        message = ExportMetricsServiceRequest.FromString(body)
        counters = [metric for group in message.resource_metrics for scope in group.scope_metrics for metric in scope.metrics
                    if metric.name == 'otelc.function.calls']
        if not counters:
            continue
        counters[0].sum.data_points[0].as_int += 1_000_000
        payload = message.SerializeToString(); (root / 'raw-metric-count.protobuf').write_bytes(payload)
        changed[index] = (route, payload); found = True; break
    assert found, 'actual positive metric counter is missing'
    reject('raw-metric-count', lambda: otlp.metrics(changed, language, service, name, checker.collected, checker.errors))
    responses = retained.read(folder / 'http-responses.json')
    changed = copy.deepcopy(responses); changed['events'][0]['status'] = 503
    (root / 'http-failed-response.json').write_text(json.dumps(changed, indent=2) + '\n')
    reject('http-failed-response', lambda: wire.response(changed, bodies))
    changed = copy.deepcopy(responses); changed['events'].pop()
    (root / 'response-denominator.json').write_text(json.dumps(changed, indent=2) + '\n')
    reject('response-denominator', lambda: wire.response(changed, bodies))
    bundle = retained.read(folder.parent / 'typed-bundle.json')['cases'][0]
    index = context['repeat']; assert type(index) is int and index in (0, 1)
    value = copy.deepcopy(bundle['instrumented_on'][index]['observation'])
    value['steps'][1]['after']['roots']['global:state']['value'] = '999999'
    (root / 'intermediate-state.json').write_text(json.dumps(value, indent=2) + '\n')
    expected = cases.expected(language, context['mode'], context['amount'], instrumented=True, version=context['version'])
    reject('intermediate-state', lambda: observation(value, bundle['contract'], entry, expected))
    assert len(rejected) == len(set(rejected)) == 14
    result = {'rejected': rejected, 'count': len(rejected), 'new_application_launches': 0,
              'original_folder': str(folder), 'mode': context['mode'], 'start': context['start']}
    (root / 'refusals.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def refusals(audit, root: Path) -> dict:
    root.mkdir()
    selected = {}
    for context in audit.contexts.values():
        selected.setdefault(context['mode'], context)
    assert set(selected) == set(cases.MODES[audit.language])
    return {mode: profile(selected[mode], root / mode) for mode in cases.MODES[audit.language]}
