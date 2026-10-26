"""Isolate closed execution-reader exit validation from native build setup."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'source'))
from otelc import prepared_native as prepared

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

original = {'plain': True, 'launch_id': 'a' * 32, 'policy': {}}
resolved = {'image': {'path': '/literal/application', 'sha256': 'b' * 64}}
supervisor = {'schema_version': 1, 'kind': 'otelc.native.supervisor', 'pid': 101, 'parent_pid': 100,
              'process_group': 101, 'session': 101, 'launch_id': original['launch_id']}
application = {'schema_version': 1, 'kind': 'otelc.native.application', 'pid': 102, 'parent_pid': 101,
               'process_group': 102, 'session': 102, 'supervisor_pid': 101, 'launch_id': original['launch_id'],
               'image': resolved['image'], 'phase': 'waiting_exec', 'source_complete': False}
value = {'schema_version': 1, 'kind': 'otelc.native.execution', 'profile': 'native-owned-v1',
         'request_sha256': digest(original), 'plan_sha256': digest(resolved), 'supervisor': supervisor,
         'application': application, 'released': True, 'process_exit_code': 0, 'supervisor_exit_code': 0,
         'exec_verified': False, 'sdk_health': None, 'inputs_rechecked': True, 'failures': {}, 'source_complete': False}
results = []
with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
    runtime = Path(temporary)
    prepared.files.write(runtime / 'native-supervisor-start.json', supervisor)
    prepared.files.write(runtime / 'native-application-start.json', application)
    for code in (0, 23, -9):
        altered = copy.deepcopy(value)
        altered['process_exit_code'] = code
        path = runtime / 'native-execution.json'
        if not path.exists():
            prepared.files.write(path, altered)
        else:
            path.write_text(json.dumps(altered))
        accepted = False
        with patch.object(prepared, 'verify', return_value=(original, resolved, None, None)):
            try:
                prepared.execution(runtime, supervisor_pid=101, parent_pid=100, returncode=0)
                accepted = True
            except ValueError:
                pass
        results.append({'claimed_child_exit': code, 'observed_supervisor_exit': 0, 'accepted': accepted})
receipt = {'head': '4a85c180124b0d8dbfe2a4fcda254dc50e270200',
           'scope': 'execution parser unit boundary with native build verification stubbed; actual private file reader used; no application launched',
           'results': results, 'regression': 'Correct control accepted; contradictory nonzero/killed child exits refused'}
(ROOT / 'exit-reader-probe.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2))
assert results[0]['accepted'] and all(not row['accepted'] for row in results[1:])
