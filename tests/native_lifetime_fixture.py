"""Literal nonexecuted build4/build5 records, independent of consumer renderers."""

import copy
import gzip
import hashlib
import json
from pathlib import Path
import shlex

import native_lifetime_build as reader
import native_lifetime_inventory as semantic
import native_provider_fixture as fixed
import native_sdk
import native_unit_fixture as original

TOOL_FILES = ('tool.d', 'tool-dependencies.json', 'tool-dependencies.stderr',
              'tool-build.json', 'tool-build.stderr', 'tool-dependencies-after.json',
              'tool-dependencies-after.stderr', 'native-lifetime-tool.json',
              'compile_commands.json', 'lifetimes')
OBJECT_FILES = ('0.d', '0-dependencies.json', '0-dependencies.stderr', '0-semantics.stderr',
                '0-dependencies-after.json', '0-dependencies-after.stderr',
                '0-semantics.json.gz', 'native-lifetimes.json')
RESOURCE_FILES = ('source.d', 'dependencies.json', 'dependencies.stderr', 'semantics.stderr',
                  'dependencies-after.json', 'dependencies-after.stderr',
                  'semantics.json.gz', 'native-resources.json', 'resolution.json')


def location(source: Path, line: int = 3) -> dict:
    return {'file': str(source), 'offset': 10, 'line': line, 'column': 2,
            'debug_file': source.name, 'debug_line': line, 'debug_column': 2}


def facts(source: Path, kind: str, *, empty: bool = False) -> dict:
    if kind == 'object':
        value = {'schema_version': 1, 'kind': 'otelc.clang.lifetime-semantics',
                 'types': [], 'constructions': [], 'variables': []}
        if not empty:
            value['types'] = [{'usr': 'c:@S@Item', 'name': 'Item', 'location': location(source, 1),
                'dependent': False, 'polymorphic': False, 'trivial_default_constructor': False,
                'trivial_destructor': False, 'methods': [], 'bases': []}]
            site = {'type_usr': 'c:@S@Item', 'location': location(source),
                    'caller': '_Z8workloadi', 'caller_base': '_Z8workloadi'}
            value['constructions'] = [{**site, 'kind': 'CXXConstructExpr', 'construction_kind': 'complete',
                'constructor_symbol': '_ZN4ItemC1Ei', 'constructor_base_symbol': '_ZN4ItemC2Ei',
                'constructor_signature': 'void (int)', 'trivial': False, 'elidable': False, 'array_type': None}]
            value['variables'] = [{**site, 'kind': 'VarDecl', 'variable': 'item', 'nrvo': False,
                'initializer_kind': 'CXXConstructExpr', 'storage_class': 0, 'parameter': False,
                'local': True, 'global_storage': False, 'static_local': False, 'thread_local': False}]
        return value
    value = {'schema_version': 1, 'kind': 'otelc.clang.c-resource-semantics',
             'types': [], 'allocations': [], 'releases': [], 'unsupported': []}
    if not empty:
        value['types'] = [{'usr': 'c:@S@Item', 'name': 'Item', 'location': location(source, 1), 'complete': True}]
        value['allocations'] = [{'callee': 'malloc', 'caller': 'workload', 'location': location(source),
            'standard': True, 'observer': False, 'arguments': 1, 'signature': 'void *(unsigned long)',
            'type_usr': 'c:@S@Item'}]
        value['releases'] = [{'callee': 'free', 'caller': 'workload', 'location': location(source, 4),
            'standard': True, 'observer': False, 'arguments': 1, 'signature': 'void (void *)'}]
    return value


