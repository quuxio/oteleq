import datetime,hashlib,json,os,subprocess,sys
from pathlib import Path
p=Path(__file__).resolve().parent
repo=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-rust-compiler')
provider=Path('/Users/sclarke/github/otelc-qualification/2026-10-20/rust-public-compiler/candidate-aca9d5a/provider')
name=sys.argv[1];cli=p/'quux-oteleq'
commands={
 'generated':[sys.executable,str(repo/'tests/qualify_rust_build.py'),'--otelc-root',str(provider),'--report-dir',str(p/'generated'),'--cli',str(cli)],
 'fixed':[sys.executable,str(repo/'examples/capture_otelc_languages.py'),'--otelc-root',str(provider),'--report-dir',str(p/'fixed'),'--language','rust','--comparator',str(cli)],
 'semantics':[sys.executable,str(repo/'tests/qualify_rust_semantics.py'),'--otelc-root',str(provider),'--report-dir',str(p/'semantics'),'--cli',str(cli)]}
command=commands[name];state_path=p/(name+'-state.json');assert not state_path.exists()
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip();assert head=='ed09f136b090c50e062ff2ff678194c959be6c1a'
assert not subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True)
with (p/(name+'.log')).open('wb') as output:
 child=subprocess.Popen(command,cwd=repo,env=os.environ,stdout=output,stderr=subprocess.STDOUT)
 state={'name':name,'source_commit':head,'pid':child.pid,'state':'running','qualifier_sha256':hashlib.sha256(Path(command[1]).read_bytes()).hexdigest(),'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
 state_path.write_text(json.dumps(state,indent=2)+'\n');rc=child.wait()
state.update(state='completed',exit_code=rc,completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_unchanged=head==subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip() and not subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True))
state_path.write_text(json.dumps(state,indent=2)+'\n');print(json.dumps(state),flush=True)
raise SystemExit(rc if state['source_unchanged'] else 1)
