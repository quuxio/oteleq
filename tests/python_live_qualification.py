"""Literal application and telemetry oracles for prepared Python live schedules."""

import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import generation
import python_launch
import python_selection
import sequence_qualification as shared
from python_sequence_fixture import FUNCTIONS, METHODS, SOURCE, boundaries, function, raw_observation

STARTS = ('both-on', 'collection-off', 'emission-off', 'both-off')
STATES = ((True, True), (False, True), (True, False), (False, False))
PROFILES = ('python-native-origins-v2', 'python-native-cache-origins-v3')
TIME = 1_700_000_000_123456789
PATH = 'src/pkg/state.py'


def states(start: str) -> tuple[dict, ...]:
    """Rotate all four states, then require a final positive restoration call."""
    if start not in STARTS:
        raise ValueError('unknown Python metric startup state')
    offset = STARTS.index(start)
    return tuple({'collection': a, 'emission': b}
                 for a, b in (*STATES[offset:], *STATES[:offset], STATES[0]))


def sources(*, changed: bool = False) -> dict[str, bytes]:
    text = SOURCE.replace('self._token=99', 'self._token=101') if changed else SOURCE
    return {'src/pkg/__init__.py': b'', PATH: text.encode()}


def policy(profile: str, start: str) -> str:
    """Keep source creation, concrete inputs and every metric flag explicit."""
    assert profile in PROFILES
    text = ('schema_version=1\nlanguages=["python"]\n[adapters.python]\nimport_roots=["src"]\n'
            'backend="prepared"\nprofile=' + json.dumps(profile) + '\n[functions]\ninclude='
            + json.dumps(list(FUNCTIONS)) + '\n[limits]\ncase_timeout_ms=60000\n')
    for method in METHODS:
        text += ('\n[[fixtures]]\nfunction=' + json.dumps(function(method)) + '\ncases=[[7]]\n'
                 'receiver={factory=' + json.dumps('make_counter' if method == 'secret' else 'Counter')
                 + ',arguments=[10]}\nsequence=[\n')
        for index, flags in enumerate(states(start)):
            arguments = '"case"' if index == 0 else '[2]'
            expectation = ('{kind="error",category="exception",type="python.builtins.ValueError"}'
                           if method == 'fail' and index == 0 else '{kind="return"}')
            text += ('{action="call",arguments=' + arguments + ',metrics={collection='
                     + str(flags['collection']).lower() + ',emission=' + str(flags['emission']).lower()
                     + '},expected_baseline=' + expectation + '},\n')
        text += ']\n'
        if method == 'transient':
            text += 'domains=[{kind="integer",minimum=0,maximum=7}]\n'
    return text


def expected_raw(method: str, amount: int, active: bool, *, changed: bool = False) -> dict:
    raw = raw_observation(method, amount, active, steps=5)
    if changed:
        for step in raw['steps']:
            for graph in (step['before'], step['after'], step['outcome']['value']):
                for node in graph['nodes']:
                    for name, value in node.get('fields', []):
                        if name == '_token':
                            assert value == {'type': 'int', 'value': '99'}
                            value['value'] = '101'
    return raw


def selection(folder: Path, entry: dict, *, changed: bool = False) -> tuple:
    """Source lines and bytes come from the fixed fixture, not producer metadata."""
    method = FUNCTIONS[entry['otelc_function']]
    raw = sources(changed=changed)[PATH]
    assert entry['path'] == PATH and entry['name'] == 'Counter.' + method
    path = folder / 'project' / PATH
    assert path.read_bytes() == raw
    frozen = python_selection.freeze(path)
    lines = raw.decode().splitlines()
    target = next(i for i, line in enumerate(lines, 1) if line.startswith(' def ' + method + '('))
    creator = 'make_counter' if method == 'secret' else 'Counter.__init__'
    factory = next(i for i, line in enumerate(lines, 1)
                   if line.startswith('def make_counter(' if method == 'secret' else ' def __init__('))
    assert entry['line'] == target
    assert (entry['receiver_fixture']['source_function'], entry['receiver_fixture']['line']) == (creator, factory)
    selected = (python_selection.Selection(frozen, entry['name'], target),
                python_selection.Selection(frozen, creator, factory))
    facts = generation.read(folder / python_launch.ORIGIN_FILE)
    assert facts['selected'] == [
        {'path_hex': os.fsencode(path).hex(), 'sha256': hashlib.sha256(raw).hexdigest(),
         'device': frozen.device, 'inode': frozen.inode, 'mtime_ns': frozen.mtime_ns,
         'mode': frozen.mode, 'qualname': item.qualname, 'line': item.line} for item in selected]
    return facts, selected


def expected_counts(method: str, amount: int, schedule: tuple[dict, ...], target_code: int,
                    creator_code: int) -> tuple[list[int], dict, dict]:
    """Each positive recursive input executes one additional selected child."""
    counts = [1 + int(method == 'recursive' and value > 0) for value in [amount, 2, 2, 2, 2]]
    calls = {target_code: sum(count for count, flags in zip(counts, schedule) if flags['collection'])}
    errors = {target_code: int(method == 'fail' and amount != 2 and schedule[0]['collection'])}
    if schedule[0]['collection']:
        calls[creator_code], errors[creator_code] = 1, 0
    return counts, calls, errors