def build(root: Path, *, kind: str = 'object', tooling: bool = True):
    old = original.build(root, tooling=tooling)
    output, sdk = old.output, old.sdk
    sdk_record = sdk.record.value()
    for name in ('object_abi.h', 'resource_abi.h'):
        path = sdk.root / 'native/llvm' / name
        path.write_text('literal ABI ' + name)
        sdk_record['sources'].append(fixed.identity(path))
    fixed.write(sdk.record.file.path, sdk_record)
    sdk = native_sdk.capture(sdk.root, sdk.directory, sdk.toolchain,
        cmake=sdk.cmake.path, ninja=sdk.ninja.path, platform='linux', source_profile='resource-v1')
    recipe = old.recipe(); groups = old.unit_dependencies
    if kind == 'resource':
        before = Path(recipe['units'][0]['source']); after = before.with_suffix('.c'); before.rename(after)
        recipe['units'][0].update(source=str(after), language='c')
        recipe['units'][0]['flags'][0] = '-std=c11'
        groups = tuple(tuple(after if path == before else path for path in group) for group in groups)
        recipe['link']['language'] = 'c'
        if tooling:
            path = Path(recipe['units'][0]['overlay']); value = json.loads(path.read_text())
            value['roots'][0]['name'] = str(after); fixed.write(path, value)
    stem = 'object' if kind == 'object' else 'resource'
    prefix = 'Object' if kind == 'object' else 'Resource'
    for name in (prefix + 'Pass.cpp', stem + '_pass.h'):
        (sdk.root / 'native/llvm' / name).write_text('literal pass source ' + name)
    if kind == 'resource':
        (sdk.toolchain.directory / 'llvm-nm').write_text('literal symbol tool; never executed')
    source = sdk.root / 'native/clang' / ('Lifetimes.cpp' if kind == 'object' else 'Resources.cpp')
    source.parent.mkdir(); source.write_text('literal semantic source; never compiled')
    library_directory = sdk.toolchain.directory.parent / 'lib'; library_directory.mkdir()
    libraries = tuple(library_directory / name for name in ('libclang-cpp.so', 'libLLVM.so'))
    for path in libraries: path.write_bytes(b'literal shared library; never loaded')
    helper_dependencies = (source, sdk.root / 'adapters/native/include/runtime.h')
    tool = semantic.freeze_tool(sdk, kind, helper_dependencies, library_directory, libraries)
    policy = copy.deepcopy(fixed.POLICY)
    policy['lifetimes'] = {'enabled': True, 'include': ['Item'], 'exclude': [],
                           'max_live': 4096, 'release_methods': ['close']}
    raw = tuple((unit['id'], facts(Path(unit['source']), kind, empty=unit['id'] != 'work'))
                for unit in recipe['units'] if unit['role'] == 'application'
                and (kind == 'resource' or unit['language'] == 'cpp'))
    staging = root / 'lifetime-staging'; output.rename(staging)
    intent = reader.freeze(sdk, old.project, output, kind, recipe, groups, policy, raw, tool,
                           target='aarch64-unknown-linux-gnu' if kind == 'object' else None)
    staging.rename(output)
    write_plugin(intent)
    steps = original.commands(recipe, output, sdk)
    expanded = []
    for step in steps:
        if 'dependencies' in step:
            unit = next(unit for unit in recipe['units'] if unit['id'] == step['unit'])
            if step['lane'] == 'instrumented' and unit['role'] == 'application':
                if kind == 'object':
                    step['environment'] = ({'OTELC_OBJECT_C_UNIT': '1'} if unit['language'] == 'c' else
                        {'OTELC_OBJECT_INVENTORY': str(output / 'lifetimes' / unit['id'] / 'native-lifetimes.json')})
                else:
                    step['environment'] = {
                        'OTELC_RESOURCE_INVENTORY': str(output / 'resources' / unit['id'] / 'native-resources.json'),
                        'OTELC_RESOURCE_RESOLUTION': str(output / 'resources' / unit['id'] / 'resolution.json')}
        expanded.append(step)
        if kind == 'resource' and ('dependencies' in step and not unit['rename_main']
                                   or step['label'].endswith('-rename')):
            label = step['label'][:-7] if step['label'].endswith('-rename') else step['label']
            lane, identifier = label.split('-', 1)
            expanded.append({'label': label + '-resource-symbols', 'directory': str(output),
                'arguments': [str(sdk.toolchain.directory / 'llvm-nm'), '--defined-only', '--extern-only',
                              '--format=just-symbols', str(output / (label + '.o'))],
                'output': str(output / (label + '-resource-symbols.stdout')), 'symbol_check': True,
                'unit': identifier, 'lane': lane})
    steps = expanded
    for step in steps:
        Path(step['output']).write_text('literal product ' + step['label'])
        for channel in ('stdout', 'stderr'):
            (output / (step['label'] + '.' + channel)).write_bytes(b'')
        if 'dependencies' in step:
            index = next(i for i, unit in enumerate(recipe['units']) if unit['id'] == step['unit'])
            Path(step['dependencies']).write_text('otelc-inputs: ' + shlex.join(map(str, groups[index])) + '\n')
    fixed.write(output / 'compile_commands.json', [{'directory': row['directory'], 'file': row['source'],
                'arguments': row['arguments']} for row in steps if 'source' in row])
    tool_record = write_tool(intent)
    semantic_records, extra_artifacts = write_inventories(intent, raw, tool_record)
    artifacts = {output / 'bootstrap.cpp', output / 'compile_commands.json', *extra_artifacts}
    for row in steps:
        artifacts.update((Path(row['output']), output / (row['label'] + '.stdout'), output / (row['label'] + '.stderr')))
        if 'dependencies' in row: artifacts.add(Path(row['dependencies']))
    dependency_records = {lane + '-' + unit['id']: [fixed.identity(path) for path in group]
        for lane in ('plain', 'instrumented') for unit, group in zip(recipe['units'], groups)}
    selected = {key: policy[key] for key in ('sources', 'functions')}
    selected['lifetimes'] = {key: policy['lifetimes'][key] for key in ('enabled', 'include', 'exclude')}
    tools = {'objcopy': fixed.identity(sdk.toolchain.directory / 'llvm-objcopy', gate=True)} if tooling else {}
    if kind == 'resource': tools['nm'] = fixed.identity(sdk.toolchain.directory / 'llvm-nm', gate=True)
    all_inputs = {path for group in groups for path in group}
    fixed.write(output / 'native-build.json', {'schema_version': 3 if kind == 'object' else 4,
        'kind': 'otelc.native-build', 'profile': 'llvm22-native-' + ('object' if kind == 'object' else 'resource') + '-units-v1',
        'language': 'cpp' if kind == 'object' else 'c', 'root': str(old.project), 'policy': policy,
        'policy_sha256': fixed.digest(policy), 'selection_sha256': fixed.digest(selected),
        'inputs': [fixed.identity(path) for path in sorted(all_inputs)], 'sdk_library': fixed.identity(sdk.library.path),
        'products': [fixed.identity(output / lane) for lane in ('plain', 'instrumented')], 'commands': steps,
        'recipe': recipe, 'files': [fixed.identity(path, gate=True) for path in sorted(all_inputs | set(map(Path, recipe['assets'])))],
        'tools': tools, 'artifacts': [fixed.identity(path, gate=True) for path in sorted(artifacts)],
        'dependencies': dependency_records, 'source_complete': False, **semantic_records})
    rebind(intent)
    return intent


