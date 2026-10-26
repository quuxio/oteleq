"""Check completion errno transparency using the held SDK and a callback exporter."""

import hashlib
import json
from pathlib import Path
import shlex
import subprocess

BASE = Path(__file__).resolve().parent
INDEX = json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-25/rust-native-bridge/source-2934455.json').read_text())
ROOT = Path(INDEX['root'])
SDK = ROOT / 'build/rust-sdk'
OUT = BASE / 'sdk-rust-review-2934455/errno'
OUT.mkdir(mode=0o700)


def facts(path):
    state = path.stat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return dict(sha256=digest, dev=state.st_dev, ino=state.st_ino, mode=state.st_mode,
                size=state.st_size, mtime_ns=state.st_mtime_ns, ctime_ns=state.st_ctime_ns)


def snapshot():
    return {'source': {name: facts(ROOT / name) for name in INDEX['files']},
            'products': {name: facts(Path(name)) for name in INDEX['products']}}


before = snapshot()
assert before == {'source': INDEX['files'], 'products': INDEX['products']}
prefix = (ROOT / 'adapters/native/tests/function_runtime_test.cpp').read_text().split(
    'void BalancedScopesErrorsAndApplicationParents() {', 1)[0]
source = OUT / 'errno.cpp'
source.write_text(prefix + '''
} // namespace engine_test
#include <cerrno>
int main() {
  engine_test::World world;
  auto engine = world.Engine();
  auto token = engine->EnterNamed("app.rs::workload");
  if (!token) return 7;
  world.span_sink->callback = [] { errno = EOVERFLOW; };
  errno = EINTR;
  bool completed = engine->Leave(token, 0);
  int after = errno;
  std::printf("before=%d after=%d exporter=%d completed=%d\\n", EINTR, after, EOVERFLOW, completed);
  world.span_sink->callback = {};
  if (!engine->Close()) return 8;
  return completed && after == EINTR ? 0 : 3;
}
''')
row = next(row for row in json.loads((SDK / 'compile_commands.json').read_text())
           if row['file'].endswith('/function_runtime.cpp'))
original = shlex.split(row['command'])
arguments = []
index = 0
while index < len(original):
    if original[index] == '-o':
        index += 2
    elif original[index] == '-c' or original[index] == row['file']:
        index += 1
    else:
        arguments.append(original[index]); index += 1
arguments.extend(['-std=c++17', '-UNDEBUG', str(source), '-L' + str(SDK),
                  '-lotelc_native_runtime', '-Wl,-rpath,' + str(SDK), '-o', str(OUT / 'errno-probe')])
state = {'head': INDEX['head'], 'scope': 'Direct FunctionRuntime completion with a callback exporter; '
         'not compiler-woven application or public Rust workflow qualification.', 'commands': []}
try:
    for label, command in [('compile', arguments), ('runtime', [str(OUT / 'errno-probe')])]:
        result = subprocess.run(command, cwd=OUT, capture_output=True, timeout=120)
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
    state['preservation'] = {key: before[key] == snapshot()[key] for key in before}
    (OUT / 'result.json').write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps(state, indent=2))
