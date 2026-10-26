"""Run the exact frozen consumer gate with explicit tools and owned outputs."""
import datetime,json,subprocess
from pathlib import Path
root=Path(__file__).parent;source=root/'source-03e95bc'
python='/Users/sclarke/github/oteleq-qualification/2026-10-22/node-source-consumer-0f05020/validation-hash-env/bin/python'
node='/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node'
environment={
 'PATH':'/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin:/Users/sclarke/.cargo/bin:/opt/homebrew/opt/openjdk@21/bin:/opt/homebrew/opt/llvm@22/bin:/opt/homebrew/opt/node@24/bin:/opt/homebrew/bin:/usr/bin:/bin',
 'CARGO_HOME':'/Users/sclarke/.cargo','RUSTUP_HOME':'/Users/sclarke/.rustup',
 'CARGO_TARGET_DIR':str(root/'target-gate-03e95bc'),'GOCACHE':str(root/'go-validation-cache'),'GOMODCACHE':str(root/'go-validation-modules'),
 'NPM_CONFIG_CACHE':str(root/'npm-validation-cache'),'PYTHONDONTWRITEBYTECODE':'1',
 'OTELC_NODE':node,'OTELC_JAVA':'/opt/homebrew/opt/openjdk@21/bin/java','OTELC_JAVAC':'/opt/homebrew/opt/openjdk@21/bin/javac',
 'OTELC_CLANG':'/opt/homebrew/opt/llvm@22/bin/clang','OTELC_CLANGXX':'/opt/homebrew/opt/llvm@22/bin/clang++',
 'OTELC_RUSTC':'/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin/rustc',
 'OTELC_GO':'/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go'}
record={'commit':'03e95bca18831cd90028b8cfa3052dbdbfbdbbdd','started_at':datetime.datetime.now(datetime.UTC).isoformat(),'command':['make','check','PYTHON='+python,'NODE='+node],'environment':environment}
(root/'gate-03e95bc.json').write_text(json.dumps(record,indent=2)+'\n')
with (root/'gate-03e95bc.log').open('w') as output:result=subprocess.run(record['command'],cwd=source,env=environment,stdout=output,stderr=subprocess.STDOUT)
record.update(exit_code=result.returncode,finished_at=datetime.datetime.now(datetime.UTC).isoformat());(root/'gate-03e95bc.json').write_text(json.dumps(record,indent=2)+'\n')
raise SystemExit(result.returncode)