def write_plugin(intent) -> None:
    sdk, output, kind = intent.base.sdk, intent.base.output, intent.kind
    prefix = 'OBJECT' if kind == 'object' else 'RESOURCE'
    common = [str(sdk.toolchain.directory / 'clang++'), '-fPIC', '-O2', *sdk.toolchain.cxxflags,
              '-DOTELC_FUNCTION_REGISTRY_V1=1', '-DOTELC_SOURCE_PROFILE_V1=1',
              '-DOTELC_' + prefix + '_WITH_FUNCTIONS_V1=1']
    objects = [output / 'plugin/functions.o', output / ('plugin/objects.o' if kind == 'object' else 'plugin/resources.o')]
    sources = [sdk.root / 'native/llvm/OtelcPass.cpp', sdk.root / ('native/llvm/ObjectPass.cpp' if kind == 'object' else 'native/llvm/ResourcePass.cpp')]
    for path in objects: path.write_text('literal pass object')
    commands = [[*common, '-c', str(source), '-o', str(path)] for source, path in zip(sources, objects)]
    database = [{'directory': str(sdk.root), 'file': str(source), 'arguments': command} for source, command in zip(sources, commands)]
    library = output / 'plugin/libotelc_llvm.so'
    commands.append([common[0], '-shared', *map(str, objects), *sdk.toolchain.ldflags, '-o', str(library)])
    fixed.write(output / 'plugin/command.json', commands); fixed.write(output / 'plugin/compile_commands.json', database)
    extras = [sdk.root / 'native/llvm' / name for name in (
        ('ObjectPass.cpp', 'object_pass.h', 'object_abi.h') if kind == 'object' else
        ('ResourcePass.cpp', 'resource_pass.h', 'resource_abi.h'))]
    fixed.write(output / 'plugin/llvm-plugin.json', {'schema_version': 1, 'kind': 'otelc.llvm-plugin',
        'profile': 'llvm22-itanium-objects-v1' if kind == 'object' else 'llvm22-c-resources-v1',
        'source': fixed.identity(sources[0], tool=True), 'headers': [fixed.identity(sdk.root / 'native/llvm/function_abi.h', tool=True)],
        'toolchain': sdk.toolchain.metadata(), 'plugin': fixed.identity(library, tool=True), 'coverage': False,
        'probe_abi': 'otelc.function.v2', 'source_complete': False,
        kind + '_inputs': [fixed.identity(path, tool=True) for path in extras],
        kind + '_probe_abi': 'otelc.' + kind + '.v1', 'evidence': {name: fixed.identity(output / 'plugin' / name, tool=True)
            for name in ('command.json', 'compile_commands.json', 'build.stdout', 'build.stderr')}})


