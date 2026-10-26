"""Review test-only wide-argument follow-up using exact unchanged Java products."""
import hashlib,json,os,subprocess,tarfile
from pathlib import Path
root=Path(__file__).parent/'java-handle-wide-review-7796c9c';root.mkdir()
owner=Path('/Users/sclarke/github/otelc-qualification/2026-10-23/java-handle-wide-arguments/source-7796c9c')
meta=json.loads(owner.with_suffix('.json').read_text());archive=owner.with_suffix('.tar');repo=Path('/Users/sclarke/github/otelc')
assert meta['head']=='7796c9cfb46ebdb0c0d54264e22bdb319ef8ae22'
assert hashlib.sha256(archive.read_bytes()).hexdigest()==meta['archive_sha256']==hashlib.sha256(subprocess.check_output(['git','archive','--format=tar',meta['head']],cwd=repo)).hexdigest()
changed=subprocess.check_output(['git','diff','--name-only','6fb166c',meta['head']],cwd=repo,text=True).splitlines()
assert set(changed)=={'docs/java-handle-witness.md','tests/test_java_handle_runtime.py','tests/test_witness.py'}
source=root/'source';source.mkdir()
with tarfile.open(archive) as stream:stream.extractall(source,filter='data')
old=Path('/Users/sclarke/github/oteleq-qualification/2026-10-23/java-handle-runtime-review-6fb166c/source-6fb166c')
oldmeta=json.loads(Path('/Users/sclarke/github/otelc-qualification/2026-10-23/java-handle-runtime/source-6fb166c.json').read_text())
assert all(sha==oldmeta['files'][name] for name,sha in meta['files'].items() if name not in changed)
subprocess.run(['/bin/cp','-cR',str(old/'adapters/java/target'),str(source/'adapters/java')],check=True)
products={p.relative_to(source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (source/'adapters/java/target').glob('*.jar')};assert products
record={'head':meta['head'],'base':'6fb166cf620e8161c6acf5bdf2d2c6336e562ac5','archive_sha256':meta['archive_sha256'],'reviewed_files':changed,'source_files':len(meta['files']),'unchanged_production_tree_verified':True,'java_products_reused_sha256':products,'runs':[]}
env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(source)+os.pathsep+str(source/'tests'),'JAVA_HOME':'/opt/homebrew/opt/openjdk@21','OTELC_JAVA':'/opt/homebrew/opt/openjdk@21/bin/java','OTELC_JAVAC':'/opt/homebrew/opt/openjdk@21/bin/javac'}
runtimes={'312':'/Users/sclarke/github/oteleq-qualification/2026-10-23/python-cli-review-b6dbebb/validation-env-312/bin/python','314':'/Users/sclarke/github/oteleq-qualification/2026-10-23/python-http-review-87ab378/validation-env/bin/python'}
for label,python in runtimes.items():
    log=root/('python-'+label+'.log');cmd=[python,'-m','unittest','test_java_handle_runtime','-v']
    with log.open('wb') as stream:
        result=subprocess.run(cmd,cwd=source,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=180)
    row={'runtime':label,'exit_code':result.returncode,'command':cmd,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()};record['runs'].append(row)
    assert all(hashlib.sha256((folder/name).read_bytes()).hexdigest()==sha for folder in (owner,source) for name,sha in meta['files'].items())
    assert all(hashlib.sha256((source/name).read_bytes()).hexdigest()==sha for name,sha in products.items())
    (root/'tests.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(row),flush=True)
    if result.returncode:raise SystemExit(result.returncode)
