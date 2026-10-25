"""Bind native build3 to caller-held per-unit contexts and neutral tooling."""

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shlex

import native_build
import native_inputs as inputs
from native_protocol import PROFILE, digest, encoded, fields, require, same
from native_sdk import SDK
from otelc_capture import strict_json

UNIT_PROFILE = 'llvm22-native-units-v1'
PATH_FLAGS = {'-I', '-isystem', '-iquote', '-include', '-imacros'}
SIMPLE_FLAGS = {'-g', '-g0', '-g1', '-g2', '-g3', '-gline-tables-only', '-pthread', '-pipe',
    '-fPIC', '-fpic', '-fPIE', '-fpie', '-fno-common', '-fcommon', '-fexceptions', '-fno-exceptions',
    '-frtti', '-fno-rtti', '-fno-omit-frame-pointer', '-fomit-frame-pointer',
    '-fno-strict-aliasing', '-fstrict-aliasing'}


def canonical(value: object, *, directory: bool = False) -> Path:
    """Caller paths must be explicit; records cannot introduce aliases."""
    require(type(value) is str and bool(value) and '\0' not in value, 'invalid native unit path')
    path = Path(value)
    require(path.is_absolute() and path.resolve(strict=True) == path
            and (path.is_dir() if directory else path.is_file()), 'noncanonical native unit path')
    return path


def compiler_flags(values: object, directory: Path) -> None:
    """Only semantic options can enter the independently reconstructed argv."""
    require(type(values) is list and len(values) <= 1024
            and all(type(value) is str and 0 < len(value) <= 8192 and '\0' not in value for value in values),
            'invalid native unit flags')
    index = 0
    while index < len(values):
        value = values[index]
        if value in PATH_FLAGS | {'-D', '-U'}:
            require(index + 1 < len(values), 'missing native option value')
            if value in PATH_FLAGS:
                selected = (directory / values[index + 1]).resolve(strict=True)
                require(selected.is_file() if value in ('-include', '-imacros') else selected.is_dir(),
                        'invalid native compiler path option')
            index += 2
            continue
        require(value in SIMPLE_FLAGS or re.fullmatch(r'-O[0123sgz]', value) is not None
                or re.fullmatch(r'-std=(?:gnu\+\+|c\+\+)(?:17|20|23)|-std=(?:gnu|c)(?:11|17|23)', value) is not None
                or re.fullmatch(r'-W(?:all|extra|error|pedantic|no-[A-Za-z][A-Za-z\d-]*)', value, re.ASCII) is not None,
                'unsupported native unit compiler option')
        index += 1


def overlay(path: Path, project: Path, assets: set[Path]) -> set[Path]:
    """Original and private VFS bytes have separate immutable identities."""
    require(path in assets, 'native overlay is not a declared private asset')
    value = strict_json(inputs.capture(path, maximum=1024 * 1024, keep=True).content)
    fields(value, {'version', 'use-external-names', 'roots'}, 'native overlay')
    require(same(value['version'], 0) and value['use-external-names'] is False
            and type(value['roots']) is list and 1 <= len(value['roots']) <= 256, 'unsupported native overlay')
    originals = set()
    for row in value['roots']:
        fields(row, {'type', 'name', 'external-contents'}, 'native overlay entry')
        original, private = canonical(row['name']), canonical(row['external-contents'])
        require(row['type'] == 'file' and original.is_relative_to(project)
                and private in assets and original not in originals, 'unbound native overlay entry')
        originals.add(original)
    return originals


