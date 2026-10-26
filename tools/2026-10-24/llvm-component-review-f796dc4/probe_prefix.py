"""Check that an explicitly selected ordinary function receives a probe."""
from pathlib import Path
import hashlib,json,os,subprocess,sys
r=Path(__file__).resolve().parent;s=r/'source';index=json.loads((r/'source-index.json').read_text())
def facts():
    out={}
    for n,d in index['files'].items():
        p=s/n;i=p.stat();assert hashlib.sha256(p.read_bytes()).hexdigest()==d
        out[n]=(i.st_dev,i.st_ino,i.st_mode,i.st_size,i.st_mtime_ns,i.st_ctime_ns)
    return out
before=facts();sys.path.insert(0,str(s))
from otelc import llvm_backend as backend
from otelc.config import Policy
work=r/'prefix-before';work.mkdir();plugin=backend.build(work/'plugin',config=Path('/opt/homebrew/opt/llvm@22/bin/llvm-config'))
record=backend.verify(plugin);tools=Path(record['toolchain']['directory']);library=Path(record['plugin']['path'])
app=work/'application.c';app.write_text('#include <stdio.h>\n__attribute__((noinline)) int otelc_workload(void){return 42;}\nint main(void){printf("%d\\n",otelc_workload());return 0;}\n')
policy=Policy.parse({'schema_version':3,'languages':['c'],'functions':{'include':['otelc_workload']}})
assert policy.selection('functions').accepts('otelc_workload')
env=backend.environment(policy,'c');commands=[]
def run(argv, *, environment=None):
    result=subprocess.run(list(map(str,argv)),env=environment,capture_output=True,timeout=120)
    commands.append({'argv':list(map(str,argv)),'exit_code':result.returncode,'stdout':result.stdout.decode(errors='replace'),'stderr':result.stderr.decode(errors='replace')})
    assert result.returncode==0,commands[-1]
    return result
run([tools/'clang',app,'-o',work/'plain'])
run([tools/'clang','-fpass-plugin='+str(library),'-c',app,'-o',work/'woven.o'],environment=env)
run([tools/'clang++','-c',s/'tests/fixtures/llvm/hooks.cpp','-o',work/'hooks.o'])
run([tools/'clang++',work/'woven.o',work/'hooks.o','-pthread','-o',work/'woven'])
plain=run([work/'plain']);woven=run([work/'woven'],environment=dict(os.environ,PROBE_REPORT=str(work/'report.json')))
assert plain.stdout==woven.stdout==b'42\n' and plain.stderr==woven.stderr==b''
actual=json.loads((work/'report.json').read_text());expected={'entries':1,'normal':1,'unwind':0,'invalid':0}
assert facts()==before;backend.verify(plugin)
receipt={'head':index['head'],'source_files_bytes_and_facts_held':len(before),'selected_function':'otelc_workload','common_policy_accepts':True,'plain_and_woven_stdout':'42\n','expected_probe_counts':expected,'actual_probe_counts':actual,'selection_mismatch_reproduced':actual!=expected,'scope':'Ordinary C function compiled stock/woven by the frozen component; diagnostic ABI only, not native SDK or oteleq admission.'}
(work/'commands.json').write_text(json.dumps(commands,indent=2)+'\n');(work/'result.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
