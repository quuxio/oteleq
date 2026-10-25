"""Bind generated native callers and lifetime semantics before SDK compilation."""

from dataclasses import dataclass
from pathlib import Path

import native_inputs as inputs
import native_lifetime_build as builds
import native_lifetime_inventory as inventory
from native_protocol import encoded, require, same
import native_unit_caller as callers
import native_workers
import native_workspace
import otelc_capture as capture


def external_path(path: Path, source: callers.Source) -> None:
    """Generated directories must be new physical paths outside original inputs."""
    require(isinstance(path, Path) and path.is_absolute() and '..' not in path.parts
            and path.parent == path.parent.resolve(strict=True)
            and not path.exists() and not path.is_symlink()
            and not any(capture.path_within(path, root) for root in
                        (source.project, source.sdk.root, source.sdk.directory)),
            'native lifetime caller requires new external evidence')


def new_evidence(path: Path, source: callers.Source) -> None:
    """Create private compiler evidence after validating its physical boundary."""
    external_path(path, source)
    path.mkdir(mode=0o700)


def command(evidence: Path, label: str, argv: list, directory: Path, execute) -> bytes:
    """Retain literal fixed-tool commands and both bounded output channels."""
    root = evidence / label
    root.mkdir(mode=0o700)
    words = list(map(str, argv))
    result = execute(words, directory)
    require(type(result.stdout) is bytes and type(result.stderr) is bytes
            and len(result.stdout) <= inventory.MAX_AST and len(result.stderr) <= 16 * 1024**2,
            'native lifetime caller command exceeded its output budget')
    (root / 'command.json').write_text(encoded({'argv': words, 'directory': str(directory),
                                              'returncode': result.returncode}) + '\n')
    (root / 'stdout').write_bytes(result.stdout)
    (root / 'stderr').write_bytes(result.stderr)
    require(result.returncode == 0, 'native lifetime caller command failed; original channels retained')
    return result.stdout


def semantic_tool(tool: inventory.Tool, evidence: Path, execute) -> inputs.File:
    """Compile a separate caller tool from its earlier frozen source/header/library facts."""
    tool.verify()
    output = evidence / 'semantic-tool'
    output.mkdir(mode=0o700)
    for phase in ('before', 'after'):
        label = 'tool-inputs-' + phase
        query, _ = tool.commands(evidence / label)
        raw = command(evidence, label, query, tool.sdk.root, execute)
        require(not raw, 'native lifetime caller dependency query emitted unexpected stdout')
        inventory.dependencies((evidence / label / 'tool.d').read_bytes(),
                               tool.sdk.root, tool.dependencies, tool.aliases)
        tool.verify()
        if phase == 'before':
            _, build = tool.commands(output)
            raw = command(evidence, 'compile-semantic-tool', build, tool.sdk.root, execute)
            require(not raw, 'native lifetime caller tool build emitted unexpected stdout')
    expected = {'lifetimes', *inventory.debug_names(tool.sdk.platform, tool.host_target)}
    require(builds.file_set(output, expected) == expected, 'native lifetime caller tool products differ')
    result = inputs.capture(output / 'lifetimes')
    if tool.sdk.platform == 'darwin':
        dwarf = output / 'lifetimes.dSYM/Contents/Resources/DWARF/lifetimes'
        image = inputs.capture(result.path, keep=True)
        debug = inputs.capture(dwarf, keep=True)
        require(inventory.debug_uuid(image.content, tool.host_target) ==
                inventory.debug_uuid(debug.content, tool.host_target),
                'native lifetime caller tool debug identity differs')
        result.verify()
    tool.verify()
    return result


def semantics(tool: inputs.File, source: callers.Source, recipe: dict, kind: str,
              target: str | None, evidence: Path, execute) -> tuple[tuple[str, dict], ...]:
    """Run the independently built tool with the same original per-unit VFS context."""
    result = []
    for unit in recipe['units']:
        if unit['role'] != 'application' or kind == 'object' and unit['language'] != 'cpp':
            continue
        compiler = source.sdk.toolchain.directory / ('clang++' if unit['language'] == 'cpp' else 'clang')
        flags = [str(compiler), *(['--target=' + target] if kind == 'object' else []),
                 *unit['flags'], '-g']
        if unit['overlay'] is not None:
            flags += ['-ivfsoverlay', unit['overlay']]
        argv = [tool.path, source.project, unit['source'], '--compile-directory', unit['directory'], *flags]
        tool.verify()
        raw = command(evidence, unit['id'], argv, Path(unit['directory']), execute)
        value = inventory.document(capture.strict_json(raw), kind)
        inventory.catalogue(value, kind, capture.strict_json(source.policy_json), source.project)
        result.append((unit['id'], value))
        tool.verify()
    require(bool(result), 'native lifetime caller has no selected application units')
    return tuple(result)


