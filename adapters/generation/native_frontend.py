"""Build and invoke a compiler-matched project inventory/preprocessor observer."""
import hashlib
import json
import os
from pathlib import Path
import shlex

from otelc_capture import strict_json
import native_dependencies

MAX_METADATA_BYTES = 16 * 1024 * 1024


def require(condition: bool, reason: str) -> None:
    """Compiler metadata gaps cannot become successful callable inventories."""
    if not condition:
        raise ValueError('native frontend: ' + reason)


def digest(path: Path) -> str:
    """Bind actual compiler, library, helper and header bytes."""
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def query(program: Path, arguments: list[str], directory: Path, execute) -> str:
    """Read a selected tool's bounded output without shell evaluation."""
    result = execute([program, *arguments], directory)
    require(result.returncode == 0, 'tool configuration query failed')
    return result.stdout.decode('utf-8', errors='strict').strip()


def development_tools(compiler: Path, directory: Path, execute) -> dict:
    """The frontend headers and libraries must belong to the selected compiler."""
    prefix = compiler.resolve(strict=True).parent.parent
    config = prefix / 'bin/llvm-config'
    builder = prefix / 'bin/clang++'
    scanner = prefix / 'bin/clang-scan-deps'
    require(all(path.is_file() for path in (config, builder, scanner)),
            'matching llvm-config, clang++ and clang-scan-deps are required')
    include = Path(query(config, ['--includedir'], directory, execute))
    library = Path(query(config, ['--libdir'], directory, execute))
    require(include.resolve() == (prefix / 'include').resolve()
            and library.resolve() == (prefix / 'lib').resolve(), 'development paths differ from the selected compiler')
    require((include / 'clang/Tooling/Tooling.h').is_file(), 'matching Clang development headers are required')
    clang_libraries = {path.resolve() for path in library.glob('libclang-cpp.*') if path.is_file()}
    require(len(clang_libraries) == 1, 'expected one matched Clang tooling library')
    llvm_names = shlex.split(query(config, ['--link-shared', '--libnames'], directory, execute))
    require(bool(llvm_names) and all(Path(name).name == name and (library / name).is_file()
                                    for name in llvm_names), 'missing matched shared LLVM libraries')
    major = int(query(config, ['--version'], directory, execute).split('.')[0])
    require(major == int(query(compiler, ['-dumpversion'], directory, execute).split('.')[0]),
            'compiler and development library versions differ')
    return {'compiler': builder, 'config': config, 'scanner': scanner, 'include': include,
            'libraries': [next(iter(clang_libraries)), *(library / name for name in llvm_names)],
            'library_directory': library, 'major': major,
            'system_flags': shlex.split(query(config, ['--link-shared', '--system-libs'], directory, execute)),
            'no_rtti': query(config, ['--has-rtti'], directory, execute) == 'NO'}


def build(compiler: Path, destination: Path, source_root: Path, execute) -> dict:
    """Compile maintained helper source outside the application and freeze its inputs."""
    require(not destination.resolve().is_relative_to(source_root.resolve()), 'helper must be outside application source')
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    tools = development_tools(compiler, destination, execute)
    source = destination / 'source'
    source.mkdir(mode=0o700)
    original = Path(__file__).with_name('native_discover.cpp')
    (source / original.name).write_bytes(original.read_bytes())
    flags = ['-std=c++17', '-fno-exceptions', '-I', str(tools['include'])]
    if tools['no_rtti']:
        flags.append('-fno-rtti')
    unit = {'source': original.name, 'directory': '.', 'flags': flags}
    dependencies = native_dependencies.inspect(unit, source, tools['compiler'], tools['scanner'],
                                               destination / 'dependency-evidence', execute)
    binary = destination / 'native-discover'
    command = [tools['compiler'], *flags, source / original.name, *tools['libraries'],
               *tools['system_flags'], '-Wl,-rpath,' + str(tools['library_directory']), '-o', binary]
    (destination / 'build-command.json').write_text(json.dumps(list(map(str, command))) + '\n')
    result = execute(command, destination)
    (destination / 'build.stdout').write_bytes(result.stdout)
    (destination / 'build.stderr').write_bytes(result.stderr)
    require(result.returncode == 0, 'helper build failed: ' + result.stderr.decode(errors='replace')[-2000:])
    external = {}
    for path in [tools['compiler'], tools['config'], tools['scanner'], *tools['libraries']]:
        external[str(path)] = {'resolved': str(path.resolve()), 'sha256': digest(path)}
    record = {'schema_version': 1, 'clang_major': tools['major'], 'compiler': str(compiler.resolve()),
              'source_sha256': digest(original),
              'assets': {'native-discover': digest(binary), 'source/' + original.name: digest(source / original.name)},
              'external': external, 'dependencies': dependencies}
    verify(record, destination)
    (destination / 'identity.json').write_text(json.dumps(record, indent=2) + '\n')
    return record


