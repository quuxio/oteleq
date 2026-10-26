"""Revalidate every retained startup state without starting applications."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

BASE=Path(__file__).resolve().parent
OUT=BASE/'retained-final-matrix-01'
SOURCE=BASE/'source-cb08b82'
SDK=Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/go-scope-provider/sdk-eda9fcc')
PYTHON=Path('/Users/sclarke/github/oteleq-qualification/2026-10-24/python-live-metrics/env-312/bin/python')
GO=Path('/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go')
OUT.mkdir(mode=0o700)
expected=json.loads((BASE/'full-gate-cb08b82/inputs-after.json').read_text())
def facts(path):
 state=path.stat()
 with path.open('rb') as stream: sha=hashlib.file_digest(stream,'sha256').hexdigest()
 return [sha,state.st_dev,state.st_ino,state.st_mode,state.st_size,state.st_mtime_ns,state.st_ctime_ns]
def inputs():
 roots={'consumer':SOURCE,'sdk':SDK,'weaver_source':SDK/'build/go-upstream-scope/source'}
 return {key:{name:facts((roots[key]/name) if key in roots else Path(name)) for name in names}
         for key,names in expected.items()}
def write(name,value):(OUT/name).write_text(json.dumps(value,indent=2)+'\n')
before=inputs();assert before==expected;write('inputs-before.json',before)
env={k:v for k,v in os.environ.items() if not k.startswith(('OTEL','OTELEQ','GH_','GITHUB_','AWS_','SONAR_'))}
env.update(PYTHONDONTWRITEBYTECODE='1',PATH=str(GO.parent)+os.pathsep+env.get('PATH',''))
state={'status':'running','head':'cb08b8267d70be6e578f9f76089f7a60f3a8b3cb','started':datetime.now(timezone.utc).isoformat(),
       'new_application_launches':0,'states':{},'scope':'Maintained retained-only oracles, operation/route checks, raw receipt and original file-fact preservation for all four startup states.'}
write('status.json',state);started=time.monotonic();global_launches=set()
try:
 for startup in ['both-on','collection-off','emission-off','both-off']:
  root=BASE/(startup+'-cb08b82-01');original=json.loads((root/'status.json').read_text());assert original['status']=='passed'
  original_argv=next(row['argv'] for row in original['commands'].values() if '--startup-state' in row['argv'])
  cli=Path(original_argv[original_argv.index('--cli')+1]);cli_before=facts(cli)
  argv=[str(PYTHON),'-B',str(SOURCE/'tests/qualify_go_controls.py'),'--retained-only','--otelc-root',str(SDK),
        '--cli',str(cli),'--startup-state',startup,'--report-dir',str(root/'workflow'),'--audit-dir',str(OUT/startup),
        '--min-free-bytes',str(8*1024**3),'--cache-max-bytes',str(512*1024**2)]
  row={'status':'running','argv':argv,'started':datetime.now(timezone.utc).isoformat()};state['states'][startup]=row;write('status.json',state);begin=time.monotonic()
  with (OUT/(startup+'.stdout')).open('xb') as stdout,(OUT/(startup+'.stderr')).open('xb') as stderr:
   result=subprocess.run(argv,cwd=SOURCE,env=env,stdout=stdout,stderr=stderr,timeout=7200)
  row.update(status='passed' if result.returncode==0 else 'failed',exit_code=result.returncode,seconds=round(time.monotonic()-begin,3));write('status.json',state);assert result.returncode==0,startup
  summary=json.loads((OUT/startup/'QUALIFICATION.json').read_text());assert summary==original['qualification']
  launches=set()
  for report in (root/'workflow').rglob('report.json'):
   for case in json.loads(report.read_text())['cases']:
    for lane in ['baseline','instrumented_on']:
     for repeat in range(2):
      start=report.parent/case['case']/(lane+'-'+str(repeat))/'go-runtime/go-application-start.json'
      launches.add(json.loads(start.read_text())['launch_id'])
  assert len(launches)==80 and not global_launches.intersection(launches)
  global_launches.update(launches);assert cli_before==facts(cli)
  row.update(qualification=summary,unique_launch_ids=len(launches),original_cli_held=True)
  write('status.json',state)
 state['status']='passed';state['unique_actual_application_launch_ids']=len(global_launches);assert len(global_launches)==320
except Exception as error:state.update(status='failed',error=repr(error))
finally:
 after=inputs();write('inputs-after.json',after);state['preservation']={key:before[key]==after[key] for key in before}
 if not all(state['preservation'].values()):state['status']='failed'
 state.update(seconds=round(time.monotonic()-started,3),finished=datetime.now(timezone.utc).isoformat());write('status.json',state)
 print(json.dumps({k:v for k,v in state.items() if k!='states'},indent=2),flush=True)
 raise SystemExit(0 if state['status']=='passed' else 1)
