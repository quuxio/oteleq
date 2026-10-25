"""Generate native observation callers and bind them through the actual compiler."""

from dataclasses import dataclass
import os
from pathlib import Path
import shlex

import native_frontend
import native_inputs as inputs
from native_protocol import encoded, require, same
from native_sdk import SDK
import native_unit_build
import native_workers
import native_workspace
from otelc_capture import strict_json


def nodes(value: dict):
    """Visit actual frontend declarations and expression references in source order."""
    yield value
    for child in value.get('inner', []):
        yield from nodes(child)


def location(node: dict) -> tuple[str | None, int | None]:
    """Macro locations retain their compiler-owned expansion position."""
    value = node.get('loc', {})
    value = value.get('expansionLoc', value)
    return value.get('file'), value.get('offset')


def signature(node: dict) -> dict:
    """Clang process-local declaration IDs are not portable type identities."""
    def type_value(value: dict) -> dict:
        return {key: value[key] for key in ('qualType', 'desugaredQualType') if key in value}
    return {'kind': node.get('kind'), 'name': node.get('name'), 'symbol': node.get('mangledName'),
            'type': type_value(node.get('type', {})),
            'parameters': [type_value(child.get('type', {})) for child in node.get('inner', [])
                           if child.get('kind') == 'ParmVarDecl']}


def selected(document: dict, source: Path, entry: dict) -> dict:
    """One physical original definition must match the inventoried overload."""
    matches = [node for node in nodes(document['ast'])
               if node.get('kind') == entry['native_kind']
               and node.get('mangledName', node.get('name')) == entry['symbol']
               and location(node) == (str(source), entry['source_offset'])
               and any(child.get('kind') == 'CompoundStmt' for child in node.get('inner', []))]
    require(len(matches) == 1, 'materialised native caller has no unique original target definition')
    return matches[0]


def helper_names(entry: dict, key: str) -> set[str]:
    """All target-wide state accessors remain assigned to their original units."""
    names = {'__oteleq_root_' + str(index) for index, row in enumerate(entry['globals']) if row['unit'] == key}
    if key == entry['unit']:
        names.add('__oteleq_invoke')
    return names


def bind(document: dict, original: dict, source: Path, entry: dict, key: str) -> None:
    """The generated invocation must reference the original exact declaration."""
    expected = helper_names(entry, key)
    definitions = [node for node in nodes(document['ast']) if node.get('kind') == 'FunctionDecl'
                   and node.get('name', '').startswith('__oteleq_')
                   and any(child.get('kind') == 'CompoundStmt' for child in node.get('inner', []))]
    require(len(definitions) == len(expected) and {node['name'] for node in definitions} == expected,
            'materialised native accessor denominator differs')
    require(all(any(node.get('kind') == 'NoProfileFunctionAttr' for node in nodes(helper)) for helper in definitions),
            'materialised native accessor lacks its compiler profiling exclusion')
    if key == entry['unit']:
        before, after = selected(original, source, entry), selected(document, source, entry)
        require(same(signature(before), signature(after)), 'materialised native target signature changed')
        require(type(after.get('id')) is str and bool(after['id']), 'materialised native target has no declaration identity')
        invoke = next(node for node in definitions if node['name'] == '__oteleq_invoke')
        require(any(node.get('referencedDecl', {}).get('id') == after.get('id') for node in nodes(invoke)),
                'materialised native invocation does not reference its frozen target')


def flags(unit: dict, language: str) -> list[str]:
    """The recipe selects the language separately from the frontend's explicit switch."""
    require(unit['language'] == language, 'native unit language differs from its target')
    values = list(unit['flags'])
    expected = 'c++' if language == 'cpp' else 'c'
    if '-x' in values:
        require(values[-2:] == ['-x', expected], 'native frontend language switch differs from its unit')
        return values[:-2]
    return values


@dataclass(frozen=True)
class Source:
    """Caller-selected project, target, concrete arguments and policy precede compilers."""

    sdk: SDK
    project: Path
    retained: Path
    profile_json: str
    entry_json: str
    arguments_json: str
    policy_json: str

    def verify(self) -> None:
        """Retain matched tools and the independently inventoried private snapshot."""
        self.sdk.verify()
        profile = strict_json(self.profile_json)
        require(self.project.is_absolute() and self.project.resolve(strict=True) == self.project,
                'native caller project must remain canonical')
        require(Path(profile['compiler']['path']).resolve(strict=True) == self.sdk.toolchain.selected_compiler.resolved,
                'native caller frontend differs from the selected SDK compiler')
        native_frontend.verify(profile['frontend'], self.retained / 'frontend')
        native_workers.checked_snapshot(self.project, profile)


