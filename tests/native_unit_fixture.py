"""Literal build3 records for independent native reader refusal tests."""

from pathlib import Path
import shlex

import native_build
import native_unit_build
import native_provider_fixture as fixed


def commands(recipe: dict, output: Path, sdk) -> list[dict]:
    """Construct literal producer-shaped records without the consumer renderer."""
    result = []
    for lane in ('plain', 'instrumented'):
        objects = []
        for unit in recipe['units']:
            label = lane + '-' + unit['id']
            final = output / (label + '.o')
            compiled = output / (label + '.original.o') if unit['rename_main'] else final
            compiler = sdk.toolchain.directory / ('clang' if unit['language'] == 'c' else 'clang++')
            argv = [str(compiler), *unit['flags'], '-g', '-MD', '-MF', str(output / (label + '.d')),
                    '-MT', 'otelc-inputs', '-c', unit['source'], '-o', str(compiled)]
            if unit['overlay'] is not None:
                argv += ['-ivfsoverlay', unit['overlay']]
            if lane == 'instrumented' and unit['role'] == 'application':
                argv += ['-fpass-plugin=' + str(output / 'plugin/libotelc_llvm.so')]
            result.append({'label': label, 'directory': unit['directory'], 'arguments': argv,
                'output': str(compiled), 'source': unit['source'], 'dependencies': str(output / (label + '.d')),
                'unit': unit['id'], 'lane': lane})
            if unit['rename_main']:
                result.append({'label': label + '-rename', 'directory': str(output),
                    'arguments': [str(sdk.toolchain.directory / 'llvm-objcopy'), '--redefine-sym',
                        'main=__oteleq_original_main', '--redefine-sym', '_main=___oteleq_original_main', str(compiled), str(final)],
                    'output': str(final)})
            objects.append(str(final))
        if lane == 'instrumented':
            result.append({'label': 'bootstrap', 'directory': str(output), 'arguments': [
                str(sdk.toolchain.directory / 'clang++'), '-std=c++17', '-O2', '-g', '-c', str(output / 'bootstrap.cpp'),
                '-o', str(output / 'bootstrap.o'), '-I', str(sdk.root / 'adapters/native/launcher/include')],
                'output': str(output / 'bootstrap.o'), 'source': str(output / 'bootstrap.cpp')})
            objects.insert(0, str(output / 'bootstrap.o'))
        argv = [str(sdk.toolchain.directory / ('clang' if recipe['link']['language'] == 'c' else 'clang++')),
                *objects, *recipe['link']['flags'], '-o', str(output / lane)]
        if lane == 'instrumented':
            argv += [str(sdk.library.path), '-Wl,-rpath,' + str(sdk.directory)]
        result.append({'label': lane + '-link', 'directory': recipe['link']['directory'],
                       'arguments': argv, 'output': str(output / lane)})
    return result


