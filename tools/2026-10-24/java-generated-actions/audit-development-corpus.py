"""Independently check every literal graph in the completed development routes."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_bytes())


def integer(value, *, scalar=False):
    return {'kind': 'integer', 'type': 'java.lang.Integer' if scalar else 'java.int',
            'value': str(value), 'bits': 32, 'signed': True}


def graph(actual, value, total, amount, *, result=False, error=False):
    receiver = actual['roots']['receiver']
    reference = {'kind': 'reference', 'node_id': receiver['node_id']}
    roots = {'receiver': reference, 'argument:0': integer(amount), 'static:Counter.total': integer(total)}
    nodes = [{'id': receiver['node_id'], 'type': 'java.object:Counter',
              'fields': {'value': integer(value), 'self': reference}}]
    if result:
        roots['result'] = reference
    if error:
        error_id = actual['roots']['error']['node_id']
        error_node = next(node for node in actual['nodes'] if node['id'] == error_id)
        message_id = error_node['fields']['message']['node_id']
        roots['error'] = {'kind': 'reference', 'node_id': error_id}
        nodes += [{'id': error_id, 'type': 'java.lang.IllegalStateException',
                   'fields': {'message': {'kind': 'reference', 'node_id': message_id}}},
                  {'id': message_id, 'type': 'java.object:java.lang.String',
                   'fields': {'value': {'kind': 'string', 'type': 'java.lang.String',
                      'encoding': 'utf16_be', 'value': 'negative'.encode('utf-16-be').hex()}}}]
    expected = {'roots': roots, 'nodes': nodes}
    assert actual == expected, (actual, expected)


reports = []
for name in ('public-workflow-development-02', 'archive-workflow-development-01', 'static-shrink-development-02'):
    reports.extend(Path(path) for path in read(ROOT / name / 'proof.json')['reports'])
assert len(reports) == len(set(reports)) == 16
identities, observations, graphs, scopes, spans = set(), 0, 0, 0, 0
records = []
for path in reports:
    report = read(path)
    assert report['source_preserved'] and not report['blocked']
    for case in report['cases']:
        bundle = read(path.parent / case['case'] / 'typed-bundle.json')['cases'][0]
        for lane in ('baseline', 'instrumented_on'):
            assert len(bundle[lane]) == 2
            for index, attempt in enumerate(bundle[lane]):
                folder = path.parent / case['case'] / (lane + '-' + str(index))
                process = read(folder / 'process.json')
                key = process['pid'], hashlib.sha256(json.dumps(process['argv']).encode()).hexdigest()
                assert key not in identities
                identities.add(key)
                observed = attempt['observation'];observations += 1
                assert observed['gaps'] == [] and observed['fixture'] == {'status': 'ready'}
                assert observed['case_id'] == bundle['contract']['case_id']
                assert observed['function_id'] == bundle['contract']['function_id']
                assert observed['fixture_sha256'] == bundle['contract']['fixture_sha256']
                if case['function'] == 'Counter.run(int)':
                    assert len(observed['steps']) == 4
                    for step_index, step in enumerate(observed['steps']):
                        before, after = (10, 10, 16, 16)[step_index], (10, 16, 16, 17)[step_index]
                        total_before, total_after = (0, 1, 5, 6)[step_index], (1, 5, 6, 8)[step_index]
                        amount, failed = (0, 3, -1, 1)[step_index], step_index == 2
                        assert step['id'] == 'step-' + str(step_index) and step['action'] == 'call' and step['gaps'] == []
                        graph(step['before'], before, total_before, amount)
                        graph(step['after'], after, total_after, amount)
                        graph(step['outcome']['graph'], after, total_after, amount, result=not failed, error=failed)
                        assert set(step['outcome']) == ({'kind', 'graph', 'category'} if failed else {'kind', 'graph'})
                        assert step['outcome']['kind'] == ('error' if failed else 'return')
                        if failed:assert step['outcome']['category'] == 'exception'
                        graphs += 3
                    assert observed['before'] == observed['steps'][0]['before']
                    assert observed['after'] == observed['steps'][-1]['after']
                    assert observed['outcome'] == observed['steps'][-1]['outcome']
                    count, expected_spans = 4, 20
                else:
                    assert case['function'] == 'Work.target(int)'
                    amount, = case['arguments']
                    before = {'roots': {'global:Work.total': integer(10, scalar=True)}, 'nodes': []}
                    after = {'roots': {'global:Work.total': integer(10 + amount + (lane == 'instrumented_on'), scalar=True)}, 'nodes': []}
                    outcome = {'kind': 'return', 'graph': {'roots': {**after['roots'], 'result': integer(7, scalar=True)}, 'nodes': []}}
                    assert observed['before'] == before and observed['after'] == after and observed['outcome'] == outcome
                    graphs += 3;count, expected_spans = 1, 3
                host = read(folder / 'java-actions/record.json')
                assert host['plain'] is (lane == 'baseline') and len(host['harness']) == count + 1
                assert (folder / 'stdout').read_bytes() == (folder / 'stderr').read_bytes() == b''
                if lane == 'instrumented_on':
                    assert len(host['armed']) == len(host['completed']) == count
                    assert attempt['execution']['witness']['spans'] == expected_spans
                    assert attempt['execution']['witness']['pending'] == 0
                    assert not any(attempt['execution']['witness']['losses'].values())
                    scopes += count;spans += expected_spans
                else:
                    assert host['controls'] == host['armed'] == host['completed'] == []
                    assert host['identity'] is None and attempt['execution']['witness'] is None
                records.append({'pid': process['pid'], 'argv_sha256': key[1], 'folder': str(folder)})
proof = {'kind': 'retained_only_development_literal_audit', 'new_applications_started': 0,
         'reports': len(reports), 'distinct_application_launches': len(identities),
         'typed_observations': observations, 'complete_literal_boundary_graphs': graphs,
         'instrumented_action_scopes': scopes, 'instrumented_spans': spans, 'records': records,
         'scope': 'Development corpus only; complete provider qualification, independent whole-feature review and delivery remain open'}
(ROOT / 'development-retained-audit.json').write_text(json.dumps(proof, indent=2) + '\n')
print(json.dumps({key: value for key, value in proof.items() if key != 'records'}))
