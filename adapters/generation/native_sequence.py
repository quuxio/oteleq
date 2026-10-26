"""Freeze native controlled calls and decode each original scalar frame separately."""

import copy
from pathlib import Path
import re

import native_inputs
import native_lifetime_policy
from native_protocol import encoded, fields, require, same
from otelc_capture import strict_json

MAX_BYTES = 8 * 1024 * 1024
KIND = 'oteleq.native.scalar-sequence'


def configuration(entry: dict, value: list[dict]) -> None:
    """Only the explicit prepared free-function profile currently owns this driver."""
    require(entry.get('language') in ('c', 'cpp') and entry.get('native_backend') == 'prepared'
            and native_lifetime_policy.kind(entry) is None
            and not any(key in entry for key in ('receiver_fixture', 'cpp_receiver'))
            and entry.get('cpp_function', {}).get('kind', 'FunctionDecl') == 'FunctionDecl',
            'native live calls require prepared function-only free functions')
    require(type(value) is list and 1 <= len(value) <= 32,
            'native live sequence requires 1 to 32 calls')
    for step in value:
        require(type(step) is dict and {'action', 'arguments', 'metrics'} <= set(step)
                <= {'action', 'arguments', 'metrics', 'expected_baseline'}
                and step['action'] == 'call' and step['arguments'] == 'case',
                'native live calls currently require the unchanged case arguments')
        fields(step['metrics'], {'collection', 'emission'}, 'native call metrics')
        require(all(type(flag) is bool for flag in step['metrics'].values()),
                'native live flags must be booleans')
    require(any(all(step['metrics'].values()) for step in value),
            'native live sequence requires a collection-on/emission-on positive control')


def concrete(entry: dict, sequence: list[dict], arguments: list) -> tuple[dict, ...]:
    """Bind concrete case calls to the original configuration before any launch."""
    requested = entry.get('sequence_configuration')
    configuration(entry, requested)
    require(type(sequence) is list and len(sequence) == len(requested),
            'native concrete sequence differs from its declared call count')
    for index, (actual, declared) in enumerate(zip(sequence, requested, strict=True)):
        fields(actual, {'id', 'action', 'arguments', 'metrics', 'expected_baseline'},
               'native concrete call')
        expected = {'id': 'step-' + str(index), 'action': 'call', 'arguments': arguments,
                    'metrics': declared['metrics'],
                    'expected_baseline': declared.get('expected_baseline', entry['expected_baseline'])}
        require(same(actual, expected), 'native concrete call or baseline expectation changed')
    return tuple(copy.deepcopy(sequence))


def container(frames: tuple[native_inputs.File, ...], sequence: tuple[dict, ...]) -> bytes:
    """The host packages exact application bytes; it does not rewrite their values."""
    require(len(frames) == len(sequence) and 1 <= len(frames) <= 32,
            'native scalar frame count differs from its declared calls')
    rows = []
    for frame, step in zip(frames, sequence, strict=True):
        frame.verify()
        require(type(frame.content) is bytes and bool(frame.content), 'native scalar frame is empty')
        rows.append({'id': step['id'], 'raw_hex': frame.content.hex()})
    raw = (encoded({'schema_version': 1, 'kind': KIND, 'frames': rows}) + '\n').encode()
    require(len(raw) <= MAX_BYTES, 'native scalar sequence exceeds its byte budget')
    return raw


def decode(raw: bytes, entry: dict) -> dict:
    """Decode fixed global-count framing independently for every declared call."""
    from typed_capture import scalar_capture

    configuration(entry, entry.get('sequence_configuration'))
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, 'invalid native scalar sequence size')
    value = fields(strict_json(raw), {'schema_version', 'kind', 'frames'}, 'native scalar sequence')
    require(same(value['schema_version'], 1) and value['kind'] == KIND
            and type(value['frames']) is list
            and len(value['frames']) == len(entry['sequence_configuration']),
            'native scalar sequence schema or denominator differs')
    result = []
    for index, row in enumerate(value['frames']):
        fields(row, {'id', 'raw_hex'}, 'native scalar frame')
        require(row['id'] == 'step-' + str(index) and type(row['raw_hex']) is str
                and re.fullmatch('(?:[0-9a-f]{2})+', row['raw_hex']) is not None,
                'native scalar frame identity or byte encoding differs')
        before, outcome, after = scalar_capture(bytes.fromhex(row['raw_hex']), entry)
        result.append({'id': row['id'], 'action': 'call', 'gaps': [],
                       'before': before, 'outcome': outcome, 'after': after})
    return {'before': result[0]['before'], 'outcome': result[-1]['outcome'],
            'after': result[-1]['after'], 'steps': result}


def publish(path: Path, raw: bytes, maximum: int) -> native_inputs.File:
    """Keep the host-created container under the caller's original capture budget."""
    import os

    require(type(maximum) is int and maximum > 0 and len(raw) <= min(maximum, MAX_BYTES),
            'native sequence exceeds the original case capture budget')
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw)
    return native_inputs.capture(path, maximum=min(maximum, MAX_BYTES), private=True, keep=True)