def freeze(sdk: SDK, project: Path, profile: dict, retained: Path, entry: dict, arguments: list, policy: dict) -> Source:
    """Mutable configuration aliases cannot change an accepted generation request."""
    result = Source(sdk, project, retained, encoded(profile), encoded(entry), encoded(arguments), encoded(policy))
    result.verify()
    native_workers.validate(strict_json(result.profile_json), strict_json(result.entry_json), strict_json(result.arguments_json))
    return result


@dataclass(frozen=True)
class Caller:
    """Hold independently generated inputs and compiler evidence before SDK builds."""

    source: Source
    intent: native_unit_build.Intent
    files: tuple[inputs.File, ...]
    states_json: str
    paths: tuple[Path, ...]

    def verify(self) -> None:
        """Rewrites of helper, compiler or original source evidence cannot repair intent."""
        self.source.verify()
        self.intent.verify()
        require(type(self.files) is tuple and tuple(item.path for item in self.files) == self.paths,
                'native caller evidence denominator changed')
        for held in self.files:
            held.verify()
        expected = {str(item.path): item for item in self.files}
        for state in strict_json(self.states_json).values():
            for logical, row in state['dependencies'].items():
                require(logical in expected and str(expected[logical].resolved) == row['resolved']
                        and expected[logical].sha256 == row['sha256'],
                        'native caller inputs changed after compiler discovery')

    def recheck(self, evidence: Path, execute) -> tuple[inputs.File, ...]:
        """Repeat compiler input/probe checks after SDK builds or application execution."""
        self.verify()
        require(evidence.is_absolute() and not evidence.exists() and not evidence.is_symlink()
                and not evidence.resolve().is_relative_to(self.intent.project), 'native caller recheck needs new external evidence')
        evidence.mkdir(mode=0o700)
        expected = strict_json(self.states_json)
        profile = strict_json(self.source.profile_json)
        for index, unit in enumerate(self.intent.recipe()['units']):
            root = self.intent.project if unit['role'] == 'application' else Path(unit['source']).parent
            flags = [*unit['flags'], '-g']
            if unit['overlay'] is not None:
                flags += ['-ivfsoverlay', unit['overlay']]
            context = {'source': Path(unit['source']).relative_to(root).as_posix(),
                       'directory': Path(unit['directory']).relative_to(root).as_posix(),
                       'compiler': profile['compiler']['path'], 'flags': flags}
            _, state, paths = inspect(context, root, profile, self.source.retained, evidence / unit['id'], execute, mode='inputs')
            require(same(state, expected[unit['id']]) and set(paths) == set(self.intent.unit_dependencies[index]),
                    'native caller compiler inputs or preprocessor probes changed')
        self.verify()
        return tuple(inputs.capture(path) for path in sorted(evidence.rglob('*')) if path.is_file())


def inspect(unit: dict, project: Path, profile: dict, retained: Path, evidence: Path, execute, *, mode: str = 'ast') -> tuple[dict, dict, tuple[Path, ...]]:
    """Use the independently built frontend with the actual private VFS context."""
    depfile = evidence / 'inputs.d'
    context = {**unit, 'flags': [*unit['flags'], '-MD', '-MF', str(depfile), '-MT', 'otelc-inputs']}
    document = native_frontend.inspect(context, project, profile['frontend'], retained / 'frontend', evidence, execute, mode=mode)
    state = native_frontend.input_state(document, unit, project)
    raw = depfile.read_text().replace('\\\n', '')
    target, separator, names = raw.partition(':')
    require(target == 'otelc-inputs' and separator == ':', 'invalid native caller compiler dependency channel')
    directory = project / unit['directory']
    logical = [os.path.abspath(directory / name.replace('$$', '$')) for name in shlex.split(names)]
    require(all(name in state['dependencies'] for name in logical), 'native caller compiler consumed an uninventoried input')
    paths = tuple(Path(state['dependencies'][name]['resolved']) for name in logical)
    require(len(paths) == len(set(paths)) and (project / unit['source']).resolve() in paths,
            'native caller compiler dependency denominator differs')
    return document, state, paths


def application_unit(source: Source, key: str, index: int, helpers: Path, evidence: Path, execute) -> tuple[dict, dict, tuple[Path, ...]]:
    """Bind one generated unit to its original physical target and exact overload."""
    profile, entry = strict_json(source.profile_json), strict_json(source.entry_json)
    original = profile['units'][key]
    path = source.project / original['source']
    vfs = helpers / (key + '.vfs.json')
    context = {**original, 'flags': [*original['flags'], '-g', '-ivfsoverlay', str(vfs)]}
    document, state, paths = inspect(context, source.project, profile, source.retained, evidence / key, execute)
    original_document = strict_json((source.retained / 'units' / key / 'metadata.json').read_bytes())
    # Original metadata uses the original root; only the physical source spelling moves.
    original_source = Path(profile['source_root']) / original['source']
    original_target = selected(original_document, original_source, entry) if key == entry['unit'] else None
    if original_target is not None:
        original_target = {**original_target, 'loc': {**original_target['loc'], 'file': str(path)}}
        original_document = {'ast': {'inner': [original_target]}}
    bind(document, original_document, path, entry, key)
    unit = {'id': 'unit_' + str(index), 'role': 'application', 'source': str(path),
        'language': entry['language'], 'directory': str(source.project / original['directory']),
        'flags': flags(original, entry['language']), 'overlay': str(vfs), 'rename_main': True}
    return unit, state, paths


