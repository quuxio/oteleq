"""Join caller-frozen native inputs to fixed compiler, plugin and gate recipes."""

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath
import shlex

import native_inputs as inputs
from native_protocol import PROFILE, digest, encoded, fields, require, same
from native_sdk import SDK
from otelc_capture import strict_json

MANIFEST = 'native-source-build.json'
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


def relative(value: object, language: str) -> str:
    """Accept canonical relative units for the selected language."""
    require(type(value) is str and bool(value) and '\0' not in value and '\\' not in value,
            'invalid native translation-unit name')
    path = PurePosixPath(value)
    suffixes = {'.c'} if language == 'c' else {'.cc', '.cpp', '.cxx', '.C'}
    require(not path.is_absolute() and str(path) == value and '..' not in path.parts
            and path.suffix in suffixes, 'native unit requires a canonical matching relative source path')
    return value


@dataclass(frozen=True)
class Intent:
    """Expected application/dependency inputs are supplied before SDK compilation."""

    sdk: SDK
    project: Path
    output: Path
    language: str
    units: tuple[str, ...]
    unit_dependencies: tuple[tuple[Path, ...], ...]
    dependencies: tuple[inputs.File, ...]
    policy_json: str
    plugin_source: inputs.File
    gate_source: inputs.File
    gate_compiler: inputs.File

    def policy(self) -> dict:
        """Decode a fresh copy of the caller's immutable policy."""
        return strict_json(self.policy_json)

    def verify(self) -> None:
        """Recheck SDK, source closure and fixed helper inputs."""
        self.sdk.verify()
        for held in (*self.dependencies, self.plugin_source, self.gate_source, self.gate_compiler):
            held.verify()


def freeze(sdk: SDK, project: Path, output: Path, language: str, units: tuple[str, ...],
           dependencies: tuple[tuple[Path, ...], ...], policy: dict) -> Intent:
    """Compiler-derived dependency paths cannot be replaced by producer metadata."""
    require(language in ('c', 'cpp') and type(units) is tuple and 1 <= len(units) <= 256
            and all(type(name) is str for name in units)
            and len(set(units)) == len(units), 'invalid native language or unit denominator')
    require(project.is_absolute() and project == project.resolve(strict=True) and project.is_dir()
            and project != Path('/'), 'native project must be canonical')
    require(output.is_absolute() and output == output.resolve() and output.parent == output.parent.resolve(strict=True)
            and not output.exists() and not output.is_symlink() and not output.is_relative_to(project),
            'native build output must be a new canonical directory outside the application')
    selected = tuple(relative(name, language) for name in units)
    require(type(dependencies) is tuple and len(dependencies) == len(selected), 'missing per-unit native caller dependencies')
    paths = {}
    for name, group in zip(selected, dependencies):
        require(type(group) is tuple and 1 <= len(group) <= 10000
                and all(isinstance(path, Path) for path in group)
                and len(set(group)) == len(group) and project / name in group,
                'incomplete or repeated native unit dependencies')
        paths.update(dict.fromkeys(group))
        require(len(paths) <= 10000, 'native caller dependency set exceeds its budget')
    require(type(policy) is dict and same(policy.get('schema_version'), 3)
            and type(policy.get('languages')) is list and language in policy['languages']
            and type(policy.get('lifetimes')) is dict and policy['lifetimes'].get('enabled') is False
            and type(policy.get('context')) is dict and set(policy['context']) == {'http', 'tasks'}
            and all(value is False for value in policy['context'].values()), 'unsupported native source policy')
    result = Intent(sdk, project, output, language, selected, dependencies, tuple(inputs.capture(path) for path in paths),
        encoded(policy), inputs.capture(sdk.root / 'native/llvm/OtelcPass.cpp'),
        inputs.capture(sdk.root / 'adapters/native/gate/ExecGate.c'), inputs.capture(sdk.toolchain.clang.resolved))
    result.verify()
    return result


def suffix(intent: Intent) -> str:
    """The selected platform fixes the shared-library suffix."""
    return 'dylib' if intent.sdk.platform == 'darwin' else 'so'


def commands(intent: Intent) -> list[list[str]]:
    """Reconstruct every compile/link operation and both matched application lanes."""
    root, output, tools = intent.project, intent.output, intent.sdk.toolchain.directory
    compiler, cxx = tools / ('clang' if intent.language == 'c' else 'clang++'), tools / 'clang++'
    flags = ['-O2', '-g', '-fexceptions', '-pthread', '-std=c11' if intent.language == 'c' else '-std=c++17', '-I', str(root)]
    result = []
    for lane in ('plain', 'instrumented'):
        objects = []
        for index, name in enumerate(intent.units):
            label = lane + '-' + str(index)
            object_path = output / (label + '.o')
            command = [str(compiler), *flags, '-MMD', '-MF', str(output / (label + '.d')),
                       '-MT', 'otelc-inputs', '-c', str(root / name), '-o', str(object_path)]
            if lane == 'instrumented':
                command.append('-fpass-plugin=' + str(output / ('plugin/libotelc_llvm.' + suffix(intent))))
            result.append(command)
            objects.append(str(object_path))
        if lane == 'instrumented':
            result.append([str(cxx), '-std=c++17', '-O2', '-g', '-c', str(output / 'bootstrap.cpp'),
                '-o', str(output / 'bootstrap.o'), '-I', str(intent.sdk.root / 'adapters/native/launcher/include')])
            objects.insert(0, str(output / 'bootstrap.o'))
        link = [str(cxx), '-pthread', *objects, '-o', str(output / lane)]
        if lane == 'instrumented':
            link += [str(intent.sdk.library.path), '-Wl,-rpath,' + str(intent.sdk.directory)]
        result.append(link)
    return result


