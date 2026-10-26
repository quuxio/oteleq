"""Fresh actual public CLI module contexts, checked against maintained literal graphs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

BASE=Path(__file__).resolve().parent
WT=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-node-source-provider')
SDK=Path('/Users/sclarke/github/otelc-qualification/2026-10-22/node-provider-2b3aa91/provider')
ROOT=BASE/'public-context-matrix-initial';ROOT.mkdir(mode=0o700)
CLI=ROOT/'quux-oteleq';shutil.copyfile('/Users/sclarke/github/oteleq-qualification/work/node-source-target/debug/quux-oteleq',CLI);CLI.chmod(0o700)
snapshot=ROOT/'source';snapshot.mkdir()
files=subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=WT).decode().split('\0')[:-1]
assert len(files)==len(set(files))
for name in files:
 p=snapshot/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(WT/name,p)
(ROOT/'source.json').write_text(json.dumps({'base':subprocess.check_output(['git','rev-parse','HEAD'],cwd=WT,text=True).strip(),'files':{name:hashlib.sha256((snapshot/name).read_bytes()).hexdigest() for name in files},'cli_sha256':hashlib.sha256(CLI.read_bytes()).hexdigest(),'accepted':False},indent=2)+'\n')
sys.path.insert(0,str(snapshot/'tests'))
import qualify_node_project as fixtures
import node_project_oracle as oracle
node='/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node'
env={'PATH':'/opt/homebrew/opt/node@24/bin:/opt/homebrew/bin:/usr/bin:/bin','HOME':str(ROOT),'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','OTELC_NODE':node,'OTELEQ_PYTHON':str(SDK/'.venv/bin/python')}
rows=[]
profiles=[(compiler,c,False) for compiler in ('native','api') for c in fixtures.CONTEXTS if compiler=='native' or c[1] in ('.ts','.cts','.mts')]
profiles += [('native',fixtures.CONTEXTS[0],True),('native',fixtures.CONTEXTS[6],True),('api',fixtures.CONTEXTS[6],True)]
for compiler,context,receiver in profiles:
 name=compiler+'-'+context[0]+('-receiver' if receiver else '')
 folder=ROOT/name;folder.mkdir();app=folder/'application';app.mkdir();(folder/'workspaces').mkdir()
 spec,source,package=fixtures.fixture(context,receiver=receiver)
 (app/spec['filename']).write_text(source)
 if package is not None:(app/'package.json').write_text(package)
 policy=folder/'policy.toml'
 text=fixtures.policy(spec).replace('[[fixtures]]','[adapters.node]\nbackend="source-v1"\ntypescript_compiler='+json.dumps(compiler)+'\n[[fixtures]]',1);policy.write_text(text)
 row={'profile':name,'spec':spec,'stages':[],'accepted':False};rows.append(row)
 def save(): (ROOT/'receipt.json').write_text(json.dumps(rows,indent=2)+'\n')
 def run(stage,args):
  record={'stage':stage,'started':True};row['stages'].append(record);save()
  r=subprocess.run([str(CLI),*map(str,args)],env=env,cwd=folder,capture_output=True,timeout=300)
  (folder/(stage+'.stdout')).write_bytes(r.stdout);(folder/(stage+'.stderr')).write_bytes(r.stderr)
  record['returncode']=r.returncode;save();return r
 result=run('plan',['plan','--source',app,'--otelc-root',SDK,'--workspace-parent',folder/'workspaces','--config',policy])
 if result.returncode:continue
 workspace=Path(result.stdout.decode().strip());row['workspace']=str(workspace)
 plan=json.loads((workspace/'plan.json').read_bytes());row['inventory']=[{key:entry[key] for key in ('name','status','reason')} for entry in plan['inventory']];save()
 if run('generate',['generate','--workspace',workspace]).returncode:continue
 result=run('run',['run','--workspace',workspace,'--report-dir',folder/'comparison'])
 row['actual_applications']=len(list(folder.rglob('node-source-application.json')))
 try:
  report=json.loads((folder/'comparison/report.json').read_bytes())
  row['results']=[{'function':c['function'],'exit_code':c['exit_code'],'error':c.get('error')} for c in report['cases']]
  assert result.returncode==0 and len(report['cases'])==1 and not report['blocked'],row['results']
  case=report['cases'][0];bundle=json.loads((folder/'comparison'/case['case']/'typed-bundle.json').read_bytes())['cases'][0]
  for lane in ('baseline','instrumented_on'):
   assert len(bundle[lane])==2
   for index,attempt in enumerate(bundle[lane]):
    oracle.check_observation(attempt['observation'],spec,lane,7.0)
    assert bytes(attempt['execution']['channels']['stdout'])==(spec['format']+'\n').encode() and attempt['execution']['channels']['stderr']==[],(spec['format'],attempt['execution']['channels'])
    actual=folder/'comparison'/case['case']/(lane+'-'+str(index));receipt=json.loads((actual/'node-context.json').read_bytes())
    assert receipt['original']['format']==receipt['caller']['format']==spec['format']
    assert receipt['original']['package']==receipt['caller']['package']==spec['package']
  row['literal_checked_launches']=4;row['status']='complete'
 except (AssertionError,ValueError,KeyError) as error:row['status']='failed';row['error']=str(error)[-1600:]
 save()
print(json.dumps(rows,indent=2))