def unit_paths(unit: dict, project: Path, assets: set[Path]) -> tuple[set[Path], tuple]:
    """A neutral driver is external; an application unit retains its original context."""
    fields(unit, {'id', 'role', 'source', 'language', 'directory', 'flags', 'overlay', 'rename_main'}, 'native unit')
    require(type(unit['id']) is str and re.fullmatch(r'[A-Za-z_]\w{0,63}', unit['id'], re.ASCII) is not None
            and unit['id'] != 'link', 'invalid native unit id')
    require(type(unit['language']) is str and unit['language'] in ('c', 'cpp')
            and unit['role'] in ('application', 'driver') and type(unit['rename_main']) is bool,
            'invalid native unit language or role')
    source, directory = canonical(unit['source']), canonical(unit['directory'], directory=True)
    require(source.suffix in (('.c',) if unit['language'] == 'c' else ('.cpp', '.cc', '.cxx', '.C')),
            'native unit source language differs')
    compiler_flags(unit['flags'], directory)
    paths = {source}
    if unit['role'] == 'application':
        require(source.is_relative_to(project) and directory.is_relative_to(project), 'native application unit escapes its root')
        if unit['overlay'] is not None:
            paths.update(overlay(canonical(unit['overlay']), project, assets))
    else:
        require(source in assets and unit['overlay'] is None and not unit['rename_main'], 'unbound neutral native driver')
    return paths, (str(source), str(directory), unit['language'], tuple(unit['flags']), unit['role'], unit['overlay'])


def link_context(link: dict) -> None:
    """The public unit recipe does not accept arbitrary linker actions."""
    fields(link, {'language', 'directory', 'flags'}, 'native link context')
    require(type(link['language']) is str and link['language'] in ('c', 'cpp')
            and type(link['flags']) is list and len(link['flags']) <= 256
            and all(type(flag) is str and (flag == '-pthread' or re.fullmatch(r'-l[A-Za-z_]\w*', flag, re.ASCII))
                    for flag in link['flags']), 'unsupported native unit link context')
    canonical(link['directory'], directory=True)


def recipe_paths(recipe: dict, project: Path) -> set[Path]:
    """Validate a caller-created closed recipe before any producer build."""
    fields(recipe, {'schema_version', 'kind', 'assets', 'units', 'link'}, 'native unit recipe')
    require(same(recipe['schema_version'], 1) and recipe['kind'] == 'otelc.native.unit-recipe'
            and len(encoded(recipe).encode()) <= 1024 * 1024, 'unsupported native unit recipe')
    require(type(recipe['assets']) is list and len(recipe['assets']) <= 1024, 'invalid native unit assets')
    assets = {canonical(value) for value in recipe['assets']}
    require(len(assets) == len(recipe['assets']) and all(not path.is_relative_to(project) for path in assets),
            'native private assets must be distinct and external')
    require(type(recipe['units']) is list and 1 <= len(recipe['units']) <= 257, 'invalid native unit denominator')
    paths, identifiers, contexts, applications, drivers = set(assets), set(), set(), 0, 0
    for unit in recipe['units']:
        group, context = unit_paths(unit, project, assets)
        require(unit['id'] not in identifiers and context not in contexts, 'repeated native unit id or context')
        identifiers.add(unit['id']); contexts.add(context); paths.update(group)
        applications += unit['role'] == 'application'
        drivers += unit['role'] == 'driver'
    require(1 <= applications <= 256 and drivers <= 1, 'invalid native application/driver denominator')
    link_context(recipe['link'])
    return paths


@dataclass(frozen=True)
class Intent:
    """Independent discovery supplies per-unit inputs before producer compilation."""

    sdk: SDK
    project: Path
    output: Path
    language: str
    recipe_json: str
    unit_dependencies: tuple[tuple[Path, ...], ...]
    dependencies: tuple[inputs.File, ...]
    policy_json: str
    plugin_source: inputs.File
    gate_source: inputs.File
    gate_compiler: inputs.File
    objcopy: inputs.File | None

    def recipe(self) -> dict:
        """Decode a new value; caller mutation cannot replace frozen intent."""
        return strict_json(self.recipe_json)

    def policy(self) -> dict:
        """Return the independently frozen common policy."""
        return strict_json(self.policy_json)

    def verify(self) -> None:
        """Retain SDK, application, private observer and matched tool identities."""
        self.sdk.verify()
        for held in (*self.dependencies, self.plugin_source, self.gate_source, self.gate_compiler):
            held.verify()
        if self.objcopy is not None:
            self.objcopy.verify()
        require(recipe_paths(self.recipe(), self.project) <= {item.path for item in self.dependencies},
                'native unit recipe contains an unfrozen input')


