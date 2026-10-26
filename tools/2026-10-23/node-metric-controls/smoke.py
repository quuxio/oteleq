"""Development smoke; this is not a published provider qualification."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
root=Path(sys.argv[1]);root.mkdir(mode=0o700)
cli=Path(sys.argv[2]);provider=Path(sys.argv[3])
source=root/'source';source.mkdir()
(source/'app.cjs').write_text('class Counter { constructor(start){this.value=start;this.self=this;} add(value){this.value+=value;return this.value;} }\n')
config=root/'policy.toml'
config.write_bytes((Path(__file__).parent/'smoke-js/policy.toml').read_bytes())
os.environ.update(OTELEQ_PYTHON=sys.executable,OTELC_NODE='/opt/homebrew/Cellar/node@24/24.21.0_2/bin/node',PYTHONDONTWRITEBYTECODE='1')
def run(name,args):
 result=subprocess.run([str(cli),*map(str,args)],capture_output=True)
 (root/(name+'.stdout')).write_bytes(result.stdout);(root/(name+'.stderr')).write_bytes(result.stderr)
 if result.returncode:raise SystemExit(name+' failed '+str(result.returncode)+'; inspect retained output')
 return result.stdout.decode().strip()
workspace=Path(run('plan',['plan','--source',source,'--otelc-root',provider,'--workspace-parent',root,'--config',config]))
run('generate',['generate','--workspace',workspace])
run('run',['run','--workspace',workspace,'--report-dir',root/'report'])
print(json.dumps({'scope':'uncommitted development smoke only','workspace':str(workspace),'report':str(root/'report/report.json'),'cli_sha256':hashlib.sha256(cli.read_bytes()).hexdigest()}))
