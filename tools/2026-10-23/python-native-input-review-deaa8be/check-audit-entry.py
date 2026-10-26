"""Check that an earlier Python audit callback cannot consume the native arm."""
import hashlib,json,os
from pathlib import Path
import subprocess,sys
root=Path(__file__).parent
source=root/'source'
sys.path.insert(0,str(source))
from ci import build_python_inputs as tooling
from otelc import python_input_journal as journal
folder=root/'audit-entry-check';folder.mkdir()
helper=folder/'reader.c'
helper.write_text('#include <stdio.h>\nint inspect_file(const char *path){FILE *file=fopen(path,"rb");if(!file)return -1;int value=fgetc(file);fclose(file);return value;}\n')
library=folder/'reader.dylib'
subprocess.run([tooling.compiler(),'-dynamiclib',str(helper),'-o',str(library)],check=True)
tool=tooling.build(folder/'tool')
application=folder/'application';application.mkdir()
entry=application/'entry.py'
bootstrap=folder/'bootstrap';bootstrap.mkdir()
(bootstrap/'sitecustomize.py').write_text("""import ctypes,os,sys
from pathlib import Path
library=ctypes.CDLL(os.environ['AUDIT_READER'])
library.inspect_file.argtypes=[ctypes.c_char_p]
library.inspect_file.restype=ctypes.c_int
target=os.environ['AUDIT_ENTRY']
armed=True
def audit(event,args):
    global armed
    if event=='open' and args[0]==target and armed:
        armed=False
        assert library.inspect_file(os.fsencode(target))==112
        Path(target).write_bytes(b"print('after audit')\\n")
sys.addaudithook(audit)
""")
env={**os.environ,'PYTHONPATH':str(bootstrap),'AUDIT_READER':str(library),'AUDIT_ENTRY':str(entry)}
original=b"print('before audit')\n"
entry.write_bytes(original)
baseline=subprocess.run([sys.executable,str(entry)],cwd=application,env=env,capture_output=True,timeout=15)
assert (baseline.returncode,baseline.stdout,baseline.stderr)==(0,b'after audit\n',b''),(baseline.returncode,baseline.stdout,baseline.stderr)
entry.write_bytes(original)
path=folder/'input.journal'
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
argv0=subprocess.check_output([sys.executable,'-I','-S','-c','import sys;print(sys.orig_argv[0])'],text=True).strip()
try:
    process=subprocess.Popen([str(tool),str(fd),sys.executable,argv0,str(entry)],cwd=application,env=env,pass_fds=(fd,),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
finally:os.close(fd)
try:stdout,stderr=process.communicate(timeout=15)
finally:
    if process.poll() is None:process.kill();process.wait(timeout=5)
value=journal.read(path,expected_pid=process.pid)
assert (process.returncode,stdout,stderr)==(baseline.returncode,baseline.stdout,baseline.stderr)
assert value.complete and len(value.sources)==1
assert value.sources[0].content==b"print('after audit')\n",value.sources[0].content
record={'original_source_sha256':hashlib.sha256(original).hexdigest(),'consumed_source_sha256':value.sources[0].sha256,'native_and_candidate_output':'after audit','candidate_exit':process.returncode,'journal_complete':value.complete,'earlier_C_stdio_read_from_Python_audit_hook_did_not_consume_arm':True,'scope':'Controlled pre-entry mutation tests actual-consumed-byte binding and Python-frame guard; not a stable-input/provider admission corpus'}
(folder/'RESULT.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record),flush=True)
