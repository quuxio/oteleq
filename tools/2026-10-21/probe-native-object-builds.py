"""Check actual SDK compile-only and separate link commands before wiring project builds."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-cpp-receivers')
sys.path[:0] = [str(REPO / 'examples'), str(REPO / 'adapters/generation')]
import otelc_capture as capture
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

PROVIDER = Path('/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/provider')
OUTPUT = Path('/Users/sclarke/github/oteleq-qualification/2026-10-21/native-object-builds')
OUTPUT.mkdir(exist_ok=False)


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def execute(command, directory, env, folder):
    folder.mkdir()
    write(folder / 'command.json', list(map(str, command)))
    result = subprocess.run(command, cwd=directory, env=env, capture_output=True, timeout=120, check=False)
    (folder / 'stdout').write_bytes(result.stdout)
    (folder / 'stderr').write_bytes(result.stderr)
    if result.returncode:
        raise ValueError('command failed; inspect ' + str(folder))
    return result


records = []
for language, suffix, compiler_name in (('c', 'c', 'clang'), ('cpp', 'cpp', 'clang++')):
    root = OUTPUT / language
    root.mkdir()
    source = root / 'original'
    source.mkdir()
    (source / 'include').mkdir()
    (source / 'include/config.h').write_text('#define OFFSET 3\n')
    (source / ('selected.' + suffix)).write_text('#include "config.h"\nint sibling(int);'
        'int selected(int value){return sibling(value)+OFFSET;}\n')
    (source / ('sibling.' + suffix)).write_text('static int state=7;'
        'int sibling(int value){state+=value;return state;}int current(void){return state;}\n')
    (source / ('caller.' + suffix)).write_text('#include <stdio.h>\nint current(void);int selected(int);'
        'int main(void){int before=current();int value=selected(5);int after=current();'
        'printf("%d:%d:%d\\n",before,value,after);return 0;}\n')
    original = {str(path.relative_to(source)): capture.file_digest(path) for path in source.rglob('*') if path.is_file()}
    tools = capture.selected_tools(PROVIDER, language)
    provider_identity = capture.artefacts(PROVIDER, language, tools)
    write(root / 'provider-inputs.json', provider_identity)
    results = {}
    with capture.receiver() as (endpoint, bodies, errors):
        policy = root / 'policy.toml'
        policy.write_text('schema_version=2\nlanguages=[' + json.dumps(language) + ']\n'
            '[sources]\ninclude=["**"]\n[functions]\ninclude=["selected"'+('' if language == 'c' else ',"selected(int)"')+']\n'
            '[traces]\nenabled=true\nroot_sample_ratio=1.0\n'
            '[export]\nendpoint=' + json.dumps(endpoint) + '\ninterval_ms=50\n')
        prefix = [PROVIDER / capture.OTELC_CLI_PATH, '--config', policy, '--language', language]
        for lane in ('baseline', 'instrumented_on'):
            folder = root / lane
            folder.mkdir()
            project = folder / 'project'
            shutil.copytree(source, project)
            env = capture.environment(project, tools, 'oteleq-object-probe-' + language, PROVIDER)
            env['OTELC_REPORT_PATH'] = str(folder / 'runtime.json')
            objects = []
            for name in ('selected', 'sibling', 'caller'):
                output = folder / (name + '.o')
                flags = ['-std=c11' if language == 'c' else '-std=c++17', '-O0', '-I', 'include',
                         '-c', project / (name + '.' + suffix), '-o', output]
                command = [tools[compiler_name], *flags] if lane == 'baseline' else prefix + [compiler_name, *flags]
                execute(command, project, env, folder / ('compile-' + name))
                objects.append(output)
            binary = folder / 'application'
            link = [*objects, '-o', binary]
            command = [tools[compiler_name], *link] if lane == 'baseline' else prefix + [compiler_name, *link]
            execute(command, project, env, folder / 'link')
            command = [binary] if lane == 'baseline' else prefix + ['run', binary]
            result = execute(command, project, env, folder / 'launch')
            if result.stdout != b'7:15:12\n' or result.stderr:
                raise ValueError('independent output oracle failed: ' + language + '/' + lane)
            if lane == 'baseline' and bodies:
                raise ValueError('baseline emitted telemetry')
            if {str(path.relative_to(project)): capture.file_digest(path) for path in project.rglob('*') if path.is_file()} != original:
                raise ValueError('private source changed')
            results[lane] = {'application_sha256': capture.file_digest(binary),
                             'objects': {path.name: capture.file_digest(path) for path in objects},
                             'stdout': result.stdout.decode(), 'stderr': result.stderr.decode()}
    capture.retain_http(root, bodies, errors)
    if errors:
        raise ValueError('receiver failure')
    names, _, trees, exceptions = capture.decode(bodies, 'oteleq-object-probe-' + language, ExportTraceServiceRequest)
    if sum(names.values()) != 1 or trees != 1 or exceptions:
        raise ValueError('incorrect selected target witness: ' + repr(names))
    runtime = capture.strict_json((root / 'instrumented_on/runtime.json').read_text())
    witness = capture.witness(bodies, runtime, {'functions': names, 'trees': 1, 'errors': 0},
                              'oteleq-object-probe-' + language, ExportTraceServiceRequest, language)
    capture.stable(PROVIDER, language, tools, provider_identity)
    if {str(path.relative_to(source)): capture.file_digest(path) for path in source.rglob('*') if path.is_file()} != original:
        raise ValueError('original source changed')
    record = {'language': language, 'source_manifest': original, 'lanes': results, 'witness': witness,
              'scope': 'compile/link recipe probe; not generated project-workflow or shipping qualification'}
    write(root / 'result.json', record)
    records.append(record)
write(OUTPUT / 'results.json', records)
print('C and C++: separate compile/link, independent value/state oracle and actual telemetry witness passed')
