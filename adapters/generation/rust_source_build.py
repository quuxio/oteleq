"""Read rebuilt Rust application builds against independently frozen caller intent."""

from dataclasses import dataclass
import math
from pathlib import Path

import native_inputs as inputs
from native_build import BOOTSTRAP
from native_protocol import digest, encoded, fields, require, same
from native_sdk import SDK
from otelc_capture import path_within, strict_json
import rust_build_recipe as recipe
import rust_inventory as inventory
import rust_lifetimes as lifetimes
from rust_tools import Tools, canonical_directory


def policy(value: object) -> dict:
    """Keep the caller's complete policy and refuse unsupported compiled selections."""
    row = fields(value, {'schema_version', 'languages', 'resource', 'export', 'sources', 'functions',
                         'metrics', 'traces', 'lifetimes', 'context', 'benchmark'}, 'Rust build policy')
    require(same(row['schema_version'], 3) and type(row['languages']) is list
            and all(type(name) is str for name in row['languages']) and 'rust' in row['languages'],
            'Rust build needs the common enabled-language policy')
    for name in ('sources', 'functions'):
        inventory.patterns(row[name])
    context = fields(row['context'], {'tasks', 'http'}, 'Rust context')
    require(all(value is False for value in context.values()), 'Rust task/service context is unavailable')
    lifetime = fields(row['lifetimes'], {'enabled', 'include', 'exclude', 'max_live', 'release_methods'},
                      'Rust lifetime policy')
    inventory.patterns({key: lifetime[key] for key in ('include', 'exclude')})
    require(type(lifetime['enabled']) is bool and type(lifetime['max_live']) is int
            and 1 <= lifetime['max_live'] <= 1000000, 'invalid Rust lifetime flags/budget')
    return strict_json(encoded(row))


@dataclass(frozen=True)
class Intent:
    """Original source/MIR observations precede the producer's application build."""

    tools: Tools
    sdk: SDK
    project: Path
    entry: Path
    output: Path
    dependencies: tuple[inputs.File, ...]
    sources: inventory.Sources
    inspection: inputs.Record
    lifetime_inspection: inputs.Record | None
    policy_json: str
    optimisation: int

    @property
    def lifetime(self) -> bool:
        """Source-build version is fixed by the frozen lifetime policy."""
        return self.policy()['lifetimes']['enabled']

    def policy(self) -> dict:
        """Each caller receives a fresh view of the immutable compiled policy."""
        return strict_json(self.policy_json)

    def selected(self) -> list[str]:
        """Producer selection must match independently inspected original declarations."""
        return inventory.selected_functions(self.policy(), self.sources, self.inspection.value())

    def bindings(self) -> dict | None:
        """Hash complete independently held MIR bodies rather than producer-selected locals."""
        if self.lifetime_inspection is None:
            return None
        return lifetimes.request(self.lifetime_inspection.value(), self.sources, self.policy(),
                                 target=self.tools.compiler.host)

    def verify(self) -> None:
        """Recheck original facts and the independent pre-build inspection denominator."""
        self.tools.verify()
        self.sdk.verify()
        canonical_directory(self.project)
        require(self.tools.root == self.sdk.root and self.sdk.source_profile == 'resource-v1',
                'Rust compiler/bridge and runtime need the same resource-capable SDK')
        require(self.sdk.platform == ('darwin' if self.tools.compiler.host.endswith('apple-darwin') else 'linux'),
                'Rust compiler target and SDK runtime platform differ')
        require(type(self.optimisation) is int and self.optimisation in (0, 1, 2, 3)
                and self.entry in tuple(file.path for file in self.sources.files),
                'invalid Rust original entry or optimisation')
        policy(self.policy())
        require(self.sources.root == self.project and type(self.dependencies) is tuple
                and 1 <= len(self.dependencies) <= 65536
                and all(type(file) is inputs.File for file in self.dependencies), 'invalid Rust original inputs')
        paths = tuple(file.path for file in self.dependencies)
        require(paths == tuple(sorted(set(paths))) and all(path.is_relative_to(self.project) for path in paths)
                and tuple(file for file in self.dependencies if file.path.suffix == '.rs') == self.sources.files,
                'Rust original source/dependency denominator changed')
        require(not (self.project / 'Cargo.toml').exists() and not (self.project / 'Cargo.toml').is_symlink(),
                'Cargo needs its separate build-context profile')
        for file in self.dependencies:
            file.verify()
        self.sources.verify()
        require(type(self.inspection) is inputs.Record, 'missing caller-held Rust inspection')
        self.inspection.verify()
        inventory.function_document(self.inspection.value(), self.sources, 'inspect')
        require((self.lifetime_inspection is not None) is self.lifetime,
                'Rust lifetime mode differs from independently held MIR discovery')
        if self.lifetime_inspection is not None:
            require(type(self.lifetime_inspection) is inputs.Record, 'invalid caller-held Rust MIR inspection')
            self.lifetime_inspection.verify()
            require(bool(self.bindings()['lifetimes']), 'Rust lifetime selection matched no original locals')
        self.selected()
        outside(self)


