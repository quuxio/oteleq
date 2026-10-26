import datetime,json,os,subprocess
from pathlib import Path
p=Path(__file__).resolve().parent
repo=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-rust-compiler')
python='/Users/sclarke/github/oteleq-qualification/2026-10-20/pause-for-reboot/otelc-integrated-provider-0419a51-frozen/.venv/bin/python'
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PATH='/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin:/Users/sclarke/.cargo/bin:/opt/homebrew/opt/llvm@22/bin:/opt/homebrew/opt/node@24/bin:/opt/homebrew/bin:/usr/bin:/bin',CARGO_INCREMENTAL='0',CARGO_TARGET_DIR='/Users/sclarke/github/oteleq-qualification/work/java-quality-target',OTELC_JAVA='/opt/homebrew/opt/openjdk@21/bin/java',OTELC_JAVAC='/opt/homebrew/opt/openjdk@21/bin/javac',OTELC_NODE='/opt/homebrew/opt/node@24/bin/node',OTELC_CLANG='/opt/homebrew/opt/llvm@22/bin/clang',OTELC_CLANGXX='/opt/homebrew/opt/llvm@22/bin/clang++',OTELC_RUSTC='/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin/rustc',OTELEQ_PYTHON=python)
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
assert not subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True)
with (p/'full-gate-recovered.log').open('wb') as output:
 child=subprocess.Popen(['make','check','PYTHON='+python,'NODE=/opt/homebrew/opt/node@24/bin/node'],cwd=repo,env=env,stdout=output,stderr=subprocess.STDOUT)
 state={'head':head,'pid':child.pid,'state':'running','started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
 (p/'gate-state.json').write_text(json.dumps(state,indent=2)+'\n')
 rc=child.wait()
state.update(state='completed',exit_code=rc,source_unchanged=head==subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip() and not subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True),completed_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
(p/'gate-state.json').write_text(json.dumps(state,indent=2)+'\n');print(json.dumps(state),flush=True)
raise SystemExit(rc if state['source_unchanged'] else 1)
