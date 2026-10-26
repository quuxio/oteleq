"""Actual provider probe for the new private native target-worker recipes."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

SOURCE = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-cpp-receivers')
sys.path[:0] = [str(SOURCE / 'tests'), str(SOURCE / 'adapters/generation'), str(SOURCE / 'examples')]
from test_generation_native_workers import NativeWorkersTests
import native_project
import native_workers
import otelc_capture as capture
import typed_capture
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

PROVIDER = Path('/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/provider')
OUTPUT = Path(sys.argv[1]).resolve()
OUTPUT.mkdir(exist_ok=False)


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def execute(command, directory, env, folder):
    folder.mkdir()
    write(folder / 'command.json', list(map(str, command)))
    (folder / 'directory').write_text(str(directory) + '\n')
    result = subprocess.run(command, cwd=directory, env=env, capture_output=True, timeout=120, check=False)
    (folder / 'stdout').write_bytes(result.stdout)
    (folder / 'stderr').write_bytes(result.stderr)
    write(folder / 'exit.json', result.returncode)
    if result.returncode:
        raise ValueError('command failed: ' + str(folder))
    return result


results = []
for language in ('c', 'cpp'):
    case = NativeWorkersTests()
    case.base = OUTPUT / language
    case.root = case.base / 'original'
    for name in ('src', 'include', 'build'):
        (case.root / name).mkdir(parents=True)
    prepared, entry, _ = case.prepare(language)
    write(case.base / 'prepared.json', prepared)
    write(case.base / 'entry.json', entry)
    tools = capture.selected_tools(PROVIDER, language)
    provider_identity = capture.artefacts(PROVIDER, language, tools)
    write(case.base / 'provider-inputs.json', provider_identity)
    service = 'oteleq-target-worker-' + language
    expected_name = 'work::selected(short)' if language == 'cpp' else 'selected'
    lanes = {}
    with capture.receiver() as (endpoint, bodies, errors):
        policy = case.base / 'otelc.toml'
        policy.write_text('schema_version=2\nlanguages=[' + json.dumps(language) + ']\n'
            '[sources]\ninclude=["**"]\n[functions]\ninclude=[' + json.dumps(expected_name) + ']\n'
            '[traces]\nenabled=true\nroot_sample_ratio=1.0\n[export]\nendpoint=' + json.dumps(endpoint) + '\ninterval_ms=50\n')
        prefix = [str(PROVIDER / capture.OTELC_CLI_PATH), '--config', str(policy), '--language', language]
        for lane in ('baseline', 'instrumented_on'):
            folder = case.base / lane
            folder.mkdir()
            project = folder / 'project'
            shutil.copytree(case.root, project)
            case.project = project
            recipe = native_workers.materialise(project, prepared, entry, [5], folder / 'helpers')
            write(folder / 'recipe.json', recipe)
            env = capture.environment(project, tools, service, PROVIDER)
            env['OTELC_REPORT_PATH'] = str(folder / 'runtime.json')
            env['OTELEQ_OBSERVATION'] = str(folder / 'observation')
            outputs = {}
            for index, step in enumerate(recipe['steps']):
                command = step['command']
                if lane == 'instrumented_on' and step['kind'] in ('compile', 'driver', 'link'):
                    command = prefix + ['clang++' if language == 'cpp' else 'clang', *command[1:]]
                execute(command, step['directory'], env, folder / (str(index) + '-' + step['kind']))
                outputs[step['output']] = capture.file_digest(Path(step['output']))
            command = [recipe['binary']] if lane == 'baseline' else prefix + ['run', recipe['binary']]
            result = execute(command, project, env, folder / 'launch')
            if result.stdout or result.stderr:
                raise ValueError('unexpected application channels')
            before, outcome, after = typed_capture.scalar_capture((folder / 'observation').read_bytes(), entry)
            case.assert_roots(before, 3, 4, 7)
            case.assert_roots(after, 8, 9, 12)
            if outcome['graph']['roots']['result']['value'] != '20':
                raise ValueError('independent return oracle failed')
            if lane == 'baseline' and bodies:
                raise ValueError('baseline emitted telemetry')
            for root in (project, case.root):
                for name, expected in prepared['local_inputs'].items():
                    if capture.file_digest(root / name) != expected:
                        raise ValueError('source changed')
            if {name: capture.file_digest(Path(name)) for name in recipe['assets']} != recipe['assets']:
                raise ValueError('helper changed')
            lanes[lane] = {'before': before, 'outcome': outcome, 'after': after, 'outputs': outputs}
    capture.retain_http(case.base, bodies, errors)
    if errors:
        raise ValueError('receiver failed')
    names, _, trees, exceptions = capture.decode(bodies, service, ExportTraceServiceRequest)
    if dict(names) != {expected_name: 1} or trees != 1 or exceptions:
        raise ValueError('incorrect target witness: ' + repr(names))
    witness = capture.witness(bodies, capture.strict_json((case.base / 'instrumented_on/runtime.json').read_text()),
        {'functions': names, 'trees': 1, 'errors': 0}, service, ExportTraceServiceRequest, language)
    capture.stable(PROVIDER, language, tools, provider_identity)
    record = {'language': language, 'lanes': lanes, 'witness': witness,
              'scope': 'private native target-worker recipe probe; public plan/replay/export are not yet integrated'}
    write(case.base / 'result.json', record)
    results.append(record)
write(OUTPUT / 'results.json', results)
print('C and C++ target workers: independent full scalar state/result, source preservation and exact actual-provider witness passed')
