"""Exercise the private lifetime caller frontend with genuine held SDK inputs."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

ROOT = Path('/Users/sclarke/github/oteleq-qualification')
REPO = ROOT / 'work/oteleq-native-lifetime-caller'
SDK_ROOT = Path('/Users/sclarke/github/otelc-qualification/work/rust-ci-integration')
OUT = ROOT / '2026-10-25/native-lifetime-build/caller-genuine-development-03'
OUT.mkdir(exist_ok=False)
(OUT / 'controller.py').write_bytes(Path(__file__).read_bytes())
sys.path[:0] = [str(REPO / 'adapters/generation'), str(REPO / 'examples')]
import native_context
import native_lifetime_caller
import native_lifetime_inventory
import native_project
import native_sdk
import native_toolchain
import native_unit_caller

ENV = {name: value for name, value in os.environ.items()
       if not name.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'AWS_', 'SONAR_'))}
ENV.update(PYTHONDONTWRITEBYTECODE='1', OTELC_LLVM_CONFIG='/opt/homebrew/opt/llvm@22/bin/llvm-config')
STATE = {'status': 'running', 'started': datetime.now(timezone.utc).isoformat(), 'commands': [],
    'scope': 'Uncommitted private caller component. Genuine SDK6475be4 inputs and actual LLVM22 '
             'frontend/VFS/semantic queries. No SDK source build or application launch; '
             'public generated, retained and shipping qualification remains open.',
    'application_launches': 0, 'sdk_builds': 0, 'cases': {}}


def write():
    (OUT / 'result.json').write_text(json.dumps(STATE, indent=2) + '\n')


def execute(argv, directory, **kwargs):
    words = list(map(str, argv))
    index = len(STATE['commands'])
    with (OUT / f'{index}.stdout').open('xb') as stdout, (OUT / f'{index}.stderr').open('xb') as stderr:
        result = subprocess.run(words, cwd=directory, env=ENV, stdout=stdout, stderr=stderr,
                                timeout=240, input=kwargs.get('input_data'))
    STATE['commands'].append({'argv': words, 'directory': str(directory), 'returncode': result.returncode})
    write()
    out, err = OUT / f'{index}.stdout', OUT / f'{index}.stderr'
    assert out.stat().st_size <= 64 * 1024**2 and err.stat().st_size <= 16 * 1024**2
    return subprocess.CompletedProcess(words, result.returncode, out.read_bytes(), err.read_bytes())


def fact(path):
    value = path.lstat()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return [digest, value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns]


def snapshot():
    result = {}
    for label, directory in (('consumer', REPO), ('provider', SDK_ROOT)):
        names = subprocess.check_output(['git', 'ls-files', '--cached', '--others',
                                         '--exclude-standard', '-z'], cwd=directory).decode().rstrip('\0').split('\0')
        result[label] = {name: fact(directory / name) for name in names}
    result['products'] = {name: fact(SDK_ROOT / 'build/correction-sdk' / name)
                          for name in ('native-sdk-build.json', 'libotelc_native_runtime.dylib')}
    return result


started = time.monotonic()
before = snapshot()
(OUT / 'inputs-before.json').write_text(json.dumps(before, indent=2) + '\n')
try:
    for kind in ('object', 'resource'):
        case = OUT / kind
        case.mkdir()
        original = case / 'original'
        original.mkdir()
        language = 'cpp' if kind == 'object' else 'c'
        source = original / ('main.cpp' if kind == 'object' else 'main.c')
        source.write_text('struct Item { int value; explicit Item(int n):value(n){} ~Item(){value=0;} };\n'
            'int workload(int n){Item item(n);return item.value+2;}\nint main(){return workload(3)==5?0:1;}\n'
            if kind == 'object' else '#include <stdlib.h>\nstruct Item{int value;};\n'
            'int workload(int n){struct Item *item=malloc(sizeof *item);if(!item)return -1;'
            'item->value=n;int value=item->value;free(item);return value+2;}\n'
            'int main(void){return workload(3)==5?0:1;}\n')
        compiler = Path('/opt/homebrew/opt/llvm@22/bin') / ('clang++' if kind == 'object' else 'clang')
        flags = ['-std=c++17' if kind == 'object' else '-std=c11', '-O0', '-fexceptions', '-pthread']
        database = [{'directory': str(original), 'file': source.name,
                     'arguments': [str(compiler), *flags, '-c', source.name, '-o', 'unused.o']}]
        (original / 'compile_commands.json').write_text(json.dumps(database) + '\n')
        settings = native_project.settings({'compilation_database': 'compile_commands.json',
            'targets': [{'name': 'application', 'units': [{'source': source.name}], 'link_flags': ['-pthread']}]})
        frontend = case / 'frontend'
        profile = native_project.prepare(original, settings, language, compiler, frontend, execute)
        rows = native_context.target_inventory(profile, frontend,
            compiler.resolve().with_name('llvm-cxxfilt') if kind == 'object' else None, execute)
        row = next(row for row in rows if row['function']['name'] == 'workload')
        entry = {**row['function'], 'language': language, 'globals': row['globals'],
                 'unit': row['unit'], 'target': row['target']}
        private = case / 'private'
        shutil.copytree(original, private)
        tools = native_toolchain.capture(Path('/opt/homebrew/opt/llvm@22/bin/llvm-config'),
                                         compiler, language, case, execute)
        sdk = native_sdk.capture(SDK_ROOT, SDK_ROOT / 'build/correction-sdk', tools,
            cmake=Path('/opt/homebrew/bin/cmake'), ninja=Path('/opt/homebrew/bin/ninja'),
            source_profile='resource-v1', coverage=True)
        helper_source = SDK_ROOT / 'native/clang' / ('Lifetimes.cpp' if kind == 'object' else 'Resources.cpp')
        dependency_file = case / 'caller-helper.d'
        result = execute([tools.directory / 'clang++', *tools.cxxflags, '-std=c++17', '-fexceptions',
            '-O1', '-g', '-M', '-MT', 'otelc-inputs', '-MF', dependency_file, helper_source], SDK_ROOT)
        assert result.returncode == 0
        prefix, separator, text = dependency_file.read_text().replace('\\\n', '').partition(':')
        assert prefix == 'otelc-inputs' and separator == ':'
        logical = tuple(Path(os.path.abspath(SDK_ROOT / word.replace('$$', '$'))) for word in shlex.split(text))
        dependencies = tuple(dict.fromkeys(path.resolve(strict=True) for path in logical))
        aliases = tuple(dict.fromkeys(path for path in logical if path.resolve(strict=True) != path))
        library = tools.directory.parent / 'lib'
        libraries = tuple((library / ('lib' + name + '.dylib')).resolve(strict=True) for name in ('clang-cpp', 'LLVM'))
        host = execute([tools.directory / 'clang++', '-print-target-triple'], case).stdout.decode().strip()
        tool = native_lifetime_inventory.freeze_tool(sdk, kind, dependencies, library, libraries,
                                                     aliases=aliases, host_target=host)
        policy = {'schema_version': 3, 'languages': [language],
            'resource': {'service_name': 'native-lifetime-caller-development'},
            'context': {'tasks': False, 'http': False},
            'sources': {'include': ['**'], 'exclude': []},
            'functions': {'include': ['workload*'], 'exclude': []},
            'lifetimes': {'enabled': True, 'include': ['Item'], 'exclude': [],
                          'max_live': 4096, 'release_methods': ['close']}}
        request = native_unit_caller.freeze(sdk, private, profile, frontend, entry, [3], policy)
        accepted = native_lifetime_caller.prepare(request, case / 'helpers', case / 'caller',
                                                  case / 'sdk-build', tool, execute)
        accepted.verify()
        accepted.recheck(case / 'after-preparation', execute)
        catalogues = [native_lifetime_inventory.catalogue(json.loads(raw), kind, policy, private)
                       for _, raw in accepted.intent.semantics]
        assert sum(len(value['types']) for value in catalogues) == 1
        sites = 'constructions' if kind == 'object' else 'allocations'
        assert sum(len(value[sites]) for value in catalogues) == 1
        STATE['cases'][kind] = {'status': 'passed', 'version': accepted.intent.version,
            'application_units': len(accepted.intent.semantics), 'types': 1, sites: 1,
            'source_bound_target': entry['symbol'], 'retained_files': len(accepted.binding.files),
            'caller_input_recheck': 'passed', 'sdk_output_absent': not accepted.intent.base.output.exists()}
        write()
    STATE['status'] = 'passed'
except Exception as error:
    STATE.update(status='failed', error=f'{type(error).__name__}: {error}')
    raise
finally:
    after = snapshot()
    (OUT / 'inputs-after.json').write_text(json.dumps(after, indent=2) + '\n')
    STATE['preservation'] = {key: before[key] == after[key] for key in before}
    STATE['seconds'] = round(time.monotonic() - started, 3)
    write()
    print(json.dumps({key: STATE.get(key) for key in ('status', 'seconds', 'cases', 'preservation', 'error')}))
