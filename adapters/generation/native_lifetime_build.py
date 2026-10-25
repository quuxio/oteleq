"""Independent build4/build5 recipes, semantic bindings and retained products."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

import native_build
import native_inputs as inputs
import native_lifetime_inventory as inventory
import native_unit_build as units
from native_protocol import PROFILE, digest, encoded, fields, require, same
from native_sdk import SDK
from otelc_capture import strict_json

PROFILES = {'object': 'llvm22-native-object-units-v1', 'resource': 'llvm22-native-resource-units-v1'}
PLUGIN_PROFILES = {'object': 'llvm22-itanium-objects-v1', 'resource': 'llvm22-c-resources-v1'}
SYMBOL_FLAGS = ('--defined-only', '--extern-only', '--format=just-symbols')
INTERPOSED = {prefix + name for prefix in ('', '_') for name in ('malloc', 'calloc', 'realloc', 'free')}


def policy(value: dict, kind: str) -> None:
    """Lifetimes are explicit; common selectors and finite budgets stay frozen."""
    inventory.paths(kind)
    require(type(value) is dict and type(value.get('lifetimes')) is dict,
            'missing native lifetime policy')
    life = fields(value['lifetimes'], {'enabled', 'include', 'exclude', 'max_live', 'release_methods'},
                  'native lifetime policy')
    require(life['enabled'] is True and type(life['max_live']) is int and 1 <= life['max_live'] <= 1000000,
            'unsupported native lifetime limits')
    for section in ('sources', 'functions', 'lifetimes'):
        require(type(value.get(section)) is dict, 'missing native lifetime selection')
        for key in ('include', 'exclude'):
            patterns = value[section].get(key)
            require(type(patterns) is list and len(patterns) <= 1024 and all(
                type(item) is str and 0 < len(item) <= 4096 and '\0' not in item for item in patterns),
                'invalid native lifetime selectors')
    require(type(life['release_methods']) is list and all(type(item) is str for item in life['release_methods']),
            'invalid native lifetime release-method configuration')


@dataclass(frozen=True)
class Intent:
    """Caller context and complete semantic expectations exist before SDK builds."""

    base: units.Intent
    kind: str
    tool: inventory.Tool
    semantics: tuple[tuple[str, str], ...]
    target: str | None
    pass_inputs: tuple[inputs.File, ...]
    nm: inputs.File | None

    @property
    def version(self) -> int:
        """Object and resource source-build versions never share a fallback."""
        return 4 if self.kind == 'object' else 5

    def selected_units(self) -> list[dict]:
        """Neutral drivers acquire neither object nor resource probes."""
        return [unit for unit in self.base.recipe()['units'] if unit['role'] == 'application'
                and (self.kind == 'resource' or unit['language'] == 'cpp')]

    def verify(self) -> None:
        """Keep every original SDK, caller, helper, pass and tool identity."""
        self.base.verify(); self.tool.verify(); policy(self.base.policy(), self.kind)
        for held in self.pass_inputs:
            held.verify()
        if self.nm is not None:
            self.nm.verify()


def freeze(sdk: SDK, project: Path, output: Path, kind: str, recipe: dict,
           dependencies: tuple[tuple[Path, ...], ...], common_policy: dict,
           semantics: tuple[tuple[str, dict], ...], tool: inventory.Tool, *,
           target: str | None = None, aliases: tuple[Path, ...] = ()) -> Intent:
    """A producer response cannot choose contexts, semantic facts, libraries or tools."""
    policy(common_policy, kind)
    require(type(tool) is inventory.Tool and tool.sdk is sdk and tool.kind == kind,
            'semantic tool does not bind the selected SDK/profile')
    require(sdk.source_profile in (('object-v1', 'resource-v1') if kind == 'object' else ('resource-v1',)),
            'native lifetime SDK source catalogue is unavailable')
    language = 'cpp' if kind == 'object' else 'c'
    base = units.freeze_context(sdk, project, output, language, recipe, dependencies, common_policy, aliases=aliases)
    selected = [unit for unit in recipe['units'] if unit['role'] == 'application']
    require(kind != 'resource' or all(unit['language'] == 'c' for unit in selected),
            'C resources require C application units')
    selected = [unit for unit in selected if kind == 'resource' or unit['language'] == 'cpp']
    require(bool(selected) and type(semantics) is tuple and len(semantics) == len(selected)
            and all(type(row) is tuple and len(row) == 2 and type(row[0]) is str for row in semantics)
            and {row[0] for row in semantics} == {unit['id'] for unit in selected},
            'incomplete caller semantic unit denominator')
    require((target is None if kind == 'resource' else type(target) is str and
             re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', target) is not None and
             ('-apple-' in target or '-linux-' in target)), 'unsupported native semantic target')
    frozen = tuple((name, encoded(inventory.document(value, kind))) for name, value in semantics)
    require(sum(len(raw.encode()) for _, raw in frozen) <= inventory.MAX_AST,
            'complete semantic input exceeds its byte budget')
    for _, raw in frozen:
        inventory.catalogue(strict_json(raw), kind, common_policy, project)
    prefix = 'Object' if kind == 'object' else 'Resource'
    stem = 'object' if kind == 'object' else 'resource'
    result = Intent(base, kind, tool, frozen, target, tuple(inputs.capture(sdk.root / name) for name in (
        'native/llvm/' + prefix + 'Pass.cpp', 'native/llvm/' + stem + '_pass.h',
        'native/llvm/' + stem + '_abi.h')), inputs.capture(sdk.toolchain.directory / 'llvm-nm')
        if kind == 'resource' else None)
    result.verify()
    return result


def commands(intent: Intent) -> list[dict]:
    """Reconstruct per-unit environments, both symbol-check lanes and fixed links."""
    base, result = intent.base, []
    for step in units.commands(base):
        if 'dependencies' in step:
            unit = next(unit for unit in base.recipe()['units'] if unit['id'] == step['unit'])
            if step['lane'] == 'instrumented' and unit['role'] == 'application':
                _tool_dir, unit_dir = inventory.paths(intent.kind)
                directory = base.output / unit_dir / unit['id']
                if intent.kind == 'object':
                    step['environment'] = ({'OTELC_OBJECT_C_UNIT': '1'} if unit['language'] == 'c' else
                        {'OTELC_OBJECT_INVENTORY': str(directory / 'native-lifetimes.json')})
                else:
                    step['environment'] = {'OTELC_RESOURCE_INVENTORY': str(directory / 'native-resources.json'),
                                          'OTELC_RESOURCE_RESOLUTION': str(directory / 'resolution.json')}
            result.append(step)
            # Main rename precedes symbol inspection, so add the check after its
            # independently reconstructed rename operation below when present.
            if intent.kind == 'resource' and not unit['rename_main']:
                result.append(symbol_command(intent, step['label'], unit['id'], step['lane']))
        else:
            result.append(step)
            if intent.kind == 'resource' and step['label'].endswith('-rename'):
                label = step['label'][:-7]
                lane, unit_id = label.split('-', 1)
                result.append(symbol_command(intent, label, unit_id, lane))
    return result


def symbol_command(intent: Intent, label: str, unit: str, lane: str) -> dict:
    """Every linked original/driver object retains the same allocator-binding guard."""
    output = intent.base.output
    return units.operation(label + '-resource-symbols', str(output), [str(intent.nm.path), *SYMBOL_FLAGS,
        str(output / (label + '.o'))], output / (label + '-resource-symbols.stdout'),
        symbol_check=True, unit=unit, lane=lane)


def artifacts(intent: Intent) -> set[str]:
    """Derive every helper, semantic, command-channel and object product name."""
    tool, directory = inventory.paths(intent.kind)
    result = {tool + '/' + name for name in inventory.TOOL_FILES}
    result.update(directory + '/' + unit['id'] + '/' + name
                  for unit in intent.selected_units() for name in inventory.UNIT_FILES[intent.kind])
    result.update(('bootstrap.cpp', 'compile_commands.json'))
    for step in commands(intent):
        result.update((Path(step['output']).name, step['label'] + '.stdout', step['label'] + '.stderr'))
        if 'dependencies' in step:
            result.add(Path(step['dependencies']).name)
    return result


def names(intent: Intent) -> set[str]:
    """Function-only build3 and lifetime products have separate closed catalogues."""
    tool_directory = inventory.paths(intent.kind)[0]
    auxiliary = {tool_directory + '/' + name for name in inventory.debug_names(
        intent.base.sdk.platform, intent.tool.host_target)}
    return units.names(intent.base) | artifacts(intent) | auxiliary | {'plugin/functions.o',
        'plugin/' + ('objects.o' if intent.kind == 'object' else 'resources.o')}


def file_set(root: Path, expected: set[str]) -> set[str]:
    """Inventory nested ordinary products without following links or foreign paths."""
    require(root == root.resolve(strict=True) and root.is_dir(), 'native lifetime output changed')
    result = set()
    directories = {parent.as_posix() for name in expected for parent in Path(name).parents
                   if parent != Path('.')}
    seen_directories = set()
    pending = [root]
    while pending:
        directory = pending.pop()
        for child in directory.iterdir():
            require(not child.is_symlink(), 'native lifetime output contains a link')
            if child.is_dir():
                relative = child.relative_to(root).as_posix()
                require(relative in directories, 'native lifetime output contains a foreign directory')
                seen_directories.add(relative)
                require(len(result) + len(seen_directories) < 100000, 'native lifetime output exceeds file budget')
                pending.append(child)
            else:
                require(child.is_file(), 'native lifetime output contains a special file')
                relative = child.relative_to(root).as_posix()
                require(relative in expected, 'native lifetime output contains a foreign file')
                result.add(relative)
    return result


def plugin(intent: Intent, held: dict[str, inputs.File]) -> None:
    """Bind the two compiled pass objects, linked plugin and fixed compiler database."""
    base, tools = intent.base, intent.base.sdk.toolchain
    prefix = 'OBJECT' if intent.kind == 'object' else 'RESOURCE'
    common = [str(tools.directory / 'clang++'), '-fPIC', '-O2', *tools.cxxflags,
              '-DOTELC_FUNCTION_REGISTRY_V1=1', '-DOTELC_SOURCE_PROFILE_V1=1',
              '-DOTELC_' + prefix + '_WITH_FUNCTIONS_V1=1']
    outputs = ['plugin/functions.o', 'plugin/' + ('objects.o' if intent.kind == 'object' else 'resources.o')]
    commands_ = [[*common, '-c', str(source.path), '-o', str(base.output / name)]
                 for source, name in zip((base.plugin_source, intent.pass_inputs[0]), outputs)]
    database = [{'directory': str(base.sdk.root), 'file': str(source.path), 'arguments': command}
                for source, command in zip((base.plugin_source, intent.pass_inputs[0]), commands_)]
    library = 'plugin/libotelc_llvm.' + native_build.suffix(base)
    commands_.append([common[0], '-shared', *[str(base.output / name) for name in outputs],
                      *tools.ldflags, '-o', str(base.output / library)])
    expected = {'schema_version': 1, 'kind': 'otelc.llvm-plugin', 'profile': PLUGIN_PROFILES[intent.kind],
        'probe_abi': 'otelc.function.v2', 'source': base.plugin_source.tool_identity(),
        'headers': [next(item for item in base.sdk.sources if item.path ==
                        base.sdk.root / 'native/llvm/function_abi.h').tool_identity()],
        'toolchain': tools.metadata(), 'plugin': held[library].tool_identity(),
        'coverage': False, 'source_complete': False,
        intent.kind + '_inputs': [item.tool_identity() for item in intent.pass_inputs],
        intent.kind + '_probe_abi': 'otelc.' + intent.kind + '.v1',
        'evidence': {name: held['plugin/' + name].tool_identity()
                     for name in ('command.json', 'compile_commands.json', 'build.stdout', 'build.stderr')}}
    require(same(strict_json(held['plugin/llvm-plugin.json'].content), expected)
            and same(strict_json(held['plugin/command.json'].content), commands_)
            and same(strict_json(held['plugin/compile_commands.json'].content), database),
            'native lifetime plugin source, ABI or compiler recipe changed')


def read_inventory(intent: Intent, held: dict[str, inputs.File], tool: dict) -> dict:
    """Join all per-unit raw frontend facts and compiler channels to frozen intent."""
    base, bindings = intent.base, {}
    tool_directory, directory = inventory.paths(intent.kind)
    frozen = dict(intent.semantics)
    dependency_groups = {unit['id']: group for unit, group in zip(base.recipe()['units'], base.unit_dependencies)}
    held_dependencies = {item.path: item for item in base.dependencies}
    total_bytes = 0
    for unit in intent.selected_units():
        prefix = directory + '/' + unit['id'] + '/'
        name = 'native-lifetimes.json' if intent.kind == 'object' else 'native-resources.json'
        semantic_name = '0-semantics.json.gz' if intent.kind == 'object' else 'semantics.json.gz'
        compressed = held[prefix + semantic_name]
        raw = inventory.semantic_bytes(compressed); total_bytes += len(raw)
        require(total_bytes <= inventory.MAX_AST, 'complete retained semantics exceed byte budget')
        actual_semantics = inventory.document(strict_json(raw), intent.kind)
        require(inventory.equivalent_facts(actual_semantics, strict_json(frozen[unit['id']])),
                'SDK semantic facts differ from caller-frozen frontend observations')
        selected = inventory.catalogue(actual_semantics, intent.kind, base.policy(), base.project)
        common = [str(base.sdk.toolchain.directory / ('clang++' if intent.kind == 'object' else 'clang'))]
        if intent.kind == 'object':
            common.append('--target=' + intent.target)
        common += [*unit['flags'], '-g']
        if unit['overlay'] is not None:
            common += ['-ivfsoverlay', unit['overlay']]
        folder = base.output / directory / unit['id']
        dep = '0.d' if intent.kind == 'object' else 'source.d'
        query = [*common, '-M', '-MT', 'otelc-inputs', '-MF', str(folder / dep), unit['source']]
        semantic_command = [str(base.output / tool_directory / 'lifetimes'), str(base.project), unit['source'],
                            '--compile-directory', unit['directory'], *common]
        dep_rows = inventory.dependencies(held[prefix + dep].content, Path(unit['directory']),
            tuple(held_dependencies[path] for path in dependency_groups[unit['id']]), base.aliases)
        context = {key: unit[key] for key in ('directory', 'flags', 'overlay')} | {'assets': base.recipe()['assets']}
        expected = {'schema_version': 2 if intent.kind == 'object' else 1,
            'kind': 'otelc.native.lifetime-inventory' if intent.kind == 'object' else 'otelc.native.c-resource-inventory',
            'profile': 'clang22-cxx-context-v1' if intent.kind == 'object' else 'clang22-c-allocation-v1',
            'root': str(base.project), 'tool': tool, 'policy_sha256': digest(base.policy()),
            'inputs': dep_rows, 'commands': [query, semantic_command], 'source_complete': False,
            'compile_context': context,
            'context_inputs': [held_dependencies[Path(path)].gate_identity() for path in base.recipe()['assets']]}
        semantic_record = {'semantic': compressed.gate_identity(), 'semantic_bytes': len(raw),
                           'semantic_sha256': hashlib.sha256(raw).hexdigest()}
        if intent.kind == 'object':
            expected.update(target=intent.target, translation_units=[{'source': unit['source'],
                            **selected, **semantic_record}])
        else:
            expected.update(source=unit['source'], **selected, **semantic_record)
            inventory.resolution(strict_json(held[prefix + 'resolution.json'].content), expected,
                                 Path(unit['directory']))
        require(same(strict_json(held[prefix + name].content), expected),
                'native lifetime inventory context, selection or compiler channels changed')
        bindings[unit['id']] = held[prefix + name].gate_identity()
    return {intent.kind + '_tool': held[tool_directory + '/native-lifetime-tool.json'].gate_identity(),
            intent.kind + '_inventories': bindings}


@dataclass(frozen=True)
class Build:
    """A lifetime build retains original facts for its complete product tree."""

    intent: Intent
    files: tuple[inputs.File, ...]

    def file(self, name: str) -> inputs.File:
        """Only caller-derived product names are available to downstream preparation."""
        require(name in names(self.intent), 'unknown native lifetime product')
        return next(held for held in self.files if held.path == self.intent.base.output / name)

    def manifest(self) -> dict:
        """Return a fresh view of the accepted source-build binding."""
        return strict_json(self.file(native_build.MANIFEST).content)

    def verify(self) -> None:
        """Recheck original caller, helper and complete ordinary product identities."""
        self.intent.verify()
        expected = names(self.intent)
        require(type(self.files) is tuple and len(self.files) == len(expected)
                and {item.path for item in self.files} == {self.intent.base.output / name for name in expected}
                and file_set(self.intent.base.output, expected) == expected, 'native lifetime product denominator changed')
        for held in self.files:
            held.verify()


def read(intent: Intent) -> Build:
    """Producer records confirm frozen expectations and never supply executable paths."""
    require(type(intent) is Intent, 'native lifetimes require their separate caller intent')
    intent.verify(); base = intent.base
    expected_names = names(intent)
    require(file_set(base.output, expected_names) == expected_names, 'native lifetime output denominator differs')
    held = {name: inputs.capture(base.output / name, maximum=inventory.MAX_AST if name.endswith(('.gz', '-resource-symbols.stdout'))
        else inputs.MAX_RECORD if name.endswith('.json') else inputs.MAX_FILE,
        keep=name.endswith(('.json', '.d', '.gz', '-resource-symbols.stdout', '/lifetimes')) or name == 'bootstrap.cpp')
            for name in sorted(expected_names)}
    require(held['bootstrap.cpp'].content == native_build.BOOTSTRAP.encode(), 'native lifetime bootstrap differs')
    plugin(intent, held); native_build.gate(base, held)
    tool = inventory.read_tool(intent.tool, base.output, held)
    semantic_bindings = read_inventory(intent, held, tool)
    discovered, groups = units.compiler_inputs(base, held)
    steps, recipe, common_policy = commands(intent), base.recipe(), base.policy()
    for step in steps:
        if step.get('symbol_check'):
            raw = held[Path(step['output']).name].content
            # Symbol stdout is a fixed compiler channel, never a selected path.
            require(len(raw) <= inventory.MAX_AST and b'\0' not in raw and
                    not INTERPOSED.intersection(raw.decode('utf-8').splitlines()),
                    'custom or interposed C allocation/free definition')
    selected = {key: common_policy[key] for key in ('sources', 'functions')}
    selected['lifetimes'] = {key: common_policy['lifetimes'][key] for key in ('enabled', 'include', 'exclude')}
    tools = {'objcopy': base.objcopy.gate_identity()} if base.objcopy is not None else {}
    if intent.nm is not None:
        tools['nm'] = intent.nm.gate_identity()
    expected = {'schema_version': intent.version - 1, 'kind': 'otelc.native-build', 'profile': PROFILES[intent.kind],
        'language': base.language, 'root': str(base.project), 'policy': common_policy, 'policy_sha256': digest(common_policy),
        'selection_sha256': digest(selected), 'inputs': discovered, 'sdk_library': base.sdk.library.identity(),
        'products': [held[name].identity() for name in ('plain', 'instrumented')], 'commands': steps,
        'source_complete': False, 'recipe': recipe,
        'files': [item.gate_identity() for item in base.dependencies],
        'artifacts': [held[name].gate_identity() for name in sorted(artifacts(intent))],
        'tools': tools, 'dependencies': groups, **semantic_bindings}
    actual = fields(strict_json(held['native-build.json'].content), set(expected), 'native lifetime build')
    for key in ('inputs', 'files'):
        require(type(actual[key]) is list and all(type(row) is dict and type(row.get('path')) is str
                for row in actual[key]), 'invalid native lifetime input set')
        expected[key] = sorted(expected[key], key=lambda row: row['path'])
        actual[key] = sorted(actual[key], key=lambda row: row['path'])
    require(same(actual, expected), 'native lifetime build differs from fixed caller context or compiler recipe')
    database = [{'directory': row['directory'], 'file': row['source'], 'arguments': row['arguments']}
                for row in steps if 'source' in row]
    require(same(strict_json(held['compile_commands.json'].content), database), 'native lifetime compiler database differs')
    outer = {'schema_version': intent.version, 'kind': 'otelc.native.source-build', 'profile': PROFILE,
        **{key: held[name].gate_identity() for key, name in (
            ('native', 'native-build.json'), ('plugin', 'plugin/llvm-plugin.json'), ('gate', 'gate/gate.json'))},
        'sdk': base.sdk.record.file.gate_identity(), 'source_complete': False}
    require(same(strict_json(held[native_build.MANIFEST].content), outer), 'native lifetime source-build binding differs')
    result = Build(intent, tuple(held.values())); result.verify()
    return result
