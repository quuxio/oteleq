"""Qualify fresh minimal differences through shrinking after actual SDK FIFO cleanup."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

BASE=Path(__file__).resolve().parent
WT=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-node-source-provider')
PROVIDER=Path('/Users/sclarke/github/otelc-qualification/2026-10-22/node-provider-2b3aa91/provider')
ROOT=BASE/'public-transport-cleanup-reduction';ROOT.mkdir(mode=0o700)
CLI=ROOT/'quux-oteleq';shutil.copyfile('/Users/sclarke/github/oteleq-qualification/work/node-source-target/debug/quux-oteleq',CLI);CLI.chmod(0o700)
snapshot=ROOT/'source';snapshot.mkdir()
files=subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=WT).decode().split('\0')[:-1]
assert len(files)==len(set(files))
for name in files:
 p=snapshot/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(WT/name,p)
(ROOT/'source.json').write_text(json.dumps({'base':subprocess.check_output(['git','rev-parse','HEAD'],cwd=WT,text=True).strip(),'files':{name:hashlib.sha256((snapshot/name).read_bytes()).hexdigest() for name in files},'cli_sha256':hashlib.sha256(CLI.read_bytes()).hexdigest(),'accepted':False},indent=2)+'\n')
sys.path.insert(0,str(snapshot/'tests'))
import qualify_node_receivers as q
os.environ.update(OTELEQ_CLI=str(CLI),OTELEQ_PYTHON=str(PROVIDER/'.venv/bin/python'),OTELC_NODE='/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node',PYTHONDONTWRITEBYTECODE='1')
rows=[]
for language,compiler in [('javascript','native'),('typescript','native'),('typescript','api')]:
 folder=ROOT/(language+'-'+compiler);folder.mkdir()
 row={'language':language,'compiler':compiler,'stages':[],'accepted':False};rows.append(row)
 def save(): (ROOT/'receipt.json').write_text(json.dumps(rows,indent=2)+'\n')
 def run(stage,command,expected=0):
  row['stages'].append({'stage':stage,'started':True});save()
  text=q.command(command,folder,stage,expected=expected);row['stages'][-1]['returncode']=expected;save();return text
 save()
 workspace=q.prepare(CLI,PROVIDER,folder/'complete',language,methods=('silent',),node_options={'backend':'source-v1','typescript_compiler':compiler});row['workspace']=str(workspace);save()
 run('comparison',[CLI,'run','--workspace',workspace,'--report-dir',folder/'comparison'],1);q.check_report(folder/'comparison/report.json',1)
 case=json.loads((folder/'comparison/report.json').read_bytes())['cases'][0]['case']
 reduction=folder/'reduction'
 run('shrink',[CLI,'shrink','--workspace',workspace,'--case',case,'--report-dir',reduction,'--trials','16'],1)
 shrink=json.loads((reduction/'shrink.json').read_bytes());assert shrink['reduced_arguments']==[0.0] and shrink['status']=='candidate_rule_minimal'
 for p in [reduction/'original/report.json',reduction/'confirmation/report.json',*(Path(t['report']) for t in shrink['trials'])]:q.check_report(p,1)
 suite=Path(shrink['workspace']);q.framework(suite,folder,'reduced-framework',1)
 replay=json.loads(run('reduced-replay',[CLI,'replay','--workspace',suite,'--case',case],1));q.check_report(Path(replay['report']),1)
 unique={}
 for p in folder.rglob('node-source-application.json'):
  application=json.loads(p.read_bytes());request=json.loads((p.parent/'node-source-request.json').read_bytes());key=(request['runtime'],application['pid'])
  unique[key]=application
  if not request['plain']:
   transport=json.loads((p.parent/'node-source-transport.json').read_bytes());assert transport['removed_after_sdk_exit'] is True
   assert not (p.parent/'node-runtime/node-events.fifo').exists()
 row.update(status='complete',reduced_arguments=shrink['reduced_arguments'],trials=len(shrink['trials']),unique_actual_applications=len(unique),retained_application_records=len(list(folder.rglob('node-source-application.json'))));save()
print(json.dumps(rows,indent=2))
