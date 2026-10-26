"""Exercise the frozen public CLI, preserving every failed or completed stage."""
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
NODE=sys.argv[2] if len(sys.argv)>2 else '/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node'
OUTPUT=BASE/sys.argv[1]
OUTPUT.mkdir(mode=0o700)
CLI=OUTPUT/'quux-oteleq'
shutil.copyfile('/Users/sclarke/github/oteleq-qualification/work/node-source-target/debug/quux-oteleq',CLI)
CLI.chmod(0o700)
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
files=subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=WT).decode().split('\0')[:-1]
assert len(files)==len(set(files))
snapshot=OUTPUT/'source';snapshot.mkdir()
for name in files:
 p=snapshot/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(WT/name,p)
write(OUTPUT/'source.json',{'base':subprocess.check_output(['git','rev-parse','HEAD'],cwd=WT,text=True).strip(),'files':{name:digest(snapshot/name) for name in files},'cli_sha256':digest(CLI),'accepted':False})
env={'PATH':'/opt/homebrew/opt/node@24/bin:/opt/homebrew/bin:/usr/bin:/bin','HOME':str(OUTPUT),'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','OTELC_NODE':NODE,'OTELEQ_PYTHON':str(PROVIDER/'.venv/bin/python')}
receipts=[]
for language,compiler,suffix in [('javascript','native','.cjs'),('typescript','native','.cts'),('typescript','api','.mts')]:
 folder=OUTPUT/(language+'-'+compiler);folder.mkdir();app=folder/'application';app.mkdir();(folder/'workspaces').mkdir()
 source='let total = 10;\nfunction add(value) { total += value; return total; }\n' if language=='javascript' else 'let total: number = 10;\nexport function add(value: number): number { total += value; return total; }\n'
 (app/('app'+suffix)).write_text(source)
 policy=folder/'policy.toml';policy.write_text('languages = ["'+language+'"]\n[functions]\ninclude = ["app.add"]\n[adapters.node]\nbackend = "source-v1"\ntypescript_compiler = "'+compiler+'"\n[[fixtures]]\nlanguage = "'+language+'"\nfunction = "app.add"\ncases = [[7]]\nexpected_baseline = { kind = "return_value", value = { kind = "float", type = "'+language+'.float64", bits = "4031000000000000" } }\n')
 stages=[];row={'language':language,'compiler':compiler,'stages':stages};receipts.append(row)
 def run(stage,args):
  command=[str(CLI),*map(str,args)];r=subprocess.run(command,cwd=folder,env=env,capture_output=True,timeout=300)
  (folder/(stage+'.stdout')).write_bytes(r.stdout);(folder/(stage+'.stderr')).write_bytes(r.stderr)
  stages.append({'stage':stage,'command':command,'returncode':r.returncode});write(OUTPUT/'receipt.json',receipts)
  return r
 result=run('plan',['plan','--source',app,'--otelc-root',PROVIDER,'--workspace-parent',folder/'workspaces','--config',policy])
 if result.returncode:continue
 workspace=Path(result.stdout.decode().strip());row['workspace']=str(workspace)
 inventory=json.loads((workspace/'plan.json').read_bytes())['inventory'];row['inventory']=[{k:e[k] for k in ('name','status','reason')} for e in inventory];write(OUTPUT/'receipt.json',receipts)
 if run('generate',['generate','--workspace',workspace]).returncode:continue
 run('run',['run','--workspace',workspace,'--report-dir',folder/'report'])
 row['actual_applications']=len(list(folder.rglob('node-source-application.json')))
 write(OUTPUT/'receipt.json',receipts)
print(json.dumps(receipts,indent=2))
