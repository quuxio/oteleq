"""Wait for original runs, then qualify one immutable committed revision."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Lock
import time

BASE = Path(__file__).resolve().parent
INDEX = json.loads((BASE / 'source-2065261.json').read_text())
SOURCE = Path(INDEX['source'])
SDK_INDEX = json.loads((BASE.parent / 'go-scope-provider/sdk-source.json').read_text())
SDK = Path(SDK_INDEX['source'])
SPEC = json.loads((BASE / 'full-gate-2065261/command.json').read_text())
WAIT = json.loads((BASE / 'wait-for-receivers-2065261.json').read_text())
ROOT = BASE / 'matrix-2065261-01'; ROOT.mkdir(mode=0o700)
CLI = BASE / 'target-2065261-public/debug/quux-oteleq'
LOCK = Lock()
STATE = {'status': 'waiting', 'head': INDEX['head'], 'started': datetime.now(timezone.utc).isoformat(),
         'waiting_for': WAIT, 'commands': {}, 'full_gate': 'pending', 'startup_matrix': 'pending'}

def write(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2) + '\n')

def update(**values):
    with LOCK:
        STATE.update(values); write('status.json.tmp', STATE); os.replace(ROOT / 'status.json.tmp', ROOT / 'status.json')

def facts(path):
    info = path.stat()
    return [hashlib.sha256(path.read_bytes()).hexdigest(), info.st_dev, info.st_ino, info.st_mode,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns]

def inputs():
    scope = SDK / 'build/go-upstream-scope'
    manifest = json.loads((scope / 'scope-source.json').read_text())
    tools = json.loads((scope / 'toolchain.json').read_text())
    return {'consumer': {n: facts(SOURCE / n) for n in INDEX['files']},
            'sdk': {n: facts(SDK / n) for n in SDK_INDEX['files']},
            'weaver_source': {n: facts(scope / 'source' / n) for n in manifest['files']},
            'tooling': {str(p): facts(p) for p in [scope / 'scope-source.json', scope / 'toolchain.json',
                *[Path(tools[n]) for n in ('go', 'weaver', 'bundle')], Path(sys.executable).resolve()]}}

environment = {k:v for k,v in os.environ.items() if not k.startswith(('OTEL', 'OTELEQ', 'GH_', 'GITHUB_', 'SONAR_', 'AWS_'))}
rust = Path('/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin')
tools = SPEC['selected_tools']
paths = [rust, *[Path(tools[n]).parent for n in ('OTELC_NODE','OTELC_CLANG','OTELC_JAVA','OTELC_GO')]]
environment.update(tools)
environment.update(PATH=os.pathsep.join(map(str,paths))+os.pathsep+environment.get('PATH',''),
    OTELEQ_PYTHON=sys.executable, OTELC_PYTHON=sys.executable, OTELEQ_CLI=str(CLI), PYTHONDONTWRITEBYTECODE='1')

def execute(name, argv, *, target=None, timeout=10800):
    selected = dict(environment)
    if target is not None:selected['CARGO_TARGET_DIR'] = str(target)
    with LOCK:
        STATE['commands'][name] = {'argv': list(map(str,argv)), 'status': 'running', 'started': datetime.now(timezone.utc).isoformat()}
        write('status.json.tmp', STATE); os.replace(ROOT / 'status.json.tmp', ROOT / 'status.json')
    started = time.monotonic()
    with (ROOT / (name+'.stdout')).open('xb') as out, (ROOT / (name+'.stderr')).open('xb') as err:
        result = subprocess.run(list(map(str,argv)),cwd=SOURCE,env=selected,stdout=out,stderr=err,timeout=timeout)
    with LOCK:
        STATE['commands'][name].update(status='passed' if result.returncode == 0 else 'failed', exit_code=result.returncode,
            seconds=round(time.monotonic()-started,3), finished=datetime.now(timezone.utc).isoformat())
        write('status.json.tmp', STATE); os.replace(ROOT / 'status.json.tmp', ROOT / 'status.json')
    if result.returncode != 0:raise RuntimeError(name+' returned '+str(result.returncode))

def active(row):
    result = subprocess.run(['/bin/ps','-p',str(row['pid']),'-o','lstart=,command='],capture_output=True,text=True,check=False)
    return result.returncode == 0 and result.stdout.strip() == row['identity']

before = None
update()
try:
    while True:
        live = [row for row in WAIT if active(row)]
        update(status='waiting', active_prior_processes=live, observed_at=datetime.now(timezone.utc).isoformat())
        if not live:break
        time.sleep(20)
    prior = {}
    for name in ('untagged','tagged'):
        path=BASE.parent/'go-scope-provider'/('receivers-'+name+'-e765f0d-01')/'status.json'
        prior[name] = json.loads(path.read_text())
    update(status='running', prior_results=prior, previous_failed_attempt=str(BASE/'matrix-65564fe-01/status.json'), phase='freeze-inputs')
    before = inputs(); write('inputs-before.json',before)
    assert all(before['consumer'][n][0] == h for n,h in INDEX['files'].items())
    assert all(before['sdk'][n][0] == h for n,h in SDK_INDEX['files'].items())
    update(phase='full-gate')
    execute('make-check',SPEC['argv'],target=BASE/'full-gate-2065261/target')
    assert inputs()==before
    update(full_gate='passed',phase='public-build')
    execute('cargo-build',[rust/'cargo','build','--locked'],target=BASE/'target-2065261-public',timeout=900)
    cli_facts=facts(CLI);write('cli-input.json',{'path':str(CLI),'facts':cli_facts})
    update(phase='startup-matrix',startup_matrix='running')
    def qualify(start):
        execute(start,[sys.executable,'-B',SOURCE/'tests/qualify_go_controls.py','--otelc-root',SDK,
            '--report-dir',ROOT/start,'--audit-dir',ROOT/('audit-'+start),'--cli',CLI,'--startup-state',start])
        assert facts(CLI)==cli_facts
        return start
    for pair in (('both-on','collection-off'),('emission-off','both-off')):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(qualify,start) for start in pair]
            for future in futures:future.result()
    update(status='passed',phase='complete',startup_matrix='passed')
except Exception as error:
    update(status='failed',error=repr(error))
finally:
    if before is not None:
        after=inputs();write('inputs-after.json',after)
        preserved={name:before[name]==after[name] for name in before}
        update(preservation=preserved)
        if not all(preserved.values()):update(status='failed')
    update(finished=datetime.now(timezone.utc).isoformat())
    print(json.dumps(STATE,indent=2),flush=True)
    raise SystemExit(0 if STATE['status']=='passed' else 1)