def outside(intent: Intent) -> None:
    """Check physical input boundaries before any output is created or read."""
    output = intent.output
    require(isinstance(output, Path) and output.is_absolute() and '..' not in output.parts
            and output == output.resolve() and output.parent == output.parent.resolve(strict=True)
            and not output.is_symlink(), 'Rust build needs a canonical external output')
    protected = (intent.project, intent.tools.directory, intent.sdk.directory, intent.tools.compiler.sysroot,
                 intent.sdk.toolchain.directory.parent, intent.tools.root / 'native/rust',
                 intent.tools.root / 'otelc', intent.sdk.root / 'adapters/native', intent.sdk.root / 'native/llvm')
    require(not any(path_within(output, root) for root in protected),
            'Rust build output overlaps original source/compiler/SDK inputs')
    for record in (intent.inspection, intent.lifetime_inspection):
        if record is not None:
            require(not path_within(record.file.path, output), 'Rust pre-build inspection is inside producer output')


def freeze(tools: Tools, sdk: SDK, project: Path, entry: Path, output: Path,
           dependencies: tuple[Path, ...], inspection: inputs.Record, compiled_policy: dict, *,
           lifetime_inspection: inputs.Record | None = None, optimisation: int = 2) -> Intent:
    """Capture independently discovered inputs before the SDK creates application output."""
    require(type(tools) is Tools and type(sdk) is SDK, 'missing caller-owned Rust compiler/runtime')
    canonical_directory(project)
    require(type(dependencies) is tuple and 1 <= len(dependencies) <= 65536
            and all(isinstance(path, Path) for path in dependencies)
            and dependencies == tuple(sorted(set(dependencies))), 'invalid caller Rust dependency paths')
    files = tuple(inputs.capture(path) for path in dependencies)
    sources = inventory.Sources(project, tuple(file for file in files if file.path.suffix == '.rs'))
    result = Intent(tools, sdk, project, entry, output, files, sources, inspection, lifetime_inspection,
                    encoded(policy(compiled_policy)), optimisation)
    result.verify()
    require(not output.exists(), 'Rust application build output must be new')
    return result


def document(intent: Intent, held: dict[str, inputs.File]) -> dict:
    """Reconstruct the complete manifest without adopting any producer paths or values."""
    modes = recipe.modes(intent.lifetime)
    return {'schema_version': 2 if intent.lifetime else 1, 'kind': 'otelc.rust.source-build',
            'profile': recipe.PROFILES[1 if intent.lifetime else 0], 'root': str(intent.project),
            'entry': str(intent.entry), 'policy': intent.policy(), 'policy_sha256': digest(intent.policy()),
            'selection_sha256': digest(recipe.selection(intent.policy())),
            'tools': intent.tools.record.file.gate_identity(), 'sdk': intent.sdk.record.file.gate_identity(),
            'inputs': [file.gate_identity() for file in intent.dependencies],
            'requests': [held[mode + '-request.json'].gate_identity() for mode in modes],
            'selected': intent.selected(), 'optimisation': intent.optimisation,
            'inventories': [held[mode + '-inventory.json'].gate_identity() for mode in modes],
            'products': [held[name].gate_identity() for name in ('plain', 'instrumented')], 'source_complete': False}


