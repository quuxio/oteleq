"""Check C++ object-completion errno transparency against the held genuine SDK."""

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess

BASE = Path(__file__).resolve().parent
INDEX = json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-25/rust-ci-integration/source-6475be4.json').read_text())
ROOT = Path(INDEX['source'])
SDK = ROOT / 'build/correction-sdk'
OUT = BASE / 'sdk-object-errno-6475be4'
OUT.mkdir(mode=0o700)


def facts(path):
    state = path.stat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return [digest, state.st_dev, state.st_ino, state.st_mode, state.st_size,
            state.st_mtime_ns, state.st_ctime_ns]


def snapshot():
    return {'source': {name: facts(ROOT / name) for name in INDEX['files']},
            'products': {name: facts(Path(name)) for name in INDEX['product_facts']}}


before = snapshot()
assert before == {'source': INDEX['original_facts'], 'products': INDEX['product_facts']}
prefix = (ROOT / 'adapters/native/tests/function_runtime_test.cpp').read_text().split(
    'void BalancedScopesErrorsAndApplicationParents() {', 1)[0]
source = OUT / 'object-errno.cpp'
source.write_text(prefix + '''
} // namespace engine_test
#include "otelc/object_runtime.h"
int main() {
  engine_test::World world;
  native::ConfigureObjectMetrics(*world.meters);
  native::ObjectRuntime objects(world.state, world.meters->GetMeter(native::FunctionScopeName),
      world.traces->GetTracer("io.quux.otelc.native"));
  int address = 7;
  if (!objects.Admit(&address, "c:@S@Item", "Item")) return 7;
  auto token = objects.Destroying(&address, "c:@S@Item");
  if (!token) return 8;
  world.span_sink->callback = [] { errno = EOVERFLOW; };
  errno = EINTR;
  bool completed = objects.Destroyed(token, 0);
  int after = errno;
  std::printf("before=%d after=%d exporter=%d completed=%d\\n", EINTR, after, EOVERFLOW, completed);
  world.span_sink->callback = {};
  if (!objects.Close()) return 9;
  return completed && after == EINTR ? 0 : 3;
}
''')
row = next(row for row in json.loads((SDK / 'compile_commands.json').read_text())
           if row['file'].endswith('/object_runtime.cpp'))
original, arguments, index = shlex.split(row['command']), [], 0
while index < len(original):
    if original[index] == '-o':
        index += 2
    elif original[index] == '-c' or original[index] == row['file']:
        index += 1
    else:
        arguments.append(original[index]); index += 1
arguments.extend(['-std=c++17', '-UNDEBUG', str(source), '-L' + str(SDK),
    '-lotelc_native_runtime', str(SDK / '_deps/otelcpp-build/sdk/src/trace/libopentelemetry_trace.a'),
    '-Wl,-rpath,' + str(SDK), '-o', str(OUT / 'object-errno-probe')])
environment = {key: value for key, value in os.environ.items()
               if not key.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'AWS_', 'SONAR_'))}
environment['LLVM_PROFILE_FILE'] = str(OUT / 'native-%m-%p.profraw')
state = {'head': INDEX['head'], 'scope': 'Direct C++ ObjectRuntime completion and callback exporter; '
         'not source-free application or generated-lifetime qualification.', 'commands': []}
try:
    for label, command in [('compile', arguments), ('runtime', [str(OUT / 'object-errno-probe')])]:
        result = subprocess.run(command, cwd=OUT, env=environment, capture_output=True, timeout=120)
        (OUT / (label + '.stdout')).write_bytes(result.stdout)
        (OUT / (label + '.stderr')).write_bytes(result.stderr)
        state['commands'].append({'argv': command, 'exit_code': result.returncode})
        if label == 'compile':
            result.check_returncode()
        else:
            state['errno_mutation_reproduced'] = result.returncode == 3
            state['observation'] = result.stdout.decode()
except Exception as error:
    state['error'] = repr(error)
finally:
    after = snapshot()
    state['preservation'] = {key: before[key] == after[key] for key in before}
    (OUT / 'result.json').write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps(state, indent=2))
