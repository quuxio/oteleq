import json,os,pathlib,subprocess,sys
base=pathlib.Path(__file__).resolve().parent
source=base/'source-f928248'
sys.path.insert(0,str(source))
from ci import build_python_inputs as tooling
binary=tooling.build()
argv0=json.loads(subprocess.check_output([sys.executable,'-I','-S','-c','import json,sys;print(json.dumps(sys.orig_argv[0]))'],text=True))
result=[]
for mode in ('function-only','function-and-snapshot'):
    root=base/(sys.implementation.cache_tag+'-'+mode)
    root.mkdir()
    app=root/'app.py'
    app.write_text('''import gc,types
import _otelc_inputs as native
function=next(value for value in gc.get_objects() if type(value) is types.FunctionType and value.__module__ == 'otelc.native.encoder')
original=function.__kwdefaults__['_len']
snapshots=[value for value in gc.get_objects() if type(value) is dict and value.get('_code_type') is types.CodeType and value.get('_len') is original]
calls=0
def changed(value):
    global calls
    calls+=1
    return len(value)
''' + ('''for value in snapshots:
    value['_len']=changed
''' if mode=='function-and-snapshot' else "function.__kwdefaults__['_len']=changed\n") + '''def workload(): return 701
try:
    encoded=native.encode(workload.__code__)
except RuntimeError:
    print('refused', calls, len(snapshots))
else:
    print('encoded', calls, len(snapshots), len(encoded))
''')
    descriptor=os.open(root/'input.journal',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        command=[str(binary),'--origin-observer',str(descriptor),sys.executable,argv0,'-B',str(app)]
        completed=subprocess.run(command,cwd=root,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},pass_fds=(descriptor,),capture_output=True,timeout=20)
    finally: os.close(descriptor)
    record={'mode':mode,'exit':completed.returncode,'stdout':completed.stdout.decode(),'stderr':completed.stderr.decode()}
    (root/'result.json').write_text(json.dumps(record,indent=2)+'\n')
    result.append(record)
path=base/('default-snapshot-'+sys.implementation.cache_tag+'.json')
path.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
