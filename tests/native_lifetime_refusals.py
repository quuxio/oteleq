"""Check altered raw capture copies without changing original SDK evidence."""

import copy
import json
from pathlib import Path
import shutil

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

import native_lifetime_audit as audit
import native_prepared_otlp as transport
import native_prepared_receipt as records


def run(source: Path, entry: dict, witness: dict, destination: Path, *, function: str = 'selected') -> dict:
    """A changed summary cannot make any declared corrupt capture acceptable."""
    audit.verify(source, entry, witness, plain=False, function=function)
    destination.mkdir()
    manifest = records.read(source / 'http-capture.json')
    names = ['policy.toml', 'http-capture.json', 'http-responses.json',
             'expected-lifetimes-before-build.json', 'expected-lifetimes.json', 'native-verified-lifetimes.json',
             'native-runtime/native-request.json', 'native-runtime/native-application-start.json',
             'native-runtime/app/health.json', *(row['file'] for row in manifest['bodies'])]
    held = {name: records.identity(source / name, owned=True) for name in names}
    trace_name = None
    for row in manifest['bodies']:
        if row['path'] == '/v1/traces':
            message = ExportTraceServiceRequest.FromString((source / row['file']).read_bytes())
            if any(span.name == 'Item lifetime' for span in transport.groups(
                    message, entry['language'], records.read(source / 'native-runtime/native-request.json')['policy']['resource']['service_name'], traces=True)):
                trace_name = row['file']
    assert trace_name is not None
    changes = ('creation-link', 'completion-type', 'missing-span', 'malformed-protobuf', 'failed-response',
               'completed-units', 'censored-units', 'span-units', 'metric-units', 'closed-type',
               'summary-spans', 'witness-hash', 'witness-type', 'declared-completion')
    refused = []
    try:
        for name in changes:
            folder = destination / name; folder.mkdir()
            for filename in names:
                target = folder / filename; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / filename, target)
            altered = copy.deepcopy(witness)
            def write(filename: str, value: object) -> None:
                (folder / filename).write_text(json.dumps(value))
            if name in ('creation-link', 'completion-type', 'missing-span'):
                message = ExportTraceServiceRequest.FromString((folder / trace_name).read_bytes())
                for resource in message.resource_spans:
                    for scope in resource.scope_spans:
                        for index, span in enumerate(scope.spans):
                            if span.name != 'Item lifetime': continue
                            if name == 'creation-link':
                                old = span.links[0].span_id
                                span.links[0].span_id = bytes([old[0] ^ 1]) + old[1:]
                            elif name == 'completion-type':
                                next(a for a in span.attributes if a.key == 'otelc.lifetime.complete').value.int_value = 1
                            else:
                                del scope.spans[index]
                            break
                (folder / trace_name).write_bytes(message.SerializeToString())
            elif name == 'malformed-protobuf': (folder / trace_name).write_bytes(b'\xff')
            elif name == 'failed-response':
                value = records.read(folder / 'http-responses.json'); value['events'][0]['status'] = 503
                write('http-responses.json', value)
            elif name in ('completed-units', 'censored-units', 'span-units', 'metric-units', 'closed-type'):
                value = records.read(folder / 'native-runtime/app/health.json')
                key = 'object_accounting' if entry['language'] == 'cpp' else 'resource_accounting'
                if name == 'completed-units': value[key]['completed'] = '2'
                elif name == 'censored-units': value[key]['censored'] = '1'
                elif name == 'span-units': value['span_accounting']['sampled_ended'] = '1'
                elif name == 'metric-units': value['metric_exports']['units_succeeded'] = '0'
                elif name == 'closed-type': value[key]['closed'] = 1
                write('native-runtime/app/health.json', value)
                summary = records.read(folder / 'native-verified-lifetimes.json'); summary['health'] = value
                write('native-verified-lifetimes.json', summary)
            elif name == 'summary-spans':
                value = records.read(folder / 'native-verified-lifetimes.json'); value['spans'] = 1
                write('native-verified-lifetimes.json', value)
            elif name == 'witness-hash': altered['raw_otlp_sha256'] = '0' * 64
            elif name == 'witness-type': altered['spans'] = True
            elif name == 'declared-completion':
                value = records.read(folder / 'expected-lifetimes-before-build.json'); value['observations'][0]['complete'] = 1
                write('expected-lifetimes-before-build.json', value)
            try:
                audit.verify(folder, entry, altered, plain=False, function=function)
            except ValueError:
                refused.append(name)
                # Each deliberately corrupt copy is disposable. Unexpected
                # acceptance leaves its copy in place for diagnosis.
                shutil.rmtree(folder)
            else:
                raise AssertionError('native lifetime audit accepted altered evidence: ' + name)
    finally:
        for filename, expected in held.items():
            records.same(records.identity(source / filename, owned=True), expected)
    result = {'refused': refused, 'count': len(refused), 'original_capture_files_preserved': len(held),
              'new_application_launches': 0, 'scope': 'Altered raw/health/summary copies; original SDK records unchanged'}
    (destination / 'refusals.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
