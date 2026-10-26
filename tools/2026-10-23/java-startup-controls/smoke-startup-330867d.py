"""Bounded real-JVM startup experiment; retained-route qualification is separate."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source-330867d'
PROVIDER = Path('/Users/sclarke/github/oteleq-qualification/2026-10-21/java-safe-sdk-e4aaafa/provider')
CLI = ROOT / 'quux-oteleq-330867d'
sys.path.insert(0, str(SOURCE / 'tests'))
from qualify_java_controls import SOURCE as FIXTURE, observation
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

STATES = ({'collection': True, 'emission': True}, {'collection': False, 'emission': True},
          {'collection': True, 'emission': False}, {'collection': False, 'emission': False})
NAMES = ('both-on', 'collection-off', 'emission-off', 'both-off')


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(arguments, folder, name):
    marker = folder / (name + '.started.json')
    if marker.exists():
        assert read(marker) == list(map(str, arguments))
        assert (folder / (name + '.exit')).read_text() == '0\n', 'Incomplete or failed prior operation'
        assert (folder / (name + '.stderr')).is_file()
        return (folder / (name + '.stdout')).read_text().strip()
    marker.write_text(json.dumps(list(map(str, arguments))) + '\n')
    result = subprocess.run(list(map(str, arguments)), capture_output=True, timeout=180)
    (folder / (name + '.stdout')).write_bytes(result.stdout)
    (folder / (name + '.stderr')).write_bytes(result.stderr)
    (folder / (name + '.exit')).write_text(str(result.returncode) + '\n')
    assert result.returncode == 0, (name, result.returncode, result.stderr[-2000:])
    return result.stdout.decode().strip()


def main():
    output = ROOT / 'startup-smoke-safe-e4aaafa-330867d'
    output.mkdir(mode=0o700, exist_ok=True)
    source_index = read(ROOT / 'source-330867d.json')
    assert digest(CLI) == '68c8c923e8bdfb84f885af82dd0a00b2067c9dfaa71763270d866775d3770c26'
    provider_index = {str(path.relative_to(PROVIDER)): digest(path)
        for path in sorted(PROVIDER.rglob('*')) if path.is_file()}
    initial = read(PROVIDER.parent / 'source-identity.json')
    assert initial['revision'] == 'e4aaafaeb617db335146cc22be2f6dd5b8be68cd'
    assert all(provider_index[name] == value for name, value in initial['files'].items())
    before = output / 'provider-before.json'
    if before.exists():
        assert read(before) == provider_index
    else:
        before.write_text(json.dumps(provider_index, indent=2) + '\n')
    fixture = FIXTURE.replace('Counter identity(int amount){',
        'Counter identity(int amount){System.out.write(new byte[]{0,-1,10},0,3);System.err.write(new byte[]{1,-1,10},0,3);')
    assert fixture != FIXTURE
    identities, rows = set(), []
    for offset, name in enumerate(NAMES):
        states = STATES[offset:] + STATES[:offset]
        folder = output / name;folder.mkdir(exist_ok=True)
        app = folder / 'application';app.mkdir(exist_ok=True)
        if (app / 'Counter.java').exists():
            assert (app / 'Counter.java').read_text() == fixture
        else:
            (app / 'Counter.java').write_text(fixture)
        text = 'schema_version=1\nlanguages=["java"]\n[adapters.java]\nbackend="prepared"\nprofile="safe-methods-v1"\n'
        text += '[functions]\ninclude=["Counter.identity(int)"]\n[limits]\ncase_timeout_ms=60000\n'
        text += '[[fixtures]]\nfunction="Counter.identity(int)"\ncases=[[7]]\nreceiver={factory="Counter",arguments=[10]}\nsequence=[\n'
        for index, state in enumerate(states):
            arguments = '"case"' if index == 0 else '[' + str(index + 1) + ']'
            text += '{action="call",arguments=' + arguments + ',metrics={collection=' + str(state['collection']).lower() + ',emission=' + str(state['emission']).lower() + '}},\n'
        text += ']\n'
        config = folder / 'equivalence.toml'
        if config.exists():
            assert config.read_text() == text
        else:
            config.write_text(text)
        workspace = Path(run([CLI, 'plan', '--source', app, '--otelc-root', PROVIDER,
            '--workspace-parent', folder, '--config', config], folder, 'plan'))
        run([CLI, 'generate', '--workspace', workspace], folder, 'generate')
        comparison = folder / 'comparison'
        run([CLI, 'run', '--workspace', workspace, '--report-dir', comparison], folder, 'run')
        report = read(comparison / 'report.json')
        assert report['exit_code'] == 0 and not report['blocked'] and report['source_preserved']
        assert len(report['cases']) == 1
        case = report['cases'][0]
        assert case['function'] == 'Counter.identity(int)' and case['exit_code'] == 0
        for lane in ('baseline', 'instrumented_on'):
            for repeat in range(2):
                attempt = comparison / case['case'] / (lane + '-' + str(repeat))
                observation(read(attempt / 'typed-observation.json'), 'identity', 7, lane == 'instrumented_on')
                assert (attempt / 'stdout').read_bytes() == bytes.fromhex('00ff0a') * 4
                assert (attempt / 'stderr').read_bytes() == bytes.fromhex('01ff0a') * 4
                process, control = read(attempt / 'process.json'), read(attempt / 'java-controls.json')
                assert control['pid'] == process['pid'] and len(control['steps']) == 4
                identity = (str(attempt), process['pid'])
                assert identity not in identities;identities.add(identity)
                if lane == 'baseline':
                    assert control['plain'] is True
                    continue
                assert control['plain'] is False
                actual = control['steps'][0]['before']['history'][0]['status']
                assert all(actual[key] == value for key, value in states[0].items())
                health = read(attempt / 'sdk-runtime/health.json')
                assert health['pid'] == process['pid'] and health['phase'] == 'final' and health['sdk_attached']
                assert health['lifecycle'] == {'flush': 'succeeded', 'shutdown': 'succeeded'}
                capture = read(attempt / 'http-capture.json');assert not capture['errors']
                spans, final = [], {}
                for body in capture['bodies']:
                    raw = (attempt / body['file']).read_bytes()
                    if body['path'] == '/v1/traces':
                        message = ExportTraceServiceRequest.FromString(raw)
                        spans.extend(span for resource in message.resource_spans for scope in resource.scope_spans for span in scope.spans)
                    else:
                        assert body['path'] == '/v1/metrics'
                        message = ExportMetricsServiceRequest.FromString(raw)
                        for resource in message.resource_metrics:
                            for scope in resource.scope_metrics:
                                for metric in scope.metrics:
                                    if metric.name not in ('otelc.function.calls', 'otelc.function.duration'):
                                        continue
                                    points = metric.sum.data_points if metric.name.endswith('calls') else metric.histogram.data_points
                                    for point in points:
                                        value = point.as_int if metric.name.endswith('calls') else point.count
                                        if metric.name not in final or point.time_unix_nano > final[metric.name][0]:
                                            final[metric.name] = (point.time_unix_nano, value)
                assert len(spans) == 4 and all(span.name == 'Counter.identity' and not span.parent_span_id for span in spans)
                assert {key: value[1] for key, value in final.items()} == {'otelc.function.calls': 2, 'otelc.function.duration': 2}
                for step, state in zip(control['steps'], states):
                    assert step['requested'] == state
                    if not state['emission']:
                        assert step['after']['held_ns'] >= 1000000000 and not step['after']['metric_bodies']
                restored = control['restored']['flush']
                assert restored['collection'] and restored['emission'] and restored['completed'] == 2
        assert (app / 'Counter.java').read_text() == fixture
        rows.append({'initial_state': name, 'actual_applications': 4, 'report': str(comparison / 'report.json')})
        (output / 'progress.json').write_text(json.dumps(rows, indent=2) + '\n')
    assert len(identities) == 16
    assert all(digest(PROVIDER / name) == value for name, value in provider_index.items())
    assert all(digest(SOURCE / name) == value for name, value in source_index['files'].items())
    result = {'executor_commit': source_index['commit'], 'provider_commit': initial['revision'],
        'actual_applications': len(identities), 'initial_states': rows,
        'provider_files_preserved': len(provider_index), 'consumer_sources_preserved': len(source_index['files']),
        'scope': 'Development smoke of one private receiver method on JDK21 safe-methods-v1, all four initial states; no retained-route, whole-profile or shipping admission.'}
    (output / 'SMOKE.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    os.environ['OTELEQ_PYTHON'] = sys.executable
    os.environ['OTELEQ_CLI'] = str(CLI)
    main()