def driver_unit(source: Source, helpers: Path, evidence: Path, execute) -> tuple[dict, dict, tuple[Path, ...]]:
    """The SDK recipe keeps the observation driver as a neutral compilation unit."""
    profile, entry = strict_json(source.profile_json), strict_json(source.entry_json)
    driver = helpers / ('driver.cpp' if entry['language'] == 'cpp' else 'driver.c')
    driver_flags = ['-std=c++17' if entry['language'] == 'cpp' else '-std=c11', '-O1']
    context = {'source': driver.name, 'directory': '.', 'compiler': profile['compiler']['path'],
               'flags': [*driver_flags, '-g']}
    _, state, paths = inspect(context, helpers, profile, source.retained, evidence / 'driver', execute)
    unit = {'id': 'observer', 'role': 'driver', 'source': str(driver), 'language': entry['language'],
            'directory': str(helpers), 'flags': driver_flags, 'overlay': None, 'rename_main': False}
    return unit, state, paths


def capture_files(source: Source, target: dict, evidence: Path, states: dict) -> tuple[inputs.File, ...]:
    """Keep compiler channels, original metadata and every source/alias file fact."""
    profile = strict_json(source.profile_json)
    paths = {source.retained / 'units' / key / 'metadata.json' for key in target['units']}
    paths.update(path for path in (source.retained / 'frontend').rglob('*') if path.is_file())
    paths.update(path for path in evidence.rglob('*') if path.is_file())
    paths.update(source.project / name for name in profile['local_inputs'])
    captured = {path: inputs.capture(path) for path in paths}
    frontend = profile['frontend']
    external = {**frontend['dependencies'], **frontend['external']}
    for logical, row in external.items():
        path = source.retained / 'frontend/source' / row['source_relative'] if row.get('source_relative') else Path(logical)
        if path not in captured:
            captured[path] = inputs.capture(path, allow_links=True)
    # Source.verify authenticates the current embedded recipe by hash. Retain
    # its durable frontend/source copy, not the Rust CLI's temporary extraction.
    for state in states.values():
        for logical in state['dependencies']:
            path = Path(logical)
            if path not in captured:
                captured[path] = inputs.capture(path, allow_links=True)
    return tuple(captured[path] for path in sorted(captured))


def prepare(source: Source, helpers: Path, evidence: Path, output: Path, execute) -> Caller:
    """Materialise source-free observations, then freeze compiler-confirmed build3 intent."""
    source.verify()
    require(not evidence.exists() and not evidence.is_symlink() and evidence.is_absolute()
            and evidence == evidence.resolve() and not evidence.is_relative_to(source.project),
            'native caller evidence requires a new canonical external directory')
    profile, entry, arguments = (strict_json(value) for value in (source.profile_json, source.entry_json, source.arguments_json))
    evidence.mkdir(mode=0o700)
    native_workspace.verify_copy(profile, source.retained, source.project, evidence / 'original-inputs', execute)
    recipe = native_workers.materialise(source.project, profile, entry, arguments, helpers, unprofiled=True)
    target = native_workers.validate(profile, entry, arguments)
    bindings = [application_unit(source, key, index, helpers, evidence, execute) for index, key in enumerate(target['units'])]
    bindings.append(driver_unit(source, helpers, evidence, execute))
    states = {unit['id']: state for unit, state, _ in bindings}
    public = {'schema_version': 1, 'kind': 'otelc.native.unit-recipe', 'assets': sorted(recipe['assets']),
        'units': [unit for unit, _, _ in bindings],
        'link': {'language': entry['language'], 'directory': str(source.project), 'flags': target['link_flags']}}
    paths = {str(path) for _, _, group in bindings for path in group}
    aliases = tuple(sorted({Path(logical) for state in states.values() for logical, row in state['dependencies'].items()
                            if logical != row['resolved'] and row['resolved'] in paths}))
    intent = native_unit_build.freeze(source.sdk, source.project, output, entry['language'], public,
        tuple(group for _, _, group in bindings), strict_json(source.policy_json), aliases=aliases)
    (evidence / 'caller.json').write_text(encoded({'schema_version': 1, 'kind': 'oteleq.native.caller',
        'entry': entry, 'arguments': arguments, 'recipe': public, 'states': states, 'source_complete': False}) + '\n')
    files = capture_files(source, target, evidence, states)
    result = Caller(source, intent, files, encoded(states), tuple(item.path for item in files))
    result.verify()
    return result