def verify(record: dict, directory: Path) -> None:
    """Retained and exported helpers use the same source, executable and tool inputs."""
    require(record['source_sha256'] == digest(Path(__file__).with_name('native_discover.cpp')),
            'maintained compiler helper changed')
    for name, expected in record['assets'].items():
        path = directory / name
        require(path.is_file() and not path.is_symlink() and digest(path) == expected, 'helper asset changed: ' + name)
    dependencies = {**record['dependencies'], **record['external']}
    for name, item in dependencies.items():
        path = directory / 'source' / item['source_relative'] if item.get('source_relative') else Path(name)
        require(path.is_file() and (item.get('source_relative') or str(path.resolve()) == item['resolved'])
                and digest(path) == item['sha256'], 'helper compiler/library/header changed: ' + name)


def document(raw: bytes, major: int) -> dict:
    """Only complete metadata from the declared compiler version is admitted."""
    require(len(raw) <= MAX_METADATA_BYTES, 'metadata exceeds its byte budget')
    data = strict_json(raw)
    require(type(data) is dict and set(data) == {'schema_version', 'clang_major', 'complete', 'files', 'probes', 'ast'},
            'unsupported metadata fields')
    require(type(data['schema_version']) is int and data['schema_version'] == 1
            and type(data['clang_major']) is int and data['clang_major'] == major and data['complete'] is True,
            'incomplete metadata or compiler version mismatch')
    files = data['files']
    require(type(files) is list and 1 <= len(files) <= 10000
            and all(type(name) is str and 0 < len(name) <= 8192 and '\0' not in name for name in files)
            and len(files) == len(set(files)),
            'invalid compiler input paths')
    require(type(data['probes']) is list and len(data['probes']) <= 10000, 'invalid preprocessor probe list')
    for probe in data['probes']:
        require(type(probe) is dict and set(probe) == {'kind', 'source', 'offset', 'name', 'angled', 'target'}
                and probe['kind'] in ('include', 'has-embed', 'embed') and type(probe['angled']) is bool
                and type(probe['offset']) is int and probe['offset'] >= 0, 'invalid preprocessor probe')
        require(all(type(probe[name]) is str and 0 < len(probe[name]) <= 8192 and '\0' not in probe[name]
                    for name in ('source', 'name')) and probe['source'] in files
                and (probe['target'] is None or probe['target'] in files), 'unbound preprocessor probe path')
    require(type(data['ast']) is dict and set(data['ast']) == {'kind', 'inner'}
            and data['ast']['kind'] == 'TranslationUnitDecl' and type(data['ast']['inner']) is list
            and all(type(item) is dict for item in data['ast']['inner']),
            'invalid project AST')
    return data


def input_state(data: dict, unit: dict, project: Path) -> dict:
    """Existence-only probes carry inputs even when Clang never includes the file."""
    directory = project / unit['directory']
    records = native_dependencies.file_records(data['files'], project, directory)
    require(str((project / unit['source']).resolve()) in {item['resolved'] for item in records.values()},
            'compiler omitted the selected translation unit')
    probes = []
    for item in data['probes']:
        binding = item.copy()
        for name in ('source', 'target'):
            if binding[name] is not None:
                binding[name] = os.path.abspath(directory / binding[name])
        probes.append(binding)
    return {'dependencies': records, 'probes': probes}


def inspect(unit: dict, project: Path, record: dict, directory: Path, evidence: Path,
            execute, *, mode: str = 'ast') -> dict:
    """Parse a real compile context without executing application initialisers."""
    require(mode in ('ast', 'inputs'), 'mode requires ast or inputs')
    require(not evidence.resolve().is_relative_to(project.resolve()), 'metadata evidence must be outside application source')
    require(Path(unit['compiler']).resolve() == Path(record['compiler']).resolve(),
            'compile unit selected a different compiler')
    require((project / unit['source']).resolve().is_relative_to(project.resolve())
            and (project / unit['directory']).resolve().is_relative_to(project.resolve()),
            'compile unit paths escape the application')
    verify(record, directory)
    evidence.mkdir(mode=0o700, parents=True, exist_ok=False)
    command = [directory / 'native-discover', project, mode, unit['compiler'],
               *unit['flags'], '-fsyntax-only', project / unit['source']]
    (evidence / 'request.json').write_text(json.dumps({'command': list(map(str, command)),
        'directory': str(project / unit['directory'])}) + '\n')
    result = execute(command, project / unit['directory'])
    (evidence / 'metadata.json').write_bytes(result.stdout)
    (evidence / 'stderr').write_bytes(result.stderr)
    require(result.returncode == 0, 'compiler query failed: ' + result.stderr.decode(errors='replace')[-2000:])
    data = document(result.stdout, record['clang_major'])
    verify(record, directory)
    return data
