"""Bind rebuilt Rust compiler declarations to caller-held original source files."""

from dataclasses import dataclass
from pathlib import Path
import re

import native_inputs as inputs
from native_lifetime_inventory import selection
from native_protocol import encoded, fields, require, same
from otelc_capture import strict_json
from rust_tools import canonical_directory

MAX_RECORD = 8 * 1024 * 1024
SOURCE_FIELDS = {'identity', 'file', 'compiler_name', 'start', 'end', 'asynchronous', 'expanded'}
MODES = ('inspect', 'weave', 'lifetime-weave')


@dataclass(frozen=True)
class Sources:
    """The caller freezes compiler-discovered paths before producer records are read."""

    root: Path
    files: tuple[inputs.File, ...]

    def verify(self) -> None:
        """Recheck original file facts without following metadata-selected paths."""
        canonical_directory(self.root)
        require(type(self.files) is tuple and 1 <= len(self.files) <= 65536
                and all(type(file) is inputs.File for file in self.files),
                'Rust inventory needs original source file expectations')
        paths = tuple(file.path for file in self.files)
        require(paths == tuple(sorted(set(paths))) and all(
            path.is_relative_to(self.root) and path.suffix == '.rs' for path in paths),
            'Rust source catalogue must contain unique ordered original Rust inputs')
        for file in self.files:
            file.verify()

    def hashes(self) -> dict[str, str]:
        """Return a fresh compiler-format source catalogue."""
        return {str(file.path): file.sha256 for file in self.files}


def capture_sources(root: Path, paths: tuple[Path, ...]) -> Sources:
    """Capture explicit caller paths; a producer inventory cannot extend them."""
    canonical_directory(root)
    require(type(paths) is tuple and 1 <= len(paths) <= 65536
            and all(isinstance(path, Path) for path in paths)
            and len(set(paths)) == len(paths), 'invalid caller Rust source denominator')
    require(all(path.is_relative_to(root) and path.suffix == '.rs' for path in paths),
            'Rust source input is outside the selected root or has another kind')
    result = Sources(root, tuple(inputs.capture(path) for path in sorted(paths)))
    result.verify()
    return result


def declaration(value: object, root: Path, files: dict[str, inputs.File], *, nonempty: bool = False) -> str:
    """Validate compiler identity and byte ranges using only the original file map."""
    row = fields(value, SOURCE_FIELDS, 'Rust source declaration')
    require(all(type(row[key]) is str and row[key] and '\0' not in row[key]
                for key in ('identity', 'file', 'compiler_name'))
            and all(type(row[key]) is bool for key in ('asynchronous', 'expanded'))
            and all(type(row[key]) is int for key in ('start', 'end'))
            and row['file'] in files, 'invalid Rust source declaration')
    file = files[row['file']]
    relative = file.path.relative_to(root).as_posix()
    require(row['identity'] == relative + '::' + row['compiler_name']
            and 0 <= row['start'] <= row['end'] <= file.size
            and (not nonempty or row['start'] < row['end']),
            'Rust declaration identity or byte range differs from its original input')
    return relative


def patterns(value: object) -> dict:
    """Keep the common source/name glob grammar and exclusion precedence."""
    row = fields(value, {'include', 'exclude'}, 'Rust selector')
    require(all(type(row[key]) is list and len(row[key]) <= 4096 and all(
        type(item) is str and 0 < len(item) <= 4096 and '\0' not in item for item in row[key])
        for key in row), 'invalid Rust selection patterns')
    return strict_json(encoded(row))


def selected_functions(policy: dict, sources: Sources, document: dict) -> list[str]:
    """Apply fixed common selectors and refuse unsupported selected bodies."""
    document = function_document(document, sources, 'inspect')
    source_pattern = patterns(policy['sources'])
    function_pattern = patterns(policy['functions'])
    result = []
    for row in document['definitions']:
        relative = Path(row['file']).relative_to(sources.root).as_posix()
        if selection(source_pattern, relative, path=True) and selection(function_pattern, row['compiler_name']):
            require(not row['asynchronous'] and not row['expanded'] and '{closure' not in row['compiler_name']
                    and len(row['identity'].encode()) <= 4096,
                    'selected Rust async, expanded, closure or oversized body needs its completion profile')
            result.append(row['identity'])
    return result


