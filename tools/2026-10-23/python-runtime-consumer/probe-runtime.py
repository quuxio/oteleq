import argparse,hashlib,json,os,pathlib,subprocess,sys,tarfile
BASE=pathlib.Path(__file__).resolve().parent
REPO=pathlib.Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-python-prepared-runtime')
sys.path[:0]=[str(REPO/'adapters/generation'),str(REPO/'examples')]
import generation,python_provider
SDK=BASE/'provider-880c85f'
APP=BASE/'application'
PYTHONS={'312':'/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python','314':'/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python'}
def worker(label,prime=False):
    folder=BASE/(('prime-' if prime else 'actual-')+label)
    folder.mkdir(mode=0o700)
    tools={'python':pathlib.Path(sys.executable).absolute()}
    env=generation.capture.environment(BASE,tools,'oteleq-python-runtime-'+label,SDK)
    entry={'language':'python','python_backend':'prepared','path':'entry.py','otelc_function':'entry.workload'}
    def prepare(where,endpoint,plain):
        config=where/'policy.toml'; config.write_text(python_provider.policy(entry,endpoint,'oteleq-python-runtime-'+label))
        runtime=where/'runtime'
        cmd=[tools['python'],'-I','-S','-B',SDK/'otelc/cli_bootstrap.py','--config',config,'python','--root',APP,'--entry','entry.py','--runtime',runtime,'--prepare-only']
        if plain:cmd.append('--plain')
        result=generation.execute(cmd,SDK,env,where/'prepare',timeout=180,max_output_bytes=64*1024*1024)
        if result.returncode:raise ValueError('prepare failed '+str(where))
        value=generation.capture.strict_json(result.stdout)
        fixed=[str(tools['python']),'-I','-S','-B',str(SDK/'otelc/python_supervisor.py'),'--runtime',str(runtime)]
        if value['command']!=fixed:raise ValueError('unexpected supervisor command')
        return runtime,fixed
    if prime:
        prepare(folder,'http://127.0.0.1:4318',True)
        return
    rows=[]
    for plain in (True,False):
        current=folder/('baseline' if plain else 'instrumented');current.mkdir(mode=0o700)
        with generation.capture.receiver(response_path=current/'http-responses.json') as (endpoint,bodies,errors):
            runtime,cmd=prepare(current,endpoint,plain)
            result=generation.execute(cmd,SDK,env,current/'owner',timeout=45,record_process=True)
        raw=current/'raw-otlp'; raw.mkdir()
        received=[]
        for index,(route,body) in enumerate(bodies):
            name=str(index)+'.bin';(raw/name).write_bytes(body)
            received.append({'path':route,'file':name,'sha256':hashlib.sha256(body).hexdigest(),'size':len(body)})
        generation.write(current/'raw-otlp.json',received)
        files={}
        for name in ('python-supervisor-start.json','python-application-start.json','python-execution.json','health.json','sdk/python-sdk-spawned.json','sdk/python-sdk-ready.json','sdk/python-sdk-status.json'):
            path=runtime/name
            if path.exists():files[name]=generation.read(path)
        row={'plain':plain,'exit':result.returncode,'stdout':result.stdout.hex(),'stderr':result.stderr.hex(),'http_errors':errors,'bodies':received,'files':files}
        generation.write(current/'probe.json',row)
        rows.append({'plain':plain,'exit':result.returncode,'stdout':result.stdout.hex(),'stderr':result.stderr.hex(),'bodies':len(bodies),'record_keys':{key:sorted(value) for key,value in files.items()}})
    generation.write(folder/'summary.json',rows)
    print(json.dumps(rows))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--worker');p.add_argument('--prime',action='store_true');a=p.parse_args()
    if a.worker:worker(a.worker,a.prime)
    else:
        archive=BASE/'provider-880c85f.tar'
        subprocess.run(['git','archive','--format=tar','-o',str(archive),'880c85f2f16b1ac46cc8214804b872e523c13af9'],cwd='/Users/sclarke/github/otelc',check=True)
        SDK.mkdir()
        with tarfile.open(archive) as stream:stream.extractall(SDK,filter='data')
        APP.mkdir()
        (APP/'entry.py').write_text('''import sys
count=0
class Counter:
    total=0
    def __init__(self,value): self.value=value

def workload(value:int)->int:
    global count
    count+=value
    Counter.total+=1
    instance=Counter(value)
    instance.value+=1
    assert instance.value==6
    return value*2

result=workload(5)
sys.stdout.buffer.write(b"raw\\x00\\xff|"+str(result).encode()+b"|"+str(count).encode()+b"|"+str(Counter.total).encode()+b"\\n")
sys.stderr.buffer.write(b"err\\x00\\xfe\\n")
''')
        for label,python in PYTHONS.items():subprocess.run([python,str(__file__),'--worker',label,'--prime'],check=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
        for label,python in PYTHONS.items():subprocess.run([python,str(__file__),'--worker',label],check=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