def check_sdk(folder: Path, method: str, amount: int, schedule: tuple[dict, ...]) -> None:
    """Independently count all traces and only the collection-enabled code trees."""
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
    creator = 'src.pkg.state.' + ('make_counter' if method == 'secret' else 'Counter.__init__')
    selected = generation.read(folder / 'python-verified-origins.json')['selected']
    assert len(selected) == 2 and all(len(row['matches']) == 1 for row in selected)
    target_code, creator_code = (row['matches'][0]['sdk'] for row in selected)
    assert type(target_code) is type(creator_code) is int and target_code != creator_code
    counts, calls, errors = expected_counts(method, amount, schedule, target_code, creator_code)
    verified = generation.read(folder / 'python-verified-controls.json')
    assert verified['metric_calls'] == {str(key): value for key, value in calls.items()}
    assert verified['metric_errors'] == {str(key): value for key, value in errors.items()}
    assert verified['collected_spans'] == sum(calls.values())
    spans, _ = shared.decode_receipt(folder)
    creation = [span for span in spans if span.name == creator]
    assert len(creation) == 1 and not creation[0].parent_span_id
    target = [span for span in spans if span.name == function(method)]
    assert len(spans) == len(target) + 1
    shared.check_serial_trees(target, counts, function(method))
    assert creation[0].end_time_unix_nano <= min(span.start_time_unix_nano for span in target)
    assert sum(span.status.code == 2 for span in spans) == int(method == 'fail' and amount != 2)
    capture = generation.read(folder / 'http-capture.json')['bodies']
    latest = {}
    for row in capture:
        if row['path'] != '/v1/metrics':
            continue
        message = ExportMetricsServiceRequest.FromString((folder / row['file']).read_bytes())
        for resource in message.resource_metrics:
            for scope in resource.scope_metrics:
                assert scope.scope.name == 'io.quux.otelc.functions'
                for metric in scope.metrics:
                    histogram = metric.name == 'otelc.function.duration'
                    assert metric.name in ('otelc.function.calls', 'otelc.function.duration', 'otelc.function.exceptions')
                    for point in metric.histogram.data_points if histogram else metric.sum.data_points:
                        attributes = {item.key: item.value for item in point.attributes}
                        assert len(point.attributes) == len(attributes) == 2
                        code = attributes['otelc.python.code_id'].int_value
                        assert code in calls
                        key = (metric.name, code)
                        value = point.count if histogram else point.as_int
                        if key not in latest or point.time_unix_nano > latest[key][0]:
                            latest[key] = point.time_unix_nano, value
    expected = {(name, code): count for code, count in calls.items()
                for name in ('otelc.function.calls', 'otelc.function.duration')}
    expected.update({('otelc.function.exceptions', code): count for code, count in errors.items() if count})
    assert {key: value[1] for key, value in latest.items() if key[0] != 'otelc.function.exceptions' or value[1]} == expected


def check_report(path: Path, count: int, *, start: str, changed: bool = False) -> int:
    report = generation.read(path)
    assert report['source_preserved'] and not report['blocked'] and len(report['cases']) == count
    assert len({case['function'] for case in report['cases']}) == count
    if count == len(METHODS):
        assert {case['function'] for case in report['cases']} == set(FUNCTIONS)
    observed = 0
    for case in report['cases']:
        method = FUNCTIONS[case['function']]
        assert case['exit_code'] == int(method == 'transient') and case['receiver_fixture']['arguments'] == [10]
        bundle = generation.read(path.parent / case['case'] / 'typed-bundle.json')['cases'][0]
        shared.check_contract(bundle, {'arguments', 'receiver', 'global:created', 'static:Counter.total',
                                      'static:Counter.instances', 'static:Counter.shared'}, 5)
        for lane in ('baseline', 'instrumented_on'):
            assert len(bundle[lane]) == 2
            for repeat, attempt in enumerate(bundle[lane]):
                observed += 1
                folder = path.parent / case['case'] / (lane + '-' + str(repeat))
                raw = expected_raw(method, case['arguments'][0], lane == 'instrumented_on', changed=changed)
                assert generation.read(folder / 'observation') == raw, str(folder)
                expected = {**boundaries(raw), 'steps': [
                    {'id': row['id'], 'action': 'call', 'gaps': [], **boundaries(row)} for row in raw['steps']]}
                assert attempt['observation']['gaps'] == []
                assert all(attempt['observation'][key] == value for key, value in expected.items())
                assert attempt['execution']['channels']['stdout'] == attempt['execution']['channels']['stderr'] == []
                control = generation.read(folder / 'python-controls.json')
                assert [row['requested'] for row in control['steps']] == list(states(start))
                assert control['plain'] is (lane == 'baseline')
                if lane == 'instrumented_on':
                    check_sdk(folder, method, case['arguments'][0], states(start))
                else:
                    assert control['sdk_pid'] is control['launch_id'] is None
    return observed
