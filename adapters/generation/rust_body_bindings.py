"""Read original Rust typed-body fingerprints against caller-held source inputs."""

from pathlib import Path
import re

import native_inputs as inputs
from native_protocol import encoded, fields, require, same
from otelc_capture import strict_json
import rust_inventory as inventory
from rust_modules import original_boundaries

ALGORITHM = 'rustc-1.98.1-stablehash-128-v1'
HEADER = {'schema_version', 'kind', 'mode', 'crate_name', 'algorithm', 'byte_coordinates',
          'sources', 'original_body_count', 'bodies', 'helper_exclusions',
          'source_complete', 'semantic_complete'}
BODY = {'function', 'diagnostic_def_index', 'eligible', 'reason', 'fingerprints'}
REASONS = ('expanded', 'asynchronous', 'body_kind', 'const_function')


def document(value: object, sources: inventory.Sources, *, crate_name: str,
             functions: object) -> dict:
    """Keep every reported owner; unavailable owners never acquire fingerprints."""
    require(type(sources) is inventory.Sources and type(crate_name) is str
            and re.fullmatch('[A-Za-z_][A-Za-z_0-9]{0,63}', crate_name) is not None,
            'Rust body bindings need original source and crate expectations')
    original = inventory.function_document(functions, sources, 'inspect')
    row = fields(value, HEADER, 'Rust original body bindings')
    require(same(row['schema_version'], 1) and row['kind'] == 'otelc.rust.body-bindings'
            and row['mode'] == 'binding-inspect' and same(row['crate_name'], crate_name)
            and row['algorithm'] == ALGORITHM and row['byte_coordinates'] == 'original-utf8'
            and same(row['sources'], sources.hashes())
            and type(row['original_body_count']) is int
            and type(row['bodies']) is list and 0 <= len(row['bodies']) <= 65536
            and row['original_body_count'] == len(row['bodies'])
            and type(row['helper_exclusions']) is list and not row['helper_exclusions']
            and row['source_complete'] is False and row['semantic_complete'] is False
            and len(encoded(row).encode()) <= inventory.MAX_RECORD,
            'Rust original body binding profile or denominator differs')
    files = {str(file.path): file for file in sources.files}
    bodies = {}
    for item in row['bodies']:
        body = fields(item, BODY, 'Rust original body')
        inventory.declaration(body['function'], sources.root, files)
        function = body['function']
        identity = function['identity']
        require(type(body['diagnostic_def_index']) is int
                and 0 <= body['diagnostic_def_index'] < 2**32
                and type(body['eligible']) is bool
                and (body['reason'] is None or type(body['reason']) is str
                     and body['reason'] in REASONS)
                and body['eligible'] == (body['reason'] is None),
                'invalid Rust original body availability')
        if function['expanded']:
            require(body['reason'] == 'expanded', 'expanded Rust body cannot gain original access')
        elif function['asynchronous']:
            require(body['reason'] == 'asynchronous', 'async Rust body needs its completion profile')
        else:
            require(body['reason'] not in ('expanded', 'asynchronous'),
                    'Rust body availability contradicts its declaration')
        if body['eligible']:
            fingerprints = fields(body['fingerprints'],
                                  {'phase', 'pre_optimization_mir', 'typeck'}, 'Rust body fingerprints')
            require(type(fingerprints['phase']) is str and 0 < len(fingerprints['phase']) <= 256
                    and '\0' not in fingerprints['phase']
                    and all(type(fingerprints[key]) is str
                            and re.fullmatch('[a-f0-9]{32}', fingerprints[key]) is not None
                            for key in ('pre_optimization_mir', 'typeck')),
                    'invalid original Rust typed-body fingerprints')
        else:
            require(body['fingerprints'] is None, 'unavailable Rust body has invented fingerprints')
        require(identity not in bodies, 'duplicate original Rust body owner')
        bodies[identity] = body
    require(list(bodies) == sorted(bodies), 'Rust original bodies must remain ordered')
    definitions = {item['identity']: item for item in original['definitions']}
    require(all(identity in bodies and same(bodies[identity]['function'], declaration)
                for identity, declaration in definitions.items()),
            'Rust original function denominator or declarations changed')
    require(all(body['reason'] in ('body_kind', 'expanded')
                for identity, body in bodies.items() if identity not in definitions),
            'extra original Rust owner is not an unavailable non-function body')
    original_boundaries(row['bodies'], files, locations=('function',))
    sources.verify()
    return strict_json(encoded(row))


def comparison(value: object, sources: inventory.Sources, *, crate_name: str,
               functions: object) -> dict:
    """Numeric definition indices are diagnostics, excluded from stable comparison."""
    row = document(value, sources, crate_name=crate_name, functions=functions)
    return {body['function']['identity']: {key: field for key, field in body.items()
            if key != 'diagnostic_def_index'} for body in row['bodies']}


def read(directory: Path, sources: inventory.Sources, *, crate_name: str,
         functions: object) -> inputs.Record:
    """Read one fixed caller-selected result; metadata cannot select another path."""
    record = inputs.read(directory / 'binding-inspect-inventory.json', maximum=inventory.MAX_RECORD)
    document(record.value(), sources, crate_name=crate_name, functions=functions)
    record.verify()
    return record
