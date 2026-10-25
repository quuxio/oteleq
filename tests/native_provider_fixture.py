"""Literal, non-executed native metadata for independent reader regression tests."""

import hashlib
import json
from pathlib import Path
import shlex
from subprocess import CompletedProcess

import native_build
import native_sdk
import native_toolchain

POLICY = {'schema_version': 3, 'languages': ['c', 'cpp'], 'sources': {'include': ['**'], 'exclude': []},
          'resource': {'service_name': 'native-telemetry-unit'},
          'functions': {'include': ['workload*'], 'exclude': []}, 'lifetimes': {'enabled': False},
          'context': {'http': False, 'tasks': False}}
BOOTSTRAP = '''#include <cstdlib>
#include <cerrno>
#include <climits>
#include "otelc/native_runtime.h"
__attribute__((constructor(0))) static void otelc_bootstrap() {
  const char *raw = std::getenv("OTELC_NATIVE_PLAN_FD");
  if (!raw || !*raw) std::_Exit(78);
  char *end = nullptr; errno = 0;
  long fd = std::strtol(raw, &end, 10);
  if (errno || *end || fd < 3 || fd > INT_MAX) std::_Exit(78);
  if (otelc_native_start_v1(static_cast<int>(fd))) std::_Exit(78);
  if (std::atexit(otelc_native_finish_v1)) std::_Exit(78);
}
'''


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + '\n')


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def identity(path: Path, *, gate: bool = False, tool: bool = False) -> dict:
    resolved = path.resolve()
    info = path.stat()
    data = {'path': str(resolved if tool else path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': info.st_size}
    if not tool:
        data['resolved_path'] = str(resolved)
        if path.is_symlink(): data['symlink'] = str(path.readlink())
    if gate:
        data.update(device=info.st_dev, inode=info.st_ino, mode=info.st_mode, uid=info.st_uid, gid=info.st_gid,
                    mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns, links=info.st_nlink)
    return data


def toolchain(root: Path, *, language: str = 'cpp', mutate=None):
    directory = root / 'llvm/bin'; directory.mkdir(parents=True)
    for name in ('llvm-config', 'clang-22'):
        (directory / name).write_text('unit tool; never executed: ' + name)
        (directory / name).chmod(0o755)
    for name in ('clang', 'clang++'):
        (directory / name).symlink_to('clang-22')
    options = ('-I' + str(root / 'llvm/include'), '-std=c++17')
    links = ('-L' + str(root / 'llvm/lib'), '-lLLVM-22')
    queries = []

    def execute(argv, cwd):
        words = tuple(map(str, argv)); queries.append(words)
        arguments = words[1:]
        if arguments == ('--version',):
            raw = '22.1.8\n' if Path(words[0]).name == 'llvm-config' else 'unit clang version 22.1.8\n'
        elif arguments == ('--bindir',): raw = str(directory) + '\n'
        elif arguments == ('--cxxflags',): raw = shlex.join(options) + '\n'
        else:
            assert arguments == ('--ldflags', '--libs', 'core', 'passes', '--system-libs')
            raw = shlex.join(links) + '\n'
        result = CompletedProcess(argv, 0, raw.encode(), b'')
        return mutate(result) if mutate else result

    selected = directory / ('clang' if language == 'c' else 'clang++')
    value = native_toolchain.capture(directory / 'llvm-config', selected, language, root, execute)
    return value, queries


def sdk(root: Path, *, language: str = 'cpp'):
    tools, _ = toolchain(root, language=language)
    source = root / 'sdk'
    names = ('adapters/native/CMakeLists.txt', 'adapters/native/launcher/CMakeLists.txt',
             'adapters/native/src/runtime.cpp', 'adapters/native/include/runtime.h', 'native/llvm/function_abi.h',
             'adapters/native/gate/ExecGate.c', 'native/llvm/OtelcPass.cpp')
    for name in names:
        path = source / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('unit source ' + name)
    directory = root / 'sdk-build'; directory.mkdir()
    library = directory / 'libotelc_native_runtime.so'; library.write_bytes(b'unit library; never loaded')
    cmake, ninja = root / 'cmake', root / 'ninja'
    cmake.write_text('unit cmake'); ninja.write_text('unit ninja')
    command = [str(cmake), '-S', str(source / 'adapters/native/launcher'), '-B', str(directory), '-G', 'Ninja',
        '-DCMAKE_BUILD_TYPE=RelWithDebInfo', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
        '-DCMAKE_C_COMPILER=' + str(tools.directory / 'clang'), '-DCMAKE_CXX_COMPILER=' + str(tools.directory / 'clang++'),
        '-DOTELC_LAUNCH_COVERAGE=OFF']
    value = {'schema_version': 1, 'kind': 'otelc.native-sdk-build', 'coverage': False, 'source_complete': False,
        'sources': [identity(source / name) for name in names[:5]], 'toolchain': tools.metadata(),
        'build_tools': [identity(path) for path in (cmake, ninja)], 'library': identity(library),
        'commands': [command, [str(cmake), '--build', str(directory), '--target', 'otelc_native_runtime', '-j', '4']]}
    write(directory / 'native-sdk-build.json', value)
    return native_sdk.capture(source, directory, tools, cmake=cmake, ninja=ninja, platform='linux')


def build(root: Path, *, language: str = 'cpp', count: int = 1):
    selected = sdk(root, language=language)
    project = root / 'application'; project.mkdir()
    extension = '.c' if language == 'c' else '.cpp'
    units = tuple('unit' + str(index) + extension for index in range(count))
    header = project / 'state.h'; header.write_text('unit header')
    for name in units: (project / name).write_text('unit source ' + name)
    dependencies = tuple((project / name, header) for name in units)
    output = root / 'build'
    intent = native_build.freeze(selected, project, output, language, units, dependencies, POLICY)
    output.mkdir(); (output / 'plugin').mkdir(); (output / 'gate').mkdir()
    for lane in ('plain', 'instrumented'):
        (output / lane).write_text('unit executable ' + lane)
        for index, name in enumerate(units):
            label = lane + '-' + str(index)
            (output / (label + '.o')).write_text('unit object ' + label)
            (output / (label + '.d')).write_text('otelc-inputs: ' + shlex.join([str(project / name), str(header)]) + '\n')
            for channel in ('stdout', 'stderr'): (output / (label + '.' + channel)).write_bytes(b'')
    (output / 'bootstrap.cpp').write_text(BOOTSTRAP); (output / 'bootstrap.o').write_bytes(b'unit bootstrap object')
    for name in ('plain-link', 'instrumented-link', 'bootstrap'):
        for channel in ('stdout', 'stderr'): (output / (name + '.' + channel)).write_bytes(b'')
    plugin = output / 'plugin/libotelc_llvm.so'; plugin.write_bytes(b'unit plugin; never loaded')
    command = [str(selected.toolchain.directory / 'clang++'), '-shared', '-fPIC', '-O2', *selected.toolchain.cxxflags,
        str(selected.root / 'native/llvm/OtelcPass.cpp'), *selected.toolchain.ldflags, '-o', str(plugin),
        '-DOTELC_FUNCTION_REGISTRY_V1=1', '-DOTELC_SOURCE_PROFILE_V1=1']
    write(output / 'plugin/command.json', command)
    write(output / 'plugin/compile_commands.json', [{'directory': str(selected.root),
        'file': str(selected.root / 'native/llvm/OtelcPass.cpp'), 'arguments': command}])
    for channel in ('stdout', 'stderr'): (output / ('plugin/build.' + channel)).write_bytes(b'')
    write(output / 'plugin/llvm-plugin.json', {'schema_version': 1, 'kind': 'otelc.llvm-plugin',
        'profile': 'llvm22-itanium-source-v1', 'probe_abi': 'otelc.function.v2', 'coverage': False, 'source_complete': False,
        'toolchain': selected.toolchain.metadata(), 'source': identity(selected.root / 'native/llvm/OtelcPass.cpp', tool=True),
        'headers': [identity(selected.root / 'native/llvm/function_abi.h', tool=True)], 'plugin': identity(plugin, tool=True),
        'evidence': {name: identity(output / 'plugin' / name, tool=True)
                     for name in ('build.stdout', 'build.stderr', 'command.json', 'compile_commands.json')}})
    executable = output / 'gate/otelc-exec-gate'; executable.write_bytes(b'unit gate; never executed'); executable.chmod(0o755)
    compiler = selected.toolchain.clang.resolved
    command = [str(compiler), '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
               str(selected.root / 'adapters/native/gate/ExecGate.c'), '-o', str(executable)]
    write(output / 'gate/compile_commands.json', [{'directory': str(selected.root),
        'file': str(selected.root / 'adapters/native/gate/ExecGate.c'), 'arguments': command}])
    for channel in ('stdout', 'stderr'): (output / ('gate/compile.' + channel)).write_bytes(b'')
    write(output / 'gate/gate.json', {'schema_version': 1, 'kind': 'otelc.native.exec-gate', 'coverage': False,
        'source_complete': False, 'source': identity(selected.root / 'adapters/native/gate/ExecGate.c', gate=True),
        'compiler': identity(compiler, gate=True), 'executable': identity(executable, gate=True), 'command': command})
    commands = []
    for lane in ('plain', 'instrumented'):
        objects = []
        for index, name in enumerate(units):
            label = lane + '-' + str(index); object_path = output / (label + '.o')
            command = [str(selected.toolchain.directory / ('clang' if language == 'c' else 'clang++')), '-O2', '-g',
                '-fexceptions', '-pthread', '-std=c11' if language == 'c' else '-std=c++17', '-I', str(project),
                '-MMD', '-MF', str(output / (label + '.d')), '-MT', 'otelc-inputs', '-c', str(project / name), '-o', str(object_path)]
            if lane == 'instrumented': command += ['-fpass-plugin=' + str(plugin)]
            commands.append(command); objects.append(str(object_path))
        if lane == 'instrumented':
            commands.append([str(selected.toolchain.directory / 'clang++'), '-std=c++17', '-O2', '-g', '-c',
                str(output / 'bootstrap.cpp'), '-o', str(output / 'bootstrap.o'), '-I', str(selected.root / 'adapters/native/launcher/include')])
            objects.insert(0, str(output / 'bootstrap.o'))
        command = [str(selected.toolchain.directory / 'clang++'), '-pthread', *objects, '-o', str(output / lane)]
        if lane == 'instrumented': command += [str(selected.library.path), '-Wl,-rpath,' + str(selected.directory)]
        commands.append(command)
    write(output / 'native-build.json', {'schema_version': 1, 'kind': 'otelc.native-build',
        'profile': 'llvm22-native-launch-v1', 'language': language, 'root': str(project), 'policy': POLICY,
        'policy_sha256': digest(POLICY), 'selection_sha256': digest({key: POLICY[key] for key in ('sources', 'functions')}),
        'inputs': [identity(project / name) for name in units] + [identity(header)],
        'sdk_library': identity(selected.library.path), 'products': [identity(output / name) for name in ('plain', 'instrumented')],
        'commands': commands, 'source_complete': False})
    write(output / 'native-source-build.json', {'schema_version': 2, 'kind': 'otelc.native.source-build', 'profile': 'native-owned-v1',
        'source_complete': False, 'native': identity(output / 'native-build.json', gate=True),
        'plugin': identity(output / 'plugin/llvm-plugin.json', gate=True), 'gate': identity(output / 'gate/gate.json', gate=True),
        'sdk': identity(selected.record.file.path, gate=True)})
    return intent
