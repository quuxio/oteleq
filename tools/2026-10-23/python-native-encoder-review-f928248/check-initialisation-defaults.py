import json,os,pathlib,subprocess,sys
base=pathlib.Path(__file__).resolve().parent
source=base/'source-f928248'
sys.path.insert(0,str(source))
from ci import build_python_inputs as tooling
binary=tooling.build()
argv0=json.loads(subprocess.check_output([sys.executable,'-I','-S','-c','import json,sys;print(json.dumps(sys.orig_argv[0]))'],text=True))
root=base/('startup-gc-'+sys.implementation.cache_tag)
root.mkdir()
(root/'sitecustomize.py').write_text('''import gc,types
calls=0
patched=[]
seen=set()
def changed(value):
    global calls
    calls+=1
    return len(value)
def patch_defaults(phase,info):
    if phase != 'stop': return
    objects=gc.get_objects()
    functions=[value for value in objects if type(value) is types.FunctionType and value.__module__=='otelc.native.encoder']
    for value in objects:
        if type(value) is dict and id(value) not in seen and value.get('_code_type') is types.CodeType and '_len' in value:
            seen.add(id(value))
            patched.append(any(function.__kwdefaults__ is None for function in functions))
            value['_len']=changed
gc.callbacks.append(patch_defaults)
gc.set_threshold(1,1,1)
''')
app=root/'app.py'
app.write_text('''import _otelc_inputs as native
import sitecustomize as state
def workload(): return 701
try:
    encoded=native.encode(workload.__code__)
except RuntimeError:
    print('refused',state.calls,state.patched)
else:
    print('encoded',state.calls,state.patched,len(encoded))
''')
fd=os.open(root/'input.journal',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
try:
 command=[str(binary),'--origin-observer',str(fd),sys.executable,argv0,'-B',str(app)]
 completed=subprocess.run(command,cwd=root,env={**os.environ,'PYTHONPATH':str(root),'PYTHONDONTWRITEBYTECODE':'1'},pass_fds=(fd,),capture_output=True,timeout=20)
finally: os.close(fd)
record={'exit':completed.returncode,'stdout':completed.stdout.decode(),'stderr':completed.stderr.decode()}
(root/'result.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record))