def build(root: Path, *, tooling: bool = True):
    """Reuse fixed SDK/plugin/gate fixtures; no fixture product is executable."""
    old = fixed.build(root, count=2)
    project, output, sdk = old.project, old.output, old.sdk
    header = project / 'state.h'
    source = project / 'unit1.c'
    (project / 'unit1.cpp').rename(source)
    private = root / 'private'; private.mkdir()
    driver = private / 'driver.c'; driver.write_text('neutral driver fixture')
    augmented = private / 'observed.cpp'; augmented.write_text('private original and observation helpers')
    overlay = private / 'overlay.json'
    fixed.write(overlay, {'version': 0, 'use-external-names': False, 'roots': [
        {'type': 'file', 'name': str(project / 'unit0.cpp'), 'external-contents': str(augmented)}]})
    objcopy = sdk.toolchain.directory / 'llvm-objcopy'; objcopy.write_text('unit object tool; never executed')
    (project / 'context').mkdir()
    def unit(name, path, language, role, directory, flags, vfs=None, rename=False):
        return {'id': name, 'source': str(path), 'language': language, 'role': role,
                'directory': str(directory), 'flags': flags, 'overlay': str(vfs) if vfs else None, 'rename_main': rename}
    units = [unit('work', project / 'unit0.cpp', 'cpp', 'application', project,
                  ['-std=c++20', '-O1', '-D', 'VALUE=3', '-isystem', str(project)], overlay if tooling else None, tooling),
             unit('state', source, 'c', 'application', project / 'context', ['-std=c17', '-O0', '-U', 'VALUE'])]
    groups = [(project / 'unit0.cpp', header), (source, header)]
    if tooling:
        units.append(unit('observer', driver, 'c', 'driver', private, ['-std=c11', '-O2']))
        groups.append((driver, header))
    recipe = {'schema_version': 1, 'kind': 'otelc.native.unit-recipe', 'units': units,
              'assets': [str(driver), str(augmented), str(overlay)] if tooling else [],
              'link': {'language': 'cpp', 'directory': str(project), 'flags': ['-pthread', '-lm']}}
    staged = root / 'staged-build'; output.rename(staged)
    intent = native_unit_build.freeze(sdk, project, output, 'cpp', recipe, tuple(groups), fixed.POLICY)
    staged.rename(output)
    for path in output.glob('*'):
        if path.name.startswith(('plain-', 'instrumented-')):
            path.unlink()
    steps = commands(recipe, output, sdk)
    for row in steps:
        Path(row['output']).write_text('unit product ' + row['label'])
        for channel in ('stdout', 'stderr'):
            (output / (row['label'] + '.' + channel)).write_bytes(b'')
        if 'dependencies' in row:
            index = next(index for index, unit in enumerate(units) if unit['id'] == row['unit'])
            Path(row['dependencies']).write_text('otelc-inputs: ' + shlex.join(map(str, groups[index])) + '\n')
    dependencies = {lane + '-' + unit['id']: [fixed.identity(path) for path in group]
                    for lane in ('plain', 'instrumented') for unit, group in zip(units, groups)}
    paths = {path for group in groups for path in group}
    files = paths | {Path(value) for value in recipe['assets']}
    artifacts = {output / 'bootstrap.cpp', output / 'compile_commands.json'}
    for row in steps:
        artifacts.update((Path(row['output']), output / (row['label'] + '.stdout'), output / (row['label'] + '.stderr')))
        if 'dependencies' in row:
            artifacts.add(Path(row['dependencies']))
    fixed.write(output / 'compile_commands.json', [{'directory': row['directory'], 'file': row['source'],
                'arguments': row['arguments']} for row in steps if 'source' in row])
    value = {'schema_version': 2, 'kind': 'otelc.native-build', 'profile': 'llvm22-native-units-v1',
        'language': 'cpp', 'root': str(project), 'policy': fixed.POLICY, 'policy_sha256': fixed.digest(fixed.POLICY),
        'selection_sha256': fixed.digest({key: fixed.POLICY[key] for key in ('sources', 'functions')}),
        'inputs': [fixed.identity(path) for path in sorted(paths)], 'sdk_library': fixed.identity(sdk.library.path),
        'products': [fixed.identity(output / lane) for lane in ('plain', 'instrumented')],
        'commands': steps, 'recipe': recipe, 'files': [fixed.identity(path, gate=True) for path in sorted(files)],
        'artifacts': [fixed.identity(path, gate=True) for path in sorted(artifacts)], 'dependencies': dependencies,
        'tools': {'objcopy': fixed.identity(objcopy, gate=True)} if tooling else {}, 'source_complete': False}
    fixed.write(output / 'native-build.json', value)
    rebind(intent)
    return intent


def rebind(intent) -> None:
    """Repair only the producer's outer binding, as an adversarial producer could."""
    fixed.write(intent.output / native_build.MANIFEST, {'schema_version': 3, 'kind': 'otelc.native.source-build',
        'profile': 'native-owned-v1', 'source_complete': False,
        'native': fixed.identity(intent.output / 'native-build.json', gate=True),
        'plugin': fixed.identity(intent.output / 'plugin/llvm-plugin.json', gate=True),
        'gate': fixed.identity(intent.output / 'gate/gate.json', gate=True),
        'sdk': fixed.identity(intent.sdk.record.file.path, gate=True)})
