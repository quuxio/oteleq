"""Exercise the development native generator API against the held build3 SDK."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

BASE = Path(__file__).resolve().parent
SOURCE = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-native-generated')
SDK = Path('/Users/sclarke/github/otelc-qualification/work/native-build-context')
INDEX = json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-25/native-build-context/source-5476ce0.json').read_text())
ROOT = BASE / 'probe-development-06'; ROOT.mkdir(mode=0o700)
sys.path[:0] = [str(SOURCE / 'adapters/generation'), str(SOURCE / 'examples')]
import generation


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def facts(path):
    info = path.stat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return [digest, info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_nlink]


def command(folder, phase, argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        status = generation.main(argv)
    (folder / (phase + '.stdout')).write_text(out.getvalue())
    (folder / (phase + '.stderr')).write_text(err.getvalue())
    write(folder / (phase + '.command.json'), argv)
    assert status == 0, phase + ' refused; inspect retained output'
    return out.getvalue()


names = subprocess.check_output(['git', 'ls-files'], cwd=SOURCE, text=True).splitlines()
names += ['adapters/generation/native_source.py', 'adapters/generation/native_source_run.py',
          'tests/test_generation_native_source.py', 'tests/test_generation_native_source_run.py']
paths = [SOURCE / name for name in sorted(set(names))]
paths += [SDK / name for name in INDEX['files']]
paths += [SDK / 'build/context-sdk/native-sdk-build.json', SDK / 'build/context-sdk/libotelc_native_runtime.dylib']
before = {str(path): facts(path) for path in paths}; write(ROOT / 'inputs-before.json', before)
assert all(before[str(SDK / name)][0] == digest for name, digest in INDEX['files'].items())
os.environ.update(PYTHONDONTWRITEBYTECODE='1', OTELEQ_PYTHON=sys.executable,
    OTELEQ_EXECUTABLE='/Users/sclarke/github/oteleq-qualification/2026-10-25/go-path-boundaries/full-gate-cb08b82/target/debug/quux-oteleq',
    LLVM_CONFIG='/opt/homebrew/opt/llvm@22/bin/llvm-config',
    OTELC_CLANG='/opt/homebrew/opt/llvm@22/bin/clang', OTELC_CLANGXX='/opt/homebrew/opt/llvm@22/bin/clang++')
state = {'status': 'running', 'started': datetime.now(timezone.utc).isoformat(), 'cases': [],
         'consumer_base': '64c42baa435ec190b9eac34f05f3228ec16e3ebc', 'dirty_development_snapshot': True,
         'sdk_head': INDEX['head'], 'scope': 'Development generator API smoke only; public Rust distribution and retained workflows require separate exact-revision qualification.'}
write(ROOT / 'status.json', state); started = time.monotonic()
try:
    for language in ('cpp',):
        for project in (False, True):
            label = language + ('-project' if project else '-standalone')
            folder = ROOT / label; folder.mkdir()
            source = folder / 'application'; source.mkdir()
            suffix = 'cpp' if language == 'cpp' else 'c'
            name = ('src/one.' if project else 'one.') + suffix
            target = source / name; target.parent.mkdir(exist_ok=True)
            body = ('#include <stdexcept>\nnamespace work { int total=7; static int own=3; int selected(short x) { total+=x; own+=x; throw std::runtime_error("original failure"); } }\n'
                    'int main(){return work::selected(0);}\n' if language == 'cpp' else
                    'int total=7; static int own=3; int selected(short x) { total+=x; own+=x; return total+own; }\n'
                    'int main(void){return selected(0);}\n')
            target.write_text(body)
            function = 'work::selected(short)' if language == 'cpp' else 'selected'
            config = folder / 'generation.toml'
            text = 'schema_version=1\nlanguages=' + json.dumps([language]) + '\n[functions]\ninclude=' + json.dumps([function])
            text += '\n[limits]\nbaseline_repeats=2\ninstrumented_repeats=2\ncase_timeout_ms=30000\n'
            text += '\n[[fixtures]]\nfunction=' + json.dumps(function) + '\nlanguage=' + json.dumps(language) + '\ncases=[[5]]\n'
            if language == 'cpp':
                text += 'expected_baseline={kind="error",category="exception",type="cpp.std::runtime_error"}\n'
            text += '\n[adapters.' + language + ']\nbackend="prepared"\nsdk_build=' + json.dumps(str(SDK / 'build/context-sdk')) + '\n'
            if project:
                database = source / 'build/compile_commands.json'; database.parent.mkdir()
                compiler = os.environ['OTELC_CLANGXX' if language == 'cpp' else 'OTELC_CLANG']
                write(database, [{'directory': str(target.parent), 'file': target.name,
                    'arguments': [compiler, '-std=c++17' if language == 'cpp' else '-std=c11', '-O0', '-c', target.name, '-o', '../build/one.o']}])
                text += 'compilation_database="build/compile_commands.json"\n'
                text += '[[adapters.' + language + '.targets]]\nname="application"\nunits=[{source=' + json.dumps(name) + '}]\n'
            config.write_text(text)
            original = {str(path): facts(path) for path in source.rglob('*') if path.is_file()}
            planned = command(folder, 'plan', ['plan', '--source', str(source), '--otelc-root', str(SDK),
                '--config', str(config), '--workspace-parent', str(folder), '--cases', '1'])
            workspace = Path(planned.strip())
            command(folder, 'generate', ['generate', '--workspace', str(workspace)])
            result = json.loads(command(folder, 'run', ['run', '--workspace', str(workspace), '--report-dir', str(folder / 'report')]))
            assert {str(path): facts(path) for path in source.rglob('*') if path.is_file()} == original
            state['cases'].append({'profile': label, 'workspace': str(workspace), 'result': result, 'source_unchanged': True})
            write(ROOT / 'status.json', state)
    state['status'] = 'passed'
except Exception as error:
    traceback.print_exc(); state.update(status='failed', error=repr(error))
finally:
    after = {str(path): facts(path) for path in paths}; write(ROOT / 'inputs-after.json', after)
    state['consumer_sdk_inputs_held'] = before == after
    if before != after:
        state['status'] = 'failed'
    state.update(seconds=round(time.monotonic() - started, 3), finished=datetime.now(timezone.utc).isoformat())
    write(ROOT / 'status.json', state); print(json.dumps(state, indent=2), flush=True)
    raise SystemExit(0 if state['status'] == 'passed' else 1)
