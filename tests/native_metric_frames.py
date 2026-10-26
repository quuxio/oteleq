"""Compare original native scalar frames to independently prescribed workloads."""

import json
import os
from pathlib import Path
import re
import stat

import native_prepared_receipt as retained
from native_prepared_otlp import require, same

ABI_TYPES = {'int', 'long', 'short', 'signed', 'signed int', 'long long', 'unsigned',
             'unsigned int', 'unsigned long', 'unsigned short', 'unsigned long long',
             'char', 'signed char', 'unsigned char', 'float', 'double'}
GLOBALS = {'state', 'calls', 'depth'}


def loads(raw: bytes) -> dict:
    """Keep duplicate keys and nonfinite values outside the fixture wire contract."""
    def pairs(rows):
        value = {}
        for key, item in rows:
            require(key not in value, 'duplicate native fixture JSON field')
            value[key] = item
        return value
    def nonfinite(value):
        raise ValueError('nonfinite native fixture value: ' + value)
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    require(type(value) is dict, 'native fixture JSON is not an object')
    return value


def frame(raw: bytes, entry: dict, expected: dict) -> None:
    """Reconstruct the entire fixed body, preserving newlines inside exception data."""
    require(type(raw) is bytes and 0 < len(raw) <= 4 * 1024**2, 'invalid native fixture frame size')
    header, separator, body = raw.partition(b'\n')
    require(bool(separator) and header.startswith(b'abi:'), 'missing native fixture ABI')
    abi = loads(header[4:])
    same(sorted(abi), sorted(('byte_order', 'char_signed', 'char_bits', 'ieee754', 'bits')))
    require(abi['byte_order'] in ('little', 'big') and type(abi['char_signed']) is bool
            and type(abi['ieee754']) is bool and type(abi['char_bits']) is int and abi['char_bits'] == 8,
            'unsupported native fixture representation')
    require(type(abi['bits']) is dict and set(abi['bits']) == ABI_TYPES
            and all(type(value) is int and value in (8, 16, 32, 64, 128) for value in abi['bits'].values())
            and abi['bits']['int'] == 32, 'native fixture requires the declared int32 ABI')
    require(entry['language'] in ('c', 'cpp') and entry['output'] == 'int'
            and len(entry['globals']) == 3 and {item['name'] for item in entry['globals']} == GLOBALS
            and all(item['type'] == 'int' for item in entry['globals']), 'native fixture roots differ')

    def integer(value: dict) -> bytes:
        same({key: value[key] for key in ('kind', 'type', 'bits', 'signed')},
             {'kind': 'integer', 'type': entry['language'] + '.int', 'bits': 32, 'signed': True})
        return int(value['value']).to_bytes(4, abi['byte_order'], signed=True).hex().encode()

    def state(graph: dict) -> bytes:
        same(sorted(graph['roots']), sorted('global:' + name for name in GLOBALS))
        same(graph['nodes'], [])
        return b''.join(item['name'].encode() + b':int:' + integer(graph['roots']['global:' + item['name']]) + b'\n'
                        for item in entry['globals'])

    outcome = expected['outcome']
    if outcome['kind'] == 'return':
        encoded = b'return:int:' + integer(outcome['graph']['roots']['result'])
    else:
        require(entry['language'] == 'cpp' and outcome['kind'] == 'error', 'unsupported native fixture error')
        same(outcome['graph']['roots']['error'], {'kind': 'reference', 'node_id': 'n0'})
        node, = outcome['graph']['nodes']
        same((node['id'], node['type']), ('n0', 'cpp.std::runtime_error'))
        encoded = b'error:std::runtime_error\t' + bytes.fromhex(node['fields']['message']['hex'])
    same(body.hex(), (b'before\n' + state(expected['before']) + encoded + b'\nafter\n' + state(expected['after'])).hex())


def directory(path: Path) -> None:
    info = path.lstat()
    require(path.resolve(strict=True) == path and stat.S_ISDIR(info.st_mode)
            and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
            'unsafe native fixture checkpoint directory')


def evidence(folder: Path, entry: dict, expected: list[dict]) -> None:
    """Require all four original frames and every private readiness/acknowledgement."""
    require(len(expected) == 4, 'native fixture requires four calls')
    container = folder / 'observation'
    retained.identity(container, private=True)
    value = loads(container.read_bytes())
    same(sorted(value), ['frames', 'kind', 'schema_version'])
    same(value['schema_version'], 1); same(value['kind'], 'oteleq.native.scalar-sequence')
    require(type(value['frames']) is list and len(value['frames']) == 4, 'missing original native frames')
    rendezvous = folder / 'native-rendezvous'; directory(rendezvous)
    phases = [phase + '-' + str(index) for index in range(4) for phase in ('before', 'after')] + ['finish']
    names = {phase + '.' + suffix for phase in phases for suffix in ('ready', 'ready.json', 'resume', 'resume.json')}
    names.update('step-' + str(index) + '.observation' for index in range(4))
    same(sorted(path.name for path in rendezvous.iterdir()), sorted(names))
    nonce = None
    for phase in phases:
        for action in ('ready', 'resume'):
            flag = rendezvous / (phase + '.' + action); directory(flag)
            require(not any(flag.iterdir()), 'native fixture checkpoint flag is not empty')
            path = rendezvous / (phase + '.' + action + '.json')
            retained.identity(path, private=True)
            row = retained.read(path)
            require(type(row.get('nonce')) is str and re.fullmatch('[0-9a-f]{32}', row['nonce']) is not None,
                    'invalid native fixture nonce')
            nonce = row['nonce'] if nonce is None else nonce
            same(row, {'nonce': nonce, 'phase': phase})
    for index, (row, step) in enumerate(zip(value['frames'], expected, strict=True)):
        same(sorted(row), ['id', 'raw_hex']); same(row['id'], 'step-' + str(index))
        require(type(row['raw_hex']) is str and re.fullmatch('(?:[0-9a-f]{2})+', row['raw_hex']) is not None,
                'invalid original native fixture frame encoding')
        path = rendezvous / ('step-' + str(index) + '.observation')
        retained.identity(path, private=True)
        raw = path.read_bytes()
        same(raw.hex(), row['raw_hex']); frame(raw, entry, step)
