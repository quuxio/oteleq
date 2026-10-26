"""Qualify the explicitly bound task observer, retaining exact launch evidence."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
REPO = Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-integrated-qualification')
PROVIDER = Path('/Users/sclarke/github/otelc-qualification/2026-10-20/integrated-provider/d6d03b7/provider')
OBSERVER = REPO / 'examples/capture_otelc_tasks.py'


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value,indent=2)+'\n')


if __debug__ is False:
    raise SystemExit('Qualification requires assertions')
before = digest(OBSERVER)
python = PROVIDER / '.venv/bin/python'
environment = dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OTELC_ADAPTER_ROOT='/decoy/must-not-be-used')
command = [str(python),str(OBSERVER),'--otelc-root',str(PROVIDER),'--report-dir',str(ROOT/'task-binding')]
state = {'pid':None,'state':'running','observer_sha256':before,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
with (ROOT/'task-binding.log').open('xb') as output:
    child = subprocess.Popen(command,env=environment,stdout=output,stderr=subprocess.STDOUT)
    state['pid'] = child.pid;save(ROOT/'task-binding-state.json',state)
    rc=child.wait()
state.update(state='completed',exit_code=rc,source_unchanged=before==digest(OBSERVER),completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
save(ROOT/'task-binding-state.json',state)
if rc:
    raise SystemExit(rc)
assert state['source_unchanged']
folder=ROOT/'task-binding'
with (folder/'comparison.json').open('wb') as out:
    compared=subprocess.run([str(ROOT/'quux-oteleq'),'compare-workload',str(folder/'bundle.json')],stdout=out,stderr=subprocess.PIPE,check=False)
assert compared.returncode==0 and not compared.stderr
assert json.loads((folder/'comparison.json').read_text())['verdict']=='equivalent_observed'
commands=[]
for path in sorted(folder.glob('*-*/commands.json')):
    record=json.loads(path.read_text());assert record['adapter_root']==str(PROVIDER/'adapters') and record['python']==str(python)
    commands.append(record['executed'])
assert len(commands)==4 and len({json.dumps(command) for command in commands})==4
result={'observer_sha256':before,'provider_commit':'d6d03b72026cde8962b11ce3cc184ff3ebcb60d4','application_launches':4,'ambient_decoy_adapter_ignored':True,'recorded_explicit_adapter_root':str(PROVIDER/'adapters'),'recorded_selected_python':str(python),'matching':True,'source_preserved':True,'scope':'Existing task byte channels and eight name-bound spans; no parent graph/resource or invocation-authentication claim.'}
save(folder/'qualification.json',result);print(json.dumps(result),flush=True)
