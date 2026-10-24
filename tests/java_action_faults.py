"""Alter real retained inputs in private copies; each control must refuse admission."""

import copy
import json
from pathlib import Path
import shutil
import tempfile

import java_action_audit as audit
import java_action_fixture as fixture
import typed_capture

KINDS = ('foreign-thread', 'foreign-attempt', 'foreign-retry', 'missing-method', 'unscoped-method',
         'wrong-probe', 'unverified-route', 'role-metrics', 'missing-duration', 'missing-metrics',
         'health-without-roles', 'wrong-binding-profile', 'wrong-outcome', 'foreign-process',
         'coerced-version', 'missing-action')


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, separators=(',', ':')) + '\n')


def traces(folder: Path, edit) -> None:
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    for record in audit.read(folder / 'http-capture.json')['bodies']:
        if record['path'] != '/v1/traces':
            continue
        path = folder / record['file'];message = ExportTraceServiceRequest.FromString(path.read_bytes())
        if edit(message):
            path.write_bytes(message.SerializeToString())
            return
    raise AssertionError('control did not find a real span')


def metrics(folder: Path, edit) -> None:
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    changed = False
    for record in audit.read(folder / 'http-capture.json')['bodies']:
        if record['path'] == '/v1/metrics':
            path = folder / record['file'];message = ExportMetricsServiceRequest.FromString(path.read_bytes())
            changed |= edit(message)
            path.write_bytes(message.SerializeToString())
    assert changed


def alter(folder: Path, kind: str, observed: dict) -> dict:
    """Rehash publication metadata where needed so the semantic guard is exercised."""
    host_path = folder / 'java-actions/record.json';host = audit.read(host_path)
    if kind == 'foreign-thread':
        row = host['harness'][0];row['thread_id'] = str(int(row['thread_id']) + 1)
        words = row['ready'].split(' ');words[-1] = row['thread_id'] + '\n';row['ready'] = ' '.join(words)
        row['release'] = row['ready'].replace('2 ready ', '2 release ', 1)
        host['armed'][0]['ready'] = {key: value for key, value in row.items() if key != 'release'}
    elif kind == 'foreign-attempt':
        host['attempt_id'] = '0' * 64
    elif kind == 'foreign-retry':
        for record in host['controls']:
            path = host_path.parent / record['file'];rows = audit.read(path)
            selected = next((row for row in rows if row['operation'] == 'end'), None)
            if selected is not None:
                selected['reply']['error'] = 'root_active'
                selected['reply']['scope'].update(cookie='0' * 32, producer_complete=False, phase='incomplete')
                write(path, rows);record['sha256'] = audit.sha(path)
                break
        else:
            raise AssertionError('control did not find a real end reply')
    elif kind in ('missing-method', 'unscoped-method', 'wrong-probe'):
        def edit(message):
            for resource in message.resource_spans:
                for group in resource.scope_spans:
                    if group.scope.name != ('io.quux.otelc.witness' if kind == 'wrong-probe' else 'io.opentelemetry.methods'):
                        continue
                    if not group.spans:
                        continue
                    if kind == 'missing-method':
                        del group.spans[0]
                    else:
                        span = group.spans[0]
                        for index, attribute in enumerate(span.attributes):
                            if attribute.key == ('otelc.witness.probe_id' if kind == 'wrong-probe' else 'otelc.witness.scope_id'):
                                if kind == 'wrong-probe':attribute.value.string_value = '0' * 64
                                else:del span.attributes[index]
                                break
                        else:
                            continue
                    return True
            return False
        traces(folder, edit)
    elif kind in ('unverified-route', 'coerced-version', 'missing-action'):
        path = folder / 'sdk-runtime/witness-health.json';value = audit.read(path)
        if kind == 'unverified-route':value['scopes'][0]['route_verified'] = False
        elif kind == 'coerced-version':value['schema_version'] = 3.0
        else:value['scopes'].pop()
        write(path, value)
    elif kind in ('role-metrics', 'missing-duration'):
        def edit(message):
            changed = False
            for resource in message.resource_metrics:
                for group in resource.scope_metrics:
                    for index in range(len(group.metrics) - 1, -1, -1):
                        metric = group.metrics[index]
                        if metric.name not in ('otelc.function.calls', 'otelc.function.duration'):
                            continue
                        if kind == 'missing-duration' and metric.name.endswith('duration'):
                            del group.metrics[index];changed = True
                        elif kind == 'role-metrics':
                            for point in getattr(metric, metric.WhichOneof('data')).data_points:
                                if metric.name.endswith('calls'):point.as_int = 3 * max(1, point.as_int)
                                else:
                                    point.count = 3 * max(1, point.count)
                                    point.bucket_counts[:] = [point.count] + [0] * len(point.explicit_bounds)
                                changed = True
            return changed
        metrics(folder, edit)
    elif kind == 'missing-metrics':
        path = folder / 'http-capture.json';value = audit.read(path)
        value['bodies'] = [row for row in value['bodies'] if row['path'] != '/v1/metrics'];write(path, value)
    elif kind == 'health-without-roles':
        path = folder / 'sdk-runtime/health.json';value = audit.read(path)
        value['span_accounting'].update(sampled_started='1', sampled_ended='1')
        value['trace_exports'].update(units_started='1', units_succeeded='1');write(path, value)
    elif kind == 'wrong-binding-profile':
        path = folder / 'action-bindings/bindings.json';value = audit.read(path)
        value['profile'] = 'java-sync-action-v2';write(path, value)
        path = folder / 'action-bindings/compiler-inputs.json';value = audit.read(path)
        value['bindings_sha256'] = audit.sha(path.with_name('bindings.json'));write(path, value)
        host['compiler_inputs'] = {'bindings_sha256': value['bindings_sha256'], 'record_sha256': audit.sha(path)}
    elif kind == 'wrong-outcome':
        assert observed['function_id'] == fixture.STATIC
        path = folder / 'observation';raw = path.read_bytes()
        assert b'return:java.lang.Integer:Nw==' in raw
        path.write_bytes(raw.replace(b'return:java.lang.Integer:Nw==',
            b'error:java.lang.IllegalStateException:string:utf16:006e006f'))
        entry = {'language': 'java', 'parameters': ['int'], 'output': 'int',
                 'globals': [{'name': 'Work.total', 'type': 'int'}]}
        observed = typed_capture.observation(path.read_bytes(), entry,
            {key: observed[key] for key in ('case_id', 'function_id', 'fixture_sha256')})
        write(folder / 'typed-observation.json', observed)
    elif kind == 'foreign-process':
        path = folder / 'process.json';value = audit.read(path);value['pid'] = True;write(path, value)
    else:
        raise AssertionError('unknown control')
    write(host_path, host)
    archive = audit.read(folder / 'runtime-archive.json')
    for name, value in archive['files'].items():
        value['sha256'] = audit.sha(folder / 'sdk-runtime' / name)
    write(folder / 'runtime-archive.json', archive)
    return observed


