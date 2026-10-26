"""Bind original Rust module routes to independent, caller-frozen source files."""

from pathlib import Path

import native_inputs as inputs
from native_protocol import encoded, fields, require, same
from otelc_capture import path_within, strict_json
from rust_inventory import MAX_RECORD, Sources
from rust_tools import canonical_directory

HEADER = {'schema_version', 'kind', 'mode', 'crate_name', 'byte_coordinates',
          'sources', 'modules', 'source_complete'}
MODULE = {'compiler_name', 'parent', 'kind', 'declaration', 'body', 'eligible', 'reason'}
LOCATION = {'file', 'start', 'end', 'expanded'}


def name(value: object) -> bool:
    """The compiler's crate-relative root is the empty name."""
    return type(value) is str and '\0' not in value and len(value.encode()) <= 4096


def location(value: object, files: dict[str, inputs.File]) -> dict:
    """A producer cannot choose another file or change integer byte coordinates."""
    row = fields(value, LOCATION, 'Rust module location')
    require(type(row['file']) is str and row['file'] in files
            and type(row['expanded']) is bool
            and type(row['start']) is type(row['end']) is int
            and 0 <= row['start'] <= row['end'] <= files[row['file']].size,
            'Rust module location is outside its original source bytes')
    return row


def original_boundaries(rows: list[dict], files: dict[str, inputs.File]) -> None:
    """Recheck original bytes and refuse coordinates inside a UTF-8 code point."""
    positions = {}
    for row in rows:
        for field in ('declaration', 'body'):
            where = row[field]
            positions.setdefault(where['file'], set()).update((where['start'], where['end']))
    for path, offsets in positions.items():
        expected = files[path]
        actual = inputs.capture(expected.path, maximum=MAX_RECORD, keep=True)
        require(same(actual.gate_identity(), expected.gate_identity()),
                'Rust module source identity changed during observation')
        raw = actual.content
        raw.decode('utf-8')
        require(all(offset == len(raw) or raw[offset] & 0xc0 != 0x80 for offset in offsets),
                'Rust module byte coordinate splits original UTF-8')


def document(value: object, sources: Sources, entry: Path, *, crate_name: str) -> dict:
    """Validate a compiler statement without claiming compiler execution or access."""
    require(type(sources) is Sources and isinstance(entry, Path) and name(crate_name)
            and bool(crate_name), 'Rust modules need caller-held original source and crate identity')
    sources.verify()
    files = {str(file.path): file for file in sources.files}
    require(str(entry) in files and all(file.size <= MAX_RECORD for file in sources.files),
            'Rust module entry or source size differs from its selected inputs')
    row = fields(value, HEADER, 'Rust module inventory')
    require(same(row['schema_version'], 1) and row['kind'] == 'otelc.rust.module-inventory'
            and row['mode'] == 'module-inspect' and same(row['crate_name'], crate_name)
            and same(row['sources'], sources.hashes()) and row['source_complete'] is False
            and row['byte_coordinates'] == 'original-utf8'
            and type(row['modules']) is list and 1 <= len(row['modules']) <= 65536
            and len(encoded(row).encode()) <= MAX_RECORD,
            'Rust module inventory differs from its caller-held profile')
    rows = row['modules']
    for item in rows:
        module = fields(item, MODULE, 'Rust module')
        require(name(module['compiler_name']) and type(module['kind']) is str
                and module['kind'] in ('crate', 'inline', 'external')
                and type(module['eligible']) is bool
                and (module['reason'] is None or type(module['reason']) is str
                     and module['reason'] in ('expanded', 'block_module'))
                and module['eligible'] == (module['reason'] is None),
                'invalid Rust module identity or availability')
        declaration, body = (location(module[key], files) for key in ('declaration', 'body'))
        require(not (declaration['expanded'] or body['expanded']) or module['reason'] == 'expanded',
                'expanded Rust module cannot gain an original caller route')
        if module['kind'] == 'crate':
            require(module['compiler_name'] == '' and module['parent'] is None
                    and same(declaration, body) and body['file'] == str(entry) and module['eligible'],
                    'Rust module root differs from the original crate entry')
        else:
            require(bool(module['compiler_name']) and name(module['parent'])
                    and module['parent'] == module['compiler_name'].rpartition('::')[0]
                    and (module['kind'] == 'inline') == (declaration['file'] == body['file']),
                    'Rust module parent or physical kind differs from its original route')
    names = [item['compiler_name'] for item in rows]
    require(names == sorted(set(names)) and sum(item['kind'] == 'crate' for item in rows) == 1,
            'Rust module routes must be ordered, unique and rooted')
    by_name = dict(zip(names, rows, strict=True))
    for module in rows:
        if module['kind'] == 'crate':
            continue
        parent = by_name.get(module['parent'])
        declaration, body = module['declaration'], module['body']
        if parent is not None and not declaration['expanded']:
            owner = parent['body']
            require(declaration['file'] == owner['file']
                    and owner['start'] <= declaration['start'] <= declaration['end'] <= owner['end'],
                    'Rust module declaration is outside its original parent body')
        if module['kind'] == 'inline' and not declaration['expanded'] and not body['expanded']:
            require(declaration['start'] <= body['start'] <= body['end'] <= declaration['end'],
                    'Rust inline module body is outside its original declaration')
        require(not module['eligible'] or parent is not None and parent['eligible'],
                'Rust caller route lacks an eligible original module ancestor')
        require(module['reason'] != 'block_module' or parent is None or parent['reason'] == 'block_module',
                'Rust block-module reason contradicts its original parent')
        require(module['reason'] != 'expanded' or declaration['expanded'] or body['expanded']
                or parent is not None and parent['reason'] == 'expanded',
                'Rust expanded-module reason has no original expanded route')
    original_boundaries(rows, files)
    sources.verify()
    return strict_json(encoded(row))


def read(directory: Path, sources: Sources, entry: Path, *, crate_name: str) -> inputs.Record:
    """Read the fixed caller-selected output without accepting metadata paths."""
    canonical_directory(directory)
    require(type(sources) is Sources and not path_within(directory, sources.root),
            'Rust module inventory output overlaps original application sources')
    record = inputs.read(directory / 'module-inventory.json', maximum=MAX_RECORD)
    document(record.value(), sources, entry, crate_name=crate_name)
    record.verify()
    return record
