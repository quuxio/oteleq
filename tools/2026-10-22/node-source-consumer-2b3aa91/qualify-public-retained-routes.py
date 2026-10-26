"""Check retained routes and complete literal observations on the frozen CLI."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

BASE=Path(__file__).resolve().parent
ROOT=BASE/sys.argv[1]
CLI=ROOT/'quux-oteleq'
PYTHON=Path('/Users/sclarke/github/otelc-qualification/2026-10-22/node-provider-2b3aa91/provider/.venv/bin/python')
rows=json.loads((ROOT/'receipt.json').read_bytes())
output=ROOT/'retained-routes';output.mkdir(mode=0o700)
receipts=[]
def write(): (output/'receipt.json').write_text(json.dumps(receipts,indent=2)+'\n')
def f(bits):return {'type':'float64','bits':bits}
node={'type':'array','fields':[['0',f('401c000000000000'),True,True,True],['length',f('3ff0000000000000'),True,False,False]],'prototype':'Array','extensible':True}
before={'roots':{'global:total':f('4024000000000000'),'arguments':{'ref':0}},'nodes':[node]}
after={'roots':{'global:total':f('4031000000000000'),'arguments':{'ref':0}},'nodes':[node]}
expected={'before':before,'outcome':{'kind':'return','value':{'roots':{**after['roots'],'result':f('4031000000000000')},'nodes':[node]}},'after':after}
for row in rows:
 assert all(stage['returncode']==0 for stage in row['stages'])
 folder=ROOT/(row['language']+'-'+row['compiler']); workspace=Path(row['workspace'])
 details={'language':row['language'],'compiler':row['compiler'],'stages':[]};receipts.append(details);write()
 node_path=json.loads((workspace/'plan.json').read_bytes())['tools'][row['language']][row['language']]
 env={'PATH':'/opt/homebrew/opt/node@24/bin:/opt/homebrew/bin:/usr/bin:/bin','HOME':str(folder),'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','OTELC_NODE':node_path,'OTELEQ_PYTHON':str(PYTHON),'OTELEQ_CLI':str(CLI),'OTELEQ_WORKSPACE_PARENT':str(folder/'workspaces')}
 def run(stage,command,expected_code=0):
  record={'stage':stage,'command':list(map(str,command)),'started':True};details['stages'].append(record);write()
  r=subprocess.run(record['command'],env=env,cwd=folder,capture_output=True,timeout=300)
  (output/(row['language']+'-'+row['compiler']+'-'+stage+'.stdout')).write_bytes(r.stdout)
  (output/(row['language']+'-'+row['compiler']+'-'+stage+'.stderr')).write_bytes(r.stderr)
  record['returncode']=r.returncode;write();assert r.returncode==expected_code,(stage,r.returncode,r.stderr[-1800:])
  return r
 run('framework',[PYTHON,'-I','-B',workspace/'tests/test_equivalence.py'])
 detached=folder/'detached-tests'
 run('export-dry',[CLI,'export-tests','--workspace',workspace,'--destination',detached]);assert not detached.exists()
 run('export',[CLI,'export-tests','--workspace',workspace,'--destination',detached,'--apply'])
 run('detached-framework',[PYTHON,'-I','-B',detached/'tests/test_equivalence.py'])
 case=json.loads((workspace/'tests/corpus.json').read_bytes())[0]['id']
 run('replay',[CLI,'replay','--workspace',workspace,'--case',case])
 probe=next((detached/'node-source-provider/capabilities').glob('*/policy.toml'))
 original=probe.read_bytes();probe.write_bytes(original+b'\n# deliberate retained-evidence mutation\n')
 count=len(list(folder.rglob('node-source-application.json')))
 run('changed-probe-refusal',[CLI,'replay','--workspace',detached,'--case',case],4)
 assert len(list(folder.rglob('node-source-application.json')))==count
 probe.write_bytes(original)
 promoted=folder/'application/equivalence-tests'
 run('promote-dry',[CLI,'promote','--workspace',workspace,'--source',folder/'application','--destination',promoted]);assert not promoted.exists()
 run('promote',[CLI,'promote','--workspace',workspace,'--source',folder/'application','--destination',promoted,'--apply'])
 run('promoted-framework',[PYTHON,'-I','-B',promoted/'test_equivalence.py'])
 observations=sorted(folder.rglob('observation'))
 assert len(observations)==20,len(observations)
 for p in observations:
  assert json.loads(p.read_bytes())==expected,p
  attempt=p.parent
  assert (attempt/'stdout').read_bytes()==(attempt/'stderr').read_bytes()==b'',attempt
  request=json.loads((attempt/'node-source-request.json').read_bytes())
  if not request['plain']:
   status=json.loads((attempt/'node-runtime/node-status.json').read_bytes())
   assert status['phase']==status['sdk_phase']=='closed' and status['span_accounting']['queue_pending']==0 and status['span_accounting']['queue_dropped']==0
 details.update(actual_applications=len(list(folder.rglob('node-source-application.json'))),complete_literal_observations=len(observations),accepted=False)
 write()
print(json.dumps(receipts,indent=2))