def qualify(report: Path, destination: Path | None = None) -> list[dict]:
    """Start no applications; positive retained evidence must pass before mutations."""
    value = audit.read(report)
    case = next(row for row in value['cases'] if row['function'] == fixture.STATIC)
    original = report.parent / case['case'] / 'instrumented_on-0'
    frozen = audit.read(original.parent / 'corpus.json')
    entry = next(row for row in value['inventory'] if row['id'] == frozen['function_id'])
    observed = audit.read(original / 'typed-observation.json')
    audit.attempt(original, entry, frozen, observed, plain=False)
    before = audit.inventory(original)
    if destination is not None:
        destination.mkdir()
    rows = []
    for kind in KINDS:
        with tempfile.TemporaryDirectory(prefix='oe-ja-fault-') as temporary:
            folder = Path(temporary).resolve() / 'attempt';shutil.copytree(original, folder)
            changed = alter(folder, kind, copy.deepcopy(observed))
            try:
                audit.attempt(folder, entry, frozen, changed, plain=False)
            except (AssertionError, ValueError) as error:
                row = {'control': kind, 'refused': True, 'reason': str(error) or 'altered evidence violated the retained contract',
                       'type': type(error).__name__}
            else:
                raise AssertionError('altered evidence passed: ' + kind)
            if destination is not None:
                write(destination / (kind + '.json'), row)
            rows.append(row)
    assert audit.inventory(original) == before
    if destination is not None:
        write(destination / 'summary.json', {'new_applications_started': 0, 'controls': rows, 'original_preserved': True})
    return rows