@dataclass(frozen=True)
class Caller:
    """Original compiler observations, generated helpers and lifetime intent stay bound."""

    binding: callers.Caller
    intent: builds.Intent
    tool: inputs.File

    def verify(self) -> None:
        """Original accepted identities cannot be refreshed from producer metadata."""
        require(type(self.binding) is callers.Caller and type(self.intent) is builds.Intent
                and self.binding.intent is self.intent.base,
                'native lifetime caller has another compiler context')
        self.binding.verify()
        self.intent.verify()
        require(type(self.tool) is inputs.File and self.tool in self.binding.files,
                'native lifetime caller tool is not retained')
        self.tool.verify()

    def recheck(self, evidence: Path, execute) -> tuple[inputs.File, ...]:
        """Repeat full compiler input/search probes and semantic facts after build/execution."""
        self.verify()
        new_evidence(evidence, self.binding.source)
        compiler = self.binding.recheck(evidence / 'compiler', execute)
        semantic_evidence = evidence / 'semantics'
        semantic_evidence.mkdir(mode=0o700)
        values = semantics(self.tool, self.binding.source, self.intent.base.recipe(),
                           self.intent.kind, self.intent.target, semantic_evidence, execute)
        require(same([(name, encoded(value)) for name, value in values], list(self.intent.semantics)),
                'native lifetime caller semantic facts changed')
        self.verify()
        return (*compiler, *(inputs.capture(path) for path in sorted(evidence.rglob('*'))
                             if path.is_file() and not path.is_relative_to(evidence / 'compiler')))


def prepare(source: callers.Source, helpers: Path, evidence: Path, output: Path,
            tool: inventory.Tool, execute) -> Caller:
    """Generate and compiler-bind observations before producing build4/build5 intent."""
    source.verify()
    require(type(tool) is inventory.Tool and tool.sdk is source.sdk,
            'native lifetime caller tool belongs to another SDK')
    policy = capture.strict_json(source.policy_json)
    builds.policy(policy, tool.kind)
    profile, entry, arguments = (capture.strict_json(value) for value in
                                (source.profile_json, source.entry_json, source.arguments_json))
    require(entry['language'] == ('cpp' if tool.kind == 'object' else 'c'),
            'native lifetime caller language differs from its selected profile')
    for path in (helpers, evidence, output):
        external_path(path, source)
    require(len({helpers, evidence, output}) == 3, 'native lifetime caller directories overlap')
    new_evidence(evidence, source)
    native_workspace.verify_copy(profile, source.retained, source.project, evidence / 'original-inputs', execute)
    materialised = native_workers.materialise(source.project, profile, entry, arguments, helpers, unprofiled=True)
    target = native_workers.validate(profile, entry, arguments)
    bindings = [callers.application_unit(source, key, index, helpers, evidence, execute)
                for index, key in enumerate(target['units'])]
    bindings.append(callers.driver_unit(source, helpers, evidence, execute))
    states = {unit['id']: state for unit, state, _ in bindings}
    recipe = {'schema_version': 1, 'kind': 'otelc.native.unit-recipe',
              'assets': sorted(materialised['assets']), 'units': [unit for unit, _, _ in bindings],
              'link': {'language': entry['language'], 'directory': str(source.project),
                       'flags': target['link_flags']}}
    frontend = semantic_tool(tool, evidence, execute)
    compiler_target = None
    if tool.kind == 'object':
        raw = command(evidence, 'target', [source.sdk.toolchain.directory / 'clang++', '-print-target-triple'],
                      source.project, execute)
        compiler_target = raw.decode('utf-8', errors='strict').strip()
    semantic_evidence = evidence / 'semantics'
    semantic_evidence.mkdir(mode=0o700)
    semantic_values = semantics(frontend, source, recipe, tool.kind, compiler_target, semantic_evidence, execute)
    paths = {str(path) for _, _, group in bindings for path in group}
    aliases = tuple(sorted({Path(logical) for state in states.values()
                            for logical, row in state['dependencies'].items()
                            if logical != row['resolved'] and row['resolved'] in paths}))
    intent = builds.freeze(source.sdk, source.project, output, tool.kind, recipe,
                           tuple(group for _, _, group in bindings), policy, semantic_values, tool,
                           target=compiler_target, aliases=aliases)
    (evidence / 'caller.json').write_text(encoded({'schema_version': 1, 'kind': 'oteleq.native.lifetime-caller',
        'entry': entry, 'arguments': arguments, 'recipe': recipe, 'states': states,
        'semantics': dict(semantic_values), 'source_complete': False}) + '\n')
    files = callers.capture_files(source, target, evidence, states)
    binding = callers.Caller(source, intent.base, files, encoded(states), tuple(item.path for item in files))
    result = Caller(binding, intent, frontend)
    result.verify()
    return result
