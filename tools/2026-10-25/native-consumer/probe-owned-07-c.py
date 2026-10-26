"""Exercise the independent native consumer through the public SDK and OS gate."""
from datetime import datetime, timezone
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

SOURCE = Path('/Users/sclarke/github/oteleq-qualification/2026-10-25/native-consumer/source-51e5438')
SDK = Path('/Users/sclarke/github/otelc-qualification/work/native-prepared')
INDEX = json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-24/native-prepared/source-4a85c18.json').read_bytes())
sys.path[:0] = [str(SOURCE / 'adapters/generation'), str(SOURCE / 'examples')]
import generation
import native_build
import native_prepared
import native_protocol
import native_sdk
import native_session
import native_toolchain
import otelc_capture as capture
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

ROOT = Path(__file__).resolve().parent / 'owned-probe-07-c'; ROOT.mkdir(mode=0o700)
PROJECT = ROOT / 'application'; PROJECT.mkdir()
APP = r'''#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
__attribute__((noinline)) int workload(int x){return x+7;}
__attribute__((constructor)) static void boot(void){const char*p=getenv("OTELEQ_PROBE_MARKER");if(p){FILE*f=fopen(p,"w");if(f){fputs("constructor\n",f);fclose(f);}}volatile int y=workload(1);(void)y;}
int main(int argc,char**argv){char text[128]={0};if(!fgets(text,sizeof(text),stdin))return 4;
if(argc!=4||strcmp(argv[1],"literal space")||strcmp(argv[2],"--literal")||strcmp(argv[3],"$literal")||strcmp(text,"input $data\n"))return 5;
printf("%ld|%s|%s|%s|%d|%s",(long)getpid(),argv[1],argv[2],argv[3],workload(10),text);return 0;}
'''
(PROJECT / 'main.c').write_text(APP)
POLICY = {'schema_version': 3, 'languages': ['c'], 'resource': {'service_name': 'oteleq-native-owned-probe'},
 'export': {'endpoint': 'http://127.0.0.1:1', 'interval_ms': 1000, 'timeout_ms': 1000, 'shutdown_timeout_ms': 5000},
 'sources': {'include': ['main.c'], 'exclude': []}, 'functions': {'include': ['workload'], 'exclude': []},
 'metrics': {'collection': True, 'emission': True, 'histogram_boundaries_seconds': [1e-6, 1e-5, .0001, .001, .01, .1, 1.]},
 'traces': {'enabled': True, 'sample_ratio': 1.0},
 'lifetimes': {'enabled': False, 'include': [], 'exclude': [], 'max_live': 4096, 'release_methods': ['close']},
 'context': {'tasks': False, 'http': False}, 'benchmark': {'iterations': 10000, 'samples': 15, 'warmup': 5}}


def config(path, data):
    lines = ['schema_version=3', 'languages=["cpp"]']
    for name, values in data.items():
        if type(values) is dict:
            lines += ['[' + name + ']', *[key + '=' + json.dumps(value) for key, value in values.items()]]
    path.write_text('\n'.join(lines) + '\n')


def facts(path):
    info = path.stat()
    return [hashlib.sha256(path.read_bytes()).hexdigest(), info.st_dev, info.st_ino, info.st_mode,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns]


consumer_index = json.loads((Path(__file__).resolve().parent / 'source-51e5438.json').read_bytes())
consumer = sorted(consumer_index['files'])


def inputs():
    return {'sdk': {name: facts(SDK / name) for name in INDEX['files']},
            'consumer': {name: facts(SOURCE / name) for name in consumer},
            'application': {'main.c': facts(PROJECT / 'main.c')}}


def write(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2) + '\n')


def execute(argv, cwd):
    return subprocess.run(list(map(str, argv)), cwd=cwd, capture_output=True, timeout=30)


def decode(bodies):
    spans, counts, metric_points = [], {}, 0
    for route, raw in bodies:
        if route == '/v1/traces':
            message = ExportTraceServiceRequest.FromString(raw)
            for resource in message.resource_spans:
                assert any(row.key == 'service.name' and row.value.string_value == POLICY['resource']['service_name'] for row in resource.resource.attributes)
                for scope in resource.scope_spans:
                    assert scope.scope.name == 'io.quux.otelc.native'
                    spans.extend(scope.spans)
        elif route == '/v1/metrics':
            message = ExportMetricsServiceRequest.FromString(raw)
            for resource in message.resource_metrics:
                for scope in resource.scope_metrics:
                    assert scope.scope.name == 'io.quux.otelc.native'
                    for metric in scope.metrics:
                        assert metric.name in ('otelc.function.calls', 'otelc.function.duration')
                        kind = metric.WhichOneof('data')
                        for point in getattr(metric, kind).data_points:
                            metric_points += 1
                            labels = {row.key: row.value.string_value for row in point.attributes}
                            assert labels['function'] == 'main.c::workload'
                            number = point.count if kind == 'histogram' else point.as_int
                            counts[metric.name] = max(number, counts.get(metric.name, 0))
        else:
            raise AssertionError('foreign OTLP route')
    assert len(spans) == 2 and len({(span.trace_id, span.span_id) for span in spans}) == 2
    assert all(span.name == 'main.c::workload' and not span.parent_span_id
               and any(span.trace_id) and any(span.span_id)
               and 0 < span.start_time_unix_nano <= span.end_time_unix_nano for span in spans)
    assert counts == {'otelc.function.calls': 2, 'otelc.function.duration': 2}
    return {'spans': len(spans), 'metric_counts': counts, 'metric_points': metric_points}