def bindings(value: object) -> dict:
    """Validate caller-held lifetime requests before comparing woven metadata."""
    row = fields(value, {'schema_version', 'lifetimes', 'lifetime_bodies'}, 'Rust lifetime request')
    require(same(row['schema_version'], 2) and type(row['lifetimes']) is dict
            and type(row['lifetime_bodies']) is dict
            and set(row['lifetimes']) == set(row['lifetime_bodies'])
            and len(row['lifetimes']) <= 65536, 'invalid Rust lifetime binding denominator')
    for identity, locals_ in row['lifetimes'].items():
        require(type(identity) is str and identity and type(locals_) is dict
                and 1 <= len(locals_) <= 65536 and all(type(key) is str
                    and re.fullmatch(r'0|[1-9][0-9]*', key) and int(key) < 65536
                    and type(name) is str and name for key, name in locals_.items()),
                'invalid Rust lifetime local binding')
        fingerprint = row['lifetime_bodies'][identity]
        require(type(fingerprint) is str and re.fullmatch('[a-f0-9]{64}', fingerprint) is not None,
                'invalid Rust complete MIR body fingerprint')
    return strict_json(encoded(row))


def function_document(value: object, sources: Sources, mode: str, *, lifetime_request: dict | None = None) -> dict:
    """Read either function inventory format without certifying compiler execution."""
    require(type(sources) is Sources and type(mode) is str and mode in MODES, 'unsupported Rust inventory context/mode')
    sources.verify()
    lifetime = mode == 'lifetime-weave'
    names = {'schema_version', 'kind', 'mode', 'definitions', 'sources', 'source_complete'}
    if lifetime:
        names |= {'lifetimes', 'lifetime_bodies', 'instrumentation_complete'}
    row = fields(value, names, 'Rust compiler inventory')
    require(same(row['schema_version'], 2 if lifetime else 1)
            and row['kind'] == ('otelc.rust.lifetime-weave' if lifetime else 'otelc.rust.compiler-inventory')
            and row['mode'] == mode and same(row['sources'], sources.hashes())
            and row['source_complete'] is False and type(row['definitions']) is list
            and len(row['definitions']) <= 65536 and len(encoded(row).encode()) <= MAX_RECORD,
            'Rust compiler inventory differs from its fixed original-source profile')
    files = {str(file.path): file for file in sources.files}
    for item in row['definitions']:
        declaration(item, sources.root, files)
    identities = [item['identity'] for item in row['definitions']]
    require(identities == sorted(set(identities)), 'Rust compiler declarations must be ordered and unique')
    if lifetime:
        expected = bindings(lifetime_request)
        require(set(expected['lifetimes']) <= set(identities)
                and same(row['lifetimes'], expected['lifetimes'])
                and same(row['lifetime_bodies'], expected['lifetime_bodies'])
                and row['instrumentation_complete'] is False,
                'Rust woven lifetime bindings differ from caller-held discovery')
    else:
        require(lifetime_request is None, 'function-only Rust inventory has a lifetime request')
    return strict_json(encoded(row))


def read_functions(directory: Path, sources: Sources, mode: str, *, lifetime_request: dict | None = None) -> inputs.Record:
    """Read a fixed inventory name; producer metadata cannot choose a new file."""
    canonical_directory(directory)
    require(type(mode) is str and mode in MODES, 'unsupported Rust inventory filename')
    record = inputs.read(directory / (mode + '-inventory.json'), maximum=MAX_RECORD)
    function_document(record.value(), sources, mode, lifetime_request=lifetime_request)
    return record
