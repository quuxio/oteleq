"""Bounded real development execution of the new maintained Go live fixture."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parent
INDEX = json.loads((BASE / 'source-development-01.json').read_text())
SOURCE = Path(INDEX['source'])
SDK_INDEX = json.loads((BASE.parent / 'go-scope-provider/sdk-source.json').read_text())
SDK = Path(SDK_INDEX['source'])
CLI = BASE.parent / 'go-scope-provider/target-e765f0d-public/debug/quux-oteleq'
GO = Path('/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go')
DEST = BASE / 'smoke-development-01'
DEST.mkdir(mode=0o700)
sys.path[:0] = [str(SOURCE / 'tests')]
import go_live_fixture as fixture
import go_live_qualification as oracle
import qualify_go_controls as qualification

def facts(path):
    info = path.stat()
    return [hashlib.sha256(path.read_bytes()).hexdigest(), info.st_dev, info.st_ino, info.st_size,
            info.st_mode, info.st_mtime_ns, info.st_ctime_ns]

def inputs():
    return {'consumer': {n: facts(SOURCE / n) for n in INDEX['files']},
            'sdk': {n: facts(SDK / n) for n in SDK_INDEX['files']},
            'tools': {str(p): facts(p) for p in (CLI, GO, Path(sys.executable).resolve())}}

def write(name, value):
    (DEST / name).write_text(json.dumps(value, indent=2)+'\n')

before = inputs()
write('inputs-before.json', before)
assert all(before['consumer'][n][0] == h for n,h in INDEX['files'].items())
assert all(before['sdk'][n][0] == h for n,h in SDK_INDEX['files'].items())
source = DEST / 'application'
original = oracle.make_source(source)
config = DEST / 'equivalence.toml'
config.write_text(fixture.policy('both-on'))
state = {'status': 'running', 'dirty_development_snapshot': True,
         'cli_head': INDEX['parent_head'], 'sdk_head': SDK_INDEX['head'],
         'started': datetime.now(timezone.utc).isoformat(), 'commands': []}
write('status.json', state)
environment = {k:v for k,v in os.environ.items() if not k.startswith(('OTEL','OTELEQ','GH_','GITHUB_','SONAR_','AWS_'))}
environment.update(OTELEQ_PYTHON=sys.executable, OTELC_PYTHON=sys.executable, OTELEQ_CLI=str(CLI),
                   OTELC_GO=str(GO), PYTHONDONTWRITEBYTECODE='1', PATH=str(GO.parent)+os.pathsep+environment.get('PATH',''))
started = time.monotonic()
def command(name,args,expected=0):
    with (DEST/(name+'.stdout')).open('xb') as stdout, (DEST/(name+'.stderr')).open('xb') as stderr:
        p=subprocess.run([str(CLI),*map(str,args)],env=environment,cwd=SOURCE,stdout=stdout,stderr=stderr,timeout=1800)
    state['commands'].append({'name':name,'exit_code':p.returncode,'expected_exit':expected})
    write('status.json',state)
    assert p.returncode==expected,(name,p.returncode)
    return (DEST/(name+'.stdout')).read_text().strip()
try:
    workspace=Path(command('plan',['plan','--source',source,'--otelc-root',SDK,'--workspace-parent',DEST,'--config',config]))
    ready={r['otelc_function'] for r in json.loads((workspace/'plan.json').read_text())['inventory'] if r['status']=='ready'}
    assert ready==set(fixture.FUNCTIONS),ready
    command('generate',['generate','--workspace',workspace])
    command('run',['run','--workspace',workspace,'--report-dir',DEST/'comparison'],1)
    # The qualifier itself runs in this process, so fix the selected spelling
    # independently of the child's stripped launch environment.
    state['observations']=oracle.check_report(DEST/'comparison/report.json',2,start='both-on',provider=SDK)
    state['source_preserved']=oracle.source_facts(source)==original
    assert state['source_preserved']
    state['status']='passed'
except Exception as error:
    state.update(status='failed',error=repr(error))
finally:
    after=inputs();write('inputs-after.json',after)
    state['preservation']={n:before[n]==after[n] for n in before}
    if not all(state['preservation'].values()):state['status']='failed'
    state.update(seconds=round(time.monotonic()-started,3),finished=datetime.now(timezone.utc).isoformat())
    write('status.json',state)
    print(json.dumps(state,indent=2),flush=True)
    raise SystemExit(0 if state['status']=='passed' else 1)
