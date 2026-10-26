"""Check whether SDK health is joined to the verified build's language/selection."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'source'))
from otelc import prepared_native as prepared

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

original = {'plain': False, 'launch_id': 'a' * 32, 'policy': {}}
resolved = {'image': {'path': '/literal/application', 'sha256': 'b' * 64}}
built = SimpleNamespace(manifest=lambda: {'language': 'cpp', 'selection_sha256': 'b' * 64})
supervisor = {'schema_version': 1, 'kind': 'otelc.native.supervisor', 'pid': 101, 'parent_pid': 100,
              'process_group': 101, 'session': 101, 'launch_id': original['launch_id']}
application = {'schema_version': 1, 'kind': 'otelc.native.application', 'pid': 102, 'parent_pid': 101,
               'process_group': 102, 'session': 102, 'supervisor_pid': 101, 'launch_id': original['launch_id'],
               'image': resolved['image'], 'phase': 'waiting_exec', 'source_complete': False}
exports = {'exporters_observed': 1, 'unit': 'spans', **{key: '0' for key in
    ('batches_started', 'batches_succeeded', 'batches_failed', 'batches_pending', 'units_started', 'units_succeeded', 'units_failed')}}
checkpoint = {'schema_version': 1, 'kind': 'otelc.runtime-health', 'language': 'cpp', 'pid': 102,
    'policy_sha256': digest(original['policy']), 'selection_sha256': 'b' * 64, 'scope': 'sdk_pipeline',
    'phase': 'final', 'sdk_attached': True, 'source_complete': False,
    'lifecycle': {'flush': 'succeeded', 'shutdown': 'succeeded'},
    'metric_flush': {'attempts': '0', 'failed_attempts': '0'},
    'span_accounting': {'processors_observed': 1, 'batch_processors_observed': 1, 'sampled_started': '0',
        'sampled_ended': '0', 'sampled_active': '0', 'queue_pending': None, 'queue_dropped': None, 'queue_evidence': 'unavailable'},
    'trace_exports': exports, 'metric_exports': exports | {'unit': 'metric_points'},
    'function_accounting': {'closed': True, **{key: '0' for key in ('registered', 'started', 'ended', 'active', 'lost', 'invalid', 'metadata_errors')}},
    'downstream_receipt': 'unavailable', 'otlp_partial_rejection': 'unavailable'}
value = {'schema_version': 1, 'kind': 'otelc.native.execution', 'profile': 'native-owned-v1',
         'request_sha256': digest(original), 'plan_sha256': digest(resolved), 'supervisor': supervisor,
         'application': application, 'released': True, 'process_exit_code': 0, 'supervisor_exit_code': 0,
         'exec_verified': False, 'sdk_health': checkpoint, 'inputs_rechecked': True, 'failures': {}, 'source_complete': False}
results = []
with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
    runtime = Path(temporary)
    (runtime / 'app').mkdir(mode=0o700)
    prepared.files.write(runtime / 'native-supervisor-start.json', supervisor)
    prepared.files.write(runtime / 'native-application-start.json', application)
    for label, changes in (('control', {}), ('wrong-language', {'language': 'java'}),
                           ('wrong-selection', {'selection_sha256': '0' * 64})):
        altered = copy.deepcopy(value)
        altered['sdk_health'].update(changes)
        for path, record in ((runtime / 'native-execution.json', altered), (runtime / 'app/health.json', altered['sdk_health'])):
            if path.exists():
                path.write_text(json.dumps(record))
            else:
                prepared.files.write(path, record)
        accepted = False
        with patch.object(prepared, 'verify', return_value=(original, resolved, built, None)):
            try:
                prepared.execution(runtime, supervisor_pid=101, parent_pid=100, returncode=0)
                accepted = True
            except ValueError:
                pass
        results.append({'case': label, 'accepted': accepted})
receipt = {'head': '3c8269eb62224c4f0bdd69ea3e7b63a19354b841',
           'scope': 'execution parser unit boundary with trusted build verification stubbed; actual private execution and SDK health readers used; no application launched',
           'verified_build': built.manifest(), 'results': results,
           'finding': 'SDK checkpoint language and selection are not joined to the verified native build'}
(ROOT / 'health-reader-probe.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2))
assert all(row['accepted'] for row in results), 'candidate behavior changed'
