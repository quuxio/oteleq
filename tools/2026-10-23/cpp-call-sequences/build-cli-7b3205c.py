import datetime,hashlib,json,os,shutil,subprocess
from pathlib import Path
root=Path(__file__).parent
short='7b3205c'
source=root/('source-'+short)
seal=json.loads((root/('source-'+short+'.json')).read_text())
env=dict(os.environ,CARGO_TARGET_DIR=str(root/('target-cli-'+short)),PATH='/Users/sclarke/.rustup/toolchains/1.98.1-aarch64-apple-darwin/bin:/Users/sclarke/.cargo/bin:'+os.environ['PATH'])
record={'commit':seal['commit'],'started_at':datetime.datetime.now(datetime.UTC).isoformat()}
with (root/('runtime-build-'+short+'.log')).open('w') as output:
 result=subprocess.run(['cargo','build','--locked'],cwd=source,env=env,stdout=output,stderr=subprocess.STDOUT)
record.update(exit_code=result.returncode,finished_at=datetime.datetime.now(datetime.UTC).isoformat())
if result.returncode==0:
 cli=root/('quux-oteleq-'+short);shutil.copy2(Path(env['CARGO_TARGET_DIR'])/'debug/quux-oteleq',cli);cli.chmod(0o555)
 record['cli_sha256']=hashlib.sha256(cli.read_bytes()).hexdigest()
 assert all(hashlib.sha256((source/name).read_bytes()).hexdigest()==digest for name,digest in seal['files'].items())
 record['source_files_preserved']=len(seal['files'])
(root/('runtime-build-'+short+'.json')).write_text(json.dumps(record,indent=2)+'\n')
raise SystemExit(result.returncode)