def freeze(sdk: SDK, project: Path, output: Path, language: str, recipe: dict,
           dependencies: tuple[tuple[Path, ...], ...], policy: dict) -> Intent:
    """Producer metadata may confirm a closed caller intent; it cannot select inputs."""
    require(language in ('c', 'cpp') and canonical(str(project), directory=True) == project and project != Path('/'),
            'invalid native unit application root')
    require(output.is_absolute() and output == output.resolve() and output.parent == output.parent.resolve(strict=True)
            and not output.exists() and not output.is_symlink() and not output.is_relative_to(project),
            'native unit output must be a new external canonical directory')
    paths = recipe_paths(recipe, project)
    require(type(dependencies) is tuple and len(dependencies) == len(recipe['units']), 'missing native per-unit discovery')
    for unit, group in zip(recipe['units'], dependencies):
        require(type(group) is tuple and 1 <= len(group) <= 10000
                and all(isinstance(path, Path) for path in group) and len(set(group)) == len(group)
                and Path(unit['source']) in group, 'invalid native per-unit input closure')
        paths.update(group)
        require(len(paths) <= 10000, 'native unit input closure exceeds its budget')
    require(type(policy) is dict and same(policy.get('schema_version'), 3)
            and type(policy.get('languages')) is list and language in policy['languages']
            and type(policy.get('lifetimes')) is dict and policy['lifetimes'].get('enabled') is False
            and same(policy.get('context'), {'tasks': False, 'http': False}), 'unsupported native unit policy')
    renamed = any(unit['rename_main'] for unit in recipe['units'])
    result = Intent(sdk, project, output, language, encoded(recipe), dependencies,
        tuple(inputs.capture(path) for path in sorted(paths)), encoded(policy),
        inputs.capture(sdk.root / 'native/llvm/OtelcPass.cpp'), inputs.capture(sdk.root / 'adapters/native/gate/ExecGate.c'),
        inputs.capture(sdk.toolchain.clang.resolved), inputs.capture(sdk.toolchain.directory / 'llvm-objcopy') if renamed else None)
    result.verify()
    return result


def operation(label: str, directory: str, argv: list[str], product: Path, **extra) -> dict:
    """Each fixed operation retains its original working directory and full argv."""
    return {'label': label, 'directory': directory, 'arguments': argv, 'output': str(product), **extra}


def unit_commands(intent: Intent, unit: dict, lane: str) -> list[dict]:
    """Compile one original context; only application units receive probes."""
    output, tools = intent.output, intent.sdk.toolchain.directory
    label = lane + '-' + unit['id']
    final = output / (label + '.o')
    product = output / (label + '.original.o') if unit['rename_main'] else final
    depfile = output / (label + '.d')
    compiler = tools / ('clang' if unit['language'] == 'c' else 'clang++')
    argv = [str(compiler), *unit['flags'], '-g', '-MD', '-MF', str(depfile), '-MT', 'otelc-inputs',
            '-c', unit['source'], '-o', str(product)]
    if unit['overlay'] is not None:
        argv += ['-ivfsoverlay', unit['overlay']]
    if lane == 'instrumented' and unit['role'] == 'application':
        argv += ['-fpass-plugin=' + str(output / ('plugin/libotelc_llvm.' + native_build.suffix(intent)))]
    result = [operation(label, unit['directory'], argv, product, source=unit['source'],
                        dependencies=str(depfile), unit=unit['id'], lane=lane)]
    if unit['rename_main']:
        result.append(operation(label + '-rename', str(output), [str(intent.objcopy.path), '--redefine-sym',
            'main=__oteleq_original_main', '--redefine-sym', '_main=___oteleq_original_main', str(product), str(final)], final))
    return result


