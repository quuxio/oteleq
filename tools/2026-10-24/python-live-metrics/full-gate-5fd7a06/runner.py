"""Run a frozen full gate and retain its exact source hold."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import time

ROOT = Path(__file__).resolve().parent
spec = json.loads((ROOT/'command.json').read_text())
source = Path(spec['cwd'])
index = json.loads((ROOT.parent/'source-5fd7a06.json').read_text())
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip() == spec['head']
assert all(hashlib.sha256((source/name).read_bytes()).hexdigest()==digest for name,digest in index['files'].items())
env = {key:value for key,value in os.environ.items() if not key.startswith(('OTEL','OTELEQ','GH_','GITHUB_','SONAR_','AWS_'))}
tools = spec['selected_tools']
rust = Path('/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin')
paths = [rust,*[Path(tools[key]).parent for key in ['OTELC_NODE','OTELC_CLANG','OTELC_JAVA','OTELC_GO']]]
env.update(tools)
env.update(PATH=os.pathsep.join(map(str,paths))+os.pathsep+env.get('PATH',''),
           CARGO_TARGET_DIR=str(ROOT/'target'),PYTHONDONTWRITEBYTECODE='1')
started = time.monotonic()
with (ROOT/'make-check.log').open('xb') as output:
    result = subprocess.run(spec['argv'],cwd=source,env=env,stdout=output,stderr=subprocess.STDOUT)
changed = [name for name,digest in index['files'].items() if hashlib.sha256((source/name).read_bytes()).hexdigest()!=digest]
receipt = {'head':spec['head'],'exit_code':result.returncode,'seconds':round(time.monotonic()-started,3),
           'source_preserved':not changed,'tracked_files_checked':len(index['files']),'changed':changed}
(ROOT/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt))
raise SystemExit(0 if result.returncode==0 and not changed else 1)
