"""Audit the completed development run without launching another application."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-public-provider')
sys.path.insert(0, str(REPO / 'tests'))
import qualify_go_receivers

spec = importlib.util.spec_from_file_location('literal_live_oracle', ROOT / 'literal-live-oracle.py')
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)
result = oracle.audit()
assert (result['cases'], result['application_observations'], result['step_observations']) == (4, 16, 80)
status = json.loads((ROOT / 'public-development-02/status.json').read_text())
assert status['status'] == 'passed' and all(status['preservation'].values())
assert status['audit']['actual_applications'] == 16 and status['audit']['complete_traces'] == 48
first = None
for path in sorted((ROOT / 'public-development-02/comparison').glob('*/typed-bundle.json')):
    case = json.loads(path.read_text())['cases'][0]
    for lane in ('baseline', 'instrumented_on'):
        for index, attempt in enumerate(case[lane]):
            qualify_go_receivers.scope_attempt(path.parent / (lane + '-' + str(index)), ())
            first = first or attempt['observation']

def modify(value, kind):
    if kind == 'global-value': value['steps'][2]['after']['nodes'][0]['fields']['value']['value'] = '1'
    elif kind == 'scalar-width': value['steps'][1]['before']['nodes'][0]['fields']['value']['bits'] = 32
    elif kind == 'extra-root': value['steps'][1]['after']['roots']['hidden'] = {'kind': 'null'}
    elif kind == 'self-alias': value['steps'][3]['after']['nodes'][20]['fields']['value']['node_id'] = 'n12'
    elif kind == 'panic-payload': value['steps'][4]['outcome']['graph']['roots']['error']['value'] = '00'
    elif kind == 'returned-value': value['steps'][0]['outcome']['graph']['roots']['result']['value'] = '12'
    elif kind == 'step-count': value['steps'].pop()
    elif kind == 'extra-node': value['steps'][1]['after']['nodes'].append({'id': 'extra', 'type': 'opaque', 'fields': {}})
    else: raise AssertionError(kind)

controls = ('global-value', 'scalar-width', 'extra-root', 'self-alias', 'panic-payload', 'returned-value', 'step-count', 'extra-node')
for kind in controls:
    altered = copy.deepcopy(first)
    modify(altered, kind)
    try:
        oracle.observation(altered)
    except AssertionError:
        continue
    raise AssertionError('literal oracle accepted ' + kind)
result.update(status='passed', actual_sdk_processes=8, complete_traces=48, compiler_tooling_audits=16,
              altered_graph_refusals=list(controls), source_preservation=status['preservation'],
              source_index='source-development-01.json', dirty_development_snapshot=True,
              sdk_head=status['sdk_head'], qualifier_sha256=hashlib.sha256(Path(qualify_go_receivers.__file__).read_bytes()).hexdigest(),
              scope='frozen uncommitted builtin-shadow direct workflow only; retained, tagged, SDK full gate and full Go remain open')
with (ROOT / 'public-development-02/retained-audit-result.json').open('x') as output:
    output.write(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