def channels(intent: Intent, held: dict[str, inputs.File]) -> None:
    """Commands and result records are observations, not independent process provenance."""
    for label, argv in recipe.commands(intent):
        command = strict_json(held[label + '.command.json'].content)
        require(same(command, {'arguments': argv, 'cwd': str(intent.project)}),
                'Rust build compiler command differs from the fixed recipe')
        value = fields(strict_json(held[label + '.result.json'].content), {'pid', 'exit_code', 'seconds'},
                       'Rust compiler result')
        require(type(value['pid']) is int and value['pid'] > 1 and same(value['exit_code'], 0)
                and type(value['seconds']) in (int, float) and math.isfinite(value['seconds'])
                and 0 <= value['seconds'] <= 1200, 'Rust compiler result is failed, unavailable or over budget')


def inventories(intent: Intent, held: dict[str, inputs.File]) -> None:
    """Both producer inspection and weaving must match the caller's earlier declarations/MIR."""
    for mode in recipe.modes(intent.lifetime):
        require(same(strict_json(held[mode + '-request.json'].content), recipe.request(intent, mode)),
                'Rust build request differs from caller-held source/selection')
        value = strict_json(held[mode + '-inventory.json'].content)
        if mode == 'lifetime-inspect':
            lifetimes.document(value, intent.sources, target=intent.tools.compiler.host)
            expected = intent.lifetime_inspection.value()
        else:
            inventory.function_document(value, intent.sources, mode, lifetime_request=
                                        intent.bindings() if mode == 'lifetime-weave' else None)
            expected = intent.inspection.value() | {'mode': mode}
            if mode == 'lifetime-weave':
                expected.update(intent.bindings(), kind='otelc.rust.lifetime-weave', instrumentation_complete=False)
        require(same(value, expected), 'Rust producer declarations/MIR differ from independent caller inspection')


@dataclass(frozen=True)
class Build:
    """Retain all required original output bytes/facts and the caller's pre-build intent."""

    intent: Intent
    files: tuple[tuple[str, inputs.File], ...]

    def manifest(self) -> dict:
        """Return a fresh decoded view bound to the originally accepted manifest."""
        return strict_json(dict(self.files)[recipe.MANIFEST].content)

    def verify(self) -> None:
        """Recheck original observations; repaired manifests cannot adopt changed inputs."""
        self.intent.verify()
        canonical_directory(self.intent.output)
        require(tuple(name for name, _ in self.files) == recipe.names(self.intent),
                'Rust retained build output denominator changed')
        held = dict(self.files)
        for name, file in self.files:
            require(file.path == self.intent.output / name, 'Rust retained output path changed')
            file.verify()
        require(same(self.manifest(), document(self.intent, held)), 'Rust source build differs from caller intent')
        recipe.dependency_paths(held['original.d'].content, self.intent.project,
                                tuple(file.path for file in self.intent.dependencies))
        require(held['bootstrap.cpp'].content == BOOTSTRAP.encode(), 'Rust native bootstrap bytes differ')
        channels(self.intent, held)
        inventories(self.intent, held)
        self.intent.verify()


def read(intent: Intent) -> Build:
    """Read fixed required paths, without importing the SDK or executing a compiler."""
    require(type(intent) is Intent, 'Rust build reader needs pre-build caller intent')
    intent.verify()
    canonical_directory(intent.output)
    budgets = {recipe.MANIFEST: inputs.MAX_RECORD, 'original.d': 4 * 1024 * 1024, 'bootstrap.cpp': 65536}
    files = tuple((name, inputs.capture(intent.output / name, keep=
                    name.endswith('.json') or name in ('original.d', 'bootstrap.cpp'),
                    maximum=budgets.get(name, inventory.MAX_RECORD if name.endswith('.json') else inputs.MAX_FILE)))
                  for name in recipe.names(intent))
    result = Build(intent, files)
    result.verify()
    return result