def write_tool(intent) -> dict:
    sdk, output, kind = intent.base.sdk, intent.base.output, intent.kind
    folder = output / ('lifetime-tool' if kind == 'object' else 'resource-tool'); folder.mkdir()
    for name in TOOL_FILES: (folder / name).write_bytes(b'')
    (folder / 'lifetimes').write_text('literal semantic tool; never executed')
    (folder / 'tool.d').write_text('otelc-inputs: ' + shlex.join(str(path.path) for path in intent.tool.dependencies) + '\n')
    common = [str(sdk.toolchain.directory / 'clang++'), *sdk.toolchain.cxxflags, '-std=c++17', '-fexceptions', '-O1', '-g']
    command = [*common, str(intent.tool.source.path), '-L' + str(intent.tool.library_directory),
        '-Wl,-rpath,' + str(intent.tool.library_directory), '-lclang-cpp', '-lLLVM', '-o', str(folder / 'lifetimes')]
    value = {'schema_version': 1 if kind == 'object' else 2, 'kind': 'otelc.native.lifetime-tool',
        'toolchain': sdk.toolchain.metadata(), 'source': fixed.identity(intent.tool.source.path, gate=True),
        'libraries': [fixed.identity(path.path, gate=True) for path in intent.tool.libraries],
        'inputs': [fixed.identity(path.path, gate=True) for path in intent.tool.dependencies],
        'product': fixed.identity(folder / 'lifetimes', gate=True), 'command': command, 'coverage': False}
    if kind == 'resource': value['semantic_profile'] = 'clang22-c-allocation-v1'
    fixed.write(folder / 'native-lifetime-tool.json', value)
    fixed.write(folder / 'compile_commands.json', [{'directory': str(sdk.root), 'file': str(intent.tool.source.path), 'arguments': command}])
    return value


