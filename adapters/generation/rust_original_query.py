"""Execute and seal fixed original Rust compiler queries before SDK application builds."""

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import time

import native_inputs as inputs
from native_lifetime_build import file_set
from native_protocol import encoded, require, same
from otelc_capture import path_within
import rust_body_bindings as bodies
import rust_build_recipe as recipe
import rust_inventory as inventory
import rust_lifetimes as lifetimes
import rust_modules as modules
from rust_tools import Tools, canonical_directory

FLOOR = 8 * 1024**3
CRATE = 'otelc_app'
QUERY_MODES = ('inspect', 'module-inspect', 'binding-inspect')
COMPILER_QUERIES = ('compiler-version', 'compiler-sysroot')


def names(lifetime: bool) -> set[str]:
    """The caller fixes every allowed query output before execution."""
    modes = (*QUERY_MODES, *(('lifetime-inspect',) if lifetime else ()))
    result = {'original.d'}
    for mode in modes:
        filename = ('module' if mode == 'module-inspect' else mode) + '-inventory.json'
        result.update((filename, mode + '-request.json'))
    result.update(label + '/' + suffix for label in (*COMPILER_QUERIES, 'dependencies', *modes)
                  for suffix in ('command.json', 'result.json', 'process.json', 'stdout', 'stderr'))
    return result


