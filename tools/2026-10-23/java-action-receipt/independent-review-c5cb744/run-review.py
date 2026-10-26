from pathlib import Path
import datetime,hashlib,json,os,subprocess
base=Path(__file__).resolve().parent
source=base/'source'
manifest=json.loads((base/'source-identity.json').read_bytes())
owner=Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/java-action-receipt/source-c5cb744')
def seal(root):return {p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in manifest['files']}
assert seal(source)==manifest['files'] and seal(owner)==manifest['files']
cohort=['test_generation_java_action_receipt','test_generation_java_witness','test_generation_java_action','test_generation_java_coverage','test_generation_java_health','test_generation_java_control','test_generation_java_control_receipt','test_generation_java_live','test_generation_java_provider','test_generation_makefile','test_generation_project_tests']
runs=[]
for label,python in [('312','/Users/sclarke/github/otelc-qualification/work/python-prepared-supervisor/.venv/bin/python'),('314','/Users/sclarke/github/otelc-qualification/2026-10-23/python-fixed-launch-recipe/validation314/bin/python')]:
 command=[python,'-m','unittest',*cohort,'-v']
 environment={**os.environ,'PYTHONPATH':'tests:adapters/generation:examples','OTELC_JAVA':'/opt/homebrew/opt/openjdk@21/bin/java','OTELC_JAVAC':'/opt/homebrew/opt/openjdk@21/bin/javac','PATH':'/opt/homebrew/opt/openjdk@21/bin:/opt/homebrew/bin:/usr/bin:/bin'}
 with (base/(label+'.log')).open('wb') as log:r=subprocess.run(command,cwd=source,env=environment,stdout=log,stderr=subprocess.STDOUT)
 runs.append({'label':label,'command':command,'exit_code':r.returncode})
 print(json.dumps(runs[-1]),flush=True)
 assert seal(source)==manifest['files'] and seal(owner)==manifest['files']
 (base/'tests.json').write_text(json.dumps({'head':manifest['head'],'runs':runs,'source_files':len(manifest['files']),'owner_and_private_preserved':True},indent=2)+'\n')
 if r.returncode:raise SystemExit(r.returncode)