def commands(intent: Intent) -> list[dict]:
    """Derive fixed compile, optional main rename, neutral driver and link operations."""
    recipe, output, tools = intent.recipe(), intent.output, intent.sdk.toolchain.directory
    result = []
    for lane in ('plain', 'instrumented'):
        objects = []
        for unit in recipe['units']:
            result.extend(unit_commands(intent, unit, lane))
            objects.append(str(output / (lane + '-' + unit['id'] + '.o')))
        if lane == 'instrumented':
            bootstrap = output / 'bootstrap.o'
            result.append(operation('bootstrap', str(output), [str(tools / 'clang++'), '-std=c++17', '-O2', '-g', '-c',
                str(output / 'bootstrap.cpp'), '-o', str(bootstrap), '-I', str(intent.sdk.root / 'adapters/native/launcher/include')],
                bootstrap, source=str(output / 'bootstrap.cpp')))
            objects.insert(0, str(bootstrap))
        compiler = tools / ('clang' if recipe['link']['language'] == 'c' else 'clang++')
        argv = [str(compiler), *objects, *recipe['link']['flags'], '-o', str(output / lane)]
        if lane == 'instrumented':
            argv += [str(intent.sdk.library.path), '-Wl,-rpath,' + str(intent.sdk.directory)]
        result.append(operation(lane + '-link', recipe['link']['directory'], argv, output / lane))
    return result


def artifacts(intent: Intent) -> set[str]:
    """Every generated command has complete products and output channels."""
    paths = {'bootstrap.cpp', 'compile_commands.json'}
    for row in commands(intent):
        paths.update((Path(row['output']).name, row['label'] + '.stdout', row['label'] + '.stderr'))
        if 'dependencies' in row:
            paths.add(Path(row['dependencies']).name)
    return paths


def names(intent: Intent) -> set[str]:
    """Keep build3's closed denominator separate from build2's fixed source recipe."""
    components = {prefix + '/' + name for prefix, entries in (
        ('plugin', ('llvm-plugin.json', 'libotelc_llvm.' + native_build.suffix(intent), 'build.stdout', 'build.stderr', 'command.json', 'compile_commands.json')),
        ('gate', ('gate.json', 'otelc-exec-gate', 'compile.stdout', 'compile.stderr', 'compile_commands.json')))
        for name in entries}
    return artifacts(intent) | components | {'plain', 'instrumented', 'native-build.json', native_build.MANIFEST}


def compiler_inputs(intent: Intent, held: dict[str, inputs.File]) -> tuple[list[dict], dict]:
    """Compiler channels only confirm each independently discovered input set."""
    expected = {str(item.path): item for item in intent.dependencies}
    discovered = {unit['id']: set(group) for unit, group in zip(intent.recipe()['units'], intent.unit_dependencies)}
    found, groups = {}, {}
    for row in commands(intent):
        if 'dependencies' not in row:
            continue
        raw = held[Path(row['dependencies']).name].content.decode().replace('\\\n', '')
        target, separator, words = raw.partition(':')
        require(target == 'otelc-inputs' and separator == ':', 'invalid native unit dependency target')
        paths = [Path(os.path.abspath(Path(row['directory']) / name.replace('$$', '$'))) for name in shlex.split(words)]
        require(len(paths) == len(set(paths)) and set(paths) == discovered[row['unit']],
                'native per-unit compiler inputs differ from caller discovery')
        groups[row['label']] = [expected[str(path)].identity() for path in paths]
        found.update({str(path): expected[str(path)].identity() for path in paths})
    return list(found.values()), groups