def names(intent: Intent) -> set[str]:
    """The fixed recipe has a closed file denominator, including compiler channels."""
    root = {'native-build.json', MANIFEST, 'plain', 'instrumented', 'bootstrap.cpp', 'bootstrap.o',
            *[label + '.' + channel for label in ('plain-link', 'instrumented-link', 'bootstrap') for channel in ('stdout', 'stderr')]}
    units = {lane + '-' + str(index) + '.' + extension for lane in ('plain', 'instrumented')
             for index in range(len(intent.units)) for extension in ('o', 'd', 'stdout', 'stderr')}
    plugin = {'plugin/' + name for name in ('llvm-plugin.json', 'libotelc_llvm.' + suffix(intent),
                                          'build.stdout', 'build.stderr', 'command.json', 'compile_commands.json')}
    gate = {'gate/' + name for name in ('gate.json', 'otelc-exec-gate', 'compile.stdout', 'compile.stderr', 'compile_commands.json')}
    return root | units | plugin | gate


def file_set(root: Path) -> set[str]:
    """Inventory ordinary products without accepting directory aliases."""
    require(root == root.resolve(strict=True) and root.is_dir(), 'native build directory changed')
    result = set()
    for path in root.iterdir():
        require(not path.is_symlink(), 'native build contains a symlink')
        if path.name in ('plugin', 'gate'):
            require(path.is_dir(), 'native build component is not a directory')
            for child in path.iterdir():
                require(not child.is_symlink() and child.is_file(), 'native build component contains an unowned path')
                result.add(child.relative_to(root).as_posix())
        else:
            require(path.is_file(), 'native build contains an unowned directory')
            result.add(path.name)
    return result


def plugin(intent: Intent, held: dict[str, inputs.File]) -> None:
    """Reconstruct the LLVM plugin receipt and compiler channels."""
    tools, root, output = intent.sdk.toolchain, intent.sdk.root, intent.output
    command = [str(tools.directory / 'clang++'), '-shared', '-fPIC', '-O2', *tools.cxxflags,
        str(intent.plugin_source.path), *tools.ldflags, '-o', str(output / ('plugin/libotelc_llvm.' + suffix(intent))),
        '-DOTELC_FUNCTION_REGISTRY_V1=1', '-DOTELC_SOURCE_PROFILE_V1=1']
    channels = ('build.stdout', 'build.stderr', 'command.json', 'compile_commands.json')
    expected = {'schema_version': 1, 'kind': 'otelc.llvm-plugin', 'profile': 'llvm22-itanium-source-v1',
        'probe_abi': 'otelc.function.v2', 'source': intent.plugin_source.tool_identity(),
        'headers': [inputs.capture(root / 'native/llvm/function_abi.h').tool_identity()], 'toolchain': tools.metadata(),
        'plugin': held['plugin/libotelc_llvm.' + suffix(intent)].tool_identity(), 'coverage': False, 'source_complete': False,
        'evidence': {name: held['plugin/' + name].tool_identity() for name in channels}}
    require(same(strict_json(held['plugin/llvm-plugin.json'].content), expected), 'native plugin recipe or evidence differs')
    require(same(strict_json(held['plugin/command.json'].content), command)
            and same(strict_json(held['plugin/compile_commands.json'].content),
                     [{'directory': str(root), 'file': str(intent.plugin_source.path), 'arguments': command}]),
            'native plugin command channels differ from the fixed recipe')


def gate(intent: Intent, held: dict[str, inputs.File]) -> None:
    """Bind the fixed gate to its source and canonical C compiler."""
    executable = intent.output / 'gate/otelc-exec-gate'
    command = [str(intent.gate_compiler.path), '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
               str(intent.gate_source.path), '-o', str(executable)]
    expected = {'schema_version': 1, 'kind': 'otelc.native.exec-gate', 'source': intent.gate_source.gate_identity(),
        'compiler': intent.gate_compiler.gate_identity(), 'executable': held['gate/otelc-exec-gate'].gate_identity(),
        'coverage': False, 'command': command, 'source_complete': False}
    require(same(strict_json(held['gate/gate.json'].content), expected), 'native gate recipe differs')
    require(same(strict_json(held['gate/compile_commands.json'].content),
                 [{'directory': str(intent.sdk.root), 'file': str(intent.gate_source.path), 'arguments': command}]),
            'native gate compiler channel differs')