def publish(path: Path, value: dict) -> inputs.Record:
    """Create a caller-owned record once, without replacing existing evidence."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(encoded(value) + '\n')
    return inputs.read(path, private=True)


def environment(tools: Tools, request: Path | None = None) -> dict[str, str]:
    """Use explicit compiler/loader inputs, without inherited Rust or telemetry hooks."""
    result = {'PATH': '/usr/bin:/bin', 'RUSTC_BOOTSTRAP': '1'}
    if tools.compiler.host.endswith('linux-gnu'):
        result['LD_LIBRARY_PATH'] = str(tools.compiler.sysroot / 'lib')
    if request is not None:
        result['OTELC_RUST_REQUEST'] = str(request)
    return result


def run(evidence: Path, label: str, argv: list[str], project: Path,
        env: dict[str, str], deadline: float, execute, *, empty: bool = True) -> bytes:
    """Use the shared owned executor and retain failures before checking results."""
    require(shutil.disk_usage(evidence).free >= FLOOR, 'Rust original queries require at least 8 GiB free')
    remaining = deadline - time.monotonic()
    require(remaining > 0, 'Rust original query deadline expired')
    folder = evidence / label
    folder.mkdir(mode=0o700)
    publish(folder / 'command.json', {'argv': argv, 'directory': str(project), 'environment': env})
    started = time.monotonic_ns()
    failure = None
    result = None
    try:
        result = execute(argv, project, env=env, folder=folder, timeout=remaining,
                         max_output_bytes=inventory.MAX_RECORD, record_process=True)
    except BaseException as error:
        failure = error
        raise
    finally:
        try:
            publish(folder / 'result.json', {
                'returncode': result.returncode if result is not None else None,
                'elapsed_ns': time.monotonic_ns() - started,
                'error': type(failure).__name__ if failure is not None else None})
        except BaseException as error:
            if failure is None:
                raise
            failure.add_note('Rust query result retention also failed: ' + type(error).__name__)
    require(type(result.returncode) is int and result.returncode == 0
            and type(result.stdout) is type(result.stderr) is bytes
            and (not empty or result.stdout == b'')
            and len(result.stdout) + len(result.stderr) <= inventory.MAX_RECORD,
            'original Rust compiler query failed; inspect retained channels')
    process = inputs.read(folder / 'process.json').value()
    require(set(process) == {'pid', 'argv'} and type(process['pid']) is int
            and process['pid'] > 0 and same(process['argv'], argv)
            and time.monotonic() <= deadline,
            'Rust original query process or deadline differs')
    require((folder / 'stdout').read_bytes() == result.stdout
            and (folder / 'stderr').read_bytes() == result.stderr,
            'Rust original query channels differ from the owned executor')
    return result.stdout


@dataclass(frozen=True)
class Context:
    """Original compiler observations and file facts precede any producer build."""

    tools: Tools
    sources: inventory.Sources
    dependencies: tuple[inputs.File, ...]
    directory: Path
    directory_facts: tuple
    entry: Path
    optimisation: int
    files: tuple[inputs.File, ...]
    inspection: inputs.Record
    module_inspection: inputs.Record
    body_inspection: inputs.Record
    lifetime_inspection: inputs.Record | None
    manifest: inputs.Record

    def verify(self) -> None:
        """Refuse changed/restored inputs, outputs, extra files and repaired records."""
        self.tools.verify()
        self.sources.verify()
        for file in self.dependencies:
            file.verify()
        require(inputs.directory(self.directory) == self.directory_facts,
                'Rust original query directory changed')
        expected = names(self.lifetime_inspection is not None) | {'original-query.json'}
        retained = {str(file.path.relative_to(self.directory)) for file in self.files}
        require(len(retained) == len(self.files) and retained == expected
                and file_set(self.directory, expected) == expected,
                'Rust original query evidence denominator changed')
        for file in self.files:
            file.verify()
        self.manifest.verify()
        require(self.manifest.file.path == self.directory / 'original-query.json'
                and same(self.manifest.value(), summary(self.tools, self.dependencies,
                    self.entry, self.optimisation, self.lifetime_inspection is not None,
                    tuple(file for file in self.files if file != self.manifest.file))),
                'Rust original query summary differs from its original observations')
        expected_paths = ('inspect-inventory.json', 'module-inventory.json',
                          'binding-inspect-inventory.json', 'lifetime-inspect-inventory.json')
        for record in (self.inspection, self.module_inspection, self.body_inspection,
                       self.lifetime_inspection):
            if record is not None:
                record.verify()
        for record, name in zip((self.inspection, self.module_inspection, self.body_inspection,
                                 self.lifetime_inspection), expected_paths):
            require(record is None or record.file.path == self.directory / name
                    and any(same(record.file.gate_identity(), file.gate_identity()) for file in self.files),
                    'Rust query record belongs to another context')


def summary(tools: Tools, held: tuple[inputs.File, ...], entry: Path,
            optimisation: int, lifetime: bool, files: tuple[inputs.File, ...]) -> dict:
    """Bind fixed query intent and all retained result identities in one record."""
    return {'schema_version': 1, 'kind': 'oteleq.rust.original-query', 'crate_name': CRATE,
            'entry': str(entry), 'optimisation': optimisation, 'lifetimes': lifetime,
            'sources': [file.gate_identity() for file in held],
            'tools': tools.record.file.gate_identity(), 'results': [file.gate_identity() for file in files],
            'source_complete': False, 'semantic_complete': False}


def prepare(tools: Tools, project: Path, entry: Path, evidence: Path,
            dependencies: tuple[Path, ...], *, optimisation: int = 2,
            lifetime: bool = False, timeout: float = 120, execute=None) -> Context:
    """Run original dependency/function/module/body queries with held source and flags."""
    require(type(tools) is Tools, 'Rust original queries need independently held tools')
    tools.verify()
    canonical_directory(project)
    require(type(dependencies) is tuple and 1 <= len(dependencies) <= 65536
            and all(isinstance(path, Path) and path.is_relative_to(project) for path in dependencies)
            and dependencies == tuple(sorted(set(dependencies)))
            and isinstance(entry, Path) and entry in dependencies and entry.suffix == '.rs'
            and type(optimisation) is int and optimisation in (0, 1, 2, 3)
            and type(lifetime) is bool and type(timeout) in (int, float) and 0 < timeout <= 1200,
            'invalid caller Rust original source/query intent')
    require(not (project / 'Cargo.toml').exists() and not (project / 'Cargo.toml').is_symlink(),
            'Cargo needs its separate original build-context profile')
    protected = (project, tools.root, tools.directory, tools.compiler.sysroot)
    require(isinstance(evidence, Path) and evidence.is_absolute() and '..' not in evidence.parts
            and evidence.parent == evidence.parent.resolve(strict=True)
            and not evidence.exists() and not evidence.is_symlink()
            and not any(path_within(evidence, root) for root in protected),
            'Rust original queries need new external evidence')
    held = tuple(inputs.capture(path) for path in dependencies)
    sources = inventory.capture_sources(project, tuple(path for path in dependencies if path.suffix == '.rs'))
    evidence.mkdir(mode=0o700)
    if execute is None:
        from generation import execute
    deadline = time.monotonic() + timeout
    failure = None
    try:
        return inspect(tools, sources, held, entry, evidence, optimisation, lifetime, deadline, execute)
    except BaseException as error:
        failure = error
        raise
    finally:
        for verify in (tools.verify, sources.verify, *(file.verify for file in held)):
            try:
                verify()
            except BaseException as error:
                if failure is None:
                    raise
                failure.add_note('Rust original input recheck also failed: ' + str(error))


def inspect(tools: Tools, sources: inventory.Sources, held: tuple[inputs.File, ...],
            entry: Path, evidence: Path, optimisation: int, lifetime: bool,
            deadline: float, execute) -> Context:
    """Keep the complete fixed query recipe separate from producer-selected metadata."""
    project = sources.root
    flags = [str(entry), '--crate-name', CRATE, '--edition=2024', '--sysroot',
             str(tools.compiler.sysroot), '-Copt-level=' + str(optimisation), '-g']
    rustc = str(tools.compiler.files[0].path)
    version = run(evidence, 'compiler-version', [rustc, '-vV'], project,
                  environment(tools), deadline, execute, empty=False).decode('utf-8').strip()
    sysroot = run(evidence, 'compiler-sysroot', [rustc, '--print', 'sysroot'], project,
                  environment(tools), deadline, execute, empty=False).decode('utf-8').strip()
    require(version == tools.compiler.version.strip() and sysroot == str(tools.compiler.sysroot),
            'actual Rust compiler version/sysroot differs from caller-held tools')
    run(evidence, 'dependencies', [str(tools.compiler.files[0].path), *flags,
        '--emit=dep-info=' + str(evidence / 'original.d')], project, environment(tools), deadline, execute)
    depfile = inputs.capture(evidence / 'original.d', maximum=4 * 1024**2, keep=True)
    recipe.dependency_paths(depfile.content, project, tuple(file.path for file in held))
    records = {}
    modes = (*QUERY_MODES, *(('lifetime-inspect',) if lifetime else ()))
    for mode in modes:
        filename = ('module' if mode == 'module-inspect' else mode) + '-inventory.json'
        request_path = evidence / (mode + '-request.json')
        request = publish(request_path, {'schema_version': 1, 'mode': mode,
            'root': str(project), 'entry': str(entry), 'sources': sources.hashes(),
            'selected': [], 'output': str(evidence / filename)})
        run(evidence, mode, [str(tools.products[0].path), *flags,
            '-o', str(evidence / 'forbidden-application')], project,
            environment(tools, request_path), deadline, execute)
        request.verify()
        record = inputs.read(evidence / filename, maximum=inventory.MAX_RECORD)
        records[mode] = record
        sources.verify()
        tools.verify()
    function = records['inspect'].value()
    inventory.function_document(function, sources, 'inspect')
    modules.document(records['module-inspect'].value(), sources, entry, crate_name=CRATE)
    bodies.document(records['binding-inspect'].value(), sources, crate_name=CRATE, functions=function)
    if lifetime:
        lifetimes.document(records['lifetime-inspect'].value(), sources, target=tools.compiler.host)
    expected = names(lifetime)
    require(file_set(evidence, expected) == expected, 'Rust original query outputs differ')
    files = tuple(inputs.capture(evidence / name) for name in sorted(expected))
    for file in held:
        file.verify()
    manifest = publish(evidence / 'original-query.json',
                       summary(tools, held, entry, optimisation, lifetime, files))
    result = Context(tools, sources, held, evidence, inputs.directory(evidence),
        entry, optimisation, (*files, manifest.file), records['inspect'], records['module-inspect'],
        records['binding-inspect'], records.get('lifetime-inspect'), manifest)
    result.verify()
    return result