@dataclass(frozen=True)
class Build:
    """Accepted build3 products stay tied to their original private file facts."""

    intent: Intent
    files: tuple[inputs.File, ...]

    def file(self, name: str) -> inputs.File:
        """Only independently derived product names can be read."""
        require(name in names(self.intent), 'unknown native unit product')
        return next(item for item in self.files if item.path == self.intent.output / name)

    def manifest(self) -> dict:
        """Return a fresh decoded outer build binding."""
        return strict_json(self.file(native_build.MANIFEST).content)

    def verify(self) -> None:
        """Recheck all original inputs and the complete product denominator."""
        self.intent.verify()
        expected = names(self.intent)
        require(type(self.files) is tuple and len(self.files) == len(expected)
                and {item.path for item in self.files} == {self.intent.output / name for name in expected}
                and native_build.file_set(self.intent.output) == expected, 'native unit build denominator changed')
        for item in self.files:
            item.verify()


def read(intent: Intent) -> Build:
    """Read a build3 response without executing producer-selected paths or commands."""
    require(type(intent) is Intent, 'native build3 requires its per-unit caller intent')
    intent.verify()
    require(native_build.file_set(intent.output) == names(intent), 'unexpected native unit build files')
    held = {name: inputs.capture(intent.output / name, maximum=inputs.MAX_RECORD if name.endswith('.json') else inputs.MAX_FILE,
                                keep=name.endswith(('.json', '.d')) or name == 'bootstrap.cpp')
            for name in sorted(names(intent))}
    require(held['bootstrap.cpp'].content == native_build.BOOTSTRAP.encode(), 'native unit bootstrap recipe differs')
    native_build.plugin(intent, held)
    native_build.gate(intent, held)
    discovered, groups = compiler_inputs(intent, held)
    policy, recipe = intent.policy(), intent.recipe()
    files = {str(path) for group in intent.unit_dependencies for path in group} | set(recipe['assets']) | {unit['source'] for unit in recipe['units']}
    expected = {'schema_version': 2, 'kind': 'otelc.native-build', 'profile': UNIT_PROFILE, 'language': intent.language,
        'root': str(intent.project), 'policy': policy, 'policy_sha256': digest(policy),
        'selection_sha256': digest({key: policy[key] for key in ('sources', 'functions')}), 'inputs': discovered,
        'sdk_library': intent.sdk.library.identity(), 'products': [held[name].identity() for name in ('plain', 'instrumented')],
        'commands': commands(intent), 'source_complete': False, 'recipe': recipe,
        'files': [item.gate_identity() for item in intent.dependencies if str(item.path) in files],
        'artifacts': [held[name].gate_identity() for name in sorted(artifacts(intent))],
        'tools': {'objcopy': intent.objcopy.gate_identity()} if intent.objcopy is not None else {}, 'dependencies': groups}
    actual = fields(strict_json(held['native-build.json'].content), set(expected), 'native unit build')
    # Input/file arrays are sets; command, recipe and per-unit dependency order is semantic.
    for key in ('inputs', 'files'):
        require(type(actual[key]) is list and all(type(item) is dict and type(item.get('path')) is str for item in actual[key]),
                'invalid native unit ' + key)
        actual[key] = sorted(actual[key], key=lambda item: item['path'])
        expected[key] = sorted(expected[key], key=lambda item: item['path'])
    require(same(actual, expected), 'native unit response differs from caller-frozen context or command recipe')
    database = [{'directory': row['directory'], 'file': row['source'], 'arguments': row['arguments']}
                for row in commands(intent) if 'source' in row]
    require(same(strict_json(held['compile_commands.json'].content), database), 'native unit compiler database differs')
    outer = {'schema_version': 3, 'kind': 'otelc.native.source-build', 'profile': PROFILE,
        **{key: held[name].gate_identity() for key, name in
           (('native', 'native-build.json'), ('plugin', 'plugin/llvm-plugin.json'), ('gate', 'gate/gate.json'))},
        'sdk': intent.sdk.record.file.gate_identity(), 'source_complete': False}
    require(same(strict_json(held[native_build.MANIFEST].content), outer), 'native unit outer build binding differs')
    result = Build(intent, tuple(held.values()))
    result.verify()
    return result