before = inputs(); write('inputs-before.json', before)
assert all(before['sdk'][name][0] == sha for name, sha in INDEX['files'].items())
assert all(before['consumer'][name][0] == sha for name, sha in consumer_index['files'].items())
state = {'status': 'running', 'dirty_development_snapshot': False, 'consumer_head': consumer_index['head'], 'sdk_head': INDEX['head'],
         'started': datetime.now(timezone.utc).isoformat(), 'applications': []}
write('status.json', state); started = time.monotonic()
environment = {key: value for key, value in os.environ.items() if not key.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'SONAR_', 'AWS_'))}
llvm = Path('/opt/homebrew/opt/llvm@22/bin/llvm-config')
environment.update(LLVM_CONFIG=str(llvm), PYTHONDONTWRITEBYTECODE='1')
try:
    descriptor = [sys.executable, '-I', '-S', '-B', str(SDK / 'otelc/cli_bootstrap.py'), 'native-protocols']
    result = subprocess.run(descriptor, cwd=ROOT, env=environment, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    native_protocol.verify_protocols(json.loads(result.stdout)); write('protocols.json', json.loads(result.stdout))
    tools = native_toolchain.capture(llvm, llvm.parent / 'clang', 'c', ROOT, execute)
    sdk = native_sdk.capture(SDK, SDK / 'build/prepared-sdk', tools,
                            cmake=Path('/opt/homebrew/bin/cmake'), ninja=Path('/opt/homebrew/bin/ninja'))
    intent = native_build.freeze(sdk, PROJECT, ROOT / 'build', 'c', ('main.c',), ((PROJECT / 'main.c',),), POLICY)
    build_config = ROOT / 'build.toml'; config(build_config, POLICY)
    command = [sys.executable, '-I', '-S', '-B', str(SDK / 'otelc/cli_bootstrap.py'), '--config', str(build_config),
        'native-build', '--language', 'c', '--root', str(PROJECT), '--source', 'main.c',
        '--output', str(intent.output), '--sdk-build', str(sdk.directory)]
    write('build-command.json', command)
    result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, timeout=300)
    (ROOT / 'build.stdout').write_bytes(result.stdout); (ROOT / 'build.stderr').write_bytes(result.stderr)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    built = native_build.read(intent)
    for plain in (True, False):
        label = 'plain' if plain else 'woven'
        marker = ROOT / (label + '.constructor')
        with capture.receiver() as (endpoint, bodies, errors):
            data = copy.deepcopy(POLICY); data['export']['endpoint'] = endpoint
            policy_file = ROOT / (label + '.toml'); config(policy_file, data)
            runtime = ROOT / ('runtime-' + label)
            expected = native_prepared.freeze(built, runtime, Path(sys.executable).absolute(), policy_file,
                data, plain=plain, arguments=('literal space', '--literal', '$literal'))
            argv = [sys.executable, '-I', '-S', '-B', str(SDK / 'otelc/cli_bootstrap.py'), '--config', str(policy_file),
                    'native-run', '--build', str(built.intent.output), '--runtime', str(runtime), '--prepare-only']
            if plain: argv.append('--plain')
            argv += ['--', *expected.arguments]
            result = subprocess.run(argv, cwd=ROOT, env=environment, capture_output=True, timeout=30)
            assert result.returncode == 0, result.stderr.decode(errors='replace')
            launch = native_prepared.read(expected)
            controller = native_session.Session(launch)
            # Add a read-only observation before the unchanged production poll.
            original_poll = controller.poll
            def observed_poll(process, deadline):
                if controller.started is None:
                    assert not marker.exists(), 'constructor executed before host ownership binding'
                return original_poll(process, deadline)
            controller.poll = observed_poll
            with native_session.retained(controller):
                result = generation.execute(native_prepared.command(expected), ROOT,
                    env={**environment, 'OTELEQ_PROBE_MARKER': str(marker), 'PATH': '/no-tools'},
                    folder=ROOT / ('execution-' + label), timeout=30, input_data=b'input $data\n',
                    record_process=True, interaction=controller)
            assert result.returncode == 0 and result.stderr == b''
            expected_output = (str(controller.child) + '|literal space|--literal|$literal|17|input $data\n').encode()
            assert result.stdout == expected_output and marker.read_bytes() == b'constructor\n'
            assert errors == []
            capture.retain_http(ROOT / ('execution-' + label), bodies, errors)
            observation = None
            if plain:
                assert bodies == [] and controller.execution.health is None
            else:
                observation = decode(bodies)
                raw = controller.execution.health.value()
                assert raw['function_accounting']['started'] == '2'
                assert int(raw['trace_exports']['batches_succeeded']) == sum(route == '/v1/traces' for route, _ in bodies)
                assert int(raw['metric_exports']['units_succeeded']) == observation['metric_points']
                assert int(raw['trace_exports']['units_succeeded']) == observation['spans']
            controller.execution.verify()
            state['applications'].append({'plain': plain, 'pid': controller.child,
                'before_constructor_os_binding': True, 'literal_arguments_and_streams': True,
                'supervisor_pid': controller.started.owner.pid, 'otlp': observation})
    state.update(status='passed', actual_application_launches=2, retained_build_files=len(built.files))
except Exception as error:
    import traceback
    traceback.print_exc()
    state.update(status='failed', error=repr(error))
finally:
    after = inputs(); write('inputs-after.json', after)
    state['preservation'] = {name: before[name] == after[name] for name in before}
    if not all(state['preservation'].values()): state['status'] = 'failed'
    state.update(seconds=round(time.monotonic() - started, 3), finished=datetime.now(timezone.utc).isoformat())
    write('status.json', state); print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed' else 1)