def compiler_inputs(intent: Intent, held: dict[str, inputs.File]) -> None:
    """Join each lane's manifests to caller-frozen per-unit inputs."""
    expected = {str(item.path): item.identity() for item in intent.dependencies}
    groups = []
    for lane in ('plain', 'instrumented'):
        found = set()
        for index in range(len(intent.units)):
            raw = held[lane + '-' + str(index) + '.d'].content.decode('utf-8').replace('\\\n', '')
            target, separator, dependencies = raw.partition(':')
            require(target == 'otelc-inputs' and separator == ':', 'native dependency channel has a different target')
            unit = set()
            for name in shlex.split(dependencies):
                # The compiler channel may confirm an already frozen path;
                # it must not select another file for the reader to inspect.
                path = Path(os.path.abspath(intent.project / name.replace('$$', '$')))
                require(str(path) in expected, 'native compiler consumed an undeclared input')
                unit.add(str(path))
            require(unit == {str(path) for path in intent.unit_dependencies[index]},
                    'native compiler per-unit dependencies differ from caller discovery')
            found.update(unit)
        require(found == set(expected), 'native compiler omitted a caller-frozen input')
        groups.append(found)
    require(groups[0] == groups[1], 'native compiler input sets differ between lanes')


@dataclass(frozen=True)
class Build:
    """Immutable snapshots retain every expected build product."""
    intent: Intent
    files: tuple[inputs.File, ...]

    def file(self, name: str) -> inputs.File:
        """Look up a fixed product without metadata-selected paths."""
        require(name in names(self.intent), 'unknown native product name')
        return next(item for item in self.files if item.path == self.intent.output / name)

    def manifest(self) -> dict:
        """Decode a fresh view of the accepted source-build record."""
        return strict_json(self.file(MANIFEST).content)

    def verify(self) -> None:
        """Recheck the product denominator and original input/file facts."""
        self.intent.verify()
        expected = names(self.intent)
        require(type(self.files) is tuple and len(self.files) == len(expected)
                and {item.path for item in self.files} == {self.intent.output / name for name in expected}
                and file_set(self.intent.output) == expected, 'native build file denominator changed')
        for item in self.files:
            item.verify()


def read(intent: Intent) -> Build:
    """Bind the compiler response; never run commands or select paths from it."""
    require(type(intent) is Intent, 'native build2 requires its fixed-source caller intent')
    intent.verify()
    require(file_set(intent.output) == names(intent), 'native build file denominator differs from the fixed recipe')
    held = {name: inputs.capture(intent.output / name, keep=name.endswith(('.json', '.d')) or name == 'bootstrap.cpp')
            for name in sorted(names(intent))}
    require(held['bootstrap.cpp'].content == BOOTSTRAP.encode(), 'native bootstrap differs from its independent recipe')
    plugin(intent, held)
    gate(intent, held)
    compiler_inputs(intent, held)
    metadata = strict_json(held['native-build.json'].content)
    values = fields(metadata, {'schema_version', 'kind', 'profile', 'language', 'root', 'policy', 'policy_sha256',
        'selection_sha256', 'inputs', 'sdk_library', 'products', 'commands', 'source_complete'}, 'native build')
    expected_inputs = {str(item.path): item.identity() for item in intent.dependencies}
    require(type(values['inputs']) is list and len(values['inputs']) == len(expected_inputs)
            and all(type(item) is dict and type(item.get('path')) is str for item in values['inputs'])
            and len({item['path'] for item in values['inputs']}) == len(values['inputs'])
            and same({item['path']: item for item in values['inputs']}, expected_inputs), 'native build input identities differ')
    policy = intent.policy()
    require(same(values, {'schema_version': 1, 'kind': 'otelc.native-build', 'profile': 'llvm22-native-launch-v1',
        'language': intent.language, 'root': str(intent.project), 'policy': policy, 'policy_sha256': digest(policy),
        'selection_sha256': digest({key: policy[key] for key in ('sources', 'functions')}), 'inputs': values['inputs'],
        'sdk_library': intent.sdk.library.identity(), 'products': [held[name].identity() for name in ('plain', 'instrumented')],
        'commands': commands(intent), 'source_complete': False}), 'native build differs from caller intent or compiler recipe')
    expected = {'schema_version': 2, 'kind': 'otelc.native.source-build', 'profile': PROFILE,
        **{key: held[name].gate_identity() for key, name in
           (('native', 'native-build.json'), ('plugin', 'plugin/llvm-plugin.json'), ('gate', 'gate/gate.json'))},
        'sdk': intent.sdk.record.file.gate_identity(), 'source_complete': False}
    require(same(strict_json(held[MANIFEST].content), expected), 'native source-build record differs from its fixed bindings')
    result = Build(intent, tuple(held.values()))
    result.verify()
    return result
