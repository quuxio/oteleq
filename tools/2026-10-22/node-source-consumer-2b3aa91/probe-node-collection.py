"""Test actual ordered calls/release/collection on the frozen source SDK consumer."""
import json
import os
from pathlib import Path
import subprocess
import sys

BASE=Path(__file__).resolve().parent
ROOT=BASE/'public-collection-initial';ROOT.mkdir(mode=0o700)
CLI=BASE/'public-receiver-initial/quux-oteleq'
PROVIDER=Path('/Users/sclarke/github/otelc-qualification/2026-10-22/node-provider-2b3aa91/provider')
env={'PATH':'/opt/homebrew/opt/node@24/bin:/opt/homebrew/bin:/usr/bin:/bin','HOME':str(ROOT),'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','OTELC_NODE':'/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node','OTELEQ_PYTHON':str(PROVIDER/'.venv/bin/python')}
rows=[]
for language,compiler,suffix in [('javascript','native','.cjs'),('typescript','native','.cts'),('typescript','api','.mts')]:
 folder=ROOT/(language+'-'+compiler);folder.mkdir();app=folder/'application';app.mkdir();(folder/'workspaces').mkdir()
 annotation=':number' if language=='typescript' else ''
 source='class Counter {constructor(start'+annotation+'){this.value=start;this.self=this;} add(value'+annotation+'){this.value+=value;return this.value;}}\nfunction make(start'+annotation+'){return new Counter(start);}\n'
 (app/('seq'+suffix)).write_text(source)
 policy=folder/'policy.toml';policy.write_text('languages=["'+language+'"]\n[functions]\ninclude=["seq.Counter.add"]\n[adapters.node]\nbackend="source-v1"\ntypescript_compiler="'+compiler+'"\n[[fixtures]]\nfunction="seq.Counter.add"\ncases=[[7]]\nreceiver={factory="make",arguments=[10]}\nsequence=[{action="call",arguments="case"},{action="call",arguments=[2]},{action="release"},{action="collect",gc_rounds=64,settle_turns=4}]\n')
 row={'language':language,'compiler':compiler,'stages':[],'accepted':False};rows.append(row)
 def run(stage,args):
  command=[str(CLI),*map(str,args)];r=subprocess.run(command,env=env,cwd=folder,capture_output=True,timeout=300)
  (folder/(stage+'.stdout')).write_bytes(r.stdout);(folder/(stage+'.stderr')).write_bytes(r.stderr)
  row['stages'].append({'stage':stage,'returncode':r.returncode});(ROOT/'receipt.json').write_text(json.dumps(rows,indent=2)+'\n');return r
 result=run('plan',['plan','--source',app,'--otelc-root',PROVIDER,'--workspace-parent',folder/'workspaces','--config',policy])
 if result.returncode:continue
 workspace=Path(result.stdout.decode().strip());row['workspace']=str(workspace)
 row['inventory']=[{k:v for k,v in entry.items() if k in ('name','status','reason')} for entry in json.loads((workspace/'plan.json').read_bytes())['inventory']]
 if run('generate',['generate','--workspace',workspace]).returncode:continue
 run('run',['run','--workspace',workspace,'--report-dir',folder/'report'])
 row['actual_applications']=len(list(folder.rglob('node-source-application.json')))
 (ROOT/'receipt.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(rows,indent=2))
