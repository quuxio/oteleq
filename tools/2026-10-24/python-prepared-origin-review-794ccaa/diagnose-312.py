"""Retain a failed public bootstrap without changing the reviewed SDK."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
SDK = ROOT / 'source-794ccaa'
sys.path.insert(0, str(SDK))
from otelc.config import Policy
from otelc import prepared_python

folder = Path(tempfile.mkdtemp(prefix='oqp794-312-', dir='/private/tmp'))
project = folder / 'a'; project.mkdir()
(project / 'entry.py').write_text('def workload(value):return value*2+3\nprint(workload(7))\n')
policy = Policy.parse({'schema_version': 3, 'languages': ['python'],
    'sources': {'include': ['*.py']}, 'functions': {'include': ['*.workload']},
    'metrics': {'collection': True, 'emission': True}, 'traces': {'enabled': True, 'sample_ratio': 1.0},
    'export': {'endpoint': 'http://127.0.0.1:4318', 'interval_ms': 100000, 'timeout_ms': 100}})
prepared = prepared_python.prepare(policy, folder / 'r', root=project, entry='entry.py',
                                    profile='python-native-origins-v2')
result = subprocess.run(prepared['command'], capture_output=True, timeout=30, start_new_session=True)
report = {'runtime': str(folder / 'r'), 'returncode': result.returncode,
          'stdout_hex': result.stdout.hex(), 'stderr_hex': result.stderr.hex()}
(ROOT / 'bootstrap-312-diagnostic.json').write_text(json.dumps(report, indent=2) + '\n')
for path in sorted((folder / 'r').rglob('*.json')):
    if path.name in ('python-execution.json', 'python-bootstrap-status.json', 'python-sdk-status.json', 'health.json'):
        data = json.loads(path.read_bytes())
        print(path.name, json.dumps({key: data.get(key) for key in ('phase','failures','application','source_complete','bootstrap_recheck')}))
print(json.dumps(report))
