"""Complete fixed-workload graphs authored independently of SDK/consumer code."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'public-development-02/comparison'
SHADOWS = ('any', 'bool', 'false', 'int', 'nil', 'panic', 'true')


def number(value):
    return {'kind': 'integer', 'type': 'go.int', 'bits': 64, 'signed': True, 'value': str(value)}


def reference(index):
    return {'kind': 'reference', 'node_id': 'n' + str(index)}


def graph(value, total, calls, amount, *, outcome=None):
    nodes = {}
    roots = {'argument:0': number(amount), 'receiver': reference(14), 'global:shared': reference(12)}

    def node(index, kind, fields):
        nodes[index] = {'id': 'n' + str(index), 'type': kind, 'fields': fields}

    def location(index):
        node(index, 'go.location', {})

    def scalar(index, value, address):
        node(index, 'go.storage:*int', {'location': reference(address), 'value': number(value)})
        location(address)

    for name, index in zip(SHADOWS, (0, 2, 4, 6, 8, 10, 24)):
        scalar(index, 0, index + 1)
        roots['global:' + name] = reference(index)
    node(12, 'go.storage:**example.test/live/counter.Counter', {'location': reference(13), 'value': reference(14)})
    location(13)
    node(14, 'go.storage:*example.test/live/counter.Counter', {'location': reference(15), 'value': reference(16)})
    location(15)
    node(16, 'go.storage:example.test/live/counter.Counter',
         {'value': reference(17), 'calls': reference(18), 'self': reference(20)})
    scalar(17, value, 15)
    scalar(18, calls, 19)
    node(20, 'go.storage:**example.test/live/counter.Counter', {'location': reference(21), 'value': reference(14)})
    location(21)
    scalar(22, total, 23)
    roots['global:total'] = reference(22)
    if outcome == 'return':
        roots['result'] = number(value)
    elif outcome == 'error':
        roots['error'] = {'kind': 'string', 'type': 'go.string', 'encoding': 'raw_bytes', 'value': '6b6e6f776e'}
    assert set(nodes) == set(range(26))
    return {'nodes': [nodes[index] for index in range(26)], 'roots': roots}


def observation(value):
    assert value['observation_schema_version'] == 1 and value['gaps'] == []
    assert len(value['steps']) == 5
    assert value['before'] == graph(10, 0, 0, 3)
    total = 0
    for index, (step, amount) in enumerate(zip(value['steps'], (3, 2, 4, 1, -2))):
        assert set(step) == {'id', 'action', 'before', 'after', 'outcome', 'gaps'}
        assert step['id'] == 'step-' + str(index) and step['action'] == 'call' and step['gaps'] == []
        assert step['before'] == graph(10 + total, total, index, amount)
        total += amount
        assert step['after'] == graph(10 + total, total, index + 1, amount)
        kind = 'error' if index == 4 else 'return'
        expected = {'kind': kind, 'graph': graph(10 + total, total, index + 1, amount, outcome=kind)}
        if kind == 'error':
            expected['category'] = 'panic'
        assert step['outcome'] == expected
    assert value['after'] == graph(18, 8, 5, -2)
    assert value['outcome'] == value['steps'][-1]['outcome']


def audit():
    reports = sorted(ROOT.glob('*/typed-bundle.json'))
    attempts = 0
    for path in reports:
        cases = json.loads(path.read_text())['cases']
        assert len(cases) == 1
        for lane in ('baseline', 'instrumented_on'):
            assert len(cases[0][lane]) == 2
            for attempt in cases[0][lane]:
                observation(attempt['observation'])
                attempts += 1
    return {'cases': len(reports), 'application_observations': attempts, 'step_observations': attempts * 5,
            'scope': 'complete literal roots, storage/location aliases, values, intermediate outcomes and panic bytes'}


if __name__ == '__main__':
    print(json.dumps(audit(), indent=2))