def write_inventories(intent, raw: tuple, tool_record: dict) -> tuple[dict, set]:
    base, kind, contents = intent.base, intent.kind, dict(raw)
    object_mode = kind == 'object'; root = base.output / ('lifetimes' if object_mode else 'resources'); root.mkdir()
    artifacts = {base.output / ('lifetime-tool' if object_mode else 'resource-tool') / name for name in TOOL_FILES}
    bindings = {}
    for unit in base.recipe()['units']:
        if unit['id'] not in contents: continue
        folder = root / unit['id']; folder.mkdir()
        for name in OBJECT_FILES if object_mode else RESOURCE_FILES: (folder / name).write_bytes(b'')
        source = contents[unit['id']]; selected = {'types': source['types']}
        for category in ('constructions', 'variables') if object_mode else ('allocations', 'releases'):
            selected[category] = [{**row, **({'type': 'Item'} if category != 'releases' else {})} for row in source[category]]
        if object_mode: selected['unresolved'] = []
        depfile = folder / ('0.d' if object_mode else 'source.d')
        group = base.unit_dependencies[next(i for i, row in enumerate(base.recipe()['units']) if row['id'] == unit['id'])]
        depfile.write_text('otelc-inputs: ' + shlex.join(map(str, group)) + '\n')
        data = (json.dumps(source, sort_keys=True, indent=2) + '\n').encode()
        compressed = folder / ('0-semantics.json.gz' if object_mode else 'semantics.json.gz')
        compressed.write_bytes(gzip.compress(data, mtime=0))
        common = [str(base.sdk.toolchain.directory / ('clang++' if object_mode else 'clang'))]
        if object_mode: common.append('--target=aarch64-unknown-linux-gnu')
        common += [*unit['flags'], '-g']
        if unit['overlay'] is not None: common += ['-ivfsoverlay', unit['overlay']]
        tool = base.output / ('lifetime-tool' if object_mode else 'resource-tool') / 'lifetimes'
        commands = [[*common, '-M', '-MT', 'otelc-inputs', '-MF', str(depfile), unit['source']],
            [str(tool), str(base.project), unit['source'], '--compile-directory', unit['directory'], *common]]
        context = {key: unit[key] for key in ('directory', 'flags', 'overlay')} | {'assets': base.recipe()['assets']}
        value = {'schema_version': 2 if object_mode else 1,
            'kind': 'otelc.native.lifetime-inventory' if object_mode else 'otelc.native.c-resource-inventory',
            'profile': 'clang22-cxx-context-v1' if object_mode else 'clang22-c-allocation-v1',
            'root': str(base.project), 'tool': tool_record, 'policy_sha256': fixed.digest(base.policy()),
            'inputs': [fixed.identity(path, gate=True) for path in group], 'commands': commands,
            'source_complete': False, 'compile_context': context,
            'context_inputs': [fixed.identity(Path(name), gate=True) for name in base.recipe()['assets']]}
        record = {'semantic': fixed.identity(compressed, gate=True), 'semantic_bytes': len(data),
                  'semantic_sha256': hashlib.sha256(data).hexdigest()}
        if object_mode: value.update(target='aarch64-unknown-linux-gnu', translation_units=[{'source': unit['source'], **selected, **record}])
        else:
            value.update(source=unit['source'], **selected, **record)
            rows = []
            for site in [*selected['allocations'], *selected['releases']]:
                rows.append({'caller': site['caller'], 'file': str(Path(unit['directory']) / site['location']['debug_file']),
                    'line': site['location']['debug_line'], 'column': site['location']['debug_column'], 'callee': site['callee'],
                    'type_usr': site.get('type_usr', ''), 'emitted_calls': 1, 'emitted_callees': [site['callee']]})
            fixed.write(folder / 'resolution.json', {'schema_version': 1, 'kind': 'otelc.native.c-resource-resolution',
                'source': unit['source'], 'sites': rows})
        name = folder / ('native-lifetimes.json' if object_mode else 'native-resources.json')
        fixed.write(name, value); bindings[unit['id']] = fixed.identity(name, gate=True)
        artifacts.update(folder / name for name in (OBJECT_FILES if object_mode else RESOURCE_FILES))
    return {kind + '_tool': fixed.identity(base.output / ('lifetime-tool' if object_mode else 'resource-tool') / 'native-lifetime-tool.json', gate=True),
            kind + '_inventories': bindings}, artifacts


def rebind(intent) -> None:
    """An adversarial producer can rehash records but cannot change caller intent."""
    base = intent.base
    fixed.write(base.output / 'native-source-build.json', {'schema_version': 4 if intent.kind == 'object' else 5,
        'kind': 'otelc.native.source-build', 'profile': 'native-owned-v1', 'source_complete': False,
        'native': fixed.identity(base.output / 'native-build.json', gate=True),
        'plugin': fixed.identity(base.output / 'plugin/llvm-plugin.json', gate=True),
        'gate': fixed.identity(base.output / 'gate/gate.json', gate=True),
        'sdk': fixed.identity(base.sdk.record.file.path, gate=True)})
