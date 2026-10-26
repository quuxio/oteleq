"""Independently validate rebuilt Rust drop discovery and complete MIR bindings."""

import hashlib
import json
from pathlib import Path

import native_inputs as inputs
from native_lifetime_inventory import selection
from native_protocol import encoded, fields, require, same
from otelc_capture import strict_json
import rust_inventory as inventory
from rust_tools import canonical_directory

VALUE_FIELDS = {'local', 'role', 'source', 'compiler_type', 'rendered_type', 'kind',
                'needs_drop', 'size', 'alignment', 'layout_error'}
UNAVAILABLE_FIELDS = {'local', 'role', 'compiler_type', 'rendered_type', 'kind', 'needs_drop'}
SITE_FIELDS = {'kind', 'block', 'statement', 'local', 'other', 'projected', 'cleanup', 'unwind'}
SITE_KINDS = {'construction', 'assignment', 'move', 'copy', 'aggregate_input', 'drop', 'call_return', 'call_argument'}


def number(value: object, limit: int) -> int:
    """Keep booleans/floats and out-of-range MIR indices explicit."""
    require(type(value) is int and 0 <= value < limit, 'invalid Rust lifetime integer position/limit')
    return value


def role(local: int, body: dict) -> str:
    """The actual local number distinguishes returns, arguments and local storage."""
    return 'return' if local == 0 else 'argument' if local <= body['argument_count'] else 'local'


def typed_local(value: object, body: dict, sources: inventory.Sources, files: dict[str, inputs.File]) -> int:
    """Bind an original ADT declaration and preserve unavailable layout evidence."""
    row = fields(value, VALUE_FIELDS, 'Rust lifetime value')
    inventory.declaration(row['source'], sources.root, files, nonempty=True)
    local = number(row['local'], body['local_count'])
    require(row['role'] == role(local, body) and type(row['kind']) is str
            and row['kind'] in ('struct', 'enum', 'union') and type(row['needs_drop']) is bool
            and type(row['rendered_type']) is str and bool(row['rendered_type'])
            and row['compiler_type'] == row['source']['compiler_name'], 'invalid Rust lifetime type/role')
    if row['layout_error'] is None:
        number(row['size'], 2**64)
        alignment = number(row['alignment'], 2**64)
        require(bool(alignment) and not alignment & (alignment - 1), 'invalid Rust lifetime alignment')
    else:
        require(type(row['layout_error']) is str and bool(row['layout_error'])
                and row['size'] is None and row['alignment'] is None, 'invalid Rust unavailable layout')
    return local


def unavailable_local(value: object, body: dict) -> int:
    """Foreign/container/opaque values stay visible without invented source origins."""
    row = fields(value, UNAVAILABLE_FIELDS, 'Rust unavailable lifetime value')
    local = number(row['local'], body['local_count'])
    require(row['role'] == role(local, body) and type(row['needs_drop']) is bool
            and type(row['kind']) is str and row['kind'] in ('foreign_adt', 'array', 'tuple', 'opaque')
            and all(type(row[key]) is str and bool(row[key]) for key in ('compiler_type', 'rendered_type')),
            'invalid Rust unavailable lifetime type/role')
    return local


def site(value: object, body: dict, locals_: set[int]) -> None:
    """Validate ownership sites while keeping projections and cleanup flags explicit."""
    row = fields(value, SITE_FIELDS, 'Rust lifetime site')
    require(type(row['kind']) is str and row['kind'] in SITE_KINDS
            and type(row['local']) is int and row['local'] in locals_
            and all(type(row[key]) is bool for key in ('projected', 'cleanup'))
            and (row['unwind'] is None or type(row['unwind']) is str)
            and ((row['kind'] == 'drop') == (type(row['unwind']) is str and bool(row['unwind']))),
            'invalid Rust lifetime ownership site')
    number(row['block'], body['block_count'])
    if row['statement'] is not None:
        number(row['statement'], 2**32)
    if row['other'] is not None:
        number(row['other'], body['local_count'])


def body(value: object, sources: inventory.Sources, files: dict[str, inputs.File]) -> dict:
    """Check every body before applying exclusions, including all unavailable locals."""
    row = fields(value, {'function', 'phase', 'local_count', 'block_count', 'argument_count',
                         'locals', 'unavailable_locals', 'sites'}, 'Rust lifetime body')
    inventory.declaration(row['function'], sources.root, files, nonempty=True)
    require(row['phase'] == 'Runtime(PostCleanup)' and type(row['locals']) is list
            and len(row['locals']) <= 65536 and type(row['unavailable_locals']) is list
            and len(row['unavailable_locals']) <= 65536 and type(row['sites']) is list
            and len(row['sites']) <= 262144 and not row['function']['asynchronous']
            and not row['function']['expanded'], 'invalid Rust lifetime body phase/bounds')
    number(row['local_count'], 65537)
    require(number(row['block_count'], 65537) > 0, 'Rust lifetime body has no blocks')
    number(row['argument_count'], row['local_count'])
    locals_ = [typed_local(item, row, sources, files) for item in row['locals']]
    unavailable = [unavailable_local(item, row) for item in row['unavailable_locals']]
    require(len(locals_) == len(set(locals_)) and len(unavailable) == len(set(unavailable))
            and not set(locals_).intersection(unavailable), 'overlapping Rust lifetime local bindings')
    selected = set(locals_)
    for item in row['sites']:
        site(item, row, selected)
    return row


def document(value: object, sources: inventory.Sources, *, target: str) -> dict:
    """Bind the version-two drop discovery to the independent selected compiler host."""
    require(type(sources) is inventory.Sources and type(target) is str and bool(target),
            'Rust lifetime inventory needs caller-held sources and target')
    sources.verify()
    row = fields(value, {'schema_version', 'kind', 'sources', 'target', 'pointer_width', 'bodies',
                         'skipped', 'source_complete', 'instrumentation_complete'}, 'Rust lifetime inventory')
    require(same(row['schema_version'], 2) and row['kind'] == 'otelc.rust.lifetime-inventory'
            and same(row['sources'], sources.hashes()) and row['target'] == target
            and same(row['pointer_width'], 64) and row['source_complete'] is False
            and row['instrumentation_complete'] is False and type(row['bodies']) is list
            and len(row['bodies']) <= 65536 and type(row['skipped']) is list and len(row['skipped']) <= 65536
            and len(encoded(row).encode()) <= inventory.MAX_RECORD, 'invalid Rust lifetime discovery profile')
    files = {str(file.path): file for file in sources.files}
    identities = set()
    for item in row['bodies']:
        parsed = body(item, sources, files)
        name = parsed['function']['identity']
        require(name not in identities, 'duplicate Rust lifetime body')
        identities.add(name)
    for item in row['skipped']:
        skipped = fields(item, {'function', 'reason'}, 'Rust skipped body')
        inventory.declaration(skipped['function'], sources.root, files, nonempty=True)
        name = skipped['function']['identity']
        require(type(skipped['reason']) is str and skipped['reason'] in ('const', 'async', 'closure', 'expanded')
                and name not in identities, 'invalid or repeated Rust skipped body')
        identities.add(name)
    return strict_json(encoded(row))


def selected_locals(body: dict, root: Path, source_pattern: dict, type_pattern: dict) -> list[dict]:
    """Apply type/source rules without losing selected unavailable values."""
    excluded = {'include': type_pattern['exclude'], 'exclude': []}
    unavailable = [row for row in body['unavailable_locals']
        if not any(selection(excluded, row[key]) for key in ('compiler_type', 'rendered_type'))
        and any(selection(type_pattern, row[key]) for key in ('compiler_type', 'rendered_type'))]
    require(not unavailable, 'selected Rust lifetime type is unavailable')
    return [row for row in body['locals'] if selection(source_pattern,
        Path(row['source']['file']).relative_to(root).as_posix(), path=True)
        and selection(type_pattern, row['rendered_type'])]


def request(value: object, sources: inventory.Sources, policy: dict, *, target: str) -> dict:
    """Select original locals and hash each complete, unfiltered MIR body."""
    parsed = document(value, sources, target=target)
    source_pattern = inventory.patterns(policy['sources'])
    lifetime = policy['lifetimes']
    require(type(lifetime) is dict and type(lifetime.get('enabled')) is bool, 'invalid Rust lifetime policy flag')
    type_pattern = inventory.patterns({key: lifetime.get(key) for key in ('include', 'exclude')})
    locals_, fingerprints = {}, {}
    for item in parsed['bodies']:
        relative = Path(item['function']['file']).relative_to(sources.root).as_posix()
        if not lifetime['enabled'] or not selection(source_pattern, relative, path=True):
            continue
        selected = selected_locals(item, sources.root, source_pattern, type_pattern)
        if selected:
            identity = item['function']['identity']
            locals_[identity] = {str(row['local']): row['compiler_type'] for row in selected}
            raw = json.dumps(item, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
            fingerprints[identity] = hashlib.sha256(raw).hexdigest()
    return inventory.bindings({'schema_version': 2, 'lifetimes': locals_, 'lifetime_bodies': fingerprints})


def read(directory: Path, sources: inventory.Sources, *, target: str) -> inputs.Record:
    """Retain the original fixed discovery record and its file facts."""
    canonical_directory(directory)
    record = inputs.read(directory / 'lifetime-inspect-inventory.json', maximum=inventory.MAX_RECORD)
    document(record.value(), sources, target=target)
    return record
